//! Own only the bridge we spawn; closing its job also handles Island crashes.
use std::{
    fs::OpenOptions,
    path::Path,
    process::{Child, Command, Stdio},
};

pub struct BridgeProcess {
    pub child: Child,
    #[cfg(windows)]
    _job: Job,
}
impl BridgeProcess {
    pub fn spawn(root: &Path, config: &Path) -> Result<Self, String> {
        let logs = config.parent().ok_or("Missing config folder")?;
        let out = OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs.join("bridge.log"))
            .map_err(|e| e.to_string())?;
        let err = OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs.join("bridge-error.log"))
            .map_err(|e| e.to_string())?;
        let python = root.join(if cfg!(windows) {
            "venv/Scripts/python.exe"
        } else {
            "venv/bin/python"
        });
        let mut command = Command::new(python);
        command
            .current_dir(root)
            .args(["-B", "-m", "services.friday_island_server", "--config"])
            .arg(config)
            .stdin(Stdio::null())
            .stdout(out)
            .stderr(err);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // Start suspended: the venv launcher must enter the job before it
            // can create the real Python process, otherwise that child escapes.
            command.creation_flags(0x08000000 | 0x00000004);
        }
        #[cfg(windows)]
        let job = Job::new()?;
        let mut child = command
            .spawn()
            .map_err(|e| format!("Could not start FRIDAY's Python: {e}"))?;
        #[cfg(windows)]
        if let Err(error) = job.assign(&child).and_then(|_| resume(&child)) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
        Ok(Self {
            child,
            #[cfg(windows)]
            _job: job,
        })
    }
}

#[cfg(windows)]
fn resume(child: &Child) -> Result<(), String> {
    use windows_sys::Win32::{
        Foundation::{CloseHandle, INVALID_HANDLE_VALUE},
        System::{
            Diagnostics::ToolHelp::*,
            Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME},
        },
    };
    // A suspended, not-yet-started child has one thread. Stable Rust doesn't
    // expose its main thread handle; select it by this owned process's ID.
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if snapshot == INVALID_HANDLE_VALUE {
            return Err(std::io::Error::last_os_error().to_string());
        }
        let mut entry: THREADENTRY32 = std::mem::zeroed();
        entry.dwSize = std::mem::size_of_val(&entry) as u32;
        let mut found = Thread32First(snapshot, &mut entry) != 0;
        let mut result = Err("Could not find the owned bridge's startup thread".into());
        while found {
            if entry.th32OwnerProcessID == child.id() {
                let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                if thread.is_null() {
                    result = Err(std::io::Error::last_os_error().to_string());
                } else {
                    result = if ResumeThread(thread) == u32::MAX {
                        Err(std::io::Error::last_os_error().to_string())
                    } else {
                        Ok(())
                    };
                    CloseHandle(thread);
                }
                break;
            }
            found = Thread32Next(snapshot, &mut entry) != 0;
        }
        CloseHandle(snapshot);
        result
    }
}
impl Drop for BridgeProcess {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[cfg(windows)]
struct Job(windows_sys::Win32::Foundation::HANDLE);
#[cfg(windows)]
impl Job {
    fn new() -> Result<Self, String> {
        use windows_sys::Win32::System::JobObjects::*;
        unsafe {
            let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if handle.is_null() {
                return Err(std::io::Error::last_os_error().to_string());
            }
            let job = Self(handle);
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &limits as *const _ as _,
                std::mem::size_of_val(&limits) as u32,
            ) == 0
            {
                return Err(std::io::Error::last_os_error().to_string());
            }
            Ok(job)
        }
    }
    fn assign(&self, child: &Child) -> Result<(), String> {
        use std::os::windows::io::AsRawHandle;
        if unsafe {
            windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(
                self.0,
                child.as_raw_handle(),
            )
        } == 0
        {
            Err(format!(
                "Could not bind bridge lifetime: {}",
                std::io::Error::last_os_error()
            ))
        } else {
            Ok(())
        }
    }
}
#[cfg(windows)]
impl Drop for Job {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.0);
        }
    }
}
