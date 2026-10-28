"""Bounded phone notification context; replies retain their exact reviewed target."""

import hashlib
import json
import threading
import time

from core.config import config
from services import settings_store
from services.phone.transport import PhoneError, Transport, identifier

CONTEXT_SECONDS = 120
MAX_NOTIFICATIONS = 10


def _fingerprint(properties):
    keys = ("internalId", "appName", "title", "text", "ticker", "replyId")
    return hashlib.sha256(json.dumps({k: properties.get(k, "") for k in keys},
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _line(text, limit=180):
    return " ".join(str(text).split())[:limit]


class PhoneBridge:
    def __init__(self, transport=Transport):
        self.transport = transport
        self.lock = threading.RLock()
        self.clear()

    def clear(self):
        with self.lock:
            self.items, self.selected, self.listed_at = [], None, 0

    def _settings(self):
        path = config.MEMORY_DIR / "phone.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            raise PhoneError("Couldn't read the selected phone settings.") from error

    def _devices(self, connection):
        result = []
        for device in connection.devices()[:16]:
            identifier(device)
            props = connection.properties(device)
            if props.get("isPaired") is True and props.get("isReachable") is True:
                result.append((device, _line(props.get("name") or device, 80)))
        return result

    def _device(self, connection):
        devices = self._devices(connection)
        chosen = self._settings().get("device")
        if chosen:
            if chosen not in dict(devices):
                raise PhoneError("Your selected phone is disconnected. Open KDE Connect on both devices.")
            return chosen
        if not devices:
            raise PhoneError("No paired phone is reachable. Pair Android with KDE Connect on this PC first.")
        if len(devices) > 1:
            raise PhoneError("Several phones are connected. Say 'list phones', then 'use phone <device ID>'.")
        return devices[0][0]

    def status(self):
        with self.lock, self.transport() as connection:
            devices = self._devices(connection)
            if not devices:
                return "KDE Connect is running; no paired phone is reachable."
            selected = self._settings().get("device")
            return "Paired phones:\n" + "\n".join(
                f"{name}: {device}" + (" (selected)" if selected == device else "")
                for device, name in devices)

    def choose(self, requested):
        with self.lock, self.transport() as connection:
            devices = self._devices(connection)
            matches = [(device, name) for device, name in devices
                       if requested.casefold() in (device.casefold(), name.casefold())]
            if len(matches) != 1:
                raise PhoneError("Name one connected phone exactly, or use its ID from 'list phones'.")
            device, name = matches[0]
            settings_store.save(config.MEMORY_DIR / "phone.json", {"device": device})
            self.clear()
            return f"Using {name} for phone commands."

    def forget(self):
        with self.lock:
            settings_store.save(config.MEMORY_DIR / "phone.json", {})
            self.clear()
            return "Forgot the selected phone and notification context. KDE Connect pairing is unchanged."

    def _snapshot(self, connection, device, notification):
        props = connection.properties(device, identifier(notification))
        if not props or not props.get("internalId"):
            raise PhoneError("That notification is no longer available. List your phone notifications again.")
        return {"device": device, "owner": connection.owner, "bus_id": connection.bus_id, "id": notification,
                "fingerprint": _fingerprint(props), "properties": props}

    def list_notifications(self):
        with self.lock, self.transport() as connection:
            self.clear()
            device = self._device(connection)
            ids = connection.notifications(device)
            # KDE's public IDs increase within one daemon lifetime; newest first.
            ids = sorted((str(n) for n in ids if str(n).isdigit()), key=int, reverse=True)[:MAX_NOTIFICATIONS]
            for notification in ids:
                self.items.append(self._snapshot(connection, device, notification))
            self.listed_at = time.monotonic()
            if not self.items:
                return "No shared phone notifications. Enable notification access for KDE Connect on Android if needed."
            if len(self.items) == 1:
                self.selected = self.items[0]
            lines = []
            for index, row in enumerate(self.items, 1):
                props = row["properties"]
                lines.append(f"{index}. {_line(props.get('appName', 'Phone'))}: "
                             f"{_line(props.get('title') or props.get('ticker') or props.get('text'))}")
            return "Phone notifications:\n" + "\n".join(lines) + "\nSay 'read phone notification 2' to select one."

    def _current(self, connection, snapshot):
        if not snapshot or time.monotonic() - self.listed_at > CONTEXT_SECONDS:
            raise PhoneError("List and select a phone notification first; the previous context has expired.")
        if (connection.owner != snapshot["owner"] or connection.bus_id != snapshot["bus_id"]
                or self._device(connection) != snapshot["device"]):
            self.clear()
            raise PhoneError("The phone connection changed. List and select the notification again.")
        current = self._snapshot(connection, snapshot["device"], snapshot["id"])
        if current["fingerprint"] != snapshot["fingerprint"]:
            self.clear()
            raise PhoneError("That notification changed. Read the updated notification before replying.")
        return current

    def read(self, number=None):
        with self.lock, self.transport() as connection:
            if number is not None:
                if not 1 <= number <= len(self.items):
                    raise PhoneError("Choose a number from 'read my phone notifications' first.")
                chosen = self.items[number - 1]
            else:
                chosen = self.selected
            current = self._current(connection, chosen)
            self.selected = current
            props = current["properties"]
            return f"{_line(props.get('appName', 'Phone'))} — {_line(props.get('title'), 200)}\n" + (
                str(props.get("text") or props.get("ticker") or "No text in this notification."))

    def draft(self, message):
        if not isinstance(message, str) or not message.strip() or len(message) > 1000 or "\x00" in message:
            raise PhoneError("Give me a reply between 1 and 1,000 characters.")
        with self.lock, self.transport() as connection:
            selected = self._current(connection, self.selected)
            props = selected["properties"]
            if not props.get("replyId"):
                raise PhoneError("This notification doesn't support direct replies. Open its app on your phone.")
            target = {key: selected[key] for key in ("device", "owner", "bus_id", "id", "fingerprint")}
            target["message"] = message
            question = (f"Reply to {_line(props.get('title') or props.get('ticker'), 120)} on "
                        f"{_line(props.get('appName', 'Phone'))}:\n{message}\nSay yes to submit, or no to cancel.")
            return target, question

    def submit(self, target):
        with self.lock, self.transport() as connection:
            # Consume even a failing send: no accidental duplicate retries.
            selected = self.selected
            self.selected = None
            if not selected or any(target.get(k) != selected.get(k) for k in ("device", "owner", "bus_id", "id", "fingerprint")):
                raise PhoneError("That phone reply is no longer current. Select the notification again.")
            current = self._current(connection, selected)
            connection.reply(target["device"], current["properties"]["replyId"], target["message"])
            return "Reply submitted to your phone. The messaging app hasn't confirmed delivery."

    def ring(self):
        with self.lock, self.transport() as connection:
            connection.ring(self._device(connection))
            return "Ring request submitted to your phone."


bridge = PhoneBridge()
