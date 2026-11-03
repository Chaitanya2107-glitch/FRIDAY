# FRIDAY Island protocol v1

## Integrated FRIDAY runtime (additive v1 extension)

Production transport lives in the full API lifespan. `status.integrated:true`
identifies that runtime; `/health.island` separately reports listener readiness.
The isolated compatibility bridge keeps `integrated:false` and its narrow engine.

| Type | Request | Result |
| --- | --- | --- |
| `command` | `text`, optional native `target:{hwnd,pid,captured_at}` | Canonical FRIDAY reply and privacy/confirmation/job metadata |
| `runtime_state` | Server event, about once per second | Backend epoch, body/voice state, desktop lease, mode/screen state, automation status, bounded identified events |
| `runtime_action` | Fixed `action`, optional bounded `value` | Requested control/result; actual state comes from subsequent snapshots |
| `history` | No extra fields | Up to 20 bounded canonical history entries |
| `keyboard_apply` | Backend-issued one-use token in `item` | Original foreground process/window is checked before backend-generated steps run |
| `projects` | Optional `action:"import"` | Revision-aware shared catalog and native launch-profile references |

`command_result` preserves `private`, `awaiting_reply`, `action_success`,
`automation_job`, provider/model and an optional `keyboard_token`. It never sends
raw typing steps to the webview. `awaiting_reply` can mean a date or ordinary
question, so the UI does not invent generic approval buttons. Existing `next`,
habit and todo plugin shortcuts retain their meanings; pending system
confirmations take precedence. Other assistant text uses the decorated canonical
chat flow under explicit local authority, without Telegram confirmation bypass.

Long commands run separately from the receive loop. Stop controls remain
receivable and no command is automatically retried after disconnect or timeout.
Token rotation is checked before live pushes as well as incoming requests.

The sole desktop controller polls `/api/v1/island/desktop` using the shared token
in a header, loopback-only middleware and an ownership lease. Commands are claimed
once, then acknowledged by identifier after dispatch. Typed turns wait for the
controller acknowledgement before chat begins; microphone cancellation and the
existing conversation state machine therefore precede the assistant action.
The Island never consumes the proactive-question queue. Notification display
events preserve Windows delivery receipts and do not claim the owner read them.

Nonprivate desktop replies include `transient:true` for short voice-command
acknowledgements. These display in the capsule and stay out of its conversation
history. Reminder `notification` events retain their titles and validated
`friday://` action buttons. Capsule acknowledgement dismisses only the display;
it never approves a pending action or changes reminder-delivery receipts.

Private turn content is never appended to Island history or localStorage and
clears on close, tab change and disconnect. Session events are bounded and
identified by backend epoch plus sequence; old events are not invitations to
restart listening. Native Start FRIDAY and All controls remain available while
the backend is offline. The trusted screen-awareness badge keeps its existing
native visibility and heartbeat requirements.

## Live tracker widgets (additive v1 extension)

`plugin_widget.widget` may include `items` (up to six displayed rows), each with
`id`, literal `label`, `detail`, and an optional `action` containing `label`,
`action`, `item`, numeric `revision`, optional `value` and `disabled`. An optional
`input` contains `label`, `placeholder`, `action` and `max_length` (at most 160).
These are generic host controls; no HTML, executable code or native launch target
is accepted from a widget. Rendering never triggers an action.

A deliberate button/form submission sends `plugin_action` with `plugin`, `action`,
`item` (default empty), `value` (up to 160 characters), and `revision` (finite
number or null), plus the usual `v` and request `id`. Its response is a correlated
`command_result`. It uses the same authentication, rate limit, serialized command
handling and no-retry policy as palette commands. Each registered plugin validates
its own action names, record IDs and revisions; other plugins cannot receive it.
Todo allows `add`/`complete`; habits allow `add`/`check`/`uncheck`. Habit row actions
include the displayed local date in `value`, so crossing midnight requires refresh.
Failed or stale writes return `ok: false`; unknown plugins/actions never execute
native commands. Open widgets refresh every 15 seconds and after explicit writes.

Tracker adapters reuse FRIDAY's `services.productivity.store.Tracker` and existing
cognition/workspace database. They do not use the broader automation command router.
Tests inject an isolated Tracker. Existing planned-task completion rules and store
revision checks remain authoritative. FRIDAY's productivity store and revision-aware
workspace implementation are prerequisites when moving the feature to another clone.

Near-class `pill_snippet_update` frames additionally include `show_from` and
`expires_at`, both Unix epoch milliseconds. Only within that interval does the
frontend replace the date with the snippet; battery, clock and orb stay in place.
The class plugin emits this only during the 15 minutes before class, never at or
after its start. Empty snippets, disconnect, expiry and connection changes restore
the date. Frames lacking timing metadata do not replace the date.

Transport: WebSocket `ws://127.0.0.1:<connection.port>/`, default port **17321**.
The Python server binds only IPv4 loopback. No HTTP API, discovery broadcast,
remote listener or telemetry. Maximum inbound frame: 16 KiB; raw command length:
4000 characters; eight clients; forty messages per five seconds per client.
Client response limit: 64 KiB. JSON is UTF-8; binary is unnecessary.

## Authentication

Allowed browser origins, exactly: `tauri://localhost`, `http://tauri.localhost`,
`https://tauri.localhost`, and development `http://127.0.0.1:1420`.
Missing/foreign origins fail the HTTP upgrade. The peer must be `127.0.0.1`.

Before any data is sent, the client has five seconds to send:

```json
{"v":1,"type":"handshake","id":"hello","token":"<64 lowercase hex characters from local config>"}
```

The server compares tokens in constant time. Failure/unsupported version closes
with WebSocket code `1008`. Tokens never appear in URLs or application logs.
Origin checking protects browsers; the random token also protects against local
clients that can forge Origin. This is a same-user local boundary, not protection
against malware that can read the user's config. Treat config and backups as private.

Success yields `{v:1,type:"handshake",id:"hello",ok:true}`, followed by `status`,
`plugin_list` and `pill_snippet_update`. The token is rechecked against current
config for each request; rotation closes an old authenticated session.

## Envelopes

Requests require `v:1`, `type`, and a nonempty string `id` (at most 64 characters).
Responses echo `id`; unsolicited events use `id:null`. Unknown request fields
and unsupported types are rejected. Request-specific fields default to empty
strings if omitted. Suggestions never execute anything.

| Type | Request fields | Response/event fields |
|---|---|---|
| `handshake` | `token` | `ok` |
| `command` | `text` (raw user input) | Responds with `command_result` |
| `command_result` | Server only | `ok`, `text`, optional `action` |
| `suggestions` | `text` | `items:[{text,detail}]`, up to six |
| `pill_snippet_update` | Server only | `plugin` ID or null, `text` (up to 80 chars) |
| `plugin_list` | No extra fields | `plugins:[{id,name,commands,version,widget}]` |
| `plugin_widget` | `plugin` ID | `plugin`, `widget:{title,text,placeholder?}` |
| `status` | No extra fields | `online:true` |
| `error` | Server only | `code`, safe `text` |

Example command and response:

```json
{"v":1,"type":"command","id":"c17","text":"proj fri"}
{"v":1,"type":"command_result","id":"c17","ok":true,"text":"Opening FRIDAY","action":{"kind":"project","id":"friday"}}
```

Allowed actions are `{kind:"app",id}`, `{kind:"pin",id}`, `{kind:"project",id}`,
`{kind:"settings"}` and `{kind:"app_search",query}`. The backend never sends
executable paths or shell strings. Rust validates installed-app IDs against the
current native catalog, and manual pin/project IDs against current config.
An `app_search` query is only search text; it is resolved through the same native
catalog and can never supply launch arguments. No action runs while suggesting.

The UI handles `open <name>` natively before any WebSocket request, online or
offline. Bare names also suggest native app matches. Python returns `app_search`
if another protocol client sends it an `open` command. The app catalog and its
launch targets remain on the Tauri side; they are not uploaded to the bridge.
Pins are favourites, not a launch whitelist. Unpinning/hiding an indexed app
does not remove it from search. Successful launches update native recent history
in the shared config. See [native catalog details](APPS.md).

In the isolated compatibility bridge, unrecognized text goes to the tool-free
language handler. Production assistant requests use FRIDAY's full local command
authority and existing confirmations as described above. Native app suggestions
and selected catalog IDs still use the validated Rust launch path.

## Errors, lifecycle, reconnection

`invalid_request` describes bad JSON/schema/unknown widget. `handler_failed`
describes a failed or timed-out handler; internal exception text is never exposed.
A malformed request does not destroy an authenticated connection. Rate-limit
violations and token changes close with `1008`. Oversize frames close with `1009`.

Commands run serially per connection with a 60-second handler timeout. Disconnect
does **not** imply a command was rolled back. The UI never automatically retries
commands; this avoids double actions. Client command timeout: 65 seconds;
suggestions: 3 seconds; widgets: 5 seconds. Pending requests are rejected on
disconnect/config replacement, and stale socket generations cannot update status.

Reconnect waits 600 ms initially, doubles with jitter to a 30-second ceiling,
and resets after authentication. Offline mode changes the character's mood and
keeps installed-app search, manual pin/project commands and settings available through Rust.
Pill data updates on connect and every 60 seconds; plugin failures are contained.

Changing the port in Settings reconnects the UI and rebinds the integrated
transport. An isolated compatibility bridge must be restarted manually.
Hand-edited config requires Reload config or an app restart. A single config
file is shared through an interoperable byte-zero/whole-file OS lock, atomic
replacement, revision checking and Rust's source-content stamp. No token is
included in protocol docs, test receipts or source commits.
