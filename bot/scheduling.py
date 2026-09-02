"""Расчёт времени следующей рассылки.

Все функции чистые: время хранится в UTC, а пользователь задаёт часы и
минуты в своём часовом поясе. Переход на летнее время и високосные годы
отдаются на откуп ``zoneinfo``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
OFF = "off"

FREQUENCIES = (DAILY, WEEKLY, MONTHLY)

FREQUENCY_TITLES = {
    DAILY: "раз в день",
    WEEKLY: "раз в неделю",
    MONTHLY: "раз в месяц",
    OFF: "рассылка выключена",
}


def to_utc(moment: datetime) -> datetime:
    """Приводит время к UTC (наивное считается уже UTC)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _local_at(day: date, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def _first_day_of_next_month(day: date) -> date:
    return date(day.year + (day.month == 12), 1 if day.month == 12 else day.month + 1, 1)


def next_run_at(
    frequency: str,
    hour: int,
    minute: int,
    tz: ZoneInfo,
    after: datetime | None = None,
) -> datetime | None:
    """Ближайший момент рассылки строго позже ``after`` (в UTC).

    * ``daily`` — каждый день в заданное время;
    * ``weekly`` — по понедельникам (расписание на всю неделю вперёд);
    * ``monthly`` — первого числа каждого месяца.
    """
    if frequency not in FREQUENCIES:
        return None
    now_utc = to_utc(after or datetime.now(timezone.utc))
    now_local = now_utc.astimezone(tz)

    if frequency == DAILY:
        candidate = _local_at(now_local.date(), hour, minute, tz)
        if candidate <= now_local:
            candidate = _local_at(now_local.date() + timedelta(days=1), hour, minute, tz)
    elif frequency == WEEKLY:
        monday = now_local.date() - timedelta(days=now_local.weekday())
        candidate = _local_at(monday, hour, minute, tz)
        if candidate <= now_local:
            candidate = _local_at(monday + timedelta(days=7), hour, minute, tz)
    else:
        first = now_local.date().replace(day=1)
        candidate = _local_at(first, hour, minute, tz)
        if candidate <= now_local:
            candidate = _local_at(_first_day_of_next_month(now_local.date()), hour, minute, tz)

    return candidate.astimezone(timezone.utc)


def period_for(frequency: str, moment: datetime, tz: ZoneInfo) -> tuple[date, date]:
    """Период расписания, который отправляем в момент ``moment``."""
    local_day = to_utc(moment).astimezone(tz).date()
    if frequency == DAILY:
        return local_day, local_day
    if frequency == WEEKLY:
        monday = local_day - timedelta(days=local_day.weekday())
        return monday, monday + timedelta(days=6)
    if frequency == MONTHLY:
        first = local_day.replace(day=1)
        return first, _first_day_of_next_month(first) - timedelta(days=1)
    return local_day, local_day
