# FRIDAY Island protocol v1

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

Allowed actions are `{kind:"pin",id}`, `{kind:"project",id}`, and
`{kind:"settings"}`. The backend never sends executable paths or shell strings.
The UI dispatches ID actions through Rust, which reloads and validates config,
rejects missing/hidden/unconfigured entries, and runs only their persisted actions.
No action is executed while suggesting or resolving an ambiguous name.

Unrecognized text goes to FRIDAY's tool-free language handler. The main `/chat`
automation router is not used: it has broader desktop authority. Conversation
may use FRIDAY's configured provider, but provider output cannot become a launch.

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
keeps configured app/project commands and settings available through Rust.
Pill data updates on connect and every 60 seconds; plugin failures are contained.

Changing the port in Settings reconnects the UI; restart the server to rebind.
Hand-edited config requires Reload config or an app restart. A single config
file is shared through an interoperable byte-zero/whole-file OS lock, atomic
replacement, revision checking and Rust's source-content stamp. No token is
included in protocol docs, test receipts or source commits.
