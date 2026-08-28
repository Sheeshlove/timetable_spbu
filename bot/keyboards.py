"""Клавиатуры бота."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .scheduling import DAILY, MONTHLY, OFF, WEEKLY

PER_PAGE = 8

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


def options_keyboard(
    labels: list[str],
    step: str,
    page: int = 0,
    *,
    per_page: int = PER_PAGE,
    back_step: str | None = None,
) -> InlineKeyboardMarkup:
    """Список вариантов с постраничной навигацией.

    В callback_data уходит индекс варианта в исходном списке, сам список
    лежит в состоянии диалога — так подписи любой длины помещаются в лимит
    Telegram в 64 байта.
    """
    pages = max(1, (len(labels) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=_shorten(label), callback_data=f"pick:{step}:{start + offset}")]
        for offset, label in enumerate(labels[start : start + per_page])
    ]

    if pages > 1:
        nav = [
            InlineKeyboardButton(
                text="◀️", callback_data=f"nav:{step}:{page - 1}" if page > 0 else "noop"
            ),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"),
            InlineKeyboardButton(
                text="▶️", callback_data=f"nav:{step}:{page + 1}" if page + 1 < pages else "noop"
            ),
        ]
        rows.append(nav)

    tail = []
    if back_step:
        tail.append(InlineKeyboardButton(text="↩️ Назад", callback_data=f"back:{back_step}"))
    tail.append(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    rows.append(tail)
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Периодичность", callback_data="settings:freq")],
            [InlineKeyboardButton(text="⏰ Время отправки", callback_data="settings:time")],
            [InlineKeyboardButton(text="🎓 Сменить группу", callback_data="settings:group")],
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
