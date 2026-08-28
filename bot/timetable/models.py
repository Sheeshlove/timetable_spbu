"""Доменные модели расписания СПбГУ."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Division:
    """Учебное подразделение (например, GSOM — ВШМ)."""

    alias: str
    name: str
    oid: str | None = None

    @property
    def key(self) -> str:
        return self.alias


@dataclass(frozen=True)
class Program:
    """Направление/образовательная программа внутри подразделения.

    ``key`` — стабильный идентификатор, по которому программу можно найти
    заново после перезапуска бота (порядковые номера для этого не годятся).
    """

    key: str
    name: str
    level: str = ""

    @property
    def title(self) -> str:
        return f"{self.level} · {self.name}" if self.level else self.name


@dataclass(frozen=True)
class AdmissionYear:
    """Год поступления.

    ``program_id`` — StudyProgramId из JSON-API; по нему запрашивается список
    групп. При разборе HTML идентификатора программы нет, зато ссылка ведёт
    сразу на группу — тогда заполняется ``group_id``.
    """

    program_id: int
    name: str
    is_current: bool = False
    group_id: int | None = None


@dataclass(frozen=True)
class StudentGroup:
    """Учебная группа, к расписанию которой можно подписаться."""

    group_id: int
    name: str
    study_form: str = ""


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
