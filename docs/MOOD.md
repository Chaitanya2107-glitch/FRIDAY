# Mochi moods

Mochi keeps the existing amber SVG, pill/peek/expanded widths and hotkeys.
The enabled-by-default `mood` plugin owns arbitration. The existing `focus`
plugin supplies session events; the mood plugin adds no competing focus timer.

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
Moving reactions sample at most 30 times a second. Between idle micro-behaviors
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
logical core, after ten seconds of warmup and thirty seconds per sample.

Manual check: run `mochi test all`, confirm each row in the pose table, then
repeat with Reduced motion on. Check battery bubble timing, focus completion,
rest/peek/expanded geometry, an untouched command draft, fullscreen pause and
resumption, and idle blinks/small behaviors. No sound should come from moods.
