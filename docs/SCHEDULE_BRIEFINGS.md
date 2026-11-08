# Offline schedules and briefings

Restart FRIDAY once to load the command-routing changes, then use `list plugins`
and check that `schedule_alerts` and `briefings` are enabled. `reload plugins`
reloads their code and editable `plugins/briefings/lines.json`. Run the updated
Island (`cd island; npm.cmd run tauri -- dev`) to see expanded briefing cards.
No dependency or model download is needed.

Say `brief me`, `morning brief`, or `night brief`. A brief has a title and at most
six content lines; absent services contribute no section. Morning speech is on,
night speech is off. `skip` and `snooze 30` apply only to the brief shown in the
last ten minutes; its buttons carry a matching opaque card ID. A later request
invalidates earlier buttons. Explicit requests may repeat a daily brief.

Morning automation uses the first activity inside 05:00-11:00 (end exclusive),
or the first 30-second tick at/after 07:30 in that window. Without an activity
service, Windows last-input metadata supplies a first-input fallback; no titles,
keys or mouse positions are collected. Night automation runs at/after 22:30 or
when a sleep scene becomes active. Delivered dates and pending snoozes survive
restarts. A deferral across midnight keeps its original scheduled night.

Game/class scenes and fullscreen foreground apps defer every delivery by ten
minutes, including explicit requests. Unknown fullscreen state also defers.
Ordinary automatic briefs wait during quiet mode; an explicit brief, snooze or
sleep-scene response can be shown under quiet mode. Existing Sneak mode remains
in control of island visibility. The night card offers Yes/Not now for sleep
when scenes exists and sleep is not already active. Yes calls `scenes.request`;
the scene's preview/confirmation policy still applies. Local scene speech uses
`briefings.tomorrow_summary()`; it never requests weather.

## Read-only sources and assumptions

The adapter reuses the confirmed College Schedules stores and pure readers:

| Source | Used for |
| --- | --- |
| `memory/timetable.json` / `timetable.load()` | Confirmed weekly slots, including upload/update results |
| `memory/class-sessions.json` / effective dated projection | Rescheduled individual classes |
| `memory/college/subjects.json` / `catalogs.subject_for()` | Faculty and room; metadata room overrides template room |
| `memory/deadlines.json` / `work.snapshot()` | Assignments, exam dates, pending homework; completed rows excluded |
| `memory/attendance.json` | Recorded holidays |
| `memory/college/events.json` | Optional `upcoming_events()` projection |
| Existing owner memory and cognition databases | Dated cancellations/resumptions and fingerprint-verified applied class constraints |

The normal timetable reader can initialize reasoning tables. The adapter supplies
a read-only projection instead: existing SQLite files open with `mode=ro` and
`query_only`, matching the normal authority's evidence window. Missing databases
are never initialized. An unsupported applied constraint makes classes unavailable
with one log message; uncertain classes are never announced. A broken faculty
catalog leaves otherwise valid classes/deadlines available with blank faculty.
Original uploads and reminder/attendance/deadline state are never edited.

Academic times are local civil datetimes, matching College Schedules. Missing
faculty stays blank. Existing exam-word recognition is reused; legacy items
whose kind is `other` and whose title says homework/assignment get that kind.
Briefs still work with no schedule data, as required by the no-data tests;
schedule alerts stay quiet and log missing data once. Old todos without completion
dates are not assigned a day. New completion timestamps and daily totals permit
night counts even after clearing finished todos. Focus adds `stats('yesterday')`.

`schedule` offers `next_classes(n)`, `classes_on(date)`, `due_items(within_days)`,
`upcoming_exams(within_days)` and `pending_homework()`. Frozen `ScheduleItem`
dataclasses include ID/title, subject, faculty, room, start/end, due_at and kind.
`briefings.build(kind)` returns text without claiming delivery;
`briefings.tomorrow_summary()` returns tomorrow's recorded classes/due items.

## Settings

Plugin settings live under `%APPDATA%\FRIDAY\plugins\<id>\settings.json` and are
read on each tick/request. These are flat keys in the relevant plugin's file:

```json
{
  "schedule_alerts.class_minutes": [15, 5],
  "schedule_alerts.assignment_hours": [24, 3],
  "schedule_alerts.exam_days": [3, 1]
}
```

```json
{
  "briefings.enabled": true,
  "briefings.morning_start": "05:00",
  "briefings.morning_end": "11:00",
  "briefings.morning_fallback": "07:30",
  "briefings.night_time": "22:30",
  "briefings.speak": {"morning": true, "night": false},
  "user_name": "",
  "honorific": "",
  "briefings.weather": false,
  "briefings.latitude": null,
  "briefings.longitude": null
}
```

`briefings.speak` also accepts one boolean for both kinds. Weather requires an
explicit true and valid numeric coordinates. It makes one HTTPS request to
[Open-Meteo's forecast API](https://open-meteo.com/en/docs), with a three-second
timeout, no redirects/proxy/geocoding, and silently omits failures. It sends only
coordinates and forecast parameters; the remaining feature works offline.

Alerts poll every 30 seconds, so delivery is within one tick after a threshold.
Claims are saved in `schedule_alerts/alerts.json` before publication: an abrupt
crash between saving and sending may lose that alert, but cannot repeat it.
On late startup only the nearest crossed lead is sent; older leads are consumed.
The event reports actual time left separately from the configured lead.
Changed due/start times form new occurrences; display-only faculty/room edits do
not re-alert. The installed plugins replace legacy automatic/explicit briefings
and class/deadline alerts, avoiding duplicates and old weather calls.

## Validation

From the repo, use a fresh external test directory:

```powershell
$briefTemp = Join-Path $env:TEMP ('friday-brief-' + [guid]::NewGuid().ToString('N'))
venv/Scripts/python.exe -B -m pytest tests/test_schedule_adapter.py tests/test_schedule_alerts.py tests/test_briefings.py tests/test_briefing_routing.py -q -p no:cacheprovider --basetemp $briefTemp
venv/Scripts/python.exe -B tests/schedule_briefings_preview.py
cd island
npm.cmd test
npm.cmd run build
```

For the isolated Chromium ordering/action check, leave `npm.cmd run dev` running
in `island`, then from the repository run:

```powershell
venv/Scripts/python.exe -B tests/island/check_briefings_browser.py
```

This check uses synthetic schedule text, fake native calls and an authenticated
SSE fixture in Chromium; it does not operate the real Tauri window or owner data.

The real-data preview never shows cards, speaks or requests weather; it compares
academic source/database hashes and saves private results in ignored
`tasks/schedule-briefings/real-preview.json`. On 2026-11-07 it verified 22 weekly
slots, no classes that Saturday, and no pending deadlines in seven days. A next
class day preview used the real five-class Monday timetable. Source hashes matched.
The focused regression tests simulate both class lead times and a restart without
editing real calendar records. UI checks are in
[BRIEFINGS_CHECKLIST.md](../tests/island/BRIEFINGS_CHECKLIST.md).

## Files in this change

Added:

- `services/schedule_adapter.py`, `services/schedule_facts_readonly.py`,
  `services/briefing_context.py`, `services/briefing_runtime.py`.
- `plugins/schedule_alerts/main.py`, `plugins/schedule_alerts/plugin.json`.
- `plugins/briefings/main.py`, `plugins/briefings/delivery.py`,
  `plugins/briefings/content.py`, `plugins/briefings/weather.py`,
  `plugins/briefings/lines.json`, `plugins/briefings/plugin.json`.
- `tests/briefing_fakes.py`, `tests/test_schedule_adapter.py`,
  `tests/test_schedule_alerts.py`, `tests/test_briefings.py`,
  `tests/test_briefing_routing.py`, `tests/schedule_briefings_preview.py`,
  `tests/island/check_briefings_browser.py`, `tests/island/BRIEFINGS_CHECKLIST.md`.
- This guide and `docs/specs/2026-11-07-schedule-briefings.md`.

Changed:

- `services/proactive/timetable.py`, `services/proactive/watcher.py`,
  `services/plugin_runtime.py`, `services/automation/intent.py`.
- `interfaces/api/routes/chat.py`, `interfaces/api/routes/voice.py`.
- `plugins/focus/main.py`, `plugins/focus/timer.py`, `plugins/todo/main.py`.
- `island/src/main.ts`, `island/src/friday.ts`, `island/src/friday.css`,
  `island/src/plugin-card.ts`, `island/tests/plugin-card.test.ts`.
- `tests/conftest.py`, `tests/test_focus_plugin.py`, `docs/PLUGINS.md`,
  `docs/EVENTS.md`.

Private preview/screenshot/receipt artifacts stay under ignored
`tasks/schedule-briefings/`. Existing Mochi/scene work is preserved.
