"""Клавиатуры бота."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .scheduling import DAILY, MONTHLY, OFF, WEEKLY

BTN_TODAY = "📅 Сегодня"
BTN_WEEK = "🗓 Неделя"
BTN_NOTES = "📝 Заметки"
BTN_SETTINGS = "⚙️ Настройки"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_WEEK)],
            [KeyboardButton(text=BTN_NOTES), KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или напишите заметку",
    )


def students_keyboard(labels: list[str]) -> InlineKeyboardMarkup:
    """Кандидаты по фамилии: один вариант — одна кнопка."""
    rows = [
        [InlineKeyboardButton(text=_shorten(label), callback_data=f"student:{index}")]
        for index, label in enumerate(labels)
    ]
    rows.append(
        [InlineKeyboardButton(text="Меня нет в списке", callback_data="student:none")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_student_keyboard(index: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Это я", callback_data=f"student:{index}")],
            [InlineKeyboardButton(text="🔁 Ввести фамилию заново", callback_data="student:retry")],
        ]
    )


def frequency_keyboard(current: str | None = None) -> InlineKeyboardMarkup:
    options = [
        (DAILY, "Раз в день"),
        (WEEKLY, "Раз в неделю"),
        (MONTHLY, "Раз в месяц"),
        (OFF, "Не присылать"),
    ]
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if code == current else "") + title,
                callback_data=f"freq:{code}",
            )
        ]
        for code, title in options
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_keyboard(current_hour: int | None = None) -> InlineKeyboardMarkup:
    hours = list(range(6, 23))
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(hours), 4):
        rows.append(
            [
                InlineKeyboardButton(
                    text=("✅ " if hour == current_hour else "") + f"{hour:02d}:00",
                    callback_data=f"time:{hour}:0",
                )
                for hour in hours[index : index + 4]
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard(show_all: bool = False) -> InlineKeyboardMarkup:
    filter_title = (
        "🔎 Показывать только мою когорту" if show_all else "📋 Показывать всё расписание"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Периодичность", callback_data="settings:freq")],
            [InlineKeyboardButton(text="⏰ Время отправки", callback_data="settings:time")],
            [InlineKeyboardButton(text=filter_title, callback_data="settings:filter")],
            [InlineKeyboardButton(text="🎓 Сменить фамилию", callback_data="settings:student")],
        ]
    )


def note_day_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="noteday:0"),
                InlineKeyboardButton(text="Завтра", callback_data="noteday:1"),
            ],
            [
                InlineKeyboardButton(text="Послезавтра", callback_data="noteday:2"),
                InlineKeyboardButton(text="Через неделю", callback_data="noteday:7"),
            ],
            [InlineKeyboardButton(text="📆 Другая дата", callback_data="noteday:custom")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def notes_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Новая заметка", callback_data="note:new")],
            [InlineKeyboardButton(text="📋 Список заметок", callback_data="note:list")],
        ]
    )


def _shorten(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
