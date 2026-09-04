"""Сборка текстов сообщений: расписание, заметки, карточка подписки."""

from __future__ import annotations

from datetime import date, datetime, timezone
from html import escape

from .changes import Diff, Slot
from .i18n import Translator
from .languages import choice_title
from .roster import Roster, Student
from .roster.filtering import educator_value
from .scheduling import DAILY, MONTHLY, OFF, WEEKLY
from .storage import Note, Subscription
from .timetable.models import Day, Schedule

TELEGRAM_LIMIT = 4096

FREQUENCY_KEYS = {
    DAILY: "freq_daily",
    WEEKLY: "freq_weekly",
    MONTHLY: "freq_monthly",
    OFF: "freq_off",
}


def frequency_title(frequency: str, t: Translator) -> str:
    return t(FREQUENCY_KEYS.get(frequency, "freq_off"))


def human_date(day: date, t: Translator) -> str:
    month = t.months_in_date[day.month - 1]
    weekday = t.weekdays[day.weekday()]
    if t.lang == "en":
        return f"{month} {day.day}, {weekday}"
    return f"{day.day} {month}, {weekday}"


def format_day(day: Day, t: Translator) -> str:
    """Один день расписания."""
    title = human_date(day.date, t) if day.date else (day.title or "")
    lines = [f"<b>{escape(title)}</b>"]
    if not day.events:
        lines.append(t("no_classes_day"))
        return "\n".join(lines)
    for event in day.events:
        subject = escape(event.subject)
        if event.subgroup:
            subject += f" · {escape(event.subgroup)}"
        if event.is_canceled:
            subject = f"<s>{subject}</s> ❌ {t('canceled')}"
        interval = escape(event.interval)
        lines.append(f"  🕘 <b>{interval}</b> {subject}" if interval else f"  🕘 {subject}")
        if event.educators:
            lines.append(f"     👤 {escape(event.educators)}")
        if event.locations:
            lines.append(f"     📍 {escape(event.locations)}")
    return "\n".join(lines)


def format_schedule(
    schedule: Schedule, t: Translator, header: str = "", footer: str = ""
) -> str:
    """Расписание целиком. Дни без занятий не печатаются, если их много."""
    parts: list[str] = []
    if header:
        parts.append(f"<b>{escape(header)}</b>")
    if schedule.group_name:
        parts.append(t("group_label", name=escape(schedule.group_name)))

    days_with_events = [day for day in schedule.days if day.events]
    days = schedule.days if len(schedule.days) <= 7 else days_with_events
    if not days_with_events:
        parts.append("\n" + t("no_classes"))
    else:
        parts.extend("\n" + format_day(day, t) for day in days)
    if footer:
        parts.append(f"\n<i>{escape(footer)}</i>")
    if schedule.url:
        link = escape(schedule.url, quote=True)
        parts.append(f'\n<a href="{link}">{t("open_on_site")}</a>')
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


def format_cohorts(student: Student, roster: Roster, t: Translator) -> str:
    """Список «предмет — когорта» для конкретного студента."""
    pairs = roster.describe(student, t.lang)
    if not pairs:
        return t("cohorts_empty")
    lines = [t("cohorts_title")]
    lines.extend(f"  · {escape(title)} — <b>{escape(value)}</b>" for title, value in pairs)
    return "\n".join(lines)


def format_subscription(
    subscription: Subscription, settings, roster: Roster, t: Translator
) -> str:
    """Карточка текущих настроек."""
    lines = [
        t("settings_title"),
        t("settings_program", program=escape(settings.program_title)),
        t("settings_language", language=t.language_name),
    ]

    student = roster.get(subscription.student_name) if subscription.student_name else None
    if student:
        lines.append(t("settings_student", name=escape(student.name)))
    elif subscription.student_name:
        lines.append(
            t("settings_student_missing", name=escape(subscription.student_name))
        )
    else:
        lines.append(t("settings_no_student"))

    if subscription.language_course:
        lines.append(
            t(
                "settings_course_language",
                course=escape(
                    choice_title(
                        subscription.language_course,
                        subscription.language_teacher,
                        t.lang,
                    )
                ),
            )
        )
    if student and not subscription.show_all and educator_value(student, roster):
        lines.append(
            t(
                "settings_subgroup",
                value=(
                    t("subgroup_label", number=subscription.subgroup)
                    if subscription.subgroup
                    else t("subgroup_any")
                ),
            )
        )
    if student:
        lines.append(
            t("settings_filter_all") if subscription.show_all else t("settings_filter_mine")
        )
    lines.append(
        t("settings_notify_on") if subscription.notify_changes else t("settings_notify_off")
    )
    lines.append(
        t("settings_frequency", frequency=frequency_title(subscription.frequency, t))
    )
    if subscription.frequency != OFF:
        lines.append(t("settings_time", time=subscription.send_time))
        if subscription.next_run_at:
            local = subscription.next_run_at.astimezone(settings.tz)
            lines.append(t("settings_next_run", moment=f"{local:%d.%m.%Y %H:%M}"))

    if student and not subscription.show_all:
        lines.append("\n" + format_cohorts(student, roster, t))
    return "\n".join(lines)


def _slot_when(slot: Slot, t: Translator) -> str:
    day = slot.day
    when = human_date(day, t) if day else slot.date
    return f"{when}, {slot.interval}" if slot.interval else when


def _slot_title(slot: Slot) -> str:
    title = escape(slot.subject)
    return f"{title} · {escape(slot.subgroup)}" if slot.subgroup else title


def _slot_line(slot: Slot, t: Translator) -> list[str]:
    lines = [f"  🕘 <b>{escape(slot.interval)}</b> {_slot_title(slot)}"]
    if slot.educators:
        lines.append(f"     👤 {escape(slot.educators)}")
    if slot.locations:
        lines.append(f"     📍 {escape(slot.locations)}")
    return lines


def format_changes(diff: Diff, t: Translator) -> str:
    """Сообщение о том, что изменилось в расписании."""
    parts = [t("changes_title")]

    for key, slots in (("changes_added", diff.added), ("changes_removed", diff.removed)):
        if not slots:
            continue
        parts.append(f"\n<b>{t(key)}</b>")
        current_day = None
        for slot in slots:
            if slot.date != current_day:
                current_day = slot.date
                day = slot.day
                parts.append(f"<i>{escape(human_date(day, t) if day else slot.date)}</i>")
            parts.extend(_slot_line(slot, t))

    if diff.moved:
        parts.append(f"\n<b>{t('changes_moved')}</b>")
        for old, new in diff.moved:
            parts.append(f"  {_slot_title(new)}")
            parts.append(f"     {t('changes_was', value=escape(_slot_when(old, t)))}")
            parts.append(f"     {t('changes_now', value=escape(_slot_when(new, t)))}")

    if diff.edited:
        parts.append(f"\n<b>{t('changes_edited')}</b>")
        for old, new, fields in diff.edited:
            parts.append(f"  {_slot_title(new)} · {escape(_slot_when(new, t))}")
            for field_name in fields:
                label = t(f"changes_field_{field_name}")
                was = escape(getattr(old, field_name)) or "—"
                now = escape(getattr(new, field_name)) or "—"
                parts.append(f"     {label}: {was} → {now}")

    parts.append(f"\n<i>{t('changes_hint')}</i>")
    return "\n".join(parts)


def format_notes(notes: list[Note], tz, t: Translator) -> str:
    if not notes:
        return t("notes_empty")
    lines = [t("notes_title")]
    for note in notes:
        when = note.due_at.astimezone(tz)
        lines.append(f"\n#{note.id} — {when:%d.%m.%Y %H:%M}\n{escape(note.text)}")
    lines.append("\n" + t("notes_delete_hint"))
    return "\n".join(lines)


def digest_header(frequency: str, start: date, end: date, t: Translator) -> str:
    if frequency == DAILY:
        return t("header_day", date=human_date(start, t))
    if frequency == WEEKLY:
        return t("header_week", start=f"{start:%d.%m}", end=f"{end:%d.%m}")
    if frequency == MONTHLY:
        return t(
            "header_month", month=t.months_standalone[start.month - 1], year=start.year
        )
    return t("header_range", start=f"{start:%d.%m}", end=f"{end:%d.%m}")


def format_note_reminder(note: Note, tz, t: Translator) -> str:
    when = note.due_at.astimezone(tz)
    return f"{t('note_reminder', date=f'{when:%d.%m.%Y}')}\n\n{escape(note.text)}"


def now_local(tz) -> datetime:
    """Текущее время в часовом поясе рассылки."""
    return datetime.now(timezone.utc).astimezone(tz)
