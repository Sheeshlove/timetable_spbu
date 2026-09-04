"""Разбор расписания из JSON-API."""

from datetime import date

from bot.timetable import api

EVENTS = {
    "StudentGroupId": 474489,
    "StudentGroupDisplayName": "Менеджмент, 2026",
    "TimeTableUrl": "https://timetable.spbu.ru/GSOM/StudentGroupEvents/Primary/474489",
    "Days": [
        {
            "Day": "2026-08-31T00:00:00",
            "DayString": "31 августа 2026",
            "DayStudyEvents": [
                {
                    "Start": "2026-08-31T10:00:00",
                    "End": "2026-08-31T11:35:00",
                    "Subject": "Микроэкономика",
                    "TimeIntervalString": "10:00–11:35",
                    "EducatorsDisplayText": "Иванов И. И.",
                    "LocationsDisplayText": "Волховский пер., 3",
                    "IsCanceled": False,
                }
            ],
        },
        {"Day": "2026-09-01T00:00:00", "DayString": "1 сентября 2026", "DayStudyEvents": []},
    ],
}


def test_parse_schedule():
    schedule = api.parse_schedule(EVENTS, 474489)
    assert schedule.group_name == "Менеджмент, 2026"
    assert len(schedule.days) == 2
    first = schedule.days[0]
    assert first.date == date(2026, 8, 31)
    assert first.events[0].subject == "Микроэкономика"
    assert first.events[0].interval == "10:00–11:35"
    assert first.events[0].educators == "Иванов И. И."
    assert schedule.days[1].events == []
    assert schedule.is_empty is False


def test_parse_schedule_ignores_unknown_shape():
    assert api.parse_schedule({"unexpected": True}, 1).days == []
    assert api.parse_schedule(None, 1).days == []


def test_event_without_subject_is_skipped():
    schedule = api.parse_schedule(
        {"Days": [{"Day": "2026-08-31T00:00:00", "DayStudyEvents": [{"Subject": ""}]}]}, 1
    )
    assert schedule.days[0].events == []


def test_event_interval_falls_back_to_start_end():
    schedule = api.parse_schedule(
        {
            "Days": [
                {
                    "Day": "2026-08-31T00:00:00",
                    "DayStudyEvents": [
                        {
                            "Subject": "Тест",
                            "Start": "2026-08-31T09:30:00",
                            "End": "2026-08-31T11:00:00",
                        }
                    ],
                }
            ]
        },
        1,
    )
    assert schedule.days[0].events[0].interval == "09:30–11:00"


def test_merge_schedules_dedupes_days():
    first = api.parse_schedule(EVENTS, 474489)
    merged = api.merge_schedules([first, first])
    assert len(merged.days) == 2
    assert [day.date for day in merged.days] == [date(2026, 8, 31), date(2026, 9, 1)]


# --- Подгруппа ---------------------------------------------------------
#
# Без метки подгруппы фильтр по когортам не работает вовсе: студент второй
# подгруппы видит пары первой. В HTML метка есть, а в JSON-API её раньше не
# читали — из-за этого бот в бою не различал Shevchuk 1 и Shevchuk 2.


def one_event(**fields) -> dict:
    payload = {
        "Days": [
            {
                "Day": "2026-09-19T00:00:00",
                "DayStudyEvents": [
                    {
                        "Subject": "Профессиональные навыки менеджера I, практическое занятие",
                        "TimeIntervalString": "10:00–11:30",
                        "EducatorsDisplayText": "Шевчук Е. В.",
                        **fields,
                    }
                ],
            }
        ]
    }
    return api.parse_schedule(payload, 474489).days[0].events[0]


def test_subgroup_from_contingent_units():
    event = one_event(ContingentUnitsDisplayTest="26.М01-вшм (Подгруппа 2)")
    assert event.subgroup == "Подгруппа 2"


def test_subgroup_from_nested_lists():
    event = one_event(ContingentUnitNames=[["26.М01-вшм", "Подгруппа 1"]])
    assert event.subgroup == "Подгруппа 1"


def test_subgroup_from_english_api():
    event = one_event(ContingentUnitName="26.М01-вшм (Subgroup 4)")
    assert event.subgroup == "Subgroup 4"


def test_subgroup_is_found_in_an_unexpected_field():
    """Имена полей у эндпоинтов разные — метку ищем по всей записи."""
    event = one_event(SomeNewFieldName="Подгруппа 3")
    assert event.subgroup == "Подгруппа 3"


def test_event_without_subgroup_stays_empty():
    event = one_event(LocationsDisplayText="Волховский переулок, д. 3, лит. А,105")
    assert event.subgroup == "", "номер аудитории — не подгруппа"


def test_lecture_for_the_whole_stream_has_no_subgroup():
    event = one_event(
        Subject="Современный стратегический анализ, лекция",
        ContingentUnitsDisplayTest="26.М01-вшм",
    )
    assert event.subgroup == ""


def test_api_schedule_is_filtered_by_subgroup():
    """Сквозная проверка: занятие из API доходит до фильтра с меткой."""
    from bot.roster import load_roster
    from bot.roster.filtering import belongs_to

    roster = load_roster()
    me = roster.get("Shishlov Egor")  # MPS I: Shevchuk 2
    assert me.cohorts["mps_1"] == "Shevchuk 2"

    mine = one_event(ContingentUnitsDisplayTest="26.М01-вшм (Подгруппа 2)")
    other = one_event(ContingentUnitsDisplayTest="26.М01-вшм (Подгруппа 1)")
    assert belongs_to(mine, me, roster)[0] is True
    assert belongs_to(other, me, roster)[0] is False
