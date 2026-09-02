"""Разбор дат, которые пользователь пишет словами или цифрами."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

RELATIVE = {
    "сегодня": 0,
    "завтра": 1,
    "послезавтра": 2,
    "today": 0,
    "tomorrow": 1,
    "day after tomorrow": 2,
}

WEEKDAY_WORDS = {
    "понедельник": 0, "вторник": 1, "среда": 2, "среду": 2, "четверг": 3,
    "пятница": 4, "пятницу": 4, "суббота": 5, "субботу": 5, "воскресенье": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

MONTH_WORDS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

DATE_DOTTED = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b")
DATE_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
DATE_WORDS = re.compile(r"\b(\d{1,2})\s+([а-яёa-z]{3,})\b", re.IGNORECASE)
# «September 5», «Sep 5» — в английском месяц идёт первым
DATE_WORDS_EN = re.compile(r"\b([a-z]{3,})\s+(\d{1,2})\b", re.IGNORECASE)
TIME_COLON = re.compile(r"\b(\d{1,2}):(\d{2})\b")
TIME_DOTTED = re.compile(r"\b(\d{1,2})\.(\d{2})\b")
IN_DAYS = re.compile(
    r"(?:через|in)\s+(\d{1,3})\s*(день|дня|дней|недел\w*|days?|weeks?)", re.IGNORECASE
)
LEADING_PREPOSITION = re.compile(r"^(?:в|во|на|к|ко|до|по|on|at|by)\s+", re.IGNORECASE)


class DateParseError(ValueError):
    """Не удалось понять дату."""


def parse_due(
    text: str,
    tz: ZoneInfo,
    *,
    default_time: time = time(9, 0),
    now: datetime | None = None,
) -> datetime:
    """Превращает пользовательский текст в момент отправки (UTC).

    Понимает «завтра», «через 3 дня», «в пятницу», «05.09», «05.09.2026 18:30»,
    «5 сентября», «2026-09-05». Прошедшие даты без года переносятся на
    следующий год, чтобы «01.02» в декабре означало февраль будущего года.
    """
    return split_due(text, tz, default_time=default_time, now=now)[0]


def split_due(
    text: str,
    tz: ZoneInfo,
    *,
    default_time: time = time(9, 0),
    now: datetime | None = None,
) -> tuple[datetime, str]:
    """То же, что ``parse_due``, плюс остаток строки без даты и времени.

    Нужно для быстрой записи одной строкой: «/note 05.09 сдать эссе».
    """
    if not text or not text.strip():
        raise DateParseError("пустая дата")

    original = text.strip()
    lowered = original.lower()
    now_local = (now or datetime.now(timezone.utc)).astimezone(tz)
    today = now_local.date()

    consumed: list[tuple[int, int]] = []

    # Время с двоеточием однозначно, поэтому забираем его сразу; «18.30» без
    # двоеточия ищем уже после даты, иначе «05.09 18.30» распадётся неверно.
    at_time = default_time
    time_match = TIME_COLON.search(lowered)
    if time_match:
        at_time = _time_from(time_match)
        consumed.append(time_match.span())

    target, span = _extract_date(_mask(lowered, consumed), today)
    if target is None:
        raise DateParseError("не нашёл дату")
    consumed.append(span)

    if time_match is None:
        dotted = TIME_DOTTED.search(_mask(lowered, consumed))
        if dotted:
            at_time = _time_from(dotted)
            consumed.append(dotted.span())

    moment = datetime.combine(target, at_time, tzinfo=tz)
    if moment <= now_local and target == today:
        # «сегодня» с уже прошедшим временем — отправим через минуту
        moment = now_local + timedelta(minutes=1)

    rest = " ".join(_mask(original, consumed).split())
    rest = rest.strip(" ,.;:-—–")
    rest = LEADING_PREPOSITION.sub("", rest)
    return moment.astimezone(timezone.utc), rest


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    """Затирает найденные куски пробелами, сохраняя длину строки."""
    chars = list(text)
    for start, end in spans:
        for index in range(start, min(end, len(chars))):
            chars[index] = " "
    return "".join(chars)


def _time_from(match: re.Match[str]) -> time:
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise DateParseError("некорректное время")
    return time(hour, minute)


def _extract_date(text: str, today: date) -> tuple[date | None, tuple[int, int]]:
    """Возвращает найденную дату и её положение в строке."""
    # Длинные слова первыми: «послезавтра» содержит в себе «завтра».
    for word, offset in sorted(RELATIVE.items(), key=lambda item: -len(item[0])):
        position = text.find(word)
        if position >= 0:
            return today + timedelta(days=offset), (position, position + len(word))

    match = IN_DAYS.search(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        step = 7 if unit.startswith(("недел", "week")) else 1
        return today + timedelta(days=amount * step), match.span()

    match = DATE_ISO.search(text)
    if match:
        parsed = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return parsed, match.span()

    match = DATE_DOTTED.search(text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        raw_year = match.group(3)
        if raw_year:
            year = int(raw_year)
            year += 2000 if year < 100 else 0
        else:
            year = today.year
        parsed = _safe_date(year, month, day)
        if parsed and not raw_year and parsed < today:
            parsed = _safe_date(year + 1, month, day)
        return parsed, match.span()

    for pattern, order in ((DATE_WORDS, "dm"), (DATE_WORDS_EN, "md")):
        match = pattern.search(text)
        if not match:
            continue
        if order == "dm":
            day, word = int(match.group(1)), match.group(2).lower()
        else:
            word, day = match.group(1).lower(), int(match.group(2))
        for prefix, month in sorted(MONTH_WORDS.items(), key=lambda item: -len(item[0])):
            if word.startswith(prefix):
                parsed = _safe_date(today.year, month, day)
                if parsed and parsed < today:
                    parsed = _safe_date(today.year + 1, month, day)
                return parsed, match.span()

    for word, weekday in WEEKDAY_WORDS.items():
        position = text.find(word)
        if position >= 0:
            ahead = (weekday - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead), (position, position + len(word))

    return None, (0, 0)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
