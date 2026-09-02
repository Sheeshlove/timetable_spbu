"""Заметки: пользователь присылает текст и указывает день, когда его вернуть."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..dates import DateParseError, parse_due, split_due
from ..formatting import format_notes
from ..i18n import Translator
from ..keyboards import note_day_keyboard, notes_menu_keyboard
from ..storage import Storage

logger = logging.getLogger(__name__)
router = Router(name="notes")

MAX_NOTE_LENGTH = 3000


class NoteStates(StatesGroup):
    text = State()
    day = State()
    custom_day = State()


async def _default_time(storage: Storage, user_id: int) -> time:
    """Заметки без указанного часа приходят в то же время, что и расписание."""
    subscription = await storage.get_subscription(user_id)
    if subscription and subscription.frequency != "off":
        return time(subscription.send_hour, subscription.send_minute)
    return time(9, 0)


async def _save_note(
    message: Message,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    t: Translator,
    user_id: int,
    text: str,
    due_at: datetime,
) -> None:
    note_id = await storage.add_note(user_id, message.chat.id, text, due_at)
    local = due_at.astimezone(settings.tz)
    await state.clear()
    await message.answer(
        t(
            "note_saved",
            date=f"{local:%d.%m.%Y}",
            time=f"{local:%H:%M}",
            id=note_id,
        )
    )


@router.message(Command("note"))
async def cmd_note(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    t: Translator,
) -> None:
    """/note — диалог; /note 05.09 текст — быстрая запись одной строкой."""
    argument = (command.args or "").strip()
    if not argument:
        await state.set_state(NoteStates.text)
        await message.answer(t("note_ask_text"))
        return

    try:
        due_at, text = split_due(
            argument, settings.tz, default_time=await _default_time(storage, message.from_user.id)
        )
    except DateParseError:
        # Даты нет — считаем всю строку текстом и спрашиваем день кнопками.
        await state.update_data(note_text=argument[:MAX_NOTE_LENGTH])
        await state.set_state(NoteStates.day)
        await message.answer(t("note_ask_day"), reply_markup=note_day_keyboard(t))
        return

    if not text:
        await state.update_data(note_due_at=due_at.isoformat())
        await state.set_state(NoteStates.text)
        await message.answer(t("note_ask_text"))
        return

    await _save_note(
        message, state, storage, settings, t, message.from_user.id,
        text[:MAX_NOTE_LENGTH], due_at,
    )


@router.message(Command("notes"))
async def cmd_notes(
    message: Message, storage: Storage, settings: Settings, t: Translator
) -> None:
    notes = await storage.pending_notes(message.from_user.id)
    await message.answer(
        format_notes(notes, settings.tz, t), reply_markup=notes_menu_keyboard(t)
    )


@router.message(F.text.in_({"📝 Заметки", "📝 Notes"}))
async def on_notes_button(
    message: Message, storage: Storage, settings: Settings, t: Translator
) -> None:
    await cmd_notes(message, storage, settings, t)


@router.message(Command("delnote"))
async def cmd_delete_note(
    message: Message, command: CommandObject, storage: Storage, t: Translator
) -> None:
    raw = (command.args or "").strip().lstrip("#")
    if not raw.isdigit():
        await message.answer(t("note_need_number"))
        return
    deleted = await storage.delete_note(message.from_user.id, int(raw))
    await message.answer(t("note_deleted") if deleted else t("note_not_found"))


@router.callback_query(F.data == "note:new")
async def on_new_note(callback: CallbackQuery, state: FSMContext, t: Translator) -> None:
    await callback.answer()
    await state.set_state(NoteStates.text)
    await callback.message.answer(t("note_ask_text"))


@router.callback_query(F.data == "note:list")
async def on_list_notes(
    callback: CallbackQuery, storage: Storage, settings: Settings, t: Translator
) -> None:
    await callback.answer()
    notes = await storage.pending_notes(callback.from_user.id)
    await callback.message.answer(format_notes(notes, settings.tz, t))


@router.message(NoteStates.text, F.text)
async def on_note_text(
    message: Message,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    t: Translator,
) -> None:
    data = await state.get_data()
    known_due = data.get("note_due_at")
    if known_due:  # день уже назван в /note, осталось получить текст
        await _save_note(
            message, state, storage, settings, t, message.from_user.id,
            message.text[:MAX_NOTE_LENGTH], datetime.fromisoformat(known_due),
        )
        return
    await state.update_data(note_text=message.text[:MAX_NOTE_LENGTH])
    await state.set_state(NoteStates.day)
    await message.answer(t("note_ask_day"), reply_markup=note_day_keyboard(t))


@router.callback_query(F.data.startswith("noteday:"))
async def on_note_day(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    t: Translator,
) -> None:
    choice = callback.data.split(":", 1)[1]
    data = await state.get_data()
    text = data.get("note_text")
    if not text:
        await callback.answer(t("note_lost"))
        await state.set_state(NoteStates.text)
        await callback.message.answer(t("note_ask_text"))
        return

    await callback.answer()
    if choice == "custom":
        await state.set_state(NoteStates.custom_day)
        await callback.message.answer(t("note_ask_custom_day"))
        return

    at_time = await _default_time(storage, callback.from_user.id)
    now_local = datetime.now(timezone.utc).astimezone(settings.tz)
    target = now_local.date() + timedelta(days=int(choice))
    due_at = datetime.combine(target, at_time, tzinfo=settings.tz)
    if due_at <= now_local:
        due_at = now_local + timedelta(minutes=1)
    await _save_note(
        callback.message, state, storage, settings, t, callback.from_user.id,
        text, due_at.astimezone(timezone.utc),
    )


@router.message(NoteStates.custom_day, F.text)
async def on_custom_day(
    message: Message,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    t: Translator,
) -> None:
    data = await state.get_data()
    text = data.get("note_text", "")
    try:
        due_at = parse_due(
            message.text,
            settings.tz,
            default_time=await _default_time(storage, message.from_user.id),
        )
    except DateParseError:
        await message.answer(t("note_bad_date") + t("note_ask_custom_day"))
        return
    await _save_note(
        message, state, storage, settings, t, message.from_user.id, text, due_at
    )


@router.message(NoteStates.day, F.text)
async def on_day_typed_instead_of_button(
    message: Message,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    t: Translator,
) -> None:
    """На шаге выбора дня можно не жать кнопку, а написать дату словами."""
    data = await state.get_data()
    text = data.get("note_text", "")
    try:
        due_at = parse_due(
            message.text,
            settings.tz,
            default_time=await _default_time(storage, message.from_user.id),
        )
    except DateParseError:
        await message.answer(
            t("note_bad_date") + t("note_ask_custom_day"),
            reply_markup=note_day_keyboard(t),
        )
        return
    await _save_note(
        message, state, storage, settings, t, message.from_user.id, text, due_at
    )


@router.message(F.text & ~F.text.startswith("/"))
async def on_free_text(
    message: Message, state: FSMContext, t: Translator
) -> None:
    """Любой свободный текст вне диалогов считаем черновиком заметки."""
    if await state.get_state() is not None:
        return
    await state.update_data(note_text=message.text[:MAX_NOTE_LENGTH])
    await state.set_state(NoteStates.day)
    await message.answer(t("note_draft"), reply_markup=note_day_keyboard(t))
