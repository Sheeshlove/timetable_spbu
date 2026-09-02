"""Разбор HTML страницы расписания — на настоящей странице сайта."""

from datetime import date

from bot.timetable import scraper
from bot.timetable.scraper import parse_day_date
from conftest import fixture

HTML = fixture("week_page_ru.html")


def test_parses_whole_week():
    schedule = scraper.parse_schedule_html(HTML, 474489, 2026)
    assert schedule.group_name == "Группа 26.М01-вшм"
    assert [day.date for day in schedule.days] == [
        date(2026, 9, 14),
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
        date(2026, 9, 18),
        date(2026, 9, 19),
    ]
    assert sum(len(day.events) for day in schedule.days) == 32


def test_event_fields():
    schedule = scraper.parse_schedule_html(HTML, 474489, 2026)
    monday = schedule.days[0]
    first = monday.events[0]
    assert first.interval == "09:00–10:30"
    assert first.subject == "Факультатив. Иностранный язык (испанский), семинар"
    assert first.educators == "Смыченко Ю. И."
    assert first.locations == "Волховский переулок, д. 3, лит. А,215"
    assert first.subgroup == ""
    assert first.is_canceled is False


def test_subgroup_is_extracted():
    schedule = scraper.parse_schedule_html(HTML, 474489, 2026)
    seminars = [
        event
        for day in schedule.days
        for event in day.events
        if "Количественные методы" in event.subject
    ]
    assert [event.subgroup for event in seminars] == [
        "Подгруппа 1",
        "Подгруппа 2",
        "Подгруппа 3",
        "Подгруппа 4",
    ]


def test_online_event_has_no_address():
    schedule = scraper.parse_schedule_html(HTML, 474489, 2026)
    online = next(
        event
        for day in schedule.days
        for event in day.events
        if "программирования" in event.subject
    )
    assert "информационно-коммуникационных технологий" in online.locations


def test_empty_page():
    schedule = scraper.parse_schedule_html("<html><body></body></html>", 1)
    assert schedule.days == []
    assert schedule.is_empty is True


def test_parse_day_date_both_languages():
    assert parse_day_date("понедельник, 14 сентября", 2026) == date(2026, 9, 14)
    assert parse_day_date("Monday, September 14", 2026) == date(2026, 9, 14)
    assert parse_day_date("суббота, 19 сентября 2026") == date(2026, 9, 19)
    assert parse_day_date("что-то без даты") is None
