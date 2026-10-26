"""
services/automation/system_control.py

System control service for F.R.I.D.A.Y.
Lets FRIDAY control the laptop — apps, files, volume, brightness, clipboard.

WHAT IT CAN DO:
  - Open or close any registered app by name
  - Open Chrome and search Google
  - Open a specific URL in Chrome
  - Organise files in a folder by type
  - Open File Explorer at a specific path
  - Set, raise, lower or mute the volume
  - Set, raise or lower screen brightness (built-in laptop screens only)
  - Read or write clipboard text
  - Take a screenshot (saved to Pictures/Screenshots)

HOW IT WORKS:
  The AI interprets the user's command and calls the right function here.
  This service never calls the AI — it only executes actions.

ADDING A NEW APP:
  Usually nothing to do: an app that isn't in APP_REGISTRY is looked up with
  Everything (services/automation/app_finder.py). Add it to APP_REGISTRY only
  if Everything can't find it (Store apps) or picks the wrong program; if it
  isn't a plain .exe (Store app, shortcut), also add its process name to
  PROCESS_NAMES so FRIDAY can close it too

FUTURE (Phase 5+):
  - Mouse/keyboard control (pyautogui)
  - File search
  - Window management (minimize, maximize)
"""

import os
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import comtypes
from PIL import ImageGrab
from pycaw.pycaw import AudioUtilities

from core.logger import logger
from core.errors import FridayError
from services.automation import app_finder, clipboard


# ── Custom error ──────────────────────────────────────────────────────────────

class AutomationError(FridayError):
    """Raised when a system control action fails."""
    pass


# ── App registry ──────────────────────────────────────────────────────────────
# Maps friendly names → executable paths.
# Add any app here and FRIDAY can open it by name.
# Keys are lowercase — matching is case-insensitive.

APP_REGISTRY: dict[str, str] = {
    # Browsers
    "chrome":       r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "edge":         r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",

    # Communication
    "whatsapp":     r"shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",

    # Virtualisation
    "virtualbox":   r"C:\Program Files\Oracle\VirtualBox\VirtualBox.exe",
    "virtual box":  r"C:\Program Files\Oracle\VirtualBox\VirtualBox.exe",

    # Games
    "black myth":           r"C:\games\Black Myth Wukong\b1.exe",
    "black myth wukong":    r"C:\games\Black Myth Wukong\b1.exe",
    "wukong":               r"C:\games\Black Myth Wukong\b1.exe",
    "expedition 33":        r"C:\games\Expedition 33\Expedition33_Steam.exe",
    "expedition":           r"C:\games\Expedition 33\Expedition33_Steam.exe",

    # System tools
    # Store apps by their Start-menu ID: "notepad.exe"/"calc.exe" are old redirect stubs, and a cold start
    # through them can leave the app without its runtime ("Microsoft.UI.Windowing.Core.dll was not found")
    "notepad":      r"shell:AppsFolder\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
    "calculator":   r"shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
    "explorer":     r"explorer.exe",
    "task manager": r"taskmgr.exe",
    "windows terminal": r"wt.exe",  # an app alias (Store app), so Everything can't find it
    "terminal":     r"wt.exe",
    "settings":     r"ms-settings:",

    # Music
    "spotify":  r"C:\Users\chait\Desktop\Spotify - Shortcut.lnk"
}

# Running process names for apps whose registry entry isn't a plain .exe
# (Store apps, shortcuts, URIs) or whose process differs from the launcher.
PROCESS_NAMES: dict[str, list[str]] = {
    "whatsapp":   ["WhatsApp.exe", "WhatsApp.Root.exe"],
    "notepad":    ["Notepad.exe"],
    "spotify":    ["Spotify.exe"],
    "calculator": ["CalculatorApp.exe", "calc.exe"],
    "settings":   ["SystemSettings.exe"],
    "windows terminal": ["WindowsTerminal.exe"],
    "terminal":   ["WindowsTerminal.exe"],
}

# Explorer also runs the taskbar and desktop — "close explorer" would take them down.
UNCLOSABLE_APPS = {"explorer"}
FOCUS_WAIT_SECONDS = 8  # how long to wait for an opened app's window to bring it to the front
# Folders shared by many apps: closing by folder there would hit unrelated programs
SHARED_FOLDERS = {"program files", "program files (x86)", "programs", "desktop", "downloads", "documents",
                  "system32", "windows", "bin", "games", "appdata", "local", "roaming"}
SCREENSHOT_DIR = Path.home() / "Pictures" / "Screenshots"


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def folder_display_name(folder_path: str) -> str:
    """The folder's own name for replies (which are also spoken) — "Downloads", not its full path."""
    return Path(folder_path).name or str(folder_path)


def _run_hidden(args: list[str]) -> subprocess.CompletedProcess:
    """Run a console command without flashing a window (the backend runs hidden)."""
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"Command {args[0]} failed to run: {e}")
        raise AutomationError(f"Couldn't run {args[0]}.")


# ── System Control Service ────────────────────────────────────────────────────

class SystemControl:
    """Handles all system-level actions FRIDAY can perform."""

    last_screenshot: Path | None = None

    def open_app(self, app_name: str) -> str:
        """
        Open a registered application by name.
        Returns a confirmation message.

        Args:
            app_name: Friendly name of the app (e.g. "chrome", "whatsapp")
        """
        key = app_name.lower().strip()

        # Not listed? Ask Everything where it's installed (no path needed in APP_REGISTRY)
        path = APP_REGISTRY.get(key) or app_finder.find_app(key)
        if not path:
            hint = "" if app_finder.es_path() else " (Everything's es.exe isn't installed, so I can only open listed apps)"
            raise AutomationError(f"I couldn't find an app called '{app_name}' on this PC{hint}.")
        logger.info(f"Opening app: {app_name} → {path}")

        from services.learning import origin
        origin.note_open(app=Path(path).stem.lower() if str(path).lower().endswith(".exe") else None)

        try:
            # os.startfile delegates to the shell (ShellExecute), which correctly
            # handles plain .exe paths, .lnk shortcuts, and shell:/ms- URIs alike —
            # subprocess.Popen can only launch real executables directly.
            os.startfile(path)
            threading.Thread(target=self._focus_when_open, args=(key, app_name), daemon=True,
                             name="focus-opened-app").start()
            return f"Opening {app_name.title()}."

        except FileNotFoundError:
            logger.warning(f"Could not find {app_name} at: {path}")
            raise AutomationError(
                f"Couldn't find {app_name.title()}. It may have been moved or uninstalled."
            )
        except Exception as e:
            # Keep the technical detail (WinError codes etc.) in the log only —
            # the user just needs to know it didn't work.
            logger.warning(f"Failed to open {app_name} at {path}: {e}")
            raise AutomationError(f"Couldn't open {app_name.title()}.")

    def _focus_when_open(self, key: str, app_name: str) -> None:
        """
        Bring the opened app's window to the front once it's there. FRIDAY runs in the background, so
        Windows otherwise leaves it behind other windows — or, for an app that was already open (Notepad
        adds a tab to its window), wherever it was, maybe minimized.
        """
        try:
            is_app = self._process_matcher(key, app_name)
        except AutomationError:
            return  # a URI/Store app FRIDAY can't match to a process
        deadline = time.monotonic() + FOCUS_WAIT_SECONDS
        while time.monotonic() < deadline:
            windows = app_finder.app_windows(is_app)  # topmost of the app's windows first
            if windows:
                time.sleep(0.3)  # let a just-opened window finish appearing
                if not app_finder.bring_to_front(windows[0]):
                    logger.info(f"Windows didn't let {app_name} come to the front")
                return
            time.sleep(0.3)

    def close_app(self, app_name: str) -> str:
        """
        Close an app's windows the way Alt+F4 does, so apps can still prompt to
        save unsaved work. Listed apps are matched by process name; others are
        found with Everything and matched by the folder they're installed in
        (a game's launcher often starts a differently named program).
        """
        key = app_name.lower().strip()

        if key in UNCLOSABLE_APPS:
            raise AutomationError(
                f"I won't close {app_name.title()} — it also runs your taskbar and desktop."
            )
        is_app = self._process_matcher(key, app_name)
        windows = app_finder.app_windows(is_app)
        if not windows:
            return f"{app_name.title()} isn't open."

        logger.info(f"Closing app: {app_name} → {len(windows)} window(s)")
        if app_finder.close_windows(windows):
            return f"Closing {app_name.title()}."
        # Windows blocks close messages to apps running as administrator
        raise AutomationError(f"Couldn't close {app_name.title()} — it may be running as administrator.")

    def is_open(self, app_name: str) -> bool:
        """Whether the app (listed, or installed and found by Everything) has a window open."""
        key = app_name.lower().strip()
        try:
            return key not in UNCLOSABLE_APPS and bool(app_finder.app_windows(self._process_matcher(key, app_name)))
        except AutomationError:
            return False  # not installed

    @staticmethod
    def _process_matcher(key: str, app_name: str):
        """Which running processes are this app (for close_app)."""
        if key in PROCESS_NAMES:  # Store apps, shortcuts, URIs
            names = {n.lower() for n in PROCESS_NAMES[key]}
            return lambda proc: proc.name().lower() in names

        found = APP_REGISTRY.get(key) or app_finder.find_app(key)
        program = app_finder.shortcut_target(found) if found and found.lower().endswith(".lnk") else found
        if not program or not program.lower().endswith(".exe"):
            raise AutomationError(f"I couldn't find an app called '{app_name}' on this PC.")
        program = Path(program)
        folder = program.parent
        if not program.is_absolute() or len(folder.parts) < 3 or folder.name.lower() in SHARED_FOLDERS:
            # No folder of its own ("notepad.exe", a loose .exe in Program Files or Desktop): that program only
            return lambda proc: proc.name().lower() == program.name.lower()
        return lambda proc: Path(proc.exe()).is_relative_to(folder)

    def search_chrome(self, query: str) -> str:
        """
        Open Chrome and search Google for the given query.

        Args:
            query: What to search for
        """
        logger.info(f"Chrome search: '{query}'")

        chrome_path = APP_REGISTRY.get("chrome")
        search_url  = f"https://www.google.com/search?q={quote(query)}"

        try:
            if chrome_path and Path(chrome_path).exists():
                subprocess.Popen([chrome_path, search_url])
            else:
                # Fall back to default browser if Chrome not found
                webbrowser.open(search_url)
                return f"Searching for '{query}' in your default browser."

            return f"Searching Google for '{query}'."

        except Exception as e:
            logger.warning(f"Failed to open Chrome search for '{query}': {e}")
            raise AutomationError("Couldn't open Chrome to search.")

    def open_url(self, url: str) -> str:
        """
        Open a specific URL in Chrome.

        Args:
            url: Full URL to open (e.g. "https://youtube.com")
        """
        logger.info(f"Opening URL: {url}")
        from services.learning import origin
        origin.note_open()

        # Add https:// if missing
        if not url.startswith("http"):
            url = "https://" + url

        chrome_path = APP_REGISTRY.get("chrome")

        try:
            if chrome_path and Path(chrome_path).exists():
                subprocess.Popen([chrome_path, url])
            else:
                webbrowser.open(url)

            return f"Opening {url}."

        except Exception as e:
            logger.warning(f"Failed to open URL '{url}': {e}")
            raise AutomationError(f"Couldn't open {url}.")

    def open_folder(self, folder_path: str) -> str:
        """
        Open a folder in File Explorer.

        Args:
            folder_path: Path to the folder (e.g. "C:\\Users\\chait\\Downloads")
        """
        path = Path(folder_path)
        logger.info(f"Opening folder: {folder_path}")

        if not path.exists():
            raise AutomationError(f"Couldn't find the folder {folder_display_name(folder_path)}.")

        from services.learning import origin
        origin.note_open(app="explorer")
        try:
            subprocess.Popen(["explorer.exe", str(path)])
            return f"Opening {folder_display_name(folder_path)}."
        except Exception as e:
            logger.warning(f"Failed to open folder '{folder_path}': {e}")
            raise AutomationError("Couldn't open that folder.")

    def _files_to_organise(self, path: Path) -> list[Path]:
        # Top-level files only — subfolders and hidden files are left alone.
        return [f for f in path.iterdir() if not f.is_dir() and not f.name.startswith(".")]

    def count_files_to_organise(self, folder_path: str) -> int:
        """How many files organise_folder would move — used to ask for confirmation."""
        path = Path(folder_path)
        if not path.exists():
            raise AutomationError(f"Couldn't find the folder {folder_display_name(folder_path)}.")
        return len(self._files_to_organise(path))

    def organise_folder(self, folder_path: str) -> str:
        """
        Organise files in a folder by type.
        Creates subfolders: Images, Videos, Documents, Audio, Archives, Others
        Moves files into the right subfolder based on extension.

        Args:
            folder_path: Path to the folder to organise
        """
        path = Path(folder_path)
        logger.info(f"Organising folder: {folder_path}")

        if not path.exists():
            raise AutomationError(f"Couldn't find the folder {folder_display_name(folder_path)}.")

        # File type → subfolder mapping
        type_map = {
            "Images":    [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico"],
            "Videos":    [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"],
            "Documents": [".pdf", ".doc", ".docx", ".txt", ".xlsx", ".xls", ".pptx", ".csv"],
            "Audio":     [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"],
            "Archives":  [".zip", ".rar", ".7z", ".tar", ".gz"],
            "Code":      [".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml"],
        }

        # Build reverse lookup: extension → folder name
        ext_to_folder = {}
        for folder_name, extensions in type_map.items():
            for ext in extensions:
                ext_to_folder[ext] = folder_name

        moved = 0
        errors = 0

        for file in self._files_to_organise(path):
            ext = file.suffix.lower()
            target_folder_name = ext_to_folder.get(ext, "Others")
            target_folder = path / target_folder_name

            try:
                target_folder.mkdir(exist_ok=True)
                new_path = target_folder / file.name

                # Don't overwrite existing files — add a number suffix
                counter = 1
                while new_path.exists():
                    new_path = target_folder / f"{file.stem}_{counter}{file.suffix}"
                    counter += 1

                file.rename(new_path)
                moved += 1
                logger.debug(f"Moved: {file.name} → {target_folder_name}/")

            except Exception as e:
                logger.warning(f"Could not move {file.name}: {e}")
                errors += 1

        result = f"Organised {moved} file{'' if moved == 1 else 's'} in {folder_display_name(folder_path)}."
        if errors:
            result += f" ({errors} files could not be moved.)"

        logger.info(result)
        return result

    def _endpoint_volume(self):
        # COM must be initialised on whichever thread handles the request.
        comtypes.CoInitialize()
        return AudioUtilities.GetSpeakers().EndpointVolume

    def set_volume(self, level: int) -> str:
        """Set the master volume to 0–100%. Unmutes if the level is above 0."""
        level = _clamp_percent(level)
        from services.mind.outcome_learning import verified_change
        expected = {'volume': level, **({'muted': False} if level > 0 else {})}
        read = self.audio_state if level > 0 else lambda: {'volume': self.volume_level()}
        return verified_change('set_volume', expected, lambda: self._set_volume(level), read,
                               f'Volume set to {level}%.')

    def _set_volume(self, level: int) -> str:
        try:
            volume = self._endpoint_volume()
            volume.SetMasterVolumeLevelScalar(level / 100, None)
            if level > 0:
                volume.SetMute(0, None)
        except Exception as e:
            logger.warning(f"Failed to set volume to {level}: {e}")
            raise AutomationError("Couldn't change the volume.")

        logger.info(f"Volume set to {level}%")
        return f"Volume set to {level}%."

    def volume_level(self) -> int:
        try:
            return round(self._endpoint_volume().GetMasterVolumeLevelScalar() * 100)
        except Exception as e:
            logger.warning(f"Failed to read volume: {e}")
            raise AutomationError("Couldn't read the current volume.")

    def change_volume(self, delta: int) -> str:
        """Raise (positive delta) or lower (negative delta) the volume."""
        return self.set_volume(self.volume_level() + delta)

    def set_mute(self, mute: bool) -> str:
        from services.mind.outcome_learning import verified_change
        return verified_change('set_mute', {'muted': bool(mute)}, lambda: self._set_mute(mute),
                               lambda: {'muted': self.muted()}, 'Muted.' if mute else 'Unmuted.')

    def _set_mute(self, mute: bool) -> str:
        try:
            self._endpoint_volume().SetMute(int(mute), None)
        except Exception as e:
            logger.warning(f"Failed to set mute={mute}: {e}")
            raise AutomationError("Couldn't change mute.")
        return "Muted." if mute else "Unmuted."

    def muted(self) -> bool:
        try:
            value = self._endpoint_volume().GetMute()
            if value not in (0, 1):
                raise ValueError('Invalid mute state')
            return bool(value)
        except Exception as error:
            raise AutomationError("Couldn't read the current mute state.") from error

    def audio_state(self) -> dict:
        return {'volume': self.volume_level(), 'muted': self.muted()}

    def _run_brightness_script(self, script: str) -> str:
        # Without this, PowerShell writes progress records ("Preparing modules for
        # first use") to stderr, which would look like a failure below.
        script = "$ProgressPreference = 'SilentlyContinue'; " + script
        result = _run_hidden(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
        if result.returncode != 0 or result.stderr.strip():
            logger.warning(f"Brightness command failed: {result.stderr.strip()}")
            raise AutomationError(
                "Couldn't change the brightness — this only works on built-in laptop screens."
            )
        return result.stdout

    def set_brightness(self, level: int) -> str:
        """Set built-in screen brightness to 0–100%."""
        level = _clamp_percent(level)
        self._run_brightness_script(
            "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods | "
            f"Select-Object -First 1).WmiSetBrightness(1, {level})"
        )
        logger.info(f"Brightness set to {level}%")
        return f"Brightness set to {level}%."

    def change_brightness(self, delta: int) -> str:
        """Raise (positive delta) or lower (negative delta) screen brightness."""
        output = self._run_brightness_script(
            "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | "
            "Select-Object -First 1).CurrentBrightness"
        )
        try:
            current = int(output.strip())
        except ValueError:
            logger.warning(f"Unexpected brightness reading: {output!r}")
            raise AutomationError("Couldn't read the current brightness.")
        return self.set_brightness(current + delta)

    def read_clipboard(self) -> str:
        try:
            text = clipboard.get_text()
        except clipboard.ClipboardError as e:
            logger.warning(f"Clipboard read failed: {e}")
            raise AutomationError("Couldn't read the clipboard — another app may be using it.")

        if not text or not text.strip():
            return "Your clipboard doesn't have any text on it."
        return f"Your clipboard says: {text}"

    def write_clipboard(self, text: str) -> str:
        if not text.strip():
            raise AutomationError("There's nothing to copy.")
        try:
            clipboard.set_text(text)
        except clipboard.ClipboardError as e:
            logger.warning(f"Clipboard write failed: {e}")
            raise AutomationError("Couldn't write to the clipboard — another app may be using it.")

        preview = text if len(text) <= 60 else text[:57] + "..."
        return f"Copied to clipboard: {preview}"

    def take_screenshot(self) -> str:
        """Capture all screens to a PNG in Pictures/Screenshots."""
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"FRIDAY_{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
        try:
            ImageGrab.grab(all_screens=True).save(path)
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
            raise AutomationError("Couldn't take a screenshot.")

        logger.info(f"Screenshot saved: {path}")
        self.last_screenshot = path  # the Telegram bot sends it back as a photo
        return f"Screenshot saved to your {folder_display_name(SCREENSHOT_DIR)} folder."

    def list_apps(self) -> list[str]:
        """Return a list of all app names FRIDAY can open."""
        return sorted(set(APP_REGISTRY.keys()))


# ── Singleton ─────────────────────────────────────────────────────────────────
system = SystemControl()
