"""Клиент: приоритет JSON-API и переход на HTML при сбое."""

from datetime import date

import pytest

from bot.timetable.client import TimetableClient, TimetableError
from conftest import fixture

EVENTS_JSON = {
    "StudentGroupDisplayName": "Менеджмент 2026",
    "Days": [
        {
            "Day": "2026-08-31T00:00:00",
            "DayStudyEvents": [{"Subject": "Микроэкономика", "TimeIntervalString": "10:00–11:35"}],
        }
    ],
}


class FakeClient(TimetableClient):
    """Подменяет сеть словарём «путь -> ответ»."""

    def __init__(self, responses: dict, **kwargs):
        super().__init__("https://timetable.spbu.ru", cache_ttl=0, **kwargs)
        self.responses = responses
        self.requested: list[str] = []
        self.languages: list[str] = []

    async def _fetch(self, path: str, *, as_json: bool, lang: str = "ru"):
        self.requested.append(path)
        self.languages.append(lang)
        if path not in self.responses:
            raise TimetableError(f"нет ответа для {path}")
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value


async def test_schedule_json_is_sliced_to_range():
    client = FakeClient({"/api/v1/groups/474489/events/2026-08-31/2026-08-31": EVENTS_JSON})
    schedule = await client.schedule(474489, date(2026, 8, 31), date(2026, 8, 31))
    assert schedule.group_name == "Менеджмент 2026"
    assert len(schedule.days) == 1


async def test_schedule_falls_back_to_html_week_pages():
    client = FakeClient(
        {"/GSOM/StudentGroupEvents/Primary/474489/2026-09-14": fixture("week_page_ru.html")}
    )
    schedule = await client.schedule(474489, date(2026, 9, 14), date(2026, 9, 20), "GSOM")
    assert [day.date for day in schedule.days][0] == date(2026, 9, 14)
    assert len(schedule.days) == 6
    assert client.requested[0].startswith("/api/"), "сначала пробуем JSON-API"


async def test_schedule_range_is_swapped_when_reversed():
    client = FakeClient({"/api/v1/groups/474489/events/2026-08-31/2026-09-06": EVENTS_JSON})
    schedule = await client.schedule(474489, date(2026, 9, 6), date(2026, 8, 31))
    assert len(schedule.days) == 1


async def test_schedule_raises_when_site_is_down():
    client = FakeClient({})
    with pytest.raises(TimetableError):
        await client.schedule(474489, date(2026, 8, 31), date(2026, 8, 31), "GSOM")


async def test_language_reaches_the_site():
    client = FakeClient({"/api/v1/groups/1/events/2026-09-14/2026-09-14": EVENTS_JSON})
    await client.schedule(1, date(2026, 9, 14), date(2026, 9, 14), "GSOM", "en")
    assert client.languages == ["en"]


async def test_cache_is_separate_per_language():
    """Русский и английский ответы не должны подменять друг друга в кэше."""
    from bot.timetable.client import TimetableClient

    class Counting(TimetableClient):
        def __init__(self):
            super().__init__("https://timetable.spbu.ru", cache_ttl=60)
            self.hits = 0

        async def _ensure_culture(self, lang):
            return

        async def _get_session(self, lang="ru"):
            raise AssertionError("сеть не должна использоваться")

        async def _fetch(self, path, *, as_json, lang="ru"):
            key = f"{'json' if as_json else 'html'}:{lang}:{path}"
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            self.hits += 1
            payload = dict(EVENTS_JSON, StudentGroupDisplayName=f"группа-{lang}")
            self._cache.set(key, payload)
            return payload

    client = Counting()
    russian = await client.schedule(1, date(2026, 9, 14), date(2026, 9, 14), "GSOM", "ru")
    english = await client.schedule(1, date(2026, 9, 14), date(2026, 9, 14), "GSOM", "en")
    again = await client.schedule(1, date(2026, 9, 14), date(2026, 9, 14), "GSOM", "ru")

    assert russian.group_name == "группа-ru"
    assert english.group_name == "группа-en"
    assert again.group_name == "группа-ru"
    assert client.hits == 2, "второй запрос на том же языке берётся из кэша"
