use crate::{windows, AppState};
use serde::Serialize;
use tauri::{State, WebviewWindow};

#[derive(Serialize)]
pub struct Target {
    hwnd: usize,
    pid: u32,
    captured_at: f64,
}

#[tauri::command]
pub fn clear_execution_target(
    window: WebviewWindow,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let mut runtime = state
        .runtime
        .lock()
        .map_err(|_| "Window state unavailable")?;
    runtime.previous_window = 0;
    runtime.previous_pid = 0;
    runtime.previous_captured_at = 0.0;
    windows::passive(&window, true)
}

#[tauri::command]
pub fn open_controls() -> Result<(), String> {
    use windows_sys::Win32::UI::WindowsAndMessaging::{FindWindowW, PostMessageW};
    let class: Vec<u16> = "FridayTaskbarHost\0".encode_utf16().collect();
    unsafe {
        let hwnd = FindWindowW(class.as_ptr(), std::ptr::null());
        if hwnd.is_null() || PostMessageW(hwnd, 0x8000 + 41, 2, 0) == 0 {
            return Err("Start FRIDAY to open its full controls.".into());
        }
    }
    Ok(())
}

#[tauri::command]
pub fn execution_target(window: WebviewWindow, state: State<'_, AppState>) -> Option<Target> {
    let runtime = state.runtime.lock().ok()?;
    let hwnd = if runtime.previous_window != 0 {
        runtime.previous_window
    } else {
        windows::foreground()
    };
    if hwnd == 0 || hwnd == window.hwnd().ok()?.0 as usize {
        return None;
    }
    let mut pid = 0;
    unsafe {
        windows_sys::Win32::UI::WindowsAndMessaging::GetWindowThreadProcessId(hwnd as _, &mut pid);
    }
    if pid == 0 {
        return None;
    }
    if runtime.previous_window != 0 && pid != runtime.previous_pid {
        return None;
    }
    let captured_at = if runtime.previous_window != 0 {
        runtime.previous_captured_at
    } else {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .ok()?
            .as_secs_f64()
    };
    Some(Target {
        hwnd,
        pid,
        captured_at,
    })
}
