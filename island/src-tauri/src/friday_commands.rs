use crate::{windows, AppState};
use serde::Serialize;
use tauri::{State, WebviewWindow};
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum HandyAction { Toggle, Cancel }

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dictation_accepts_only_the_existing_handy_controls() {
        for action in ["\"toggle\"", "\"cancel\""] { assert!(serde_json::from_str::<HandyAction>(action).is_ok()); }
        for action in ["\"launch\"", "\"powershell\"", "{}"] { assert!(serde_json::from_str::<HandyAction>(action).is_err()); }
    }
}

#[tauri::command]
pub fn handy_control(action: HandyAction, window: WebviewWindow, state: State<'_, AppState>) -> Result<(), String> {
    use std::{os::windows::process::CommandExt, process::Command};
    if window.label() != "main" { return Err("Use Handy from Island's command bar.".into()); }
    if matches!(action, HandyAction::Toggle) {
        let runtime = state.runtime.lock().map_err(|_| "Window state unavailable")?;
        if crate::display::blocked(&runtime) { return Err("Dictation is hidden while gaming or fullscreen.".into()); }
        if !matches!(runtime.mode.as_str(), "peek" | "sneak" | "expanded")
            || windows::foreground() != window.hwnd().map_err(|e| e.to_string())?.0 as usize
        {
            return Err("Focus the Island command bar to use Handy.".into());
        }
    }
    let path = std::path::PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or("Windows app folder unavailable")?).join("Handy/handy.exe");
    if !path.is_file() { return Err("Handy is not installed. Type a command or use FRIDAY's Listen control.".into()); }
    Command::new(path).arg(match action { HandyAction::Toggle => "--toggle-transcription", HandyAction::Cancel => "--cancel" })
        .creation_flags(0x08000000).spawn().map_err(|e| e.to_string())?;
    Ok(())
}

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
