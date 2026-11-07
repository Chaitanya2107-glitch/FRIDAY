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
| `focus.started` | `{session_id: string, duration_s: number, task?: string}` | Explicit focus session started. |
| `focus.paused` | `{session_id: string, remaining_s: number}` | Explicit focus session paused. |
| `focus.done` | `{session_id: string, elapsed_s: number, reason: string}` | Focus session ended; reason distinguishes completed/cancelled. |
| `schedule.class_soon` | `{subject: string, starts_at: string, minutes?: number, room?: string, text: string}` | Scheduled class warning; starts_at is a local ISO-8601 datetime. |
| `schedule.due_soon` | `{item_id: string, title: string, due_at: string, text: string}` | Due-item warning; due_at is an ISO-8601 datetime. |
| `mood.set` | `{mood: string, duration_s: number, priority: integer, message?: string, sticky?: boolean}` | Request a mood; the mood plugin arbitrates. |
| `mood.changed` | `{mood: string, message: string, until: number|null, sticky: boolean, previous: string, priority: integer, plugin_id: string, expires_at: number}` | Accepted mood. `until` is Unix seconds for temporary moods, null for sticky/idle. `expires_at` is its Phase 0 alias (0 for null). |
| `ui.card` | `{title: string, body: string, actions: [{id: string, label: string, payload?: object}], ttl_s: number}` | Show literal-text Island card with optional callbacks. |
| `briefing.ready` | `{text: string, generated_at: string}` | A completed briefing, generated_at ISO-8601; no delivery claim. |
| `index.progress` | `{phase: string, processed?: integer, done?: integer, total?: integer, current_folder?: string}` | A local indexer's progress; semantic_search emits at most once a second. No document text. |
| `index.done` | `{files: integer, readable?: integer, chunks?: integer, needs_ocr?: integer, elapsed_s?: number}` | A completed local index pass, including unreadable/OCR counts where available. |
| `plugin.disabled` | `{plugin_id: string, reason: string, failures: integer}` | Host auto-disabled a plugin after repeated errors. |
| `todo.changed` | `{action: "add"|"done"|"remove"|"clear_done", items: [Todo]}` | Plugin todo store committed a change. |
| `hud.changed` | `{settings: object, action: string}` | Occasional HUD configuration/control change; never system readings. |
| `hud.state_changed` | `{source: string}` | HUD focus/scene reducer committed an official event; consumers may refresh slow state. |
| `hud.available` | `{}` | HUD plugin loaded/reloaded; connected Island may fetch its current state. |

`Todo` is `{id: integer, text: string, done: boolean, created_at: string}`;
`created_at` is UTC ISO-8601. A done item remains until removed or clear-done.
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

The focus plugin publishes focus transitions; legacy modes publish scene starts
and ends; timetable/deadline warnings publish schedule events. Smart clipboard
publishes action availability, and semantic search publishes index completion.
The remaining names are shared contracts for additional providers; they should
publish these shapes instead of introducing competing names.

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
