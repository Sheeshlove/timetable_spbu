"""Знакомство: фамилия студента, затем периодичность и время рассылки."""

from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..formatting import format_cohorts, format_subscription
from ..keyboards import (
    BTN_NOTES,
    BTN_SETTINGS,
    BTN_TODAY,
    BTN_WEEK,
    confirm_student_keyboard,
    frequency_keyboard,
    main_menu,
    students_keyboard,
    time_keyboard,
)
from ..roster import Roster, Student
from ..scheduling import FREQUENCY_TITLES, OFF, next_run_at
from ..storage import Storage, Subscription

logger = logging.getLogger(__name__)
router = Router(name="setup")

ASK_LAST_NAME = (
    "Как ваша фамилия? Напишите её — по списку программы я определю ваши когорты "
    "и буду показывать только ваши занятия.\n\n"
    "Можно писать по-русски («Иванов») или латиницей, как в ведомости («Ivanov»)."
)

NOT_FOUND = (
    "Не нашёл такой фамилии в списке 🤔\n\n"
    "Проверьте написание или пришлите фамилию вместе с именем. "
    "Если вас нет в списке, нажмите кнопку — покажу расписание всей программы."
)

NO_COHORTS = (
    "Хорошо, буду показывать расписание всей программы целиком, без деления на когорты.\n"
    "Указать фамилию позже можно в «⚙️ Настройки»."
)


class SetupStates(StatesGroup):
    last_name = State()
    frequency = State()
    send_time = State()


def greeting(settings: Settings) -> str:
    return (
        f"Привет! Я присылаю расписание программы «{escape(settings.program_title)}» "
        "с сайта timetable.spbu.ru.\n\n"
        "Ещё я умею хранить заметки и присылать их в нужный день: /note"
    )


# --- Вход в мастер -----------------------------------------------------


async def ask_last_name(message: Message, state: FSMContext) -> None:
    await state.set_state(SetupStates.last_name)
    await message.answer(ASK_LAST_NAME)


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, storage: Storage, settings: Settings, roster: Roster
) -> None:
    await state.clear()
    subscription = await storage.get_subscription(message.from_user.id)
    if subscription and subscription.student_name:
        await message.answer(
            format_subscription(subscription, settings, roster),
            reply_markup=main_menu(),
        )
        return
    await message.answer(greeting(settings), reply_markup=main_menu())
    await ask_last_name(message, state)


@router.message(Command("setup"))
async def cmd_setup(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ask_last_name(message, state)


@router.callback_query(F.data == "settings:student")
async def restart_wizard(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await ask_last_name(callback.message, state)


# --- Поиск студента ----------------------------------------------------


@router.message(
    SetupStates.last_name,
    F.text
    & ~F.text.startswith("/")
    & ~F.text.in_({BTN_TODAY, BTN_WEEK, BTN_NOTES, BTN_SETTINGS}),
)
async def on_last_name(message: Message, state: FSMContext, roster: Roster) -> None:
    candidates = roster.find(message.text)
    if not candidates:
        await message.answer(NOT_FOUND, reply_markup=students_keyboard([]))
        return

    await state.update_data(
        candidates=[roster.storage_key(student) for student in candidates]
    )

    if len(candidates) == 1:
        student = candidates[0]
        await message.answer(
            f"Это вы? <b>{escape(student.name)}</b>\n\n{format_cohorts(student, roster)}",
            reply_markup=confirm_student_keyboard(),
        )
        return

    labels = [
        f"{student.name} (№{student.number})" if roster.is_namesake(student) else student.name
        for student in candidates
    ]
    await message.answer(
        f"Нашёл {len(candidates)} совпадения — выберите себя:",
        reply_markup=students_keyboard(labels),
    )


@router.callback_query(F.data.startswith("student:"))
async def on_student_picked(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
) -> None:
    choice = callback.data.split(":", 1)[1]
    await callback.answer()

    if choice == "retry":
        await ask_last_name(callback.message, state)
        return

    if choice == "none":
        await _remember_student(callback, state, storage, settings, roster, student=None)
        return

    data = await state.get_data()
    keys = data.get("candidates", [])
    index = int(choice)
    if index >= len(keys):
        await callback.message.answer("Список устарел, напишите фамилию ещё раз.")
        await ask_last_name(callback.message, state)
        return

    student = roster.get(keys[index])
    if student is None:
        await callback.message.answer("Не нашёл эту запись, попробуйте ещё раз.")
        await ask_last_name(callback.message, state)
        return
    await _remember_student(callback, state, storage, settings, roster, student=student)


async def _remember_student(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
    *,
    student: Student | None,
) -> None:
    existing = await storage.get_subscription(callback.from_user.id)
    subscription = existing or Subscription(
        user_id=callback.from_user.id, chat_id=callback.message.chat.id
    )
    subscription.chat_id = callback.message.chat.id
    subscription.student_name = roster.storage_key(student) if student else ""
    subscription.show_all = student is None
    await storage.save_subscription(subscription)

    if student is None:
        await callback.message.answer(NO_COHORTS)
    else:
        await callback.message.answer(
            f"Записал: <b>{escape(student.name)}</b>\n\n{format_cohorts(student, roster)}"
        )

    await ask_frequency(callback.message, state, subscription)


# --- Периодичность и время --------------------------------------------


async def ask_frequency(
    message: Message, state: FSMContext, subscription: Subscription | None
) -> None:
    await state.set_state(SetupStates.frequency)
    await message.answer(
        "Как часто присылать расписание?",
        reply_markup=frequency_keyboard(subscription.frequency if subscription else None),
    )


@router.callback_query(F.data.startswith("freq:"))
async def on_frequency(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
) -> None:
    frequency = callback.data.split(":", 1)[1]
    await callback.answer()
    await state.update_data(frequency=frequency)

    if frequency == OFF:
        await _save(callback, state, storage, settings, roster, frequency=OFF, hour=8, minute=0)
        return

    subscription = await storage.get_subscription(callback.from_user.id)
    await state.set_state(SetupStates.send_time)
    await callback.message.edit_text(
        f"Периодичность: <b>{FREQUENCY_TITLES[frequency]}</b>.\n\n"
        f"В какое время присылать? Часовой пояс — {settings.tz_name}.",
        reply_markup=time_keyboard(subscription.send_hour if subscription else 8),
    )


@router.callback_query(F.data.startswith("time:"))
async def on_time(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
) -> None:
    _, hour, minute = callback.data.split(":", 2)
    await callback.answer()
    data = await state.get_data()
    await _save(
        callback,
        state,
        storage,
        settings,
        roster,
        frequency=data.get("frequency", OFF),
        hour=int(hour),
        minute=int(minute),
    )


async def _save(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
    *,
    frequency: str,
    hour: int,
    minute: int,
) -> None:
    subscription = await storage.get_subscription(callback.from_user.id) or Subscription(
        user_id=callback.from_user.id, chat_id=callback.message.chat.id
    )
    subscription.chat_id = callback.message.chat.id
    subscription.frequency = frequency
    subscription.send_hour = hour
    subscription.send_minute = minute
    subscription.next_run_at = next_run_at(frequency, hour, minute, settings.tz)
    await storage.save_subscription(subscription)
    await state.clear()

    await callback.message.edit_text(
        "Готово! ✅\n\n" + format_subscription(subscription, settings, roster)
    )
    await callback.message.answer(
        "Расписание можно посмотреть в любой момент кнопками ниже.",
        reply_markup=main_menu(),
    )
