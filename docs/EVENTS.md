# FRIDAY event contracts, v1

Publish via `api.publish(topic, payload)` or `services.event_bus.publish`.
Every payload is a JSON object; times named `at`, `since`, or `expires_at` are
Unix seconds unless explicitly documented otherwise. Unknown additional fields
may be ignored by consumers. Do not infer task completion, permission or user
intent from observed activity.

```json
{
  "id": 42,
  "topic": "todo.changed",
  "payload": {"action": "add", "items": []},
  "plugin_id": "todo",
  "at": 1793870000.0
}
```

IDs increase during one backend process and reset on restart. There is no durable
replay guarantee. `show recent events` retains 200 envelopes; GET `/api/events`
streams live events only. An optional `?topic=activity.*` filter uses the same
wildcard rules as `subscribe`. Each subscription has a separate worker/queue;
slow subscribers lose their oldest queued event beyond 200 entries.

## Official topics

Fields with `?` are optional. `null` is permitted only where shown.

| Topic | Payload shape | Meaning |
| --- | --- | --- |
| `activity.app_changed` | `{process: string|null, app_name: string|null, category: string}` | Activity plugin changed canonical app/site/category. Private windows use null identities and category `private`. |
| `activity.idle_started` | `{since: number}` | No input for the configured threshold, or foreground window disappeared/locked. |
| `activity.idle_ended` | `{at: number}` | Active foreground sampling resumed. |
| `activity.nudge` | `{reason: "continuous_category", minutes: number, category: string}` | Continuous-category threshold reached; no app/window text is included. |
| `clipboard.action_available` | `{action_id: string, label: string, preview?: string, expires_at?: number}` | An available clipboard action; omit raw clipboard contents. |
| `battery.low` | `{percent: number, plugged: boolean}` | Battery ≤20%, once per recovery episode. |
| `battery.critical` | `{percent: number, plugged: boolean}` | Battery ≤10%, once per recovery episode. |
| `battery.plugged` | `{percent: number, plugged: true}` | Cable transitioned to charging/plugged. |
| `battery.unplugged` | `{percent: number, plugged: false}` | Cable transitioned to unplugged. |
| `scene.started` | `{scene_id: string, name: string, since: number, quiet_mode?: boolean}` | A scene/mode provider started a scene. Quiet scenes suppress mood priorities below 4. |
| `scene.ended` | `{scene_id: string, name: string, reason?: string}` | That scene ended. |
| `scene.state` | `{scene_id: string|null, name: string|null, since: number|null, phase: "idle"|"applying"|"active"|"undoing"}` | Official scenes snapshot on load/every five seconds; repairs owners missed during reload. |
| `focus.started` | `{session_id: string, minutes: number, label: string, duration_s: number, task: string, phase: string, round: integer, owner: string, resumed?: boolean}` | Explicit focus/break phase started or resumed. |
| `focus.paused` | `{session_id: string, minutes: number, label: string, duration_s: number, remaining_s: number, phase: string, round: integer, owner: string}` | Focus or break phase paused. |
| `focus.done` | `{session_id: string, minutes: number, label: string, completed: boolean, elapsed_s: number, reason: "completed"|"stopped", phase: string, round: integer, owner: string}` | Timer phase ended; breaks do not count as focused time. |
| `schedule.class_soon` | `{subject: string, faculty?: string, room?: string|null, starts_at: string, minutes?: number, lead_minutes?: number, text: string}` | Local ISO class start. schedule_alerts emits both configured leads (15/5 minutes by default), with persistent occurrence/lead de-duplication. `minutes` is actual remaining time rounded up; `lead_minutes` identifies the crossed threshold. |
| `schedule.due_soon` | `{title: string, kind?: string, due_at: string, hours?: number, lead_hours?: number, item_id: string, text: string}` | Local ISO due time. Default assignment leads 24/3 hours; exams 72/24 hours. Actual remaining `hours` and configured `lead_hours` are separate. |
| `mood.set` | `{mood: string, duration_s: number, priority: integer, message?: string, sticky?: boolean}` | Request a mood; the mood plugin arbitrates. |
| `mood.changed` | `{mood: string, message: string, until: number|null, sticky: boolean, previous: string, priority: integer, plugin_id: string, expires_at: number}` | Accepted mood. `until` is Unix seconds for temporary moods, null for sticky/idle. `expires_at` is its Phase 0 alias (0 for null). |
| `ui.card` | `{title: string, body: string, actions: [{id: string, label: string, payload?: object}], ttl_s: number, card_id?: string, urgency?: "normal"|"critical"}` | Literal-text Island card. Briefings use the expanded FRIDAY view, at most six lines, with an opaque ID for scoped actions/dismissal. Explicit requests and sleep-scene responses may use critical delivery under quiet mode. |
| `briefing.ready` | `{kind?: "morning"|"night", text: string, generated_at?: string}` | briefings publishes after local delivery is claimed. Legacy builders may omit kind and include generated_at (ISO-8601). |
| `briefing.dismissed` | `{kind: "morning"|"night", card_id: string}` | Only the briefings owner's matching card is dismissed after Skip, Snooze or a sleep answer. |
| `index.progress` | `{phase: string, processed?: integer, done?: integer, total?: integer, current_folder?: string}` | A local indexer's progress; semantic_search emits at most once a second. No document text. |
| `index.done` | `{files: integer, readable?: integer, chunks?: integer, needs_ocr?: integer, elapsed_s?: number}` | A completed local index pass, including unreadable/OCR counts where available. |
| `plugin.disabled` | `{plugin_id: string, reason: string, failures: integer}` | Host auto-disabled a plugin after repeated errors. |
| `todo.changed` | `{action: "add"|"done"|"remove"|"clear_done", items: [Todo]}` | Plugin todo store committed a change. |
| `hud.changed` | `{settings: object, action: string}` | Occasional HUD configuration/control change; never system readings. |
| `hud.state_changed` | `{source: string}` | HUD focus/scene reducer committed an official event; consumers may refresh slow state. |
| `hud.available` | `{}` | HUD plugin loaded/reloaded; connected Island may fetch its current state. |

`Todo` is `{id: integer, text: string, done: boolean, created_at: string, done_at?: string}`;
`created_at` and `done_at` are UTC ISO-8601. New completions keep a daily count
even after clear-done; old undated completions are never assigned invented dates.
A done item remains until removed or clear-done.
The `items` snapshot belongs to the JSON todo plugin; existing workspace tasks
remain in their original store.

## Producers and consumers in this increment

Connected producers are the `activity` plugin (the four `activity.*` topics),
`system_events` (all four battery
topics), the `mood` plugin (`mood.changed`), the plugin host
(`plugin.disabled`), and `todo` (`todo.changed`). Plugins can publish `mood.set`
and `ui.card`; Island consumes those through the SSE companion. Activity event
payloads deliberately omit window titles. Installing `plugins/activity/main.py`
takes over foreground awareness and disables the legacy title/browser-history
sampler, even if the new plugin is paused, disabled or fails. With no activity
plugin installed, the legacy monitor retains its older `{app, previous_app}` /
`{previous_app}` / `{app}` transition payloads. Check the envelope's `plugin_id`
when supporting older FRIDAY installations.

The focus plugin publishes focus transitions; scenes and legacy modes publish scene starts
and ends. The schedule_alerts plugin owns schedule warning events while installed;
its presence disables legacy 10-minute class warnings and duplicate deadline alerts.
Briefings owns daily delivery and explicit briefing aliases while installed, including
when disabled or unavailable (the old weather-enabled briefing does not resume). Smart clipboard
publishes action availability, and semantic search publishes index completion.
The remaining names are shared contracts for additional providers; they should
publish these shapes instead of introducing competing names.

Focus `minutes` is the planned phase duration; `elapsed_s` records elapsed work
for a stopped phase. `phase` is `focus`, `short_break` or `long_break`; rounds
start at one. Stats count active focus segments, excluding pauses/breaks and
clipping at local midnight/Monday. The scenes plugin uses `scenes:` owner IDs;
activity snapshot reconciliation prunes only that namespace.

During scene quiet mode ordinary `ui.card` events remain in debug history with
`suppressed: true` but are not delivered. SSE also filters cards queued before
quiet activation. Optional payload `urgency: "critical"` bypasses quiet for
explicit confirmation/recovery; ordinary trigger suggestions do not bypass it.

## Battery and internal monitor event

The existing proactive monitor publishes the internal topic
`system.battery_reading` with `{percent: number|null, plugged: boolean|null}`.
It continues even when visible nudges are disabled. `system_events` consumes it
and falls back to psutil only after readings have stopped for 90 seconds.
No battery produces no low/critical/cable event. The first reading initializes
the cable state; subsequent changes emit plugged/unplugged. Low/critical fire
independently and both can fire on a first critical reading. Their flags reset
only above 25%, independently of charging; flags persist across hot reloads.

## Mood and UI actions

`mood.set` accepts the eleven moods listed in [MOOD.md](MOOD.md), a positive finite
duration ≤3600 seconds and integer priority. A higher priority interrupts and
equal priority replaces. Temporary expiry returns to the highest-priority current
sticky context, then idle. Interrupted temporary moods are discarded. Sticky
contexts have owners, so ending one focus session/scene cannot clear another.
Rule cooldowns default to 60 seconds; rejected reactions do not consume them.
Sticky lifecycle cooldowns are per owner and reset on their release event.
`mood.calm_mode` and quiet scenes allow only priority 4 and above. FRIDAY's
shared quiet-state owner is also honored while scenes are active.
Listening/speaking/thinking retains its existing display precedence. Island
fetches `GET /api/plugins/mood/state` with the same token on reconnect because
SSE has no replay. `message` is literal text, bounded to 60 characters; peek
bubbles last four seconds. No sound is added by the mood plugin.

`ui.card` actions are delivered to the source plugin's `on_action(id, handler)`
through authenticated POST `/api/plugins/<plugin_id>/actions/<id>`. The handler
receives the action's JSON `payload` and returns the standard command result.
TTL removes the card from the display; disabled or unloaded actions fail cleanly. See [PLUGINS.md](PLUGINS.md)
for size limits, lifecycle, token security and an executable example.

Semantic-search result cards additionally carry an opaque `content_ref` and
`result_start`/`result_count`. Their bus body contains only filenames/counts;
Island fetches private snippets from the authenticated plugin `results` route.
These snippets never enter the event bus, replay history, or logs.
