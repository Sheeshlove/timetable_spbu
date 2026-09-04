"""Хранилище: подписки и заметки."""

from datetime import date, timedelta

import pytest

from bot.changes import Slot
from bot.storage import Storage, Subscription, utcnow


@pytest.fixture
async def storage(tmp_path):
    store = Storage(tmp_path / "test.sqlite3")
    await store.connect()
    yield store
    await store.close()


def make(**overrides) -> Subscription:
    defaults = dict(user_id=1, chat_id=100, student_name="Shishlov Egor")
    defaults.update(overrides)
    return Subscription(**defaults)


async def test_save_is_idempotent_upsert(storage):
    await storage.save_subscription(make(frequency="daily"))
    await storage.save_subscription(make(frequency="weekly", student_name="Morozov Ilia"))
    saved = await storage.get_subscription(1)
    assert saved.frequency == "weekly"
    assert saved.student_name == "Morozov Ilia"


async def test_show_all_flag_survives(storage):
    await storage.save_subscription(make(show_all=True))
    assert (await storage.get_subscription(1)).show_all is True


async def test_missing_subscription_is_none(storage):
    assert await storage.get_subscription(42) is None


async def test_due_subscriptions_respect_time_and_frequency(storage):
    now = utcnow()
    await storage.save_subscription(make(user_id=1, frequency="daily", next_run_at=now))
    await storage.save_subscription(
        make(user_id=2, frequency="daily", next_run_at=now + timedelta(hours=1))
    )
    await storage.save_subscription(make(user_id=3, frequency="off", next_run_at=now))

    due = await storage.due_subscriptions(now)
    assert [item.user_id for item in due] == [1]


async def test_set_next_run_to_none_pauses_delivery(storage):
    now = utcnow()
    await storage.save_subscription(make(frequency="daily", next_run_at=now))
    await storage.set_next_run(1, None)
    assert await storage.due_subscriptions(now) == []


async def test_delete_subscription(storage):
    await storage.save_subscription(make())
    await storage.delete_subscription(1)
    assert await storage.get_subscription(1) is None


async def test_notes_lifecycle(storage):
    now = utcnow()
    first = await storage.add_note(1, 100, "Первая", now)
    second = await storage.add_note(1, 100, "Вторая", now + timedelta(days=1))
    await storage.add_note(2, 200, "Чужая", now)

    mine = await storage.pending_notes(1)
    assert [note.id for note in mine] == [first, second]

    due = await storage.due_notes(now)
    assert {note.text for note in due} == {"Первая", "Чужая"}

    await storage.mark_note_sent(first)
    assert [note.id for note in await storage.pending_notes(1)] == [second]


async def test_delete_note_only_own(storage):
    note_id = await storage.add_note(1, 100, "Моя", utcnow())
    assert await storage.delete_note(2, note_id) is False
    assert await storage.delete_note(1, note_id) is True
    assert await storage.delete_note(1, note_id) is False


async def test_data_survives_reconnect(storage, tmp_path):
    await storage.save_subscription(make(frequency="daily", next_run_at=utcnow()))
    await storage.close()

    again = Storage(tmp_path / "test.sqlite3")
    await again.connect()
    saved = await again.get_subscription(1)
    assert saved is not None and saved.frequency == "daily"
    await again.close()
    await storage.connect()  # чтобы фикстура корректно закрылась


# --- Слепки расписания -------------------------------------------------

WINDOW = (date(2026, 8, 31), date(2026, 9, 14))
SLOTS = [
    Slot(date="2026-08-31", interval="10:00–11:35", subject="Финансы", locations="ауд. 101"),
    Slot(date="2026-09-01", interval="12:00–13:35", subject="MPS", subgroup="Shevchuk II"),
]


async def test_snapshot_round_trip(storage):
    await storage.save_subscription(make())
    await storage.save_snapshot(1, "key", WINDOW, SLOTS)

    saved = await storage.get_snapshot(1)
    assert saved.filter_key == "key"
    assert saved.window == WINDOW
    assert saved.slots == SLOTS


async def test_snapshot_is_replaced_not_duplicated(storage):
    await storage.save_subscription(make())
    await storage.save_snapshot(1, "key", WINDOW, SLOTS)
    await storage.save_snapshot(1, "other", WINDOW, SLOTS[:1])

    saved = await storage.get_snapshot(1)
    assert saved.filter_key == "other"
    assert len(saved.slots) == 1


async def test_missing_snapshot_is_none(storage):
    assert await storage.get_snapshot(42) is None


async def test_due_for_check_skips_those_who_said_no(storage):
    moment = utcnow()
    await storage.save_subscription(make(user_id=1))  # слежение включено, проверок не было
    await storage.save_subscription(make(user_id=2, notify_changes=False))
    await storage.save_subscription(
        make(user_id=3, next_check_at=moment + timedelta(hours=1))
    )
    await storage.save_subscription(
        make(user_id=4, next_check_at=moment - timedelta(minutes=1))
    )

    due = {item.user_id for item in await storage.due_for_check(moment)}
    assert due == {1, 4}


async def test_set_next_check_and_notify_flag(storage):
    moment = utcnow() + timedelta(hours=3)
    await storage.save_subscription(make())

    await storage.set_next_check(1, moment)
    assert (await storage.get_subscription(1)).next_check_at == moment

    await storage.set_notify_changes(1, False)
    assert (await storage.get_subscription(1)).notify_changes is False


async def test_stop_forgets_the_snapshot(storage):
    await storage.save_subscription(make())
    await storage.save_snapshot(1, "key", WINDOW, SLOTS)

    await storage.delete_subscription(1)
    assert await storage.get_snapshot(1) is None


async def test_snapshot_can_be_forgotten(storage):
    await storage.save_subscription(make())
    await storage.save_snapshot(1, "key", WINDOW, SLOTS)

    await storage.clear_snapshot(1)
    assert await storage.get_snapshot(1) is None
