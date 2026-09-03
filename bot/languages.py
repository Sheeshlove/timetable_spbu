"""Языковые занятия: какой иностранный язык изучает студент.

В ВШМ языки идут параллельными потоками: в один слот стоят и испанский, и
немецкий, и французский, и русский как иностранный, причём у популярных
языков по две группы с разными преподавателями. Студенту нужна одна пара из
шести, поэтому бот спрашивает язык, а при необходимости и преподавателя.

Занятие считается языковым, только если в названии есть и слово «язык» (или
«language»), и название конкретного языка. Одного слова «язык» мало: иначе
«Языки программирования» попадут под фильтр и пропадут у тех, кто выбрал
«не изучаю».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from .timetable.models import Event, Schedule

# Значения выбора, не являющиеся языком
ANY = ""  # язык не указан — показываем все языковые занятия
NONE = "none"  # языки не изучаю — скрываем их все
ANY_TEACHER = ""

LANGUAGE_CLASS_RE = re.compile(r"язык|language", re.I)


@dataclass(frozen=True)
class Language:
    key: str
    names: Mapping[str, str]
    match: tuple[str, ...]

    def name(self, lang: str = "ru") -> str:
        return self.names.get(lang) or self.names.get("ru") or self.key


# Порядок важен: «русский как иностранный» проверяется раньше прочих, потому
# что его название содержит и «русский», и «иностранный».
LANGUAGES: tuple[Language, ...] = (
    Language(
        "ru_foreign",
        {"ru": "Русский как иностранный", "en": "Russian as a foreign language"},
        ("русск", "russian"),
    ),
    Language("en", {"ru": "Английский", "en": "English"}, ("англ", "english")),
    Language("de", {"ru": "Немецкий", "en": "German"}, ("немец", "german", "deutsch")),
    Language("fr", {"ru": "Французский", "en": "French"}, ("француз", "french")),
    Language("es", {"ru": "Испанский", "en": "Spanish"}, ("испан", "spanish")),
    Language("it", {"ru": "Итальянский", "en": "Italian"}, ("итальян", "italian")),
    Language("zh", {"ru": "Китайский", "en": "Chinese"}, ("китайск", "chinese")),
    Language("ja", {"ru": "Японский", "en": "Japanese"}, ("японск", "japanese")),
    Language("ko", {"ru": "Корейский", "en": "Korean"}, ("корейск", "korean")),
    Language("ar", {"ru": "Арабский", "en": "Arabic"}, ("арабск", "arabic")),
)

BY_KEY = {language.key: language for language in LANGUAGES}

# Языки, которые в ВШМ преподают постоянно. Их показываем всегда, даже если в
# ближайших неделях расписания их не оказалось: пары могут начаться позже, а
# студент выбирает язык один раз.
COMMON_KEYS = ("en", "de", "fr", "es", "it", "zh", "ru_foreign")

# Что показать, если сходить на сайт за расписанием вовсе не удалось.
FALLBACK_KEYS = COMMON_KEYS


def language_name(key: str, lang: str = "ru") -> str:
    found = BY_KEY.get(key)
    return found.name(lang) if found else key


def detect_language(event: Event) -> str | None:
    """Какой язык преподаётся на занятии. None — занятие не языковое.

    Нужны оба признака: слово «язык» и название языка. «Языки
    программирования» первому условию удовлетворяют, второму — нет, и под
    языковой фильтр не попадают.
    """
    if not LANGUAGE_CLASS_RE.search(event.subject):
        return None
    subject = event.subject.lower()
    for language in LANGUAGES:
        if any(needle in subject for needle in language.match):
            return language.key
    return None


def is_language_class(event: Event) -> bool:
    """Языковое ли это занятие — то есть узнали ли мы язык."""
    return detect_language(event) is not None


def languages_in_schedule(schedule: Schedule) -> list[str]:
    """Языки, которые встречаются в этом расписании, в порядке каталога."""
    found = {
        key
        for day in schedule.days
        for event in day.events
        if (key := detect_language(event)) is not None
    }
    return [language.key for language in LANGUAGES if language.key in found]


def offered_languages(schedule: Schedule | None) -> list[str]:
    """Что предложить студенту на выбор.

    Сначала языки, которые действительно стоят в ближайшем расписании, —
    их студент увидит первыми. Дальше остальные обычные языки программы:
    пары могут начаться позже в семестре, а язык выбирается один раз, и
    пропавший из списка английский хуже лишней кнопки.
    """
    found = languages_in_schedule(schedule) if schedule is not None else []
    rest = [key for key in COMMON_KEYS if key not in found]
    return found + rest


def teachers_for(schedule: Schedule, key: str) -> list[str]:
    """Преподаватели этого языка — чтобы уточнить группу, когда их несколько."""
    teachers: list[str] = []
    for day in schedule.days:
        for event in day.events:
            if detect_language(event) != key:
                continue
            name = (event.educators or "").strip()
            if name and name not in teachers:
                teachers.append(name)
    return sorted(teachers)


def matches_teacher(event: Event, teacher: str) -> bool:
    """Тот ли преподаватель. Пустое поле в расписании — не повод скрывать."""
    if not teacher:
        return True
    educators = (event.educators or "").strip().lower()
    if not educators:
        return True
    wanted = teacher.strip().lower()
    # Фамилия сравнивается отдельно: сайт может писать «Нейман Ю. Е.» и
    # «Нейман Юлия Евгеньевна» в разных разделах.
    return wanted in educators or educators.split()[0] == wanted.split()[0]


def belongs_to_student(event: Event, choice: str, teacher: str = ANY_TEACHER) -> bool:
    """Показывать ли языковое занятие студенту.

    Осторожность та же, что и с когортами: скрываем только то, про что точно
    известно, что это чужой язык или чужая группа.
    """
    if detect_language(event) is None:
        return True
    if choice == ANY:
        return True
    if choice == NONE:
        return False

    detected = detect_language(event)
    if detected is None:  # не языковое занятие — не наше дело
        return True
    if detected != choice:
        return False
    return matches_teacher(event, teacher)


def filter_events(
    events: Iterable[Event], choice: str, teacher: str = ANY_TEACHER
) -> tuple[list[Event], int]:
    """Отбирает занятия студента и заодно считает скрытые."""
    original = list(events)
    kept = [event for event in original if belongs_to_student(event, choice, teacher)]
    return kept, len(original) - len(kept)


def choice_title(choice: str, teacher: str, lang: str = "ru") -> str:
    """Как выбор выглядит в карточке настроек."""
    if choice == NONE:
        return "—"
    if choice == ANY:
        return "все" if lang == "ru" else "all"
    title = language_name(choice, lang)
    return f"{title} · {teacher}" if teacher else title
