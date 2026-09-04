"""Сравнение слепков расписания."""

from datetime import date

from bot.changes import Slot, compare, in_window, overlap, take_snapshot
from bot.timetable.models import Day, Event, Schedule


def slot(day: str, interval: str, subject: str, **extra) -> Slot:
    return Slot(date=day, interval=interval, subject=subject, **extra)


def test_snapshot_keeps_only_dated_days():
    schedule = Schedule(
        group_id=1,
        group_name="MiM",
        days=[
            Day(
                date=date(2026, 9, 1),
                title="",
                events=[Event(subject="Финансы", time_text="10:00–11:35")],
            ),
            Day(date=None, title="Без даты", events=[Event(subject="Что-то")]),
        ],
    )
    snapshot = take_snapshot(schedule)
    assert [item.subject for item in snapshot] == ["Финансы"]
    assert snapshot[0].date == "2026-09-01"
    assert snapshot[0].interval == "10:00–11:35"


def test_identical_snapshots_have_no_diff():
    old = [slot("2026-09-01", "10:00", "Финансы")]
    assert compare(old, list(old)).is_empty


def test_added_and_removed():
    old = [slot("2026-09-01", "10:00", "Финансы")]
    new = [slot("2026-09-01", "12:00", "Маркетинг")]
    diff = compare(old, new)
    assert [item.subject for item in diff.added] == ["Маркетинг"]
    assert [item.subject for item in diff.removed] == ["Финансы"]
    assert diff.count == 2


def test_same_lesson_at_another_time_is_a_move():
    old = [slot("2026-09-01", "10:00", "Финансы")]
    new = [slot("2026-09-03", "14:00", "Финансы")]
    diff = compare(old, new)
    assert not diff.added and not diff.removed
    assert len(diff.moved) == 1
    was, now = diff.moved[0]
    assert (was.date, now.date) == ("2026-09-01", "2026-09-03")


def test_subgroups_are_not_confused_with_each_other():
    """Пары разных подгрупп — разные занятия, а не перенос одной."""
    old = [slot("2026-09-01", "10:00", "MPS", subgroup="Shevchuk I")]
    new = [
        slot("2026-09-01", "10:00", "MPS", subgroup="Shevchuk I"),
        slot("2026-09-01", "12:00", "MPS", subgroup="Shevchuk II"),
    ]
    diff = compare(old, new)
    assert not diff.moved
    assert [item.subgroup for item in diff.added] == ["Shevchuk II"]


def test_room_change_is_an_edit():
    old = [slot("2026-09-01", "10:00", "Финансы", locations="ауд. 101")]
    new = [slot("2026-09-01", "10:00", "Финансы", locations="ауд. 202")]
    diff = compare(old, new)
    assert not diff.added and not diff.removed and not diff.moved
    was, now, fields = diff.edited[0]
    assert fields == ("locations",)
    assert (was.locations, now.locations) == ("ауд. 101", "ауд. 202")


def test_teacher_change_is_an_edit():
    old = [slot("2026-09-01", "10:00", "Испанский язык", educators="Иванов И. И.")]
    new = [slot("2026-09-01", "10:00", "Испанский язык", educators="Петров П. П.")]
    assert compare(old, new).edited[0][2] == ("educators",)


def test_window_limits_comparison():
    """Пары за пределами общего окна не считаются изменениями."""
    old = [
        slot("2026-08-30", "10:00", "Вчерашняя"),
        slot("2026-09-01", "10:00", "Общая"),
    ]
    new = [
        slot("2026-09-01", "10:00", "Общая"),
        slot("2026-09-20", "10:00", "Далёкая"),
    ]
    window = overlap((date(2026, 8, 30), date(2026, 9, 13)), (date(2026, 8, 31), date(2026, 9, 20)))
    assert window == (date(2026, 8, 31), date(2026, 9, 13))
    assert compare(old, new, window).is_empty


def test_sliding_window_does_not_invent_changes():
    """Окно уехало на день — исчезнувший вчерашний день не «отменён»."""
    yesterday = [slot("2026-08-31", "10:00", "Финансы")]
    today = []
    window = overlap((date(2026, 8, 31), date(2026, 9, 14)), (date(2026, 9, 1), date(2026, 9, 15)))
    assert compare(yesterday, today, window).is_empty


def test_overlap_of_disjoint_windows_is_none():
    assert overlap((date(2026, 1, 1), date(2026, 1, 5)), (date(2026, 2, 1), date(2026, 2, 5))) is None


def test_in_window_filters_by_date():
    slots = [slot("2026-09-01", "10:00", "A"), slot("2026-09-20", "10:00", "B")]
    kept = in_window(slots, date(2026, 9, 1), date(2026, 9, 10))
    assert [item.subject for item in kept] == ["A"]


def test_slot_survives_json_round_trip():
    original = slot(
        "2026-09-01", "10:00", "Финансы", subgroup="Coh.2", locations="101", educators="Иванов"
    )
    assert Slot.from_dict(original.to_dict()) == original
