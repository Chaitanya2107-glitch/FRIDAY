use crate::{
    catalog::{Catalog, IndexStatus, Match},
    config::{self, Config, RecentApp},
    shell::{LocalAction, LocalResult},
    AppState,
};
use std::{path::Path, sync::Arc};
use tauri::State;

#[tauri::command]
pub async fn search_apps(query: String, state: State<'_, AppState>) -> Result<Vec<Match>, String> {
    let config = crate::get_config(state.clone()).await?;
    Ok(state.catalog.search(&query, &config, 100))
}
#[tauri::command]
pub fn app_index_status(state: State<'_, AppState>) -> IndexStatus {
    state.catalog.status()
}
#[tauri::command]
pub async fn rescan_apps(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<IndexStatus, String> {
    let catalog = Arc::clone(&state.catalog);
    tauri::async_runtime::spawn_blocking(move || catalog.refresh(&app))
        .await
        .map_err(|e| e.to_string())?;
    Ok(state.catalog.status())
}
#[tauri::command]
pub async fn app_icon(id: String, state: State<'_, AppState>) -> Result<String, String> {
    let catalog = Arc::clone(&state.catalog);
    tauri::async_runtime::spawn_blocking(move || catalog.icon(&id))
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
pub async fn toggle_app_pin(id: String, state: State<'_, AppState>) -> Result<Config, String> {
    let path = state.path.clone();
    let catalog = Arc::clone(&state.catalog);
    tauri::async_runtime::spawn_blocking(move || {
        let mut config = config::load(&path)?;
        if let Some(index) = config
            .pins
            .iter()
            .position(|p| p.app_id.as_deref() == Some(&id))
        {
            config.pins.remove(index);
        } else {
            config.pins.push(catalog.favourite(&id)?);
        }
        config::save(&path, config)
    })
    .await
    .map_err(|e| e.to_string())?
}
pub fn resolve(text: &str, config: &Config, catalog: &Catalog) -> LocalResult {
    let trimmed = text.trim();
    let (head, query) = trimmed.split_once(' ').unwrap_or((trimmed, ""));
    if head.eq_ignore_ascii_case("open") {
        if text.len() <= 4000 && !query.trim().is_empty() {
            if let Some(found) = catalog.search(query, config, 1).first() {
                return LocalResult {
                    text: format!("Opening {}", found.name),
                    ok: true,
                    action: Some(LocalAction {
                        kind: found.kind.clone(),
                        id: found.id.clone(),
                    }),
                };
            }
        }
        return LocalResult {
            text: "No app found. Rescan apps in Settings.".into(),
            ok: false,
            action: None,
        };
    }
    crate::shell::local_command(text, config)
}
fn remember(path: &Path, id: &str) -> Result<(), String> {
    for _ in 0..3 {
        let mut config = config::load(path)?;
        let previous = config
            .recent_apps
            .iter()
            .find(|r| r.id == id)
            .map_or(0, |r| r.count);
        config.recent_apps.retain(|r| r.id != id);
        config.recent_apps.insert(
            0,
            RecentApp {
                id: id.into(),
                last_used: crate::catalog::now(),
                count: previous.saturating_add(1),
            },
        );
        config.recent_apps.truncate(100);
        if config::save(path, config).is_ok() {
            return Ok(());
        }
    }
    Err("Recent app history could not be saved".into())
}
pub fn launch(path: &Path, catalog: &Catalog, kind: &str, id: &str) -> Result<String, String> {
    let mut config = config::load(path)?;
    let app_id = if kind == "app" {
        Some(id.to_string())
    } else if kind == "pin" {
        config
            .pins
            .iter()
            .find(|p| p.id == id)
            .and_then(|p| p.app_id.clone())
    } else {
        None
    };
    let result = if let Some(id) = &app_id {
        catalog.launch(id)?
    } else {
        crate::shell::launch(&mut config, kind, id)?
    };
    if kind == "project" {
        if config::save(path, config).is_err() {
            return Ok(format!(
                "{result} · Last-opened time could not be saved; reload Settings."
            ));
        }
    } else {
        let recent_id = app_id.unwrap_or_else(|| format!("pin-{id}"));
        if remember(path, &recent_id).is_err() {
            return Ok(format!("{result} · Recent history could not be saved."));
        }
    }
    Ok(result)
}
