//! The native gate wins over hover, replies, hotkeys and disconnected webviews.
use tauri::{Emitter, Manager, State};

pub fn blocked(runtime: &crate::RuntimeStatus) -> bool {
    #[cfg(windows)] {
        let (locked, fullscreen) = crate::hud::visibility();
        if locked || fullscreen || gaming() { return true; }
    }
    runtime.backend_game_until.is_some_and(|end| std::time::Instant::now() < end)
}

#[tauri::command]
pub fn display_policy(app: tauri::AppHandle, state: State<'_, crate::AppState>, suppressed: bool) {
    state.runtime.lock().unwrap().backend_game_until = suppressed.then(||
        std::time::Instant::now() + std::time::Duration::from_secs(3));
    refresh(&app);
}

pub fn refresh(app: &tauri::AppHandle) {
    let state = app.state::<crate::AppState>();
    let mut status = state.runtime.lock().unwrap();
    let suppressed = blocked(&status);
    #[cfg(windows)] let (locked, fullscreen) = crate::hud::visibility();
    #[cfg(not(windows))] let (locked, fullscreen) = (false, false);
    if status.display_suppressed == suppressed && status.desktop_locked == locked && status.fullscreen_front == fullscreen { return; }
    status.display_suppressed = suppressed;
    status.desktop_locked = locked;
    status.fullscreen_front = fullscreen;
    if suppressed {
        status.mode = "hidden".into();
        status.previous_window = 0;
        status.previous_pid = 0;
    }
    let snapshot = status.clone();
    drop(status);
    if suppressed {
        if let Some(window) = app.get_webview_window("main") {
            #[cfg(windows)] let _ = crate::windows::regions(&window, vec![]);
            let _ = window.hide();
        }
    } else if let Some(window) = app.get_webview_window("main") {
        // A webview first launched while hidden may not have booted yet.
        #[cfg(windows)] let _ = crate::windows::passive(&window, true);
        let _ = window.show();
    }
    let _ = app.emit("native-status", snapshot);
    crate::hud::tick(app);
}

fn game_path(path: &str) -> bool {
    let path = path.replace('\\', "/").to_lowercase();
    let name = path.rsplit('/').next().unwrap_or("").trim_end_matches(".exe");
    name.ends_with("-shipping") || ["steamapps/common/", "/games/", "/xboxgames/", "/riot games/", "/epic games/", "/ea games/", "/gog galaxy/games/"].iter().any(|folder| path.contains(folder))
        || ["steam", "steamwebhelper", "epicgameslauncher", "xboxpcapp", "xboxpcappft", "gamingservices", "riotclientservices", "riotclientux", "leagueclient", "valorant", "battle.net", "eadesktop", "ubisoftconnect", "upc", "galaxyclient", "robloxplayerbeta", "minecraft", "minecraftlauncher", "javaw", "gamebar"].contains(&name)
}

#[cfg(windows)]
fn gaming() -> bool {
    use windows_sys::Win32::{Foundation::CloseHandle, System::Threading::*, UI::{Shell::*, WindowsAndMessaging::*}};
    unsafe {
        let mut notification = 0;
        if SHQueryUserNotificationState(&mut notification) == 0
            && matches!(notification, QUNS_RUNNING_D3D_FULL_SCREEN | QUNS_PRESENTATION_MODE)
        {
            return true;
        }
        let hwnd = GetForegroundWindow();
        let mut pid = 0;
        GetWindowThreadProcessId(hwnd, &mut pid);
        if pid == 0 || pid == std::process::id() { return false; }
        let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if process.is_null() { return false; }
        let mut path = [0u16; 4096]; let mut length = path.len() as u32;
        let ok = QueryFullProcessImageNameW(process, 0, path.as_mut_ptr(), &mut length);
        CloseHandle(process);
        ok != 0 && game_path(&String::from_utf16_lossy(&path[..length as usize]))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn windowed_games_are_detected_without_the_backend() {
        for path in [r"D:\SteamLibrary\steamapps\common\Game\game.exe", r"C:\Games\A\a.exe", r"C:\Custom\b1-Win64-Shipping.exe", r"C:\Riot\VALORANT.exe"] { assert!(game_path(path)); }
        for path in [r"C:\Windows\explorer.exe", r"C:\Apps\Code.exe", r"C:\Apps\friday-island.exe"] { assert!(!game_path(path)); }
    }
}
