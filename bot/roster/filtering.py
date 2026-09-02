"""Отбор занятий, которые относятся к когорте конкретного студента.

Правило одно и намеренно осторожное: занятие скрывается, только если по
тексту видно, что оно принадлежит *другой* когорте. Если метки когорты нет
или она непонятна — занятие показывается. Пропустить пару из-за слишком
умного фильтра хуже, чем увидеть лишнюю.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..timetable.models import Day, Event, Schedule
from . import Roster, Student, Subject
from .translit import is_cyrillic, to_latin

# «Coh.1», «Cohort 2», «когорта 3», «ког. 1»
COHORT_RE = re.compile(r"(?:coh\.?|cohort|когорт\w*|ког\.?)\s*[-–—:]?\s*(\d+)", re.I)
# «группа 1», «гр. 2», «поток 3», «group 1», «подгруппа 2»
GROUP_RE = re.compile(
    r"(?:подгруп\w*|груп\w*|гр\.|поток\w*|subgroup|group|gr\.)\s*[-–—:]?\s*(\d+)", re.I
)
# «1 когорта», «2 группа» — тот же смысл, обратный порядок слов
REVERSED_RE = re.compile(r"(\d+)\s*(?:когорт\w*|груп\w*|поток\w*|cohort|group)", re.I)

LECTURE_RE = re.compile(r"лекц|lecture", re.I)
SEMINAR_RE = re.compile(r"семин|практич|seminar|practice|workshop|tutorial", re.I)


@dataclass
class FilterReport:
    """Что фильтр сделал — для отладки и для подписи под расписанием."""

    hidden: int = 0
    reasons: list[str] = field(default_factory=list)


def event_text(event: Event) -> str:
    return " ".join(part for part in (event.subject, event.educators, event.locations) if part)


def _numbers(text: str) -> set[int]:
    """Все номера когорт и групп, упомянутые в тексте занятия."""
    found: set[int] = set()
    for pattern in (COHORT_RE, GROUP_RE, REVERSED_RE):
        found.update(int(match) for match in pattern.findall(text))
    return found


def _value_number(value: str) -> int | None:
    match = re.search(r"(\d+)", value or "")
    return int(match.group(1)) if match else None


def _surname(value: str) -> str:
    """«Shevchuk 2» -> «shevchuk»."""
    return re.sub(r"[\d\s]+$", "", (value or "").strip()).lower()


def _mentions_surname(text: str, surname: str) -> bool:
    """Ищет латинскую фамилию в тексте, который может быть кириллицей."""
    if not surname:
        return False
    lowered = text.lower()
    if surname in lowered:
        return True
    for word in re.findall(r"[а-яё]+", lowered):
        if len(word) < 3:
            continue
        if surname in to_latin(word):
            return True
    return False


def matching_subjects(text: str, roster: Roster) -> list[Subject]:
    """Предметы из таблицы, к которым может относиться занятие."""
    lowered = text.lower()
    matched = [
        subject
        for subject in roster.subjects
        if any(needle in lowered for needle in subject.match)
    ]
    if len(matched) < 2:
        return matched

    # Лекции и семинары одного предмета различаем по типу занятия; если тип
    # не указан, оставляем оба варианта — тогда подойдёт любая из когорт.
    is_lecture, is_seminar = bool(LECTURE_RE.search(text)), bool(SEMINAR_RE.search(text))
    if is_lecture and not is_seminar:
        narrowed = [s for s in matched if s.event_type in (None, "lecture")]
    elif is_seminar and not is_lecture:
        narrowed = [s for s in matched if s.event_type in (None, "seminar")]
    else:
        return matched
    return narrowed or matched


def belongs_to(event: Event, student: Student, roster: Roster) -> tuple[bool, str]:
    """Показывать ли занятие. Второе значение — причина, если скрываем."""
    text = event_text(event)
    subjects = matching_subjects(text, roster)
    if not subjects:
        return True, ""

    for subject in subjects:
        mine = student.cohorts.get(subject.key, "")
        if not mine:
            continue

        if subject.kind == "educator":
            verdict = _check_educator(text, mine, subject, roster)
        else:
            verdict = _check_number(text, mine, subject, roster)

        if verdict is True:  # занятие точно моё — дальше не смотрим
            return True, ""
        if verdict is False:
            return False, f"{subject.title}: не моя когорта ({mine})"

    # Ни один предмет не дал уверенного ответа — показываем.
    return True, ""


def _check_number(text: str, mine: str, subject: Subject, roster: Roster) -> bool | None:
    """True — моё, False — чужое, None — по тексту не понять."""
    my_number = _value_number(mine)
    mentioned = _numbers(text)
    if my_number is None or not mentioned:
        return None
    if my_number in mentioned:
        return True
    known = {
        _value_number(value)
        for value in _subject_values(subject, roster)
        if _value_number(value) is not None
    }
    # Чужой считаем только тот номер, который вообще бывает у этого предмета:
    # иначе номер аудитории или потока чужого курса скрыл бы занятие.
    return False if mentioned & known else None


def _check_educator(text: str, mine: str, subject: Subject, roster: Roster) -> bool | None:
    my_surname = _surname(mine)
    my_number = _value_number(mine)
    if not _mentions_surname(text, my_surname):
        others = {
            _surname(value)
            for value in _subject_values(subject, roster)
            if _surname(value) and _surname(value) != my_surname
        }
        if any(_mentions_surname(text, surname) for surname in others):
            return False
        return None

    # Преподаватель мой. Если у него несколько групп, проверяем номер.
    if my_number is None:
        return True
    mentioned = _numbers(text)
    if not mentioned:
        return None
    return True if my_number in mentioned else False


def _subject_values(subject: Subject, roster: Roster) -> set[str]:
    return {
        student.cohorts.get(subject.key, "")
        for student in roster.students
        if student.cohorts.get(subject.key)
    }


def filter_schedule(
    schedule: Schedule, student: Student, roster: Roster
) -> tuple[Schedule, FilterReport]:
    """Оставляет в расписании занятия, относящиеся к когортам студента."""
    report = FilterReport()
    days: list[Day] = []
    for day in schedule.days:
        kept: list[Event] = []
        for event in day.events:
            visible, reason = belongs_to(event, student, roster)
            if visible:
                kept.append(event)
            else:
                report.hidden += 1
                if reason not in report.reasons:
                    report.reasons.append(reason)
        days.append(Day(date=day.date, title=day.title, events=kept))
    filtered = Schedule(
        group_id=schedule.group_id,
        group_name=schedule.group_name,
        days=days,
        url=schedule.url,
    )
    return filtered, report
