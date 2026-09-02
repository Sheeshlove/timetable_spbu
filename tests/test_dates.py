"""Разбор пользовательских дат для заметок."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from bot.dates import DateParseError, parse_due, split_due

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)  # пятница, 15:00 МСК


def local(text: str):
    return parse_due(text, TZ, now=NOW).astimezone(TZ)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("сегодня 23:00", "28.08.2026 23:00"),
        ("завтра", "29.08.2026 09:00"),
        ("послезавтра", "30.08.2026 09:00"),
        ("через 3 дня", "31.08.2026 09:00"),
        ("через 2 недели", "11.09.2026 09:00"),
        ("05.09 18:30", "05.09.2026 18:30"),
        ("05.09 18.30", "05.09.2026 18:30"),
        ("05.09.2026", "05.09.2026 09:00"),
        ("5 сентября", "05.09.2026 09:00"),
        ("2026-09-05", "05.09.2026 09:00"),
        ("в пятницу", "04.09.2026 09:00"),
        ("в понедельник", "31.08.2026 09:00"),
    ],
)
def test_parse_due(text, expected):
    assert local(text).strftime("%d.%m.%Y %H:%M") == expected


def test_past_date_without_year_moves_to_next_year():
    assert local("01.02").year == 2027


def test_today_with_passed_time_is_pushed_one_minute():
    moment = local("сегодня 09:00")
    assert moment.strftime("%d.%m.%Y %H:%M") == "28.08.2026 15:01"


def test_split_due_returns_note_text():
    due, rest = split_due("05.09 18:30 сдать эссе по стратегии", TZ, now=NOW)
    assert due.astimezone(TZ).strftime("%d.%m %H:%M") == "05.09 18:30"
    assert rest == "сдать эссе по стратегии"


def test_split_due_strips_leading_preposition():
    assert split_due("в пятницу зачёт", TZ, now=NOW)[1] == "зачёт"


def test_split_due_without_text():
    assert split_due("завтра", TZ, now=NOW)[1] == ""


@pytest.mark.parametrize("text", ["", "   ", "просто текст без даты", "99.99"])
def test_unparseable_dates_raise(text):
    with pytest.raises(DateParseError):
        parse_due(text, TZ, now=NOW)


def test_invalid_time_raises():
    with pytest.raises(DateParseError):
        parse_due("05.09 99:99", TZ, now=NOW)


# --- английские формулировки ------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("today 23:00", "28.08.2026 23:00"),
        ("tomorrow", "29.08.2026 09:00"),
        ("in 3 days", "31.08.2026 09:00"),
        ("in 2 weeks", "11.09.2026 09:00"),
        ("September 5", "05.09.2026 09:00"),
        ("Sep 5 18:30", "05.09.2026 18:30"),
        ("on Friday", "04.09.2026 09:00"),
        ("on Monday", "31.08.2026 09:00"),
    ],
)
def test_parse_due_english(text, expected):
    assert local(text).strftime("%d.%m.%Y %H:%M") == expected


def test_split_due_english_note():
    due, rest = split_due("in 3 days deadline for the case", TZ, now=NOW)
    assert due.astimezone(TZ).strftime("%d.%m") == "31.08"
    assert rest == "deadline for the case"


def test_split_due_strips_english_preposition():
    assert split_due("on Friday exam", TZ, now=NOW)[1] == "exam"
