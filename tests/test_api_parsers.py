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
