"""Сборка текстов сообщений: расписание, заметки, карточка подписки."""

from __future__ import annotations

from datetime import date, datetime, timezone
from html import escape

from .roster import Roster, Student
from .scheduling import DAILY, FREQUENCY_TITLES, MONTHLY, WEEKLY
from .storage import Note, Subscription
from .timetable.models import Day, Schedule

WEEKDAYS = (
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
)
MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
MONTHS_NOMINATIVE = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)
TELEGRAM_LIMIT = 4096


def human_date(day: date) -> str:
    return f"{day.day} {MONTHS_GENITIVE[day.month - 1]}, {WEEKDAYS[day.weekday()]}"


def format_day(day: Day) -> str:
    """Один день расписания."""
    title = human_date(day.date) if day.date else (day.title or "Без даты")
    lines = [f"<b>{escape(title)}</b>"]
    if not day.events:
        lines.append("  — занятий нет")
        return "\n".join(lines)
    for event in day.events:
        subject = escape(event.subject)
        if event.is_canceled:
            subject = f"<s>{subject}</s> ❌ отменено"
        interval = escape(event.interval)
        lines.append(f"  🕘 <b>{interval}</b> {subject}" if interval else f"  🕘 {subject}")
        if event.educators:
            lines.append(f"     👤 {escape(event.educators)}")
        if event.locations:
            lines.append(f"     📍 {escape(event.locations)}")
    return "\n".join(lines)


def format_schedule(schedule: Schedule, header: str = "", footer: str = "") -> str:
    """Расписание целиком. Дни без занятий не печатаются, если их много."""
    parts: list[str] = []
    if header:
        parts.append(f"<b>{escape(header)}</b>")
    if schedule.group_name:
        parts.append(f"👥 {escape(schedule.group_name)}")

    days_with_events = [day for day in schedule.days if day.events]
    days = schedule.days if len(schedule.days) <= 7 else days_with_events
    if not days_with_events:
        parts.append("\nЗанятий на этот период нет 🎉")
    else:
        parts.extend("\n" + format_day(day) for day in days)
    if footer:
        parts.append(f"\n<i>{escape(footer)}</i>")
    if schedule.url:
        parts.append(f'\n<a href="{escape(schedule.url, quote=True)}">Открыть на сайте</a>')
    return "\n".join(parts)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Режет длинное сообщение по границам строк под лимит Telegram."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # аномально длинная строка
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def format_cohorts(student: Student, roster: Roster) -> str:
    """Список «предмет — когорта» для конкретного студента."""
    pairs = roster.describe(student)
    if not pairs:
        return "Когорты для вас в списке не указаны."
    lines = ["<b>Ваши когорты</b>"]
    lines.extend(f"  · {escape(title)} — <b>{escape(value)}</b>" for title, value in pairs)
    return "\n".join(lines)


def format_subscription(subscription: Subscription, settings, roster: Roster) -> str:
    """Карточка текущих настроек."""
    lines = ["<b>Ваши настройки</b>", f"🎓 Программа: {escape(settings.program_title)}"]

    student = roster.get(subscription.student_name) if subscription.student_name else None
    if student:
        lines.append(f"👤 Вы: {escape(student.name)}")
    elif subscription.student_name:
        lines.append(
            f"👤 Вы: {escape(subscription.student_name)} "
            "(в текущем списке не найдены — обновите фамилию)"
        )
    else:
        lines.append("👤 Фамилия не указана — показываю расписание всей программы")

    if student:
        lines.append(
            "🔎 Показываю: "
            + ("всё расписание" if subscription.show_all else "только занятия моих когорт")
        )
    lines.append(
        f"🔔 Рассылка: {FREQUENCY_TITLES.get(subscription.frequency, subscription.frequency)}"
    )
    if subscription.frequency != "off":
        lines.append(f"⏰ Время: {subscription.send_time}")
        if subscription.next_run_at:
            local = subscription.next_run_at.astimezone(settings.tz)
            lines.append(f"➡️ Следующая отправка: {local:%d.%m.%Y %H:%M}")

    if student and not subscription.show_all:
        lines.append("\n" + format_cohorts(student, roster))
    return "\n".join(lines)


def format_notes(notes: list[Note], tz) -> str:
    if not notes:
        return "У вас нет запланированных заметок."
    lines = ["<b>Запланированные заметки</b>"]
    for note in notes:
        when = note.due_at.astimezone(tz)
        lines.append(f"\n#{note.id} — {when:%d.%m.%Y %H:%M}\n{escape(note.text)}")
    lines.append("\nУдалить: /delnote &lt;номер&gt;")
    return "\n".join(lines)


def digest_header(frequency: str, start: date, end: date) -> str:
    if frequency == DAILY:
        return f"Расписание на {human_date(start)}"
    if frequency == WEEKLY:
        return f"Расписание на неделю {start:%d.%m} — {end:%d.%m}"
    if frequency == MONTHLY:
        return f"Расписание на {MONTHS_NOMINATIVE[start.month - 1]} {start.year}"
    return f"Расписание {start:%d.%m} — {end:%d.%m}"


def format_note_reminder(note: Note, tz) -> str:
    when = note.due_at.astimezone(tz)
    return f"📝 <b>Ваша заметка на {when:%d.%m.%Y}</b>\n\n{escape(note.text)}"


def now_local(tz) -> datetime:
    """Текущее время в часовом поясе рассылки."""
    return datetime.now(timezone.utc).astimezone(tz)
