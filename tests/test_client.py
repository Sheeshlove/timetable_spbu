"""Клиент: расписание берётся со страниц сайта, JSON-API — запасной.

Порядок именно такой, потому что пометку подгруппы («Подгруппа 2») и перевод
названий отдаёт только HTML: в JSON-API их нет.
"""

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


MINIMAL_WEEK = """
<h2>Группа {name}</h2>
<div class="panel panel-default">
  <div class="panel-heading"><h4 class="panel-title">понедельник, 14 сентября</h4></div>
  <ul class="panel-collapse">
    <li class="common-list-item row">
      <div class="col-sm-2 studyevent-datetime"><div class="with-icon"><div>
        <span class="moreinfo">10:00–11:30</span></div></div></div>
      <div class="col-sm-4 studyevent-subject"><div class="with-icon"><div>
        <span class="moreinfo">Микроэкономика</span></div></div>
        <div class="with-icon"><div><span>Подгруппа 2</span></div></div>
      </div>
    </li>
  </ul>
</div>
"""


async def test_schedule_is_read_from_week_pages():
    client = FakeClient(
        {"/GSOM/StudentGroupEvents/Primary/474489/2026-09-14": fixture("week_page_ru.html")}
    )
    schedule = await client.schedule(474489, date(2026, 9, 14), date(2026, 9, 20), "GSOM")
    assert [day.date for day in schedule.days][0] == date(2026, 9, 14)
    assert len(schedule.days) == 6
    assert client.requested[0].startswith("/GSOM/"), "сначала берём страницу сайта"
    assert not any(path.startswith("/api/") for path in client.requested), (
        "к API не ходим, пока страница отвечает"
    )


async def test_page_keeps_the_subgroup_mark():
    """Ради этой пометки страница и предпочтена API — без неё нет фильтра."""
    client = FakeClient(
        {"/GSOM/StudentGroupEvents/Primary/474489/2026-09-14": MINIMAL_WEEK.format(name="ru")}
    )
    schedule = await client.schedule(474489, date(2026, 9, 14), date(2026, 9, 20), "GSOM")
    assert schedule.days[0].events[0].subgroup == "Подгруппа 2"


async def test_json_api_is_used_when_the_page_is_unavailable():
    client = FakeClient({"/api/v1/groups/474489/events/2026-08-31/2026-08-31": EVENTS_JSON})
    schedule = await client.schedule(474489, date(2026, 8, 31), date(2026, 8, 31), "GSOM")
    assert schedule.group_name == "Менеджмент 2026"
    assert len(schedule.days) == 1
    assert client.requested[0].startswith("/GSOM/"), "страницу пробовали первой"


async def test_empty_page_is_checked_against_the_api():
    """Пустая страница — это либо каникулы, либо сломанный разбор."""
    client = FakeClient(
        {
            "/GSOM/StudentGroupEvents/Primary/474489/2026-08-31": "<html></html>",
            "/api/v1/groups/474489/events/2026-08-31/2026-08-31": EVENTS_JSON,
        }
    )
    schedule = await client.schedule(474489, date(2026, 8, 31), date(2026, 8, 31), "GSOM")
    assert len(schedule.days) == 1


async def test_empty_week_stays_empty_when_the_api_is_silent_too():
    client = FakeClient(
        {"/GSOM/StudentGroupEvents/Primary/474489/2026-08-31": "<html></html>"}
    )
    schedule = await client.schedule(474489, date(2026, 8, 31), date(2026, 8, 31), "GSOM")
    assert schedule.days == []


async def test_schedule_range_is_swapped_when_reversed():
    client = FakeClient({"/api/v1/groups/474489/events/2026-08-31/2026-09-06": EVENTS_JSON})
    schedule = await client.schedule(474489, date(2026, 9, 6), date(2026, 8, 31))
    assert len(schedule.days) == 1


async def test_schedule_raises_when_site_is_down():
    client = FakeClient({})
    with pytest.raises(TimetableError):
        await client.schedule(474489, date(2026, 8, 31), date(2026, 8, 31), "GSOM")


async def test_language_reaches_the_site():
    client = FakeClient(
        {"/GSOM/StudentGroupEvents/Primary/1/2026-09-14": MINIMAL_WEEK.format(name="en")}
    )
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
            payload = MINIMAL_WEEK.format(name=lang)
            self._cache.set(key, payload)
            return payload

    client = Counting()
    russian = await client.schedule(1, date(2026, 9, 14), date(2026, 9, 14), "GSOM", "ru")
    english = await client.schedule(1, date(2026, 9, 14), date(2026, 9, 14), "GSOM", "en")
    again = await client.schedule(1, date(2026, 9, 14), date(2026, 9, 14), "GSOM", "ru")

    assert russian.group_name == "Группа ru"
    assert english.group_name == "Группа en"
    assert again.group_name == "Группа ru"
    assert client.hits == 2, "второй запрос на том же языке берётся из кэша"
