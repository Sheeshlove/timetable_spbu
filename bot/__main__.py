"""Точка входа: `python -m bot`."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .config import Settings, load_settings
from .handlers import notes, schedule, setup
from .middleware import LanguageMiddleware
from .roster import Roster, load_roster
from .scheduler import Scheduler
from .storage import Storage
from .timetable import TimetableClient

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Начать и указать фамилию"),
    BotCommand(command="language", description="Язык / Language"),
    BotCommand(command="today", description="Расписание на сегодня"),
    BotCommand(command="tomorrow", description="Расписание на завтра"),
    BotCommand(command="week", description="Расписание на эту неделю"),
    BotCommand(command="nextweek", description="Расписание на следующую неделю"),
    BotCommand(command="note", description="Новая заметка"),
    BotCommand(command="notes", description="Мои заметки"),
    BotCommand(command="delnote", description="Удалить заметку"),
    BotCommand(command="cohorts", description="Мои когорты"),
    BotCommand(command="settings", description="Периодичность и время рассылки"),
    BotCommand(command="setup", description="Заново указать фамилию"),
    BotCommand(command="stop", description="Отключить рассылку"),
]


def hide_credentials(url: str) -> str:
    """Прячет логин и пароль прокси: адрес попадает в журнал."""
    if "@" not in url:
        return url
    scheme, _, rest = url.rpartition("://")
    return f"{scheme}://***@{rest.rpartition('@')[2]}" if scheme else f"***@{rest.rpartition('@')[2]}"


def build_bot(settings: Settings) -> Bot:
    """Бот, при необходимости — через прокси.

    С части хостингов (в том числе российских) `api.telegram.org` недоступен
    напрямую: запросы просто виснут до таймаута. На такой случай есть
    `TELEGRAM_PROXY` — адрес вида `socks5://user:pass@host:1080` или
    `http://host:3128`.
    """
    session = None
    if settings.telegram_proxy:
        try:
            session = AiohttpSession(proxy=settings.telegram_proxy)
        except RuntimeError as error:  # нет aiohttp-socks
            raise SystemExit(
                "TELEGRAM_PROXY задан, но не установлен пакет aiohttp-socks.\n"
                "Выполните: .venv/bin/pip install -r requirements.txt"
            ) from error
        logger.info("Telegram — через прокси %s", hide_credentials(settings.telegram_proxy))
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def announce_commands(bot: Bot) -> None:
    """Меню команд в Telegram.

    Это украшение, а не условие работы: если сеть до Telegram сейчас не
    отвечает, бот всё равно должен подняться — polling переживает обрывы сам
    и подхватит связь, когда она вернётся.
    """
    try:
        await bot.set_my_commands(COMMANDS)
    except TelegramNetworkError as error:
        logger.warning("Меню команд не обновилось, продолжаю без него: %s", error)


def build_dispatcher(
    storage: Storage, client: TimetableClient, settings: Settings, roster: Roster
) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["storage"] = storage
    dispatcher["client"] = client
    dispatcher["settings"] = settings
    dispatcher["roster"] = roster
    # Язык пользователя подставляется до хендлеров — им нужен готовый `t`.
    dispatcher.message.middleware(LanguageMiddleware())
    dispatcher.callback_query.middleware(LanguageMiddleware())
    # Порядок важен: мастер настройки и команды идут раньше, чем перехват
    # свободного текста в заметках.
    dispatcher.include_router(setup.router)
    dispatcher.include_router(schedule.router)
    dispatcher.include_router(notes.router)
    return dispatcher


async def run() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    storage = Storage(settings.db_path)
    await storage.connect()
    client = TimetableClient(
        settings.base_url, timeout=settings.http_timeout, cache_ttl=settings.http_cache_ttl
    )
    bot = build_bot(settings)
    roster = load_roster(settings.roster_path) if settings.roster_path else load_roster()
    dispatcher = build_dispatcher(storage, client, settings, roster)
    scheduler = Scheduler(bot, storage, client, settings, roster)

    await announce_commands(bot)
    scheduler.start()
    logger.info(
        "Бот запущен: программа «%s», группа %s, студентов в списке %s, пояс %s",
        settings.program_title,
        settings.group_id,
        len(roster.students),
        settings.tz_name,
    )
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await scheduler.stop()
        await client.close()
        await storage.close()
        await bot.session.close()


def main() -> None:
    # SystemExit не перехватываем: это подсказка про BOT_TOKEN из load_settings,
    # и её должен увидеть тот, кто запускает бота.
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Остановлено")


if __name__ == "__main__":
    main()
