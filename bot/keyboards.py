"""Клавиатуры бота. Все подписи берутся из переводчика."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .i18n import LANGUAGE_NAMES, Translator
from .languages import NONE as COURSE_NONE, language_name
from .scheduling import DAILY, MONTHLY, OFF, WEEKLY


def main_menu(t: Translator) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_today")), KeyboardButton(text=t("btn_week"))],
            [KeyboardButton(text=t("btn_notes")), KeyboardButton(text=t("btn_settings"))],
        ],
        resize_keyboard=True,
        input_field_placeholder=t("btn_placeholder"),
    )


def language_keyboard(current: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ " if code == current else "") + name,
                    callback_data=f"lang:{code}",
                )
            ]
            for code, name in LANGUAGE_NAMES.items()
        ]
    )


def course_language_keyboard(keys: list[str], t: Translator) -> InlineKeyboardMarkup:
    """Изучаемый иностранный язык: список берётся из живого расписания."""
    rows = [
        [
            InlineKeyboardButton(
                text=language_name(key, t.lang), callback_data=f"course:{key}"
            )
        ]
        for key in keys
    ]
    rows.append(
        [InlineKeyboardButton(text=t("btn_course_all"), callback_data="course:all")]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_course_none"), callback_data=f"course:{COURSE_NONE}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def course_teacher_keyboard(teachers: list[str], t: Translator) -> InlineKeyboardMarkup:
    """Уточнение группы, когда у языка несколько преподавателей."""
    rows = [
        [InlineKeyboardButton(text=_shorten(name), callback_data=f"teacher:{index}")]
        for index, name in enumerate(teachers)
    ]
    rows.append(
        [InlineKeyboardButton(text=t("btn_any_teacher"), callback_data="teacher:any")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def students_keyboard(labels: list[str], t: Translator) -> InlineKeyboardMarkup:
    """Кандидаты по фамилии: один вариант — одна кнопка."""
    rows = [
        [InlineKeyboardButton(text=_shorten(label), callback_data=f"student:{index}")]
        for index, label in enumerate(labels)
    ]
    rows.append(
        [InlineKeyboardButton(text=t("btn_not_in_list"), callback_data="student:none")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_student_keyboard(t: Translator, index: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_its_me"), callback_data=f"student:{index}")],
            [InlineKeyboardButton(text=t("btn_retry_name"), callback_data="student:retry")],
        ]
    )


def frequency_keyboard(t: Translator, current: str | None = None) -> InlineKeyboardMarkup:
    options = [
        (DAILY, t("btn_daily")),
        (WEEKLY, t("btn_weekly")),
        (MONTHLY, t("btn_monthly")),
        (OFF, t("btn_off")),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ " if code == current else "") + title,
                    callback_data=f"freq:{code}",
                )
            ]
            for code, title in options
        ]
    )


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


def settings_keyboard(t: Translator, show_all: bool = False) -> InlineKeyboardMarkup:
    filter_title = t("btn_settings_show_mine") if show_all else t("btn_settings_show_all")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_settings_freq"), callback_data="settings:freq")],
            [InlineKeyboardButton(text=t("btn_settings_time"), callback_data="settings:time")],
            [InlineKeyboardButton(text=filter_title, callback_data="settings:filter")],
            [
                InlineKeyboardButton(
                    text=t("btn_settings_course_language"),
                    callback_data="settings:course",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_settings_student"), callback_data="settings:student"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_settings_language"), callback_data="settings:language"
                )
            ],
        ]
    )


def note_day_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_today_note"), callback_data="noteday:0"),
                InlineKeyboardButton(text=t("btn_tomorrow"), callback_data="noteday:1"),
            ],
            [
                InlineKeyboardButton(text=t("btn_day_after"), callback_data="noteday:2"),
                InlineKeyboardButton(text=t("btn_in_a_week"), callback_data="noteday:7"),
            ],
            [InlineKeyboardButton(text=t("btn_other_date"), callback_data="noteday:custom")],
            [InlineKeyboardButton(text=t("btn_cancel"), callback_data="cancel")],
        ]
    )


def notes_menu_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_new_note"), callback_data="note:new")],
            [InlineKeyboardButton(text=t("btn_note_list"), callback_data="note:list")],
        ]
    )


def _shorten(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
