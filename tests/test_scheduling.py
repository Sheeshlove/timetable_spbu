"""Расчёт времени рассылки."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from bot.scheduling import DAILY, MONTHLY, OFF, WEEKLY, next_run_at, period_for

TZ = ZoneInfo("Europe/Moscow")


def moscow(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


def run(frequency: str, at: str, hour: int = 8) -> str:
    result = next_run_at(frequency, hour, 0, TZ, after=moscow(at))
    return result.astimezone(TZ).strftime("%Y-%m-%d %H:%M")


def test_daily_today_then_tomorrow():
    assert run(DAILY, "2026-08-28 07:00") == "2026-08-28 08:00"
    assert run(DAILY, "2026-08-28 08:00") == "2026-08-29 08:00"
    assert run(DAILY, "2026-08-28 20:00") == "2026-08-29 08:00"


def test_weekly_lands_on_monday():
    # пятница -> ближайший понедельник
    assert run(WEEKLY, "2026-08-28 12:00") == "2026-08-31 08:00"
    # понедельник до времени рассылки -> сегодня
    assert run(WEEKLY, "2026-08-31 07:00") == "2026-08-31 08:00"
    # понедельник после -> через неделю
    assert run(WEEKLY, "2026-08-31 09:00") == "2026-09-07 08:00"


def test_monthly_lands_on_first_day():
    assert run(MONTHLY, "2026-08-28 12:00") == "2026-09-01 08:00"
    assert run(MONTHLY, "2026-12-05 12:00") == "2027-01-01 08:00"
    assert run(MONTHLY, "2026-09-01 07:30") == "2026-09-01 08:00"


def test_off_has_no_next_run():
    assert next_run_at(OFF, 8, 0, TZ, after=moscow("2026-08-28 12:00")) is None


def test_result_is_utc():
    result = next_run_at(DAILY, 8, 0, TZ, after=moscow("2026-08-28 09:00"))
    assert result.tzinfo == timezone.utc
    assert result.hour == 5  # 08:00 МСК = 05:00 UTC


def test_naive_input_is_treated_as_utc():
    naive = datetime(2026, 8, 28, 3, 0)
    assert next_run_at(DAILY, 8, 0, TZ, after=naive).isoformat() == "2026-08-28T05:00:00+00:00"


def test_periods():
    friday = moscow("2026-08-28 12:00")
    assert period_for(DAILY, friday, TZ) == (date(2026, 8, 28), date(2026, 8, 28))
    assert period_for(WEEKLY, friday, TZ) == (date(2026, 8, 24), date(2026, 8, 30))
    assert period_for(MONTHLY, friday, TZ) == (date(2026, 8, 1), date(2026, 8, 31))


def test_monthly_period_in_february():
    assert period_for(MONTHLY, moscow("2028-02-10 12:00"), TZ) == (
        date(2028, 2, 1),
        date(2028, 2, 29),
    )
