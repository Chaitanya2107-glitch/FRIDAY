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
| `activity.app_changed` | `{app: string|null, previous_app: string|null}` | Foreground app changed; null indicates idle/unavailable. |
| `activity.idle_started` | `{previous_app: string|null}` | Activity monitor entered an idle boundary. |
| `activity.idle_ended` | `{app: string}` | Activity monitor resumed observing an app. |
| `activity.nudge` | `{kind: string, text: string, urgent?: boolean}` | A feature offers a nudge; not proof of notification delivery. |
| `clipboard.action_available` | `{action_id: string, label: string, preview?: string, expires_at?: number}` | An available clipboard action; omit raw clipboard contents. |
| `battery.low` | `{percent: number, plugged: boolean}` | Battery ≤20%, once per recovery episode. |
| `battery.critical` | `{percent: number, plugged: boolean}` | Battery ≤10%, once per recovery episode. |
| `battery.plugged` | `{percent: number, plugged: true}` | Cable transitioned to charging/plugged. |
| `battery.unplugged` | `{percent: number, plugged: false}` | Cable transitioned to unplugged. |
| `scene.started` | `{scene_id: string, name: string, since: number}` | A scene/mode provider started a scene. |
| `scene.ended` | `{scene_id: string, name: string, reason?: string}` | That scene ended. |
| `focus.started` | `{session_id: string, duration_s: number, task?: string}` | Explicit focus session started. |
| `focus.paused` | `{session_id: string, remaining_s: number}` | Explicit focus session paused. |
| `focus.done` | `{session_id: string, elapsed_s: number, reason: string}` | Focus session ended; reason distinguishes completed/cancelled. |
| `schedule.class_soon` | `{subject: string, starts_at: string, room?: string, text: string}` | Scheduled class warning; starts_at is a local ISO-8601 datetime. |
| `schedule.due_soon` | `{item_id: string, title: string, due_at: string, text: string}` | Due-item warning; due_at is an ISO-8601 datetime. |
| `mood.set` | `{mood: string, duration_s: number, priority: integer, message: string}` | Request a temporary mood; see arbitration below. |
| `mood.changed` | `{mood: string, previous: string, priority: integer, message: string, plugin_id: string, expires_at: number}` | Accepted/displayable mood state; expires_at=0 for idle. |
| `ui.card` | `{title: string, body: string, actions: [{id: string, label: string, payload?: object}], ttl_s: number}` | Show literal-text Island card with optional callbacks. |
| `briefing.ready` | `{text: string, generated_at: string}` | A completed briefing, generated_at ISO-8601; no delivery claim. |
| `index.progress` | `{phase: string, processed?: integer, total?: integer}` | A local indexer's progress; counters describe its own phase. |
| `index.done` | `{files: integer, readable?: integer, elapsed_s?: number}` | A successful local index pass. |
| `plugin.disabled` | `{plugin_id: string, reason: string, failures: integer}` | Host auto-disabled a plugin after repeated errors. |
| `todo.changed` | `{action: "add"|"done"|"remove"|"clear_done", items: [Todo]}` | Plugin todo store committed a change. |

`Todo` is `{id: integer, text: string, done: boolean, created_at: string}`;
`created_at` is UTC ISO-8601. A done item remains until removed or clear-done.
The `items` snapshot belongs to the JSON todo plugin; existing workspace tasks
remain in their original store.

## Producers and consumers in this increment

Connected producers are the existing activity monitor (`activity.app_changed`,
`activity.idle_started`, `activity.idle_ended`), `system_events` (all four battery
topics), the backend mood controller (`mood.changed`), the plugin host
(`plugin.disabled`), and `todo` (`todo.changed`). Plugins can publish `mood.set`
and `ui.card`; Island consumes those through the SSE companion. Activity event
payloads deliberately omit window titles.

The remaining official names above reserve shared contracts for feature/plugin
providers. They do not imply that legacy clipboard, modes, focus, schedule,
briefing or indexing code has been rewritten to emit these topics. Their current
feature behavior is preserved. A future provider should publish these shapes
instead of introducing a competing topic for the same event.

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

`mood.set` uses a positive finite duration ≤3600 seconds and integer priority.
While a mood is active, lower priority requests are ignored; equal priority uses
the latest request. Expiry publishes idle with `expires_at: 0`. The backend
publishes the accepted state once, and listening/speaking/thinking retains its
existing visual precedence on Island.

`ui.card` actions are delivered to the source plugin's `on_action(id, handler)`
through authenticated POST `/api/plugins/<plugin_id>/actions/<id>`. The handler
receives the action's JSON `payload` and returns the standard command result.
An expired, disabled or unloaded action fails cleanly. See [PLUGINS.md](PLUGINS.md)
for size limits, lifecycle, token security and an executable example.
