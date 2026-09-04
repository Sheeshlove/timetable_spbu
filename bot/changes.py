"""Сравнение расписаний: что изменилось с прошлой проверки.

Сайт расписания не умеет сообщать об изменениях сам, поэтому бот держит
слепок того расписания, которое студент видел в прошлый раз, и сравнивает
его со свежим. Слепок снимается уже после фильтров по когортам и языку —
студента интересуют только его пары.

Главная тонкость — окно. Слепок покрывает ближайшие две недели, и это окно
каждый день сдвигается. Если сравнивать слепки целиком, вчерашние пары
выглядели бы «убранными», а появившиеся на горизонте — «добавленными».
Поэтому сравнение идёт только по пересечению окон.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .timetable.models import Schedule

# Поля занятия, изменение которых стоит показать отдельно
WATCHED_FIELDS = ("locations", "educators")


@dataclass(frozen=True)
class Slot:
    """Занятие в слепке — только то, что важно для сравнения."""

    date: str
    interval: str
    subject: str
    subgroup: str = ""
    locations: str = ""
    educators: str = ""

    @property
    def day(self) -> date | None:
        try:
            return date.fromisoformat(self.date)
        except ValueError:
            return None

    @property
    def identity(self) -> tuple[str, str, str, str]:
        """Точное совпадение: тот же день, время, предмет и поток."""
        return (self.date, self.interval, self.subject, self.subgroup)

    @property
    def lesson(self) -> tuple[str, str]:
        """Пара «предмет + поток» без времени — чтобы заметить перенос."""
        return (self.subject, self.subgroup)

    def to_dict(self) -> dict[str, str]:
        return {
            "date": self.date,
            "interval": self.interval,
            "subject": self.subject,
            "subgroup": self.subgroup,
            "locations": self.locations,
            "educators": self.educators,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Slot":
        return cls(
            date=str(raw.get("date", "")),
            interval=str(raw.get("interval", "")),
            subject=str(raw.get("subject", "")),
            subgroup=str(raw.get("subgroup", "")),
            locations=str(raw.get("locations", "")),
            educators=str(raw.get("educators", "")),
        )


@dataclass
class Diff:
    """Что поменялось между двумя слепками."""

    added: list[Slot] = field(default_factory=list)
    removed: list[Slot] = field(default_factory=list)
    moved: list[tuple[Slot, Slot]] = field(default_factory=list)
    edited: list[tuple[Slot, Slot, tuple[str, ...]]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.moved or self.edited)

    @property
    def count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.moved) + len(self.edited)


def take_snapshot(schedule: Schedule) -> list[Slot]:
    """Снимает слепок с уже отфильтрованного расписания."""
    slots: list[Slot] = []
    for day in schedule.days:
        if day.date is None:
            continue  # без даты сравнивать нечего
        for event in day.events:
            slots.append(
                Slot(
                    date=day.date.isoformat(),
                    interval=event.interval,
                    subject=event.subject,
                    subgroup=event.subgroup,
                    locations=event.locations,
                    educators=event.educators,
                )
            )
    return sorted(slots, key=lambda slot: (slot.date, slot.interval, slot.subject))


def in_window(slots: list[Slot], start: date, end: date) -> list[Slot]:
    return [slot for slot in slots if slot.day is not None and start <= slot.day <= end]


def compare(
    old: list[Slot],
    new: list[Slot],
    window: tuple[date, date] | None = None,
) -> Diff:
    """Сравнивает слепки. ``window`` ограничивает сравнение пересечением окон."""
    if window is not None:
        start, end = window
        old = in_window(old, start, end)
        new = in_window(new, start, end)

    old_by_identity = {slot.identity: slot for slot in old}
    new_by_identity = {slot.identity: slot for slot in new}

    diff = Diff()

    # Совпали точно — но могли поменяться аудитория или преподаватель
    for identity, new_slot in new_by_identity.items():
        old_slot = old_by_identity.get(identity)
        if old_slot is None:
            continue
        changed = tuple(
            name
            for name in WATCHED_FIELDS
            if getattr(old_slot, name) != getattr(new_slot, name)
        )
        if changed:
            diff.edited.append((old_slot, new_slot, changed))

    disappeared = [slot for slot in old if slot.identity not in new_by_identity]
    appeared = [slot for slot in new if slot.identity not in old_by_identity]

    # Тот же предмет в другое время — это перенос, а не «убрали и добавили»
    remaining_new = list(appeared)
    for old_slot in disappeared:
        match = next(
            (slot for slot in remaining_new if slot.lesson == old_slot.lesson), None
        )
        if match is None:
            diff.removed.append(old_slot)
        else:
            remaining_new.remove(match)
            diff.moved.append((old_slot, match))
    diff.added.extend(remaining_new)

    diff.added.sort(key=lambda slot: (slot.date, slot.interval))
    diff.removed.sort(key=lambda slot: (slot.date, slot.interval))
    diff.moved.sort(key=lambda pair: (pair[0].date, pair[0].interval))
    diff.edited.sort(key=lambda item: (item[0].date, item[0].interval))
    return diff


def overlap(
    first: tuple[date, date], second: tuple[date, date]
) -> tuple[date, date] | None:
    """Пересечение двух окон — период, за который сравнение честное."""
    start = max(first[0], second[0])
    end = min(first[1], second[1])
    return (start, end) if start <= end else None
