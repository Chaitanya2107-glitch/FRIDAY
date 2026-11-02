# FRIDAY Island v1 validation

## Automatic startup and bridge recovery — 2026-11-02

The island now starts its fixed Python bridge when needed, reuses an occupied
port without stopping its owner, and restarts an exited owned child with bounded
backoff. Only the authenticated frontend connection is reported as FRIDAY online.
The separate Windows sign-in option remains opt-in. This supersedes earlier
instructions requiring a manually started bridge and the earlier autostart exclusion.

Focused checks:

- **Rust: 10 passed, 1 opt-in discovery test ignored.** Includes startup argument
  quoting, invalid backend-folder handling and capped retry delay; existing config,
  app-launch boundary, hotkey and battery/media tests also passed.
- **Python: 19 passed.** New startup preferences survive shared-config roundtrips,
  default sign-in is off, and invalid backend paths are rejected.
- **Frontend: 8 passed.** Existing state/connection/widget checks remain green.
  Chromium integration also exercised Settings → Connection: no sign-in mutation
  before a click, explicit enable/disable calls, and the existing tracker/media flows.
- **Native lifecycle fixture passed.** It uses a temporary Python venv launcher
  and fake local bridge, never the owner's database. It verifies auto-start,
  crash recovery, explicit restart, hand-edited-port reload, recovery from a missing
  backend folder, disable stopping only owned processes, reuse of an external
  server, passive duplicate `--background` launches, and hard-exit cleanup.
  Cleanup checks both captured descendants and the released listening port.
- The real `FRIDAYIsland` sign-in registry value remained byte-for-byte unchanged
  through the fixture. Isolated-config registration is rejected. Registration from
  a debug build is also rejected, since it would require Vite at sign-in.
- **Native focus regression passed at 120 DPI / 125%.** Startup and hover remain
  passive, explicit input focus and Esc restoration work, and the four states
  retain their compact regions. The lifecycle fixture also checks actual owned
  Python startup preserves the foreground app. The test harness handles Windows'
  initial foreground lock only when activating its own fixture windows.
- The extra compositor-pixel regression was attempted, but its owned browser
  fixture could not be made visible on the physical desktop **before Island was
  launched**. No new compositor/pixel-pass claim is made for this build. Native
  rounded-region/click-area checks passed; physical pixel verification remains
  manual. The window's transparency and geometry code were unchanged in this step.

The exact release/source hashes are recorded in
[startup-validation.json](startup-validation.json); native source capture and the
lifecycle fixture's results live under ignored `tasks/island-native-release` and
`tasks/island-startup-native`. The native supervisor milestone is `b378c52`.

Python starts suspended, enters its Windows Job Object, and only then resumes.
This prevents the venv launcher creating an unowned Python child before job
assignment. The job terminates owned descendants even if Island itself is killed.
No external FRIDAY server is attached to that job or stopped by a restart request.
The implementation uses the existing Windows crates, without adding a new package.

Run `tests/island/check_startup_native.py` with the normal Island closed. The
fixture enables supervision explicitly via `FRIDAY_ISLAND_MANAGE_BRIDGE=1`; other
isolated-config native checks continue to suppress automatic Python startup.
Detailed fixture evidence is under ignored `tasks/island-startup-native/`.

Try manually: close/reopen the standalone island and check Connection status;
use Restart managed bridge when it owns the server. To opt into actual Windows
sign-in launch, enable the toggle from the standalone release, then sign out/in
when convenient. Actual sign-out/in, Windows Startup Apps overrides, separate
Windows 10 hardware, and deliberately hanging a still-running Python process
remain manual coverage; recovery tests cover exited processes and startup deadlines.

## Live todos, habits and timed class reminders — 2026-10-31

The tracker placeholders have been replaced with adapters for FRIDAY's shared
productivity store. The date slot now accepts only a currently valid reminder
interval and restores the date at expiry, disconnect or an empty update. This
supersedes the hidden-timetable statement in the earlier capsule section below.
Source/build hashes are in [plugin-validation.json](plugin-validation.json).

- **Python: 18 passed.** Real temporary SQLite stores cover shared persistence,
  streaks, check/undo, stale revisions, wrong dates, task-plan protection, unknown
  actions, input limits, authenticated widget writes and grammar whitespace.
  List commands include records beyond the six visible widget rows.
- **Frontend: 8 passed.** State/connection tests cover active reminder intervals,
  exact expiry, malformed mutation acknowledgements and bounded widget payloads.
- **Chromium integration passed.** Real authenticated bridge and temporary store:
  add/complete todos, add/check/undo habits, literal HTML-like labels, preserved
  drafts/focus, external-edit conflicts, delayed-save navigation without duplicate
  adds, future/missing/expired reminder rejection, and restoring date offline.
  Existing app search, pins, reorder, media and four-state checks also passed.
- **Standalone Tauri release passed at 125% scaling.** Real WebView2 forms wrote
  only an isolated tracker database; a new store instance confirmed persistence.
  A near-class reminder replaced the date and clearing it restored the date.
  The test is `tests/island/check_plugins_native.py`; its inspection port exists
  only in the test child, and all fixture records live in a temporary directory.
- **Native focus/transparency regressions passed.** Hover stays passive, deliberate
  input focus and Esc restoration work, all four native sizes remain compact,
  desktop pixels outside the capsule are unchanged, and real typing reaches the
  browser underneath. The Windows native shell itself was unchanged in this step.
- **Normal bridge verified.** A read-only authenticated request against the real
  shared config confirmed both tracker widgets are available. No demo records
  were added to the owner's database. The bridge was restarted with the new code.

Backend milestone `efc214e` and widget milestone `153190b` were followed by the
owner's integration commit `5e620aa`, which contains the final tested code and
shared-store prerequisites. The source snapshot still matches the release build.
README and protocol documents describe the new commands and generic action schema.

Try manually:

1. Open Expanded → Plugins. Add your own task and habit, complete/check them,
   reopen the app, and confirm the same records in FRIDAY's Habits & To-do desktop.
2. Try `todo buy charger`, `todo list`, `todo done <full name or #ID>`,
   `habit add Read 20 pages`, `habit check Read 20 pages`, and `habit undo Read 20 pages`
   in Peek and Sneak. These deliberately change your real saved data.
3. Within 15 minutes before a real class, check the date-slot reminder. At class
   start it must return to the date; far-future classes stay out of Rest. Toggle
   Appearance → Near-class reminders to disable it.

Separate Windows 10 hardware, a live display-scale change and waiting for an
actual owner class remain manual coverage; class timing was exercised with an
injected clock and a real native fixture. No installer, autostart or publication
change was made.

## Clock, battery and media capsule — 2026-10-31

Rest now uses a 360px capsule: 12-hour clock/weekday left, orb at the geometric
center, date/battery right. A 38px song strip appears only for a Windows media
session that is playing or paused. Plugin/timetable text remains hidden.
This section supersedes the earlier Rest sizes and character-only behavior.

The source/executable hashes and check commands are recorded in
[capsule-validation.json](capsule-validation.json). Native integration was
committed separately as `9860cf8`. No existing Python assistant module changed.

- **Build:** TypeScript/Vite and standalone Tauri release passed offline, using
  additional features of the existing Windows crate; no new package was added.
- **Rust:** 9 passed; the pre-existing live app-discovery test stays opt-in.
  Battery tests distinguish charging, missing batteries, unknown readings and 0%.
  Media commands accept only previous/toggle/next.
- **Frontend:** 5 unit tests passed. Chromium at 150% pixel scale checked exact orb
  centering, midnight/noon AM/PM, date rollover, battery unknown/missing states,
  direct Rest media clicks without expansion, safe literal song metadata,
  capability-disabled controls, Sneak polling pause, and existing command flows.
- **Real Windows, 120 DPI / 125%:** a local silent Chromium fixture supplied a
  real SMTC session. Title/artist, play/pause/previous/next and battery matched
  Windows. Real mouse clicks preserved the foreground application; invalid
  actions and a different player source were rejected before any control fired.
- **Native regression:** all four states, hover, hotkeys, rounded hit regions,
  focus restoration and centered Sneak passed. Compositor pixels outside the
  capsule remained unchanged and real mouse/keyboard input reached the browser
  underneath. Rest measured 475×82 physical pixels without active media.
- **Idle cost:** offline Rest across the Island and six WebView2 processes used
  0.94% of one CPU core over five seconds after a five-second warm-up. This is a
  short sample, not a battery-life estimate. Clock updates once per minute;
  battery/media poll about every two seconds, paused in Hidden/Sneak.

Run `tests/island/check_capsule_native.py` against the release build with the
normal Island closed. It creates only its own local silent player, isolated
config and temporary WebView2 inspection port; it never controls an owner player.
The ordinary app has no inspection port. Full captures are under the ignored
`tasks/island-capsule-native`, `tasks/island-native-release` and
`tasks/island-transparency` directories.

Manual follow-up: play a song in your usual Windows-media-aware player/browser;
check title changes, pause/resume and track skipping while typing elsewhere.
Plug/unplug the charger and check the charging indicator. Separate Windows 10
hardware and changing display scale while running remain manual coverage.

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
