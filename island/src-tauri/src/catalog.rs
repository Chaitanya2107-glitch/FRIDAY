//! Native launch authority. Text searches metadata; only an indexed ID launches.
use crate::config::{Config, Pin};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex, RwLock,
    },
};
use tauri::{Emitter, Manager};

#[derive(Clone, Debug)]
pub enum Target {
    Shortcut(String),
    Executable(String),
    Packaged(String),
}
#[derive(Clone, Debug, Serialize)]
pub struct App {
    pub id: String,
    pub name: String,
    pub source: String,
    #[serde(skip)]
    pub target: Target,
}
impl App {
    pub fn new(name: String, source: &str, target: Target) -> Option<Self> {
        if name.trim().is_empty() || name.chars().any(|c| c.is_control()) || name.len() > 512 {
            return None;
        }
        let identity = match &target {
            Target::Shortcut(p) | Target::Executable(p) if crate::config::safe_path(p) => {
                p.replace('/', "\\").to_lowercase()
            }
            Target::Packaged(id) if valid_aumid(id) => id.to_lowercase(),
            _ => return None,
        };
        let hash = format!("{:x}", Sha256::digest(identity.as_bytes()));
        Some(Self {
            id: format!("app-{}", &hash[..32]),
            name: name.trim().into(),
            source: source.into(),
            target,
        })
    }
}
pub fn valid_aumid(id: &str) -> bool {
    id.len() <= 256
        && id
            .split_once('!')
            .is_some_and(|(a, b)| !a.is_empty() && !b.is_empty())
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-!".contains(&b))
}
pub fn registered_path(value: &str) -> Option<String> {
    let value = value.trim();
    let path = if value.starts_with('"') {
        value.strip_prefix('"')?.strip_suffix('"')?
    } else {
        value
    };
    (crate::config::safe_path(path) && path.to_lowercase().ends_with(".exe") && !path.contains('"'))
        .then(|| path.into())
}
#[derive(Clone, Default, Serialize)]
pub struct IndexStatus {
    pub count: usize,
    pub scanning: bool,
    pub updated_at: u64,
    pub errors: Vec<String>,
}
#[derive(Clone, Serialize)]
pub struct Match {
    pub id: String,
    pub name: String,
    pub source: String,
    pub kind: String,
    pub pinned: bool,
}
#[derive(Default)]
pub struct Catalog {
    entries: RwLock<Vec<App>>,
    icons: Mutex<HashMap<String, String>>,
    scanning: AtomicBool,
    status: Mutex<IndexStatus>,
}
pub fn now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn recent_bonus(config: &Config, id: &str) -> i64 {
    config
        .recent_apps
        .iter()
        .find(|r| r.id == id)
        .map_or(0, |r| {
            100 + r.count.min(50) as i64
                + if now().saturating_sub(r.last_used) < 7 * 86400 {
                    100
                } else {
                    0
                }
        })
}
fn edit_distance(a: &str, b: &str) -> usize {
    let b: Vec<_> = b.chars().collect();
    let mut row: Vec<usize> = (0..=b.len()).collect();
    for (i, x) in a.chars().enumerate() {
        let mut previous = row[0];
        row[0] = i + 1;
        for (j, y) in b.iter().enumerate() {
            let old = row[j + 1];
            row[j + 1] = (row[j] + 1)
                .min(old + 1)
                .min(previous + usize::from(x != *y));
            previous = old;
        }
    }
    row[b.len()]
}
pub fn score(query: &str, name: &str) -> i64 {
    let (q, n) = (query.trim().to_lowercase(), name.to_lowercase());
    if q.len() > 128 || q.chars().any(|c| c.is_control() || "\\/:;|<>".contains(c)) {
        return 0;
    }
    if q.is_empty() {
        return 1000;
    }
    if q == n {
        return 10000;
    }
    if n.starts_with(&q) {
        return 8000;
    }
    if n.split_whitespace().any(|w| w.starts_with(&q)) {
        return 7000;
    }
    if n.contains(&q) {
        return 6000;
    }
    let mut chars = n.chars();
    if q.chars().all(|c| chars.by_ref().any(|v| v == c)) {
        return 4000 - n.chars().count() as i64;
    }
    if (3..=30).contains(&q.chars().count())
        && n.split_whitespace()
            .any(|w| w.len() <= 40 && edit_distance(&q, w) <= if q.len() < 6 { 1 } else { 2 })
    {
        return 2000;
    }
    0
}
impl Catalog {
    pub fn status(&self) -> IndexStatus {
        let mut s = self.status.lock().unwrap().clone();
        s.scanning = self.scanning.load(Ordering::Acquire);
        s
    }
    pub fn get(&self, id: &str) -> Result<App, String> {
        self.entries
            .read()
            .unwrap()
            .iter()
            .find(|a| a.id == id)
            .cloned()
            .ok_or_else(|| "No app found. Rescan apps in Settings.".into())
    }
    pub fn search(&self, query: &str, config: &Config, limit: usize) -> Vec<Match> {
        let mut rows: Vec<(i64, Match)> = self
            .entries
            .read()
            .unwrap()
            .iter()
            .filter_map(|app| {
                let rank = score(query, &app.name);
                if rank == 0 {
                    return None;
                }
                let recent = config.recent_apps.iter().find(|r| r.id == app.id);
                let bonus = recent.map_or(0, |r| {
                    100 + (r.count.min(50) as i64)
                        + if now().saturating_sub(r.last_used) < 7 * 86400 {
                            100
                        } else {
                            0
                        }
                });
                Some((
                    rank + bonus
                        + if app.source.contains("Start Menu") {
                            10
                        } else {
                            0
                        },
                    Match {
                        id: app.id.clone(),
                        name: app.name.clone(),
                        source: app.source.clone(),
                        kind: "app".into(),
                        pinned: config
                            .pins
                            .iter()
                            .any(|p| p.app_id.as_deref() == Some(&app.id)),
                    },
                ))
            })
            .collect();
        for pin in config.pins.iter().filter(|p| p.app_id.is_none()) {
            let rank = score(query, &pin.name);
            if rank > 0 {
                rows.push((
                    rank + 5 + recent_bonus(config, &format!("pin-{}", pin.id)),
                    Match {
                        id: pin.id.clone(),
                        name: pin.name.clone(),
                        source: "Favourite · manual".into(),
                        kind: "pin".into(),
                        pinned: true,
                    },
                ));
            }
        }
        rows.sort_by(|a, b| {
            b.0.cmp(&a.0)
                .then_with(|| a.1.name.cmp(&b.1.name))
                .then_with(|| a.1.id.cmp(&b.1.id))
        });
        rows.into_iter().take(limit.min(100)).map(|r| r.1).collect()
    }
    pub fn icon(&self, id: &str) -> Result<String, String> {
        let app = self.get(id)?;
        if let Some(icon) = self.icons.lock().unwrap().get(id).cloned() {
            return Ok(icon);
        }
        #[cfg(windows)]
        let icon = crate::discovery::icon(&app.target)?;
        #[cfg(not(windows))]
        let icon: String = {
            let _ = app;
            return Err("Windows icons unavailable".into());
        };
        self.icons.lock().unwrap().insert(id.into(), icon.clone());
        Ok(icon)
    }
    pub fn launch(&self, id: &str) -> Result<String, String> {
        let app = self.get(id)?;
        #[cfg(windows)]
        crate::discovery::launch(&app.target)?;
        #[cfg(not(windows))]
        return Err("App launching is Windows-only".into());
        Ok(format!("Opened {}", app.name))
    }
    pub fn refresh(&self, app: &tauri::AppHandle) {
        if self.scanning.swap(true, Ordering::AcqRel) {
            return;
        }
        let _ = app.emit("apps-updated", self.status());
        #[cfg(windows)]
        let (mut entries, errors) = crate::discovery::scan();
        #[cfg(not(windows))]
        let (mut entries, errors): (Vec<App>, Vec<String>) =
            (vec![], vec!["App indexing is Windows-only".into()]);
        entries.sort_by(|a, b| a.id.cmp(&b.id));
        entries.dedup_by(|a, b| a.id == b.id);
        let count = entries.len();
        *self.entries.write().unwrap() = entries;
        self.icons.lock().unwrap().clear();
        *self.status.lock().unwrap() = IndexStatus {
            count,
            updated_at: now(),
            errors,
            scanning: false,
        };
        self.scanning.store(false, Ordering::Release);
        let _ = app.emit("apps-updated", self.status());
    }
    pub fn start(app: tauri::AppHandle) {
        std::thread::spawn(move || loop {
            if app.get_webview_window("main").is_none() {
                break;
            }
            app.state::<crate::AppState>().catalog.refresh(&app);
            std::thread::sleep(std::time::Duration::from_secs(300));
        });
    }
    pub fn favourite(&self, id: &str) -> Result<Pin, String> {
        let app = self.get(id)?;
        Ok(Pin {
            id: app.id.clone(),
            name: app.name.chars().take(80).collect(),
            path: String::new(),
            visible: true,
            app_id: Some(app.id),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn registry_paths_are_not_command_lines() {
        assert_eq!(
            registered_path("\"C:/Program Files/App/app.exe\""),
            Some("C:/Program Files/App/app.exe".into())
        );
        for bad in [
            "calc.exe",
            "C:/app.exe --bad",
            "\"C:/app.exe\" --bad",
            "\\\\server\\a.exe",
            "C:/a/../b.exe",
            "C:/a.bat",
        ] {
            assert!(registered_path(bad).is_none(), "{bad}");
        }
    }
    #[test]
    fn ranking_recency_and_id_boundary() {
        let catalog = Catalog::default();
        let chrome = App::new(
            "Chrome".into(),
            "Start Menu",
            Target::Executable("C:/chrome.exe".into()),
        )
        .unwrap();
        let beta = App::new(
            "Chrome Beta".into(),
            "App Paths",
            Target::Executable("C:/beta.exe".into()),
        )
        .unwrap();
        let mut config = Config::default();
        config.recent_apps.push(crate::config::RecentApp {
            id: beta.id.clone(),
            last_used: now(),
            count: 30,
        });
        *catalog.entries.write().unwrap() = vec![beta.clone(), chrome.clone()];
        assert_eq!(catalog.search("Chrome", &config, 6)[0].id, chrome.id);
        assert_eq!(catalog.search("chr", &config, 6)[0].id, beta.id);
        assert!(catalog
            .search("chorme", &config, 6)
            .iter()
            .any(|a| a.id == chrome.id));
        assert!(catalog.search("C:/chrome.exe", &config, 6).is_empty());
        assert!(catalog.launch("C:/chrome.exe").is_err());
        assert!(catalog.get("unknown").is_err());
        assert!(valid_aumid("Microsoft.Calculator_123!App"));
        assert!(!valid_aumid("x!app -Command something"));
        assert_eq!(
            chrome.id,
            App::new(
                "Renamed".into(),
                "Different",
                Target::Executable("c:\\chrome.exe".into())
            )
            .unwrap()
            .id
        );
    }
}
