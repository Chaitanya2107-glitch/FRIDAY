# FRIDAY Island protocol v1

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
revision checks remain authoritative. This local checkout's productivity store and
workspace changes are prerequisites; they are not republished by Island commits.

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

Unrecognized text goes to FRIDAY's tool-free language handler. The main `/chat`
automation router is not used: it has broader desktop authority. Conversation
may use FRIDAY's configured provider; conversational text cannot become a launch.

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

Changing the port in Settings reconnects the UI; restart the server to rebind.
Hand-edited config requires Reload config or an app restart. A single config
file is shared through an interoperable byte-zero/whole-file OS lock, atomic
replacement, revision checking and Rust's source-content stamp. No token is
included in protocol docs, test receipts or source commits.
