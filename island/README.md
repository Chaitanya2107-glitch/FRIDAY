# FRIDAY Island

A quiet, original amber companion for Windows 10/11. Tauri 2 + plain TypeScript,
Vite and token-based CSS; an optional Python WebSocket bridge supplies FRIDAY's
commands and plugins. Existing FRIDAY startup and desktop interfaces are untouched.

## Setup and run

Use the repository's **Python 3.12 virtualenv**, Node **22.18+** (24 tested), stable
Rust with MSVC build tools/Windows SDK, and Microsoft Edge WebView2 Runtime.
[Tauri's Windows prerequisites](https://v2.tauri.app/start/prerequisites/) describe
the Rust/Visual Studio setup. On this laptop the required tooling is installed.

From the repository root, start the bridge in one PowerShell terminal:

```powershell
venv/Scripts/python.exe -m pip install -r services/friday_island_server/requirements.txt
venv/Scripts/python.exe -m services.friday_island_server --verbose
```

Then start the island in another:

```powershell
cd island
npm install
npm run tauri dev
```

The app also starts without the bridge. `open <installed app>`,
`proj <configured project>` and `settings` still work through Rust.
There is no taskbar entry: reach the app by top-center hover or its hotkeys;
use Settings → Connection → Quit Island to stop it. A second launch summons
the running instance. `npm run dev` alone is a browser preview with desktop
controls disabled.

**Existing shortcut conflict:** FRIDAY's current taskbar flyout already uses
`Ctrl+Shift+Alt+F`. The island keeps that requested default and reports the failure
in Settings → Hotkeys. Hover, open Settings, and choose an unused shortcut such
as `Ctrl+Shift+Alt+I`. It never unregisters another app's hotkeys.

Normal FRIDAY startup is unchanged. The bridge is opt-in and can run alongside
`python main.py`; it does not start FRIDAY's voice, tray, watchers or API loops.
The `next` adapter reads FRIDAY's actual timetable directly, without requiring
the main API process. Natural-language replies use FRIDAY's existing **tool-free**
language handler and configured AI provider; they can use that provider's normal
network behavior. The island UI itself connects only to `127.0.0.1`.

## Everyday use

- **Rest:** a full capsule with the character and no visible text for now.
  Hover reveals Peek. Snippet text and automatic shrinking are temporarily hidden
  regardless of the saved appearance toggle. `next` still answers on demand;
  the backend's class reminder window remains 15 minutes before class.
- **Peek:** one command input, up to eight visible app icons, Projects and Settings.
  Hover does not activate the window. Clicking the input deliberately activates it.
- **Expanded:** Projects · Plugins · Settings. Extra pinned apps appear above
  the project grid. Text fields accept focus when deliberately clicked.
- **Sneak:** `Ctrl+Shift+Alt+Space` opens a centered white input. Enter submits
  and dismisses it; Esc closes it. Results appear briefly by the resting island.
- **Expand hotkey:** `Ctrl+Shift+Alt+F` cycles Peek → Expanded → Rest. The first
  deliberate summon focuses the command input. Esc also closes a hover-opened
  passive panel while another app owns keyboard focus.

Use ↑/↓ for suggestions, Tab to complete and Enter to run. Both skins use one
input and command engine. Examples: `proj fri`, `open editor`, `next`, `habit`,
`todo buy charger`, `settings`, or a natural-language question. Exact names win
over partial matches. Ambiguous project names need more text; app matches are
ranked by name and recent use. Hiding/unpinning an installed app only changes
favourites: the app stays searchable and launchable.
`habit` and `todo` are explicitly **placeholders**, so they do not save data.
`note` and `focus` currently reach the tool-free conversational fallback; v1
does not add note storage or a focus timer.

The character is drawn in SVG code, with CSS breathing/blinking and mood changes.
The global pointer sample updates eyes at most 12.5 times/second; it does not
capture the screen. Animations stop while hidden/offline and honor Windows reduced
motion. The native window and WebView are fully transparent. The dark glass,
CSS backdrop blur, border and shadow belong only to the island element; no
native acrylic/mica/vibrancy is applied. Native size follows the animated
element bounds, keeping the top-center anchor (or centered Sneak box).

## Installed apps and favourites

Type `open <name>` in Peek or Sneak to fuzzy-search and launch any indexed app.
Typing a bare name also suggests matching apps; select one with ↑/↓ and Enter,
or Tab then Enter. A full exact bare app name also works. Suggestions include
icons and a one-click pin/unpin button. Duplicate names retain the selected app
ID, including after Tab completion. Native matches do not wait for Python.

Discovery covers current-user/all-users Start Menu shortcuts, 32/64-bit HKCU/HKLM
App Paths and packaged Windows Store apps through AppsFolder. It runs on startup,
every five minutes in the background, and via **Settings → Pinned apps → Rescan
apps**. No app-index data is uploaded. The in-memory catalog rebuilds locally;
recent launch history stays in the shared config and improves similar matches.

If nothing matches, the UI says **No app found** and offers Rescan apps. All this
works with the Python bridge stopped. App searches/launches are native in both
skins; other commands still use FRIDAY. Known plugin commands retain priority,
so `focus` remains a command while `open Focus` can launch an installed app.

Pins are only favourites. Your first eight visible pins appear in Peek, with
extras in Expanded. In Settings → Pinned apps, search the installed-app list and
click its pin icon, or use the pin beside a palette suggestion. Favourites stay
drag-reorderable and persist across restarts.

**Add app** retains the manual native `.exe`/`.lnk` picker for portable/custom apps.
Icons are
extracted into memory, with an original generic glyph if extraction fails.
Rename, show/hide, drag to reorder, use the up/down buttons, or click remove
twice to confirm. Hiding a manual favourite does not prevent command-line use;
removing it removes that manual launch entry. No arbitrary typed path or shell
command is executed: only an ID from the native catalog or a saved manual
pin/project may launch. See [catalog architecture](docs/APPS.md).

## Projects

Add a project from Projects or Settings → Projects. Each has a name, absolute
local folder, accent and ordered open actions. Choose any combination of:

| Action | Configuration |
|---|---|
| Explorer | Opens the saved folder |
| Editor | Absolute editor `.exe` and a JSON array of arguments, usually `["{path}"]` |
| Terminal | Absolute terminal `.exe` and a JSON array of saved arguments; launches in a new console with the project as working directory |
| URL | Saved `http://` or `https://` URL without credentials |

`{path}` is replaced with the saved project folder. An editor example:
`C:\Users\you\AppData\Local\Programs\Microsoft VS Code\Code.exe` with
`["{path}"]`. A terminal example is
`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` with
`["-NoExit", "-Command", "npm run dev"]`. Shell syntax works only if you
explicitly configure a shell executable and its arguments. Command-line text
can never provide a process, arguments or a URL. Actions run in order; partial
failures report how many already opened. Last-opened time updates on success.

## Config reference

One human-readable file: **`%APPDATA%\FRIDAY\island\config.json`**.
Both processes create the same schema on first run. The token is random and
private: do not publish this file or its corruption backups.

| Key | Default / meaning |
|---|---|
| `version`, `revision` | Schema `1`; revision increments on native saves |
| `pins` | `[{id,name,app_id?,path,visible}]`; at most 64, IDs unique; indexed favourites use `app_id` and empty `path`, manual favourites use `.exe`/`.lnk` `path` |
| `recent_apps` | `[{id,last_used,count}]`; up to 100 distinct app records, epoch seconds and use count |
| `projects` | `[{id,name,path,color,last_opened,actions}]`; at most 64 |
| `hotkeys.sneak` | `Ctrl+Shift+Alt+Space` |
| `hotkeys.expand` | `Ctrl+Shift+Alt+F` |
| `appearance.glow` | `#FFB347` |
| `appearance.idle_mode` | `always`, `auto-hide`, or `hover` |
| `appearance.idle_seconds` | `30`; range 5–3600 |
| `appearance.snippet` | `true`; false gives a character-only Rest |
| `connection.port` | `17321`; range 1024–65535 |
| `connection.token` | 64 lowercase hex characters, generated on first run |

Paths must be absolute local paths without traversal, UNC or device prefixes.
IDs allow letters, digits, `_` and `-`; colors use `#RRGGBB`. Config has a 1 MiB
limit. Validation failure preserves the exact file as `config.corrupt-*.json`
before writing defaults. Writes use a shared OS lock and atomic replacement.
Rust also compares the actual bytes read through an IPC-only `source_stamp`,
so stale Settings saves cannot overwrite hand edits even when revision is unchanged.
After hand edits choose Settings → Connection → Reload config, or restart the app.
Restart the bridge after changing its port. A changed token requires reconnecting.
An unknown/invalid hotkey is saved and shown as a registration error so you can fix it.
Indexed favourites are references, not arbitrary executable paths: an `app_id`
must still exist in the current native catalog to launch. Existing manual pins
and old v1 configs load without migration. Index failures appear as scan warnings;
apps without Start Menu/App Paths/Store registration can be added manually.

For isolated development, the app accepts `FRIDAY_ISLAND_CONFIG` as an absolute
config filename; the server accepts `--config <absolute path>`. Point both at
the same file. Neither override changes the normal config location.

## Build and test

From `island/`:

```powershell
npm test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
npm run tauri build -- --no-bundle
```

The executable is `island/src-tauri/target/release/friday-island.exe`.
It embeds the frontend and needs no Vite server. Installer packaging and
autostart integration are outside v1. No auto-update or telemetry is installed.

From the repository root:

```powershell
venv/Scripts/python.exe -B -m unittest discover -s tests/island -v
```

Optional Chromium integration check (uses installed Python Playwright and its
Chromium; first run `npm run dev` in `island/`):

```powershell
venv/Scripts/python.exe -B tests/island/check_browser.py
```

This uses a real isolated WebSocket bridge and mocked native calls; it never
launches configured programs or reads owner memory. The native Windows check
launches the debug executable with an isolated config and two owned test windows:

```powershell
cd island
cargo build --manifest-path src-tauri/Cargo.toml
cd ..
venv/Scripts/python.exe -B tests/island/check_native.py
```

It deliberately exercises desktop focus/hotkeys and restores the cursor afterward.
It uses temporary F23/F24 bindings to avoid existing FRIDAY shortcuts.
Add `--release --measure --online` to check the standalone executable with an
isolated real bridge and sample its connected idle CPU.

The compositor regression uses a real owned browser under the app and actual
Windows clicks/typing at the laptop's DPI:

```powershell
venv/Scripts/python.exe -B tests/island/check_transparency.py --release
```

The native catalog end-to-end check uses an isolated config and test-only local
WebView2 debug port. It opens Calculator once, closes only a new Calculator window,
and verifies offline search/launch, icons, pin/unpin, rescanning and persistence:

```powershell
venv/Scripts/python.exe -B tests/island/check_apps_native.py
```
See [validation evidence](docs/VALIDATION.md) for measured checks and remaining
manual coverage, and [the protocol](docs/PROTOCOL.md) for connection details.

## Write a plugin

Trusted plugins live in Python, with data in FRIDAY's backend. Implement the
`Plugin` protocol from `services.friday_island_server.plugins`:

```python
from services.friday_island_server.plugins import Manifest

class MyPlugin:
    manifest = Manifest("my_plugin", "My plugin", ("mycommand",), version=1)

    def snippet(self) -> str:
        return "One calm line"

    def widget(self) -> dict:
        return {"title": "My plugin", "text": "A small text widget"}

    async def command(self, text: str) -> dict:
        return {"ok": True, "text": "Done"}
```

Register an instance with `Registry.register()` in the Python bridge composition.
The manifest's wire format is `{id,name,commands,version,widget}`; `commands`
is an array of unique command prefixes and `widget` is a boolean. Set
`widget=False` for a command-only plugin; the host shows its name and commands.
Registered Python code is trusted; v1 does not load arbitrary files/packages from config.
Snippet selection uses the first nonempty registered plugin, publishing every
60 seconds. Widgets are plain text, not injected HTML or JavaScript.
Commands can return text or an action referencing an indexed app, manual pin
or project ID; Rust revalidates catalog/config membership. An `app_search` query
is resolved natively and can never supply executable paths or process arguments.

The three shipped plugins are `habit_tracker` (stub), `todo` (stub), and
`college_schedule` (real next-class adapter with a no-timetable fallback).
Plugin lists/widgets are generic: the island has no classes/habit/todo UI logic.
