#!/usr/bin/env python3
"""Проверка живого сайта timetable.spbu.ru.

Запускать с машины, у которой есть доступ к сайту:

    python scripts/probe_site.py                       # группа из настроек
    python scripts/probe_site.py --group 474489        # другая группа
    python scripts/probe_site.py --lang en             # проверить английскую версию
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


async def probe(alias: str, group_id: int, dump: Path | None, langs: list[str]) -> int:
    client = TimetableClient(cache_ttl=0)
    problems = 0
    subjects: dict[str, list[str]] = {}
    try:
        for lang in langs:
            problems += await _probe_schedule(client, alias, group_id, dump, lang, subjects)
        problems += _compare_languages(subjects)
    finally:
        await client.close()
    return problems


def _compare_languages(subjects: dict[str, list[str]]) -> int:
    """Проверяет, что сайт действительно переключил язык названий занятий."""
    if len(subjects) < 2:
        return 0
    print("\n=== Языки ===")
    (first, first_names), (second, second_names) = list(subjects.items())[:2]
    if not first_names or not second_names:
        print(f"{FAIL} Не с чем сравнивать: расписание пустое хотя бы на одном языке.")
        return 1
    if first_names == second_names:
        print(
            f"{FAIL} Названия занятий совпали на «{first}» и «{second}» —"
            " сайт не переключил язык."
        )
        print("   Проверьте форму /Base/SetClientCultureCookie и куку в ответе;")
        print("   правится в bot/timetable/client.py (_ensure_culture).")
        return 1
    print(f"{OK} Язык переключается: названия занятий отличаются.")
    print(f"   {first}: {first_names[0]}")
    print(f"   {second}: {second_names[0]}")
    return 0


async def _probe_schedule(
    client: TimetableClient,
    alias: str,
    group_id: int,
    dump: Path | None,
    lang: str = "ru",
    subjects: dict[str, list[str]] | None = None,
) -> int:
    monday = date.today() - timedelta(days=date.today().weekday())
    sunday = monday + timedelta(days=6)
    print(f"\n=== Расписание группы {group_id}, язык «{lang}» ({monday} — {sunday}) ===")
    problems = 0
    try:
        payload = await client._fetch(
            api.EVENTS_PATH.format(
                group_id=group_id, start=monday.isoformat(), end=sunday.isoformat()
            ),
            as_json=True,
            lang=lang,
        )
        schedule = api.parse_schedule(payload, group_id)
        print(f"{OK if schedule.days else FAIL} JSON-API: {len(schedule.days)} дней")
        _print_schedule(schedule)
        _dump(dump, f"api_events_{lang}.json", payload)
        problems += 0 if schedule.days else 1
        if subjects is not None and schedule.days:
            subjects[lang] = _subject_names(schedule)
    except TimetableError as error:
        print(f"{FAIL} JSON-API недоступен: {error}")
        problems += 1

    try:
        path = f"/{alias}/StudentGroupEvents/Primary/{group_id}/{monday.isoformat()}"
        html = await client._fetch(path, as_json=False, lang=lang)
        schedule = scraper.parse_schedule_html(html, group_id, monday.year)
        print(f"{OK if schedule.days else FAIL} HTML: {len(schedule.days)} дней")
        _print_schedule(schedule)
        _dump(dump, f"week_page_{lang}.html", html)
        if subjects is not None and lang not in subjects and schedule.days:
            subjects[lang] = _subject_names(schedule)
    except TimetableError as error:
        print(f"{FAIL} HTML недоступен: {error}")
    return problems


def _subject_names(schedule) -> list[str]:
    return [event.subject for day in schedule.days for event in day.events]


def _print_schedule(schedule) -> None:
    for day in schedule.days[:3]:
        print(f"   {day.date or day.title}:")
        for event in day.events[:3]:
            subgroup = f" [{event.subgroup}]" if event.subgroup else ""
            print(
                f"     • {event.interval} {event.subject}{subgroup}"
                f" | {event.educators} | {event.locations}"
            )


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
    parser.add_argument("--alias", default="GSOM", help="псевдоним подразделения")
    parser.add_argument("--group", type=int, default=474489, help="id учебной группы MiM")
    parser.add_argument("--dump", type=Path, help="куда сохранить сырые ответы")
    parser.add_argument(
        "--lang",
        action="append",
        choices=["ru", "en"],
        help="язык расписания; можно указать дважды для сравнения (по умолчанию оба)",
    )
    args = parser.parse_args()

    problems = asyncio.run(
        probe(args.alias, args.group, args.dump, args.lang or ["ru", "en"])
    )
    print(
        f"\n{OK} Расписание читается."
        if not problems
        else f"\n{FAIL} Проблем: {problems}."
        " Смотрите вывод выше и правьте bot/timetable/api.py или scraper.py."
    )
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
