"""Сквозной сценарий: настоящий Dispatcher, поддельный Telegram и сайт."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from aiogram.fsm.storage.memory import MemoryStorage

from bot.__main__ import build_dispatcher
from bot.config import Settings
from bot.roster import load_roster
from bot.scheduling import DAILY, WEEKLY
from bot.storage import Storage
from bot.timetable.models import Day, Event, Schedule
from fake_telegram import FakeTelegram

ROSTER = load_roster()

SETTINGS = Settings(
    bot_token="42:TEST",
    db_path=Path("unused.sqlite3"),
    tz_name="Europe/Moscow",
    base_url="https://timetable.spbu.ru",
    http_cache_ttl=0,
    http_timeout=5,
    log_level="INFO",
    group_id=474489,
    division_alias="GSOM",
    program_title="Master in Management, 2026",
)


class StubTimetable:
    """Отвечает как сайт, но без сети."""

    def __init__(self) -> None:
        self.schedule_calls: list[tuple[int, date, date]] = []

    async def schedule(self, group_id, start, end, alias=None):
        self.schedule_calls.append((group_id, start, end))
        return Schedule(
            group_id=group_id,
            group_name="MiM 2026",
            days=[
                Day(
                    date=start,
                    title="",
                    events=[
                        Event(
                            subject="Corporate Finance (Coh.1)",
                            time_text="10:00–11:35",
                            locations="Волховский пер., 3",
                        ),
                        Event(
                            subject="Corporate Finance (Coh.2)",
                            time_text="12:00–13:35",
                            educators="Иванов И. И.",
                        ),
                    ],
                )
            ],
        )


@pytest.fixture(scope="module")
def dispatcher():
    """Роутеры aiogram привязываются к одному Dispatcher, поэтому он общий;
    зависимости и состояние диалогов подменяются в каждом тесте."""
    return build_dispatcher(Storage("unused.sqlite3"), StubTimetable(), SETTINGS, ROSTER)


@pytest.fixture
async def app(tmp_path: Path, dispatcher):
    storage = Storage(tmp_path / "bot.sqlite3")
    await storage.connect()
    timetable = StubTimetable()

    dispatcher["storage"] = storage
    dispatcher["client"] = timetable
    dispatcher["settings"] = SETTINGS
    dispatcher["roster"] = ROSTER
    dispatcher.fsm.storage = MemoryStorage()  # чистое состояние на каждый тест

    telegram = FakeTelegram(dispatcher)
    yield telegram, storage, timetable
    await telegram.close()
    await storage.close()


async def complete_setup(telegram, surname: str = "Шишлов") -> None:
    await telegram.send("/start")
    await telegram.send(surname)
    await telegram.click_button("Это я")
    await telegram.click_button("Раз в день")
    await telegram.click_button("08:00")


# --- Знакомство --------------------------------------------------------


async def test_start_asks_for_surname(app):
    telegram, _, _ = app
    await telegram.send("/start")
    assert "Master in Management" in telegram.session.texts[0]
    assert "фамилия" in telegram.session.texts[-1].lower()


async def test_surname_lookup_shows_cohorts_and_saves(app):
    telegram, storage, _ = app
    await telegram.send("/start")
    await telegram.send("Шишлов")

    confirmation = telegram.session.texts[-1]
    assert "Shishlov Egor" in confirmation
    assert "Coh.2" in confirmation and "Shevchuk 2" in confirmation

    await telegram.click_button("Это я")
    saved = await storage.get_subscription(777)
    assert saved.student_name == "Shishlov Egor"
    assert saved.show_all is False

    await telegram.click_button("Раз в день")
    await telegram.click_button("08:00")
    saved = await storage.get_subscription(777)
    assert saved.frequency == DAILY
    assert saved.send_hour == 8
    assert saved.next_run_at is not None


async def test_latin_surname_also_works(app):
    telegram, storage, _ = app
    await telegram.send("/start")
    await telegram.send("Iurchenko")
    await telegram.click_button("Это я")
    assert (await storage.get_subscription(777)).student_name == "Iurchenko Kseniia"


async def test_unknown_surname_offers_full_schedule(app):
    telegram, storage, _ = app
    await telegram.send("/start")
    await telegram.send("Пупкин")
    assert "Не нашёл такой фамилии" in telegram.session.texts[-1]

    await telegram.click_button("Меня нет в списке")
    saved = await storage.get_subscription(777)
    assert saved.student_name == ""
    assert saved.show_all is True


async def test_retry_button_asks_surname_again(app):
    telegram, storage, _ = app
    await telegram.send("/start")
    await telegram.send("Шишлов")
    await telegram.click_button("Ввести фамилию заново")
    assert "фамилия" in telegram.session.texts[-1].lower()

    await telegram.send("Морозов")
    await telegram.click_button("Это я")
    assert (await storage.get_subscription(777)).student_name == "Morozov Ilia"


async def test_second_start_shows_saved_card(app):
    telegram, _, _ = app
    await complete_setup(telegram)
    telegram.session.clear()

    await telegram.send("/start")
    card = telegram.session.texts[-1]
    assert "Shishlov Egor" in card
    assert "только занятия моих когорт" in card


# --- Расписание --------------------------------------------------------


async def test_today_filters_foreign_cohort(app):
    telegram, _, timetable = app
    await complete_setup(telegram)
    telegram.session.clear()

    await telegram.send("/today")
    today = date.today()
    assert timetable.schedule_calls[-1] == (474489, today, today)

    text = telegram.session.texts[-1]
    assert "Coh.2" in text
    assert "Coh.1" not in text
    assert "Скрыто занятий других когорт: 1" in text


async def test_schedule_without_setup_asks_to_configure(app):
    telegram, _, timetable = app
    await telegram.send("/today")
    assert "Сначала напишите фамилию" in telegram.session.texts[-1]
    assert timetable.schedule_calls == []


async def test_week_command_asks_for_monday_to_sunday(app):
    telegram, _, timetable = app
    await complete_setup(telegram)
    telegram.session.clear()

    await telegram.send("/week")
    _group_id, start, end = timetable.schedule_calls[-1]
    assert start.weekday() == 0 and end.weekday() == 6
    assert (end - start).days == 6


async def test_cohorts_command(app):
    telegram, _, _ = app
    await complete_setup(telegram)
    telegram.session.clear()

    await telegram.send("/cohorts")
    text = telegram.session.texts[-1]
    assert "QMBR, семинары" in text and "Coh.4" in text


# --- Настройки ---------------------------------------------------------


async def test_filter_can_be_switched_off_and_on(app):
    telegram, storage, _ = app
    await complete_setup(telegram)

    await telegram.send("/settings")
    await telegram.click_button("Показывать всё расписание")
    assert (await storage.get_subscription(777)).show_all is True

    telegram.session.clear()
    await telegram.send("/today")
    text = telegram.session.texts[-1]
    assert "Coh.1" in text and "Coh.2" in text

    await telegram.send("/settings")
    await telegram.click_button("Показывать только мою когорту")
    assert (await storage.get_subscription(777)).show_all is False


async def test_surname_can_be_changed_from_settings(app):
    telegram, storage, _ = app
    await complete_setup(telegram)

    await telegram.send("/settings")
    await telegram.click_button("Сменить фамилию")
    await telegram.send("Юрченко")
    await telegram.click_button("Это я")

    saved = await storage.get_subscription(777)
    assert saved.student_name == "Iurchenko Kseniia"
    assert saved.frequency == DAILY, "смена фамилии не должна сбрасывать рассылку"


async def test_frequency_can_be_changed_from_settings(app):
    telegram, storage, _ = app
    await complete_setup(telegram)

    await telegram.send("/settings")
    await telegram.click_button("Периодичность")
    await telegram.click_button("Раз в неделю")
    await telegram.click_button("09:00")

    saved = await storage.get_subscription(777)
    assert saved.frequency == WEEKLY
    assert saved.send_hour == 9
    assert saved.student_name == "Shishlov Egor", "смена рассылки не должна терять студента"


async def test_stop_removes_subscription(app):
    telegram, storage, _ = app
    await complete_setup(telegram)
    await telegram.send("/stop")
    assert await storage.get_subscription(777) is None


# --- Заметки -----------------------------------------------------------


async def test_note_via_buttons(app):
    telegram, storage, _ = app
    await complete_setup(telegram)
    telegram.session.clear()

    await telegram.send("/note")
    assert "текст заметки" in telegram.session.texts[-1]

    await telegram.send("Сдать эссе по стратегии")
    assert "Когда напомнить" in telegram.session.texts[-1]

    await telegram.click_button("Завтра")
    notes = await storage.pending_notes(777)
    assert len(notes) == 1
    assert notes[0].text == "Сдать эссе по стратегии"
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    assert notes[0].due_at.date() in {tomorrow, tomorrow - timedelta(days=1)}


async def test_note_one_liner(app):
    telegram, storage, _ = app
    await complete_setup(telegram)

    await telegram.send("/note 05.09 18:30 сдать эссе")
    notes = await storage.pending_notes(777)
    assert notes[0].text == "сдать эссе"
    assert notes[0].due_at.astimezone(timezone.utc).strftime("%d.%m") == "05.09"


async def test_free_text_becomes_a_note_draft(app):
    telegram, storage, _ = app
    await complete_setup(telegram)
    telegram.session.clear()

    await telegram.send("Забрать справку в деканате")
    assert "Сохранить это как заметку" in telegram.session.texts[-1]

    await telegram.click_button("Другая дата")
    await telegram.send("через 3 дня")
    notes = await storage.pending_notes(777)
    assert notes[0].text == "Забрать справку в деканате"


async def test_note_list_and_delete(app):
    telegram, storage, _ = app
    await complete_setup(telegram)
    await telegram.send("/note завтра позвонить научруку")
    note_id = (await storage.pending_notes(777))[0].id

    telegram.session.clear()
    await telegram.send("/notes")
    assert "позвонить научруку" in telegram.session.texts[-1]

    await telegram.send(f"/delnote {note_id}")
    assert "Удалил" in telegram.session.texts[-1]
    assert await storage.pending_notes(777) == []


async def test_html_in_note_does_not_break_message(app):
    telegram, storage, _ = app
    await complete_setup(telegram)

    await telegram.send("<b>дедлайн</b> & отчёт")
    await telegram.click_button("Завтра")
    telegram.session.clear()

    await telegram.send("/notes")
    assert "&lt;b&gt;дедлайн&lt;/b&gt; &amp; отчёт" in telegram.session.texts[-1]


async def test_menu_button_during_setup_is_not_treated_as_surname(app):
    telegram, _, _ = app
    await telegram.send("/start")
    telegram.session.clear()

    await telegram.send("📝 Заметки")
    assert "заметок" in telegram.session.texts[-1].lower()
