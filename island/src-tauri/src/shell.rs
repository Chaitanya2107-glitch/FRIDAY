//! Only persisted configuration can name an executable, URL, or argument.
use crate::config::{Action, Config};
use serde::Serialize;
use std::{path::Path, process::Command};

#[cfg(windows)]
pub fn wide(text: &str) -> Vec<u16> { text.encode_utf16().chain(Some(0)).collect() }

#[cfg(windows)]
fn shell_open(path: &str) -> Result<(), String> {
    use windows_sys::Win32::UI::{Shell::ShellExecuteW, WindowsAndMessaging::SW_SHOWNORMAL};
    let target = wide(path);
    let result = unsafe { ShellExecuteW(std::ptr::null_mut(), wide("open").as_ptr(), target.as_ptr(),
        std::ptr::null(), std::ptr::null(), SW_SHOWNORMAL) };
    if result as isize <= 32 { Err(format!("Windows could not open this item (code {}).", result as isize)) } else { Ok(()) }
}
#[cfg(not(windows))]
fn shell_open(_path: &str) -> Result<(), String> { Err("Launching is implemented for Windows in v1".into()) }

fn execute(executable: &str, args: &[String], folder: &str, terminal: bool) -> Result<(), String> {
    let mut command = Command::new(executable);
    command.args(args.iter().map(|a| a.replace("{path}", folder))).current_dir(folder);
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(if terminal { 0x00000010 } else { 0x08000000 });
    }
    command.spawn().map(|_| ()).map_err(|e| format!("Configured program failed: {e}"))
}

pub fn launch(config: &mut Config, kind: &str, id: &str) -> Result<String, String> {
    config.validate()?;
    match kind {
        "pin" => {
            let pin = config.pins.iter().find(|p| p.id == id && p.visible).ok_or("App is not configured or is hidden")?;
            if !Path::new(&pin.path).is_file() { return Err("Configured app is missing".into()); }
            shell_open(&pin.path)?;
            Ok(format!("Opened {}", pin.name))
        }
        "project" => {
            let project = config.projects.iter_mut().find(|p| p.id == id).ok_or("Project is not configured")?;
            if !Path::new(&project.path).is_dir() { return Err("Project folder is missing".into()); }
            if project.actions.is_empty() { return Err("Add at least one open action in Settings".into()); }
            for (completed, action) in project.actions.iter().enumerate() {
                let result = match action {
                    Action::Folder => shell_open(&project.path),
                    Action::Url { url } => shell_open(url),
                    Action::Editor { executable, args } => execute(executable, args, &project.path, false),
                    Action::Terminal { executable, args } => execute(executable, args, &project.path, true),
                };
                if let Err(error) = result { return Err(format!("{completed} action(s) opened; {error}")); }
            }
            project.last_opened = Some(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default().as_secs().to_string());
            Ok(format!("Opened {}", project.name))
        }
        _ => Err("Unsupported action; only configured apps/projects can launch".into()),
    }
}

#[derive(Serialize)]
pub struct LocalResult { pub text: String, pub ok: bool, pub action: Option<LocalAction> }
#[derive(Serialize)]
pub struct LocalAction { pub kind: String, pub id: String }
fn score(query: &str, name: &str) -> u8 {
    let (q, n) = (query.trim().to_lowercase(), name.to_lowercase());
    if q.is_empty() { return 0; }
    if n.starts_with(&q) { return 3; }
    if n.contains(&q) { return 2; }
    let mut chars = n.chars();
    if q.chars().all(|c| chars.by_ref().any(|v| v == c)) { 1 } else { 0 }
}
pub fn local_command(text: &str, config: &Config) -> LocalResult {
    let trimmed = text.trim();
    let (head, tail) = trimmed.split_once(' ').unwrap_or((trimmed, ""));
    let result = |text: &str, action: Option<LocalAction>| LocalResult { text: text.into(), ok: action.is_some(), action };
    if text.len() > 4000 || text.contains('\0') { return result("Invalid command", None); }
    if head.eq_ignore_ascii_case("settings") {
        return result("Settings", Some(LocalAction { kind: "settings".into(), id: String::new() }));
    }
    let (kind, items): (&str, Vec<(&str, &str)>) = match head.to_lowercase().as_str() {
        "open" => ("pin", config.pins.iter().filter(|p| p.visible).map(|p| (p.id.as_str(), p.name.as_str())).collect()),
        "proj" => ("project", config.projects.iter().map(|p| (p.id.as_str(), p.name.as_str())).collect()),
        _ => return result("FRIDAY offline · apps, projects and settings still work", None),
    };
    let mut ranked: Vec<_> = items.iter().map(|(id, name)| (score(tail, name), id)).filter(|p| p.0 > 0).collect();
    ranked.sort_by(|a, b| b.0.cmp(&a.0));
    if ranked.is_empty() { return result("No configured match. Add it in Settings.", None); }
    if ranked.len() > 1 && ranked[0].0 == ranked[1].0 { return result("More than one match. Use a longer name.", None); }
    result("Opening configured item", Some(LocalAction { kind: kind.into(), id: (*ranked[0].1).into() }))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn arbitrary_launches_are_rejected() {
        let mut config = Config::default();
        assert!(launch(&mut config, "shell", "powershell.exe").is_err());
        assert!(launch(&mut config, "pin", "not-configured").is_err());
        assert!(!local_command("open calc.exe", &config).ok);
        assert!(local_command("settings", &config).ok);
        assert!(!local_command("who am I", &config).ok);
    }
}
