# Mochi moods

Mochi keeps the existing amber SVG, pill/peek/expanded widths and hotkeys.
The enabled-by-default `mood` plugin owns arbitration. The existing `focus`
plugin supplies session events; the mood plugin adds no competing focus timer.
Restart FRIDAY once if its Phase 0 mood controller is already running, and
launch the rebuilt Island. Later rule-file edits reload without a restart.

Try these in FRIDAY's command bar, chat or Island:

```text
mochi test all
mochi test worried
mochi dev on
fake event battery.low
focus 25
pause focus
resume focus
stop focus
mochi calm on
mochi calm off
mochi dev off
```

`mochi test all` shows each of the eleven moods for three seconds. Test moods
use priority 100 so an ordinary reaction does not hide a pose during the demo;
they return to the current sticky context afterward. They add no sound.
Real focus completion also celebrates. To test that quickly, use `focus 0.05`
(three seconds). Existing focus notifications retain their own preferences.

With developer commands enabled, `fake event <topic>` supplies harmless example
fields (battery 18%, subject Study, five minutes, etc.). An optional JSON object
replaces them, for example:

```text
fake event schedule.class_soon {"subject":"DBMS","minutes":5}
fake event scene.started {"scene_id":"demo","name":"exam","quiet_mode":true}
fake event scene.ended {"scene_id":"demo","name":"exam"}
```

Developer commands default off and never bypass the event bus or mood priority.

## Rules and settings

Edit [mood_rules.json](../plugins/mood/mood_rules.json). The engine reloads this
data live, without restarting the plugin or clearing active sticky contexts.
Malformed/partial edits log a warning and keep the last valid rules. Other plugin
source edits follow the host's ordinary reload behavior. Rules use version 1:

```json
{"version":1,"rules":[
  {"event":"battery.low","mood":"worried","duration_s":8,"priority":3,
   "message":"Battery at {percent}%","cooldown_s":60}
]}
```

Supported fields: `event`, `mood`, positive `duration_s` up to 3600, integer
`priority`, `message`, boolean `sticky`, `cooldown_s` (default 60), `until` (release
event names), `match` (payload field to allowed literal values), `min_idle_s`.
Message fields are simple names; missing fields become `?`. Values are literal
text, with no attribute lookup, script or markup execution.

Higher priority interrupts; equal priority replaces. Temporary reactions return
to the highest-priority current sticky context, then idle. Interrupted temporary
reactions do not resume. Scene/focus identities keep release events scoped to
their own sticky context. A lower-priority sticky context can wait underneath an
alarm and becomes visible when the alarm expires. Rule cooldowns are global for
temporary reactions and per owner for sticky lifecycles; rejected requests do
not consume cooldowns. Ending a lifecycle clears its sticky-rule cooldown.

Plugin settings live in `%APPDATA%\FRIDAY\plugins\mood\settings.json`:
`mood.calm_mode` and `mood.dev_commands` are booleans, both false by default.
Use the `mochi calm` / `mochi dev` commands above to change them safely.
Calm mode and any quiet scene permit only priorities 4 and above. Study/exam
and focus have priority 4. Quiet game/sleep scenes therefore suppress their own
lower-priority expressions. The shared FRIDAY quiet-state owner is honored
while a scene is active, including custom scenes with quiet actions.

Assumptions: late night means **local 01:00–05:59**, with recent input, once per
30 minutes, priority 1. Dozing waits for ten minutes since last input, including
when the plugin starts while the user is already idle. An idle-ended event wakes
Mochi with a wave. Plugin code reload resets mood contexts; JSON rule edits do
not. SSE reconnect fetches the authenticated mood snapshot because events have
no replay guarantee.

## Motion and comfort

| Mood | Pose/reaction |
| --- | --- |
| idle | A blink every 3–6 seconds; look, stretch or yawn every 20–60 seconds |
| happy | Small bounce and smile |
| curious | Gentle tilt toward peek |
| worried | Dimmer amber and a small blue sweat drop |
| alarmed | Faster amber glow pulse |
| sleepy | Dimmer amber, half-closed eyes, floating z |
| dozing | Closed eyes and slow breathing |
| focused | Narrowed eyes and a calm, steady glow |
| alert | Perked eyes and a small bounce |
| celebrating | Tiny amber sparkles and a smile |
| waving | A raised, gently waving hand |

Messages use a four-second, at-most-60-character bubble in passive peek. They
do not take keyboard focus or open expanded view. A command draft, active reply,
Sneak, hidden Island or fullscreen application prevents automatic peek.

Settings → Look → **Reduced motion** persists `island.reduced_motion` in Island's
config. It combines with Windows motion preferences and `prefers-reduced-motion`;
any one enables static poses. Hidden/Sneak, a hidden document, locked desktop
or a foreground fullscreen application stops animation and idle timers.
Moving reactions sample at most 30 times a second (slow breathing/z motion uses
four samples a second). Resting desktop status polls every five seconds;
interactive peek/expanded views retain two-second readings. Between idle micro-behaviors
there is no character frame loop and no continuously composited CSS animation.

## Validation

```powershell
venv/Scripts/python.exe -B -m pytest tests/test_mood.py tests/test_focus_plugin.py tests/test_event_bus.py tests/test_plugin_system.py tests/test_plugin_bridge.py
Set-Location island
npm.cmd test
npm.cmd run build
Set-Location src-tauri
cargo test --offline
```

For a packaged native check, from the repository root (after the frontend build):

```powershell
venv/Scripts/python.exe -B tasks/mochi-mood/build_probe.py candidate
venv/Scripts/python.exe -B tests/island/check_mood_native.py
venv/Scripts/python.exe -B tasks/mochi-mood/measure.py candidate
```

The probe uses its own app identity, config, token, loopback bridge and profile.
It does not stop the owner's Island or start the owner's backend. CPU results,
source/build hashes and screenshots are under `tasks/mochi-mood/`. CPU includes
the native Island and all recursive WebView2/GPU children, as percent of one
logical core, after forty-five seconds of warmup and thirty seconds per sample.
DevTools attaches only after CPU sampling, to verify the observed pose and mode.

Manual check: run `mochi test all`, confirm each row in the pose table, then
repeat with Reduced motion on. Check battery bubble timing, focus completion,
rest/peek/expanded geometry, an untouched command draft, fullscreen pause and
resumption, and idle blinks/small behaviors. No sound should come from moods.

## Files in this change

Added: `plugins/mood/{plugin.json,main.py,engine.py,rules.py,mood_rules.json}`;
`island/src/{mochi.ts,mochi-display.ts,mochi.css}`; `island/tests/mochi.test.ts`;
`tests/test_mood.py`; `tests/island/{mood_fixture.py,check_mood_native.py}`;
this guide and `docs/specs/2026-11-06-mochi-mood.md`.

Changed: `services/{plugin_api.py,plugin_manager.py,plugin_mood.py,plugin_runtime.py}`;
`services/automation/modes.py`; `services/proactive/{timetable.py,deadlines.py}`;
`services/friday_island_server/config.py`; `plugins/smart_clipboard/main.py`;
`island/src/{main.ts,icons.ts,capsule.ts,settings.ts,types.ts,native.ts}`;
`island/src-tauri/src/{main.rs,windows.rs,hud.rs}`;
`tests/{smart_clipboard_support.py,test_smart_clipboard.py}`;
`docs/{EVENTS.md,PLUGINS.md}`.

Local, gitignored validation helpers/artifacts are in `tasks/mochi-mood/`,
including `build_probe.py`, `measure.py`, immutable build snapshots and receipts.
Adjacent focus, scene and HUD implementation changes are preserved.
The Island startup config/status read retries briefly while native state becomes
available, so a cold launch can subscribe with its actual token and port.

The packaged native walkthrough verifies all eleven moods through the real
authenticated stream, the battery bubble and four-second timeout, focus
start/pause/resume/end, the frame cap, reduced-motion preference/setting and
persistence, hidden suspension and rejected missing-token requests. It keeps
the owner's Island and backend running. The full receipt is
`tasks/mochi-mood/native-check/receipt.json`.

Recorded validation: 365 backend cases passed; 59 Island runtime/bridge/mood
cases and seven subtests passed (these overlap the backend mood cases); 31 Node
tests passed; TypeScript/Vite build passed; Rust had 12 passes and one existing
installed-app metadata test skipped. The packaged walkthrough passed on the
same frozen release used for CPU sampling.

The final **45-second unpaused idle sample used 0.87% of one logical core**
(0.036% of total CPU on this 24-thread machine), including all eight
Island/WebView2/GPU processes. It used the validated release, an isolated
loopback bridge, eight seconds of warmup, and no attached DevTools. The document
was visible; fullscreen, desktop lock and reduced motion were all off. The raw
result is `tasks/mochi-mood/candidate-active-idle/measurement.json`.

A separate 60-second sample after 45 seconds of warmup used **0.57% of one
logical core** with a fullscreen foreground window and the animation pause
gate active (`tasks/mochi-mood/candidate-final/measurement.json`). These are
local observations; the runbook above reproduces them on another machine.
