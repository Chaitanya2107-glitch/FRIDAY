"""Control-aware Notepad/file-dialog adapter, owned by a single COM MTA thread."""

import ctypes
import json
import os
import time

from services.browser.models import Observation, Step
from services.browser.worker import ProcessRuntime


class WindowsControls:
    def __init__(self, stopped):
        self.stopped = stopped
        self.initialized = False
        self.controls = {}
        self.last_observation = None

    def _check(self):
        if self.stopped.is_set():
            raise InterruptedError("Task stopped")

    def start(self, headless=False):
        if os.name != "nt" or headless:
            raise ValueError("Windows controls require a visible Windows desktop")
        try:
            return self.observe()
        except ValueError:
            return Observation("desktop", "Windows desktop", "No supported window is in the foreground. "
                               "You may propose opening Notepad if the owner requested it.")

    def _window(self):
        self._check()
        if not self.initialized:
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
            # Import and all UIA objects remain in this apartment/thread.
            from pywinauto import Desktop
            self.desktop = Desktop(backend="uia")
            self.initialized = True
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            raise ValueError("No foreground window")
        window = self.desktop.window(handle=hwnd).wrapper_object()
        import psutil
        process = psutil.Process(window.process_id()).name().lower()
        # Initial native scope: standard text editors and common file dialogs.
        # Shells, password managers and arbitrary settings windows aren't targets.
        file_dialog = (window.class_name() == "#32770" and window.window_text().strip().lower() in
                       {"open", "save as", "save file", "select file", "choose file"})
        if file_dialog:
            edits = window.descendants(control_type="Edit", depth=6)
            buttons = window.descendants(control_type="Button", depth=6)
            file_dialog = (any(e.element_info.automation_id == "1148" or
                               "file name" in e.element_info.name.lower() for e in edits) and
                           any(b.window_text().replace("&", "").lower() in {"open", "save"} for b in buttons))
        if process not in {"notepad.exe", "notepad++.exe"} and not file_dialog:
            raise ValueError("Use foreground Notepad or a standard Open/Save file dialog")
        return user32, hwnd, window

    @staticmethod
    def _text(control):
        try:
            if control.element_info.control_type in {"Edit", "Document"}:
                try:
                    return control.get_value()[:12000]
                except Exception:
                    return control.iface_text.DocumentRange.GetText(12000)
            return control.window_text()[:300]
        except Exception:
            return ""

    def observe(self):
        user32, hwnd, window = self._window()
        controls, texts = [], []
        control_chars = 0
        self.controls = {}
        for control in window.descendants(depth=5)[:200]:
            if len(controls) >= 80:
                break
            info = control.element_info
            if (info.control_type not in {"Edit", "Document", "Button", "MenuItem", "TabItem", "ListItem", "ComboBox"}
                    or not control.is_visible() or not control.is_enabled()):
                continue
            if info.element.CurrentIsPassword:
                continue
            value = self._text(control)
            name = info.name or info.automation_id or info.control_type
            item = {"id": len(controls) + 1, "name": name[:180], "kind": info.control_type,
                    "identity": str(info.runtime_id), "automation_id": info.automation_id[:180], "protected": False}
            control_chars += len(json.dumps(item, ensure_ascii=False))
            if control_chars > 12000:
                continue
            self.controls[item["id"]] = control
            controls.append(item)
            texts.append(f"{name}: {value}")
        if user32.GetForegroundWindow() != hwnd:
            raise ValueError("Foreground window changed")
        observation = Observation(str(hwnd), window.window_text()[:300], "\n".join(texts)[:12000], controls)
        self.last_observation = observation
        return observation

    def execute(self, step: Step, fingerprint: str):
        from services.automation import keyboard
        if step.action == "launch" and step.value == "notepad":
            self._check()
            import subprocess
            subprocess.Popen(["notepad.exe"])
            for _ in range(20):
                self._check()
                time.sleep(.2)
                try:
                    observation = self.observe()
                    _, _, window = self._window()
                    import psutil
                    if psutil.Process(window.process_id()).name().lower() == "notepad.exe":
                        return "Opened Notepad; foreground window observed.", observation
                except ValueError:
                    continue
            raise ValueError("Notepad did not reach the foreground")
        observed = self.observe()
        if observed.fingerprint() != fingerprint:
            raise ValueError("The window changed; review a fresh step")
        target = self.controls.get(step.target)
        if target is None or target.element_info.element.CurrentIsPassword:
            raise ValueError("Unavailable or protected control")
        user32, hwnd, _ = self._window()
        self._check()
        if str(hwnd) != observed.location or user32.GetForegroundWindow() != hwnd:
            raise ValueError("Foreground window changed")
        if step.action == "fill":
            if hasattr(target, "set_edit_text"):
                target.set_edit_text(step.value)
            elif target.element_info.control_type == "Document":
                target.set_focus()
                target.iface_text.DocumentRange.Select()
                self._check()
                if user32.GetForegroundWindow() != hwnd or not target.has_keyboard_focus():
                    raise ValueError("Editor focus changed")
                keyboard.type_text(step.value)
            else:
                raise ValueError("Control does not support literal text entry")
            if self._text(target) != step.value:
                raise ValueError("Text entry could not be verified")
            receipt = "Entered text; control value verified."
        elif step.action == "click":
            target.invoke() if hasattr(target, "invoke") else target.select()
            receipt = "Control invoked; inspect the resulting window state."
        elif step.action == "press":
            target.set_focus()
            self._check()
            if user32.GetForegroundWindow() != hwnd:
                raise ValueError("Foreground window changed")
            keyboard.press_keys({"Enter": "enter", "Tab": "tab", "Escape": "esc",
                                 "ArrowDown": "down", "ArrowUp": "up"}[step.value])
            receipt = "Key submitted; inspect the resulting window state."
        else:
            raise ValueError("Unsupported Windows operation")
        return receipt, self.observe()

    def close(self):
        self.controls = {}
        if self.initialized:
            self.desktop = None
            import pythoncom
            pythoncom.CoUninitialize()
            self.initialized = False


class WindowsRuntime(ProcessRuntime):
    """A blocked native provider cannot hold FRIDAY's API or shutdown indefinitely."""
    def __init__(self, stopped, downloads=None):
        # Deliberately no job/tree kill: Notepad is the owner's target application.
        super().__init__(WindowsControls, (), stopped, timeout=15)
