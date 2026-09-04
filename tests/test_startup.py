"""Запуск бота: прокси до Telegram и устойчивость к обрыву связи."""

from pathlib import Path

import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

from bot.__main__ import announce_commands, build_bot, hide_credentials
from bot.config import Settings

TOKEN = "123456:AAHfake-token-for-tests"


def make_settings(**overrides) -> Settings:
    defaults = dict(
        bot_token=TOKEN,
        db_path=Path("x"),
        tz_name="Europe/Moscow",
        base_url="https://timetable.spbu.ru",
        http_cache_ttl=0,
        http_timeout=5,
        log_level="INFO",
        group_id=474489,
        division_alias="GSOM",
        program_title="Master in Management, 2026",
    )
    defaults.update(overrides)
    return Settings(**defaults)


class StubBot:
    """Минимальный двойник: нам нужен только set_my_commands."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    async def set_my_commands(self, commands):
        self.calls += 1
        if self.error is not None:
            raise self.error


async def test_commands_are_announced():
    bot = StubBot()
    await announce_commands(bot)
    assert bot.calls == 1


async def test_network_error_does_not_stop_startup():
    """Telegram недоступен — меню команд подождёт, бот должен подняться."""
    bot = StubBot(TelegramNetworkError(method=None, message="Request timeout error"))
    await announce_commands(bot)  # не должно бросить наружу
    assert bot.calls == 1


async def test_bad_token_still_fails_loudly():
    """А вот отказ самого Telegram глушить нельзя: это ошибка настройки."""
    from aiogram.exceptions import TelegramUnauthorizedError

    bot = StubBot(TelegramUnauthorizedError(method=None, message="Unauthorized"))
    with pytest.raises(TelegramUnauthorizedError):
        await announce_commands(bot)


async def test_bot_without_proxy_uses_default_session():
    bot = build_bot(make_settings())
    assert bot.session.proxy is None
    await bot.session.close()


async def test_bot_with_proxy_goes_through_it():
    bot = build_bot(make_settings(telegram_proxy="socks5://127.0.0.1:1080"))
    assert isinstance(bot.session, AiohttpSession)
    assert bot.session.proxy == "socks5://127.0.0.1:1080"
    await bot.session.close()


def test_proxy_password_is_not_logged():
    assert hide_credentials("socks5://user:secret@1.2.3.4:1080") == "socks5://***@1.2.3.4:1080"
    assert hide_credentials("http://1.2.3.4:3128") == "http://1.2.3.4:3128"
