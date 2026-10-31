# FRIDAY Island v1 validation

## Installed-app launching follow-up

The window fix was committed first as `689b48e`; the native catalog followed in
`f59fe82`. Installed-app launching replaces the initial configured-app-only rule.
Pins now select favourites; the native catalog independently authorizes installed
apps online and offline.

Current checks:

The exact current source/build binding is in [update-validation.json](update-validation.json).

- **Python:** 10 passed, including additive indexed-favourite/recents validation
  and native search delegation; existing protocol/config failure paths remain covered.
- **Rust:** 7 passed, plus the explicitly invoked live-metadata test. Coverage
  includes App Paths quoting/traversal/command rejection, bounded shortcut
  traversal, stable IDs, fuzzy and recent ranking, and refusal of non-indexed IDs.
- **Frontend:** 5 passed, plus real Chromium/Python integration. Added regressions
  cover duplicate-name Tab identity, stale favourites rows after unpin, native
  suggestions arriving while Python is delayed, plugin command priority, offline
  search/launch, inline pin/unpin, and No app found → Rescan.
- **Real native release:** `check_apps_native.py` found **313 deduplicated apps**,
  with **no scan warnings**. A Store icon returned PNG; an unpinned Calculator
  launched offline; arbitrary executable text was rejected as an app ID. Pins
  and recent history survived a real app restart, and manual rescanning succeeded.
- **Builds:** TypeScript/Vite and standalone Windows release passed. The native
  test-only CDP port is supplied through the test child's environment; it is not
  configured in the shipped app.

The compositor/browser-input and native focus/bridge suites were rerun after
adding installed-app launching, preserving the transparency regression coverage.
The final browser fixture waits for its known-color page to be physically
composed, verifies the browser PID/Windows hit target, then sends actual OS
clicks and keystrokes. This avoids false input failures from other Chrome windows
while retaining the real compositor and hit-testing assertions.

### Exact manual checks for this update

1. Launch the release. Leave a browser under the top-center region: click and
   type below Rest, hover Peek, expand Projects/Settings, enter Sneak and press
   Esc. Verify no grey canvas, appropriate small window bounds and preserved focus.
2. With the Python bridge stopped, type `open <an installed app you have never
   pinned>` in Peek and Sneak. Try a short fuzzy name and a bare app name; select
   with arrows/Enter and with Tab/Enter. Check icons/source labels and the right app.
3. Pin an app in suggestions, then unpin it. Verify it still launches. In Settings
   → Pinned apps, pin from the installed list, rename/reorder favourites and restart.
4. Launch two similarly named apps; search again and check recent ranking without
   overriding an exact name. Restart and verify recent history remains.
5. Search a nonexistent name, click Rescan apps, and try Settings → Pinned apps →
   Rescan apps after installing/uninstalling an app. No typed path or appended
   shell arguments should execute. Try the retained manual `.exe`/`.lnk` picker.
6. Repeat on another DPI/resolution if available. Automated compositor/input and
   native focus tests ran at the laptop's actual **125% scaling**; physically
   changing display settings or testing a separate Windows 10 machine remains manual.

## Transparency regression fix

The original v1 native-acrylic/fixed-canvas approach below is superseded.
Whole-window vibrancy was removed, both backgrounds use zero alpha, and the
native window follows the measured DOM island bounds. Intrinsic layout limits
are independent of viewport size so resizing cannot repeatedly shrink the UI.
Width and card-height transitions drive the native resize without activation.

`check_transparency.py --release` uses an owned, headed Chromium window beneath
the real island. At **120 DPI / 125% scaling**, real Windows clicks/typing reached
its input under the old empty canvas, and desktop pixels outside the pill were
byte-for-byte unchanged. Measured physical window sizes: Rest **373×69**, Peek
**888×92**, Expanded **888×452**, Sneak **800×99**. Sneak centers its actual box;
other states retain the top-center anchor. Native rounded regions exclude empty
gutters. Run the regression with:

```powershell
venv/Scripts/python.exe -B tests/island/check_transparency.py --release
```

The historical CPU measurements and old native-acrylic assertions below describe
the initial v1 build, not this corrected window implementation.

Validated locally on **Windows, 120 DPI (125% scaling)** with Python 3.12.8,
Node 24.18.0, Rust 1.98.1 and Edge WebView2. No existing FRIDAY source was changed.
Pre-existing unrelated working changes were preserved. The work is in isolated
feature commits; no push, deployment, installer or autostart change was performed.

## Automated checks

| Check | Result |
|---|---|
| Python unit/integration suite | 9 passed: config, partial-config token stability, locking, corruption backup, parsing, ambiguity, authentication, malformed messages and failure recovery |
| Rust suite | 4 passed: config validation/revisions/content stamps/backups/token materialization, hotkey parsing, rejection of unconfigured launches |
| Frontend suite | 5 passed: four-state transitions, hidden behavior, offline suggestions, connection replacement/disconnect without command replay |
| Real Chromium + Python bridge | Passed: all states, non-activating hover requests, plugin widget, Tab/Enter regression, app add/remove/drag reorder, project add/reorder, offline settings, server restart/reconnect, reduced motion |
| Windows debug executable | Passed: native styles, focus, global shortcuts, states, rounded hit regions |
| Standalone Windows release, Vite stopped | Passed: same native checks and connected WebSocket handshake/`next` command |
| TypeScript/Vite production build | Passed; approximately 25.9 kB JS + 12.5 kB CSS before gzip |
| Tauri release build | Passed; standalone x64 executable approximately 3.4 MB |
| npm dependency audit | 0 reported vulnerabilities |

Python's invalid-origin test intentionally elicits a WebSocket rejection log;
the test passes. No live provider, desktop automation, owner memory modification
or configured application/project launch is used by these tests.

Native foreground checks use two owned Windows test windows, including:

- Starting and hovering the island leaves the existing foreground window focused.
- The window is frameless, topmost, a tool window and non-activating at rest.
- The empty canvas and transparent rounded corners are excluded from its region.
- First deliberate expand focuses Peek; second opens Expanded.
- Esc restores the prior app; passive Esc closes hover-opened Peek.
- Sneak is centered, focuses deliberately, and uses the same bridge command engine.
- Selecting another window while Sneak is open keeps that newly selected app focused.

The requested default expand shortcut is already registered by FRIDAY's existing
taskbar flyout. This conflict is detected and reported. Native smoke tests use
temporary Ctrl+Shift+Alt+F23/F24 so they do not interfere with it.

## Measured rendering cost

Source manifests, immutable source ZIPs and executable SHA-256s are recorded
with the native checks under ignored `tasks/island-native-*` folders. A portable
summary is in [validation.json](validation.json).

Each sample covers five seconds after an additional five-second warm-up,
summing CPU time across the Island and six WebView2 child processes. Values
are **percent of one CPU core**, not whole-machine utilization.
This laptop has 24 logical processors; 7.81% of one core is approximately 0.33%
of their combined capacity.

| Build/state | CPU sample |
|---|---:|
| Original SVG/CSS animation + duplicate CSS blur, offline Rest | 62.81% |
| Final release, offline Rest | 0.94% |
| Final release, connected Rest with breathing/blinking | 7.81% |

The optimization moves breathing to the SVG's compositor-friendly outer element,
uses subtle discrete steps, pauses offline animation and removes CSS backdrop
blur that duplicated native acrylic. No extra dependency or launch authority was
added. Earlier samples were 0.00% offline and 1.25% connected; short samples vary
with WebView startup, blinking and the desktop behind the window. The table uses
the final executable's source-bound measurements. This is a short local sample,
not a battery-life or long-duration guarantee.

## Remaining manual coverage

Monitor/resolution/DPI changes are handled by primary-monitor geometry polling
and native scale conversion; physically changing display settings/hot-plugging
was not performed. Native focus/click-through checks ran at the laptop's actual
125% scaling. Windows 10 and unsupported-acrylic fallback were not exercised on
separate hardware. Reduced motion was checked in Chromium and the native shell
reads Windows' setting, without changing the owner's OS preferences.

Native app/shortcut icon extraction and file pickers compile against Windows APIs;
full app launches, terminal actions and URL launches are deliberately left for
the owner to try with their chosen configuration. The unit tests enforce the
configured-ID boundary. College's existing next-occurrence function is reused;
the automated bridge tests inject a timetable fixture to avoid owner data.

## What to try

1. Start the Python bridge and `npm run tauri dev` using the README commands.
2. Hover at the top center; verify your editor keeps focus. Open Settings →
   Hotkeys and change Expand to an unused binding on this laptop.
3. Add an app, rename it, hide/show it, drag it and restart the island to check persistence.
4. Add a project folder; start with Explorer only, then configure an editor or terminal.
5. Type `proj <name>`, use ↑/↓ and Tab, then try the same command in Sneak.
6. Stop/restart the bridge; check that local launches still work and the
   connected character/snippet return automatically.
7. Try auto-hide, character-only Rest and your own glow color.
