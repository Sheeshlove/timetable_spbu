#!/usr/bin/env bash
# Резервная копия базы бота. Безопасно запускать на работающем боте:
# используется онлайн-бэкап SQLite, а не копирование файла.
#
#   ./deploy/backup.sh                 # копия в /opt/timetable_spbu/backups
#   BACKUP_DIR=/mnt/backup ./deploy/backup.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/timetable_spbu}"
DB_FILE="${DB_FILE:-$APP_DIR/data/bot.sqlite3}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
PYTHON="${PYTHON:-$APP_DIR/.venv/bin/python}"

if [ ! -f "$DB_FILE" ]; then
    echo "База не найдена: $DB_FILE" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
OUT="$BACKUP_DIR/bot-$(date +%Y%m%d-%H%M%S).sqlite3"

"$PYTHON" - "$DB_FILE" "$OUT" <<'PY'
import sqlite3
import sys

source_path, target_path = sys.argv[1], sys.argv[2]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
target = sqlite3.connect(target_path)
with target:
    source.backup(target)
source.close()
target.close()
PY

gzip -f "$OUT"
find "$BACKUP_DIR" -name 'bot-*.sqlite3.gz' -mtime "+$KEEP_DAYS" -delete
echo "Готово: $OUT.gz ($(du -h "$OUT.gz" | cut -f1))"
