"""HTTP-клиент расписания СПбГУ.

Сначала пробуется JSON-API (`/api/v1/...`), при ошибке — разбор HTML той же
страницы расписания. Ответы кэшируются на ``cache_ttl`` секунд, чтобы не
ходить на сайт при каждом запросе.

Бот обслуживает одну программу (MiM), поэтому справочники подразделений и
программ клиенту не нужны: идентификатор группы задаётся настройкой.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

import aiohttp

from . import api, scraper
from .models import Schedule

logger = logging.getLogger(__name__)

USER_AGENT = "timetable-spbu-bot/1.0 (+https://github.com/sheeshlove/timetable_spbu)"
MAX_WEEKS_PER_REQUEST = 8

# Сайт запоминает язык в куке, которую ставит эта форма. Имя куки нам знать не
# нужно: aiohttp сохранит её сам, поэтому на каждый язык заводится своя сессия
# со своим хранилищем кук.
CULTURE_PATH = "/Base/SetClientCultureCookie"
ACCEPT_LANGUAGE = {"ru": "ru-RU,ru;q=0.9,en;q=0.5", "en": "en-US,en;q=0.9,ru;q=0.5"}
SITE_CULTURES = {"ru": "ru", "en": "en-us"}


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
        self._sessions: dict[str, aiohttp.ClientSession] = {}
        if session is not None:
            self._sessions["ru"] = session
        self._owns_sessions = session is None
        self._culture_set: set[str] = set()
        self._lock = asyncio.Lock()

    async def _get_session(self, lang: str = "ru") -> aiohttp.ClientSession:
        session = self._sessions.get(lang)
        if session is not None and not session.closed:
            return session
        async with self._lock:
            session = self._sessions.get(lang)
            if session is None or session.closed:
                session = aiohttp.ClientSession(
                    timeout=self._timeout,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept-Language": ACCEPT_LANGUAGE.get(lang, ACCEPT_LANGUAGE["ru"]),
                    },
                )
                self._sessions[lang] = session
                self._owns_sessions = True
        return session

    async def _ensure_culture(self, lang: str) -> None:
        """Просит сайт переключить язык и запоминает выданную куку.

        Форма переключателя на сайте отправляет `clientCultureName`; ответная
        кука сохраняется в сессии этого языка. Если запрос не удался, язык
        всё равно уходит заголовком Accept-Language.
        """
        if lang in self._culture_set:
            return
        self._culture_set.add(lang)
        culture = SITE_CULTURES.get(lang)
        if culture is None:
            return
        session = await self._get_session(lang)
        try:
            async with session.post(
                f"{self.base_url}{CULTURE_PATH}",
                data={"clientCultureName": culture},
                allow_redirects=True,
            ) as response:
                await response.read()
        except Exception:  # noqa: BLE001 — не критично, останется Accept-Language
            logger.info("Не удалось переключить язык сайта на %s", culture, exc_info=True)

    async def close(self) -> None:
        if not self._owns_sessions:
            return
        for session in self._sessions.values():
            if not session.closed:
                await session.close()

    async def _fetch(self, path: str, *, as_json: bool, lang: str = "ru") -> Any:
        cache_key = f"{'json' if as_json else 'html'}:{lang}:{path}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}{path}"
        await self._ensure_culture(lang)
        session = await self._get_session(lang)
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

    # --- Расписание ----------------------------------------------------

    async def schedule(
        self,
        group_id: int,
        start: date,
        end: date,
        alias: str | None = None,
        lang: str = "ru",
    ) -> Schedule:
        """Расписание группы за период [start, end] включительно.

        Основной источник — страницы расписания (HTML): только там есть
        пометка подгруппы («Подгруппа 2», «Cohort 1») и перевод названий на
        выбранный язык. JSON-API отдаёт те же занятия без подгруппы и всегда
        по-русски, поэтому он остался запасным вариантом: расписание без
        фильтра лучше, чем никакого.

        ``alias`` — псевдоним подразделения в адресе страницы. ``lang``
        определяет, на каком языке сайт отдаст названия занятий.
        """
        if end < start:
            start, end = end, start

        empty: Schedule | None = None
        html_error: TimetableError | None = None
        try:
            schedule = await self._schedule_html(group_id, start, end, alias, lang)
        except TimetableError as error:
            html_error = error
            logger.warning("Страница расписания недоступна (%s), пробуем JSON-API", error)
        else:
            if schedule.days:
                return schedule
            # Пустая неделя бывает (каникулы), но бывает и сломанный разбор —
            # сверимся с API, прежде чем говорить студенту «занятий нет».
            empty = schedule
            logger.info("Страница расписания пуста за %s — %s, сверяюсь с JSON-API", start, end)

        try:
            return await self._schedule_api(group_id, start, end, lang)
        except TimetableError as error:
            if empty is not None:
                return empty
            raise TimetableError(f"{html_error}; {error}") from error

    async def _schedule_api(
        self, group_id: int, start: date, end: date, lang: str = "ru"
    ) -> Schedule:
        """Запасной источник. Занятия те же, но без пометки подгруппы."""
        payload = await self._fetch(
            api.EVENTS_PATH.format(
                group_id=group_id, start=start.isoformat(), end=end.isoformat()
            ),
            as_json=True,
            lang=lang,
        )
        schedule = api.parse_schedule(payload, group_id)
        if not schedule.days:
            raise TimetableError(f"JSON-API вернул пустое расписание для группы {group_id}")
        return _slice(schedule, start, end)

    async def _schedule_html(
        self, group_id: int, start: date, end: date, alias: str | None, lang: str = "ru"
    ) -> Schedule:
        weeks: list[Schedule] = []
        monday = start - timedelta(days=start.weekday())
        errors: list[str] = []
        while monday <= end and len(weeks) < MAX_WEEKS_PER_REQUEST:
            prefix = f"/{alias}" if alias else ""
            path = f"{prefix}/StudentGroupEvents/Primary/{group_id}/{monday.isoformat()}"
            try:
                html = await self._fetch(path, as_json=False, lang=lang)
            except TimetableError as error:
                errors.append(str(error))
                monday += timedelta(days=7)
                continue
            weeks.append(scraper.parse_schedule_html(html, group_id, fallback_year=monday.year))
            monday += timedelta(days=7)
        if not weeks:
            raise TimetableError("Расписание недоступно: " + ("; ".join(errors) or "нет данных"))
        return _slice(api.merge_schedules(weeks), start, end)

    async def week(
        self, group_id: int, monday: date, alias: str | None = None, lang: str = "ru"
    ) -> Schedule:
        return await self.schedule(group_id, monday, monday + timedelta(days=6), alias, lang)

    async def day(
        self, group_id: int, target: date, alias: str | None = None, lang: str = "ru"
    ) -> Schedule:
        return await self.schedule(group_id, target, target, alias, lang)


def _slice(schedule: Schedule, start: date, end: date) -> Schedule:
    """Оставляет только дни внутри запрошенного диапазона."""
    days = [day for day in schedule.days if day.date is None or start <= day.date <= end]
    return Schedule(
        group_id=schedule.group_id, group_name=schedule.group_name, days=days, url=schedule.url
    )
