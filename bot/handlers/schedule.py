"""Показ расписания по запросу и меню настроек."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..formatting import (
    format_cohorts,
    format_schedule,
    format_subscription,
    human_date,
    now_local,
    split_message,
)
from ..i18n import TEXTS, Translator
from ..languages import filter_events
from ..keyboards import frequency_keyboard, settings_keyboard, time_keyboard
from ..roster import Roster
from ..roster.filtering import educator_value, filter_schedule
from ..storage import Storage, Subscription
from ..timetable import Schedule, TimetableClient, TimetableError
from ..timetable.models import Day

logger = logging.getLogger(__name__)
router = Router(name="schedule")


def menu_button(key: str):
    """Фильтр по подписи кнопки главного меню на любом языке."""
    return F.text.in_({TEXTS[lang][key] for lang in TEXTS})


def apply_cohorts(
    schedule: Schedule, subscription: Subscription, roster: Roster, t: Translator
) -> tuple[Schedule, str]:
    """Оставляет занятия студента: его когорты и его язык.

    Возвращает отфильтрованное расписание и подпись под ним.
    """
    notes: list[str] = []
    if subscription.show_all:
        return schedule, ""

    if subscription.student_name:
        student = roster.get(subscription.student_name)
        if student is None:
            logger.info("Студент %s не найден в списке", subscription.student_name)
            notes.append(t("not_in_roster"))
        else:
            schedule, report = filter_schedule(
                schedule, student, roster, subscription.subgroup
            )
            if report.hidden:
                notes.append(t("hidden_note", count=report.hidden))

    schedule, hidden_languages = _apply_language(schedule, subscription)
    if hidden_languages:
        notes.append(t("hidden_language_note", count=hidden_languages))

    return schedule, " ".join(notes)


def show_subgroup_button(subscription: Subscription, roster: Roster) -> bool:
    """Есть ли смысл в пункте «Моя подгруппа».

    Он нужен там, где группу задаёт преподаватель: по ведомости она не
    вычисляется, а на сайте подгрупп у преподавателя может быть несколько.
    """
    if subscription.show_all or not subscription.student_name:
        return False
    student = roster.get(subscription.student_name)
    return bool(student and educator_value(student, roster))


def _apply_language(schedule: Schedule, subscription: Subscription) -> tuple[Schedule, int]:
    """Убирает языковые пары чужих языков и групп."""
    if not subscription.language_course:
        return schedule, 0
    days = []
    hidden = 0
    for day in schedule.days:
        kept, count = filter_events(
            day.events, subscription.language_course, subscription.language_teacher
        )
        hidden += count
        days.append(Day(date=day.date, title=day.title, events=kept))
    return (
        Schedule(
            group_id=schedule.group_id,
            group_name=schedule.group_name,
            days=days,
            url=schedule.url,
        ),
        hidden,
    )


async def send_schedule(
    message: Message,
    storage: Storage,
    client: TimetableClient,
    settings: Settings,
    roster: Roster,
    t: Translator,
    start: date,
    end: date,
    header: str,
) -> None:
    subscription = await storage.get_subscription(message.from_user.id)
    if subscription is None:
        await message.answer(t("not_configured"))
        return
    notice = await message.answer(t("loading"))
    try:
        schedule = await client.schedule(
            settings.group_id, start, end, settings.division_alias, t.lang
        )
    except TimetableError as error:
        logger.warning("Расписание не загрузилось: %s", error)
        await notice.edit_text(t("site_down"))
        return
    if not schedule.group_name:
        schedule.group_name = settings.program_title

    schedule, footer = apply_cohorts(schedule, subscription, roster, t)
    chunks = split_message(format_schedule(schedule, t, header, footer))
    await notice.edit_text(chunks[0], disable_web_page_preview=True)
    for chunk in chunks[1:]:
        await message.answer(chunk, disable_web_page_preview=True)


@router.message(Command("today"))
@router.message(menu_button("btn_today"))
async def cmd_today(
    message: Message,
    storage: Storage,
    client: TimetableClient,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    # Дата берётся в часовом поясе рассылки, а не в поясе сервера: иначе
    # ночью «сегодня» съедет на сутки.
    today = now_local(settings.tz).date()
    await send_schedule(
        message, storage, client, settings, roster, t, today, today,
        t("header_day", date=human_date(today, t)),
    )


@router.message(Command("tomorrow"))
async def cmd_tomorrow(
    message: Message,
    storage: Storage,
    client: TimetableClient,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    day = now_local(settings.tz).date() + timedelta(days=1)
    await send_schedule(
        message, storage, client, settings, roster, t, day, day,
        t("header_day", date=human_date(day, t)),
    )


@router.message(Command("week"))
@router.message(menu_button("btn_week"))
async def cmd_week(
    message: Message,
    storage: Storage,
    client: TimetableClient,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    today = now_local(settings.tz).date()
    monday = today - timedelta(days=today.weekday())
    await _send_week(message, storage, client, settings, roster, t, monday)


@router.message(Command("nextweek"))
async def cmd_next_week(
    message: Message,
    storage: Storage,
    client: TimetableClient,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    today = now_local(settings.tz).date()
    monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
    await _send_week(message, storage, client, settings, roster, t, monday)


async def _send_week(
    message: Message,
    storage: Storage,
    client: TimetableClient,
    settings: Settings,
    roster: Roster,
    t: Translator,
    monday: date,
) -> None:
    sunday = monday + timedelta(days=6)
    await send_schedule(
        message, storage, client, settings, roster, t, monday, sunday,
        t("header_week", start=f"{monday:%d.%m}", end=f"{sunday:%d.%m}"),
    )


@router.message(Command("cohorts"))
async def cmd_cohorts(
    message: Message, storage: Storage, roster: Roster, t: Translator
) -> None:
    subscription = await storage.get_subscription(message.from_user.id)
    student = (
        roster.get(subscription.student_name)
        if subscription and subscription.student_name
        else None
    )
    if student is None:
        await message.answer(t("cohorts_unknown"))
        return
    await message.answer(format_cohorts(student, roster, t))


@router.message(Command("settings"))
@router.message(menu_button("btn_settings"))
async def cmd_settings(
    message: Message, storage: Storage, settings: Settings, roster: Roster, t: Translator
) -> None:
    subscription = await storage.get_subscription(message.from_user.id)
    if subscription is None:
        await message.answer(t("not_configured"))
        return
    await message.answer(
        format_subscription(subscription, settings, roster, t),
        reply_markup=settings_keyboard(
            t,
            subscription.show_all,
            subscription.notify_changes,
            show_subgroup_button(subscription, roster),
        ),
    )


@router.callback_query(F.data == "settings:freq")
async def on_settings_frequency(
    callback: CallbackQuery, storage: Storage, t: Translator
) -> None:
    subscription = await storage.get_subscription(callback.from_user.id)
    await callback.answer()
    await callback.message.answer(
        t("ask_frequency"),
        reply_markup=frequency_keyboard(
            t, subscription.frequency if subscription else None
        ),
    )


@router.callback_query(F.data == "settings:time")
async def on_settings_time(
    callback: CallbackQuery,
    storage: Storage,
    settings: Settings,
    state: FSMContext,
    t: Translator,
) -> None:
    from .setup import SetupStates  # локальный импорт: избегаем цикла модулей

    subscription = await storage.get_subscription(callback.from_user.id)
    if subscription is None:
        await callback.answer(t("setup_first"), show_alert=True)
        return
    await callback.answer()
    await state.update_data(frequency=subscription.frequency)
    await state.set_state(SetupStates.send_time)
    await callback.message.answer(
        t("ask_time_short", tz=settings.tz_name),
        reply_markup=time_keyboard(subscription.send_hour),
    )


@router.callback_query(F.data == "settings:filter")
async def on_settings_filter(
    callback: CallbackQuery,
    storage: Storage,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    subscription = await storage.get_subscription(callback.from_user.id)
    if subscription is None:
        await callback.answer(t("setup_first"), show_alert=True)
        return
    subscription.show_all = not subscription.show_all
    await storage.save_subscription(subscription)
    await callback.answer(
        t("toast_show_all") if subscription.show_all else t("toast_show_mine")
    )
    await callback.message.edit_text(
        format_subscription(subscription, settings, roster, t),
        reply_markup=settings_keyboard(
            t,
            subscription.show_all,
            subscription.notify_changes,
            show_subgroup_button(subscription, roster),
        ),
    )


@router.callback_query(F.data == "settings:notify")
async def on_settings_notify(
    callback: CallbackQuery,
    storage: Storage,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    subscription = await storage.get_subscription(callback.from_user.id)
    if subscription is None:
        await callback.answer(t("setup_first"), show_alert=True)
        return
    subscription.notify_changes = not subscription.notify_changes
    # Слепок сохраняет расписание на момент выключения; за время паузы оно
    # успеет измениться само собой, и вываливать эти изменения при повторном
    # включении незачем. Проще забыть слепок и снять новый на ближайшем такте.
    await storage.clear_snapshot(subscription.user_id)
    subscription.next_check_at = None
    await storage.save_subscription(subscription)
    await callback.answer(
        t("toast_notify_on") if subscription.notify_changes else t("toast_notify_off")
    )
    await callback.message.edit_text(
        format_subscription(subscription, settings, roster, t),
        reply_markup=settings_keyboard(
            t,
            subscription.show_all,
            subscription.notify_changes,
            show_subgroup_button(subscription, roster),
        ),
    )


@router.message(Command("stop"))
async def cmd_stop(message: Message, storage: Storage, t: Translator) -> None:
    await storage.delete_subscription(message.from_user.id)
    await message.answer(t("stopped"))
