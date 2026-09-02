# Развёртывание бота на сервере

Пошаговая инструкция: от чистого сервера до работающего бота, который сам
поднимается после перезагрузки. Все команды проверены на Ubuntu 24.04.

Оглавление:

1. [Что понадобится](#что-понадобится)
2. [Шаг 1. Получить токен бота](#шаг-1-получить-токен-бота)
3. [Шаг 2. Подготовить сервер](#шаг-2-подготовить-сервер)
4. [Шаг 3. Установить Python](#шаг-3-установить-python)
5. [Шаг 4. Выложить код и собрать окружение](#шаг-4-выложить-код-и-собрать-окружение)
6. [Шаг 5. Заполнить .env](#шаг-5-заполнить-env)
7. [Шаг 6. Проверить перед запуском](#шаг-6-проверить-перед-запуском)
8. [Шаг 7. Настроить автозапуск через systemd](#шаг-7-настроить-автозапуск-через-systemd)
9. [Шаг 8. Проверить бота в Telegram](#шаг-8-проверить-бота-в-telegram)
10. [Логи и наблюдение](#логи-и-наблюдение)
11. [Обновление списка студентов](#обновление-списка-студентов)
12. [Обновление](#обновление)
13. [Резервные копии](#резервные-копии)
14. [Вариант с Docker](#вариант-с-docker)
15. [Устранение неполадок](#устранение-неполадок)
16. [Удаление](#удаление)

---

## Что понадобится

* **Сервер** с Linux: Ubuntu 22.04/24.04 или Debian 12. Хватит самой дешёвой
  VPS — 1 ядро, 512 МБ памяти, 5 ГБ диска. Бот работает на long polling,
  поэтому **внешний IP, домен и открытые порты не нужны**.
* **Python 3.11 или новее.**
* **Исходящий доступ в интернет** к `api.telegram.org` и `timetable.spbu.ru`.
* Токен бота от [@BotFather](https://t.me/BotFather).
* Доступ к серверу по SSH с правами `sudo`.

Дальше в командах используются:

| Что | Значение |
| --- | --- |
| Каталог приложения | `/opt/timetable_spbu` |
| Системный пользователь | `timetable` |
| Имя сервиса systemd | `timetable-bot` |

---

## Шаг 1. Получить токен бота

1. Откройте в Telegram [@BotFather](https://t.me/BotFather) и отправьте `/newbot`.
2. Введите отображаемое имя (например, `Расписание СПбГУ`).
3. Введите username — он должен заканчиваться на `bot`, например `spbu_timetable_bot`.
4. BotFather пришлёт токен вида `1234567890:AAH...`. **Это пароль от бота** —
   не публикуйте его и не коммитьте в git.

Полезно сразу задать описание, чтобы пользователи понимали, что делает бот:

```
/setdescription — Присылаю расписание MiM с учётом когорт и напоминаю о заметках
/setabouttext  — Расписание занятий ВШМ СПбГУ с timetable.spbu.ru
```

Список команд в меню бот выставляет сам при запуске — руками ничего делать
не нужно.

---

## Шаг 2. Подготовить сервер

Зайдите на сервер по SSH и обновите пакеты:

```bash
ssh root@ВАШ_СЕРВЕР

apt update && apt upgrade -y
apt install -y git curl ca-certificates
```

### Создать системного пользователя

Бот не должен работать от root. Заведите отдельного пользователя без
возможности логина:

```bash
useradd --system --home-dir /opt/timetable_spbu --shell /usr/sbin/nologin timetable
id timetable
```

Ожидаемый вывод — что-то вроде `uid=996(timetable) gid=995(timetable)`.

### Проверить часовой пояс и синхронизацию времени

Бот рассылает расписание по часам, поэтому время на сервере должно быть верным.
Сам бот работает в поясе из настройки `TZ_NAME` (по умолчанию московский), но
системные часы всё равно должны идти точно:

```bash
timedatectl set-ntp true
timedatectl
```

В выводе нужны `System clock synchronized: yes` и `NTP service: active`.

### Настроить фаервол (по желанию, но лучше сделать)

Боту не нужны входящие соединения — только исходящие. Значит, можно закрыть
всё, кроме SSH:

```bash
apt install -y ufw
ufw allow OpenSSH
ufw --force enable
ufw status
```

---

## Шаг 3. Установить Python

Проверьте, какая версия уже стоит:

```bash
python3 --version
```

**Если 3.11 или новее** (Ubuntu 24.04 — 3.12, Debian 12 — 3.11) — доставьте
только модуль venv:

```bash
apt install -y python3-venv python3-pip
```

**Если версия старее** (Ubuntu 22.04 идёт с 3.10) — поставьте Python 3.11 из
PPA deadsnakes:

```bash
apt install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt update
apt install -y python3.11 python3.11-venv
python3.11 --version
```

Дальше в командах, где написано `python3`, подставляйте `python3.11`.

Компиляторы и dev-пакеты не нужны: все зависимости ставятся из готовых
бинарных пакетов.

---

## Шаг 4. Выложить код и собрать окружение

```bash
git clone https://github.com/sheeshlove/timetable_spbu.git /opt/timetable_spbu
cd /opt/timetable_spbu
git checkout claude/spbu-timetable-telegram-bot-r944tu
```

> Ветку укажите ту, в которой лежит нужная версия. После слияния в `main`
> достаточно `git checkout main`.

Создайте виртуальное окружение и поставьте зависимости:

```bash
python3 -m venv /opt/timetable_spbu/.venv
/opt/timetable_spbu/.venv/bin/pip install --upgrade pip
/opt/timetable_spbu/.venv/bin/pip install -r /opt/timetable_spbu/requirements.txt
```

Проверьте, что всё встало:

```bash
/opt/timetable_spbu/.venv/bin/pip list | grep -Ei "aiogram|aiohttp|aiosqlite|lxml|beautifulsoup"
```

Ожидаемый вывод:

```
aiogram           3.31.0
aiohttp           3.14.3
aiosqlite         0.22.1
beautifulsoup4    4.15.0
lxml              6.1.2
```

---

## Шаг 5. Заполнить `.env`

```bash
cd /opt/timetable_spbu
cp .env.example .env
nano .env
```

Обязательно заполните `BOT_TOKEN`, остальное можно оставить по умолчанию:

```ini
BOT_TOKEN=1234567890:AAHваш_токен_от_BotFather
GROUP_ID=474489
DIVISION_ALIAS=GSOM
PROGRAM_TITLE=Master in Management, 2026
DB_PATH=data/bot.sqlite3
TZ_NAME=Europe/Moscow
TIMETABLE_BASE_URL=https://timetable.spbu.ru
HTTP_CACHE_TTL=900
HTTP_TIMEOUT=20
LOG_LEVEL=INFO
```

| Переменная | Что делает |
| --- | --- |
| `BOT_TOKEN` | Токен от @BotFather. Обязательна |
| `GROUP_ID` | Учебная группа MiM: число из адреса страницы расписания |
| `DIVISION_ALIAS` | Псевдоним подразделения в адресах сайта |
| `PROGRAM_TITLE` | Как программа называется в сообщениях бота |
| `ROSTER_PATH` | Путь к списку студентов, если храните его вне репозитория |
| `DB_PATH` | Файл базы SQLite. Относительный путь считается от каталога приложения |
| `TZ_NAME` | Часовой пояс, в котором пользователь выбирает время рассылки |
| `TIMETABLE_BASE_URL` | Адрес сайта расписания |
| `HTTP_CACHE_TTL` | Сколько секунд держать ответы сайта в кэше |
| `HTTP_TIMEOUT` | Таймаут запроса к сайту, секунды |
| `LOG_LEVEL` | `INFO` для обычной работы, `DEBUG` при разборе проблем |

Идентификатор группы берётся из адреса расписания на сайте:
`https://timetable.spbu.ru/GSOM/StudentGroupEvents/Primary/`**`474489`**`/2026-08-31`

Закройте файл от посторонних и отдайте каталог сервисному пользователю:

```bash
chmod 600 /opt/timetable_spbu/.env
mkdir -p /opt/timetable_spbu/data
chown -R timetable:timetable /opt/timetable_spbu
chmod 750 /opt/timetable_spbu
ls -l /opt/timetable_spbu/.env
```

Должно быть `-rw------- 1 timetable timetable`.

---

## Шаг 6. Проверить перед запуском

### Доступность сайта расписания

```bash
sudo -u timetable /opt/timetable_spbu/.venv/bin/python \
    /opt/timetable_spbu/scripts/probe_site.py --alias GSOM --group 474489
```

Скрипт покажет, какой источник данных отвечает и что удалось разобрать:

```
=== Расписание группы 474489 (2026-08-31 — 2026-09-06) ===
✅ JSON-API: 6 дней
   2026-08-31:
     • 10:45–12:20 Corporate Finance (Coh.2) | Окулов В. Л. | Волховский пер., 3
```

Скрипт забирает неделю дважды — по-русски и по-английски — и в конце пишет,
**переключился ли язык**. Если названия занятий совпали, культурная кука не
сработала: смотрите `_ensure_culture` в `bot/timetable/client.py`.

Заодно посмотрите, **как сайт подписывает подгруппы**: бот ждёт «Подгруппа 2»
(и «Subgroup 2» в английской версии). Если формат другой, поправьте регулярные
выражения в начале `bot/roster/filtering.py`.

Если у всех строк `❌` — сайт недоступен с этого сервера либо изменил
структуру. Бот запустится, но расписание отдавать не сможет; см.
[устранение неполадок](#устранение-неполадок).

### Доступность Telegram

```bash
curl -s "https://api.telegram.org/bot$(grep -oP '(?<=^BOT_TOKEN=).*' /opt/timetable_spbu/.env)/getMe"
```

Ответ должен быть с `"ok":true` и именем вашего бота. `"ok":false` —
проверьте токен; таймаут — исходящий доступ к Telegram закрыт.

### Тесты (по желанию)

```bash
cd /opt/timetable_spbu
/opt/timetable_spbu/.venv/bin/pip install -r requirements-dev.txt
sudo -u timetable /opt/timetable_spbu/.venv/bin/python -m pytest -q
```

Ожидается `192 passed`.

### Пробный запуск руками

```bash
cd /opt/timetable_spbu
sudo -u timetable /opt/timetable_spbu/.venv/bin/python -m bot
```

В логе появится строка:

```
2026-08-31 08:00:00 INFO     bot.__main__: Бот запущен, часовой пояс рассылки: Europe/Moscow
```

Напишите боту `/start` в Telegram — он должен ответить. Остановите
`Ctrl+C` и переходите к автозапуску.

---

## Шаг 7. Настроить автозапуск через systemd

Готовый юнит лежит в репозитории:

```bash
cp /opt/timetable_spbu/deploy/timetable-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now timetable-bot
```

Проверьте состояние:

```bash
systemctl status timetable-bot
```

Ожидается `Active: active (running)`.

Юнит уже настроен так, чтобы бот перезапускался при падении и после
перезагрузки сервера, а также был ограничен в правах: файловая система
доступна только на чтение, кроме каталога `data`, домашние каталоги скрыты,
повышение привилегий запрещено. Если вы меняли пути или имя пользователя,
поправьте их в `/etc/systemd/system/timetable-bot.service` и выполните
`systemctl daemon-reload`.

Управление сервисом:

```bash
systemctl restart timetable-bot    # перезапустить
systemctl stop timetable-bot       # остановить
systemctl disable --now timetable-bot   # выключить и убрать из автозапуска
```

---

## Шаг 8. Проверить бота в Telegram

1. Откройте бота и отправьте `/start`.
2. Выберите язык — русский или английский.
3. Напишите свою фамилию — бот покажет найденного студента и его когорты.
4. Нажмите «Это я», выберите периодичность и время рассылки.
5. Отправьте `/today` — придёт расписание на сегодня, уже без чужих когорт.
6. Отправьте любой текст, например `сдать эссе`, и выберите день — бот
   подтвердит, что пришлёт заметку.

Проверить, что рассылка запланирована, можно прямо в базе:

```bash
sudo -u timetable /opt/timetable_spbu/.venv/bin/python - <<'PY'
import sqlite3
conn = sqlite3.connect("/opt/timetable_spbu/data/bot.sqlite3")
for row in conn.execute(
    "SELECT user_id, student_name, lang, show_all, frequency, send_hour, next_run_at"
    " FROM subscriptions"
):
    print(row)
PY
```

---

## Логи и наблюдение

```bash
journalctl -u timetable-bot -f              # смотреть вживую
journalctl -u timetable-bot -n 200          # последние 200 строк
journalctl -u timetable-bot --since "1 hour ago"
journalctl -u timetable-bot -p err          # только ошибки
```

Ограничить размер журнала на диске:

```bash
journalctl --vacuum-size=200M
```

Постоянный лимит — в `/etc/systemd/journald.conf`:

```ini
[Journal]
SystemMaxUse=200M
```

затем `systemctl restart systemd-journald`.

Подробные логи на время разбора проблемы: поменяйте в `.env`
`LOG_LEVEL=DEBUG` и выполните `systemctl restart timetable-bot`. После
разбора верните `INFO` — на `DEBUG` пишется много.

---

## Обновление списка студентов

Распределение по когортам лежит в `bot/roster/mim_2026.json` и обновляется из
таблицы деканата. Скрипту нужен `openpyxl` из dev-зависимостей:

```bash
cd /opt/timetable_spbu
sudo -u timetable .venv/bin/pip install -r requirements-dev.txt
sudo -u timetable .venv/bin/python scripts/import_cohorts.py \
    ~/Cohorts_Distribution_MiM_2026.xlsx
sudo systemctl restart timetable-bot
```

Скрипт печатает, сколько студентов прочитал и какие значения когорт нашёл по
каждому предмету, — сверьтесь с таблицей перед перезапуском:

```
Студентов: 85
Убраны строки-копии (3): №52 Meleshko Mikhail, ...
  Corp. Finance    Coh.1, Coh.2
  QMBR seminars    Coh.1, Coh.2, Coh.3, Coh.4
  MPS I            Pavlovskaya, Shevchuk 1, Shevchuk 2, Zamulin
```

Если деканат переименует предмет, поправьте список `SUBJECTS` в начале
скрипта — там же заданы подстроки, по которым занятие в расписании относят к
предмету. Студенты, которых в новом списке нет, увидят расписание всей
программы и просьбу указать фамилию заново.

## Обновление

Готовый скрипт делает всё сам: бэкап базы, обновление кода и зависимостей,
перезапуск сервиса.

```bash
sudo /opt/timetable_spbu/deploy/update.sh
```

Вручную то же самое:

```bash
cd /opt/timetable_spbu
sudo /opt/timetable_spbu/deploy/backup.sh
sudo -u timetable git pull --ff-only
sudo -u timetable /opt/timetable_spbu/.venv/bin/pip install -r requirements.txt
sudo systemctl restart timetable-bot
sudo systemctl status timetable-bot
```

Если `git pull` ругается на локальные изменения — значит, файлы правили прямо
на сервере. Посмотрите что именно (`git status`, `git diff`) и решите, что с
этим делать; скрипт намеренно не затирает такие правки молча.

---

## Резервные копии

Вся память бота — один файл SQLite: подписки и заметки. Скрипт делает
онлайн-копию, останавливать бота не нужно:

```bash
sudo /opt/timetable_spbu/deploy/backup.sh
```

Копии кладутся в `/opt/timetable_spbu/backups`, старше 14 дней — удаляются.
Каталог и срок можно переопределить:

```bash
sudo BACKUP_DIR=/mnt/backup KEEP_DAYS=30 /opt/timetable_spbu/deploy/backup.sh
```

### Копия каждую ночь

```bash
sudo crontab -e
```

Добавьте строку — копия в 04:30:

```cron
30 4 * * * /opt/timetable_spbu/deploy/backup.sh >> /var/log/timetable-backup.log 2>&1
```

### Восстановление из копии

```bash
sudo systemctl stop timetable-bot
sudo -u timetable gunzip -c /opt/timetable_spbu/backups/bot-20260828-043000.sqlite3.gz \
    > /opt/timetable_spbu/data/bot.sqlite3
sudo chown timetable:timetable /opt/timetable_spbu/data/bot.sqlite3
sudo systemctl start timetable-bot
```

---

## Вариант с Docker

Если на сервере уже есть Docker, можно обойтись без systemd и venv.

```bash
git clone https://github.com/sheeshlove/timetable_spbu.git /opt/timetable_spbu
cd /opt/timetable_spbu
git checkout claude/spbu-timetable-telegram-bot-r944tu

cp .env.example .env
nano .env          # вписать BOT_TOKEN
chmod 600 .env

docker compose up -d --build
```

Управление:

```bash
docker compose logs -f          # логи
docker compose restart          # перезапуск
docker compose down             # остановить
docker compose up -d --build    # обновить после git pull
```

База лежит на хосте в `./data/bot.sqlite3` и переживает пересборку образа.
Бэкап делается тем же способом, что и без Docker:

```bash
docker compose exec bot python - <<'PY'
import sqlite3
src = sqlite3.connect("file:/app/data/bot.sqlite3?mode=ro", uri=True)
dst = sqlite3.connect("/app/data/backup.sqlite3")
with dst:
    src.backup(dst)
PY
```

---

## Устранение неполадок

Первое, что стоит сделать при любой проблеме:

```bash
systemctl status timetable-bot
journalctl -u timetable-bot -n 100 --no-pager
```

| Симптом в логе | Причина | Что делать |
| --- | --- | --- |
| `Не задан BOT_TOKEN` | Сервис не видит `.env` | Проверьте `EnvironmentFile` в юните и что файл существует: `ls -l /opt/timetable_spbu/.env` |
| `TelegramUnauthorizedError` | Неверный или отозванный токен | Сверьте токен с @BotFather, поправьте `.env`, `systemctl restart timetable-bot` |
| `TelegramConflictError: terminated by other getUpdates` | Запущено две копии бота с одним токеном | Оставьте одну: `systemctl stop timetable-bot` на лишнем сервере, проверьте `docker ps` |
| `Сайт расписания не отвечает` у пользователей | `timetable.spbu.ru` недоступен с сервера | `curl -sI https://timetable.spbu.ru` — если не отвечает, проблема в сети сервера, а не в боте |
| `probe_site.py` показывает `❌` у всех источников | Сайт сменил вёрстку или адреса | `python scripts/probe_site.py --dump tests/fixtures`, дальше правится `bot/timetable/api.py` или `scraper.py` |
| Бот не нашёл фамилию студента | Его нет в `bot/roster/mim_2026.json` | Сверьте написание с таблицей деканата и переимпортируйте список |
| Пропали занятия, которые должны быть | Фильтр принял метку за чужую когорту | Студент включает «Показывать всё расписание» в настройках; чинится в `bot/roster/filtering.py` |
| `sqlite3.OperationalError: unable to open database file` | Нет прав на каталог `data` | `chown -R timetable:timetable /opt/timetable_spbu/data` |
| `sqlite3.OperationalError: attempt to write a readonly database` | `ProtectSystem=strict` без `ReadWritePaths` | Проверьте строку `ReadWritePaths` в юните, `systemctl daemon-reload && systemctl restart timetable-bot` |
| Рассылка приходит не в то время | Часовой пояс или часы сервера | `timedatectl` и значение `TZ_NAME` в `.env` |
| Рассылка не пришла совсем | Бот стоял или сайт молчал | В логе будет `Рассылка … отложена`; попытка повторится через 15 минут. Проверьте `systemctl status` |
| `Status=203/EXEC` при старте | Неверный путь к python в юните | `ls -l /opt/timetable_spbu/.venv/bin/python`, поправьте `ExecStart` |
| Бот перезапускается по кругу | Ошибка на старте | `journalctl -u timetable-bot -n 50`; проверьте `.env` и права |

Проверить связность прямо с сервера:

```bash
curl -sI https://api.telegram.org | head -1     # ожидается HTTP/2 200 или 302
curl -sI https://timetable.spbu.ru | head -1    # ожидается HTTP/2 200
```

Убедиться, что запущен ровно один экземпляр:

```bash
systemctl is-active timetable-bot
pgrep -af "python -m bot"
```

---

## Удаление

```bash
sudo systemctl disable --now timetable-bot
sudo rm /etc/systemd/system/timetable-bot.service
sudo systemctl daemon-reload

# база и заметки пользователей — сохраните, если ещё пригодятся
sudo cp -r /opt/timetable_spbu/data ~/timetable-backup-data

sudo rm -rf /opt/timetable_spbu
sudo userdel timetable
```

Самого бота удаляют через @BotFather командой `/deletebot`.
