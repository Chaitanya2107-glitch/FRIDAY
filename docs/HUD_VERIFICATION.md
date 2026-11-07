# HUD verification — 7 November 2026

All widgets were enabled and populated, including GPU, class, focus and activity.
System figures came from real psutil/NVML readings; the optional schedule,
focus and category content came from the isolated native test fixture.

Windows 11 build 26300; 24 logical CPUs; one monitor at 125% scaling.
Release WebView2 build, 12-second warmup, approximately 35.7 seconds per sample.
The baseline executable was preserved before the HUD change. Both runs used the
same authenticated loopback fixture and their complete Island/WebView2 trees.

| Measurement | Baseline | Island + all HUD widgets |
| --- | ---: | ---: |
| UI CPU, Windows machine percentage | 0.336% | 0.607% |
| UI CPU, one logical core percentage | 8.07% | 14.57% |
| UI private working set, median | 96.1 MiB | 153.3 MiB |
| UI RSS, summed process working sets | 395.8 MiB | 517.6 MiB |
| UI private commit | 178.7 MiB | 301.5 MiB |

Including the incremental backend sampling CPU, total HUD + Island idle CPU was
**0.622% of the machine** (14.92% of one logical core). Including plugin startup
allocation and the backend's resident-memory increase, additional private
working set was **78.1 MiB**. Both Windows Task Manager style budgets pass.
This is incremental memory; the complete UI occupies 153.3 MiB private resident
memory. Summed RSS increases by 145.9 MiB including the backend. RSS counts shared
WebView2/DLL pages repeatedly across processes and is not the private-memory
budget. Private commit is also disclosed above rather than equated with resident
memory. A single-core CPU budget of 2% would not pass on this machine.

The exact executable SHA-256 is
`90c2276aa26fb3d1fa80692b2fe7645eee8dd10daf424a7797b258d69b849045`.
Raw per-second readings, backend deltas and source hashes are retained in
`tasks/hud/native-receipt.json`. The test fails when machine CPU reaches 2% or
additional private working set reaches 100 MiB. `tasks/hud/hud.png` is the native
WebView2 screenshot of the populated layout.

Passed native checks:

- Native transparent click-through and hit testing over another window.
- Toolwindow/noactivate/taskbar styles, including preservation after Tao style
  rebuilds. The initial one-off TOOLWINDOW flag was lost on show; a narrow
  WM_STYLECHANGING subclass now preserves it. No focus policy is weakened.
- Drag/edit mode accepts input; Done persists changed geometry and restores
  click-through. The all-widget layout fits without clipping.
- Desktop layering: HUD was immediately above the visible Progman wallpaper
  window and behind ordinary windows. Tauri's persistent HWND_BOTTOM strategy
  succeeded, so desktop remains the default. No WorkerW parenting or wallpaper
  modification was needed.
- Fullscreen suppression, zero stats requests while hidden, restoration, game
  scene suppression/restoration, and on/off commands.
- Manual saver switched to five-second polling; unit tests cover automatic
  unplugged/below-threshold selection. GPU readings use installed NVML directly.
- Boot sweep and Mochi eye-animation styles, key skip, no replay on showing or
  reloading Island with the same backend epoch.

Targeted checks passed: 42 backend tests, 29 frontend tests, 12 Rust tests
(one existing live installed-app test is intentionally ignored), TypeScript/Vite
build and native release build. A separate, broader mood suite encountered
`ModuleNotFoundError: plugins.mood.focus` while unrelated mood work changed in
the shared workspace; it is outside the HUD test set and was not represented as
a passing full-repository run.

Hardware checks still required: real lock/unlock and secure desktop, Windows 10,
two monitors/disconnect/reconnect, 100% and 150% scaling, and the OS reduced-motion
switch. The native probe does not lock the owner's session or alter display
settings. See [HUD_CHECKLIST.md](HUD_CHECKLIST.md).

The schedule adapter assumes `get_service('schedule').next_class()` returns an
ISO-8601 `starts_at` plus subject/faculty/room. No schedule service is installed,
so that card hides in the normal app. The focus ring consumes the official focus
events; this task does not add a focus-session producer. Unsupported GPU drivers
produce null rather than a simulated reading.

No commit, push, merge, or external publication was performed. Existing and newer
Mochi changes in the workspace were preserved.

## Files in this change

Added:

- `plugins/hud/plugin.json`, `main.py`, `stats.py`, `gpu.py`.
- `island/hud.html`, `island/src/hud.ts`, `hud.css`, `hud-model.ts`,
  `hud-controller.ts`, `hud-settings.ts`, `boot.ts`, `boot.css`.
- `island/src-tauri/src/hud.rs`.
- `tests/test_hud.py`, `tests/island/check_hud_native.py`,
  `tests/island/hud_fixture.py`, `island/tests/hud.test.ts`.
- `docs/HUD.md`, `docs/HUD_CHECKLIST.md`, `docs/HUD_VERIFICATION.md`,
  `docs/specs/2026-11-06-hud.md`.
- Ignored local artifacts: `tasks/hud/measure.py`, policy, source/resource receipts,
  preserved baseline binary, native screenshots and logs.

Changed for integration:

- `island/src-tauri/tauri.conf.json`, `Cargo.toml`, `capabilities/main.json`,
  `src/main.rs`, `src/config.rs`, `src/windows.rs`.
- `island/src/main.ts`, `connection.ts`, `native.ts`, `types.ts`, `settings.ts`;
  `island/vite.config.ts`.
- `services/friday_island_server/config.py`, `docs/PLUGINS.md`, `docs/EVENTS.md`.

Other workspace changes, including the newer Mochi implementation, are not
claimed as HUD edits.
