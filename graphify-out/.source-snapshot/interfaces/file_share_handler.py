"""Standard-library Explorer helper: forward a selected file to local Friday.

    pythonw file_share_handler.py telegram "C:\\path\\selected.txt" 8000

This process never uploads files itself or imports Friday's backend modules.
"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request


TITLE = "Send to Chaitu through Friday"
TIMEOUT = 120


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A local endpoint must never forward the selected path to another server.
        return None


def _failure(message: str) -> dict:
    return {"success": False, "message": message}


def _response(data: bytes) -> dict:
    result = json.loads(data)
    if not isinstance(result, dict) or type(result.get("success")) is not bool or not isinstance(result.get("message"), str):
        raise ValueError("Invalid response")
    return result


def share_file(channel: str, path: str, port: int) -> dict:
    """Validate and pass the exact Explorer path to Friday on loopback only."""
    if channel not in ("telegram", "whatsapp"):
        return _failure("Choose Telegram or WhatsApp to send this file.")
    if type(port) is not int or not 1 <= port <= 65535:
        return _failure("Friday's local API port is invalid.")
    try:
        selected = Path(path)
        if not selected.is_absolute() or not selected.is_file():
            return _failure("Select an existing file to send. Folders cannot be sent.")
    except (OSError, ValueError):
        return _failure("The selected file cannot be accessed.")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/share/file",
        data=json.dumps({"channel": channel, "path": path}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Ignore system HTTP proxies: the file path is only sent to local Friday.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            return _response(response.read())
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read())
            message = (body.get("message") or body.get("detail")) if isinstance(body, dict) else None
            if isinstance(message, str) and message:
                return _failure(message)
        except (OSError, ValueError):
            pass
        return _failure("Friday could not send this file. Check your sharing settings and try again.")
    except (urllib.error.URLError, OSError):
        return _failure("Friday could not be reached or the request timed out. Start Friday and check the destination before retrying.")
    except (ValueError, UnicodeError):
        return _failure("Friday returned an unexpected response. Please try again.")


def show_message(message: str, success: bool) -> None:
    """A pythonw process has no console, so report results with a native dialog."""
    if os.name == "nt":
        flags = 0x40 if success else 0x10  # MB_ICONINFORMATION / MB_ICONERROR
        ctypes.windll.user32.MessageBoxW(None, message[:2000], TITLE, flags | 0x10000)
    else:
        print(message, file=sys.stdout if success else sys.stderr)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid sharing arguments. Select a file from Friday's right-click menu.")


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("channel", choices=("telegram", "whatsapp"))
    parser.add_argument("path")
    parser.add_argument("port", type=int)
    try:
        args = parser.parse_args(argv)
        result = share_file(args.channel, args.path, args.port)
    except ValueError as error:
        result = _failure(str(error))
    show_message(result["message"], result["success"])
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
