"""Хранилище подписок и заметок (SQLite через aiosqlite)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id      INTEGER PRIMARY KEY,
    chat_id      INTEGER NOT NULL,
    student_name TEXT    NOT NULL DEFAULT '',
    lang         TEXT    NOT NULL DEFAULT 'ru',
    language_course  TEXT NOT NULL DEFAULT '',
    language_teacher TEXT NOT NULL DEFAULT '',
    show_all     INTEGER NOT NULL DEFAULT 0,
    frequency    TEXT    NOT NULL DEFAULT 'off',
    send_hour    INTEGER NOT NULL DEFAULT 8,
    send_minute  INTEGER NOT NULL DEFAULT 0,
    next_run_at  TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    chat_id    INTEGER NOT NULL,
    text       TEXT    NOT NULL,
    due_at     TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'pending',
    created_at TEXT    NOT NULL,
    sent_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_notes_due ON notes (status, due_at);
CREATE INDEX IF NOT EXISTS idx_subscriptions_next_run ON subscriptions (next_run_at);
"""

# Колонки, добавленные после первой версии новой схемы: их дописываем
# в существующую таблицу через ALTER TABLE.
LATER_COLUMNS = {
    "lang": "lang TEXT NOT NULL DEFAULT 'ru'",
    "language_course": "language_course TEXT NOT NULL DEFAULT ''",
    "language_teacher": "language_teacher TEXT NOT NULL DEFAULT ''",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class Subscription:
    user_id: int
    chat_id: int
    student_name: str = ""
    lang: str = "ru"
    # Изучаемый иностранный язык и, если групп несколько, преподаватель
    language_course: str = ""
    language_teacher: str = ""
    show_all: bool = False
    frequency: str = "off"
    send_hour: int = 8
    send_minute: int = 0
    next_run_at: datetime | None = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Subscription":
        return cls(
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            student_name=row["student_name"],
            lang=row["lang"],
            language_course=row["language_course"],
            language_teacher=row["language_teacher"],
            show_all=bool(row["show_all"]),
            frequency=row["frequency"],
            send_hour=row["send_hour"],
            send_minute=row["send_minute"],
            next_run_at=_parse(row["next_run_at"]),
        )

    @property
    def send_time(self) -> str:
        return f"{self.send_hour:02d}:{self.send_minute:02d}"


@dataclass
class Note:
    id: int
    user_id: int
    chat_id: int
    text: str
    due_at: datetime
    status: str = "pending"

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Note":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            text=row["text"],
            due_at=_parse(row["due_at"]) or utcnow(),
            status=row["status"],
        )


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._migrate()
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def _migrate(self) -> None:
        """Переезд со схемы, где студент выбирал направление и группу.

        Расписание теперь одно — MiM, — а вместо группы хранится фамилия.
        Настройки рассылки переносим, но снимаем с расписания: при первом
        обращении бот попросит фамилию заново.
        """
        async with self._db.execute("PRAGMA table_info(subscriptions)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if not columns:
            return

        if "student_name" in columns:
            # Схема уже новая: добавляем колонки, появившиеся позже.
            for column, ddl in LATER_COLUMNS.items():
                if column not in columns:
                    await self._db.execute(f"ALTER TABLE subscriptions ADD COLUMN {ddl}")
            await self._db.commit()
            return

        await self._db.executescript(
            """
            ALTER TABLE subscriptions RENAME TO subscriptions_old;
            """
            + SCHEMA
            + """
            INSERT INTO subscriptions (
                user_id, chat_id, student_name, lang, show_all, frequency,
                send_hour, send_minute, next_run_at, created_at, updated_at
            )
            SELECT user_id, chat_id, '', 'ru', 0, frequency,
                   send_hour, send_minute, NULL, created_at, updated_at
            FROM subscriptions_old;
            DROP TABLE subscriptions_old;
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Storage.connect() не вызван")
        return self._db

    # --- Подписки ------------------------------------------------------

    async def get_subscription(self, user_id: int) -> Subscription | None:
        async with self.db.execute(
            "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return Subscription.from_row(row) if row else None

    async def save_subscription(self, subscription: Subscription) -> None:
        now = _iso(utcnow())
        await self.db.execute(
            """
            INSERT INTO subscriptions (
                user_id, chat_id, student_name, lang, language_course, language_teacher,
                show_all, frequency, send_hour, send_minute, next_run_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                chat_id          = excluded.chat_id,
                student_name     = excluded.student_name,
                lang             = excluded.lang,
                language_course  = excluded.language_course,
                language_teacher = excluded.language_teacher,
                show_all         = excluded.show_all,
                frequency    = excluded.frequency,
                send_hour    = excluded.send_hour,
                send_minute  = excluded.send_minute,
                next_run_at  = excluded.next_run_at,
                updated_at   = excluded.updated_at
            """,
            (
                subscription.user_id,
                subscription.chat_id,
                subscription.student_name,
                subscription.lang,
                subscription.language_course,
                subscription.language_teacher,
                int(subscription.show_all),
                subscription.frequency,
                subscription.send_hour,
                subscription.send_minute,
                _iso(subscription.next_run_at),
                now,
                now,
            ),
        )
        await self.db.commit()

    async def set_next_run(self, user_id: int, moment: datetime | None) -> None:
        await self.db.execute(
            "UPDATE subscriptions SET next_run_at = ?, updated_at = ? WHERE user_id = ?",
            (_iso(moment), _iso(utcnow()), user_id),
        )
        await self.db.commit()

    async def due_subscriptions(self, moment: datetime) -> list[Subscription]:
        async with self.db.execute(
            """
            SELECT * FROM subscriptions
            WHERE frequency != 'off' AND next_run_at IS NOT NULL AND next_run_at <= ?
            ORDER BY next_run_at
            """,
            (_iso(moment),),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Subscription.from_row(row) for row in rows]

    async def delete_subscription(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        await self.db.commit()

    # --- Заметки -------------------------------------------------------

    async def add_note(self, user_id: int, chat_id: int, text: str, due_at: datetime) -> int:
        cursor = await self.db.execute(
            "INSERT INTO notes (user_id, chat_id, text, due_at, status, created_at)"
            " VALUES (?, ?, ?, ?, 'pending', ?)",
            (user_id, chat_id, text, _iso(due_at), _iso(utcnow())),
        )
        await self.db.commit()
        return int(cursor.lastrowid)

    async def pending_notes(self, user_id: int) -> list[Note]:
        async with self.db.execute(
            "SELECT * FROM notes WHERE user_id = ? AND status = 'pending' ORDER BY due_at",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Note.from_row(row) for row in rows]

    async def due_notes(self, moment: datetime) -> list[Note]:
        async with self.db.execute(
            "SELECT * FROM notes WHERE status = 'pending' AND due_at <= ? ORDER BY due_at",
            (_iso(moment),),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Note.from_row(row) for row in rows]

    async def mark_note_sent(self, note_id: int) -> None:
        await self.db.execute(
            "UPDATE notes SET status = 'sent', sent_at = ? WHERE id = ?",
            (_iso(utcnow()), note_id),
        )
        await self.db.commit()

    async def delete_note(self, user_id: int, note_id: int) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM notes WHERE id = ? AND user_id = ? AND status = 'pending'",
            (note_id, user_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0
