"""Список студентов MiM и их распределение по когортам.

Данные лежат в `mim_2026.json` и обновляются скриптом
`scripts/import_cohorts.py` из таблицы деканата.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from .translit import is_cyrillic, to_latin

DATA_FILE = Path(__file__).with_name("mim_2026.json")

FUZZY_THRESHOLD = 0.78
MAX_SUGGESTIONS = 6


@dataclass(frozen=True)
class Subject:
    """Предмет из таблицы и правила, по которым его узнают в расписании."""

    key: str
    column: str
    title: str
    kind: str  # cohort | group | educator
    match: tuple[str, ...]
    event_type: str | None = None  # lecture | seminar — для предметов вроде QMBR


@dataclass(frozen=True)
class Student:
    number: str
    name: str
    last_name: str
    parts: tuple[str, ...]
    cohorts: Mapping[str, str]

    @property
    def key(self) -> str:
        """Ключ для хранения в базе: имени хватает, а если в списке есть
        полные тёзки — к имени добавляется номер строки из таблицы."""
        return normalize(self.name)

    @property
    def label(self) -> str:
        return self.name


def normalize(text: str) -> str:
    """Приводит написание к сравнимому виду: регистр, ё, дефисы, пробелы."""
    lowered = (text or "").strip().lower().replace("ё", "е")
    cleaned = "".join(char if char.isalnum() else " " for char in lowered)
    return " ".join(cleaned.split())


def _variants(token: str) -> list[str]:
    """Кандидаты написания одного слова: как есть плюс транслитерация."""
    if is_cyrillic(token):
        return to_latin(token) or [token]
    return [token]


class Roster:
    def __init__(self, payload: dict) -> None:
        self.program: str = payload.get("program", "")
        self.source: str = payload.get("source", "")
        self.subjects: tuple[Subject, ...] = tuple(
            Subject(
                key=item["key"],
                column=item["column"],
                title=item["title"],
                kind=item["kind"],
                match=tuple(item.get("match", ())),
                event_type=item.get("event_type"),
            )
            for item in payload.get("subjects", [])
        )
        self.students: tuple[Student, ...] = tuple(
            Student(
                number=str(item.get("no", "")),
                name=item["name"],
                last_name=item["last_name"],
                parts=tuple(item["parts"]),
                cohorts=dict(item.get("cohorts", {})),
            )
            for item in payload.get("students", [])
        )
        self._parts = [
            (student, [normalize(part) for part in student.parts])
            for student in self.students
        ]
        self._by_key: dict[str, Student] = {}
        for student in self.students:
            self._by_key.setdefault(student.key, student)
            self._by_key[f"{student.key} {student.number}"] = student

        names = [student.key for student in self.students]
        # Полные тёзки с разными когортами: имени для выбора мало, показываем
        # ещё и номер строки из таблицы деканата.
        self._namesakes = {key for key in names if names.count(key) > 1}

    def subject(self, key: str) -> Subject | None:
        return next((item for item in self.subjects if item.key == key), None)

    def get(self, name: str) -> Student | None:
        """Точный поиск по сохранённому в базе имени (возможно, с номером)."""
        return self._by_key.get(normalize(name))

    def storage_key(self, student: Student) -> str:
        """Как записать студента в базу, чтобы потом найти однозначно."""
        return (
            f"{student.name} {student.number}"
            if student.key in self._namesakes
            else student.name
        )

    def is_namesake(self, student: Student) -> bool:
        return student.key in self._namesakes

    def find(self, query: str) -> list[Student]:
        """Кандидаты по фамилии (или фамилии с именем), лучшие первыми.

        Сначала ищем точные совпадения слов — с учётом того, что студент
        может написать фамилию кириллицей. Если ничего не нашлось, включаем
        нечёткое сравнение: оно вытягивает опечатки и чужие схемы
        транслитерации.
        """
        tokens = normalize(query).split()
        if not tokens:
            return []
        token_variants = [_variants(token) for token in tokens]

        exact: list[tuple[int, Student]] = []
        for student, parts in self._parts:
            hits = sum(
                1
                for variants in token_variants
                if any(variant in parts for variant in variants)
            )
            if hits:
                exact.append((hits, student))
        if exact:
            best = max(hits for hits, _ in exact)
            return [student for hits, student in exact if hits == best]

        scored: list[tuple[float, Student]] = []
        for student, parts in self._parts:
            score = max(
                (
                    SequenceMatcher(None, variant, part).ratio()
                    for variants in token_variants
                    for variant in variants
                    for part in parts
                ),
                default=0.0,
            )
            if score >= FUZZY_THRESHOLD:
                scored.append((score, student))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [student for _score, student in scored[:MAX_SUGGESTIONS]]

    def describe(self, student: Student) -> list[tuple[str, str]]:
        """Пары «предмет — когорта» в порядке из таблицы."""
        return [
            (subject.title, student.cohorts.get(subject.key, ""))
            for subject in self.subjects
            if student.cohorts.get(subject.key)
        ]


@lru_cache(maxsize=1)
def load_roster(path: str | Path = DATA_FILE) -> Roster:
    return Roster(json.loads(Path(path).read_text(encoding="utf-8")))
