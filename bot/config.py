"""Настройки бота из переменных окружения (или файла .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


def load_dotenv(path: str | Path = ".env") -> None:
    """Минимальный разбор .env, чтобы не тянуть лишнюю зависимость."""
    file = Path(path)
    if not file.exists():
        return
    for raw_line in file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_path: Path
    tz_name: str
    base_url: str
    http_cache_ttl: float
    http_timeout: float
    log_level: str

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)


def load_settings() -> Settings:
    load_dotenv()
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Не задан BOT_TOKEN. Скопируйте .env.example в .env и укажите токен от @BotFather."
        )
    db_path = Path(os.environ.get("DB_PATH", "data/bot.sqlite3"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        bot_token=token,
        db_path=db_path,
        tz_name=os.environ.get("TZ_NAME", "Europe/Moscow"),
        base_url=os.environ.get("TIMETABLE_BASE_URL", "https://timetable.spbu.ru"),
        http_cache_ttl=float(os.environ.get("HTTP_CACHE_TTL", "900")),
        http_timeout=float(os.environ.get("HTTP_TIMEOUT", "20")),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )
