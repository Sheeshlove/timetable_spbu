"""Переводы: полнота каталога и выбор языка по коду клиента."""

import pytest

from bot.i18n import (
    DEFAULT_LANG,
    LANGUAGE_NAMES,
    MONTHS_IN_DATE,
    SITE_CULTURES,
    TEXTS,
    Translator,
    all_keys_present,
    menu_texts,
    normalize_lang,
)


def test_every_language_has_every_key():
    assert all_keys_present() == [], "в каком-то языке не хватает строк"


def test_languages_are_consistent():
    for lang in TEXTS:
        assert lang in LANGUAGE_NAMES
        assert lang in SITE_CULTURES
        assert len(MONTHS_IN_DATE[lang]) == 12


@pytest.mark.parametrize(
    "code, expected",
    [
        ("ru", "ru"),
        ("ru-RU", "ru"),
        ("RU", "ru"),
        ("en", "en"),
        ("en-GB", "en"),
        ("de", "en"),
        ("zh-hans", "en"),
        ("uk", "ru"),   # соседние языки ближе к русскому интерфейсу
        ("kk", "ru"),
        (None, DEFAULT_LANG),
        ("", DEFAULT_LANG),
    ],
)
def test_normalize_lang(code, expected):
    assert normalize_lang(code) == expected


def test_translator_falls_back_to_russian_for_missing_key():
    t = Translator("en")
    assert t("совсем-неизвестный-ключ") == "совсем-неизвестный-ключ"


def test_translator_formats_placeholders():
    assert Translator("en")("settings_time", time="08:30") == "⏰ Time: 08:30"
    assert Translator("ru")("settings_time", time="08:30") == "⏰ Время: 08:30"


def test_unknown_language_falls_back_to_default():
    assert Translator("xx").lang == DEFAULT_LANG


def test_menu_texts_cover_both_languages():
    texts = menu_texts()
    assert "📅 Сегодня" in texts and "📅 Today" in texts
    assert len(texts) == 8


def test_site_cultures_match_the_site_form():
    # Значения из формы переключателя на timetable.spbu.ru
    assert SITE_CULTURES == {"ru": "ru", "en": "en-us"}
