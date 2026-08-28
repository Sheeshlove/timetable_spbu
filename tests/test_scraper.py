"""Резервный разбор HTML."""

from datetime import date

from bot.timetable import scraper
from conftest import fixture


def test_parse_divisions_skips_service_links():
    divisions = scraper.parse_divisions_html(fixture("home_page.html"))
    assert [d.alias for d in divisions] == ["GSOM", "MATH"]
    assert divisions[0].name == "Высшая школа менеджмента"


def test_parse_programs_keeps_level():
    programs = scraper.parse_programs_html(fixture("division_page.html"))
    names = {(p.level, p.name) for p in programs}
    assert ("Магистратура", "38.04.02 Менеджмент") in names
    assert ("Бакалавриат", "38.03.02 Менеджмент") in names


def test_parse_years_links_to_group_ids():
    html = fixture("division_page.html")
    master = next(p for p in scraper.parse_programs_html(html) if p.level == "Магистратура")
    years = scraper.parse_admission_years_html(html, master.key)
    assert [(y.name, y.group_id) for y in years] == [("2026", 474489), ("2025", 460001)]


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
