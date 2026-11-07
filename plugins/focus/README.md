# Offline focus and Pomodoro

This plugin uses a managed one-second timer, local JSON files and FRIDAY's existing
notification/mood API. It makes no network requests, launches no apps and requires
no extra packages. It does not inspect what you are doing during a timer.

## Commands

```text
focus
focus 25
start focus timer 25 minutes
pomodoro
pause focus
resume focus
stop focus
how long is left
focus stats today
focus stats this week
```

Bare `focus` uses the configured focus duration. Starting another timer while one
is running or paused returns a friendly refusal; it does not replace your work.
Pause applies to focus and break phases. Stop ends the whole Pomodoro sequence.

## Settings

Edit `settings.json` in the plugin's data directory. Defaults are filled on first
load; edits apply when starting the next timer/sequence:

```json
{
  "focus": {
    "focus_minutes": 25,
    "short_break_minutes": 5,
    "long_break_minutes": 15,
    "rounds": 4
  }
}
```

Minutes must be positive finite numbers up to 1440; fractional minutes are allowed.
Rounds must be an integer from 1 to 24. After each focus phase a short break starts,
except after the last round, when a long break starts. Finishing the long break
starts round one of the next cycle. A single focus timer has no automatic break.

At completion, the plugin publishes `focus.done`, sends a local notification and
requests `celebrating` for six seconds at priority 3. Timer completion notifications
use critical urgency so an explicitly requested timer can finish visibly during
a study scene's quiet mode. Pausing/stopping early does not celebrate.

## Persistence and counting

State and history share one atomically written file:
`%APPDATA%\FRIDAY\plugins\focus\focus.json`. The host also supports the configured
`FRIDAY_USER_DATA` root. Nothing is stored in the plugin source folder.

The active phase retains an absolute end timestamp, or its remaining seconds
while paused. Unloading/restarting does not stop the timer. If an end timestamp
passed while FRIDAY was closed, that phase completes once after loading. A
Pomodoro's next phase starts at recovery time; missed hours never fabricate
additional focus rounds. Completion, history and the next phase are committed
together before events/notification output, preventing duplicate history on retry.
Malformed saved state/settings are reported and preserved for repair.

History records include date, actual focused minutes, completion flag, planned
minutes, label, session ID and active time segments. Breaks and pauses do not count.
Stopped sessions count only the time actually spent, and active focus contributes
its elapsed time. Daily totals clip segments at local midnight; this week starts
Monday. Completion/stopped counts use their finish dates. Timer completion times
retain their scheduled date even if FRIDAY resumes much later.

## Service and events

```python
focus = api.get_service('focus')
if focus is not None:
    status = focus.status()
    minutes = focus.today_minutes()
```

`status()` returns `state` (`idle`, `running`, `paused`), `active`, `running`,
`remaining_s`, `session_id` and `owner`. Active phases also include `label`,
`minutes`, `end_at`, `phase` (`focus`, `short_break`, `long_break`), `round` and
`pomodoro`. Reads also complete an overdue phase. Protected read-only routes are
`GET /api/plugins/focus/status` and `/api/plugins/focus/stats?range=today` (or
`this%20week`); the existing bridge token is required.

Scenes can call `start(minutes, label='Focus', owner=scene_id)` and later
`stop(owner=scene_id)`. `start` returns the usual command-result dict and refuses
to replace an existing timer. An owner-specific stop leaves a timer owned by the
user or another scene alone. `pause()`, `resume()` and `stop()` return command
results too. `matches(text)` and `handle_command(text)` support local core routing.

`focus.started` includes `{minutes, label, session_id, duration_s, task, owner,
phase, round}`. Resume publishes it with `resumed: true`. `focus.paused` includes
the same identity plus `remaining_s`. `focus.done` adds `{completed, elapsed_s,
reason}`; `reason` is `completed` or `stopped`. The phase distinguishes breaks
from focused work. Existing event fields remain available to older consumers.

## Tests

From the FRIDAY repo root:

```powershell
venv/Scripts/python.exe -B -m pytest tests/test_focus_plugin.py -q
```

Tests fake the clock, notifications, moods and managed timer registration. They
use temporary files and perform no real desktop actions or network calls.
