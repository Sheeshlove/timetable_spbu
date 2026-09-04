"""Знакомство: язык, фамилия студента, затем периодичность и время рассылки."""

from __future__ import annotations

import logging
import re
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from datetime import timedelta

from ..config import Settings
from ..formatting import format_cohorts, format_subscription, frequency_title, now_local
from ..i18n import Translator, menu_texts
from ..keyboards import (
    confirm_student_keyboard,
    course_language_keyboard,
    course_teacher_keyboard,
    frequency_keyboard,
    language_keyboard,
    main_menu,
    students_keyboard,
    subgroup_keyboard,
    time_keyboard,
)
from ..languages import (
    ANY as COURSE_ANY,
    FALLBACK_KEYS,
    NONE as COURSE_NONE,
    language_name,
    offered_languages,
    teachers_for,
)
from ..roster import Roster, Student
from ..roster.filtering import educator_subgroups, educator_value
from ..scheduling import OFF, next_run_at
from ..storage import Storage, Subscription
from ..timetable import TimetableClient, TimetableError

logger = logging.getLogger(__name__)
router = Router(name="setup")


class SetupStates(StatesGroup):
    language = State()
    last_name = State()
    course_language = State()
    course_teacher = State()
    subgroup = State()
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
    client: TimetableClient,
    roster: Roster,
    t: Translator,
) -> None:
    choice = callback.data.split(":", 1)[1]
    await callback.answer()

    if choice == "retry":
        await ask_last_name(callback.message, state, t)
        return

    if choice == "none":
        await _remember_student(
            callback, state, storage, settings, client, roster, t, student=None
        )
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
    await _remember_student(
        callback, state, storage, settings, client, roster, t, student=student
    )


async def _remember_student(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    client: TimetableClient,
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

    await ask_course_language(callback.message, state, settings, client, t)


# --- Изучаемый иностранный язык ---------------------------------------


# Сколько недель расписания смотреть, чтобы узнать языки и их группы. Месяц
# берётся не из осторожности: языковые пары могут начаться не с первой недели,
# а язык студент выбирает один раз.
LOOKAHEAD_DAYS = 27


async def _upcoming_week(settings: Settings, client: TimetableClient, lang: str):
    """Ближайший месяц — по нему узнаём, какие языки и группы вообще бывают."""
    today = now_local(settings.tz).date()
    monday = today - timedelta(days=today.weekday())
    return await client.schedule(
        settings.group_id,
        monday,
        monday + timedelta(days=LOOKAHEAD_DAYS),
        settings.division_alias,
        lang,
    )


async def ask_course_language(
    message: Message,
    state: FSMContext,
    settings: Settings,
    client: TimetableClient,
    t: Translator,
) -> None:
    """Спрашивает язык, предлагая то, что реально стоит в расписании."""
    await state.set_state(SetupStates.course_language)
    note = ""
    try:
        schedule = await _upcoming_week(settings, client, t.lang)
        keys = offered_languages(schedule)
    except TimetableError as error:
        logger.info("Список языков с сайта не получен: %s", error)
        keys = list(FALLBACK_KEYS)
        note = "\n\n" + t("course_language_unknown")

    await message.answer(
        t("ask_course_language") + note, reply_markup=course_language_keyboard(keys, t)
    )


@router.callback_query(F.data.startswith("course:"))
async def on_course_language(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    client: TimetableClient,
    roster: Roster,
    t: Translator,
) -> None:
    choice = callback.data.split(":", 1)[1]
    await callback.answer()

    subscription = await storage.get_subscription(callback.from_user.id)
    if subscription is None:
        await callback.message.answer(t("not_configured"))
        return

    if choice == "all":
        subscription.language_course = COURSE_ANY
        subscription.language_teacher = ""
        await storage.save_subscription(subscription)
        await callback.message.answer(t("course_language_all"))
        await _after_course(
            callback.message, state, storage, settings, client, roster, t,
            callback.from_user.id,
        )
        return

    if choice == COURSE_NONE:
        subscription.language_course = COURSE_NONE
        subscription.language_teacher = ""
        await storage.save_subscription(subscription)
        await callback.message.answer(t("course_language_none"))
        await _after_course(
            callback.message, state, storage, settings, client, roster, t,
            callback.from_user.id,
        )
        return

    subscription.language_course = choice
    subscription.language_teacher = ""
    await storage.save_subscription(subscription)

    teachers: list[str] = []
    try:
        schedule = await _upcoming_week(settings, client, t.lang)
        teachers = teachers_for(schedule, choice)
    except TimetableError as error:
        logger.info("Преподаватели языка с сайта не получены: %s", error)

    if len(teachers) > 1:  # у языка несколько групп — уточняем
        await state.update_data(course_teachers=teachers)
        await state.set_state(SetupStates.course_teacher)
        await callback.message.answer(
            t("ask_course_teacher"), reply_markup=course_teacher_keyboard(teachers, t)
        )
        return

    await callback.message.answer(
        t("course_language_saved", course=escape(language_name(choice, t.lang)))
    )
    await _after_course(
        callback.message, state, storage, settings, client, roster, t, callback.from_user.id
    )


@router.callback_query(F.data.startswith("teacher:"))
async def on_course_teacher(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    client: TimetableClient,
    roster: Roster,
    t: Translator,
) -> None:
    choice = callback.data.split(":", 1)[1]
    await callback.answer()

    subscription = await storage.get_subscription(callback.from_user.id)
    if subscription is None:
        await callback.message.answer(t("not_configured"))
        return

    teacher = ""
    if choice != "any":
        teachers = (await state.get_data()).get("course_teachers", [])
        index = int(choice)
        if index < len(teachers):
            teacher = teachers[index]

    subscription.language_teacher = teacher
    await storage.save_subscription(subscription)

    title = language_name(subscription.language_course, t.lang)
    if teacher:
        title = f"{title} · {teacher}"
    await callback.message.answer(t("course_language_saved", course=escape(title)))
    await _after_course(
        callback.message, state, storage, settings, client, roster, t, callback.from_user.id
    )


async def _after_course(
    message: Message,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    client: TimetableClient,
    roster: Roster,
    t: Translator,
    user_id: int,
) -> None:
    """После языка: либо продолжаем знакомство, либо показываем карточку."""
    subscription = await storage.get_subscription(user_id)
    data = await state.get_data()
    if data.get("editing_course"):
        await state.clear()
        if subscription is not None:
            await message.answer(format_subscription(subscription, settings, roster, t))
        return
    if await ask_subgroup(message, state, subscription, settings, client, roster, t):
        return
    await ask_frequency(message, state, subscription, t)


# --- Подгруппа у преподавателя ----------------------------------------


def _subgroup_when(entries, t: Translator) -> str:
    """Когда занимается эта подгруппа — «суббота 10:00, 11:45»."""
    labels: list[str] = []
    for day, event in entries:
        weekday = t.weekdays[day.weekday()] if day else ""
        start = re.split(r"[–—-]", event.interval or "", maxsplit=1)[0].strip()
        label = " ".join(part for part in (weekday, start) if part)
        if label and label not in labels:
            labels.append(label)
        if len(labels) == 3:  # трёх примеров хватает, чтобы узнать свою пару
            break
    return ", ".join(labels)


async def ask_subgroup(
    message: Message,
    state: FSMContext,
    subscription: Subscription | None,
    settings: Settings,
    client: TimetableClient,
    roster: Roster,
    t: Translator,
    *,
    forced: bool = False,
) -> bool:
    """Спрашивает подгруппу, если по ведомости её не определить.

    В ведомости деканата группы преподавателя пронумерованы внутри него
    («Shevchuk 1», «Shevchuk 2»), а на сайте подгруппы нумеруются по всему
    потоку. Сопоставить одно с другим нельзя, поэтому спрашиваем студента —
    но только когда выбор действительно есть. Возвращает True, если спросили.
    """
    student = (
        roster.get(subscription.student_name)
        if subscription and subscription.student_name
        else None
    )
    if student is None or subscription.show_all:
        return False

    try:
        schedule = await _upcoming_week(settings, client, t.lang)
    except TimetableError as error:
        logger.info("Подгруппы с сайта не получены: %s", error)
        if forced:
            await message.answer(t("subgroup_unknown"))
        return False

    groups = educator_subgroups(schedule, student, roster)
    if len(groups) < 2:
        if forced:
            await message.answer(t("subgroup_single"))
        return False

    first = next(iter(groups.values()))[0][1]
    cohort = educator_value(student, roster)
    lines = [t("ask_subgroup", educator=escape(first.educators), cohort=escape(cohort))]
    for number, entries in groups.items():
        lines.append(
            t(
                "subgroup_option",
                label=t("subgroup_label", number=number),
                when=escape(_subgroup_when(entries, t)),
            )
        )

    await state.set_state(SetupStates.subgroup)
    await message.answer(
        "\n".join(lines), reply_markup=subgroup_keyboard(list(groups), t)
    )
    return True


@router.callback_query(F.data.startswith("subgroup:"))
async def on_subgroup(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    roster: Roster,
    t: Translator,
) -> None:
    choice = callback.data.split(":", 1)[1]
    await callback.answer()

    subscription = await storage.get_subscription(callback.from_user.id)
    if subscription is None:
        await callback.message.answer(t("not_configured"))
        return

    subscription.subgroup = "" if choice == "all" else choice
    await storage.save_subscription(subscription)

    if subscription.subgroup:
        await callback.message.answer(
            t("subgroup_saved", subgroup=t("subgroup_label", number=subscription.subgroup))
        )
    else:
        await callback.message.answer(t("subgroup_all_saved"))

    data = await state.get_data()
    if data.get("editing_subgroup"):
        await state.clear()
        await callback.message.answer(
            format_subscription(subscription, settings, roster, t)
        )
        return
    await ask_frequency(callback.message, state, subscription, t)


@router.callback_query(F.data == "settings:course")
async def change_course_language(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    client: TimetableClient,
    t: Translator,
) -> None:
    await callback.answer()
    await state.clear()
    await state.update_data(editing_course=True)
    await ask_course_language(callback.message, state, settings, client, t)


@router.callback_query(F.data == "settings:subgroup")
async def change_subgroup(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    client: TimetableClient,
    roster: Roster,
    t: Translator,
) -> None:
    subscription = await storage.get_subscription(callback.from_user.id)
    if subscription is None:
        await callback.answer(t("setup_first"), show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.update_data(editing_subgroup=True)
    asked = await ask_subgroup(
        callback.message, state, subscription, settings, client, roster, t, forced=True
    )
    if not asked:
        await state.clear()


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
