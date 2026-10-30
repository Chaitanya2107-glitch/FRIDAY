//! Windows policy: no activation unless explicitly requested; no invisible hit area.
use crate::config::Hotkeys;
use serde::{Deserialize, Serialize};
use std::{mem::zeroed, ptr::null_mut};
use tauri::{Emitter, Manager, WebviewWindow};
use windows_sys::Win32::{
    Foundation::*, Graphics::Gdi::*,
    UI::{Input::KeyboardAndMouse::*, WindowsAndMessaging::*},
};

#[derive(Clone, Deserialize)]
pub struct HitRect { pub x: f64, pub y: f64, pub width: f64, pub height: f64, pub radius: f64, #[serde(default)] pub top_square: bool }
#[derive(Clone, Serialize)]
pub struct Pointer { x: f64, y: f64, reveal: bool }

pub fn passive(window: &WebviewWindow, enabled: bool) -> Result<(), String> {
    window.set_focusable(!enabled).map_err(|e| e.to_string())?;
    unsafe {
        let hwnd = window.hwnd().map_err(|e| e.to_string())?.0 as HWND;
        let style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, if enabled { style | WS_EX_NOACTIVATE as isize | WS_EX_TOOLWINDOW as isize }
            else { (style & !(WS_EX_NOACTIVATE as isize)) | WS_EX_TOOLWINDOW as isize });
    }
    Ok(())
}

pub fn foreground() -> usize { unsafe { GetForegroundWindow() as usize } }
pub fn restore(hwnd: usize) { unsafe { if hwnd != 0 && IsWindow(hwnd as HWND) != 0 { SetForegroundWindow(hwnd as HWND); } } }

pub fn regions(window: &WebviewWindow, rects: Vec<HitRect>) -> Result<(), String> {
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    unsafe {
        let hwnd = window.hwnd().map_err(|e| e.to_string())?.0 as HWND;
        let union = CreateRectRgn(0, 0, 0, 0);
        if union.is_null() { return Err("Could not create window region".into()); }
        for r in rects.iter().take(16) {
            if ![r.x, r.y, r.width, r.height, r.radius].iter().all(|n| n.is_finite())
                || r.width <= 0.0 || r.height <= 0.0 { continue; }
            let region = CreateRoundRectRgn((r.x * scale).floor() as i32, (r.y * scale).floor() as i32,
                ((r.x + r.width) * scale).ceil() as i32 + 1, ((r.y + r.height) * scale).ceil() as i32 + 1,
                (r.radius * scale * 2.0) as i32, (r.radius * scale * 2.0) as i32);
            if !region.is_null() {
                if r.top_square {
                    let top = CreateRectRgn((r.x * scale).floor() as i32, (r.y * scale).floor() as i32,
                        ((r.x + r.width) * scale).ceil() as i32, ((r.y + r.radius) * scale).ceil() as i32);
                    if !top.is_null() { CombineRgn(region, region, top, RGN_OR); DeleteObject(top); }
                }
                CombineRgn(union, union, region, RGN_OR); DeleteObject(region);
            }
        }
        if SetWindowRgn(hwnd, union, 1) == 0 {
            DeleteObject(union);
            return Err("Could not apply window region".into());
        }
        // Windows owns the region after a successful SetWindowRgn.
    }
    Ok(())
}

pub fn geometry(window: &WebviewWindow, sneak: bool) -> Result<(), String> {
    let monitor = window.primary_monitor().map_err(|e| e.to_string())?.ok_or("No primary monitor")?;
    let scale = monitor.scale_factor();
    let size = monitor.size();
    let origin = monitor.position();
    let width = 720.0_f64.min(size.width as f64 / scale);
    let height = 560.0_f64.min(size.height as f64 / scale);
    let x = origin.x + ((size.width as f64 - width * scale) / 2.0).round() as i32;
    let y = origin.y + if sneak { ((size.height as f64 - height * scale) / 2.0).max(0.0) as i32 } else { 0 };
    window.set_size(tauri::LogicalSize::new(width, height)).map_err(|e| e.to_string())?;
    window.set_position(tauri::PhysicalPosition::new(x, y)).map_err(|e| e.to_string())?;
    Ok(())
}

pub fn reduce_motion() -> bool {
    let mut enabled: BOOL = 1;
    unsafe { SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, &mut enabled as *mut _ as _, 0); }
    enabled == 0
}

pub fn parse_hotkey(text: &str) -> Result<(u32, u32), String> {
    let mut modifiers = MOD_NOREPEAT;
    let mut key = None;
    for part in text.split('+').map(|p| p.trim().to_ascii_lowercase()) {
        match part.as_str() {
            "ctrl" | "control" => modifiers |= MOD_CONTROL,
            "shift" => modifiers |= MOD_SHIFT,
            "alt" => modifiers |= MOD_ALT,
            "win" | "super" => modifiers |= MOD_WIN,
            p => {
                if key.is_some() { return Err("Use modifiers and one key".into()); }
                key = Some(match p {
                    "space" => VK_SPACE as u32,
                    p if p.len() == 1 && p.as_bytes()[0].is_ascii_alphanumeric() => p.as_bytes()[0].to_ascii_uppercase() as u32,
                    p if p.starts_with('f') => p[1..].parse::<u32>().ok().filter(|n| (1..=24).contains(n))
                        .map(|n| VK_F1 as u32 + n - 1).ok_or("Unknown function key")?,
                    _ => return Err("Use a letter, number, Space, or F1–F24".into()),
                });
            }
        }
    }
    if modifiers == MOD_NOREPEAT { return Err("Choose at least one modifier".into()); }
    Ok((modifiers, key.ok_or("Missing hotkey")?))
}

pub fn register(hotkeys: &Hotkeys) -> Vec<String> {
    let mut errors = vec![];
    for (id, name, value) in [(1, "Sneak", &hotkeys.sneak), (2, "Expand", &hotkeys.expand)] {
        unsafe { UnregisterHotKey(null_mut(), id); }
        match parse_hotkey(value) {
            Ok((modifiers, key)) => unsafe {
                if RegisterHotKey(null_mut(), id, modifiers, key) == 0 {
                    errors.push(format!("{name}: {value} is unavailable (Windows error {}).", GetLastError()));
                }
            },
            Err(error) => errors.push(format!("{name}: {error}")),
        }
    }
    errors
}

pub fn start(app: tauri::AppHandle, receiver: std::sync::mpsc::Receiver<Hotkeys>) {
    std::thread::spawn(move || {
        let mut last_pointer = (i32::MIN, i32::MIN);
        let mut last_geometry = String::new();
        let mut count = 0u32;
        loop {
            let Some(window) = app.get_webview_window("main") else { break };
            if let Ok(hotkeys) = receiver.try_recv() {
                let errors = register(&hotkeys);
                let state = app.state::<crate::AppState>();
                state.runtime.lock().unwrap().hotkey_errors = errors;
                let _ = app.emit("native-status", state.runtime.lock().unwrap().clone());
            }
            unsafe {
                let mut message: MSG = zeroed();
                while PeekMessageW(&mut message, null_mut(), 0, 0, PM_REMOVE) != 0 {
                    if message.message == WM_HOTKEY {
                        let _ = app.emit("hotkey", if message.wParam == 1 { "sneak" } else { "expand" });
                    }
                }
                let mut point: POINT = zeroed();
                if GetCursorPos(&mut point) != 0 && last_pointer != (point.x, point.y) {
                    last_pointer = (point.x, point.y);
                    if let (Ok(pos), Ok(scale), Ok(Some(primary))) = (window.inner_position(), window.scale_factor(), window.primary_monitor()) {
                        let center = primary.position().x + (primary.size().width / 2) as i32;
                        let reveal = (point.x - center).abs() < (145.0 * scale) as i32
                            && point.y >= primary.position().y && point.y < primary.position().y + (8.0 * scale) as i32;
                        let _ = app.emit("pointer", Pointer { x: (point.x - pos.x) as f64 / scale,
                            y: (point.y - pos.y) as f64 / scale, reveal });
                    }
                }
            }
            if count.is_multiple_of(12) {
                let sneak = app.state::<crate::AppState>().runtime.lock().unwrap().mode == "sneak";
                if let Ok(Some(primary)) = window.primary_monitor() {
                    let key = format!("{:?}{:?}{}{sneak}", primary.position(), primary.size(), primary.scale_factor());
                    if key != last_geometry {
                        last_geometry = key;
                        let owned = window.clone();
                        let _ = window.run_on_main_thread(move || { let _ = geometry(&owned, sneak); });
                    }
                }
                let reduced = reduce_motion();
                let state = app.state::<crate::AppState>();
                let mut status = state.runtime.lock().unwrap();
                if status.reduce_motion != reduced {
                    status.reduce_motion = reduced;
                    let _ = app.emit("native-status", status.clone());
                }
            }
            count = count.wrapping_add(1);
            std::thread::sleep(std::time::Duration::from_millis(80));
        }
        unsafe { UnregisterHotKey(null_mut(), 1); UnregisterHotKey(null_mut(), 2); }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn hotkeys_reject_invalid_and_accept_defaults() {
        assert!(parse_hotkey("Ctrl+Shift+Alt+Space").is_ok());
        assert!(parse_hotkey("Ctrl+F24").is_ok());
        for bad in ["Space", "Ctrl", "Ctrl+A+B", "Ctrl+F25", "Ctrl+Escape"] {
            assert!(parse_hotkey(bad).is_err(), "{bad}");
        }
    }
}
