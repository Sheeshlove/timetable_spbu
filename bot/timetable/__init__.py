"""Работа с сайтом расписания СПбГУ."""

from .client import TimetableClient, TimetableError
from .models import AdmissionYear, Day, Division, Event, Program, Schedule, StudentGroup

__all__ = [
    "AdmissionYear",
    "Day",
    "Division",
    "Event",
    "Program",
    "Schedule",
    "StudentGroup",
    "TimetableClient",
    "TimetableError",
]
