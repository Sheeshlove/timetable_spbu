"""Отбор занятий по когорте студента."""

from datetime import date

import pytest

from bot.roster import load_roster
from bot.roster.filtering import belongs_to, filter_schedule
from bot.timetable.models import Day, Event, Schedule

roster = load_roster()
# Coh.2 / Coh.2 / лекции Coh.2 / семинары Coh.4 / RS 1 / CCM Coh.2 / MPS Shevchuk 2
ME = roster.get("Shishlov Egor")


def visible(subject: str, educators: str = "") -> bool:
    return belongs_to(Event(subject=subject, educators=educators), ME, roster)[0]


def test_fixture_student_has_expected_cohorts():
    assert ME.cohorts["corp_finance"] == "Coh.2"
    assert ME.cohorts["qmbr_seminars"] == "Coh.4"
    assert ME.cohorts["mps_1"] == "Shevchuk 2"


@pytest.mark.parametrize(
    "subject",
    [
        "Corporate Finance (Coh.2)",
        "Корпоративные финансы, когорта 2",
        "Organizational Behaviour Coh. 2",
        "QMBR lecture Coh.2",
        "QMBR seminar Coh.4",
        "Research Seminar I, группа 1",
        "Cross-Cultural Management (Coh.2)",
    ],
)
def test_my_cohort_is_shown(subject):
    assert visible(subject) is True


@pytest.mark.parametrize(
    "subject",
    [
        "Corporate Finance (Coh.1)",
        "Корпоративные финансы, когорта 1",
        "Organizational Behaviour Coh. 1",
        "QMBR lecture Coh.1",
        "QMBR seminar Coh.3",
        "Research Seminar I, группа 3",
        "Cross-Cultural Management (Coh.1)",
    ],
)
def test_foreign_cohort_is_hidden(subject):
    assert visible(subject) is False


@pytest.mark.parametrize(
    "subject",
    [
        "Corporate Finance",                 # метки когорты нет
        "Корпоративные финансы, ауд. 401",   # номер аудитории — не когорта
        "QMBR, ауд. 305",                    # непонятно, лекция или семинар
        "Физкультура",                       # предмета нет в таблице
        "Английский язык, группа 3",         # чужой предмет со своей нумерацией
    ],
)
def test_unclear_events_are_kept(subject):
    """Осторожность важнее краткости: пропущенная пара хуже лишней."""
    assert visible(subject) is True


def test_qmbr_without_type_uses_both_cohorts():
    assert visible("QMBR Coh.2") is True   # моя лекционная
    assert visible("QMBR Coh.4") is True   # мой семинар
    assert visible("QMBR Coh.1") is False  # ни то ни другое
    assert visible("QMBR Coh.3") is False


def test_educator_split_is_matched_across_alphabets():
    assert visible("MPS I", "Шевчук Дмитрий Александрович") is True
    assert visible("MPS I", "Замулин Андрей Леонидович") is False
    assert visible("MPS I", "Павловская Ольга") is False
    assert visible("MPS I", "Shevchuk D.") is True


def test_educator_group_number_is_checked():
    """«Подгруппа 1» на сайте = «Shevchuk 1» в ведомости — номера совпадают."""
    assert visible("MPS I, подгруппа 2", "Шевчук Дмитрий") is True
    assert visible("MPS I, подгруппа 1", "Шевчук Дмитрий") is False
    assert visible("MPS I, группа 2", "Шевчук Дмитрий") is True
    assert visible("MPS I, группа 1", "Шевчук Дмитрий") is False


def test_unknown_educator_keeps_event():
    assert visible("MPS I", "Неизвестный Преподаватель") is True
    assert visible("MPS I", "") is True


def test_student_without_number_in_educator_value():
    student = next(s for s in roster.students if s.cohorts["mps_1"] == "Pavlovskaya")
    assert belongs_to(Event(subject="MPS I", educators="Павловская О."), student, roster)[0]
    assert not belongs_to(Event(subject="MPS I", educators="Шевчук Д."), student, roster)[0]


def test_filter_schedule_counts_hidden():
    schedule = Schedule(
        group_id=1,
        group_name="MiM",
        days=[
            Day(
                date=date(2026, 9, 1),
                title="",
                events=[
                    Event(subject="Corporate Finance (Coh.1)", time_text="10:00–11:35"),
                    Event(subject="Corporate Finance (Coh.2)", time_text="12:00–13:35"),
                    Event(subject="Физкультура", time_text="14:00–15:35"),
                ],
            ),
            Day(date=date(2026, 9, 2), title="", events=[]),
        ],
    )
    filtered, report = filter_schedule(schedule, ME, roster)
    assert report.hidden == 1
    assert [event.subject for event in filtered.days[0].events] == [
        "Corporate Finance (Coh.2)",
        "Физкультура",
    ]
    assert len(filtered.days) == 2, "пустые дни остаются на месте"
    assert filtered.group_name == "MiM"


def test_every_student_keeps_own_lesson():
    """У каждого студента его собственная когорта не отфильтровывается."""
    for student in roster.students:
        cohort = student.cohorts["corp_finance"].replace("Coh.", "")
        event = Event(subject=f"Corporate Finance (Coh.{cohort})")
        assert belongs_to(event, student, roster)[0], student.name


# --- на настоящей странице сайта --------------------------------------


def real_week():
    from bot.timetable.scraper import parse_schedule_html
    from conftest import fixture

    return parse_schedule_html(fixture("week_page_ru.html"), 474489, 2026)


def test_real_page_subgroup_filtering():
    """Неделя с сайта: у Шишлова QMBR-семинар — подгруппа 4, MPS — Шевчук 2."""
    schedule = real_week()
    filtered, report = filter_schedule(schedule, ME, roster)

    kept = [event for day in filtered.days for event in day.events]
    qmbr = [e for e in kept if "Количественные методы" in e.subject]
    assert [e.subgroup for e in qmbr] == ["Подгруппа 4"]

    mps = [e for e in kept if "Профессиональные навыки" in e.subject]
    assert mps and all(e.subgroup == "Подгруппа 2" for e in mps)

    assert report.hidden == 3, "три чужих семинара QMBR"


def test_real_page_keeps_common_classes():
    schedule = real_week()
    filtered, _ = filter_schedule(schedule, ME, roster)
    kept = {event.subject for day in filtered.days for event in day.events}
    # Лекции без деления и факультативы остаются у всех
    assert "Современный стратегический анализ, лекция" in kept
    assert any("Иностранный язык" in subject for subject in kept)


def test_real_page_for_another_cohort():
    """Студент из подгруппы 1 видит свой семинар и не видит четвёртый."""
    student = next(s for s in roster.students if s.cohorts["qmbr_seminars"] == "Coh.1")
    filtered, _ = filter_schedule(real_week(), student, roster)
    qmbr = [
        event
        for day in filtered.days
        for event in day.events
        if "Количественные методы" in event.subject
    ]
    assert [event.subgroup for event in qmbr] == ["Подгруппа 1"]


def test_mps_educator_split_on_real_page():
    """У студента с MPS у Замулина субботние пары Шевчука скрыты."""
    student = next(s for s in roster.students if s.cohorts["mps_1"] == "Zamulin")
    filtered, _ = filter_schedule(real_week(), student, roster)
    mps = [
        event
        for day in filtered.days
        for event in day.events
        if "Профессиональные навыки" in event.subject
    ]
    assert mps == []
