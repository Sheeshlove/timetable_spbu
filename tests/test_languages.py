"""Изучаемый иностранный язык: распознавание и отбор пар."""

import pytest

from bot.languages import (
    ANY,
    FALLBACK_KEYS,
    NONE,
    offered_languages,
    belongs_to_student,
    choice_title,
    detect_language,
    filter_events,
    is_language_class,
    language_name,
    languages_in_schedule,
    matches_teacher,
    teachers_for,
)
from bot.timetable.models import Event
from bot.timetable.scraper import parse_schedule_html
from conftest import fixture

WEEK = parse_schedule_html(fixture("week_page_ru.html"), 474489, 2026)
MONDAY = WEEK.days[0].events


def event(subject: str, educators: str = "") -> Event:
    return Event(subject=subject, educators=educators)


# --- распознавание -----------------------------------------------------


@pytest.mark.parametrize(
    "subject, expected",
    [
        ("Электив. Иностранный язык (немецкий), семинар", "de"),
        ("Факультатив. Иностранный язык (испанский), семинар", "es"),
        ("Электив. Иностранный язык (французский), семинар", "fr"),
        ("Электив. Русский язык как иностранный, практическое занятие", "ru_foreign"),
        ("Английский язык, семинар", "en"),
        ("Foreign language (German), seminar", "de"),
        ("Russian as a foreign language", "ru_foreign"),
    ],
)
def test_detect_language(subject, expected):
    assert detect_language(event(subject)) == expected


@pytest.mark.parametrize(
    "subject",
    [
        "Современный стратегический анализ, лекция",
        "Количественные методы исследований в менеджменте, семинар",
        "Профессиональные навыки менеджера I, практическое занятие",
    ],
)
def test_regular_subjects_are_not_language_classes(subject):
    assert is_language_class(event(subject)) is False
    assert detect_language(event(subject)) is None


def test_unknown_language_is_not_guessed():
    """Пара на языке, которого нет в каталоге, под фильтр не попадает."""
    unknown = event("Иностранный язык (суахили), семинар")
    assert detect_language(unknown) is None
    assert is_language_class(unknown) is False
    assert belongs_to_student(unknown, "de") is True
    assert belongs_to_student(unknown, NONE) is True


@pytest.mark.parametrize(
    "subject",
    [
        "Языки программирования, лекция",
        "Факультатив. Языки разметки и обработки данных",
        "Формальные языки и автоматы",
    ],
)
def test_programming_languages_are_not_language_classes(subject):
    """Слова «язык» мало: иначе такие курсы пропадут у «не изучаю языки»."""
    lesson = event(subject)
    assert is_language_class(lesson) is False
    assert belongs_to_student(lesson, NONE) is True
    assert belongs_to_student(lesson, "de") is True


# --- что предлагать студенту -------------------------------------------


def test_languages_in_real_week():
    assert languages_in_schedule(WEEK) == ["ru_foreign", "de", "fr", "es"]


def test_teachers_of_a_language():
    assert teachers_for(WEEK, "de") == ["Нейман Ю. Е.", "Павлова Н. Г."]
    assert teachers_for(WEEK, "es") == ["Смыченко Ю. И."]
    assert teachers_for(WEEK, "ja") == []


def test_fallback_list_is_meaningful():
    assert set(FALLBACK_KEYS) >= {"en", "de", "fr", "es"}
    assert all(language_name(key) for key in FALLBACK_KEYS)


def test_offered_list_starts_with_what_is_in_the_schedule():
    offered = offered_languages(WEEK)
    assert offered[: len(languages_in_schedule(WEEK))] == languages_in_schedule(WEEK)


def test_offered_list_keeps_common_languages():
    """Английского в этой неделе нет, но выбрать его студент должен уметь."""
    offered = offered_languages(WEEK)
    assert "en" in offered
    assert len(offered) == len(set(offered)), "без повторов"


def test_offered_list_without_schedule():
    assert offered_languages(None) == list(FALLBACK_KEYS)


# --- отбор -------------------------------------------------------------


def test_monday_has_all_language_streams():
    languages = [e for e in MONDAY if is_language_class(e)]
    assert len(languages) == 12, "шесть потоков в двух парах"


def test_choice_keeps_only_my_language():
    kept, hidden = filter_events(MONDAY, "de")
    assert hidden == 8
    assert {detect_language(e) for e in kept if is_language_class(e)} == {"de"}


def test_teacher_narrows_to_my_group():
    kept, hidden = filter_events(MONDAY, "de", "Нейман Ю. Е.")
    languages = [e for e in kept if is_language_class(e)]
    assert len(languages) == 2, "две пары своей группы"
    assert all(e.educators == "Нейман Ю. Е." for e in languages)
    assert hidden == 10


def test_none_hides_every_language_class():
    kept, hidden = filter_events(MONDAY, NONE)
    assert hidden == 12
    assert not any(is_language_class(e) for e in kept)


def test_unset_choice_keeps_everything():
    kept, hidden = filter_events(MONDAY, ANY)
    assert hidden == 0
    assert len(kept) == len(MONDAY)


def test_other_subjects_are_never_touched():
    for choice in (ANY, NONE, "de", "fr"):
        kept, _ = filter_events(MONDAY, choice)
        assert any("Современный стратегический анализ" in e.subject for e in kept)


def test_missing_teacher_in_schedule_keeps_event():
    """Если у пары не указан преподаватель, скрывать её из-за группы нельзя."""
    anonymous = event("Электив. Иностранный язык (немецкий), семинар")
    assert belongs_to_student(anonymous, "de", "Нейман Ю. Е.") is True


def test_matches_teacher_by_surname():
    lesson = event("Иностранный язык (немецкий)", "Нейман Юлия Евгеньевна")
    assert matches_teacher(lesson, "Нейман Ю. Е.") is True
    assert matches_teacher(lesson, "Павлова Н. Г.") is False


def test_choice_title():
    assert choice_title("de", "", "ru") == "Немецкий"
    assert choice_title("de", "Нейман Ю. Е.", "ru") == "Немецкий · Нейман Ю. Е."
    assert choice_title("de", "", "en") == "German"
    assert choice_title(NONE, "", "ru") == "—"
    assert choice_title(ANY, "", "en") == "all"
