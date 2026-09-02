#!/usr/bin/env bash
# Обновление бота до свежей версии из git. Запускать от root (или через sudo).
#
#   sudo /opt/timetable_spbu/deploy/update.sh
#   sudo BRANCH=main /opt/timetable_spbu/deploy/update.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/timetable_spbu}"
APP_USER="${APP_USER:-timetable}"
BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-timetable-bot}"

cd "$APP_DIR"

echo "==> Резервная копия базы"
"$APP_DIR/deploy/backup.sh"

echo "==> Забираем изменения из ветки $BRANCH"
# --ff-only: если в рабочем каталоге правки, обновление остановится с ошибкой,
# а не затрёт их молча
runuser -u "$APP_USER" -- git fetch origin "$BRANCH"
runuser -u "$APP_USER" -- git merge --ff-only "origin/$BRANCH"

echo "==> Обновляем зависимости"
runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/pip" install --quiet --upgrade -r requirements.txt

echo "==> Перезапускаем сервис"
systemctl restart "$SERVICE"
sleep 3
systemctl --no-pager --lines=10 status "$SERVICE"
