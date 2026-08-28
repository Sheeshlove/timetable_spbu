"""Мастер выбора: направление → программа → год поступления → группа."""

from __future__ import annotations

import logging
from html import escape
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..formatting import format_subscription
from ..keyboards import (
    BTN_NOTES,
    BTN_SETTINGS,
    BTN_TODAY,
    BTN_WEEK,
    frequency_keyboard,
    main_menu,
    options_keyboard,
    time_keyboard,
)
from ..scheduling import FREQUENCY_TITLES, OFF, next_run_at
from ..storage import Storage, Subscription
from ..timetable import TimetableClient, TimetableError

logger = logging.getLogger(__name__)
router = Router(name="setup")

STEP_DIVISION = "div"
STEP_PROGRAM = "prog"
STEP_YEAR = "year"
STEP_GROUP = "group"

PREVIOUS_STEP = {STEP_PROGRAM: STEP_DIVISION, STEP_YEAR: STEP_PROGRAM, STEP_GROUP: STEP_YEAR}

STEP_TITLES = {
    STEP_DIVISION: "Шаг 1/4. Выберите направление (учебное подразделение):",
    STEP_PROGRAM: "Шаг 2/4. Выберите образовательную программу:",
    STEP_YEAR: "Шаг 3/4. Выберите год поступления:",
    STEP_GROUP: "Шаг 4/4. Выберите учебную группу:",
}

SEARCH_HINT = "\n\n🔎 Список длинный — пришлите часть названия, чтобы отфильтровать."

GREETING = (
    "Привет! Я присылаю расписание занятий СПбГУ с сайта timetable.spbu.ru.\n\n"
    "Сейчас выберем вашу группу, а потом — как часто присылать расписание.\n"
    "Ещё я умею хранить заметки и присылать их в нужный день: /note"
)


class SetupStates(StatesGroup):
    division = State()
    program = State()
    year = State()
    group = State()
    frequency = State()
    send_time = State()


STEP_STATES = {
    STEP_DIVISION: SetupStates.division,
    STEP_PROGRAM: SetupStates.program,
    STEP_YEAR: SetupStates.year,
    STEP_GROUP: SetupStates.group,
}


# --- Упаковка вариантов в состояние ------------------------------------


def _pack(items: list[Any], step: str) -> list[dict[str, Any]]:
    if step == STEP_DIVISION:
        return [{"alias": item.alias, "name": item.name} for item in items]
    if step == STEP_PROGRAM:
        return [{"key": item.key, "name": item.name, "level": item.level} for item in items]
    if step == STEP_YEAR:
        return [
            {
                "program_id": item.program_id,
                "name": item.name,
                "group_id": item.group_id,
                "is_current": item.is_current,
            }
            for item in items
        ]
    return [
        {"group_id": item.group_id, "name": item.name, "form": item.study_form}
        for item in items
    ]


def _label(item: dict[str, Any], step: str) -> str:
    if step == STEP_DIVISION:
        return f"{item['name']} ({item['alias']})"
    if step == STEP_PROGRAM:
        return f"{item['level']} · {item['name']}" if item.get("level") else item["name"]
    if step == STEP_YEAR:
        return f"{item['name']}{' ⭐️' if item.get('is_current') else ''}"
    return f"{item['name']} · {item['form']}" if item.get("form") else item["name"]


def _matches(item: dict[str, Any], step: str, query: str) -> bool:
    return query in _label(item, step).lower()


# --- Отрисовка шага ----------------------------------------------------


async def show_step(
    message: Message,
    state: FSMContext,
    step: str,
    page: int = 0,
    *,
    edit: bool = False,
    query: str = "",
) -> None:
    data = await state.get_data()
    items: list[dict[str, Any]] = data.get(f"all:{step}", [])
    if query:
        filtered = [item for item in items if _matches(item, step, query.lower())]
        if not filtered:
            await message.answer("Ничего не нашлось. Попробуйте другое слово.")
            return
    else:
        filtered = items

    await state.update_data(**{f"shown:{step}": filtered})
    await state.set_state(STEP_STATES[step])

    title = STEP_TITLES[step]
    if query:
        title += f"\n\nФильтр: «{escape(query)}» — найдено {len(filtered)}."
    elif len(filtered) > 8:
        title += SEARCH_HINT

    markup = options_keyboard(
        [_label(item, step) for item in filtered],
        step,
        page,
        back_step=PREVIOUS_STEP.get(step),
    )
    if edit:
        try:
            await message.edit_text(title, reply_markup=markup)
            return
        except Exception:  # noqa: BLE001 — сообщение могло устареть, шлём новое
            logger.debug("Не удалось отредактировать сообщение шага %s", step, exc_info=True)
    await message.answer(title, reply_markup=markup)


async def load_step(
    message: Message,
    state: FSMContext,
    step: str,
    client: TimetableClient,
    *,
    edit: bool = False,
) -> None:
    """Загружает варианты для шага с сайта и показывает их."""
    data = await state.get_data()
    try:
        if step == STEP_DIVISION:
            items = await client.divisions()
        elif step == STEP_PROGRAM:
            items = await client.programs(data["division"]["alias"])
        elif step == STEP_YEAR:
            items = await client.admission_years(
                data["division"]["alias"], data["program"]["key"]
            )
        else:
            year = data["year"]
            items = await client.groups(
                _year_model(year)
            )
    except TimetableError as error:
        logger.warning("Шаг %s не загрузился: %s", step, error)
        await message.answer(
            "Сайт расписания сейчас не отвечает 😕\nПопробуйте ещё раз через пару минут: /start"
        )
        return

    await state.update_data(**{f"all:{step}": _pack(items, step)})
    await show_step(message, state, step, 0, edit=edit)


def _year_model(year: dict[str, Any]):
    from ..timetable.models import AdmissionYear

    return AdmissionYear(
        program_id=year.get("program_id", 0),
        name=year.get("name", ""),
        group_id=year.get("group_id"),
    )


# --- Точки входа -------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    client: TimetableClient,
    storage: Storage,
    settings: Settings,
) -> None:
    await state.clear()
    subscription = await storage.get_subscription(message.from_user.id)
    if subscription:
        await message.answer(
            format_subscription(subscription, settings.tz)
            + "\n\nЧтобы поменять группу — «⚙️ Настройки» → «Сменить группу».",
            reply_markup=main_menu(),
        )
        return
    await message.answer(GREETING, reply_markup=main_menu())
    await load_step(message, state, STEP_DIVISION, client)


@router.message(Command("setup"))
async def cmd_setup(message: Message, state: FSMContext, client: TimetableClient) -> None:
    await state.clear()
    await load_step(message, state, STEP_DIVISION, client)


@router.callback_query(F.data == "settings:group")
async def restart_wizard(
    callback: CallbackQuery, state: FSMContext, client: TimetableClient
) -> None:
    await callback.answer()
    await state.clear()
    await load_step(callback.message, state, STEP_DIVISION, client)


# --- Навигация по спискам ---------------------------------------------


@router.callback_query(F.data.startswith("nav:"))
async def on_navigate(callback: CallbackQuery, state: FSMContext) -> None:
    _, step, page = callback.data.split(":", 2)
    await callback.answer()
    data = await state.get_data()
    shown = data.get(f"shown:{step}")
    if shown is None:
        await callback.message.answer("Список устарел, начнём заново: /start")
        return
    await state.update_data(**{f"all:{step}": data.get(f"all:{step}", shown)})
    markup = options_keyboard(
        [_label(item, step) for item in shown],
        step,
        int(page),
        back_step=PREVIOUS_STEP.get(step),
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
    except Exception:  # noqa: BLE001
        logger.debug("Не удалось обновить клавиатуру", exc_info=True)


@router.callback_query(F.data.startswith("back:"))
async def on_back(callback: CallbackQuery, state: FSMContext, client: TimetableClient) -> None:
    step = callback.data.split(":", 1)[1]
    await callback.answer()
    data = await state.get_data()
    if data.get(f"all:{step}"):
        await show_step(callback.message, state, step, 0, edit=True)
    else:
        await load_step(callback.message, state, step, client, edit=True)


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    await callback.message.answer("Хорошо, отменил. Вернуться к настройке: /setup")


# --- Выбор варианта ----------------------------------------------------


@router.callback_query(F.data.startswith("pick:"))
async def on_pick(
    callback: CallbackQuery,
    state: FSMContext,
    client: TimetableClient,
    storage: Storage,
) -> None:
    _, step, raw_index = callback.data.split(":", 2)
    data = await state.get_data()
    shown = data.get(f"shown:{step}", [])
    index = int(raw_index)
    if index >= len(shown):
        await callback.answer("Список устарел")
        await callback.message.answer("Начнём заново: /start")
        return

    chosen = shown[index]
    await callback.answer()

    if step == STEP_DIVISION:
        await state.update_data(division=chosen)
        await load_step(callback.message, state, STEP_PROGRAM, client, edit=True)
        return

    if step == STEP_PROGRAM:
        await state.update_data(program=chosen)
        await load_step(callback.message, state, STEP_YEAR, client, edit=True)
        return

    if step == STEP_YEAR:
        await state.update_data(year=chosen)
        try:
            groups = await client.groups(_year_model(chosen))
        except TimetableError as error:
            logger.warning("Группы не загрузились: %s", error)
            await callback.message.answer("Не удалось получить список групп. Попробуйте позже.")
            return
        if len(groups) == 1:  # выбирать не из чего — пропускаем шаг
            await state.update_data(group=_pack(groups, STEP_GROUP)[0])
            await ask_frequency(
                callback.message, state, storage, callback.from_user.id, edit=True
            )
            return
        await state.update_data(**{f"all:{STEP_GROUP}": _pack(groups, STEP_GROUP)})
        await show_step(callback.message, state, STEP_GROUP, 0, edit=True)
        return

    if step == STEP_GROUP:
        await state.update_data(group=chosen)
        await ask_frequency(callback.message, state, storage, callback.from_user.id, edit=True)


# --- Поиск по списку ---------------------------------------------------


@router.message(
    StateFilter(
        SetupStates.division, SetupStates.program, SetupStates.year, SetupStates.group
    ),
    F.text
    & ~F.text.startswith("/")
    & ~F.text.in_({BTN_TODAY, BTN_WEEK, BTN_NOTES, BTN_SETTINGS}),
)
async def on_search(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    step = next((key for key, value in STEP_STATES.items() if value.state == current), None)
    if step is None:
        return
    await show_step(message, state, step, 0, query=message.text.strip())


# --- Периодичность и время --------------------------------------------


async def ask_frequency(
    message: Message,
    state: FSMContext,
    storage: Storage,
    user_id: int,
    *,
    edit: bool = False,
) -> None:
    data = await state.get_data()
    group = data.get("group", {})
    subscription = await storage.get_subscription(user_id)
    text = (
        f"Группа выбрана: <b>{escape(str(group.get('name', '')))}</b>\n\n"
        "Как часто присылать расписание?"
    )
    markup = frequency_keyboard(subscription.frequency if subscription else None)
    await state.set_state(SetupStates.frequency)
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except Exception:  # noqa: BLE001
            logger.debug("Не удалось отредактировать сообщение периодичности", exc_info=True)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("freq:"))
async def on_frequency(
    callback: CallbackQuery, state: FSMContext, storage: Storage, settings: Settings
) -> None:
    frequency = callback.data.split(":", 1)[1]
    await callback.answer()
    await state.update_data(frequency=frequency)

    if frequency == OFF:
        await _save(callback, state, storage, settings, frequency=OFF, hour=8, minute=0)
        return

    await state.set_state(SetupStates.send_time)
    subscription = await storage.get_subscription(callback.from_user.id)
    hour = subscription.send_hour if subscription else 8
    await callback.message.edit_text(
        f"Периодичность: <b>{FREQUENCY_TITLES[frequency]}</b>.\n\n"
        f"В какое время присылать? Часовой пояс — {settings.tz_name}.",
        reply_markup=time_keyboard(hour),
    )


@router.callback_query(F.data.startswith("time:"))
async def on_time(
    callback: CallbackQuery, state: FSMContext, storage: Storage, settings: Settings
) -> None:
    _, hour, minute = callback.data.split(":", 2)
    await callback.answer()
    data = await state.get_data()
    await _save(
        callback,
        state,
        storage,
        settings,
        frequency=data.get("frequency", OFF),
        hour=int(hour),
        minute=int(minute),
    )


async def _save(
    callback: CallbackQuery,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
    *,
    frequency: str,
    hour: int,
    minute: int,
) -> None:
    data = await state.get_data()
    division = data.get("division") or {}
    program = data.get("program") or {}
    year = data.get("year") or {}
    group = data.get("group") or {}

    existing = await storage.get_subscription(callback.from_user.id)
    if not group and existing is None:
        await callback.message.answer("Сначала выберите группу: /setup")
        return

    subscription = Subscription(
        user_id=callback.from_user.id,
        chat_id=callback.message.chat.id,
        division_alias=division.get("alias") or (existing.division_alias if existing else ""),
        division_name=division.get("name") or (existing.division_name if existing else ""),
        program_key=program.get("key") or (existing.program_key if existing else ""),
        program_name=program.get("name") or (existing.program_name if existing else ""),
        year_name=year.get("name") or (existing.year_name if existing else ""),
        group_id=int(group.get("group_id") or (existing.group_id if existing else 0)),
        group_name=group.get("name") or (existing.group_name if existing else ""),
        frequency=frequency,
        send_hour=hour,
        send_minute=minute,
    )
    subscription.next_run_at = next_run_at(frequency, hour, minute, settings.tz)
    await storage.save_subscription(subscription)
    await state.clear()

    await callback.message.edit_text(
        "Готово! ✅\n\n" + format_subscription(subscription, settings.tz)
    )
    await callback.message.answer(
        "Расписание можно посмотреть в любой момент кнопками ниже.",
        reply_markup=main_menu(),
    )
