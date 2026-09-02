"""Точка входа: `python -m bot`."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .config import Settings, load_settings
from .handlers import notes, schedule, setup
from .roster import Roster, load_roster
from .scheduler import Scheduler
from .storage import Storage
from .timetable import TimetableClient

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Начать и указать фамилию"),
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


def build_dispatcher(
    storage: Storage, client: TimetableClient, settings: Settings, roster: Roster
) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["storage"] = storage
    dispatcher["client"] = client
    dispatcher["settings"] = settings
    dispatcher["roster"] = roster
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
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    roster = load_roster(settings.roster_path) if settings.roster_path else load_roster()
    dispatcher = build_dispatcher(storage, client, settings, roster)
    scheduler = Scheduler(bot, storage, client, settings, roster)

    await bot.set_my_commands(COMMANDS)
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
