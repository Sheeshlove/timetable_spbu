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

    async def _fetch(self, path: str, *, as_json: bool):
        self.requested.append(path)
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
        {"/GSOM/StudentGroupEvents/Primary/474489/2026-08-31": fixture("week_page.html")}
    )
    schedule = await client.schedule(474489, date(2026, 8, 31), date(2026, 9, 6), "GSOM")
    assert [day.date for day in schedule.days] == [date(2026, 8, 31), date(2026, 9, 1)]
    assert schedule.days[0].events[0].subject == "Микроэкономика, лекция"
    assert client.requested[0].startswith("/api/"), "сначала пробуем JSON-API"


async def test_schedule_range_is_swapped_when_reversed():
    client = FakeClient({"/api/v1/groups/474489/events/2026-08-31/2026-09-06": EVENTS_JSON})
    schedule = await client.schedule(474489, date(2026, 9, 6), date(2026, 8, 31))
    assert len(schedule.days) == 1


async def test_schedule_raises_when_site_is_down():
    client = FakeClient({})
    with pytest.raises(TimetableError):
        await client.schedule(474489, date(2026, 8, 31), date(2026, 8, 31), "GSOM")
