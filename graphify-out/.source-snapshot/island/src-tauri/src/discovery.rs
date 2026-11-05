//! Read installed-app metadata through local Windows APIs. Never scan PATH or disks.
use crate::catalog::{registered_path, valid_aumid, App, Target};
use std::{
    fs,
    os::windows::fs::MetadataExt,
    path::{Path, PathBuf},
};
use windows::{
    core::{Interface, PCWSTR, PWSTR},
    Win32::{
        Foundation::{PROPERTYKEY, SIZE},
        Graphics::Gdi::DeleteObject,
        System::Com::{
            CoCreateInstance, CoInitializeEx, CoTaskMemFree, CoUninitialize, CLSCTX_INPROC_SERVER,
            COINIT_APARTMENTTHREADED,
        },
        UI::Shell::*,
    },
};
use winreg::{enums::*, RegKey};

struct Com(bool);
impl Com {
    fn new() -> Self {
        Self(unsafe { CoInitializeEx(None, COINIT_APARTMENTTHREADED).is_ok() })
    }
}
impl Drop for Com {
    fn drop(&mut self) {
        if self.0 {
            unsafe {
                CoUninitialize();
            }
        }
    }
}
unsafe fn take_string(value: PWSTR) -> String {
    let text = value.to_string().unwrap_or_default();
    CoTaskMemFree(Some(value.0 as _));
    text
}
fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}

pub fn shortcuts(root: &Path, output: &mut Vec<App>, depth: usize) {
    if !crate::config::safe_path(&root.to_string_lossy()) || depth > 12 || output.len() >= 10000 {
        return;
    }
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten().take(20000) {
        let path = entry.path();
        let Ok(meta) = fs::symlink_metadata(&path) else {
            continue;
        };
        if meta.file_attributes() & 0x400 != 0 {
            continue;
        } // no junctions/reparse points
        if meta.is_dir() {
            shortcuts(&path, output, depth + 1);
        } else if path
            .extension()
            .is_some_and(|e| e.eq_ignore_ascii_case("lnk"))
        {
            let name = path
                .file_stem()
                .unwrap_or_default()
                .to_string_lossy()
                .into_owned();
            if name.to_lowercase().starts_with("uninstall") {
                continue;
            }
            if let Some(app) = App::new(
                name,
                "Start Menu",
                Target::Shortcut(path.to_string_lossy().into()),
            ) {
                output.push(app);
            }
        }
        if output.len() >= 10000 {
            break;
        }
    }
}
fn expand(value: &str) -> String {
    use windows_sys::Win32::System::Environment::ExpandEnvironmentStringsW;
    let value = wide(value);
    let mut buffer = vec![0u16; 32768];
    let length = unsafe {
        ExpandEnvironmentStringsW(value.as_ptr(), buffer.as_mut_ptr(), buffer.len() as u32)
    };
    if length == 0 || length as usize > buffer.len() {
        return String::new();
    }
    String::from_utf16_lossy(&buffer[..length as usize - 1])
}
fn registry(output: &mut Vec<App>) {
    for hive in [HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE] {
        for view in [KEY_WOW64_64KEY, KEY_WOW64_32KEY] {
            let Ok(root) = RegKey::predef(hive).open_subkey_with_flags(
                "Software\\Microsoft\\Windows\\CurrentVersion\\App Paths",
                KEY_READ | view,
            ) else {
                continue;
            };
            for name in root.enum_keys().flatten().take(10000) {
                let Ok(key) = root.open_subkey_with_flags(&name, KEY_READ | view) else {
                    continue;
                };
                let Ok(value) = key.get_value::<String, _>("") else {
                    continue;
                };
                let Some(path) = registered_path(&expand(&value)) else {
                    continue;
                };
                if !Path::new(&path).is_file() {
                    continue;
                }
                let name = Path::new(&name)
                    .file_stem()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned();
                if let Some(app) = App::new(name, "App Paths", Target::Executable(path)) {
                    output.push(app);
                }
            }
        }
    }
}
unsafe fn packaged(output: &mut Vec<App>) -> windows::core::Result<()> {
    let folder: IShellItem = SHGetKnownFolderItem(&FOLDERID_AppsFolder, KF_FLAG_DEFAULT, None)?;
    let enumerator: IEnumShellItems = folder.BindToHandler(None, &BHID_EnumItems)?;
    let key = PROPERTYKEY {
        fmtid: windows::core::GUID::from_u128(0x9f4c2855_9f79_4b39_a8d0_e1d42de1d5f3),
        pid: 5,
    };
    for _ in 0..10000 {
        let mut items = [None];
        let mut fetched = 0;
        if enumerator.Next(&mut items, Some(&mut fetched)).is_err() || fetched == 0 {
            break;
        }
        let Some(item) = items[0].take() else {
            continue;
        };
        let Ok(details) = item.cast::<IShellItem2>() else {
            continue;
        };
        let Ok(aumid) = details.GetString(&key) else {
            continue;
        };
        let aumid = take_string(aumid);
        if !valid_aumid(&aumid) {
            continue;
        }
        let Ok(name) = item.GetDisplayName(SIGDN_NORMALDISPLAY) else {
            continue;
        };
        if let Some(app) = App::new(take_string(name), "Windows Store", Target::Packaged(aumid)) {
            output.push(app);
        }
    }
    Ok(())
}
pub fn scan() -> (Vec<App>, Vec<String>) {
    let _com = Com::new();
    let mut apps = vec![];
    let mut errors = vec![];
    for id in [FOLDERID_Programs, FOLDERID_CommonPrograms] {
        match unsafe { SHGetKnownFolderPath(&id, KF_FLAG_DEFAULT, None) } {
            Ok(path) => {
                let path = unsafe { take_string(path) };
                shortcuts(&PathBuf::from(path), &mut apps, 0);
            }
            Err(_) => errors.push("A Start Menu folder could not be read".into()),
        }
    }
    registry(&mut apps);
    if unsafe { packaged(&mut apps) }.is_err() {
        errors.push(
            "Windows Store app enumeration unavailable; Start Menu and App Paths still work".into(),
        );
    }
    (apps, errors)
}
pub fn launch(target: &Target) -> Result<(), String> {
    match target {
        Target::Shortcut(path) | Target::Executable(path) => {
            if !crate::config::safe_path(path) || !Path::new(path).is_file() {
                return Err("App is missing. Rescan apps in Settings.".into());
            }
            crate::shell::shell_open(path)
        }
        Target::Packaged(id) => {
            if !valid_aumid(id) {
                return Err("Invalid indexed app ID".into());
            }
            let _com = Com::new();
            unsafe {
                let manager: IApplicationActivationManager =
                    CoCreateInstance(&ApplicationActivationManager, None, CLSCTX_INPROC_SERVER)
                        .map_err(|e| e.to_string())?;
                manager
                    .ActivateApplication(PCWSTR(wide(id).as_ptr()), PCWSTR::null(), AO_NOERRORUI)
                    .map_err(|e| format!("Windows could not activate this app: {e}"))?;
            }
            Ok(())
        }
    }
}
pub fn icon(target: &Target) -> Result<String, String> {
    match target {
        Target::Shortcut(path) | Target::Executable(path) => crate::picker::icon(path),
        Target::Packaged(id) => {
            let _com = Com::new();
            unsafe {
                let name = wide(&format!("shell:AppsFolder\\{id}"));
                let item: IShellItem = SHCreateItemFromParsingName(PCWSTR(name.as_ptr()), None)
                    .map_err(|e| e.to_string())?;
                let factory: IShellItemImageFactory = item.cast().map_err(|e| e.to_string())?;
                let bitmap = factory
                    .GetImage(SIZE { cx: 32, cy: 32 }, SIIGBF_ICONONLY)
                    .map_err(|e| e.to_string())?;
                let result = crate::picker::bitmap_png(bitmap.0 as _);
                let _ = DeleteObject(bitmap.into());
                result
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore = "Reads real installed app metadata; explicit local validation only"]
    fn live_installed_app_metadata() {
        let (apps, errors) = scan();
        assert!(
            !apps.is_empty(),
            "No installed app metadata found: {errors:?}"
        );
        let counts = ["Start Menu", "App Paths", "Windows Store"]
            .map(|source| (source, apps.iter().filter(|a| a.source == source).count()));
        for source in ["Start Menu", "Windows Store"] {
            if let Some(app) = apps.iter().find(|a| a.source == source) {
                assert!(icon(&app.target)
                    .unwrap()
                    .starts_with("data:image/png;base64,"));
            }
        }
        println!("Installed app source counts: {counts:?}; warnings: {errors:?}");
    }
    #[test]
    fn start_menu_walk_is_bounded_and_only_shortcuts() {
        let root = std::env::temp_dir().join(format!("island-index-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("Sub")).unwrap();
        fs::write(root.join("Sub/Editor.lnk"), b"fixture").unwrap();
        fs::write(root.join("ignore.bat"), b"fixture").unwrap();
        fs::write(root.join("Uninstall Editor.lnk"), b"fixture").unwrap();
        let mut apps = vec![];
        shortcuts(&root, &mut apps, 0);
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0].name, "Editor");
        fs::remove_dir_all(root).unwrap();
    }
}
