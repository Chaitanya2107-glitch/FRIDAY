use fs2::FileExt;
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    fs,
    io::Write,
    path::{Path, PathBuf},
    thread,
    time::Duration,
};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    #[serde(default)]
    pub source_stamp: String,
    pub version: u32,
    pub revision: u64,
    pub pins: Vec<Pin>,
    pub projects: Vec<Project>,
    pub hotkeys: Hotkeys,
    pub appearance: Appearance,
    pub connection: Connection,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Pin {
    pub id: String,
    pub name: String,
    pub path: String,
    #[serde(default = "yes")]
    pub visible: bool,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Project {
    pub id: String,
    pub name: String,
    pub path: String,
    #[serde(default = "amber")]
    pub color: String,
    #[serde(default)]
    pub last_opened: Option<String>,
    #[serde(default = "folder_action")]
    pub actions: Vec<Action>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Action {
    Folder,
    Editor {
        executable: String,
        #[serde(default)]
        args: Vec<String>,
    },
    Terminal {
        executable: String,
        #[serde(default)]
        args: Vec<String>,
    },
    Url {
        url: String,
    },
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Hotkeys {
    pub sneak: String,
    pub expand: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Appearance {
    pub glow: String,
    pub idle_mode: String,
    pub idle_seconds: u32,
    pub snippet: bool,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Connection {
    pub port: u16,
    pub token: String,
}
fn yes() -> bool {
    true
}
fn amber() -> String {
    "#FFB347".into()
}
fn folder_action() -> Vec<Action> {
    vec![Action::Folder]
}
impl Default for Hotkeys {
    fn default() -> Self {
        Self {
            sneak: "Ctrl+Shift+Alt+Space".into(),
            expand: "Ctrl+Shift+Alt+F".into(),
        }
    }
}
impl Default for Appearance {
    fn default() -> Self {
        Self {
            glow: amber(),
            idle_mode: "always".into(),
            idle_seconds: 30,
            snippet: true,
        }
    }
}
impl Default for Connection {
    fn default() -> Self {
        Self {
            port: 17321,
            token: format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple()),
        }
    }
}
impl Default for Config {
    fn default() -> Self {
        Self {
            source_stamp: String::new(),
            version: 1,
            revision: 0,
            pins: vec![],
            projects: vec![],
            hotkeys: Hotkeys::default(),
            appearance: Appearance::default(),
            connection: Connection::default(),
        }
    }
}

pub fn path() -> Result<PathBuf, String> {
    let base = std::env::var_os(if cfg!(windows) {
        "APPDATA"
    } else {
        "XDG_CONFIG_HOME"
    })
    .map(PathBuf::from)
    .or_else(|| std::env::var_os("HOME").map(|p| PathBuf::from(p).join(".config")))
    .ok_or("Cannot locate user config directory")?;
    Ok(base.join("FRIDAY/island/config.json"))
}

pub fn safe_path(path: &str) -> bool {
    let normalized = path.replace('\\', "/");
    let drive = normalized.as_bytes();
    let absolute = if cfg!(windows) {
        drive.len() >= 3 && drive[0].is_ascii_alphabetic() && drive[1] == b':' && drive[2] == b'/'
    } else {
        Path::new(path).is_absolute()
    };
    absolute
        && path.len() <= 4096
        && !path.chars().any(|c| c.is_control())
        && !normalized.starts_with("//")
        && !normalized.split('/').any(|p| p == "..")
}
fn color(value: &str) -> bool {
    value.len() == 7 && value.starts_with('#') && value[1..].bytes().all(|b| b.is_ascii_hexdigit())
}
fn ids<'a>(items: impl Iterator<Item = (&'a str, &'a str)>) -> bool {
    let mut seen = HashSet::new();
    items.into_iter().all(|(id, name)| {
        !id.is_empty()
            && id.len() <= 64
            && !name.trim().is_empty()
            && name.chars().count() <= 80
            && id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
            && seen.insert(id)
    })
}
impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.version != 1
            || self.connection.port < 1024
            || self.connection.token.len() != 64
            || !self
                .connection
                .token
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err("Invalid config version, port or token".into());
        }
        if !color(&self.appearance.glow)
            || !["always", "auto-hide", "hover"].contains(&self.appearance.idle_mode.as_str())
            || !(5..=3600).contains(&self.appearance.idle_seconds)
        {
            return Err("Invalid appearance settings".into());
        }
        if [&self.hotkeys.sneak, &self.hotkeys.expand]
            .iter()
            .any(|s| s.is_empty() || s.len() > 100)
        {
            return Err("Invalid hotkey length".into());
        }
        if self.pins.len() > 64
            || self.projects.len() > 64
            || !ids(self.pins.iter().map(|p| (p.id.as_str(), p.name.as_str())))
            || !ids(self
                .projects
                .iter()
                .map(|p| (p.id.as_str(), p.name.as_str())))
        {
            return Err("Invalid or duplicate app/project IDs".into());
        }
        for pin in &self.pins {
            if !safe_path(&pin.path)
                || !["exe", "lnk"]
                    .iter()
                    .any(|ext| pin.path.to_lowercase().ends_with(&format!(".{ext}")))
            {
                return Err("Pins must be absolute local .exe or .lnk paths".into());
            }
        }
        for project in &self.projects {
            if !safe_path(&project.path) || !color(&project.color) || project.actions.len() > 8 {
                return Err("Invalid project folder, color or actions".into());
            }
            for action in &project.actions {
                match action {
                    Action::Editor { executable, args } | Action::Terminal { executable, args } => {
                        if !safe_path(executable)
                            || !executable.to_lowercase().ends_with(".exe")
                            || args.len() > 32
                            || args.iter().any(|a| a.len() > 4096 || a.contains('\0'))
                        {
                            return Err(
                                "Choose an absolute local editor/terminal .exe and valid arguments"
                                    .into(),
                            );
                        }
                    }
                    Action::Url { url } => {
                        let url = url::Url::parse(url).map_err(|_| "Invalid project URL")?;
                        if !["http", "https"].contains(&url.scheme())
                            || url.host_str().is_none()
                            || !url.username().is_empty()
                            || url.password().is_some()
                        {
                            return Err("Use an http(s) URL without credentials".into());
                        }
                    }
                    Action::Folder => {}
                }
            }
        }
        Ok(())
    }
}

fn lock(path: &Path) -> Result<fs::File, String> {
    fs::create_dir_all(path.parent().ok_or("Invalid config path")?).map_err(|e| e.to_string())?;
    let mut file = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path.with_extension("lock"))
        .map_err(|e| e.to_string())?;
    if file.metadata().map_err(|e| e.to_string())?.len() == 0 {
        file.write_all(b"0").map_err(|e| e.to_string())?;
    }
    for _ in 0..60 {
        if FileExt::try_lock_exclusive(&file).is_ok() {
            return Ok(file);
        }
        thread::sleep(Duration::from_millis(50));
    }
    Err("Island config is busy".into())
}
fn read(path: &Path, materialize_token: bool) -> Result<Config, String> {
    if fs::metadata(path).map_err(|e| e.to_string())?.len() > 1_048_576 {
        return Err("Config exceeds 1 MiB".into());
    }
    let data = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let raw: serde_json::Value =
        serde_json::from_str(data.trim_start_matches('\u{feff}')).map_err(|e| e.to_string())?;
    let missing_token = raw.get("connection").and_then(|c| c.get("token")).is_none();
    let mut config: Config = serde_json::from_value(raw).map_err(|e| e.to_string())?;
    config.validate()?;
    if missing_token && materialize_token {
        write(path, &config)?;
        return read(path, false);
    }
    use std::hash::{Hash, Hasher};
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    data.hash(&mut hasher);
    config.source_stamp = format!("{:016x}", hasher.finish());
    Ok(config)
}
fn write(path: &Path, config: &Config) -> Result<(), String> {
    let temp = path.with_file_name(format!(".config.{}.tmp", Uuid::new_v4()));
    let result = (|| {
        let mut file = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temp)
            .map_err(|e| e.to_string())?;
        let mut persisted = serde_json::to_value(config).map_err(|e| e.to_string())?;
        persisted.as_object_mut().unwrap().remove("source_stamp");
        file.write_all(
            serde_json::to_string_pretty(&persisted)
                .map_err(|e| e.to_string())?
                .as_bytes(),
        )
        .map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
        drop(file);
        // std::fs::rename uses MoveFileExW(REPLACE_EXISTING) on Windows.
        fs::rename(&temp, path).map_err(|e| e.to_string())
    })();
    if result.is_err() {
        let _ = fs::remove_file(temp);
    }
    result
}
pub fn load(path: &Path) -> Result<Config, String> {
    let _lock = lock(path)?;
    if path.exists() {
        if let Ok(config) = read(path, true) {
            return Ok(config);
        }
        fs::copy(
            path,
            path.with_file_name(format!("config.corrupt-{}.json", Uuid::new_v4())),
        )
        .map_err(|e| e.to_string())?;
    }
    let config = Config::default();
    write(path, &config)?;
    read(path, false)
}
pub fn save(path: &Path, mut next: Config) -> Result<Config, String> {
    next.validate()?;
    let _lock = lock(path)?;
    let current = read(path, false)?;
    if current.revision != next.revision
        || current.connection.token != next.connection.token
        || current.source_stamp != next.source_stamp
    {
        return Err("Config changed elsewhere. Reload Settings and retry.".into());
    }
    next.revision += 1;
    write(path, &next)?;
    read(path, false)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn missing_token_is_materialized_once() {
        let root = std::env::temp_dir().join(format!("friday-island-test-{}", Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("config.json");
        fs::write(&path, r##"{"appearance":{"glow":"#FF9900"}}"##).unwrap();
        let first = load(&path).unwrap();
        assert_eq!(
            first.connection.token,
            load(&path).unwrap().connection.token
        );
        assert_eq!(first.appearance.glow, "#FF9900");
        assert!(fs::read_to_string(&path)
            .unwrap()
            .contains(&first.connection.token));
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn validates_boundary_and_preserves_corruption() {
        let root = std::env::temp_dir().join(format!("friday-island-test-{}", Uuid::new_v4()));
        let path = root.join("config.json");
        let first = load(&path).unwrap();
        assert_eq!(
            first.connection.token,
            load(&path).unwrap().connection.token
        );
        let mut invalid = first.clone();
        invalid.pins.push(Pin {
            id: "x".into(),
            name: "X".into(),
            path: "cmd.exe".into(),
            visible: true,
        });
        assert!(invalid.validate().is_err());
        let saved = save(&path, first.clone()).unwrap();
        assert_eq!(saved.revision, 1);
        assert!(save(&path, first).is_err());
        let edited = fs::read_to_string(&path)
            .unwrap()
            .replace("#FFB347", "#FF9900");
        fs::write(&path, edited).unwrap();
        assert!(save(&path, saved).is_err());
        fs::write(&path, "{broken").unwrap();
        assert!(load(&path).is_ok());
        assert!(fs::read_dir(&root).unwrap().any(|e| e
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with("config.corrupt-")));
        fs::remove_dir_all(root).unwrap();
    }
}
