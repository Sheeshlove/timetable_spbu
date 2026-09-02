"""Тексты сообщений."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from pathlib import Path

from bot.config import Settings
from bot.formatting import (
    digest_header,
    format_cohorts,
    format_notes,
    format_schedule,
    format_subscription,
    human_date,
    split_message,
)
from bot.roster import load_roster
from bot.storage import Note, Subscription
from bot.timetable.models import Day, Event, Schedule

TZ = ZoneInfo("Europe/Moscow")
ROSTER = load_roster()
SETTINGS = Settings(
    bot_token="t",
    db_path=Path("x"),
    tz_name="Europe/Moscow",
    base_url="https://timetable.spbu.ru",
    http_cache_ttl=0,
    http_timeout=5,
    log_level="INFO",
    group_id=474489,
    division_alias="GSOM",
    program_title="Master in Management, 2026",
)


def sample(days=None) -> Schedule:
    return Schedule(
        group_id=474489,
        group_name="Менеджмент 2026",
        days=days
        if days is not None
        else [
            Day(
                date=date(2026, 8, 31),
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


def test_human_date():
    assert human_date(date(2026, 8, 31)) == "31 августа, понедельник"


def test_format_schedule_lists_details():
    text = format_schedule(sample(), "Расписание на сегодня")
    assert "Расписание на сегодня" in text
    assert "10:00–11:35" in text
    assert "Иванов И. И." in text
    assert "Волховский пер., 3" in text


def test_empty_schedule_says_so():
    text = format_schedule(sample(days=[Day(date=date(2026, 8, 31), title="", events=[])]))
    assert "Занятий на этот период нет" in text


def test_canceled_event_is_marked():
    schedule = sample(
        days=[Day(date=date(2026, 8, 31), title="", events=[Event(subject="Пара", is_canceled=True)])]
    )
    assert "отменено" in format_schedule(schedule)


def test_html_is_escaped():
    schedule = sample(
        days=[Day(date=date(2026, 8, 31), title="", events=[Event(subject="<b>взлом</b>")])]
    )
    assert "&lt;b&gt;взлом&lt;/b&gt;" in format_schedule(schedule)


def test_long_month_hides_empty_days():
    days = [Day(date=date(2026, 9, day), title="", events=[]) for day in range(1, 29)]
    days[0].events = [Event(subject="Лекция", time_text="10:00–11:35")]
    text = format_schedule(sample(days=days))
    assert text.count("занятий нет") == 0
    assert "Лекция" in text


def test_split_message_respects_limit():
    chunks = split_message("\n".join(f"строка {i}" for i in range(1000)), limit=500)
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "".join(chunk.replace("\n", "") for chunk in chunks).count("строка") == 1000


def test_split_message_breaks_overlong_line():
    chunks = split_message("x" * 250, limit=100)
    assert [len(chunk) for chunk in chunks] == [100, 100, 50]


def test_digest_headers():
    assert digest_header("daily", date(2026, 8, 31), date(2026, 8, 31)).startswith("Расписание на 31")
    assert "неделю" in digest_header("weekly", date(2026, 8, 31), date(2026, 9, 6))
    assert digest_header("monthly", date(2026, 9, 1), date(2026, 9, 30)) == "Расписание на сентябрь 2026"


def test_format_subscription_shows_everything():
    subscription = Subscription(
        user_id=1,
        chat_id=1,
        student_name="Shishlov Egor",
        frequency="daily",
        send_hour=8,
        send_minute=30,
        next_run_at=datetime(2026, 8, 31, 5, 30, tzinfo=timezone.utc),
    )
    text = format_subscription(subscription, SETTINGS, ROSTER)
    assert "Master in Management" in text
    assert "Shishlov Egor" in text
    assert "раз в день" in text
    assert "08:30" in text
    assert "31.08.2026 08:30" in text
    assert "Coh.2" in text, "когорты видно прямо в карточке"


def test_format_subscription_without_student():
    text = format_subscription(Subscription(user_id=1, chat_id=1), SETTINGS, ROSTER)
    assert "Фамилия не указана" in text


def test_format_subscription_for_missing_student():
    subscription = Subscription(user_id=1, chat_id=1, student_name="Кто-то Выбывший")
    assert "не найдены" in format_subscription(subscription, SETTINGS, ROSTER)


def test_format_cohorts():
    text = format_cohorts(ROSTER.get("Shishlov Egor"), ROSTER)
    assert "Corporate Finance" in text and "Coh.2" in text
    assert "MPS I" in text and "Shevchuk 2" in text


def test_schedule_footer_is_rendered():
    text = format_schedule(sample(), "Заголовок", "Скрыто занятий других когорт: 2")
    assert "Скрыто занятий других когорт: 2" in text


def test_format_notes():
    note = Note(id=7, user_id=1, chat_id=1, text="Сдать эссе",
                due_at=datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc))
    text = format_notes([note], TZ)
    assert "#7" in text and "05.09.2026 09:00" in text and "Сдать эссе" in text
    assert "нет запланированных" in format_notes([], TZ)


def test_now_local_uses_given_timezone():
    from bot.formatting import now_local

    assert now_local(TZ).tzinfo is TZ
    assert now_local(ZoneInfo("UTC")).utcoffset().total_seconds() == 0
