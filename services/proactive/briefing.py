"""
services/proactive/briefing.py

The morning briefing, as one spoken-style paragraph:
    "Good morning. It's 24° and partly cloudy in Pune, with a high of 29°.
     You have 2 reminders today: call mom at 5:00 PM, … Battery is at 64% and
     charging. Yesterday you were active for 4h 10m: code 3h 10m, chrome 1h."

Each part is skipped when there's nothing to say or it can't be read (no
WEATHER_CITY, weather service down, no battery). Blocking — run it in a thread.
"""

from datetime import datetime, timedelta

import httpx
import psutil

from core.config import config
from core.logger import logger
from services.activity.log import NO_ACTIVITY, activity_log
from services.automation import system_stats
from services.memory import notes
from services.reminders.service import reminders

WEATHER_TIMEOUT_SECONDS = 5
RAIN_WORTH_MENTIONING = 30  # % chance
# WMO weather codes (Open-Meteo) → words
WEATHER_WORDS = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "foggy", 48: "foggy",
    51: "drizzling", 53: "drizzling", 55: "drizzling", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "raining", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snowing", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "rain showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}

_places: dict[str, tuple[float, float, str]] = {}  # city → (latitude, longitude, name), looked up once


def build(now: datetime | None = None, *, structured: bool | None = None) -> str:
    now = now or datetime.now()
    if structured is None:
        from services.automation.intent import remote_request
        structured = remote_request.get()
    if structured:
        from services.telegram.formatting import activity_lines, section
        parts = [("🌤️ Weather", weather()), ("📚 Classes", _classes_today(now, structured=True)),
                 ("📋 Attendance", _attendance(now)), ("⏰ Due soon", _deadlines(now, structured=True)),
                 ("🗓️ Exams", _exams(now)), ("⚠️ Needs attention", _risk(now)),
                 ("🔔 Reminders", _reminders_today(now, structured=True)), ("📝 Notes", notes.briefing_line()),
                 ("🔋 Laptop", _system(structured=True)), ("📊 Yesterday", activity_lines(_yesterday(now)))]
        sections = [section(title, body) for title, body in parts]
        return (f"☀️ FRIDAY — Daily briefing\n{now:%A, %d %B %Y}\n{_greeting(now)}\n\n"
                + "\n\n".join(part for part in sections if part))
    parts = [_greeting(now), weather(), _classes_today(now), _attendance(now), _deadlines(now), _exams(now), _college_events(now),
             _risk(now), _reminders_today(now), notes.briefing_line(), _system(), _yesterday(now)]
    return " ".join(part for part in parts if part)


def _risk(now: datetime) -> str:
    from services.activity import insights  # avoid an import cycle at startup

    try:  # "Heads up: DBMS assignment is due in 2 days with 10 min of DBMS in the last 3 days."
        return insights.deadline_risk_line(activity_log, now)
    except Exception as e:  # never break the briefing
        logger.warning(f"Deadline risk skipped: {e}")
        return ""


def _exams(now: datetime) -> str:
    from services.proactive import college  # avoid an import cycle at startup

    return college.exam_line(now)  # "Exams: DBMS CIE 2 in 9 days."


def _college_events(now: datetime) -> str:
    from services.automation.intent import remote_request
    from services.college.reading import events_message
    if remote_request.get():
        return ''
    try:
        return events_message(now, briefing=True)
    except (OSError, ValueError):
        logger.warning('College events unavailable for the local briefing')
        return ''


def _attendance(now: datetime) -> str:
    from services.proactive import attendance  # avoid an import cycle at startup

    return attendance.evening_line(now)  # only subjects close to / under 75%


def _greeting(now: datetime) -> str:
    return "Good morning." if now.hour < 12 else "Good afternoon." if now.hour < 17 else "Good evening."


def weather(city: str | None = None) -> str:
    city = config.WEATHER_CITY if city is None else city
    if not city:
        return ""
    try:
        with httpx.Client(timeout=WEATHER_TIMEOUT_SECONDS) as client:
            if city not in _places:
                found = client.get(
                    "https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1},
                ).json().get("results")
                if not found:
                    logger.warning(f"Weather: no place called {city!r}")
                    return ""
                _places[city] = (found[0]["latitude"], found[0]["longitude"], found[0]["name"])
            latitude, longitude, name = _places[city]
            data = client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": 1,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,precipitation_probability_max",
            }).json()
        now_temp, code = data["current"]["temperature_2m"], data["current"]["weather_code"]
        high, rain = data["daily"]["temperature_2m_max"][0], data["daily"]["precipitation_probability_max"][0]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        logger.warning(f"Weather unavailable: {e}")
        return ""
    text = f"It's {round(now_temp)}° and {WEATHER_WORDS.get(code, 'mixed weather')} in {name}, with a high of {round(high)}°"
    if rain is not None and rain >= RAIN_WORTH_MENTIONING:
        text += f" and a {rain}% chance of rain"
    return text + "."


def _deadlines(now: datetime, *, structured: bool = False) -> str:
    from services.proactive import deadlines  # avoid an import cycle at startup

    if structured:
        soon = sorted((d for d in deadlines.load() if datetime.fromisoformat(d["due"]) - now <= deadlines.SOON),
                      key=lambda d: d["due"])
        return "\n".join(f"{d['what']} — {deadlines.when(datetime.fromisoformat(d['due']), now)}"
                         + (" (overdue)" if datetime.fromisoformat(d['due']) < now else "") for d in soon)
    return deadlines.briefing_line(now)


def _classes_today(now: datetime, *, structured: bool = False) -> str:
    from services.proactive import timetable  # avoid an import cycle at startup

    try:
        if structured:
            if not timetable.load():
                return ""
            return "\n".join(timetable._describe(c, metadata=False) for c in timetable.classes_for_date(now.date())) or "No classes today."
        return timetable.today_line(now)
    except Exception as e:  # a broken timetable file mustn't break the briefing
        logger.warning(f"Timetable unavailable for the briefing: {e}")
        return ""


def _reminders_today(now: datetime, *, structured: bool = False) -> str:
    today = [r for r in reminders.pending() if datetime.fromtimestamp(r.due_at).date() == now.date()]
    if not today:
        return "No reminders today."
    if structured:
        return "\n".join(f"{datetime.fromtimestamp(r.due_at):%I:%M %p} — {r.text}"
                         for r in sorted(today, key=lambda r: r.due_at))
    listed = ", ".join(
        f"{r.text} at {datetime.fromtimestamp(r.due_at).strftime('%I:%M %p').lstrip('0')}" for r in today
    )
    return f"You have {len(today)} reminder{'s' if len(today) != 1 else ''} today: {listed}."


def _system(*, structured: bool = False) -> str:
    """Battery, plus memory or disk only when they need attention."""
    parts = []
    try:
        if psutil.sensors_battery() is not None:
            parts.append(system_stats.report("battery"))
        if psutil.virtual_memory().percent >= system_stats.HIGH_MEMORY:
            parts.append(system_stats.report("memory"))
        if psutil.disk_usage(system_stats.SYSTEM_DRIVE).free / system_stats.GB < system_stats.LOW_DISK_GB:
            parts.append(system_stats.report("disk"))
    except (OSError, RuntimeError) as e:
        logger.warning(f"Briefing couldn't read the system: {e}")
    return ("\n" if structured else " ").join(parts)


def _yesterday(now: datetime) -> str:
    summary = activity_log.day_summary(now - timedelta(days=1))
    return "" if summary == NO_ACTIVITY else summary
