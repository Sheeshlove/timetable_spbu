"""Знакомство: язык, фамилия студента, затем периодичность и время рассылки."""

from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..formatting import format_cohorts, format_subscription, frequency_title
from ..i18n import Translator, menu_texts
from ..keyboards import (
    confirm_student_keyboard,
    frequency_keyboard,
    language_keyboard,
    main_menu,
    students_keyboard,
    time_keyboard,
)
from ..roster import Roster, Student
from ..scheduling import OFF, next_run_at
from ..storage import Storage, Subscription

logger = logging.getLogger(__name__)
router = Router(name="setup")


class SetupStates(StatesGroup):
    language = State()
    last_name = State()
    frequency = State()
    send_time = State()


# --- Язык --------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    await state.clear()
    subscription = await storage.get_subscription(message.from_user.id)
    if subscription and subscription.student_name:
        await message.answer(
            format_subscription(subscription, settings, roster, t),
            reply_markup=main_menu(t),
        )
        return
    await state.set_state(SetupStates.language)
    await message.answer(t("choose_language"), reply_markup=language_keyboard(t.lang))


@router.message(Command("language"))
@router.callback_query(F.data == "settings:language")
async def choose_language(
    event: Message | CallbackQuery, state: FSMContext, t: Translator
) -> None:
    message = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()
    await state.set_state(SetupStates.language)
    await message.answer(t("choose_language"), reply_markup=language_keyboard(t.lang))


@router.callback_query(F.data.startswith("lang:"))
async def on_language(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
) -> None:
    lang = callback.data.split(":", 1)[1]
    t = Translator(lang)
    await callback.answer()
    await state.update_data(lang=lang)

    subscription = await storage.get_subscription(callback.from_user.id)
    if subscription is not None:
        subscription.lang = lang
        await storage.save_subscription(subscription)

    await callback.message.edit_text(f"{t('language_saved')}")

    if subscription is not None and subscription.student_name:
        await callback.message.answer(
            format_subscription(subscription, settings, roster, t),
            reply_markup=main_menu(t),
        )
        await state.clear()
        return

    await callback.message.answer(
        t("greeting", program=escape(settings.program_title)), reply_markup=main_menu(t)
    )
    await ask_last_name(callback.message, state, t)


# --- Фамилия -----------------------------------------------------------


async def ask_last_name(message: Message, state: FSMContext, t: Translator) -> None:
    await state.set_state(SetupStates.last_name)
    await message.answer(t("ask_last_name"))


@router.message(Command("setup"))
async def cmd_setup(message: Message, state: FSMContext, t: Translator) -> None:
    await state.clear()
    await ask_last_name(message, state, t)


@router.callback_query(F.data == "settings:student")
async def restart_wizard(callback: CallbackQuery, state: FSMContext, t: Translator) -> None:
    await callback.answer()
    await state.clear()
    await ask_last_name(callback.message, state, t)


@router.message(
    SetupStates.last_name,
    F.text & ~F.text.startswith("/") & ~F.text.in_(menu_texts()),
)
async def on_last_name(
    message: Message, state: FSMContext, roster: Roster, t: Translator
) -> None:
    candidates = roster.find(message.text)
    if not candidates:
        await message.answer(t("not_found"), reply_markup=students_keyboard([], t))
        return

    await state.update_data(
        candidates=[roster.storage_key(student) for student in candidates]
    )

    if len(candidates) == 1:
        student = candidates[0]
        await message.answer(
            t("is_it_you", name=escape(student.name))
            + "\n\n"
            + format_cohorts(student, roster, t),
            reply_markup=confirm_student_keyboard(t),
        )
        return

    labels = [
        f"{student.name} (№{student.number})" if roster.is_namesake(student) else student.name
        for student in candidates
    ]
    await message.answer(t("several_matches"), reply_markup=students_keyboard(labels, t))


@router.callback_query(F.data.startswith("student:"))
async def on_student_picked(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    choice = callback.data.split(":", 1)[1]
    await callback.answer()

    if choice == "retry":
        await ask_last_name(callback.message, state, t)
        return

    if choice == "none":
        await _remember_student(callback, state, storage, roster, t, student=None)
        return

    data = await state.get_data()
    keys = data.get("candidates", [])
    index = int(choice)
    if index >= len(keys):
        await callback.message.answer(t("list_outdated"))
        await ask_last_name(callback.message, state, t)
        return

    student = roster.get(keys[index])
    if student is None:
        await callback.message.answer(t("record_not_found"))
        await ask_last_name(callback.message, state, t)
        return
    await _remember_student(callback, state, storage, roster, t, student=student)


async def _remember_student(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    roster: Roster,
    t: Translator,
    *,
    student: Student | None,
) -> None:
    data = await state.get_data()
    existing = await storage.get_subscription(callback.from_user.id)
    subscription = existing or Subscription(
        user_id=callback.from_user.id, chat_id=callback.message.chat.id
    )
    subscription.chat_id = callback.message.chat.id
    subscription.lang = data.get("lang") or subscription.lang or t.lang
    subscription.student_name = roster.storage_key(student) if student else ""
    subscription.show_all = student is None
    await storage.save_subscription(subscription)

    if student is None:
        await callback.message.answer(t("no_cohorts"))
    else:
        await callback.message.answer(
            t("saved_student", name=escape(student.name))
            + "\n\n"
            + format_cohorts(student, roster, t)
        )

    await ask_frequency(callback.message, state, subscription, t)


# --- Периодичность и время --------------------------------------------


async def ask_frequency(
    message: Message, state: FSMContext, subscription: Subscription | None, t: Translator
) -> None:
    await state.set_state(SetupStates.frequency)
    await message.answer(
        t("ask_frequency"),
        reply_markup=frequency_keyboard(
            t, subscription.frequency if subscription else None
        ),
    )


@router.callback_query(F.data.startswith("freq:"))
async def on_frequency(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    frequency = callback.data.split(":", 1)[1]
    await callback.answer()
    await state.update_data(frequency=frequency)

    if frequency == OFF:
        await _save(
            callback, state, storage, settings, roster, t, frequency=OFF, hour=8, minute=0
        )
        return

    subscription = await storage.get_subscription(callback.from_user.id)
    await state.set_state(SetupStates.send_time)
    await callback.message.edit_text(
        t("ask_time", frequency=frequency_title(frequency, t), tz=settings.tz_name),
        reply_markup=time_keyboard(subscription.send_hour if subscription else 8),
    )


@router.callback_query(F.data.startswith("time:"))
async def on_time(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
    t: Translator,
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
        t,
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
    t: Translator,
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
        t("done") + "\n\n" + format_subscription(subscription, settings, roster, t)
    )
    await callback.message.answer(t("menu_hint"), reply_markup=main_menu(t))
