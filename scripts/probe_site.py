#!/usr/bin/env python3
"""Проверка живого сайта timetable.spbu.ru.

Запускать с машины, у которой есть доступ к сайту:

    python scripts/probe_site.py                       # проверить всё
    python scripts/probe_site.py --group 474489        # и расписание группы
    python scripts/probe_site.py --dump tests/fixtures # сохранить ответы

Скрипт показывает, какой способ получения данных работает — JSON-API или
разбор HTML, — и что именно распарсилось. Если сайт поменяет разметку,
запустите его и сверьтесь с выводом: чинить нужно
`bot/timetable/api.py` (JSON) или `bot/timetable/scraper.py` (HTML).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.timetable import api, scraper  # noqa: E402
from bot.timetable.client import TimetableClient, TimetableError  # noqa: E402

OK = "✅"
FAIL = "❌"


async def probe(alias: str, group_id: int | None, dump: Path | None) -> int:
    client = TimetableClient(cache_ttl=0)
    problems = 0
    try:
        problems += await _probe_divisions(client, dump)
        problems += await _probe_programs(client, alias, dump)
        if group_id:
            problems += await _probe_schedule(client, alias, group_id, dump)
    finally:
        await client.close()
    return problems


async def _probe_divisions(client: TimetableClient, dump: Path | None) -> int:
    print("\n=== Подразделения ===")
    problems = 0
    try:
        payload = await client._fetch(api.DIVISIONS_PATH, as_json=True)
        parsed = api.parse_divisions(payload)
        print(f"{OK if parsed else FAIL} JSON-API: {len(parsed)} шт. {_sample(parsed)}")
        problems += 0 if parsed else 1
        _dump(dump, "api_divisions.json", payload)
    except TimetableError as error:
        print(f"{FAIL} JSON-API недоступен: {error}")
        problems += 1

    try:
        html = await client._fetch("/", as_json=False)
        parsed = scraper.parse_divisions_html(html)
        print(f"{OK if parsed else FAIL} HTML: {len(parsed)} шт. {_sample(parsed)}")
        _dump(dump, "home_page.html", html)
    except TimetableError as error:
        print(f"{FAIL} HTML недоступен: {error}")
    return problems


async def _probe_programs(client: TimetableClient, alias: str, dump: Path | None) -> int:
    print(f"\n=== Программы и годы поступления ({alias}) ===")
    problems = 0
    try:
        payload = await client._fetch(api.PROGRAMS_PATH.format(alias=alias), as_json=True)
        programs = api.parse_programs(payload)
        print(f"{OK if programs else FAIL} JSON-API: {len(programs)} программ {_sample(programs)}")
        _dump(dump, f"api_programs_{alias}.json", payload)
        if programs:
            years = api.parse_admission_years(payload, programs[0].key)
            print(f"   годы у «{programs[0].name}»: {[year.name for year in years]}")
            if years:
                groups_payload = await client._fetch(
                    api.GROUPS_PATH.format(program_id=years[0].program_id), as_json=True
                )
                groups = api.parse_groups(groups_payload)
                print(f"   группы: {[(g.group_id, g.name) for g in groups][:5]}")
                _dump(dump, f"api_groups_{alias}.json", groups_payload)
        else:
            problems += 1
    except TimetableError as error:
        print(f"{FAIL} JSON-API недоступен: {error}")
        problems += 1

    try:
        html = await client._fetch(f"/{alias}", as_json=False)
        programs = scraper.parse_programs_html(html)
        print(f"{OK if programs else FAIL} HTML: {len(programs)} программ {_sample(programs)}")
        _dump(dump, f"division_page_{alias}.html", html)
        if programs:
            years = scraper.parse_admission_years_html(html, programs[0].key)
            print(f"   годы у «{programs[0].name}»: {[(y.name, y.group_id) for y in years]}")
    except TimetableError as error:
        print(f"{FAIL} HTML недоступен: {error}")
    return problems


async def _probe_schedule(
    client: TimetableClient, alias: str, group_id: int, dump: Path | None
) -> int:
    monday = date.today() - timedelta(days=date.today().weekday())
    sunday = monday + timedelta(days=6)
    print(f"\n=== Расписание группы {group_id} ({monday} — {sunday}) ===")
    problems = 0
    try:
        payload = await client._fetch(
            api.EVENTS_PATH.format(
                group_id=group_id, start=monday.isoformat(), end=sunday.isoformat()
            ),
            as_json=True,
        )
        schedule = api.parse_schedule(payload, group_id)
        print(f"{OK if schedule.days else FAIL} JSON-API: {len(schedule.days)} дней")
        _print_schedule(schedule)
        _dump(dump, "api_events.json", payload)
        problems += 0 if schedule.days else 1
    except TimetableError as error:
        print(f"{FAIL} JSON-API недоступен: {error}")
        problems += 1

    try:
        path = f"/{alias}/StudentGroupEvents/Primary/{group_id}/{monday.isoformat()}"
        html = await client._fetch(path, as_json=False)
        schedule = scraper.parse_schedule_html(html, group_id, monday.year)
        print(f"{OK if schedule.days else FAIL} HTML: {len(schedule.days)} дней")
        _print_schedule(schedule)
        _dump(dump, "week_page_live.html", html)
    except TimetableError as error:
        print(f"{FAIL} HTML недоступен: {error}")
    return problems


def _print_schedule(schedule) -> None:
    for day in schedule.days[:3]:
        print(f"   {day.date or day.title}:")
        for event in day.events[:3]:
            print(f"     • {event.interval} {event.subject} | {event.educators} | {event.locations}")


def _sample(items: list) -> str:
    names = [getattr(item, "name", "") for item in items[:3]]
    return f"например: {names}" if names else ""


def _dump(directory: Path | None, name: str, payload) -> None:
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if isinstance(payload, str):
        target.write_text(payload, encoding="utf-8")
    else:
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   💾 {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка структуры сайта timetable.spbu.ru")
    parser.add_argument("--alias", default="GSOM", help="псевдоним подразделения (по умолчанию GSOM)")
    parser.add_argument("--group", type=int, default=474489, help="id учебной группы")
    parser.add_argument("--dump", type=Path, help="куда сохранить сырые ответы")
    args = parser.parse_args()

    problems = asyncio.run(probe(args.alias, args.group, args.dump))
    print(
        f"\n{OK} Все источники живы." if not problems else f"\n{FAIL} Проблем: {problems}."
        " Смотрите вывод выше и правьте bot/timetable/api.py или scraper.py."
    )
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
