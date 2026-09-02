"""Резервный разбор HTML-страниц timetable.spbu.ru.

Используется, когда JSON-API недоступен или изменился. Парсер намеренно
терпим к разметке: он опирается на структуру классов вида `day`,
`study-event` и на текстовые заголовки, а не на конкретную вёрстку
бутстрапа, которая на сайте меняется чаще всего.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from .models import Day, Event, Schedule

DATE_RE = re.compile(r"(\d{1,2})\s+([А-Яа-яЁё]+)\s*(\d{4})?")
TIME_RE = re.compile(r"\d{1,2}[:.]\d{2}\s*[–—-]\s*\d{1,2}[:.]\d{2}")
DAY_CLASS_RE = re.compile(r"^days?(-(container|panel|wrapper|block))?$", re.I)

MONTHS = {
    "янва": 1, "февра": 2, "март": 3, "апре": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "август": 8, "сентяб": 9, "октяб": 10, "нояб": 11, "декаб": 12,
}


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - lxml отсутствует
        return BeautifulSoup(html, "html.parser")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _outermost(nodes: list[Tag]) -> list[Tag]:
    """Оставляет только внешние узлы: `study-event-time` лежит внутри
    `study-event` и тоже попадает под регулярное выражение, но отдельным
    занятием не является."""
    result: list[Tag] = []
    for node in nodes:
        if any(parent is other for other in nodes for parent in node.parents):
            continue
        result.append(node)
    return result


def _parse_day_date(text: str, fallback_year: int | None = None) -> date | None:
    match = DATE_RE.search(text or "")
    if not match:
        return None
    day = int(match.group(1))
    month_word = match.group(2).lower()
    year = int(match.group(3)) if match.group(3) else (fallback_year or datetime.now().year)
    for prefix, number in MONTHS.items():
        if month_word.startswith(prefix):
            try:
                return date(year, number, day)
            except ValueError:
                return None
    return None


def parse_schedule_html(html: str, group_id: int, fallback_year: int | None = None) -> Schedule:
    """Расписание недели со страницы StudentGroupEvents/Primary."""
    soup = _soup(html)
    group_name = ""
    header = soup.find(["h1", "h2"])
    if header:
        group_name = _clean(header.get_text())

    days: list[Day] = []
    day_nodes = _outermost(
        [
            node
            for node in soup.find_all(True)
            if any(DAY_CLASS_RE.match(name) for name in (node.get("class") or []))
        ]
    )
    for node in day_nodes:
        title_node = node.find(
            attrs={"class": re.compile(r"(day-?header|panel-heading|title)", re.I)}
        )
        title = _clean(title_node.get_text()) if title_node else ""
        if not title:
            title = _clean(node.get_text())[:60]
        day_date = _parse_day_date(title, fallback_year)
        events = _parse_events(node)
        if not events and not day_date:
            continue
        days.append(Day(date=day_date, title=title, events=events))

    if not days:  # разметка без обёрток дней — собираем плоский список
        events = _parse_events(soup)
        if events:
            days.append(Day(date=None, title="", events=events))

    return Schedule(group_id=group_id, group_name=group_name, days=days)


def _parse_events(container: Tag) -> list[Event]:
    events: list[Event] = []
    nodes = _outermost(
        container.find_all(
            attrs={"class": re.compile(r"(study-?event|event-?container|lesson)", re.I)}
        )
    )
    for node in nodes:
        text = _clean(node.get_text(" "))
        if not text:
            continue
        time_node = node.find(attrs={"class": re.compile(r"(time|interval)", re.I)})
        time_text = _clean(time_node.get_text()) if time_node else ""
        if not time_text:
            time_match = TIME_RE.search(text)
            time_text = time_match.group(0) if time_match else ""
        subject_node = node.find(attrs={"class": re.compile(r"(subject|title|name)", re.I)})
        subject = _clean(subject_node.get_text()) if subject_node else ""
        if not subject:
            subject = _clean(text.replace(time_text, " ") if time_text else text) or text
        location_node = node.find(
            attrs={"class": re.compile(r"(location|address|room|place)", re.I)}
        )
        educator_node = node.find(
            attrs={"class": re.compile(r"(educator|teacher|lecturer)", re.I)}
        )
        events.append(
            Event(
                subject=subject[:300],
                time_text=time_text.replace(".", ":"),
                locations=_clean(location_node.get_text()) if location_node else "",
                educators=_clean(educator_node.get_text()) if educator_node else "",
                is_canceled="отмен" in text.lower(),
            )
        )
    return events
