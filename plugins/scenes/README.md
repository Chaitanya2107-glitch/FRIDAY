# Offline scenes

Scenes are editable local routines with an explicit preview and reverse undo.
They use the existing app aliases, local Windows APIs, offline speech and the
authenticated island bridge. There is no shell action, arbitrary program command
line, PC shutdown/restart/sleep/sign-out action, or file-deletion action.

## Try it

```text
list scenes
preview study mode
study mode
yes
what scene is active
end scene
exam mode
game mode
sleep mode
class mode
add Chrome to study distractions
remove Chrome from study distractions
create scene reading
```

The first start and every edited version shows the entire preview and asks Yes/No.
The island has real buttons; text `yes`/`no` also works. Buttons carry an opaque
token and cannot approve a changed file, a different question or an expired
confirmation. Questions expire after two minutes. A new unrelated local command
cancels an old scene question. Remote messages cannot approve/cancel local scenes.
Old core confirmations are cleared before a new scene question is offered.

Closing apps asks every time, even after first-run approval. Only an explicit
`"close_without_asking": true` opts out. Distraction lists ship empty. Their named
apps become close actions before the other actions; no process wildcards or
installation-folder-wide close is used. Windows receives **WM_CLOSE only**, so
unsaved-work prompts remain visible. An app still open after two seconds is
reported, including blocked or unidentified windows. No force-kill is attempted.

`create scene reading` copies study, changes its name/alias, saves a new JSON file
and opens it in the default editor. It refuses an existing name. Legacy routines,
mode files, notes and their history are not migrated or removed.

## Files and defaults

Defaults are copied **once** to `%APPDATA%\FRIDAY\plugins\scenes\scenes\`.
Edit those copies, not the shipped files. New/edited JSON is read on command and
every five seconds; malformed or unknown/forbidden actions refuse that scene with
a clear reason. Removing a default is respected after restart. The ordinary host
`FRIDAY_USER_DATA` override also works. Settings and undo state stay outside the repo.

```json
{
  "name": "reading",
  "aliases": ["reading mode", "library time"],
  "description": "Quiet reading with a 25 minute timer.",
  "restore": true,
  "confirm_first_run": true,
  "close_without_asking": false,
  "distractions": [],
  "duration_minutes": 30,
  "triggers": [],
  "actions": [
    {"type": "quiet_mode", "on": true},
    {"type": "set_volume", "percent": 30},
    {"type": "start_focus", "minutes": 25},
    {"type": "set_mood", "mood": "focused"}
  ]
}
```

`restore` and `confirm_first_run` default true. `duration_minutes` is optional:
without it the scene stays active until ended/replaced; a focus timer finishing
does not end the scene. Starting another scene first restores the old one, after
the new scene's required confirmation. Failed restoration keeps its journal and
blocks replacement; say `end scene` to retry. The active scene appears as a small
island chip and is recovered from the protected status route on reconnect.

Scenes support up to 64 actions plus 32 distractions; the complete preview must
fit the island's 4,000-character card. Oversized previews are refused, not truncated.
Aliases use FRIDAY's normal wake-word/politeness normalization and whole-string
matching. Reserved confirmation/end phrases cannot become aliases.

| Default | Behavior |
| --- | --- |
| study | Quiet, volume 30%, focus 25, entertainment limit 10 minutes, focused mood, optional music. |
| exam | Quiet, volume 20%, focus 50, entertainment limit 5 minutes, focused mood, optional music, good-luck speech. |
| game | High-performance power plan, quiet, happy mood. Activity suppresses game-scene nudges. |
| sleep | Built-in brightness 20%, volume 15%, quiet, sleepy mood, optional tomorrow briefing. The PC stays awake. |
| class | Quiet, mute, open the existing College Schedules UI. |

For optional study/exam music set `"study_music"` in this plugin's `settings.json`
to a local playlist path, URL, `music` (resume/open the existing player), or a
Spotify search phrase. Blank/unset skips music. Local media-session helpers are
reused; Spotify's HTTP API is never called. Named Spotify searches open the local
client and require you to select playback. URLs hand off to the browser/player;
uncached online content cannot play without connectivity.

Sleep looks up the optional **offline** `briefings` service and calls its
synchronous `tomorrow_summary() -> str | {text: str}`. Absence/empty output skips
that action. It never falls back to the legacy weather/network briefing builder.

## Actions and restoration

| Type | Parameters | Undo |
| --- | --- | --- |
| open_app | `name` | Uses FRIDAY aliases; launches/navigation are kept on exit. |
| close_app | `name` | WM_CLOSE only; cannot restore closed documents/unsaved state. |
| minimize_app | `name` | Restores saved window placement only if HWND, PID and process creation time still match. |
| set_volume | integer `percent` 0–100 | Exact raw Core Audio scalar, mute flag and device identity. |
| mute | boolean `on` | Restores exact audio state. |
| set_brightness | integer `percent` 0–100 | Restores each supported built-in WMI display and verifies readback. |
| set_power_plan | `balanced`, `high_performance`, `power_saver` in `plan` | Saves/restores the exact previous GUID using fixed `powercfg` argument lists. |
| quiet_mode | boolean `on` | Releases its own quiet owner; other owners are preserved. |
| start_focus | positive `minutes` | Stops only the scene-owned timer. An existing user timer is kept. |
| set_activity_threshold | `category`, positive `minutes` | Clears this scene's overrides. Missing activity skips cleanly. |
| set_mood | named `mood` | Temporary priority-2 scene mood; completion celebrations have priority 3. |
| say | `text` | Offline speech; no automatic undo. `{tomorrow_summary}` is the optional briefing marker. |
| open_url | `url` | HTTP/HTTPS only, without credentials; no executable protocols. |
| open_path | absolute local `path` | Folders/passive documents/media only; executable/script/shortcut targets and UNC/traversal are refused, including resolved link targets. |
| play_music | `playlist_or_url` | Existing local media/client; playback/navigation is kept on exit. |
| run_command | `text` | Finite permitted native actions are reversed; explicitly opted-in plugin commands have no generic undo. |

Audio/brightness support is optional. Missing pycaw, unsupported WMI displays,
unavailable power plans and missing services produce warnings and let other actions
continue. Restoration failures retain undo state instead of claiming success.
Ordinary action failures abort and reverse the completed/prepared actions.

Quiet mode suppresses FRIDAY's noncritical desktop notifications and cards across
both backend and tray processes. Due reminders defer before Windows/phone/model
delivery. Unsolicited speech also respects quiet state. Critical timer completion
and explicit confirmation/recovery cards bypass it; optional trigger suggestions
do not. Windows-wide Do Not Disturb/Focus Assist is not changed.

## Crash safety

`scene-state.json` holds the active scene and undo journal. Built-in reversible
actions checkpoint previous settings **before** applying and checkpoint returned
tokens immediately afterward. Undo runs in reverse order and commits progress after
each action, so another crash can retry idempotent restoration. App launches,
closed documents, speech and arbitrary plugin commands have no general reversal.

On a new backend process, leftover state offers: **Restore your settings from the
previous scene?** Yes reverses settings; No keeps them and releases scene-only
quiet/activity policy. The critical card is also returned by `GET /api/plugins/scenes/status`
so startup/reconnect cannot lose the question. Bad recovery data is preserved and
reported rather than guessed. Hot reload in the same process retains an active
scene; an interrupted apply/undo still offers recovery. End a scene before
disabling/removing its plugin so its restoration service remains available.

`scene.started`/`scene.ended` include name, owner ID and lifecycle fields from
`docs/EVENTS.md`. A `scene.state` snapshot every five seconds repairs activity
owners missed during reload; only this plugin's `scenes:` owners are reconciled.
An activity restart/reload therefore cannot leave an ended game/private scene or
entertainment threshold stuck indefinitely.

## Optional triggers

All default trigger lists are empty. Examples:

```json
[
  {"type": "time", "days": "weekdays", "at": "19:00"},
  {"type": "process", "process": "steam.exe"},
  {"type": "event", "topic": "schedule.class_soon", "within_minutes": 5}
]
```

Time uses local HH:MM; days can be `daily`, `weekdays`, `weekends`, or a list of
`mon`…`sun`. Process rules detect newly started PID/creation-time pairs after a
baseline; no foreground titles or process contents are read. Event rules may
also include a JSON `match` object. Class suggestions ignore events more than
five minutes away by default. Rules show **Yes / Not now / Don't suggest again**.
Disabled rule IDs and deduplication slots persist in settings.

Add `"auto": true` only for deliberate automatic application. First-run/changed
file approval and close confirmation still apply unless explicitly opted out in
the scene. `"action": "end"` suggests ending this scene; with auto true it ends it.
Optional suggestions wait during quiet mode or another pending confirmation.

## Extension providers and safe commands

Plugins remain trusted Python code in FRIDAY, with no sandbox. These JSON rules
constrain the scene engine; they cannot sandbox a malicious installed plugin.
Other plugins look up `api.get_service('scene_actions')` and register a provider:

```python
registry.register('my_action', provider)
# provider.do(params) -> JSON undo token or None
# provider.undo(token) -> None; must be safe to retry
# Optional: validate(params), preview(params), prepare(params) -> write-ahead token
# In unload(), remove only your own generation:
registry.unregister('my_action', provider)
```

For strong crash recovery supply `prepare`: without it there is an unavoidable
gap if the process dies inside custom `do` before it returns its token. Providers
must not offer forbidden system power, shell or file-deletion actions. Re-register
against the new registry if scenes itself reloads; cope with an absent service.

`run_command` never calls the broad intent/AI/routine executor. It uses local parsing
for explicit app/window, absolute audio/brightness, mute, URL and passive-path
actions; all substeps are validated first. Recursive scenes, scripts, shell syntax,
PC power/session operations, deletion and installers are refused. Safe focus,
todo, hello and activity commands are explicitly permitted. Other trusted plugins
must opt finite safe patterns in via `registry.allow_command(plugin_id, patterns)`.
They must be offline and obey the same restrictions; plugin permission declarations
alone are not a sandbox. Use a real action provider when a custom command needs undo.

## Tests

```powershell
venv/Scripts/python.exe -B -m pytest tests/test_focus_plugin.py tests/test_scenes_engine.py tests/test_scenes_safety.py tests/test_scenes_triggers.py tests/test_scene_runtime.py tests/test_scene_quiet.py tests/test_scene_plugin_lifecycle.py tests/test_scene_activity.py -q
```

All desktop providers, clocks and close-window calls are faked. No tests change
volume/brightness/power, close applications, play media or send real notifications.
