"""Разбор ответов JSON-API сайта timetable.spbu.ru.

Функции этого модуля — чистые: на вход уже загруженный JSON, на выходе
доменные модели. Ключи ищутся без учёта регистра и в нескольких вариантах
написания, потому что API отдаёт PascalCase, а часть эндпоинтов —
camelCase.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Iterable

from .models import AdmissionYear, Day, Division, Event, Program, Schedule, StudentGroup

DIVISIONS_PATH = "/api/v1/study/divisions"
PROGRAMS_PATH = "/api/v1/study/divisions/{alias}/programs/levels"
GROUPS_PATH = "/api/v1/programs/{program_id}/groups"
EVENTS_PATH = "/api/v1/groups/{group_id}/events/{start}/{end}"


def program_key(level: str, name: str) -> str:
    """Стабильный короткий идентификатор программы для callback_data."""
    raw = f"{level.strip().lower()}|{name.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _get(data: Any, *names: str, default: Any = None) -> Any:
    """Достаёт значение по одному из имён без учёта регистра."""
    if not isinstance(data, dict):
        return default
    lowered = {str(key).lower(): value for key, value in data.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return default


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=None)
    return None


def parse_divisions(payload: Any) -> list[Division]:
    divisions: list[Division] = []
    for item in _as_list(payload):
        alias = _text(_get(item, "Alias", "PublicDivisionAlias"))
        name = _text(_get(item, "Name", "Title", "NameRu")) or alias
        if not alias:
            continue
        divisions.append(Division(alias=alias, name=name, oid=_text(_get(item, "Oid")) or None))
    return divisions


def parse_programs(payload: Any) -> list[Program]:
    """Уровни обучения -> направления. Годы поступления берутся отдельно."""
    programs: list[Program] = []
    seen: set[str] = set()
    for level in _as_list(payload):
        level_name = _text(_get(level, "StudyLevelName", "Name", "LevelName"))
        combinations = _get(
            level, "StudyProgramCombinations", "Combinations", "Programs", default=[]
        )
        for combination in _as_list(combinations):
            name = _text(_get(combination, "Name", "ProgramName", "Title"))
            if not name:
                continue
            key = program_key(level_name, name)
            if key in seen:
                continue
            seen.add(key)
            programs.append(Program(key=key, name=name, level=level_name))
    return programs


def parse_admission_years(payload: Any, key: str) -> list[AdmissionYear]:
    """Годы поступления для конкретного направления."""
    years: list[AdmissionYear] = []
    for level in _as_list(payload):
        level_name = _text(_get(level, "StudyLevelName", "Name", "LevelName"))
        combinations = _get(
            level, "StudyProgramCombinations", "Combinations", "Programs", default=[]
        )
        for combination in _as_list(combinations):
            name = _text(_get(combination, "Name", "ProgramName", "Title"))
            if not name or program_key(level_name, name) != key:
                continue
            raw_years = _get(combination, "AdmissionYears", "Years", default=[])
            for entry in _as_list(raw_years):
                program_id = _get(entry, "StudyProgramId", "ProgramId", "Id")
                if program_id is None:
                    continue
                years.append(
                    AdmissionYear(
                        program_id=int(program_id),
                        name=_text(_get(entry, "YearName", "Name", "Year")) or str(program_id),
                        is_current=bool(_get(entry, "IsCurrent", default=False)),
                    )
                )
    return years


def parse_groups(payload: Any) -> list[StudentGroup]:
    raw = _get(payload, "Groups", "StudentGroups", default=payload)
    groups: list[StudentGroup] = []
    for item in _as_list(raw):
        group_id = _get(item, "StudentGroupId", "GroupId", "Id")
        if group_id is None:
            continue
        groups.append(
            StudentGroup(
                group_id=int(group_id),
                name=_text(_get(item, "StudentGroupName", "Name", "DisplayName")) or str(group_id),
                study_form=_text(_get(item, "StudentGroupStudyForm", "StudyForm")),
            )
        )
    return groups


def _parse_event(item: Any) -> Event | None:
    subject = _text(
        _get(item, "Subject", "SubjectName", "DisplayName", "StudyEventsTimeTableKindCode")
    )
    if not subject:
        return None
    return Event(
        subject=subject,
        start=_parse_dt(_get(item, "Start", "TimeIntervalStart", "StartTime")),
        end=_parse_dt(_get(item, "End", "TimeIntervalEnd", "EndTime")),
        time_text=_text(_get(item, "TimeIntervalString", "TimeInterval")),
        locations=_text(_get(item, "LocationsDisplayText", "Locations", "Location")),
        educators=_text(_get(item, "EducatorsDisplayText", "Educators", "Educator")),
        is_canceled=bool(_get(item, "IsCanceled", "Cancelled", default=False)),
    )


def parse_schedule(payload: Any, group_id: int) -> Schedule:
    days: list[Day] = []
    for raw_day in _as_list(_get(payload, "Days", "StudyEventsDays", default=[])):
        day_dt = _parse_dt(_get(raw_day, "Day", "Date"))
        events: list[Event] = []
        for raw_event in _as_list(
            _get(raw_day, "DayStudyEvents", "StudyEvents", "Events", default=[])
        ):
            event = _parse_event(raw_event)
            if event is not None:
                events.append(event)
        days.append(
            Day(
                date=day_dt.date() if day_dt else None,
                title=_text(_get(raw_day, "DayString", "DayText", "Title")),
                events=events,
            )
        )
    return Schedule(
        group_id=group_id,
        group_name=_text(
            _get(payload, "StudentGroupDisplayName", "StudentGroupName", "DisplayName")
        ),
        days=days,
        url=_text(_get(payload, "TimeTableUrl", "Url")),
    )


def merge_schedules(schedules: Iterable[Schedule]) -> Schedule:
    """Склеивает несколько недель в одно расписание без дублей дней."""
    merged: dict[Any, Day] = {}
    group_id = 0
    group_name = ""
    url = ""
    for schedule in schedules:
        group_id = schedule.group_id or group_id
        group_name = group_name or schedule.group_name
        url = url or schedule.url
        for day in schedule.days:
            key = day.date or day.title
            if key in merged:
                continue
            merged[key] = day
    days = sorted(
        merged.values(),
        key=lambda day: (day.date is None, day.date or date.max),
    )
    return Schedule(group_id=group_id, group_name=group_name, days=days, url=url)
