"""Разбор HTML-страницы расписания timetable.spbu.ru.

Используется, когда JSON-API недоступен или отдал пустоту. Разметка взята с
живой страницы недели: день — панель `panel panel-default` с заголовком
`panel-title`, занятие — `li.common-list-item`, а внутри него колонки
`studyevent-datetime`, `studyevent-subject`, `studyevent-locations`,
`studyevent-educators`. Деление потока подписано отдельным блоком с иконкой
`glyphicon-transfer` («Подгруппа 2»).
"""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from .models import Day, Event, Schedule

TIME_RE = re.compile(r"(\d{1,2}[:.]\d{2})\s*[–—-]\s*(\d{1,2}[:.]\d{2})")
DAY_DATE_RU = re.compile(r"(\d{1,2})\s+([А-Яа-яЁё]+)\s*(\d{4})?")
DAY_DATE_EN = re.compile(r"([A-Za-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?")

MONTHS_RU = {
    "янва": 1, "февра": 2, "март": 3, "апре": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "август": 8, "сентяб": 9, "октяб": 10, "нояб": 11, "декаб": 12,
}
MONTHS_EN = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

CANCELED_RE = re.compile(r"отмен|cancel", re.I)


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - lxml отсутствует
        return BeautifulSoup(html, "html.parser")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_day_date(text: str, fallback_year: int | None = None) -> date | None:
    """«понедельник, 14 сентября» или «Monday, September 14» -> дата."""
    year = fallback_year or datetime.now().year

    match = DAY_DATE_RU.search(text or "")
    if match:
        day, word = int(match.group(1)), match.group(2).lower()
        if match.group(3):
            year = int(match.group(3))
        for prefix, number in MONTHS_RU.items():
            if word.startswith(prefix):
                return _safe_date(year, number, day)

    match = DAY_DATE_EN.search(text or "")
    if match:
        word, day = match.group(1).lower(), int(match.group(2))
        if match.group(3):
            year = int(match.group(3))
        number = MONTHS_EN.get(word[:3])
        if number:
            return _safe_date(year, number, day)
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_schedule_html(html: str, group_id: int, fallback_year: int | None = None) -> Schedule:
    soup = _soup(html)

    header = soup.find("h2")
    group_name = _clean(header.get_text()) if header else ""

    days: list[Day] = []
    for panel in soup.select("div.panel"):
        title_node = panel.select_one(".panel-title, .panel-heading")
        if title_node is None:
            continue
        title = _clean(title_node.get_text())
        events = [
            event
            for item in panel.select("li.common-list-item")
            if (event := _parse_event(item)) is not None
        ]
        day_date = parse_day_date(title, fallback_year)
        if not events and day_date is None:
            continue
        days.append(Day(date=day_date, title=title, events=events))

    return Schedule(group_id=group_id, group_name=group_name, days=days)


def _parse_event(item: Tag) -> Event | None:
    subject_block = item.select_one(".studyevent-subject")
    if subject_block is None:
        return None

    blocks = subject_block.select(".with-icon")
    subject = _clean(blocks[0].get_text()) if blocks else _clean(subject_block.get_text())
    if not subject:
        return None

    # Второй блок с иконкой — деление потока: «Подгруппа 2», «Subgroup 2».
    subgroup = " ".join(_clean(block.get_text()) for block in blocks[1:]).strip()

    time_block = item.select_one(".studyevent-datetime")
    time_text = _clean(time_block.get_text()) if time_block else ""
    match = TIME_RE.search(time_text)
    time_text = f"{match.group(1)}–{match.group(2)}".replace(".", ":") if match else time_text

    location_block = item.select_one(".studyevent-locations")
    locations = ""
    if location_block is not None:
        address = location_block.select_one(".address-modal-btn")
        locations = _clean((address or location_block).get_text())

    educator_block = item.select_one(".studyevent-educators")
    educators = _clean(educator_block.get_text()) if educator_block else ""

    return Event(
        subject=subject[:300],
        time_text=time_text,
        locations=locations,
        educators=educators,
        subgroup=subgroup,
        is_canceled=bool(CANCELED_RE.search(_clean(item.get_text()))),
    )
