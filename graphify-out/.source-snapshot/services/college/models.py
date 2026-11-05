"""Authoritative college input validation; all clocks are local, 24-hour time."""
from datetime import date, datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def clock(value: str, optional=False) -> str:
    if optional and not value:
        return value
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Use a 24-hour time, HH:MM.')
    return value


def local_due(value: str) -> str:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', value):
        raise ValueError('Use a local date and time: YYYY-MM-DDTHH:MM.')
    datetime.fromisoformat(value)
    return value


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)

    @field_validator('*', mode='after')
    @classmethod
    def printable(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 and c not in '\n\t' for c in value):
            raise ValueError('Remove control characters.')
        return value


class Subject(Strict):
    subject: str = Field(min_length=1, max_length=120)
    faculty: str = Field(default='', max_length=160)
    room: str = Field(default='', max_length=120)
    email: str = Field(default='', max_length=200)
    notes: str = Field(default='', max_length=3000)

    @field_validator('email')
    @classmethod
    def email_format(cls, value):
        if value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Use an email address or leave it blank.')
        return value


class Slot(Strict):
    day: Literal['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    start: str
    end: str
    subject: str = Field(min_length=1, max_length=120)
    room: str | None = Field(default=None, max_length=120)

    @model_validator(mode='after')
    def times(self):
        clock(self.start)
        clock(self.end)
        if self.end <= self.start:
            raise ValueError('Class end must be after start on the same day.')
        return self


Kind = Literal['assignment', 'homework', 'exam', 'project', 'other']


class Deadline(Strict):
    what: str = Field(min_length=1, max_length=200)
    due: str
    kind: Kind = 'assignment'
    subject: str = Field(default='', max_length=120)
    done: bool = False
    notes: str = Field(default='', max_length=3000)
    venue: str = Field(default='', max_length=200)

    @field_validator('due')
    @classmethod
    def due_format(cls, value):
        return local_due(value)


class Exam(Strict):
    subject: str = Field(min_length=1, max_length=120)
    date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    time: str = '09:00'
    venue: str = Field(default='', max_length=200)
    notes: str = Field(default='', max_length=3000)
    done: bool = False

    @model_validator(mode='after')
    def times(self):
        date.fromisoformat(self.date)
        clock(self.time)
        return self


class Event(Strict):
    title: str = Field(min_length=1, max_length=200)
    date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    start: str = '09:00'
    end: str = ''
    location: str = Field(default='', max_length=200)
    notes: str = Field(default='', max_length=3000)

    @model_validator(mode='after')
    def times(self):
        date.fromisoformat(self.date)
        clock(self.start)
        clock(self.end, optional=True)
        if self.end and self.end <= self.start:
            raise ValueError('Event end must be after start on the same date.')
        return self


class Edit(Strict):
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    id: str | None = Field(default=None, min_length=1, max_length=160)
    value: dict


class Delete(Strict):
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    id: str = Field(min_length=1, max_length=160)


class DatedMove(Strict):
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    id: str = Field(min_length=1, max_length=160)
    date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    start: str

    @model_validator(mode='after')
    def times(self):
        date.fromisoformat(self.date)
        clock(self.start)
        return self


class ImportEdit(Strict):
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    rows: list[dict] = Field(min_length=1, max_length=300)
    mode: Literal['merge', 'replace'] = 'merge'


class Consent(Strict):
    consent: str = Field(pattern=r'^[a-f0-9]{64}$')
    section: str = Field(default='', max_length=40, pattern=r'^[\w -]*$')


class Confirm(ImportEdit):
    review: str = Field(pattern=r'^[a-f0-9]{64}$')
