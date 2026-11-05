"""Narrow libdbus binding for KDE Connect's own Windows session bus.

Load the DLL from KDE's installation so its install-scoped bus matches Qt.
No remote server, shell commands, or Python/Qt dependency is introduced.
"""

import ctypes as C
import os
from pathlib import Path
import re
import shutil
import subprocess

SERVICE = "org.kde.kdeconnect"
BASE = "/modules/kdeconnect"
DEVICE = SERVICE + ".device"
NOTIFICATIONS = DEVICE + ".notifications"
PROPERTIES = "org.freedesktop.DBus.Properties"
TIMEOUT_MS = 2000


class PhoneError(Exception):
    pass


def installation() -> Path:
    candidates = []
    if configured := os.environ.get("KDECONNECT_DIR"):
        root = Path(configured).expanduser().resolve()
        candidates.extend((root / "kdeconnect-cli.exe", root / "bin" / "kdeconnect-cli.exe"))
    if found := shutil.which("kdeconnect-cli.exe"):
        candidates.append(Path(found).resolve())
    for base in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            for folder in ("KDE Connect", "KDEConnect", "Programs/KDE Connect"):
                candidates.extend(Path(base) / folder / sub / "kdeconnect-cli.exe" for sub in ("", "bin"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise PhoneError("Install KDE Connect on Windows and Android, pair them, then say 'phone status'.")


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", value):
        raise PhoneError("The phone returned an invalid device or notification identifier.")
    return value


def _local_address(address):
    if address in ("", "autolaunch:", "autolaunch:scope=*install-path"):
        return True
    if ";" in address or "\x00" in address or not address.startswith(("tcp:", "nonce-tcp:")):
        return False
    parts = [part.split("=", 1) for part in address.split(":", 1)[1].split(",")]
    if any(len(part) != 2 for part in parts):
        return False
    fields = dict(parts)
    return (len(fields) == len(parts) and fields.get("host") in ("127.0.0.1", "localhost")
            and set(fields) <= {"host", "port", "noncefile", "guid", "family"})


class _Iter(C.Structure):
    # ABI layout from the public DBusMessageIter declaration in dbus-message.h.
    _fields_ = [("pointer1", C.c_void_p), ("pointer2", C.c_void_p), ("serial", C.c_uint32)]
    _fields_ += [("integer" + str(i), C.c_int) for i in range(9)]
    _fields_ += [("padding1", C.c_void_p), ("padding2", C.c_void_p)]


class Transport:
    def __enter__(self):
        self.cli = installation()
        address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        if not _local_address(address):
            raise PhoneError("Phone access requires KDE Connect's local session bus.")
        folder = self.cli.parent
        dll = next((folder / name for name in ("dbus-1.dll", "libdbus-1-3.dll", "dbus-1-3.dll")
                    if (folder / name).is_file()), None)
        if dll is None:
            raise PhoneError("This KDE Connect installation is missing its D-Bus library. Repair the Windows installation.")
        self._directory, self.connection = None, None
        try:
            self._directory = os.add_dll_directory(str(folder))
            self.lib = C.CDLL(str(dll), winmode=0x1100)
            self._bind()
            if not self.lib.dbus_threads_init_default():
                raise PhoneError("Couldn't initialize KDE Connect's local bridge.")
            self.connection = self.lib.dbus_bus_get_private(0, None)  # DBUS_BUS_SESSION
            if not self.connection:
                raise PhoneError("Open KDE Connect on Windows first; its local connection is unavailable.")
            self.lib.dbus_connection_set_exit_on_disconnect(self.connection, 0)
            self.owner = self._call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                    "org.freedesktop.DBus", "GetNameOwner", SERVICE)
            self.bus_id = self._call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                    "org.freedesktop.DBus", "GetId")
            if not isinstance(self.owner, str) or not re.fullmatch(r":\d+\.\d+", self.owner):
                raise PhoneError("KDE Connect's local service is unavailable.")
            if not isinstance(self.bus_id, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", self.bus_id):
                raise PhoneError("KDE Connect's local bus identity is unavailable.")
            return self
        except (OSError, AttributeError) as error:
            self.__exit__(None, None, None)
            raise PhoneError("Couldn't load KDE Connect's local bridge. Repair or update KDE Connect.") from error
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.connection:
            self.lib.dbus_connection_close(self.connection)
            self.lib.dbus_connection_unref(self.connection)
            self.connection = None
        if self._directory:
            self._directory.close()

    def _bind(self):
        ptr, string, integer = C.c_void_p, C.c_char_p, C.c_int
        signatures = {
            "dbus_threads_init_default": (integer, []),
            "dbus_bus_get_private": (ptr, [integer, ptr]),
            "dbus_connection_set_exit_on_disconnect": (None, [ptr, integer]),
            "dbus_connection_close": (None, [ptr]), "dbus_connection_unref": (None, [ptr]),
            "dbus_message_new_method_call": (ptr, [string, string, string, string]),
            "dbus_message_unref": (None, [ptr]), "dbus_message_get_type": (integer, [ptr]),
            "dbus_message_iter_init": (integer, [ptr, ptr]),
            "dbus_message_iter_init_append": (None, [ptr, ptr]),
            "dbus_message_iter_append_basic": (integer, [ptr, integer, ptr]),
            "dbus_message_iter_get_arg_type": (integer, [ptr]),
            "dbus_message_iter_get_basic": (None, [ptr, ptr]),
            "dbus_message_iter_next": (integer, [ptr]),
            "dbus_message_iter_recurse": (None, [ptr, ptr]),
            "dbus_connection_send_with_reply_and_block": (ptr, [ptr, ptr, integer, ptr]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, args

    def _value(self, iterator, depth=0):
        kind = self.lib.dbus_message_iter_get_arg_type(C.byref(iterator))
        if depth > 6:
            raise PhoneError("KDE Connect returned an oversized response.")
        if kind in (ord("s"), ord("o"), ord("g")):
            value = C.c_char_p()
            self.lib.dbus_message_iter_get_basic(C.byref(iterator), C.byref(value))
            raw = value.value or b""
            if len(raw) > 8192:
                raise PhoneError("This phone notification is too long to read safely.")
            return raw.decode("utf-8", errors="replace")
        if kind in (ord("b"), ord("u"), ord("i")):
            value = C.c_int32()
            self.lib.dbus_message_iter_get_basic(C.byref(iterator), C.byref(value))
            return bool(value.value) if kind == ord("b") else value.value
        if kind in (ord("a"), ord("v"), ord("e")):
            child, values = _Iter(), []
            self.lib.dbus_message_iter_recurse(C.byref(iterator), C.byref(child))
            dictionary = self.lib.dbus_message_iter_get_arg_type(C.byref(child)) == ord("e")
            while self.lib.dbus_message_iter_get_arg_type(C.byref(child)):
                if len(values) >= 128:
                    raise PhoneError("KDE Connect returned too many entries.")
                values.append(self._value(child, depth + 1))
                if not self.lib.dbus_message_iter_next(C.byref(child)):
                    break
            return values[0] if kind == ord("v") and values else dict(values) if dictionary else values
        raise PhoneError("This KDE Connect response format isn't supported.")

    def _call(self, destination, path, interface, method, *args):
        message = self.lib.dbus_message_new_method_call(*(v.encode() for v in (destination, path, interface, method)))
        if not message:
            raise PhoneError("Couldn't create the local phone request.")
        reply = None
        try:
            iterator = _Iter()
            self.lib.dbus_message_iter_init_append(message, C.byref(iterator))
            for arg in args:
                if isinstance(arg, bool):
                    kind, value = ord("b"), C.c_uint32(arg)
                else:
                    if not isinstance(arg, str) or "\x00" in arg or len(arg) > 2000:
                        raise PhoneError("Invalid phone request text.")
                    kind, value = ord("s"), C.c_char_p(arg.encode("utf-8"))
                if not self.lib.dbus_message_iter_append_basic(C.byref(iterator), kind, C.byref(value)):
                    raise PhoneError("Couldn't encode the local phone request.")
            reply = self.lib.dbus_connection_send_with_reply_and_block(self.connection, message, TIMEOUT_MS, None)
            if not reply or self.lib.dbus_message_get_type(reply) == 3:
                raise PhoneError("KDE Connect didn't accept that request. Check the connection and enabled phone plugins.")
            iterator = _Iter()
            return self._value(iterator) if self.lib.dbus_message_iter_init(reply, C.byref(iterator)) else None
        finally:
            if reply:
                self.lib.dbus_message_unref(reply)
            self.lib.dbus_message_unref(message)

    def devices(self):
        return self._call(self.owner, BASE, SERVICE + ".daemon", "devices", True, True) or []

    def properties(self, device, notification=None):
        path = BASE + "/devices/" + identifier(device)
        interface = DEVICE
        if notification is not None:
            path += "/notifications/" + identifier(notification)
            interface = NOTIFICATIONS + ".notification"
        return self._call(self.owner, path, PROPERTIES, "GetAll", interface) or {}

    def notifications(self, device):
        return self._call(self.owner, BASE + "/devices/" + identifier(device) + "/notifications",
                          NOTIFICATIONS, "activeNotifications") or []

    def reply(self, device, reply_id, message):
        return self._call(self.owner, BASE + "/devices/" + identifier(device) + "/notifications",
                          NOTIFICATIONS, "sendReply", reply_id, message)

    def ring(self, device):
        try:
            result = subprocess.run([str(self.cli), "--device", identifier(device), "--ring"],
                                    capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PhoneError("Couldn't submit the ring request to KDE Connect.") from error
        if result.returncode:
            raise PhoneError("KDE Connect couldn't ring that phone. Check its connection.")
