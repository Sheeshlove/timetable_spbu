"""Фоновая рассылка: расписание по расписанию и заметки в назначенный день.

Вместо отдельной задачи на каждого пользователя работает один «тикер»: раз в
минуту он спрашивает у базы, кому уже пора отправлять. Такой подход переживает
перезапуск бота (состояние живёт в SQLite, а не в памяти) и не теряет
рассылки, пропущенные во время простоя.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from .changes import Slot, compare, overlap, take_snapshot
from .config import Settings
from .formatting import (
    digest_header,
    format_changes,
    format_note_reminder,
    format_schedule,
    split_message,
)
from .handlers.schedule import apply_cohorts
from .i18n import Translator
from .roster import Roster
from .scheduling import next_run_at, period_for
from .storage import Note, Storage, Subscription
from .timetable import Schedule, TimetableClient, TimetableError

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
RETRY_MINUTES = 15

# Об изменениях сообщаем только днём: ночью такое сообщение бесполезно,
# а разбудить может. За окном тишины проверка откладывается до утра.
QUIET_FROM_HOUR = 22
QUIET_UNTIL_HOUR = 8

OK = "ok"
FAILED = "failed"
BLOCKED = "blocked"


def filter_key(subscription: Subscription) -> str:
    """Настройки, от которых зависит расписание студента.

    Если ключ изменился, старый слепок сравнивать не с чем: студент сам
    поменял фильтр, а не расписание поменялось.
    """
    return "|".join(
        (
            subscription.student_name,
            str(int(subscription.show_all)),
            subscription.language_course,
            subscription.language_teacher,
            subscription.lang,
        )
    )


class Scheduler:
    def __init__(
        self,
        bot: Bot,
        storage: Storage,
        client: TimetableClient,
        settings: Settings,
        roster: Roster,
        *,
        tick_seconds: int = TICK_SECONDS,
    ) -> None:
        self.bot = bot
        self.storage = storage
        self.client = client
        self.settings = settings
        self.roster = roster
        self.tick_seconds = tick_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — тикер не должен умирать от одной ошибки
                logger.exception("Ошибка в цикле рассылки")
            await asyncio.sleep(self.tick_seconds)

    async def tick(self, now: datetime | None = None) -> int:
        """Один проход: отправляет всё, чему подошёл срок. Возвращает счётчик."""
        moment = now or datetime.now(timezone.utc)
        sent = 0
        for subscription in await self.storage.due_subscriptions(moment):
            sent += await self._send_digest(subscription, moment)
        for note in await self.storage.due_notes(moment):
            sent += await self._send_note(note)
        sent += await self.check_changes(moment)
        return sent

    # --- Расписание ----------------------------------------------------

    async def _send_digest(self, subscription: Subscription, moment: datetime) -> int:
        t = Translator(subscription.lang)
        start, end = period_for(subscription.frequency, moment, self.settings.tz)
        try:
            schedule = await self.client.schedule(
                self.settings.group_id, start, end, self.settings.division_alias, t.lang
            )
        except TimetableError as error:
            # Сайт молчит — не теряем слот, пробуем ещё раз через 15 минут.
            logger.warning("Рассылка %s отложена: %s", subscription.user_id, error)
            await self.storage.set_next_run(subscription.user_id, self._retry_at(moment))
            return 0

        if not schedule.group_name:
            schedule.group_name = self.settings.program_title
        schedule, footer = apply_cohorts(schedule, subscription, self.roster, t)
        text = format_schedule(
            schedule, t, digest_header(subscription.frequency, start, end, t), footer
        )
        status = await self._deliver(subscription.chat_id, text, user_id=subscription.user_id)
        if status == BLOCKED:
            # Рассылка уже снята в _deliver, следующий запуск не назначаем.
            return 0

        await self.storage.set_next_run(
            subscription.user_id,
            next_run_at(
                subscription.frequency,
                subscription.send_hour,
                subscription.send_minute,
                self.settings.tz,
                after=moment,
            ),
        )
        return 1 if status == OK else 0

    # --- Изменения в расписании ----------------------------------------

    async def check_changes(self, moment: datetime) -> int:
        """Сверяет расписание студентов с прошлым слепком и шлёт разницу."""
        due = await self.storage.due_for_check(moment)
        if not due:
            return 0

        wake = self._quiet_until(moment)
        if wake is not None:
            # Ночь: ни проверять, ни тем более писать не нужно.
            for subscription in due:
                await self.storage.set_next_check(subscription.user_id, wake)
            return 0

        today = moment.astimezone(self.settings.tz).date()
        window = (today, today + timedelta(days=self.settings.change_window_days))
        # Группа у всех одна, поэтому за расписанием ходим один раз на язык.
        loaded: dict[str, Schedule | None] = {}
        sent = 0
        for subscription in due:
            schedule = await self._load_window(loaded, subscription.lang, window)
            if schedule is None:
                # Сайт молчит — слепок не трогаем, вернёмся через 15 минут.
                await self.storage.set_next_check(
                    subscription.user_id, self._retry_at(moment)
                )
                continue
            sent += await self._check_one(subscription, schedule, window, moment)
        return sent

    async def _load_window(
        self,
        cache: dict[str, Schedule | None],
        lang: str,
        window: tuple[date, date],
    ) -> Schedule | None:
        if lang in cache:
            return cache[lang]
        try:
            schedule = await self.client.schedule(
                self.settings.group_id,
                window[0],
                window[1],
                self.settings.division_alias,
                lang,
            )
        except TimetableError as error:
            logger.warning("Проверка изменений отложена: %s", error)
            schedule = None
        cache[lang] = schedule
        return schedule

    async def _check_one(
        self,
        subscription: Subscription,
        schedule: Schedule,
        window: tuple[date, date],
        moment: datetime,
    ) -> int:
        t = Translator(subscription.lang)
        mine, _ = apply_cohorts(schedule, subscription, self.roster, t)
        slots = take_snapshot(mine)
        key = filter_key(subscription)
        previous = await self.storage.get_snapshot(subscription.user_id)

        # Сравнивать честно можно только по пересечению окон: окно каждый день
        # уезжает вперёд, и вчерашние пары иначе выглядели бы отменёнными.
        common = (
            overlap(previous.window, window)
            if previous is not None and previous.filter_key == key
            else None
        )
        # Первая проверка или сменившиеся настройки фильтра: сравнивать не с
        # чем — запоминаем расписание молча, чтобы не выдать его за изменение.
        if common is None:
            await self._remember(subscription.user_id, key, window, slots, moment)
            return 0

        diff = compare(previous.slots, slots, common)
        if diff.is_empty:
            await self._remember(subscription.user_id, key, window, slots, moment)
            return 0

        logger.info("У %s изменилось занятий: %s", subscription.user_id, diff.count)
        status = await self._deliver(
            subscription.chat_id,
            format_changes(diff, t),
            user_id=subscription.user_id,
        )
        if status == BLOCKED:
            # Писать больше некуда: снимаем слежение, иначе бот будет ходить
            # на сайт ради сообщений, которые никто не получит.
            await self.storage.set_notify_changes(subscription.user_id, False)
            return 0
        if status == FAILED:
            # Студент про изменения не узнал — слепок оставляем прежним,
            # чтобы рассказать о них на следующей попытке.
            await self.storage.set_next_check(subscription.user_id, self._retry_at(moment))
            return 0

        await self._remember(subscription.user_id, key, window, slots, moment)
        return 1

    async def _remember(
        self,
        user_id: int,
        key: str,
        window: tuple[date, date],
        slots: list[Slot],
        moment: datetime,
    ) -> None:
        await self.storage.save_snapshot(user_id, key, window, slots)
        await self.storage.set_next_check(user_id, self._next_check(moment))

    def _quiet_until(self, moment: datetime) -> datetime | None:
        """Когда закончится ночь. None — сейчас день, можно проверять."""
        local = moment.astimezone(self.settings.tz)
        if QUIET_UNTIL_HOUR <= local.hour < QUIET_FROM_HOUR:
            return None
        day = local.date()
        if local.hour >= QUIET_FROM_HOUR:
            day += timedelta(days=1)
        morning = datetime.combine(
            day, time(hour=QUIET_UNTIL_HOUR), tzinfo=self.settings.tz
        )
        return morning.astimezone(timezone.utc)

    def _next_check(self, moment: datetime) -> datetime:
        return moment.replace(second=0, microsecond=0) + timedelta(
            hours=self.settings.change_check_hours
        )

    def _retry_at(self, moment: datetime) -> datetime:
        return moment.replace(second=0, microsecond=0) + timedelta(minutes=RETRY_MINUTES)

    # --- Заметки -------------------------------------------------------

    async def _send_note(self, note: Note) -> int:
        subscription = await self.storage.get_subscription(note.user_id)
        t = Translator(subscription.lang if subscription else "ru")
        status = await self._deliver(
            note.chat_id,
            format_note_reminder(note, self.settings.tz, t),
            user_id=note.user_id,
        )
        if status == OK:
            await self.storage.mark_note_sent(note.id)
            return 1
        if status == BLOCKED:
            # Доставить некуда: закрываем заметку, иначе она будет повторяться
            # на каждом такте вечно.
            logger.info("Заметка %s закрыта: бот заблокирован", note.id)
            await self.storage.mark_note_sent(note.id)
        return 0

    # --- Отправка ------------------------------------------------------

    async def _deliver(self, chat_id: int, text: str, *, user_id: int) -> str:
        for chunk in split_message(text):
            try:
                await self.bot.send_message(chat_id, chunk, disable_web_page_preview=True)
            except TelegramRetryAfter as error:
                await asyncio.sleep(error.retry_after + 1)
                try:
                    await self.bot.send_message(chat_id, chunk, disable_web_page_preview=True)
                except Exception:  # noqa: BLE001
                    logger.warning("Не доставили сообщение в чат %s", chat_id, exc_info=True)
                    return FAILED
            except TelegramForbiddenError:
                # Пользователь заблокировал бота — выключаем рассылку.
                logger.info("Пользователь %s заблокировал бота, отключаю рассылку", user_id)
                await self.storage.set_next_run(user_id, None)
                return BLOCKED
            except Exception:  # noqa: BLE001
                logger.warning("Не доставили сообщение в чат %s", chat_id, exc_info=True)
                return FAILED
        return OK
