//! Local battery and Windows media-session access, independent of the Python bridge.
use serde::{Deserialize, Serialize};

#[derive(Default, Serialize)]
pub struct DesktopStatus {
    battery: Option<Battery>,
    media: Option<Media>,
}

#[derive(Debug, PartialEq, Serialize)]
pub struct Battery {
    percent: Option<u8>,
    charging: bool,
    plugged_in: Option<bool>,
}

#[derive(Serialize)]
pub struct Media {
    source: String,
    title: String,
    artist: String,
    playing: bool,
    can_toggle: bool,
    can_previous: bool,
    can_next: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MediaAction {
    Toggle,
    Previous,
    Next,
}

fn battery_status(ac: u8, flags: u8, percent: u8) -> Option<Battery> {
    if flags != 255 && flags & 128 != 0 {
        return None;
    }
    Some(Battery {
        percent: (percent <= 100).then_some(percent),
        charging: flags != 255 && flags & 8 != 0,
        plugged_in: match ac {
            0 => Some(false),
            1 => Some(true),
            _ => None,
        },
    })
}

#[tauri::command]
pub async fn desktop_status() -> Result<DesktopStatus, String> {
    tauri::async_runtime::spawn_blocking(read)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn media_control(action: MediaAction, source: String) -> Result<(), String> {
    if source.is_empty() || source.len() > 2048 {
        return Err("The media player changed. Try again.".into());
    }
    tauri::async_runtime::spawn_blocking(move || control(action, &source))
        .await
        .map_err(|e| e.to_string())?
}

#[cfg(not(windows))]
fn read() -> DesktopStatus {
    DesktopStatus::default()
}
#[cfg(not(windows))]
fn control(_action: MediaAction, _source: &str) -> Result<(), String> {
    Err("Media controls are available on Windows.".into())
}

#[cfg(windows)]
use platform::{control, read};

#[cfg(windows)]
mod platform {
    use super::*;
    use std::{sync::mpsc, time::Duration};
    use windows::{
        core::Result as WinResult,
        Media::Control::{
            GlobalSystemMediaTransportControlsSessionManager as SessionManager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
        },
        Win32::System::{
            Power::{GetSystemPowerStatus, SYSTEM_POWER_STATUS},
            WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED},
        },
    };

    // Bound WinRT waits so a stalled player cannot freeze polling or its buttons.
    // The completion owns its sender; cancellation after timeout is safe.
    macro_rules! wait {
        ($operation:expr) => {{
            let operation = $operation?;
            let (sender, receiver) = mpsc::sync_channel(1);
            operation.when(move |result| {
                let _ = sender.send(result);
            })?;
            match receiver.recv_timeout(Duration::from_secs(3)) {
                Ok(result) => result?,
                Err(_) => {
                    let _ = operation.Cancel();
                    return Err(windows::core::Error::new(
                        windows::core::HRESULT(0x800705B4u32 as i32),
                        "Windows media session timed out.",
                    ));
                }
            }
        }};
    }

    struct Apartment;
    impl Apartment {
        fn new() -> WinResult<Self> {
            unsafe { RoInitialize(RO_INIT_MULTITHREADED)? };
            Ok(Self)
        }
    }
    impl Drop for Apartment {
        fn drop(&mut self) {
            unsafe { RoUninitialize() };
        }
    }

    pub fn read() -> DesktopStatus {
        let mut power = SYSTEM_POWER_STATUS::default();
        let battery = unsafe { GetSystemPowerStatus(&mut power) }
            .ok()
            .and_then(|_| {
                battery_status(
                    power.ACLineStatus,
                    power.BatteryFlag,
                    power.BatteryLifePercent,
                )
            });
        // OS/session failures never prevent the clock or battery from working.
        DesktopStatus {
            battery,
            media: media().ok().flatten(),
        }
    }

    fn media() -> WinResult<Option<Media>> {
        let _apartment = Apartment::new()?;
        let manager = wait!(SessionManager::RequestAsync());
        let session = match manager.GetCurrentSession() {
            Ok(session) => session,
            Err(_) => return Ok(None),
        };
        let info = session.GetPlaybackInfo()?;
        let status = info.PlaybackStatus()?;
        if status != PlaybackStatus::Playing && status != PlaybackStatus::Paused {
            return Ok(None);
        }
        let properties = wait!(session.TryGetMediaPropertiesAsync());
        let controls = info.Controls()?;
        let playing = status == PlaybackStatus::Playing;
        Ok(Some(Media {
            source: session.SourceAppUserModelId()?.to_string(),
            title: properties.Title()?.to_string().chars().take(512).collect(),
            artist: properties.Artist()?.to_string().chars().take(256).collect(),
            playing,
            can_toggle: controls.IsPlayPauseToggleEnabled()?
                || if playing {
                    controls.IsPauseEnabled()?
                } else {
                    controls.IsPlayEnabled()?
                },
            can_previous: controls.IsPreviousEnabled()?,
            can_next: controls.IsNextEnabled()?,
        }))
    }

    pub fn control(action: MediaAction, source: &str) -> Result<(), String> {
        control_inner(action, source).map_err(|e| e.to_string())
    }

    fn control_inner(action: MediaAction, source: &str) -> WinResult<()> {
        let _apartment = Apartment::new()?;
        let manager = wait!(SessionManager::RequestAsync());
        let session = manager.GetCurrentSession()?;
        if session.SourceAppUserModelId()?.to_string() != source {
            return Err(windows::core::Error::new(
                windows::core::HRESULT(0x80004005u32 as i32),
                "The media player changed. Try again.",
            ));
        }
        let info = session.GetPlaybackInfo()?;
        let controls = info.Controls()?;
        let accepted = match action {
            MediaAction::Previous if controls.IsPreviousEnabled()? => {
                wait!(session.TrySkipPreviousAsync())
            }
            MediaAction::Next if controls.IsNextEnabled()? => wait!(session.TrySkipNextAsync()),
            MediaAction::Toggle if controls.IsPlayPauseToggleEnabled()? => {
                wait!(session.TryTogglePlayPauseAsync())
            }
            MediaAction::Toggle
                if info.PlaybackStatus()? == PlaybackStatus::Playing
                    && controls.IsPauseEnabled()? =>
            {
                wait!(session.TryPauseAsync())
            }
            MediaAction::Toggle
                if info.PlaybackStatus()? != PlaybackStatus::Playing
                    && controls.IsPlayEnabled()? =>
            {
                wait!(session.TryPlayAsync())
            }
            _ => false,
        };
        if accepted {
            Ok(())
        } else {
            Err(windows::core::Error::new(
                windows::core::HRESULT(0x80004005u32 as i32),
                "This player doesn't support that control.",
            ))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn battery_flags_distinguish_unknown_missing_and_charging() {
        assert_eq!(
            battery_status(1, 8, 65),
            Some(Battery {
                percent: Some(65),
                charging: true,
                plugged_in: Some(true)
            })
        );
        assert_eq!(
            battery_status(255, 255, 255),
            Some(Battery {
                percent: None,
                charging: false,
                plugged_in: None
            })
        );
        assert_eq!(battery_status(0, 4, 0).unwrap().percent, Some(0));
        assert_eq!(battery_status(1, 128, 255), None);
    }

    #[test]
    fn media_actions_are_a_fixed_enum() {
        assert!(serde_json::from_str::<MediaAction>("\"toggle\"").is_ok());
        for value in ["\"launch\"", "\"powershell\"", "{}", "\"open spotify\""] {
            assert!(serde_json::from_str::<MediaAction>(value).is_err());
        }
    }
}
