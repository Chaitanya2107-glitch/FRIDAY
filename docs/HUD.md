# FRIDAY HUD

Build the Island release and start FRIDAY normally. The existing plugin host
discovers `plugins/hud`; no new packages are required. Nothing is pushed.

```
hud on
hud off
hud edit
hud done
hud layer desktop
hud layer top
hud saver on
hud saver off
```

Ctrl+Shift+Alt+H toggles the HUD; change it in Settings → Hotkeys. Registration
errors appear in Island and the Hotkeys panel. Settings → HUD controls widgets,
monitor, logical position/size, opacity, fullscreen/game hiding and battery saver.
In edit mode drag the header or a corner, then select Done or say `hud done`.
Edit mode is session-only, so a crash cannot leave a clickable HUD on restart.
Disconnected monitors fall back to primary; geometry is clamped on-screen.

HUD settings are the `hud` object in `%APPDATA%/FRIDAY/plugins/hud/settings.json`.
The initial layer is `desktop`; top mode uses opacity 0.82. Automatic saver
starts when unplugged below 30%, updates every five seconds and disables HUD
animations. Manual saver off leaves automatic low-battery saver enabled.
No battery means no automatic saver. Fullscreen and locked/secure desktops are
checked natively about once per second, including while the HUD is hidden.
Activity fullscreen hints expire after two seconds so stale tracking cannot
prevent restoration. A `game` scene also hides the HUD by default.

The `hud` Tauri window is transparent, borderless, skip-taskbar and a Windows
toolwindow with no activation; click-through uses native ignore-cursor-events.
Desktop mode tries Tauri's persistent always-on-bottom handling, which enforces
`HWND_BOTTOM` during `WM_WINDOWPOSCHANGING`. There is no WorkerW reparenting or
wallpaper modification. Native verification results and any fallback are recorded
in `tasks/hud/native-receipt.json` and the final report.
References: [Tauri window API](https://docs.rs/tauri/latest/tauri/webview/struct.WebviewWindowBuilder.html),
[Microsoft SetWindowPos](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setwindowpos).

The 2.1-second boot sequence uses the authenticated full backend epoch, persisted
as `island.last_boot_epoch` in the existing Island config. Showing/reloading
Island or reconnecting to that backend does not replay it. Click or press any key
to skip, including outside the passive Island. Reduced motion uses a fade;
there is no sound. `island.boot_animation` defaults to true; `user_name` customizes
the greeting. Both are in Settings → Look. A standalone bridge without a full
backend does not announce a FRIDAY startup.

## Routes and data

All routes use the existing bridge token, localhost Host, approved Origin and
loopback-peer protection. Clients send `X-Friday-Token`; it never enters a URL.

`GET /api/plugins/hud/stats` returns:

```typescript
interface Stats {
  sampled_at: number;                  // Unix seconds
  cpu_percent: number | null;          // 0..100, whole machine
  ram: {percent: number; used_bytes: number; total_bytes: number} | null;
  battery: {percent: number | null; plugged: boolean; charging: boolean} | null;
  gpu: {percent: number} | null;        // 0..100
  network: {upload_bps: number; download_bps: number} | null; // bytes/second
}
```

One locked sampler caches the entire response for one second across HTTP worker
threads. CPU/network use nonblocking cumulative deltas; the first delta reading
is null. Unsupported hardware is null. GPU uses the installed NVIDIA NVML driver
directly, without repeated `nvidia-smi` processes. Other GPU drivers have no
reader and their ring is hidden. No hardware readings are published as events.

The main Island's existing bridge/SSE connection forwards native frames to the
small HUD WebView. There is no second bridge connection or animation frame loop.
Visible stats update each second, saver each five seconds. Hiding aborts the
request and cancels polling; network history holds at most 40 pairs.

`GET /api/plugins/hud/state` returns `settings`, `scene`, `game`, `fullscreen`,
`focus`, `next_class`, and `activity`. Slow data refreshes on events and every
30 seconds while visible. `POST /api/plugins/hud/actions/settings` accepts partial
settings and rejects unknown keys, invalid types, and out-of-range values.

- Schedule adapter: `get_service('schedule').next_class()` returns null or a dict
  with `subject`, `faculty`, `room`, and ISO-8601 `starts_at`. This is an explicit
  assumption: no schedule plugin currently provides a service in the repository.
  The class card is hidden when it is absent; legacy timetable data is preserved.
- Focus uses official `focus.started`, `focus.paused`, `focus.done` events and
  wall-clock deadlines, with no accumulated timer drift.
- Scene uses official scene events, falling back to the legacy runtime mode.
- Activity uses `get_service('activity').summary('today')`, projected to category
  names and seconds only and cached 30 seconds. App names/titles never cross the
  HUD route. The strip is hidden if the service is absent.
- `hud.changed` carries occasional settings/control changes. `hud.state_changed`
  notifies after focus/scene reduction commits, preventing consumer races.
  Neither topic carries system statistics.

## Tests and native measurement

From the repository root:

```powershell
venv/Scripts/python.exe -B -m pytest tests/test_hud.py tests/test_event_bus.py tests/test_plugin_system.py tests/test_plugin_bridge.py tests/test_island_runtime.py -q
Set-Location island
npm.cmd test
npm.cmd run build
Set-Location src-tauri
cargo test --offline
```

Build and run the Windows release probe, starting at repository root:

```powershell
Set-Location island
npm.cmd run tauri -- build --no-bundle -- --offline
Set-Location ..
venv/Scripts/python.exe -B tests/island/check_hud_native.py --seconds 35
```

The probe uses owned windows, temporary settings/token and a local authenticated
bridge. System readings are real; optional class/focus/activity content is a test
fixture so every widget is populated. Island is temporarily restarted and the
current release restored afterward. It does not lock the owner session or change
display scaling. Screenshots and resource receipts are under `tasks/hud/`.
CPU records both percent of one logical core and machine-normalized Windows Task
Manager percent (the 2% budget). Memory includes Island and every WebView2 child.
The memory budget uses incremental private working set. Backend CPU/memory deltas
are recorded separately. RSS can count shared pages more than once; private
working set and commit are also reported.

See [HUD_CHECKLIST.md](HUD_CHECKLIST.md) for hardware checks that cannot be faked.
