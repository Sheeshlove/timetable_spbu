"""Мини-эмулятор Telegram: гоняем настоящий Dispatcher без сети."""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import Chat, InlineKeyboardMarkup, Message, Update, User

USER = User(id=777, is_bot=False, first_name="Аня", username="anya")
CHAT = Chat(id=777, type="private")


class FakeSession(BaseSession):
    """Возвращает правдоподобные ответы и запоминает вызовы API."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self._ids = itertools.count(1000)

    async def close(self) -> None:  # pragma: no cover - интерфейс
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - интерфейс
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout=None):
        self.calls.append(method)
        # Ответы Telegram привязаны к боту — иначе message.edit_text() из
        # хендлера не сможет отправить запрос.
        if isinstance(method, SendMessage):
            return self._message(method.text, method.reply_markup).as_(bot)
        if isinstance(method, EditMessageText):
            return self._message(
                method.text, method.reply_markup, message_id=method.message_id
            ).as_(bot)
        if isinstance(method, EditMessageReplyMarkup):
            return self._message("", method.reply_markup, message_id=method.message_id).as_(bot)
        if isinstance(method, AnswerCallbackQuery):
            return True
        return True

    def _message(self, text, markup=None, message_id: int | None = None) -> Message:
        message = Message(
            message_id=message_id or next(self._ids),
            date=datetime.now(timezone.utc),
            chat=CHAT,
            from_user=User(id=1, is_bot=True, first_name="bot"),
            text=text or "",
            reply_markup=markup if isinstance(markup, InlineKeyboardMarkup) else None,
        )
        return message

    # --- удобные выборки для тестов ---

    @property
    def texts(self) -> list[str]:
        return [
            call.text
            for call in self.calls
            if isinstance(call, (SendMessage, EditMessageText)) and call.text
        ]

    def last_markup(self) -> InlineKeyboardMarkup | None:
        for call in reversed(self.calls):
            markup = getattr(call, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup):
                return markup
        return None

    def buttons(self) -> dict[str, str]:
        """Подпись кнопки -> callback_data последней инлайн-клавиатуры."""
        markup = self.last_markup()
        if markup is None:
            return {}
        return {
            button.text: button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        }

    def clear(self) -> None:
        self.calls.clear()


class FakeTelegram:
    """Обёртка: шлём боту сообщения и нажимаем кнопки."""

    def __init__(self, dispatcher) -> None:
        self.session = FakeSession()
        self.bot = Bot(token="42:TEST", session=self.session)
        self.dispatcher = dispatcher
        self._update_ids = itertools.count(1)
        self._message_ids = itertools.count(1)

    async def send(self, text: str) -> None:
        message = Message(
            message_id=next(self._message_ids),
            date=datetime.now(timezone.utc),
            chat=CHAT,
            from_user=USER,
            text=text,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=next(self._update_ids), message=message)
        )

    async def click(self, callback_data: str) -> None:
        from aiogram.types import CallbackQuery

        message = Message(
            message_id=next(self._message_ids),
            date=datetime.now(timezone.utc),
            chat=CHAT,
            from_user=User(id=1, is_bot=True, first_name="bot"),
            text="…",
        )
        callback = CallbackQuery(
            id=str(next(self._update_ids)),
            from_user=USER,
            chat_instance="1",
            message=message,
            data=callback_data,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=next(self._update_ids), callback_query=callback)
        )

    async def click_button(self, label_part: str) -> None:
        """Нажимает кнопку, в подписи которой встречается ``label_part``."""
        buttons = self.session.buttons()
        for label, data in buttons.items():
            if label_part.lower() in label.lower():
                await self.click(data)
                return
        raise AssertionError(f"Кнопки «{label_part}» нет среди {list(buttons)}")

    async def close(self) -> None:
        await self.bot.session.close()
