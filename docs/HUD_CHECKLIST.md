# HUD native manual checks

Use a release build with all seven widgets enabled. Supply optional schedule and
activity services and start a focus session for the complete layout. Record OS,
monitor arrangement, DPI, executable hash and pass/fail evidence.

- [ ] `hud on`: click desktop icons and applications underneath each tile.
- [ ] `hud edit`: drag the header and resize each corner. `hud done`: position
  survives restart; clicks pass through; HUD never appears in Alt-Tab/taskbar.
- [ ] Desktop layer: above wallpaper, behind applications. Test Win+D twice,
  minimize/restore, Explorer restart and virtual desktop switching.
- [ ] Top layer: reduced opacity; no activation or keyboard theft.
- [ ] Fullscreen game/video on each monitor: hides within two seconds, no stats
  requests while hidden, restores afterward. Repeat with activity paused.
- [ ] Win+L: absent while locked and on the secure desktop; restores on unlock.
- [ ] Start/end a `game` scene: hides/restores. Repeat with suppression disabled.
- [ ] Two monitors: select each, drag between displays and save. Unplug the
  selected monitor, verify primary fallback, then reconnect.
- [ ] 100% and 150% scaling: sharp text/rings; correct geometry, drag, resize,
  click-through; class/focus/activity fit without clipping on each monitor.
- [ ] Reduced motion: simple startup fade; no class pulse or HUD animation.
- [ ] Saver on/off: five-second/one-second readings, static animations in saver.
  Unplug below threshold, plug in again, and test missing battery and manual saver.
- [ ] Boot: ring sweep, Mochi eyes open, optional name + “Online and ready”, HUD
  fade. Skip using a click/key in another application. Showing/reloading Island
  does not replay; restarting FRIDAY produces one new sequence.
- [ ] Missing schedule/activity service hides its tile; no app names appear.
- [ ] Reserve the hotkey in another app: clear error in Island and Hotkeys settings.
- [ ] Warm 12 seconds and measure at least 35 seconds, no build running. All widgets
  populated, foreground input idle. CPU <2% machine-normalized, incremental
  private working set <100 MiB; also record core CPU, RSS and total memory.
