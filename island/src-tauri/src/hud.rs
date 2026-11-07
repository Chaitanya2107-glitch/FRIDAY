//! HUD owns no sampler: one native visibility gate and the existing Island bridge.
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{Emitter, Manager, State};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct BootSettings {
    pub boot_animation: bool,
    pub last_boot_epoch: String,
    pub reduced_motion: bool,
}
impl Default for BootSettings {
    fn default() -> Self { Self { boot_animation: true, last_boot_epoch: String::new(), reduced_motion: false } }
}

#[derive(Clone, Default, Deserialize, Serialize)]
pub struct Settings {
    pub enabled: bool,
    pub editing: bool,
    pub layer: String,
    pub monitor: String,
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    pub opacity: f64,
    pub hide_fullscreen: bool,
    pub hide_game: bool,
    pub saver: bool,
    pub auto_saver: bool,
    pub battery_threshold: f64,
    pub widgets: std::collections::HashMap<String, bool>,
}
impl Settings {
    fn validate(&self) -> Result<(), String> {
        if !["desktop", "top"].contains(&self.layer.as_str())
            || self.monitor.is_empty() || self.monitor.len() > 128
            || !(0.2..=1.0).contains(&self.opacity)
            || !(1.0..=100.0).contains(&self.battery_threshold)
            || ![self.x, self.y, self.width, self.height].iter().all(|v| v.is_finite())
            || !(0.0..=16000.0).contains(&self.x) || !(0.0..=16000.0).contains(&self.y)
            || !(300.0..=16000.0).contains(&self.width) || !(360.0..=16000.0).contains(&self.height)
        { return Err("Invalid HUD geometry or settings".into()); }
        Ok(())
    }
}

#[derive(Clone, Default, Serialize, PartialEq)]
pub struct Status {
    pub visible: bool,
    pub editing: bool,
    pub reason: String,
    pub reduce_motion: bool,
}
#[derive(Default)]
pub struct Runtime {
    settings: Option<Settings>,
    game: bool,
    provider_fullscreen: bool,
    provider_until: Option<std::time::Instant>,
    ready: bool,
    boot_active: bool,
    boot_until: Option<std::time::Instant>,
    epochs: std::collections::HashSet<String>,
    status: Status,
    data: serde_json::Value,
    monitor_key: String,
}
pub struct Hud(pub Mutex<Runtime>);
impl Default for Hud { fn default() -> Self { Self(Mutex::new(Runtime::default())) } }

#[cfg(windows)]
pub fn install_policy(window: &tauri::WebviewWindow) -> Result<(), String> {
    use windows_sys::Win32::{Foundation::*, UI::{Shell::*, WindowsAndMessaging::*}};
    unsafe extern "system" fn policy(hwnd: HWND, message: u32, wparam: WPARAM, lparam: LPARAM, id: usize, _: usize) -> LRESULT {
        // Tao rebuilds extended styles on show/resize; preserve Alt-Tab exclusion.
        if message == WM_STYLECHANGING && wparam as i32 == GWL_EXSTYLE && lparam != 0 {
            let style = &mut *(lparam as *mut STYLESTRUCT);
            style.styleNew = (style.styleNew | WS_EX_TOOLWINDOW) & !WS_EX_APPWINDOW;
        }
        if message == WM_NCDESTROY { RemoveWindowSubclass(hwnd, Some(policy), id); }
        DefSubclassProc(hwnd, message, wparam, lparam)
    }
    unsafe {
        let hwnd = window.hwnd().map_err(|e| e.to_string())?.0 as HWND;
        if SetWindowSubclass(hwnd, Some(policy), 0xF11DA, 0) == 0 { return Err("Could not enforce HUD Alt-Tab policy".into()); }
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (GetWindowLongPtrW(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW as isize) & !(WS_EX_APPWINDOW as isize));
    }
    Ok(())
}

fn monitor(window: &tauri::WebviewWindow, name: &str) -> Result<tauri::Monitor, String> {
    let monitors = window.available_monitors().map_err(|e| e.to_string())?;
    if name != "primary" {
        if let Some(found) = monitors.into_iter().find(|m| m.name().is_some_and(|n| n == name)) { return Ok(found); }
    }
    window.primary_monitor().map_err(|e| e.to_string())?.ok_or("No primary monitor".into())
}
fn geometry(window: &tauri::WebviewWindow, settings: &Settings) -> Result<String, String> {
    let monitor = monitor(window, &settings.monitor)?;
    let scale = monitor.scale_factor();
    let (max_w, max_h) = (monitor.size().width as f64, monitor.size().height as f64);
    let (width, height) = ((settings.width * scale).min(max_w), (settings.height * scale).min(max_h));
    let (x, y) = ((settings.x * scale).min(max_w - width), (settings.y * scale).min(max_h - height));
    window.set_position(tauri::PhysicalPosition::new(monitor.position().x + x as i32, monitor.position().y + y as i32)).map_err(|e| e.to_string())?;
    window.set_size(tauri::PhysicalSize::new(width as u32, height as u32)).map_err(|e| e.to_string())?;
    Ok(format!("{:?}{:?}{}", monitor.position(), monitor.size(), scale))
}

#[tauri::command]
pub fn hud_monitors(window: tauri::WebviewWindow) -> Result<Vec<String>, String> {
    Ok(window.available_monitors().map_err(|e| e.to_string())?.iter().filter_map(|m| m.name().cloned()).collect())
}

#[tauri::command]
pub fn hud_apply(app: tauri::AppHandle, state: State<'_, Hud>, settings: Settings, game: bool, fullscreen: bool) -> Result<Status, String> {
    settings.validate()?;
    let window = app.get_webview_window("hud").ok_or("Missing HUD window")?;
    let mut runtime = state.0.lock().unwrap();
    let was_editing = runtime.settings.as_ref().is_some_and(|s| s.editing);
    // Applying slow state during an edit must not snap the user's drag back.
    if !was_editing { runtime.monitor_key = geometry(&window, &settings)?; }
    window.set_always_on_bottom(false).map_err(|e| e.to_string())?;
    window.set_always_on_top(settings.editing || settings.layer == "top").map_err(|e| e.to_string())?;
    if !settings.editing && settings.layer == "desktop" { window.set_always_on_bottom(true).map_err(|e| e.to_string())?; }
    window.set_ignore_cursor_events(!settings.editing).map_err(|e| e.to_string())?;
    window.set_resizable(settings.editing).map_err(|e| e.to_string())?;
    window.set_min_size(Some(tauri::LogicalSize::new(300.0, 360.0))).map_err(|e| e.to_string())?;
    #[cfg(windows)] crate::windows::passive(&window, !settings.editing)?;
    runtime.settings = Some(settings);
    runtime.game = game;
    runtime.provider_fullscreen = fullscreen;
    runtime.provider_until = Some(std::time::Instant::now() + std::time::Duration::from_secs(2));
    drop(runtime);
    tick(&app);
    Ok(state.0.lock().unwrap().status.clone())
}

#[tauri::command]
pub fn hud_geometry(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let window = app.get_webview_window("hud").ok_or("Missing HUD window")?;
    let monitor = window.current_monitor().map_err(|e| e.to_string())?.ok_or("No HUD monitor")?;
    let scale = monitor.scale_factor();
    let position = window.outer_position().map_err(|e| e.to_string())?;
    let size = window.inner_size().map_err(|e| e.to_string())?;
    Ok(serde_json::json!({"monitor": monitor.name(), "x": ((position.x - monitor.position().x) as f64 / scale).max(0.0),
        "y": ((position.y - monitor.position().y) as f64 / scale).max(0.0), "width": size.width as f64 / scale,
        "height": size.height as f64 / scale, "editing": false}))
}

#[tauri::command]
pub fn hud_drag(app: tauri::AppHandle, state: State<'_, Hud>, edge: Option<String>) -> Result<(), String> {
    if !state.0.lock().unwrap().settings.as_ref().is_some_and(|s| s.editing) { return Err("Enable HUD edit mode first".into()); }
    let window = app.get_webview_window("hud").ok_or("Missing HUD window")?;
    if edge.is_none() { return window.start_dragging().map_err(|e| e.to_string()); }
    #[cfg(windows)] {
        use windows_sys::Win32::UI::{Input::KeyboardAndMouse::ReleaseCapture, WindowsAndMessaging::*};
        let hit = match edge.as_deref() { Some("se") => HTBOTTOMRIGHT, Some("sw") => HTBOTTOMLEFT,
            Some("ne") => HTTOPRIGHT, Some("nw") => HTTOPLEFT, _ => return Err("Unknown resize corner".into()) };
        let hwnd = window.hwnd().map_err(|e| e.to_string())?.0 as usize;
        window.run_on_main_thread(move || unsafe {
            ReleaseCapture(); SendMessageW(hwnd as _, WM_NCLBUTTONDOWN, hit as usize, 0);
        }).map_err(|e| e.to_string())
    }
    #[cfg(not(windows))] { Err("Corner resize is currently supported on Windows".into()) }
}

#[tauri::command]
pub fn hud_data(app: tauri::AppHandle, state: State<'_, Hud>, data: serde_json::Value) -> Result<(), String> {
    if data.to_string().len() > 32768 { return Err("HUD frame too large".into()); }
    state.0.lock().unwrap().data = data.clone();
    app.emit_to("hud", "hud-data", data).map_err(|e| e.to_string())
}
#[tauri::command]
pub fn hud_finish(app: tauri::AppHandle) { let _ = app.emit_to("main", "hud-done", ()); }
#[tauri::command]
pub fn hud_ready(app: tauri::AppHandle, state: State<'_, Hud>) -> Result<(), String> {
    let runtime = state.0.lock().unwrap();
    app.emit_to("hud", "hud-status", runtime.status.clone()).map_err(|e| e.to_string())?;
    app.emit_to("hud", "hud-data", runtime.data.clone()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn boot_claim(state: State<'_, Hud>, app_state: State<'_, crate::AppState>, epoch: String) -> bool {
    let mut runtime = state.0.lock().unwrap();
    if epoch.is_empty() || epoch.len() > 128 || !runtime.epochs.insert(epoch.clone()) { return false; }
    if let Ok(mut config) = crate::config::load(&app_state.path) {
        if config.island.last_boot_epoch == epoch { return false; }
        config.island.last_boot_epoch = epoch;
        let _ = crate::config::save(&app_state.path, config);
    }
    runtime.ready = false;
    runtime.boot_active = true;
    runtime.boot_until = Some(std::time::Instant::now() + std::time::Duration::from_millis(2400));
    true
}
#[tauri::command]
pub fn boot_done(app: tauri::AppHandle, state: State<'_, Hud>) {
    let mut runtime = state.0.lock().unwrap();
    runtime.ready = true;
    runtime.boot_active = false;
    drop(runtime);
    tick(&app);
}

#[cfg(windows)]
pub fn boot_input(app: &tauri::AppHandle) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
    let state = app.state::<Hud>();
    let mut runtime = state.0.lock().unwrap();
    if !runtime.boot_active { return; }
    let expired = runtime.boot_until.is_some_and(|end| std::time::Instant::now() >= end);
    let pressed = (1..=254).any(|key| unsafe { GetAsyncKeyState(key) < 0 });
    if pressed || expired {
        runtime.boot_active = false;
        runtime.ready = true;
        let _ = app.emit_to("main", "boot-skip", ());
    }
}

pub fn tick(app: &tauri::AppHandle) {
    let state = app.state::<Hud>();
    let mut runtime = state.0.lock().unwrap();
    let Some(settings) = runtime.settings.clone() else { return; };
    let Some(window) = app.get_webview_window("hud") else { return; };
    #[cfg(windows)] let (locked, fullscreen) = visibility();
    #[cfg(not(windows))] let (locked, fullscreen) = (false, false);
    #[cfg(windows)] let reduced = crate::windows::reduce_motion();
    #[cfg(not(windows))] let reduced = false;
    let provider_fullscreen = runtime.provider_fullscreen && runtime.provider_until.is_some_and(|end| std::time::Instant::now() < end);
    let reason = if !settings.enabled { "off" } else if locked { "locked" }
        else if settings.hide_game && runtime.game { "game" }
        else if settings.hide_fullscreen && (fullscreen || provider_fullscreen) { "fullscreen" }
        else if !runtime.ready { "boot" } else { "" };
    let next = Status { visible: reason.is_empty(), editing: settings.editing, reason: reason.into(), reduce_motion: reduced };
    if next != runtime.status {
        if next.visible { let _ = window.show(); } else { let _ = window.hide(); }
        runtime.status = next.clone();
        let _ = app.emit("hud-status", next);
    }
    if !settings.editing {
        if let Ok(m) = monitor(&window, &settings.monitor) {
            let key = format!("{:?}{:?}{}", m.position(), m.size(), m.scale_factor());
            if key != runtime.monitor_key { if let Ok(key) = geometry(&window, &settings) { runtime.monitor_key = key; } }
        }
    }
}

#[cfg(windows)]
pub(crate) fn visibility() -> (bool, bool) {
    use windows_sys::Win32::{Foundation::*, Graphics::Gdi::*, System::StationsAndDesktops::*, UI::WindowsAndMessaging::*};
    unsafe {
        let desktop = OpenInputDesktop(0, 0, DESKTOP_READOBJECTS);
        if desktop.is_null() { return (true, false); }
        let mut name = [0u16; 128];
        let mut needed = 0;
        let ok = GetUserObjectInformationW(desktop, UOI_NAME, name.as_mut_ptr() as _, 256, &mut needed);
        CloseDesktop(desktop);
        let locked = ok == 0 || String::from_utf16_lossy(&name[..name.iter().position(|c| *c == 0).unwrap_or(0)]) != "Default";
        let hwnd = GetForegroundWindow();
        if locked || hwnd.is_null() || IsIconic(hwnd) != 0 { return (locked, false); }
        let mut pid = 0;
        GetWindowThreadProcessId(hwnd, &mut pid);
        if pid == std::process::id() { return (locked, false); }
        let mut class = [0u16; 128];
        let length = GetClassNameW(hwnd, class.as_mut_ptr(), 128);
        let class = String::from_utf16_lossy(&class[..length.max(0) as usize]);
        if ["Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"].contains(&class.as_str()) { return (locked, false); }
        let mut info: MONITORINFO = std::mem::zeroed();
        info.cbSize = std::mem::size_of::<MONITORINFO>() as u32;
        let mut rect: RECT = std::mem::zeroed();
        let fullscreen = GetWindowRect(hwnd, &mut rect) != 0
            && GetMonitorInfoW(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &mut info) != 0
            && rect.left <= info.rcMonitor.left + 1 && rect.top <= info.rcMonitor.top + 1
            && rect.right >= info.rcMonitor.right - 1 && rect.bottom >= info.rcMonitor.bottom - 1;
        (locked, fullscreen)
    }
}
