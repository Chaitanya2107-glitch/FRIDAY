use crate::{bridge_process::BridgeProcess, config::Config};
use serde::Serialize;
use std::{
    net::TcpListener,
    path::{Path, PathBuf},
    sync::{mpsc, Arc, Mutex},
    time::{Duration, Instant},
};

#[derive(Clone, Default, Serialize)]
pub struct Status {
    pub phase: String,
    pub error: String,
    pub owned_pid: Option<u32>,
    pub attempts: u32,
    pub isolated: bool,
    pub login_enabled: bool,
}
enum Event {
    Configure(Config),
    Restart,
    Stop,
}

#[tauri::command]
pub async fn start_friday(state: tauri::State<'_, crate::AppState>) -> Result<(), String> {
    if std::env::var_os("FRIDAY_ISLAND_CONFIG").is_some() {
        return Err("Starting the owner's FRIDAY is disabled in isolated runs.".into());
    }
    let path = state.path.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let config = crate::config::load(&path)?;
        let root = backend_root(&config.startup.backend_root)?;
        if !root.join("interfaces/taskbar/launch.py").is_file() {
            return Err("Update the FRIDAY backend before starting it from Island.".into());
        }
        BridgeProcess::spawn(&root, &path).map(|_| ())
    })
    .await
    .map_err(|error| error.to_string())?
}
pub struct Supervisor {
    sender: mpsc::Sender<Event>,
    status: Arc<Mutex<Status>>,
    pub isolated: bool,
}

fn root_valid(path: &Path) -> bool {
    crate::config::safe_path(&path.to_string_lossy())
        && path
            .join("services/friday_island_server/__main__.py")
            .is_file()
        && path
            .join(if cfg!(windows) {
                "venv/Scripts/python.exe"
            } else {
                "venv/bin/python"
            })
            .is_file()
}
fn backend_root(configured: &str) -> Result<PathBuf, String> {
    if !configured.is_empty() {
        let path = PathBuf::from(configured);
        return if root_valid(&path) {
            Ok(path)
        } else {
            Err("Choose the FRIDAY folder containing its server module and venv.".into())
        };
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(root) = exe.ancestors().find(|p| root_valid(p)) {
            return Ok(root.to_path_buf());
        }
    }
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent);
    root.filter(|p| root_valid(p))
        .map(Path::to_path_buf)
        .ok_or("FRIDAY folder not found. Select it in Connection settings.".into())
}
fn listening(port: u16) -> bool {
    // Probe availability without opening an unauthenticated WebSocket connection
    // (which would spam the Python server's logs). The UI verifies identity.
    TcpListener::bind(("127.0.0.1", port)).is_err()
}
pub fn retry_delay(attempts: u32) -> Duration {
    Duration::from_secs((1u64 << attempts.min(5)).min(30))
}

impl Supervisor {
    pub fn start(config: Config, path: PathBuf) -> Self {
        let isolated = std::env::var_os("FRIDAY_ISLAND_CONFIG").is_some();
        let allowed = std::env::var("FRIDAY_ISLAND_MANAGE_BRIDGE")
            .map(|v| v == "1")
            .unwrap_or(!isolated);
        let (sender, receiver) = mpsc::channel();
        let status = Arc::new(Mutex::new(Status {
            isolated,
            ..Default::default()
        }));
        let shared = status.clone();
        std::thread::spawn(move || {
            let mut config = config;
            let mut child: Option<BridgeProcess> = None;
            let mut attempts = 0;
            let mut next = Instant::now();
            let mut launched = Instant::now();
            loop {
                let mut current = Status {
                    isolated,
                    attempts,
                    ..Default::default()
                };
                if !allowed || !config.startup.manage_bridge {
                    child = None;
                    current.phase = "disabled".into();
                    if !allowed {
                        current.error =
                            "Automatic bridge launch is disabled for this isolated run.".into();
                    }
                } else {
                    if let Some(process) = child.as_mut() {
                        match process.child.try_wait() {
                            Ok(Some(_)) | Err(_) => {
                                child = None;
                                attempts = attempts.saturating_add(1);
                                next = Instant::now() + retry_delay(attempts);
                            }
                            Ok(None) => {}
                        }
                    }
                    if let Some(process) = child.as_ref() {
                        current.owned_pid = Some(process.child.id());
                        if listening(config.connection.port) {
                            current.phase = "managed".into();
                            if launched.elapsed() > Duration::from_secs(30) {
                                attempts = 0;
                            }
                        } else {
                            current.phase = "starting".into();
                            if !process.desktop && launched.elapsed() > Duration::from_secs(30) {
                                child = None;
                                attempts = attempts.saturating_add(1);
                                next = Instant::now() + retry_delay(attempts);
                                current.phase = "retrying".into();
                                current.owned_pid = None;
                                current.error = "Bridge did not become ready. Check bridge-error.log next to config.json.".into();
                            }
                        }
                    } else if listening(config.connection.port) {
                        current.phase = "external".into();
                    } else if Instant::now() < next {
                        current.phase = "retrying".into();
                    } else {
                        match backend_root(&config.startup.backend_root)
                            .and_then(|root| BridgeProcess::spawn(&root, &path))
                        {
                            Ok(process) => {
                                current.owned_pid = Some(process.child.id());
                                child = Some(process);
                                launched = Instant::now();
                                current.phase = "starting".into();
                            }
                            Err(error) => {
                                attempts = attempts.saturating_add(1);
                                next = Instant::now() + retry_delay(attempts);
                                current.phase = "error".into();
                                current.error = error;
                            }
                        }
                    }
                }
                current.attempts = attempts;
                // Preserve useful failures through the backoff rather than blinking them away.
                if current.phase == "retrying" && current.error.is_empty() {
                    current.error = shared.lock().unwrap().error.clone();
                }
                *shared.lock().unwrap() = current;
                match receiver.recv_timeout(Duration::from_secs(1)) {
                    Ok(Event::Configure(updated)) => {
                        if updated.connection.port != config.connection.port
                            || updated.connection.token != config.connection.token
                            || updated.startup.backend_root != config.startup.backend_root
                        {
                            child = None;
                        }
                        config = updated;
                        attempts = 0;
                        next = Instant::now();
                    }
                    Ok(Event::Restart) => {
                        child = None;
                        attempts = 0;
                        next = Instant::now();
                    }
                    Ok(Event::Stop) | Err(mpsc::RecvTimeoutError::Disconnected) => break,
                    Err(mpsc::RecvTimeoutError::Timeout) => {}
                }
            }
        });
        Self {
            sender,
            status,
            isolated,
        }
    }
    pub fn configure(&self, config: Config) {
        let _ = self.sender.send(Event::Configure(config));
    }
    pub fn stop(&self) {
        let _ = self.sender.send(Event::Stop);
    }
}

pub fn login_command(exe: &Path) -> Result<String, String> {
    if !exe.is_absolute()
        || !exe.is_file()
        || exe
            .to_string_lossy()
            .chars()
            .any(|c| c == '"' || c.is_control())
    {
        return Err("Invalid Island executable".into());
    }
    let command = format!("\"{}\" --background", exe.display());
    if command.len() > 260 {
        return Err("Move the Island to a shorter path before enabling sign-in startup.".into());
    }
    Ok(command)
}
#[cfg(windows)]
fn login_value() -> Result<Option<String>, String> {
    use winreg::{enums::*, RegKey};
    let key = RegKey::predef(HKEY_CURRENT_USER).open_subkey_with_flags(
        "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        KEY_READ,
    );
    match key {
        Ok(key) => match key.get_value("FRIDAYIsland") {
            Ok(v) => Ok(Some(v)),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.to_string()),
        },
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}
#[cfg(windows)]
fn write_login(value: Option<&str>) -> Result<(), String> {
    use winreg::{enums::*, RegKey};
    let (key, _) = RegKey::predef(HKEY_CURRENT_USER)
        .create_subkey("Software\\Microsoft\\Windows\\CurrentVersion\\Run")
        .map_err(|e| e.to_string())?;
    match value {
        Some(value) => key
            .set_value("FRIDAYIsland", &value)
            .map_err(|e| e.to_string()),
        None => match key.delete_value("FRIDAYIsland") {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(e.to_string()),
        },
    }
}
#[cfg(not(windows))]
fn login_value() -> Result<Option<String>, String> {
    Ok(None)
}
#[cfg(not(windows))]
fn write_login(_: Option<&str>) -> Result<(), String> {
    Err("Sign-in startup is Windows-only.".into())
}

#[tauri::command]
pub fn startup_status(supervisor: tauri::State<'_, Supervisor>) -> Status {
    let mut status = supervisor.status.lock().unwrap().clone();
    if !supervisor.isolated {
        match login_value() {
            Ok(v) => status.login_enabled = v.is_some(),
            Err(e) => status.error = e,
        }
    }
    status
}
#[tauri::command]
pub fn restart_bridge(supervisor: tauri::State<'_, Supervisor>) {
    let _ = supervisor.sender.send(Event::Restart);
}
#[tauri::command]
pub async fn reload_config(
    state: tauri::State<'_, crate::AppState>,
    supervisor: tauri::State<'_, Supervisor>,
) -> Result<Config, String> {
    let path = state.path.clone();
    let config = tauri::async_runtime::spawn_blocking(move || crate::config::load(&path))
        .await
        .map_err(|e| e.to_string())??;
    supervisor.configure(config.clone());
    state
        .hotkeys
        .send(config.hotkeys.clone())
        .map_err(|e| e.to_string())?;
    Ok(config)
}
#[tauri::command]
pub async fn set_login(
    enabled: bool,
    state: tauri::State<'_, crate::AppState>,
    supervisor: tauri::State<'_, Supervisor>,
) -> Result<Config, String> {
    if supervisor.isolated {
        return Err("Sign-in startup is unavailable with an isolated config.".into());
    }
    if enabled && cfg!(debug_assertions) {
        return Err("Enable sign-in startup from the standalone release app; the development app requires Vite.".into());
    }
    let path = state.path.clone();
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        static LOGIN_WRITE: Mutex<()> = Mutex::new(());
        let _guard = LOGIN_WRITE
            .lock()
            .map_err(|_| "Sign-in settings are busy")?;
        let old = login_value()?;
        let mut config = crate::config::load(&path)?;
        let command = if enabled {
            Some(login_command(&exe)?)
        } else {
            None
        };
        write_login(command.as_deref())?;
        config.startup.launch_at_login = enabled;
        match crate::config::save(&path, config) {
            Ok(saved) => Ok(saved),
            Err(error) => {
                let _ = write_login(old.as_deref());
                Err(error)
            }
        }
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn retry_is_bounded_and_launch_uses_quoted_background_executable() {
        assert_eq!(retry_delay(0).as_secs(), 1);
        assert_eq!(retry_delay(100).as_secs(), 30);
        let exe = std::env::current_exe().unwrap();
        assert_eq!(
            login_command(&exe).unwrap(),
            format!("\"{}\" --background", exe.display())
        );
        assert!(login_command(Path::new("relative.exe")).is_err());
        assert!(backend_root("C:/definitely-not-friday").is_err());
    }
}
