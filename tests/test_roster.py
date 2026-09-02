"""Список студентов: поиск по фамилии и транслитерация."""

import pytest

from bot.roster import load_roster, normalize
from bot.roster.translit import to_latin

roster = load_roster()


def names(query: str) -> list[str]:
    return [student.name for student in roster.find(query)]


def test_roster_loaded():
    assert roster.program == "MiM 2026"
    assert len(roster.students) == 85
    assert len(roster.subjects) == 7


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Shishlov", "Shishlov Egor"),
        ("shishlov", "Shishlov Egor"),
        ("ШИШЛОВ", "Shishlov Egor"),
        ("Шишлов", "Shishlov Egor"),
        ("Юрченко", "Iurchenko Kseniia"),          # Ю -> iu, паспортная схема
        ("Шиманская", "Shimanskaia Angelina"),      # -ая -> aia
        ("Айрапетян", "Airapetian Albert"),
        ("Алексеева", "Alekseeva Kseniia"),
        ("Кулькова", "Kulkova Polina"),
        ("Шнейдерман", "Shneiderman Anna"),
    ],
)
def test_finds_by_surname(query, expected):
    assert expected in names(query)


def test_finds_by_alternative_transliteration():
    # студент может написать «Yurchenko», хотя в ведомости «Iurchenko»
    assert "Iurchenko Kseniia" in names("Yurchenko")


def test_finds_with_first_name():
    assert names("Шишлов Егор") == ["Shishlov Egor"]


def test_typo_is_forgiven():
    assert "Shishlov Egor" in names("Shihlov")


def test_unknown_surname_returns_nothing():
    assert names("Пупкин") == []
    assert names("") == []


def test_international_names_are_searchable():
    assert names("Nafhani") == ["Nafhani Binti Azli"]
    assert names("Danyo") == ["Danyo Kenneth Elorm Atsu"]


def test_duplicate_rows_were_collapsed():
    # в таблице деканата строки 52-54 дублируют 49-51
    assert names("Morozov") == ["Morozov Ilia"]
    assert names("Meleshko") == ["Meleshko Mikhail"]


def test_storage_key_round_trip():
    student = roster.find("Шишлов")[0]
    assert roster.get(roster.storage_key(student)) is student


def test_get_unknown_returns_none():
    assert roster.get("Кто-то Неизвестный") is None


def test_cohorts_are_complete():
    keys = {subject.key for subject in roster.subjects}
    for student in roster.students:
        assert set(student.cohorts) == keys, student.name
        assert all(student.cohorts.values()), student.name


def test_normalize():
    assert normalize("  Иванов-Петров  ") == "иванов петров"
    assert normalize("Алёна") == "алена"


def test_translit_keeps_passport_spelling_first():
    assert to_latin("Юрченко")[0] == "iurchenko"
    assert to_latin("Шиманская")[0] == "shimanskaia"
    assert to_latin("latin") == ["latin"]
