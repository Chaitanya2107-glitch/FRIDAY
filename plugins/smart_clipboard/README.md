# Smart clipboard (Windows)

An offline rule-based plugin. No model, network client, new dependency, download
or persisted clipboard history. The plugin keeps one item and its latest result
in memory. Disable/reload clears them. Windows privacy flags and the copying
process are checked before text is obtained, inside the same clipboard lock.
Unknown owners and malformed privacy flags are skipped conservatively.

Restart FRIDAY's backend once to load the shared clipboard helper and command
router changes. Use the updated Island frontend (the development server, or a
rebuilt standalone Island). To rebuild the standalone executable offline:

```powershell
npm.cmd --prefix island run tauri -- build --no-bundle -- --offline
```

Then in FRIDAY, run `reload plugins`, `list plugins` and `clipboard on`. Copy `5 km to miles`: the
island offers **Convert**, with a preview near `3.106855961 mi`. Copy
`3x+5=20`: **Solve** shows `x = 5`; clicking it uses the installed local SymPy
engine and exposes working. Copy from a password manager: no clipboard card.
Cards expire after six seconds and do not activate the island window.

Commands:

- `clipboard on` / `clipboard off`
- `what's on my clipboard` (item type and available actions)
- `solve clipboard` / `convert clipboard` / `clean clipboard link`
- **Ctrl+Shift+Alt+V** shows current actions even below the confidence threshold.

Commands are local to the PC. The plugin owns these phrases ahead of FRIDAY's
older clipboard reader and generic `solve` command while installed/enabled.
New cards are limited to one per three seconds, including explicit requests.
Requests and action results for the same item refresh its existing card; idle,
game/sleep and fullscreen still suppress cards. No suppressed item is replayed
later. Hotkey registration failures show
a local message; commands remain available.

Settings live in `%APPDATA%\FRIDAY\plugins\smart_clipboard\settings.json` (or
the configured `FRIDAY_USER_DATA` root). Only preferences are written there:

```json
{
  "smart_clipboard.enabled": true,
  "smart_clipboard.confidence_threshold": 0.8,
  "smart_clipboard.card_ttl_seconds": 6,
  "smart_clipboard.hotkey": "Ctrl+Shift+Alt+V",
  "smart_clipboard.blocklist": [
    "keepass", "keepassxc", "bitwarden", "1password", "lastpass", "dashlane",
    "enpass", "nordpass", "roboform", "keeper", "protonpass"
  ]
}
```

The hotkey and settings are checked live. An empty blocklist is an explicit
override; privacy flags are always honored. Native reads cap text at 65,536
characters. Windows clipboard writes use exclusion/history/cloud opt-out flags
and a FRIDAY marker, so result copies are ignored by monitoring.

Only a one-line preview of at most 80 characters enters `ui.card`; opaque tokens
identify action payloads. Command/action responses are generic descriptions or
acknowledgments, and errors never include input or exception details. There is
no clipboard route or custom clipboard event. The Phase 0 bus retains the short
UI preview. Full results/working remain in RAM and are available via **Copy
result**. JSON **Format** and **Copy clean link** also copy their result directly.
Long text shows only word and character counts. FRIDAY's independent legacy
clipboard-history feature is unchanged; this plugin creates no history.

Detection and conversion work offline. **Open** and **Search online** explicitly
open the default app/browser only after selection. Those user-requested browser
actions may navigate online; there are no automatic requests. Filesystem
detection rejects UNC paths, mapped network drives, symlinks and junctions before
probing their targets. Local files/folders open only on selection.

Math checks an installed `math_engine` service at use time; otherwise it reuses
FRIDAY's bounded, hidden computation worker and safe SymPy AST. Without SymPy,
only the bounded stdlib arithmetic AST is offered. Input is never evaluated as
Python source. Subtraction without spaces, dates, phone/version numbers, bare
numbers, currency amounts and sentences are intentionally conservative.
Chemistry is available only with `periodictable`; local WordNet needs both NLTK
and its corpus installed. Missing dictionary data offers **Search online**.
No package or corpus is installed automatically.

Assumptions: offset-free ISO dates mean local time; default conversions pair
metric/US units, Fahrenheit/Celsius, and bytes/MiB. Gallons/cups are US units;
KB/MB/GB are decimal and KiB/MiB/GiB binary. Temperatures are absolute values.
10/13-digit numbers are interpreted as Unix epochs, while ordinary numbers
do not activate math. Scalar JSON is omitted to avoid these ambiguities.

## Extending the registry

Plugins are trusted in-process Python. Extensions must remain offline, keep
input in memory, and never log/publish/store it. They should register after the
service appears and remove their registrations on unload. The registry itself
retains only detector definitions, never clipboard items.

```python
from plugins.smart_clipboard.registry import Action

registry = api.get_service('clipboard_actions')
if registry:
    remove_detector = registry.register(
        'my_detector',
        lambda text: 0.95 if text == 'example!' else 0.0,
        [Action('transform', 'Transform', lambda text: 'local result')],
        preview=lambda text: 'A short local preview',
    )
# Call remove_detector() in unload(). Action returns str result, or None for Open.
```

The host uses isolated module generations on reload. For compatibility, actions
are accepted by their `name`, `label`, `run` interface; confidence must be finite
and between zero and one. At most three actions appear. A `math_engine` provider
must implement offline `calculate(command)` returning a string, EngineResult,
or `{ok/success, value/text}`; alternatively `evaluate(text)` and `solve(text)`.
It is looked up on every use, so providers can reload independently.

## Tests

From the repo root:

```powershell
venv/Scripts/python.exe -B -m pytest tests/test_smart_clipboard.py tests/test_smart_clipboard_actions.py tests/test_smart_clipboard_native.py -q
venv/Scripts/python.exe -B -m pytest tests/test_event_bus.py tests/test_plugin_system.py tests/test_plugin_bridge.py tests/test_clipboard_history.py tests/test_typing.py tests/test_computation_engine.py -q
npm.cmd --prefix island test
npm.cmd --prefix island run build
```

Tests inject fake clipboard/native functions, clocks, activity and hotkey pumps;
they never read the actual clipboard, register real shortcuts or open apps.

`venv/Scripts/python.exe -B tasks/smart-clipboard/verify.py` repeats the focused
regression tests and island checks, records source hashes and a fake-polling
benchmark in `tasks/smart-clipboard/evidence.json`, and uses a fresh isolated
folder under the system temporary directory. `venv/Scripts/python.exe -B -m pytest tests -q`
runs the entire repository suite.

## Files in this change

Added:

- `plugins/smart_clipboard/{plugin.json,main.py,registry.py,maths.py,units.py,detectors.py,windows.py,README.md}`
- `tests/{smart_clipboard_support.py,test_smart_clipboard.py,test_smart_clipboard_actions.py,test_smart_clipboard_native.py}`
- `island/src/plugin-card.ts`, `island/tests/plugin-card.test.ts`
- `docs/specs/2026-11-05-smart-clipboard.md`, `tasks/smart-clipboard/{verify.py,validation.md}`

Changed:

- `services/automation/{clipboard.py,intent.py}`, `services/plugin_runtime.py`
- `island/src/{main.ts,friday.ts,reply-state.ts,reply-surface.ts,reply.css}`
- `tests/test_plugin_system.py`, `docs/PLUGINS.md`

Native privacy behavior follows Microsoft's
[clipboard format contracts](https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats#cloud-clipboard-and-clipboard-history-formats).
The bounded text reader also accounts for
[GlobalSize reporting a larger allocation than the text](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-globalsize).
