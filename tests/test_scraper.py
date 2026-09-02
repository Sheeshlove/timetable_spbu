"""Резервный разбор HTML расписания."""

from datetime import date

from bot.timetable import scraper
from conftest import fixture


def test_parse_schedule_html():
    schedule = scraper.parse_schedule_html(fixture("week_page.html"), 474489, 2026)
    assert schedule.group_name == "Менеджмент, 2026, группа 1"
    assert [day.date for day in schedule.days] == [date(2026, 8, 31), date(2026, 9, 1)]

    monday = schedule.days[0]
    assert len(monday.events) == 2, "вложенные узлы не должны считаться занятиями"
    assert monday.events[0].subject == "Микроэкономика, лекция"
    assert monday.events[0].interval == "10:00–11:35"
    assert monday.events[0].educators == "Иванов Иван Иванович, доцент"
    assert monday.events[0].locations == "Волховский пер., д. 3, ауд. 42"
    assert monday.events[1].is_canceled is True


def test_parse_schedule_html_survives_empty_page():
    schedule = scraper.parse_schedule_html("<html><body></body></html>", 1)
    assert schedule.days == []
    assert schedule.is_empty is True
