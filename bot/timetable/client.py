"""HTTP-клиент расписания СПбГУ.

Сначала пробуется JSON-API (`/api/v1/...`), при ошибке — разбор HTML тех же
разделов сайта. Ответы кэшируются на ``cache_ttl`` секунд, чтобы не ходить
на сайт при каждом нажатии кнопки.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

import aiohttp

from . import api, scraper
from .models import AdmissionYear, Division, Program, Schedule, StudentGroup

logger = logging.getLogger(__name__)

USER_AGENT = "timetable-spbu-bot/1.0 (+https://github.com/sheeshlove/timetable_spbu)"
MAX_WEEKS_PER_REQUEST = 8


class TimetableError(RuntimeError):
    """Сайт расписания недоступен или ответил неожиданным образом."""


class _TTLCache:
    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        self._data.clear()


class TimetableClient:
    def __init__(
        self,
        base_url: str = "https://timetable.spbu.ru",
        *,
        timeout: float = 20.0,
        cache_ttl: float = 900.0,
        retries: int = 2,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._retries = max(0, retries)
        self._cache = _TTLCache(cache_ttl)
        self._session = session
        self._owns_session = session is None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            async with self._lock:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession(
                        timeout=self._timeout,
                        headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
                    )
                    self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._session is not None and self._owns_session and not self._session.closed:
            await self._session.close()

    async def _fetch(self, path: str, *, as_json: bool) -> Any:
        cache_key = f"{'json' if as_json else 'html'}:{path}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}{path}"
        session = await self._get_session()
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                headers = {"Accept": "application/json"} if as_json else {"Accept": "text/html"}
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    payload = (
                        await response.json(content_type=None)
                        if as_json
                        else await response.text()
                    )
            except Exception as error:  # noqa: BLE001 — переигрываем любую сетевую ошибку
                last_error = error
                if attempt < self._retries:
                    await asyncio.sleep(2**attempt)
                continue
            self._cache.set(cache_key, payload)
            return payload
        raise TimetableError(f"Не удалось загрузить {url}: {last_error}")

    # --- Справочники ---------------------------------------------------

    async def divisions(self) -> list[Division]:
        try:
            payload = await self._fetch(api.DIVISIONS_PATH, as_json=True)
            divisions = api.parse_divisions(payload)
            if divisions:
                return divisions
            logger.warning("JSON-API вернул пустой список подразделений, пробуем HTML")
        except TimetableError as error:
            logger.warning("JSON-API подразделений недоступен (%s), пробуем HTML", error)
        html = await self._fetch("/", as_json=False)
        divisions = scraper.parse_divisions_html(html)
        if not divisions:
            raise TimetableError("Не удалось получить список направлений")
        return divisions

    async def programs(self, alias: str) -> list[Program]:
        payload = await self._programs_payload(alias)
        programs = (
            api.parse_programs(payload)
            if isinstance(payload, (list, dict))
            else scraper.parse_programs_html(payload)
        )
        if not programs:
            raise TimetableError(f"Для «{alias}» не найдено ни одной программы")
        return programs

    async def admission_years(self, alias: str, program_key: str) -> list[AdmissionYear]:
        payload = await self._programs_payload(alias)
        years = (
            api.parse_admission_years(payload, program_key)
            if isinstance(payload, (list, dict))
            else scraper.parse_admission_years_html(payload, program_key)
        )
        if not years:
            raise TimetableError("Не найдено годов поступления для этой программы")
        return years

    async def _programs_payload(self, alias: str) -> Any:
        """JSON-список уровней либо HTML страницы подразделения."""
        try:
            payload = await self._fetch(api.PROGRAMS_PATH.format(alias=alias), as_json=True)
            if api.parse_programs(payload):
                return payload
            logger.warning("JSON-API вернул пустые программы для %s, пробуем HTML", alias)
        except TimetableError as error:
            logger.warning("JSON-API программ недоступен (%s), пробуем HTML", error)
        return await self._fetch(f"/{alias}", as_json=False)

    async def groups(self, year: AdmissionYear) -> list[StudentGroup]:
        if year.group_id is not None:
            return [StudentGroup(group_id=year.group_id, name=year.name)]
        payload = await self._fetch(
            api.GROUPS_PATH.format(program_id=year.program_id), as_json=True
        )
        groups = api.parse_groups(payload)
        if not groups:
            raise TimetableError("У этого года поступления нет учебных групп")
        return groups

    # --- Расписание ----------------------------------------------------

    async def schedule(
        self, group_id: int, start: date, end: date, alias: str | None = None
    ) -> Schedule:
        """Расписание группы за период [start, end] включительно.

        ``alias`` нужен только для резервного разбора HTML: адрес страницы
        расписания содержит псевдоним подразделения.
        """
        if end < start:
            start, end = end, start
        try:
            payload = await self._fetch(
                api.EVENTS_PATH.format(
                    group_id=group_id, start=start.isoformat(), end=end.isoformat()
                ),
                as_json=True,
            )
            schedule = api.parse_schedule(payload, group_id)
            if schedule.days:
                return _slice(schedule, start, end)
            logger.warning("JSON-API вернул пустое расписание для группы %s", group_id)
        except TimetableError as error:
            logger.warning("JSON-API расписания недоступен (%s), пробуем HTML", error)
        return await self._schedule_html(group_id, start, end, alias)

    async def _schedule_html(
        self, group_id: int, start: date, end: date, alias: str | None
    ) -> Schedule:
        weeks: list[Schedule] = []
        monday = start - timedelta(days=start.weekday())
        errors: list[str] = []
        while monday <= end and len(weeks) < MAX_WEEKS_PER_REQUEST:
            prefix = f"/{alias}" if alias else ""
            path = f"{prefix}/StudentGroupEvents/Primary/{group_id}/{monday.isoformat()}"
            try:
                html = await self._fetch(path, as_json=False)
            except TimetableError as error:
                errors.append(str(error))
                monday += timedelta(days=7)
                continue
            weeks.append(scraper.parse_schedule_html(html, group_id, fallback_year=monday.year))
            monday += timedelta(days=7)
        if not weeks:
            raise TimetableError("Расписание недоступно: " + ("; ".join(errors) or "нет данных"))
        return _slice(api.merge_schedules(weeks), start, end)

    async def week(self, group_id: int, monday: date, alias: str | None = None) -> Schedule:
        return await self.schedule(group_id, monday, monday + timedelta(days=6), alias)

    async def day(self, group_id: int, target: date, alias: str | None = None) -> Schedule:
        return await self.schedule(group_id, target, target, alias)


def _slice(schedule: Schedule, start: date, end: date) -> Schedule:
    """Оставляет только дни внутри запрошенного диапазона."""
    days = [day for day in schedule.days if day.date is None or start <= day.date <= end]
    return Schedule(
        group_id=schedule.group_id, group_name=schedule.group_name, days=days, url=schedule.url
    )
