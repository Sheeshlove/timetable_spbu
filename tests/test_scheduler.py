"""Фоновая рассылка: расписание и заметки."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramForbiddenError

from bot.config import Settings
from bot.roster import load_roster
from bot.scheduler import Scheduler
from bot.scheduling import DAILY, WEEKLY
from bot.storage import Storage, Subscription, utcnow
from bot.timetable import TimetableError
from bot.timetable.models import Day, Event, Schedule

TZ = ZoneInfo("Europe/Moscow")


class FakeBot:
    def __init__(self, fail_with: Exception | None = None):
        self.sent: list[tuple[int, str]] = []
        self.fail_with = fail_with

    async def send_message(self, chat_id, text, **kwargs):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((chat_id, text))


class FakeTimetable:
    def __init__(self, schedule: Schedule | None = None, error: Exception | None = None):
        self.schedule_result = schedule
        self.error = error
        self.calls: list[tuple[int, date, date]] = []
        self.langs: list[str] = []

    async def schedule(self, group_id, start, end, alias=None, lang="ru"):
        self.calls.append((group_id, start, end))
        self.langs.append(lang)
        if self.error is not None:
            raise self.error
        return self.schedule_result


ROSTER = load_roster()


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        bot_token="test",
        db_path=tmp_path / "test.sqlite3",
        tz_name="Europe/Moscow",
        base_url="https://timetable.spbu.ru",
        http_cache_ttl=0,
        http_timeout=5,
        log_level="INFO",
        group_id=474489,
        division_alias="GSOM",
        program_title="Master in Management, 2026",
    )


def sample_schedule() -> Schedule:
    return Schedule(
        group_id=474489,
        group_name="Менеджмент 2026",
        days=[
            Day(
                date=date(2026, 8, 31),
                title="",
                events=[Event(subject="Микроэкономика", time_text="10:00–11:35")],
            )
        ],
    )


@pytest.fixture
async def storage(tmp_path):
    store = Storage(tmp_path / "test.sqlite3")
    await store.connect()
    yield store
    await store.close()


def subscription(**overrides) -> Subscription:
    defaults = dict(
        user_id=1,
        chat_id=100,
        student_name="Shishlov Egor",
        frequency=DAILY,
        send_hour=8,
        send_minute=0,
    )
    defaults.update(overrides)
    return Subscription(**defaults)


async def test_digest_is_sent_and_next_run_advances(storage, tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)  # 08:00 МСК
    await storage.save_subscription(subscription(next_run_at=now))
    bot, timetable = FakeBot(), FakeTimetable(sample_schedule())
    scheduler = Scheduler(bot, storage, timetable, make_settings(tmp_path), ROSTER)

    assert await scheduler.tick(now) == 1
    assert bot.sent[0][0] == 100
    assert "Микроэкономика" in bot.sent[0][1]
    # Первый заход — рассылка; следом тикер снимает слепок для слежения.
    assert timetable.calls[0] == (474489, date(2026, 8, 31), date(2026, 8, 31))

    updated = await storage.get_subscription(1)
    assert updated.next_run_at == now + timedelta(days=1)


async def test_weekly_digest_covers_whole_week(storage, tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    await storage.save_subscription(subscription(frequency=WEEKLY, next_run_at=now))
    timetable = FakeTimetable(sample_schedule())
    scheduler = Scheduler(FakeBot(), storage, timetable, make_settings(tmp_path), ROSTER)

    await scheduler.tick(now)
    assert timetable.calls[0] == (474489, date(2026, 8, 31), date(2026, 9, 6))
    assert (await storage.get_subscription(1)).next_run_at == now + timedelta(days=7)


async def test_nothing_is_sent_before_time(storage, tmp_path):
    due = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    await storage.save_subscription(subscription(next_run_at=due))
    bot = FakeBot()
    scheduler = Scheduler(
        bot, storage, FakeTimetable(sample_schedule()), make_settings(tmp_path), ROSTER
    )

    assert await scheduler.tick(due - timedelta(minutes=1)) == 0
    assert bot.sent == []


async def test_site_failure_reschedules_instead_of_skipping(storage, tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    await storage.save_subscription(subscription(next_run_at=now))
    bot = FakeBot()
    scheduler = Scheduler(
        bot,
        storage,
        FakeTimetable(error=TimetableError("сайт лёг")),
        make_settings(tmp_path),
        ROSTER,
    )

    assert await scheduler.tick(now) == 0
    assert bot.sent == []
    assert (await storage.get_subscription(1)).next_run_at == now + timedelta(minutes=15)


async def test_blocked_user_stops_receiving(storage, tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    await storage.save_subscription(subscription(next_run_at=now))
    bot = FakeBot(fail_with=TelegramForbiddenError(method=None, message="bot was blocked"))
    scheduler = Scheduler(
        bot, storage, FakeTimetable(sample_schedule()), make_settings(tmp_path), ROSTER
    )

    assert await scheduler.tick(now) == 0
    assert (await storage.get_subscription(1)).next_run_at is None


async def test_missed_digest_is_delivered_after_downtime(storage, tmp_path):
    """Бот лежал сутки — рассылка не теряется, а уходит при первом такте."""
    missed = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    await storage.save_subscription(subscription(next_run_at=missed))
    bot = FakeBot()
    scheduler = Scheduler(
        bot, storage, FakeTimetable(sample_schedule()), make_settings(tmp_path), ROSTER
    )

    later = missed + timedelta(days=1, hours=3)
    assert await scheduler.tick(later) == 1
    assert (await storage.get_subscription(1)).next_run_at > later


async def test_note_is_sent_once(storage, tmp_path):
    now = utcnow()
    await storage.add_note(1, 100, "Сдать эссе", now - timedelta(minutes=1))
    bot = FakeBot()
    scheduler = Scheduler(
        bot, storage, FakeTimetable(sample_schedule()), make_settings(tmp_path), ROSTER
    )

    assert await scheduler.tick(now) == 1
    assert "Сдать эссе" in bot.sent[0][1]
    assert await storage.pending_notes(1) == []
    assert await scheduler.tick(now) == 0  # повторно не уходит


async def test_future_note_waits(storage, tmp_path):
    now = utcnow()
    await storage.add_note(1, 100, "Потом", now + timedelta(hours=2))
    bot = FakeBot()
    scheduler = Scheduler(
        bot, storage, FakeTimetable(sample_schedule()), make_settings(tmp_path), ROSTER
    )

    assert await scheduler.tick(now) == 0
    assert len(await storage.pending_notes(1)) == 1


async def test_note_to_blocked_user_is_closed(storage, tmp_path):
    now = utcnow()
    await storage.add_note(1, 100, "Заметка", now)
    bot = FakeBot(fail_with=TelegramForbiddenError(method=None, message="blocked"))
    scheduler = Scheduler(
        bot, storage, FakeTimetable(sample_schedule()), make_settings(tmp_path), ROSTER
    )

    assert await scheduler.tick(now) == 0
    assert await storage.pending_notes(1) == []


async def cohort_schedule() -> Schedule:
    """День с занятиями двух когорт сразу."""
    return Schedule(
        group_id=474489,
        group_name="MiM 2026",
        days=[
            Day(
                date=date(2026, 8, 31),
                title="",
                events=[
                    Event(subject="Corporate Finance (Coh.1)", time_text="10:00–11:35"),
                    Event(subject="Corporate Finance (Coh.2)", time_text="12:00–13:35"),
                ],
            )
        ],
    )


async def test_digest_keeps_only_my_cohort(storage, tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    await storage.save_subscription(subscription(next_run_at=now))
    bot = FakeBot()
    scheduler = Scheduler(
        bot, storage, FakeTimetable(await cohort_schedule()), make_settings(tmp_path), ROSTER
    )

    await scheduler.tick(now)
    text = bot.sent[0][1]
    assert "Coh.2" in text
    assert "Coh.1" not in text
    assert "Скрыто занятий других когорт: 1" in text


async def test_show_all_disables_cohort_filter(storage, tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    await storage.save_subscription(subscription(show_all=True, next_run_at=now))
    bot = FakeBot()
    scheduler = Scheduler(
        bot, storage, FakeTimetable(await cohort_schedule()), make_settings(tmp_path), ROSTER
    )

    await scheduler.tick(now)
    text = bot.sent[0][1]
    assert "Coh.1" in text and "Coh.2" in text
    assert "Скрыто" not in text


async def test_unknown_student_gets_full_schedule(storage, tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    await storage.save_subscription(
        subscription(student_name="Кого-то Отчислили", next_run_at=now)
    )
    bot = FakeBot()
    scheduler = Scheduler(
        bot, storage, FakeTimetable(await cohort_schedule()), make_settings(tmp_path), ROSTER
    )

    await scheduler.tick(now)
    text = bot.sent[0][1]
    assert "Coh.1" in text and "Coh.2" in text
    assert "Вас нет в текущем списке" in text


# --- Слежение за изменениями ---------------------------------------------

DAY = datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc)  # 09:00 МСК, рабочее время
WINDOW = (date(2026, 8, 31), date(2026, 9, 14))


def changed_schedule() -> Schedule:
    """То же расписание, но добавилась ещё одна пара."""
    return Schedule(
        group_id=474489,
        group_name="Менеджмент 2026",
        days=[
            Day(
                date=date(2026, 8, 31),
                title="",
                events=[
                    Event(subject="Микроэкономика", time_text="10:00–11:35"),
                    Event(subject="Маркетинг", time_text="12:00–13:35"),
                ],
            )
        ],
    )


class RangeTimetable(FakeTimetable):
    """Фейк, который честно отдаёт только дни из запрошенного окна."""

    async def schedule(self, group_id, start, end, alias=None, lang="ru"):
        full = await super().schedule(group_id, start, end, alias, lang)
        days = [day for day in full.days if day.date and start <= day.date <= end]
        return Schedule(
            group_id=full.group_id, group_name=full.group_name, days=days, url=full.url
        )


async def test_first_check_only_remembers_schedule(storage, tmp_path):
    """Первую проверку сравнивать не с чем — молчим и запоминаем."""
    await storage.save_subscription(subscription())
    bot, timetable = FakeBot(), FakeTimetable(sample_schedule())
    scheduler = Scheduler(bot, storage, timetable, make_settings(tmp_path), ROSTER)

    assert await scheduler.tick(DAY) == 0
    assert bot.sent == []
    assert timetable.calls == [(474489, *WINDOW)]

    snapshot = await storage.get_snapshot(1)
    assert [item.subject for item in snapshot.slots] == ["Микроэкономика"]
    assert (await storage.get_subscription(1)).next_check_at == DAY + timedelta(hours=3)


async def test_new_class_is_reported(storage, tmp_path):
    await storage.save_subscription(subscription())
    bot, timetable = FakeBot(), FakeTimetable(sample_schedule())
    scheduler = Scheduler(bot, storage, timetable, make_settings(tmp_path), ROSTER)
    await scheduler.tick(DAY)

    timetable.schedule_result = changed_schedule()
    later = DAY + timedelta(hours=3)
    assert await scheduler.tick(later) == 1

    chat, text = bot.sent[0]
    assert chat == 100
    assert "Расписание изменилось" in text
    assert "Маркетинг" in text
    assert "Микроэкономика" not in text  # не менялась — и в письме её нет
    assert (await storage.get_subscription(1)).next_check_at == later + timedelta(hours=3)


async def test_unchanged_schedule_is_silent(storage, tmp_path):
    await storage.save_subscription(subscription())
    bot, timetable = FakeBot(), FakeTimetable(sample_schedule())
    scheduler = Scheduler(bot, storage, timetable, make_settings(tmp_path), ROSTER)

    await scheduler.tick(DAY)
    assert await scheduler.tick(DAY + timedelta(hours=3)) == 0
    assert bot.sent == []


async def test_changed_filter_rebaselines_without_message(storage, tmp_path):
    """Студент сам переключил фильтр — это не изменение расписания."""
    await storage.save_subscription(subscription())
    bot, timetable = FakeBot(), FakeTimetable(await cohort_schedule())
    scheduler = Scheduler(bot, storage, timetable, make_settings(tmp_path), ROSTER)
    await scheduler.tick(DAY)

    await storage.save_subscription(subscription(show_all=True))
    later = DAY + timedelta(hours=3)
    assert await scheduler.tick(later) == 0
    assert bot.sent == []

    snapshot = await storage.get_snapshot(1)
    assert len(snapshot.slots) == 2  # запомнили уже расписание без фильтра


async def test_sliding_window_is_not_a_change(storage, tmp_path):
    """Вчерашний день ушёл из окна — «отменённых» пар быть не должно."""
    await storage.save_subscription(subscription())
    bot = FakeBot()
    scheduler = Scheduler(
        bot, storage, RangeTimetable(sample_schedule()), make_settings(tmp_path), ROSTER
    )

    await scheduler.tick(DAY)
    assert await scheduler.tick(DAY + timedelta(days=1)) == 0
    assert bot.sent == []


async def test_quiet_hours_postpone_the_check(storage, tmp_path):
    """Ночью бот не будит: проверка переезжает на утро."""
    await storage.save_subscription(subscription())
    night = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)  # 03:00 МСК
    timetable = FakeTimetable(sample_schedule())
    scheduler = Scheduler(FakeBot(), storage, timetable, make_settings(tmp_path), ROSTER)

    assert await scheduler.tick(night) == 0
    assert timetable.calls == []  # на сайт даже не ходили
    assert (await storage.get_subscription(1)).next_check_at == datetime(
        2026, 8, 31, 5, 0, tzinfo=timezone.utc
    )  # 08:00 МСК


async def test_late_evening_check_waits_for_morning(storage, tmp_path):
    await storage.save_subscription(subscription())
    evening = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)  # 23:00 МСК
    scheduler = Scheduler(
        FakeBot(), storage, FakeTimetable(sample_schedule()), make_settings(tmp_path), ROSTER
    )

    await scheduler.tick(evening)
    assert (await storage.get_subscription(1)).next_check_at == datetime(
        2026, 9, 1, 5, 0, tzinfo=timezone.utc
    )


async def test_site_failure_keeps_the_snapshot(storage, tmp_path):
    await storage.save_subscription(subscription())
    timetable = FakeTimetable(sample_schedule())
    scheduler = Scheduler(FakeBot(), storage, timetable, make_settings(tmp_path), ROSTER)
    await scheduler.tick(DAY)

    timetable.error = TimetableError("сайт лёг")
    later = DAY + timedelta(hours=3)
    assert await scheduler.tick(later) == 0

    snapshot = await storage.get_snapshot(1)
    assert [item.subject for item in snapshot.slots] == ["Микроэкономика"]
    assert (await storage.get_subscription(1)).next_check_at == later + timedelta(minutes=15)


async def test_watching_can_be_turned_off(storage, tmp_path):
    await storage.save_subscription(subscription(notify_changes=False))
    timetable = FakeTimetable(sample_schedule())
    scheduler = Scheduler(FakeBot(), storage, timetable, make_settings(tmp_path), ROSTER)

    assert await scheduler.tick(DAY) == 0
    assert timetable.calls == []
    assert await storage.get_snapshot(1) is None


async def test_blocked_user_is_no_longer_watched(storage, tmp_path):
    await storage.save_subscription(subscription())
    bot, timetable = FakeBot(), FakeTimetable(sample_schedule())
    scheduler = Scheduler(bot, storage, timetable, make_settings(tmp_path), ROSTER)
    await scheduler.tick(DAY)

    bot.fail_with = TelegramForbiddenError(method=None, message="bot was blocked")
    timetable.schedule_result = changed_schedule()
    assert await scheduler.tick(DAY + timedelta(hours=3)) == 0
    assert (await storage.get_subscription(1)).notify_changes is False


async def test_one_request_per_language_for_many_students(storage, tmp_path):
    """Группа у всех одна: на десять студентов — один заход на сайт."""
    for user_id in range(1, 11):
        await storage.save_subscription(subscription(user_id=user_id, chat_id=100 + user_id))
    timetable = FakeTimetable(sample_schedule())
    scheduler = Scheduler(FakeBot(), storage, timetable, make_settings(tmp_path), ROSTER)

    await scheduler.tick(DAY)
    assert timetable.calls == [(474489, *WINDOW)]
    assert len((await storage.get_snapshot(10)).slots) == 1
