"""Сквозной сценарий: настоящий Dispatcher, поддельный Telegram и сайт."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from aiogram.fsm.storage.memory import MemoryStorage

from bot.__main__ import build_dispatcher
from bot.config import Settings
from bot.scheduling import DAILY, WEEKLY
from bot.storage import Storage
from bot.timetable.models import (
    AdmissionYear,
    Day,
    Division,
    Event,
    Program,
    Schedule,
    StudentGroup,
)
from fake_telegram import FakeTelegram


class StubTimetable:
    """Отвечает как сайт, но без сети."""

    def __init__(self) -> None:
        self.schedule_calls: list[tuple[int, date, date]] = []

    async def divisions(self):
        return [
            Division(alias="GSOM", name="Высшая школа менеджмента"),
            Division(alias="MATH", name="Математика и компьютерные науки"),
        ]

    async def programs(self, alias):
        assert alias == "GSOM"
        return [
            Program(key="mag01", name="38.04.02 Менеджмент", level="Магистратура"),
            Program(key="bak01", name="38.03.02 Менеджмент", level="Бакалавриат"),
        ]

    async def admission_years(self, alias, program_key):
        assert program_key == "mag01"
        return [
            AdmissionYear(program_id=12345, name="2026", is_current=True),
            AdmissionYear(program_id=12000, name="2025"),
        ]

    async def groups(self, year):
        if year.program_id == 12345:
            return [
                StudentGroup(group_id=474489, name="Группа 1", study_form="очная"),
                StudentGroup(group_id=474490, name="Группа 2", study_form="очная"),
            ]
        return [StudentGroup(group_id=460001, name="Группа 2025")]

    async def schedule(self, group_id, start, end, alias=None):
        self.schedule_calls.append((group_id, start, end))
        return Schedule(
            group_id=group_id,
            group_name="Менеджмент 2026, группа 1",
            days=[
                Day(
                    date=start,
                    title="",
                    events=[
                        Event(
                            subject="Микроэкономика",
                            time_text="10:00–11:35",
                            educators="Иванов И. И.",
                            locations="Волховский пер., 3",
                        )
                    ],
                )
            ],
        )


SETTINGS = Settings(
    bot_token="42:TEST",
    db_path=Path("unused.sqlite3"),
    tz_name="Europe/Moscow",
    base_url="https://timetable.spbu.ru",
    http_cache_ttl=0,
    http_timeout=5,
    log_level="INFO",
)


@pytest.fixture(scope="module")
def dispatcher():
    """Роутеры aiogram привязываются к одному Dispatcher, поэтому он общий;
    зависимости и состояние диалогов подменяются в каждом тесте."""
    return build_dispatcher(Storage("unused.sqlite3"), StubTimetable(), SETTINGS)


@pytest.fixture
async def app(tmp_path: Path, dispatcher):
    storage = Storage(tmp_path / "bot.sqlite3")
    await storage.connect()
    timetable = StubTimetable()

    dispatcher["storage"] = storage
    dispatcher["client"] = timetable
    dispatcher["settings"] = SETTINGS
    dispatcher.fsm.storage = MemoryStorage()  # чистое состояние на каждый тест

    telegram = FakeTelegram(dispatcher)
    yield telegram, storage, timetable
    await telegram.close()
    await storage.close()


async def complete_wizard(telegram) -> None:
    await telegram.send("/start")
    await telegram.click_button("Высшая школа менеджмента")
    await telegram.click_button("38.04.02 Менеджмент")
    await telegram.click_button("2026")
    await telegram.click_button("Группа 1")
    await telegram.click_button("Раз в день")
    await telegram.click_button("08:00")


async def test_full_setup_wizard_saves_subscription(app):
    telegram, storage, _ = app
    await telegram.send("/start")
    assert "Привет" in telegram.session.texts[0]
    assert "Шаг 1/4" in telegram.session.texts[-1]

    await telegram.click_button("Высшая школа менеджмента")
    assert "Шаг 2/4" in telegram.session.texts[-1]

    await telegram.click_button("38.04.02 Менеджмент")
    assert "Шаг 3/4" in telegram.session.texts[-1]

    await telegram.click_button("2026")
    assert "Шаг 4/4" in telegram.session.texts[-1]

    await telegram.click_button("Группа 1")
    assert "Как часто" in telegram.session.texts[-1]

    await telegram.click_button("Раз в день")
    assert "В какое время" in telegram.session.texts[-1]

    await telegram.click_button("08:00")

    saved = await storage.get_subscription(777)
    assert saved.division_alias == "GSOM"
    assert saved.program_name == "38.04.02 Менеджмент"
    assert saved.year_name == "2026"
    assert saved.group_id == 474489
    assert saved.frequency == DAILY
    assert saved.send_hour == 8
    assert saved.next_run_at is not None


async def test_wizard_back_button_returns_to_previous_step(app):
    telegram, _, _ = app
    await telegram.send("/start")
    await telegram.click_button("Высшая школа менеджмента")
    await telegram.click_button("38.04.02 Менеджмент")
    assert "Шаг 3/4" in telegram.session.texts[-1]

    await telegram.click_button("Назад")
    assert "Шаг 2/4" in telegram.session.texts[-1]


async def test_search_filters_the_list(app):
    telegram, _, _ = app
    await telegram.send("/start")
    await telegram.send("Математика")
    assert "Фильтр: «Математика» — найдено 1" in telegram.session.texts[-1]
    assert any("Математика" in label for label in telegram.session.buttons())


async def test_today_command_requests_and_renders_schedule(app):
    telegram, _, timetable = app
    await complete_wizard(telegram)
    telegram.session.clear()

    await telegram.send("/today")
    today = date.today()
    assert timetable.schedule_calls[-1] == (474489, today, today)
    assert "Микроэкономика" in telegram.session.texts[-1]
    assert "Иванов И. И." in telegram.session.texts[-1]


async def test_week_command_asks_for_monday_to_sunday(app):
    telegram, _, timetable = app
    await complete_wizard(telegram)
    telegram.session.clear()

    await telegram.send("/week")
    group_id, start, end = timetable.schedule_calls[-1]
    assert start.weekday() == 0 and end.weekday() == 6
    assert (end - start).days == 6


async def test_schedule_without_setup_asks_to_configure(app):
    telegram, _, timetable = app
    await telegram.send("/today")
    assert "Сначала выберите группу" in telegram.session.texts[-1]
    assert timetable.schedule_calls == []


async def test_frequency_can_be_changed_from_settings(app):
    telegram, storage, _ = app
    await complete_wizard(telegram)

    await telegram.send("/settings")
    await telegram.click_button("Периодичность")
    await telegram.click_button("Раз в неделю")
    await telegram.click_button("09:00")

    saved = await storage.get_subscription(777)
    assert saved.frequency == WEEKLY
    assert saved.send_hour == 9
    assert saved.group_id == 474489, "смена периодичности не должна терять группу"


async def test_stop_removes_subscription(app):
    telegram, storage, _ = app
    await complete_wizard(telegram)
    await telegram.send("/stop")
    assert await storage.get_subscription(777) is None


async def test_note_via_buttons(app):
    telegram, storage, _ = app
    await complete_wizard(telegram)
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
    await complete_wizard(telegram)

    await telegram.send("/note 05.09 18:30 сдать эссе")
    notes = await storage.pending_notes(777)
    assert notes[0].text == "сдать эссе"
    assert notes[0].due_at.astimezone(timezone.utc).strftime("%d.%m") == "05.09"


async def test_free_text_becomes_a_note_draft(app):
    telegram, storage, _ = app
    await complete_wizard(telegram)
    telegram.session.clear()

    await telegram.send("Забрать справку в деканате")
    assert "Сохранить это как заметку" in telegram.session.texts[-1]

    await telegram.click_button("Другая дата")
    await telegram.send("через 3 дня")
    notes = await storage.pending_notes(777)
    assert notes[0].text == "Забрать справку в деканате"


async def test_note_list_and_delete(app):
    telegram, storage, _ = app
    await complete_wizard(telegram)
    await telegram.send("/note завтра позвонить научруку")
    note_id = (await storage.pending_notes(777))[0].id

    telegram.session.clear()
    await telegram.send("/notes")
    assert "позвонить научруку" in telegram.session.texts[-1]

    await telegram.send(f"/delnote {note_id}")
    assert "Удалил" in telegram.session.texts[-1]
    assert await storage.pending_notes(777) == []


async def test_delnote_with_bad_argument(app):
    telegram, _, _ = app
    await complete_wizard(telegram)
    await telegram.send("/delnote абв")
    assert "Укажите номер заметки" in telegram.session.texts[-1]


async def test_menu_button_during_wizard_is_not_treated_as_search(app):
    telegram, _, _ = app
    await telegram.send("/start")
    telegram.session.clear()

    await telegram.send("📝 Заметки")
    assert not any("Фильтр" in text for text in telegram.session.texts)
    assert "заметок" in telegram.session.texts[-1].lower()


async def test_typed_date_works_instead_of_day_button(app):
    telegram, storage, _ = app
    await complete_wizard(telegram)

    await telegram.send("Забрать зачётку")
    await telegram.send("5 сентября")
    notes = await storage.pending_notes(777)
    assert notes[0].text == "Забрать зачётку"
    assert notes[0].due_at.strftime("%m-%d") == "09-05"


async def test_unparseable_date_asks_again_without_losing_note(app):
    telegram, storage, _ = app
    await complete_wizard(telegram)

    await telegram.send("Написать научруку")
    await telegram.send("когда-нибудь потом")
    assert "Не понял дату" in telegram.session.texts[-1]
    assert await storage.pending_notes(777) == []

    await telegram.send("завтра")
    notes = await storage.pending_notes(777)
    assert len(notes) == 1 and notes[0].text == "Написать научруку"


async def test_group_step_is_skipped_when_only_one_group(app):
    telegram, storage, _ = app
    await telegram.send("/start")
    await telegram.click_button("Высшая школа менеджмента")
    await telegram.click_button("38.04.02 Менеджмент")
    await telegram.click_button("2025")  # у этого года одна группа
    assert "Как часто" in telegram.session.texts[-1]

    await telegram.click_button("Раз в месяц")
    await telegram.click_button("10:00")
    saved = await storage.get_subscription(777)
    assert saved.group_id == 460001
    assert saved.frequency == "monthly"


async def test_html_in_note_does_not_break_message(app):
    telegram, storage, _ = app
    await complete_wizard(telegram)

    await telegram.send("<b>дедлайн</b> & отчёт")
    await telegram.click_button("Завтра")
    telegram.session.clear()

    await telegram.send("/notes")
    assert "&lt;b&gt;дедлайн&lt;/b&gt; &amp; отчёт" in telegram.session.texts[-1]
