#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod apps_commands;
mod bridge_process;
mod catalog;
mod config;
mod desktop;
#[cfg(windows)]
mod discovery;
#[cfg(windows)]
mod friday_commands;
#[cfg(windows)]
mod picker;
mod shell;
mod startup;
#[cfg(windows)]
mod windows;

use config::{Config, Hotkeys};
use serde::{Deserialize, Serialize};
use std::{
    path::PathBuf,
    sync::{mpsc, Arc, Mutex},
};
use tauri::{Emitter, Manager, State, WebviewWindow};

#[derive(Clone, Default, Serialize)]
pub struct RuntimeStatus {
    mode: String,
    hotkey_errors: Vec<String>,
    max_width: f64,
    max_height: f64,
    reduce_motion: bool,
    #[serde(skip)]
    previous_window: usize,
    #[serde(skip)]
    previous_pid: u32,
    #[serde(skip)]
    previous_captured_at: f64,
    #[serde(skip)]
    width: f64,
    #[serde(skip)]
    height: f64,
}
pub struct AppState {
    path: PathBuf,
    runtime: Mutex<RuntimeStatus>,
    hotkeys: mpsc::Sender<Hotkeys>,
    catalog: Arc<catalog::Catalog>,
}
#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
enum Mode {
    Rest,
    Peek,
    Expanded,
    Sneak,
    Hidden,
}

#[tauri::command]
async fn get_config(state: State<'_, AppState>) -> Result<Config, String> {
    let path = state.path.clone();
    tauri::async_runtime::spawn_blocking(move || config::load(&path))
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
async fn save_config(
    next: Config,
    state: State<'_, AppState>,
    supervisor: State<'_, startup::Supervisor>,
) -> Result<Config, String> {
    let path = state.path.clone();
    let saved = tauri::async_runtime::spawn_blocking(move || {
        let old = config::load(&path)?;
        if old.startup.launch_at_login != next.startup.launch_at_login {
            return Err("Use the explicit sign-in startup control to change this setting.".into());
        }
        config::save(&path, next)
    })
    .await
    .map_err(|e| e.to_string())??;
    state
        .hotkeys
        .send(saved.hotkeys.clone())
        .map_err(|e| e.to_string())?;
    supervisor.configure(saved.clone());
    Ok(saved)
}
#[tauri::command]
fn runtime_status(state: State<'_, AppState>) -> RuntimeStatus {
    state.runtime.lock().unwrap().clone()
}

#[tauri::command]
fn set_mode(
    mode: Mode,
    activate: bool,
    window: WebviewWindow,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let mut runtime = state.runtime.lock().unwrap();
    runtime.mode = match mode {
        Mode::Rest => "rest",
        Mode::Peek => "peek",
        Mode::Expanded => "expanded",
        Mode::Sneak => "sneak",
        Mode::Hidden => "hidden",
    }
    .into();
    let deliberate = activate && matches!(mode, Mode::Peek | Mode::Sneak | Mode::Expanded);
    #[cfg(windows)]
    let was_foreground =
        windows::foreground() == window.hwnd().map_err(|e| e.to_string())?.0 as usize;
    #[cfg(windows)]
    {
        if deliberate && runtime.previous_window == 0 {
            let current = windows::foreground();
            let own = window.hwnd().map_err(|e| e.to_string())?.0 as usize;
            if current != own {
                runtime.previous_window = current;
                unsafe {
                    windows_sys::Win32::UI::WindowsAndMessaging::GetWindowThreadProcessId(
                        current as _,
                        &mut runtime.previous_pid,
                    );
                }
                runtime.previous_captured_at = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map_or(0.0, |time| time.as_secs_f64());
            }
        }
        windows::passive(&window, !deliberate)?;
        windows::geometry(
            &window,
            runtime.width,
            runtime.height,
            matches!(mode, Mode::Sneak),
        )?;
    }
    if deliberate {
        window.set_focus().map_err(|e| e.to_string())?;
    } else if matches!(mode, Mode::Rest | Mode::Hidden) {
        #[cfg(windows)]
        {
            if was_foreground {
                windows::restore(runtime.previous_window);
            }
        }
        runtime.previous_window = 0;
    }
    #[cfg(debug_assertions)]
    eprintln!("Island mode: {} (keyboard: {deliberate})", runtime.mode);
    Ok(())
}

#[cfg(windows)]
#[tauri::command]
fn set_regions(
    width: f64,
    height: f64,
    rects: Vec<windows::HitRect>,
    window: WebviewWindow,
    state: State<'_, AppState>,
) -> Result<(), String> {
    if !width.is_finite() || !height.is_finite() || width < 1.0 || height < 1.0 {
        return Err("Invalid island size".into());
    }
    let mut runtime = state.runtime.lock().unwrap();
    runtime.width = width;
    runtime.height = height;
    windows::geometry(&window, width, height, runtime.mode == "sneak")?;
    windows::regions(&window, rects)
}
#[cfg(not(windows))]
#[tauri::command]
fn set_regions(width: f64, height: f64, rects: Vec<serde_json::Value>) {
    let _ = (width, height, rects);
}

#[tauri::command]
async fn local_command(
    text: String,
    state: State<'_, AppState>,
) -> Result<shell::LocalResult, String> {
    let config = get_config(state.clone()).await?;
    Ok(apps_commands::resolve(&text, &config, &state.catalog))
}

#[tauri::command]
async fn launch(kind: String, id: String, state: State<'_, AppState>) -> Result<String, String> {
    let path = state.path.clone();
    let catalog = Arc::clone(&state.catalog);
    tauri::async_runtime::spawn_blocking(move || apps_commands::launch(&path, &catalog, &kind, &id))
        .await
        .map_err(|e| e.to_string())?
}

#[cfg(windows)]
#[tauri::command]
async fn choose_path(
    folder: bool,
    window: WebviewWindow,
) -> Result<Option<picker::Picked>, String> {
    // An explicit Settings button is the only caller of the native picker.
    let owner = window.hwnd().map_err(|e| e.to_string())?.0 as usize;
    tauri::async_runtime::spawn_blocking(move || picker::choose(folder, owner))
        .await
        .map_err(|e| e.to_string())
}
#[cfg(not(windows))]
#[tauri::command]
fn choose_path(folder: bool) -> Result<Option<serde_json::Value>, String> {
    let _ = folder;
    Err("Native picker is Windows-only in v1".into())
}

#[tauri::command]
async fn pin_icon(id: String, state: State<'_, AppState>) -> Result<String, String> {
    let config = get_config(state.clone()).await?;
    let pin = config
        .pins
        .iter()
        .find(|p| p.id == id)
        .ok_or("Unknown pin")?;
    let path = pin.path.clone();
    if let Some(id) = &pin.app_id {
        let catalog = Arc::clone(&state.catalog);
        let id = id.clone();
        return tauri::async_runtime::spawn_blocking(move || catalog.icon(&id))
            .await
            .map_err(|e| e.to_string())?;
    }
    #[cfg(windows)]
    {
        tauri::async_runtime::spawn_blocking(move || picker::icon(&path))
            .await
            .map_err(|e| e.to_string())?
    }
    #[cfg(not(windows))]
    {
        let _ = path;
        Err("Icon extraction is Windows-only".into())
    }
}
#[tauri::command]
fn quit(app: tauri::AppHandle) {
    app.exit(0);
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            if args.iter().any(|a| a == "--quit") {
                app.exit(0);
            } else if !args.iter().any(|a| a == "--background") {
                let _ = app.emit("hotkey", "expand");
            }
        }))
        .invoke_handler(tauri::generate_handler![
            get_config,
            save_config,
            runtime_status,
            startup::startup_status,
            startup::restart_bridge,
            startup::start_friday,
            startup::set_login,
            startup::reload_config,
            set_mode,
            set_regions,
            local_command,
            friday_commands::execution_target,
            friday_commands::clear_execution_target,
            friday_commands::open_controls,
            launch,
            choose_path,
            pin_icon,
            desktop::desktop_status,
            desktop::media_control,
            apps_commands::search_apps,
            apps_commands::app_index_status,
            apps_commands::rescan_apps,
            apps_commands::app_icon,
            apps_commands::toggle_app_pin,
            quit
        ])
        .setup(|app| {
            if std::env::args().any(|arg| arg == "--quit") {
                app.handle().exit(0);
                return Ok(());
            }
            let path = std::env::var_os("FRIDAY_ISLAND_CONFIG")
                .map(PathBuf::from)
                .map(Ok)
                .unwrap_or_else(config::path)?;
            if !path.is_absolute() {
                return Err("FRIDAY_ISLAND_CONFIG must be absolute".into());
            }
            let config = config::load(&path)?;
            let (sender, receiver) = mpsc::channel();
            let mut runtime = RuntimeStatus {
                mode: "rest".into(),
                width: 298.0,
                height: 54.0,
                max_width: 720.0,
                max_height: 560.0,
                ..Default::default()
            };
            let window = app
                .get_webview_window("main")
                .ok_or("Missing main window")?;
            #[cfg(windows)]
            {
                windows::passive(&window, true)?;
                windows::regions(&window, vec![])?;
                window.set_background_color(Some(tauri::window::Color(0, 0, 0, 0)))?;
                windows::geometry(&window, runtime.width, runtime.height, false)?;
                (runtime.max_width, runtime.max_height) = windows::limits(&window)?;
                runtime.reduce_motion = windows::reduce_motion();
            }
            app.manage(startup::Supervisor::start(config.clone(), path.clone()));
            app.manage(AppState {
                path,
                runtime: Mutex::new(runtime),
                hotkeys: sender.clone(),
                catalog: Arc::new(catalog::Catalog::default()),
            });
            sender.send(config.hotkeys)?;
            #[cfg(windows)]
            windows::start(app.handle().clone(), receiver);
            #[cfg(not(windows))]
            drop(receiver);
            window.show()?;
            #[cfg(windows)]
            windows::passive(&window, true)?;
            catalog::Catalog::start(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Unable to start FRIDAY Island")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                if let Some(supervisor) = app.try_state::<startup::Supervisor>() {
                    supervisor.stop();
                }
            }
        });
}
