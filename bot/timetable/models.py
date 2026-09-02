"""Доменные модели расписания СПбГУ."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Event:
    """Одно занятие."""

    subject: str
    start: datetime | None = None
    end: datetime | None = None
    time_text: str = ""
    locations: str = ""
    educators: str = ""
    is_canceled: bool = False

    @property
    def interval(self) -> str:
        if self.time_text:
            return self.time_text
        if self.start and self.end:
            return f"{self.start:%H:%M}–{self.end:%H:%M}"
        if self.start:
            return f"{self.start:%H:%M}"
        return ""


@dataclass
class Day:
    """День расписания."""

    date: date | None
    title: str
    events: list[Event] = field(default_factory=list)


@dataclass
class Schedule:
    """Расписание группы за произвольный период."""

    group_id: int
    group_name: str
    days: list[Day] = field(default_factory=list)
    url: str = ""

    @property
    def is_empty(self) -> bool:
        return not any(day.events for day in self.days)
