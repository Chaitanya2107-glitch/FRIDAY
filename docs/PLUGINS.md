# FRIDAY plugins, API version 1

`hud` adds the transparent desktop HUD, boot sequence, and cached protected
system-statistics route. See [HUD.md](HUD.md) for settings, commands and verification.

`semantic_search` adds private offline document search, opt-in indexed folders,
and a `semantic_search` service. See [SEMANTIC_SEARCH.md](SEMANTIC_SEARCH.md) for
installation, commands, settings, privacy behavior and tests.

Plugins are **trusted Python code running inside FRIDAY, with no sandbox**.
Only install code you trust. Permissions describe intended access; they do not
prevent a plugin from importing Python modules, reading files, using the network,
or controlling the desktop. The host, bundled plugins, discovery and tests need
no network access and never install dependencies automatically.

## Quick start

Start FRIDAY normally, or start its backend with `venv\Scripts\python.exe main.py`.
The plugin host starts with `services.friday_island_server` in the backend.
Enter these commands in FRIDAY's command bar, chat, voice, or Island:

```text
list plugins
hello friday
todo add Buy bread and butter
plugin todos
todo done 1
todo remove 1
todo clear done
show recent events
```

`list plugins` shows `hello`, `todo`, and `system_events`, including versions,
enabled/load status, declared permissions, errors and command collisions.

Copy `plugins/_template/` to `plugins/my_plugin/`, change the manifest ID/name
and edit `main.py`. Direct child folders beginning with `_` are ignored.
Once a valid folder is present, discovery polls every two seconds. An ordinary
plugin should be usable within about three seconds, without restarting FRIDAY.
Save the entry and helpers before saving `plugin.json` when installing a folder.
Plugins are loaded alphabetically; look up optional services when needed rather
than assuming that another plugin was already registered.

For the first use of this implementation, restart the already-running backend
once so it loads the new host. Later plugin edits require no backend restart.

## Folder and manifest

```text
plugins/my_plugin/
  plugin.json
  main.py
  helpers.py       # optional; import with: from .helpers import something
```

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "api_version": 1,
  "description": "An offline feature.",
  "author": "Your name",
  "entry": "main.py",
  "permissions": ["events", "files", "ui"],
  "requires": [],
  "enabled_by_default": true
}
```

All fields except `entry` and `requires` are required. `version` is a nonempty
string; `api_version` must be the integer `1`. IDs match
`[a-z][a-z0-9_-]{0,63}` and must be unique. `entry` defaults to `main.py` and
must be an existing `.py` file inside the folder, without absolute paths or `..`.
Unknown fields, wrong types, invalid permissions and bad manifests are logged
and skipped; other plugins continue loading.

Allowed permissions: `events`, `files`, `clipboard`, `network`,
`system_control`, `ui`. Declare only what the feature uses. `requires` contains
installed pip **distribution names**, such as `psutil`, with no version syntax
or URLs. Missing packages produce a clear load error. Install dependencies
separately from offline media if needed; loading never invokes pip.

## Entry points and command results

```python
def register(api):
    def greet(match):
        name = match.group('name')
        return {
            'ok': True,
            'text': f'Hello, {name}.',
            'error': None,
            'speech': f'Hello, {name}.',   # optional
            'data': {'name': name},       # optional JSON object
        }

    api.on_command(r'greet (?P<name>.+)', greet,
                   help='Greet someone offline.', examples=['greet Ada'])


def unload():
    pass  # Optional: close resources opened outside the managed API.
```

Handlers are synchronous and receive a `re.Match`. Patterns may be one regex
string or a list of strings. Matching uses `re.fullmatch` and `re.IGNORECASE`.
The host reuses FRIDAY's text normalization for wake words/politeness. When it
removes the entire greeting, literal trimmed text is retained, so `hello friday`
works. Captures keep their case; normalization can remove final punctuation.

Return `ok` as a bool, `text` as a string and `error` as a string or `None`.
`speech` is optional text; `data` is an optional JSON object. The host fills in a
missing `error` with `None`, checks JSON serialization, and catches handler
exceptions. Failures become friendly failed results with `error=plugin_error`.
Never return coroutines, file handles, sets, datetimes or NaN: convert them to JSON.
Command text is the normal reply; optional `speech` follows existing reply speech
preferences. Use `api.speak` when the plugin explicitly needs offline speech.

FRIDAY's built-ins win over plugin patterns. Plugin handlers run before the
language/model fallback, including commands whose payload contains “and”. Use
distinct verbs and supply realistic `examples`: these help detect collisions
at registration. Actual built-in matches also record collision warnings.
Warnings are logged and appear in `list plugins`. Plugin/plugin overlaps use
discovery/registration order; prefer distinct patterns instead of relying on it.

## API reference

| API | Contract |
| --- | --- |
| `api.plugin_id` | The validated manifest ID. |
| `api.data_dir` | Absolute `pathlib.Path` for this plugin's persistent user data. |
| `api.settings.get(key, default=None)` | Read a JSON setting, returning a copy of the value/default. |
| `api.settings.set(key, value)` | Atomically persist a JSON value; existing keys are preserved. |
| `api.log` | Logger named `friday.plugins.<id>`; use debug/info/warning/exception. |
| `api.on_command(patterns, handler, help='', examples=())` | Register synchronous command handlers receiving a regex match. |
| `api.subscribe(pattern, callback)` | Callback receives the full event envelope; returns a subscription. |
| `api.publish(topic, payload)` | Publish a JSON object asynchronously; returns the envelope. |
| `api.every(seconds, fn)` | Positive finite interval; first `fn()` runs after the interval. |
| `api.run_background(fn)` | Managed daemon thread for finite work or cooperative long-running work. |
| `api.stop_event` | `threading.Event` set on unload; jobs should wait on/check it. |
| `api.notify(title, body, urgency='normal')` | Existing Windows notification helper, with Telegram mirroring off. |
| `api.speak(text)` | Schedule existing offline Piper/SAPI output; no-op without an active speech loop. |
| `api.set_mood(mood, duration_s=5, priority=0, message='', *, sticky=False)` | Publish `mood.set`; the mood plugin emits `mood.changed`. |
| `api.show_card(title, body, actions=(), ttl_s=30)` | Publish a literal-text Island card. |
| `api.on_action(action_id, handler)` | Handler receives the chosen action's JSON payload and returns a command result. |
| `api.provide(name, obj)` | Offer a runtime service; another plugin cannot replace its name. |
| `api.get_service(name)` | Return a loaded provider's object, or `None`. |
| `api.add_route('GET', path, handler)` | Mount a protected static path under `/api/plugins/<id>/`; handler receives `{'query': {...}}`. |

Notification `urgency` is advisory in v1: the existing Windows transport has no
urgency parameter. Failures are logged. No notification is mirrored to a phone.
Temporary mood requests last up to 3600 seconds (positive), with integer priority;
lower priorities cannot displace a higher priority. Equal priority uses the latest
request. Expiry returns to the active sticky mood, then idle. Island's live
listening/speaking/thinking state takes display precedence. See [MOOD.md](MOOD.md)
for all eleven moods, editable rules, calm/developer settings and test commands.

### Settings and files

Plugin state lives at `%APPDATA%\FRIDAY\plugins\<id>\`, never in `plugins/`
or the repository's existing `memory/` folder. Settings use `settings.json`;
plugin enable/disable choices use `%APPDATA%\FRIDAY\plugin-state.json`.
`FRIDAY_USER_DATA` can select an absolute user-data root outside this repository.
Without APPDATA, the default is `~/.config/FRIDAY`.

```python
interval = api.settings.get('interval_seconds', 60)
api.settings.set('interval_seconds', interval)
path = api.data_dir / 'items.json'
```

Reuse `services.settings_store.save(path, value)` for atomic JSON writes. Protect
read/modify/write sequences with your own lock or `settings_store.lock`.
Treat malformed saved data as an error; do not silently overwrite it with an
empty list. Disabled/reloaded plugins retain their data and settings.

### Events

```python
def register(api):
    def battery_warning(event):
        percent = event['payload']['percent']
        api.notify('Battery', f'{percent}% remaining')
    api.subscribe('battery.low', battery_warning)
    api.subscribe('activity.*', lambda event: api.log.debug('%s', event['topic']))
```

Topics use dotted words. A `*` segment matches a suffix, including further dots;
`*` alone subscribes to all topics. Each subscription has its own worker thread
and 200-event queue. Delivery order follows publication order for that subscriber;
there is no cross-subscriber completion ordering. Publishers never run callbacks.
Slow subscribers drop their oldest queued event when full. Events are transient,
not a durable job queue; persist important state before publishing a change.

The global bus retains the last 200 envelopes for `show recent events`.
Envelopes contain `id`, `topic`, `payload`, `plugin_id`, and Unix `at`.
Payloads must be JSON objects, without NaN/Infinity. Avoid secrets or clipboard
contents: debug history and authorized Island clients can read these events.
See [EVENTS.md](EVENTS.md) for official topics and payloads.

### Background work and unloading

```python
def register(api):
    api.every(60, lambda: api.publish('my_plugin.tick', {}))

    def worker(stop):
        while not stop.wait(5):
            api.log.debug('Doing a short offline check')
    api.run_background(worker)
```

Background functions with a parameter receive `api.stop_event`; no-argument
functions are also supported for finite jobs. Do not use an infinite `sleep`
loop or start unmanaged threads. Python cannot forcibly terminate arbitrary
in-process threads safely. Managed jobs **must cooperate with cancellation**.
Unload fences the old API, signals jobs, removes subscriptions, commands,
routes, actions and services, calls optional `unload()`, and imports a fresh
module generation. Imports from relative helpers also read fresh source.
The host waits briefly for jobs; an uncooperative job is logged and its API
stays fenced. Trusted code using raw OS/file APIs remains outside those guards.

Five uncaught load/callback/result failures within 60 seconds auto-disable a
plugin, persist that choice, emit `plugin.disabled`, and send a local notification.
Discovery retries failed loads every two seconds until that limit. Fix the code,
then explicitly enable it again. A normal reload does not re-enable disabled plugins.

```text
disable plugin my_plugin
enable plugin my_plugin
reload plugins
```

### Cards, actions and optional services

```python
def register(api):
    api.on_action('ack', lambda payload: {
        'ok': True, 'text': 'Acknowledged.', 'error': None,
    })
    api.show_card('Offline reminder', 'Take a short break.',
                  actions=[{'id': 'ack', 'label': 'Done', 'payload': {}}], ttl_s=30)

    def add_task(match):
        todos = api.get_service('todo')
        if todos is None:
            return {'ok': False, 'text': 'Enable the todo plugin first.', 'error': 'service_missing'}
        return todos.change('add', match.group(1))
    api.on_command(r'capture task (.+)', add_task, examples=['capture task Read chapter 2'])
```

Cards accept title ≤120 characters, body ≤4000, up to six action dictionaries
`{id, label, payload?}`, and TTL clamped to 1–3600 seconds. Markup is never rendered.
Action IDs use letters/numbers/`_`/`-`, ≤64 characters; labels ≤40.
Look services up at use time and cope with `None`; do not retain stale provider
objects across reloads. Providers define/document their own service interfaces.

## HTTP bridge and security

The existing WebSocket remains on `127.0.0.1:17321`. The companion HTTP endpoints
use FRIDAY's existing API port (normally `127.0.0.1:8000`), advertised to Island
in its authenticated status frame. Compatibility `--bridge-only` mode also starts
a loopback HTTP companion using `connection.api_port` in its isolated config.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/plugins` | Manifests, permissions, status and warnings. |
| `POST /api/plugins/<id>/enable` / `disable` | Persist enabled state and load/unload. |
| `POST /api/plugins/reload` | Reload enabled plugins and rediscover folders. |
| `GET /api/plugins/<id>/<path>` | Plugin's registered static GET route. |
| `POST /api/plugins/<id>/actions/<action_id>` | Deliver a JSON object to `on_action`. |
| `GET /api/events?topic=activity.*` | SSE stream with an optional wildcard topic filter. |

These endpoints require `X-Friday-Token`. SSE also accepts `?token=` for native
clients, but Island uses fetch streaming with the header so the token stays out
of URLs. Access logs strip queries. The 32-byte random secret is materialized
once in `%APPDATA%\FRIDAY\island\config.json` (`connection.token`); Tauri reads
this local file through its native config command. Never put this token in a
plugin manifest, source, screenshots, logs, or version control.

Missing/wrong token returns 401; foreign Host returns 400; foreign Origin or
non-loopback peers return 403. Origins are restricted to Tauri's localhost origins
and the island's localhost development origin. CORS preflight contains no data
and needs no token. Token changes close existing SSE/WebSocket sessions. Native
clients may omit Origin. Legacy `/api/v1` routes retain their existing protection.

## Bundled plugins and Island

`hello` demonstrates one command and an activity subscriber. `system_events`
reuses proactive battery readings; if readings stop for 90 seconds it uses
installed psutil. Low/critical thresholds fire once until recovery above 25%,
including while charging. Cable changes emit plugged/unplugged transitions.
No battery means no battery transition events.

`todo` stores `todos.json` in its own data directory, with add/list/done/remove/
clear-done commands, a `todo` service, and `GET /api/plugins/todo/items`.
`todo list` collides with FRIDAY's existing built-in UI command, so use
`plugin todos`, `todos`, or `todo show` to list plugin items. The Island todo tile
shows plugin items first and existing workspace tasks in remaining rows. Its add
form writes plugin todos when enabled; existing task completion stays in its
original store. No existing task data is migrated or deleted. Habit and college
tiles keep their current behavior.

Island Settings → Hotkeys configures Sneak, Expand and Dismiss. Expand defaults
to `Ctrl+Shift+Alt+I`; the conflicting old default is migrated. Registration
failures display a message pointing to Hotkeys. In Settings → Connection,
“Start Island together with FRIDAY” is off by default. The existing opt-in
Windows sign-in control uses only the current user's Run key and needs no admin.
Enable it from a standalone release build; development builds need Vite.

## Offline testing

`smart_clipboard` provides Windows clipboard actions without a model, downloads,
or persistent clipboard data. It respects privacy flags and password managers,
retains one item in RAM, and sends only an 80-character UI preview with opaque
action tokens. Say `clipboard on`, `clipboard off`, `what's on my clipboard`,
`solve clipboard`, `convert clipboard`, or `clean clipboard link`; the default
actions shortcut is `Ctrl+Shift+Alt+V`. See
[its README](../plugins/smart_clipboard/README.md) for settings, extension APIs,
privacy limits, optional packages and fake-provider tests.

```powershell
venv/Scripts/python.exe -B -m pytest tests/test_event_bus.py tests/test_plugin_system.py tests/test_plugin_bridge.py
venv/Scripts/python.exe -B -m pytest tests
Set-Location island
npm.cmd test
npm.cmd run build
Set-Location src-tauri
cargo test --offline
```

For a new plugin, create its code/manifest under `tmp_path`, instantiate
`PluginManager(plugins_dir=tmp_path / 'code', data_root=tmp_path / 'data',
bus=EventBus(), notify=fake_notify, speak=fake_speak)`, then call `scan()` and
`command(...)`. Always `manager.close()` and `manager.bus.close()` in cleanup.
Use injected readers, fake clocks/events and temporary JSON files; never open
real windows, call network APIs, send notifications, speak or change the registry
in tests. Test malformed inputs, failure paths, disable/reload and saved-data
survival. The bundled tests are executable examples of these patterns.
