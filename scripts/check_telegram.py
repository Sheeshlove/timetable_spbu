#!/usr/bin/env python3
"""Проверка связи с Telegram с этого сервера.

Бот не заработает, если с сервера не дотянуться до `api.telegram.org`, а
выглядит это одинаково при любой причине: запрос висит до таймаута. Скрипт
показывает, что именно не так — не резолвится имя, не устанавливается
соединение или отвечает сам Telegram, — и делает несколько попыток подряд:
блокировки часто пропускают первый запрос и режут следующие.

    python scripts/check_telegram.py                    # 5 попыток
    python scripts/check_telegram.py --tries 20         # поймать «через раз»
    python scripts/check_telegram.py --ipv4             # только IPv4
    python scripts/check_telegram.py --proxy socks5://127.0.0.1:1080

Токен берётся из `.env` (`BOT_TOKEN`), прокси — из `--proxy` или
`TELEGRAM_PROXY`. Токен нигде не печатается.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import time
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.config import load_dotenv  # noqa: E402

HOST = "api.telegram.org"
OK = "✅"
FAIL = "❌"


def resolve(family: int, label: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(HOST, 443, family, socket.SOCK_STREAM)
    except socket.gaierror as error:
        print(f"{FAIL} DNS {label}: {error}")
        return []
    addresses = sorted({info[4][0] for info in infos})
    print(f"{OK} DNS {label}: {', '.join(addresses)}")
    return addresses


def make_connector(proxy: str, ipv4_only: bool) -> aiohttp.BaseConnector:
    family = socket.AF_INET if ipv4_only else socket.AF_UNSPEC
    if not proxy:
        return aiohttp.TCPConnector(family=family)
    try:
        from aiohttp_socks import ProxyConnector
    except ImportError:
        raise SystemExit(
            "Для проверки через прокси нужен пакет aiohttp-socks:\n"
            "  .venv/bin/pip install -r requirements.txt"
        ) from None
    return ProxyConnector.from_url(proxy)


async def check(url: str, connector: aiohttp.BaseConnector, tries: int, seconds: float) -> int:
    """Делает запросы подряд и возвращает число удачных."""
    good = 0
    timeout = aiohttp.ClientTimeout(total=seconds)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for number in range(1, tries + 1):
            started = time.monotonic()
            try:
                async with session.get(url) as response:
                    raw = await response.text()
                    status = response.status
            except asyncio.TimeoutError:
                print(f"{FAIL} попытка {number}: таймаут ({time.monotonic() - started:.1f} с)")
                continue
            except Exception as error:  # noqa: BLE001 — здесь важна любая причина
                print(f"{FAIL} попытка {number}: {type(error).__name__}: {error}")
                continue
            spent = time.monotonic() - started
            try:
                body = json.loads(raw)
            except ValueError:
                # Не JSON — значит отвечал не Telegram, а что-то по дороге:
                # страница-заглушка провайдера или прокси.
                snippet = " ".join(raw.split())[:120]
                print(f"{FAIL} попытка {number}: ответ не от Telegram ({status}): {snippet}")
                continue
            if body.get("ok"):
                good += 1
                username = body.get("result", {}).get("username", "?")
                print(f"{OK} попытка {number}: @{username}, {spent:.2f} с")
            else:
                description = body.get("description", body)
                print(f"{FAIL} попытка {number}: Telegram ответил отказом ({status}): {description}")
    return good


def verdict(good: int, tries: int, proxy: str) -> int:
    print(f"\nУдачных: {good} из {tries}")
    if good == tries:
        print("Связь с Telegram есть. Если бот всё равно молчит — дело не в сети.")
        return 0
    hint = (
        "Проверьте тем же скриптом через прокси или VPN:\n"
        "  python scripts/check_telegram.py --proxy socks5://логин:пароль@адрес:порт\n"
        "Если через прокси работает — пропишите его в .env как TELEGRAM_PROXY\n"
        "и перезапустите бота: systemctl restart timetable-bot"
    )
    if proxy:
        hint = "Прокси тоже не тянет: проверьте его адрес, доступность и учётные данные."
    if good == 0:
        print(f"Связи нет совсем — похоже на блокировку Telegram у хостинга.\n{hint}")
    else:
        print(f"Связь рвётся через раз — похоже на фильтрацию трафика.\n{hint}")
    return 1


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tries", type=int, default=5, help="сколько запросов сделать")
    parser.add_argument("--timeout", type=float, default=15, help="таймаут запроса, секунды")
    parser.add_argument("--proxy", default="", help="прокси; по умолчанию TELEGRAM_PROXY из .env")
    parser.add_argument("--ipv4", action="store_true", help="только IPv4")
    args = parser.parse_args()

    load_dotenv()
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        print(f"{FAIL} В .env нет BOT_TOKEN — проверять нечего.")
        return 2
    proxy = args.proxy or os.environ.get("TELEGRAM_PROXY", "").strip()

    resolve(socket.AF_INET, "IPv4")
    if not args.ipv4:
        resolve(socket.AF_INET6, "IPv6")

    print(f"\nПрокси: {proxy or 'нет, напрямую'}")
    good = await check(
        f"https://{HOST}/bot{token}/getMe",
        make_connector(proxy, args.ipv4),
        args.tries,
        args.timeout,
    )
    return verdict(good, args.tries, proxy)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
