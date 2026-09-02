"""Подстановка языка пользователя в хендлеры."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from .i18n import DEFAULT_LANG, Translator, normalize_lang
from .storage import Storage


class LanguageMiddleware(BaseMiddleware):
    """Кладёт в хендлеры `t` — переводчик на языке пользователя.

    Язык берётся из сохранённой подписки; пока её нет — из выбора, сделанного
    в текущем диалоге, а до выбора — из языка Telegram-клиента. Так первое
    сообщение приходит уже на понятном языке.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        storage: Storage | None = data.get("storage")
        lang = DEFAULT_LANG

        if user is not None and storage is not None:
            subscription = await storage.get_subscription(user.id)
            if subscription is not None:
                lang = subscription.lang
            else:
                state = data.get("state")
                chosen = (await state.get_data()).get("lang") if state else None
                lang = chosen or normalize_lang(user.language_code)

        data["lang"] = lang
        data["t"] = Translator(lang)
        return await handler(event, data)
