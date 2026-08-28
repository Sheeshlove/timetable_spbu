"""Показ расписания по запросу и меню настроек."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..formatting import (
    format_schedule,
    format_subscription,
    human_date,
    now_local,
    split_message,
)
from ..keyboards import (
    BTN_SETTINGS,
    BTN_TODAY,
    BTN_WEEK,
    frequency_keyboard,
    settings_keyboard,
    time_keyboard,
)
from ..storage import Storage
from ..timetable import TimetableClient, TimetableError

logger = logging.getLogger(__name__)
router = Router(name="schedule")

NOT_CONFIGURED = "Сначала выберите группу — это займёт полминуты: /setup"


async def send_schedule(
    message: Message,
    storage: Storage,
    client: TimetableClient,
    start: date,
    end: date,
    header: str,
) -> None:
    subscription = await storage.get_subscription(message.from_user.id)
    if subscription is None or not subscription.group_id:
        await message.answer(NOT_CONFIGURED)
        return
    notice = await message.answer("Смотрю расписание…")
    try:
        schedule = await client.schedule(
            subscription.group_id, start, end, subscription.division_alias
        )
    except TimetableError as error:
        logger.warning("Расписание не загрузилось: %s", error)
        await notice.edit_text("Сайт расписания не отвечает 😕 Попробуйте позже.")
        return
    if not schedule.group_name:
        schedule.group_name = subscription.group_name
    chunks = split_message(format_schedule(schedule, header))
    await notice.edit_text(chunks[0], disable_web_page_preview=True)
    for chunk in chunks[1:]:
        await message.answer(chunk, disable_web_page_preview=True)


@router.message(Command("today"))
@router.message(F.text == BTN_TODAY)
async def cmd_today(
    message: Message, storage: Storage, client: TimetableClient, settings: Settings
) -> None:
    # Дата берётся в часовом поясе рассылки, а не в поясе сервера: иначе
    # ночью «сегодня» съедет на сутки.
    today = now_local(settings.tz).date()
    await send_schedule(
        message, storage, client, today, today, f"Расписание на {human_date(today)}"
    )


@router.message(Command("tomorrow"))
async def cmd_tomorrow(
    message: Message, storage: Storage, client: TimetableClient, settings: Settings
) -> None:
    day = now_local(settings.tz).date() + timedelta(days=1)
    await send_schedule(
        message, storage, client, day, day, f"Расписание на {human_date(day)}"
    )


@router.message(Command("week"))
@router.message(F.text == BTN_WEEK)
async def cmd_week(
    message: Message, storage: Storage, client: TimetableClient, settings: Settings
) -> None:
    today = now_local(settings.tz).date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    await send_schedule(
        message,
        storage,
        client,
        monday,
        sunday,
        f"Расписание на неделю {monday:%d.%m} — {sunday:%d.%m}",
    )


@router.message(Command("nextweek"))
async def cmd_next_week(
    message: Message, storage: Storage, client: TimetableClient, settings: Settings
) -> None:
    today = now_local(settings.tz).date()
    monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
    sunday = monday + timedelta(days=6)
    await send_schedule(
        message,
        storage,
        client,
        monday,
        sunday,
        f"Расписание на неделю {monday:%d.%m} — {sunday:%d.%m}",
    )


@router.message(Command("settings"))
@router.message(F.text == BTN_SETTINGS)
async def cmd_settings(message: Message, storage: Storage, settings: Settings) -> None:
    subscription = await storage.get_subscription(message.from_user.id)
    if subscription is None:
        await message.answer(NOT_CONFIGURED)
        return
    await message.answer(
        format_subscription(subscription, settings.tz), reply_markup=settings_keyboard()
    )


@router.callback_query(F.data == "settings:freq")
async def on_settings_frequency(callback: CallbackQuery, storage: Storage) -> None:
    subscription = await storage.get_subscription(callback.from_user.id)
    await callback.answer()
    await callback.message.answer(
        "Как часто присылать расписание?",
        reply_markup=frequency_keyboard(subscription.frequency if subscription else None),
    )


@router.callback_query(F.data == "settings:time")
async def on_settings_time(
    callback: CallbackQuery, storage: Storage, settings: Settings, state
) -> None:
    from .setup import SetupStates  # локальный импорт: избегаем цикла модулей

    subscription = await storage.get_subscription(callback.from_user.id)
    if subscription is None:
        await callback.answer("Сначала /setup", show_alert=True)
        return
    await callback.answer()
    await state.update_data(frequency=subscription.frequency)
    await state.set_state(SetupStates.send_time)
    await callback.message.answer(
        f"В какое время присылать? Часовой пояс — {settings.tz_name}.",
        reply_markup=time_keyboard(subscription.send_hour),
    )


@router.message(Command("stop"))
async def cmd_stop(message: Message, storage: Storage) -> None:
    await storage.delete_subscription(message.from_user.id)
    await message.answer("Рассылка выключена, настройки удалены. Вернуться: /setup")
