"""Хранилище: подписки и заметки."""

from datetime import timedelta

import pytest

from bot.storage import Storage, Subscription, utcnow


@pytest.fixture
async def storage(tmp_path):
    store = Storage(tmp_path / "test.sqlite3")
    await store.connect()
    yield store
    await store.close()


def make(**overrides) -> Subscription:
    defaults = dict(
        user_id=1,
        chat_id=100,
        division_alias="GSOM",
        division_name="ВШМ",
        program_key="key",
        program_name="Менеджмент",
        year_name="2026",
        group_id=474489,
        group_name="Группа 1",
    )
    defaults.update(overrides)
    return Subscription(**defaults)


async def test_save_is_idempotent_upsert(storage):
    await storage.save_subscription(make(frequency="daily"))
    await storage.save_subscription(make(frequency="weekly", group_id=999))
    saved = await storage.get_subscription(1)
    assert saved.frequency == "weekly"
    assert saved.group_id == 999


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
