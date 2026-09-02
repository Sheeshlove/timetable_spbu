"""Работа с сайтом расписания СПбГУ."""

from .client import TimetableClient, TimetableError
from .models import Day, Event, Schedule

__all__ = ["Day", "Event", "Schedule", "TimetableClient", "TimetableError"]
