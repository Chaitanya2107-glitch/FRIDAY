# Local Windows activity

This plugin polls foreground **metadata** every two seconds, offline. No network,
screenshots, clipboard reads, key hooks, browser-history scans, file-content
inspection or AI/model calls are used. A window title is read briefly only to
detect private windows and match an explicitly configured site label. It is
discarded at the provider boundary and never stored, logged, returned or published.

## Try it

After installation, ask FRIDAY:

```text
what am I doing
activity summary
what did I do today
how much time did I spend on YouTube today
how much time have I spent in coding this week
how long was I on Chrome yesterday
how long have I been in games the last seven days
categorise Spotify as entertainment
pause tracking
resume tracking
delete my activity data
confirm delete my activity data
```

Deletion requires the explicit confirmation phrase within 30 seconds. Plain
"yes" does not confirm, so another feature's confirmation cannot erase history.
Deletion clears the session database, current pending session and activity-source
debug events/undelivered bus events. Subscribers may already hold their own local
copies; the bus cannot recall already-delivered data. Settings/maps are retained.

Session data is `%APPDATA%\FRIDAY\plugins\activity\activity.sqlite3`, under the
host's user-data directory. `FRIDAY_USER_DATA` can select another user-data root
outside the repository. The plugin rejects database paths inside the repository.
The only database columns are `start`, `end`, `process`, `app_name`, `category`.
There is no title, URL, arbitrary text/payload, screenshot or clipboard column.
Private sessions have null process and app names. SQLite secure-delete and VACUUM
are used when clearing history; nothing is migrated into the legacy database.

## Settings

Edit the `activity` object in the plugin's `settings.json` in that same data
directory (or use `api.settings.get/set('activity', ...)`). Defaults are filled
in on first load:

```json
{
  "activity": {
    "poll_seconds": 2,
    "idle_seconds": 120,
    "site_labels": true,
    "retention_days": 90,
    "paused": false,
    "pause_in_private_scene": true,
    "excluded_processes": ["1password.exe", "bitwarden.exe", "keepass.exe", "keepassxc.exe", "banking.exe"],
    "excluded_title_fragments": ["InPrivate", "Incognito", "Private Browsing", "Online Banking", "Internet Banking"],
    "nudge_rules": {"entertainment": 120, "games": 120},
    "nudge_cooldown_minutes": 60,
    "category_overrides": {}
  }
}
```

The actual first-run exclusion lists also cover other common vault/banking
processes and banking-title markers. The three mandatory private-browser markers
remain excluded even if removed from settings. Settings are checked on each poll;
poll intervals can range from 0.25 to 3600 seconds. `paused` is independent of the
private-scene pause, so ending a scene never overrides a manual pause.

`activity.maps` caches the last valid user-edited maps. `activity.runtime` retains
scene/threshold policy and nudge cooldown across hot reloads in the same process;
it is ignored after FRIDAY restarts. These contain configuration, not raw window
observations. Retention runs on load and hourly. Rows crossing the cutoff are
clipped; intervals below three seconds are discarded.

Edit `categories.json` to map executable names or canonical site labels to
`study`, `coding`, `entertainment`, `social`, `games`, `communication`, `system`,
or `other`; `names` supplies friendly executable labels. Unknown apps are `other`.
The `categorise` command saves an override in settings instead of modifying source.

Edit `sites.json` to change browser executables and site-label title hints.
Labels such as `YouTube`/`Gmail` are hints from the title, not verified URLs or
proof of user intent. Full raw titles never leave the native provider. Setting
`site_labels` to false records only the browser executable/friendly name, while
private-title exclusion continues to work. Source JSON edits use normal plugin
hot reload. Malformed maps retain the last valid cached configuration.

## Counting rules

- Consecutive samples with the same process, friendly/site label and category
  form one session. A brief focus switch is ignored below three seconds.
- Once inactivity reaches 120 seconds, the recorded tail back to the last input
  is removed. That initial waiting period is provisional, not permanently counted.
  Lock screen/no foreground is idle immediately. Sleep/suspend gaps and wall-clock
  jumps are not credited to an app.
- Active time includes anonymous `private` time; idle and paused time are excluded.
  Private time appears separately and never appears in the app-name ranking.
- Today/yesterday use local midnight; this week starts Monday. Last seven days
  means a rolling seven-day window. Cross-midnight sessions are clipped to each
  query's boundaries rather than double-counted.
- Longest focus stretch means adjacent recorded coding/study sessions, ending on
  idle, private time or another category. This measures observed app categories,
  not proof of concentration or task completion.

## Service and Island route

```python
activity = api.get_service('activity')
if activity is not None:
    current = activity.current()
    time = activity.time_on('YouTube', range='today')
    summary = activity.summary(range='this week')
    fullscreen = activity.is_fullscreen()
    activity.set_threshold_override('entertainment', 10, owner='study-scene-id')
    activity.clear_overrides(owner='study-scene-id')
```

`current()` returns state (`active`, `idle`, `private`, `paused`), sanitized
`process`, `app_name`, `category`, `since` and `seconds`. `time_on()` accepts an
executable name with/without `.exe`, friendly/site label, or category and returns
`{name, range, seconds}`. `summary()` returns range, active/private seconds, top
five apps, category totals, and longest focus seconds. Fullscreen compares the
foreground rectangle with its own monitor, excluding desktop/taskbar/minimized
windows, with temporary per-thread DPI awareness. Paused/idle state returns false.

GET `/api/plugins/activity/summary?range=today` returns the same summary using
the existing `X-Friday-Token` bridge protection. Invalid ranges return a friendly
`invalid_range` result. No new route capability was needed.

Scene events use the contracts in `docs/EVENTS.md`. One ordered `scene.*`
subscription handles start/end. A `private` scene pauses tracking by default.
A `game` scene suppresses nudges; no scenes plugin is required. The strictest
threshold among configured rules and owners wins. Ended scene IDs clear that
owner's overrides. Continuous entertainment/games nudges occur at the threshold,
then at most once per cooldown, never while idle, paused, private or in game mode.
Notifications use the existing local transport with phone mirroring disabled.
Their text is generic; app names, categories and durations are not copied into
the core notification log or speech pipeline.

## Core privacy handoff

The existing bridge/manager API was sufficient. Small core adapters are needed
because legacy brain/screen/activity commands otherwise intercept these phrases
and can store responses or use online speech:

- `services/activity_plugin.py`: private activity dispatch, remote refusal and
  fail-closed installation detection.
- Chat/voice routes and `services/automation/intent.py`: intercept activity before
  file/web/model context and keep nested/routine results private and local speech.
  `show recent events` is also private while activity is installed, because its
  debug output can contain canonical app labels.
- `services/activity/log.py`: stop the old title/history sampler while this plugin
  is installed, even on disable/failure, and stop legacy title-helper reads.
- `services/event_bus.py`: forget one plugin's recent/queued events on deletion.

Those Python adapters need one backend restart on the initial upgrade. Later
plugin changes hot reload normally. Installing this plugin does not erase
previously collected legacy history or change other features' explicit network
permissions. Removing the plugin and restarting restores the legacy tracker.

## Tests and CPU verification

```powershell
venv/Scripts/python.exe -B -m pytest tests/test_activity_plugin.py tests/test_activity_native.py tests/test_activity_privacy.py tests/test_activity_lifecycle.py
venv/Scripts/python.exe -B tasks/activity-plugin/measure_cpu.py
```

Pytest uses fake foreground providers, clocks, and Win32 functions only. The
separate CPU probe performs read-only real Windows sampling, uses temporary
storage outside the repo, reports only aggregate CPU/idle counts and schema,
and makes no network requests or desktop actions. CPU is measured as process CPU
time divided by wall time, in one-core percent; it is not the misleading first
`psutil.cpu_percent(None)` sample. The full FRIDAY process also runs other features,
so its total CPU is not attributed to this plugin.

The probe also measures real Windows idle sampling with a one-second threshold
in its temporary profile, so it can exercise idle without requiring two minutes
of inactivity. Your normal 120-second threshold and stored settings are untouched.
