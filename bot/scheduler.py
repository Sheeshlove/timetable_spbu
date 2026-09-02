"""Фоновая рассылка: расписание по расписанию и заметки в назначенный день.

Вместо отдельной задачи на каждого пользователя работает один «тикер»: раз в
минуту он спрашивает у базы, кому уже пора отправлять. Такой подход переживает
перезапуск бота (состояние живёт в SQLite, а не в памяти) и не теряет
рассылки, пропущенные во время простоя.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from .config import Settings
from .formatting import digest_header, format_note_reminder, format_schedule, split_message
from .handlers.schedule import apply_cohorts
from .i18n import Translator
from .roster import Roster
from .scheduling import next_run_at, period_for
from .storage import Note, Storage, Subscription
from .timetable import TimetableClient, TimetableError

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
RETRY_MINUTES = 15

OK = "ok"
FAILED = "failed"
BLOCKED = "blocked"


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
            await self.storage.set_next_run(
                subscription.user_id,
                moment.replace(second=0, microsecond=0) + timedelta(minutes=RETRY_MINUTES),
            )
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
