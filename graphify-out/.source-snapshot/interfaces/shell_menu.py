"""Install Friday's file-sharing Explorer submenu for the current Windows user.

Run ``python -m interfaces.shell_menu install`` or ``remove`` manually.
The API also refreshes the registration at startup after a project move.
"""

import argparse
from pathlib import Path
import sys

from core.logger import logger

try:
    import winreg
except ImportError:  # Other operating systems can still run the backend.
    winreg = None


MENU_KEY = r"Software\Classes\*\shell\FridaySendChaitu"
HANDLER_PATH = Path(__file__).with_name("file_share_handler.py").resolve()
CHANNELS = ("telegram", "whatsapp")


def _pythonw() -> str | None:
    executable = Path(sys.executable).with_name("pythonw.exe")
    return str(executable.resolve()) if executable.is_file() else None


def _write_key(path: str, values: dict[str, str]) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def register_menu(port: int | None = None) -> bool:
    """Refresh only Friday's per-user menu; return False if unavailable."""
    if winreg is None:
        return False
    if port is None:
        from core.config import config
        port = config.API_PORT
    if type(port) is not int or not 1 <= port <= 65535:
        logger.warning("Cannot install Friday right-click menu: invalid API port")
        return False
    pythonw = _pythonw()
    if not pythonw:
        logger.warning("Cannot install Friday right-click menu: pythonw.exe is unavailable")
        return False
    try:
        _write_key(MENU_KEY, {
            "": "",
            "MUIVerb": "Send to Chaitu through Friday",
            "SubCommands": "",
            "MultiSelectModel": "Single",
        })
        _write_key(MENU_KEY + r"\shell", {"": "telegram,whatsapp"})
        for channel in CHANNELS:
            verb = MENU_KEY + "\\shell\\" + channel
            label = "WhatsApp" if channel == "whatsapp" else "Telegram"
            _write_key(verb, {"MUIVerb": label, "MultiSelectModel": "Single"})
            # Explorer substitutes %1. All paths are quoted; no command shell is involved.
            command = f'"{pythonw}" "{HANDLER_PATH}" {channel} "%1" {port}'
            _write_key(verb + r"\command", {"": command})
    except OSError:
        logger.warning("Could not install Friday right-click menu", exc_info=True)
        return False
    logger.debug("Friday file-sharing right-click menu registered for current user")
    return True


def unregister_menu() -> bool:
    """Delete only the keys Friday owns, children first; safe to repeat."""
    if winreg is None:
        return False
    keys = []
    for channel in CHANNELS:
        verb = MENU_KEY + "\\shell\\" + channel
        keys.extend([verb + r"\command", verb])
    keys.extend([MENU_KEY + r"\shell", MENU_KEY])
    try:
        for key in keys:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except FileNotFoundError:
                pass
    except OSError:
        logger.warning("Could not remove Friday right-click menu", exc_info=True)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "remove"))
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    success = register_menu(args.port) if args.action == "install" else unregister_menu()
    print("Friday right-click menu " + ("updated." if success else "could not be updated."))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
