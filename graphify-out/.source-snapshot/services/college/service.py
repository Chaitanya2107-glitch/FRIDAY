"""Catalog dispatch shared by the college API; no interface dependencies."""
from services.college import catalogs, overview, schedules, work


def snapshot(section, day=None):
    if section == 'timetable':
        return schedules.snapshot(day)
    if section == 'subjects':
        return catalogs.subjects()
    if section == 'events':
        return catalogs.events()
    return work.snapshot(section)


def change(section, identifier, value, revision):
    if section == 'timetable':
        return schedules.change(identifier, value, revision)
    if section == 'subjects':
        return catalogs.change_subject(identifier, value, revision)
    if section == 'events':
        return catalogs.change_event(identifier, value, revision)
    return work.change(identifier, value, revision, section)
