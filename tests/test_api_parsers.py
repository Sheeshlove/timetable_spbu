"""Разбор ответов JSON-API."""

from datetime import date

from bot.timetable import api

LEVELS = [
    {
        "StudyLevelName": "Магистратура",
        "StudyProgramCombinations": [
            {
                "Name": "38.04.02 Менеджмент",
                "AdmissionYears": [
                    {"StudyProgramId": 12345, "YearName": "2026", "IsCurrent": True},
                    {"StudyProgramId": 12000, "YearName": "2025", "IsCurrent": False},
                ],
            }
        ],
    },
    {
        "StudyLevelName": "Бакалавриат",
        "StudyProgramCombinations": [
            {"Name": "38.03.02 Менеджмент", "AdmissionYears": [{"StudyProgramId": 999, "YearName": "2026"}]}
        ],
    },
]

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


def test_parse_divisions():
    divisions = api.parse_divisions(
        [{"Alias": "GSOM", "Name": "ВШМ", "Oid": "abc"}, {"Alias": "", "Name": "битая запись"}]
    )
    assert [d.alias for d in divisions] == ["GSOM"]
    assert divisions[0].name == "ВШМ"


def test_parse_programs_and_years():
    programs = api.parse_programs(LEVELS)
    assert [p.name for p in programs] == ["38.04.02 Менеджмент", "38.03.02 Менеджмент"]
    assert programs[0].level == "Магистратура"

    years = api.parse_admission_years(LEVELS, programs[0].key)
    assert [(y.name, y.program_id) for y in years] == [("2026", 12345), ("2025", 12000)]
    assert years[0].is_current is True

    # ключ второго направления не должен подтягивать годы первого
    other = api.parse_admission_years(LEVELS, programs[1].key)
    assert [y.program_id for y in other] == [999]


def test_parse_programs_ignores_unknown_shape():
    assert api.parse_programs({"unexpected": True}) == []
    assert api.parse_divisions(None) == []


def test_parse_groups_accepts_both_shapes():
    wrapped = api.parse_groups({"Groups": [{"StudentGroupId": 1, "StudentGroupName": "Гр. 1"}]})
    bare = api.parse_groups([{"StudentGroupId": 1, "StudentGroupName": "Гр. 1"}])
    assert wrapped == bare
    assert wrapped[0].group_id == 1


def test_parse_schedule():
    schedule = api.parse_schedule(EVENTS, 474489)
    assert schedule.group_name == "Менеджмент, 2026"
    assert len(schedule.days) == 2
    first = schedule.days[0]
    assert first.date == date(2026, 8, 31)
    assert first.events[0].subject == "Микроэкономика"
    assert first.events[0].interval == "10:00–11:35"
    assert schedule.days[1].events == []
    assert schedule.is_empty is False


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
