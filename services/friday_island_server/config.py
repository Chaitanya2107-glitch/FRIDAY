"""Shared human-readable config. No FRIDAY services are imported at startup."""
from __future__ import annotations

import json
import os
import secrets
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class Pin(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=80)
    path: str = ""
    app_id: str | None = Field(default=None, pattern=r"^app-[a-f0-9]{32}$")
    visible: bool = True

    @model_validator(mode="after")
    def executable(self):
        if self.app_id is not None:
            if self.path:
                raise ValueError("Indexed favourites store only an app ID")
            return self
        absolute_path(self.path)
        if Path(self.path).suffix.lower() not in {".exe", ".lnk"}:
            raise ValueError("Pins must be .exe or .lnk files")
        return self


def absolute_path(value: str) -> str:
    # Validate Windows paths even in protocol tests running on another OS.
    from pathlib import PureWindowsPath
    if not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid path")
    win = PureWindowsPath(value)
    if not (Path(value).is_absolute() or win.is_absolute()) or ".." in win.parts:
        raise ValueError("Use an absolute path without traversal")
    if value.startswith(("\\\\", "//", "\\?", "\\.")):
        raise ValueError("Network and device paths are not supported")
    return value


class OpenAction(Model):
    kind: Literal["folder", "editor", "terminal", "url"]
    executable: str = ""
    args: list[str] = Field(default_factory=list, max_length=32)
    url: str = ""

    @model_validator(mode="after")
    def safe_action(self):
        if self.kind in {"editor", "terminal"}:
            absolute_path(self.executable)
            if Path(self.executable).suffix.lower() != ".exe":
                raise ValueError("Choose an editor or terminal .exe")
            if any(len(a) > 4096 or "\x00" in a for a in self.args):
                raise ValueError("Invalid argument")
        if self.kind == "url":
            from urllib.parse import urlparse
            parsed = urlparse(self.url)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError("Use an http(s) URL without credentials")
        return self


class Project(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=80)
    path: str
    color: str = Field(default="#FFB347", pattern=r"^#[0-9a-fA-F]{6}$")
    last_opened: str | None = None
    actions: list[OpenAction] = Field(default_factory=lambda: [OpenAction(kind="folder")], max_length=8)

    _path = field_validator("path")(absolute_path)


class Hotkeys(Model):
    sneak: str = Field(default="Ctrl+Shift+Alt+Space", min_length=1, max_length=100)
    expand: str = Field(default="Ctrl+Shift+Alt+F", min_length=1, max_length=100)


class Appearance(Model):
    glow: str = Field(default="#FFB347", pattern=r"^#[0-9a-fA-F]{6}$")
    idle_mode: Literal["always", "auto-hide", "hover"] = "always"
    idle_seconds: int = Field(default=30, ge=5, le=3600)
    snippet: bool = True


class Connection(Model):
    port: int = Field(default=17321, ge=1024, le=65535)
    token: str = Field(default_factory=lambda: secrets.token_hex(32), pattern=r"^[a-f0-9]{64}$")


class RecentApp(Model):
    id: str = Field(min_length=1, max_length=128)
    last_used: int = Field(ge=0, le=18446744073709551615)
    count: int = Field(ge=0, le=4294967295)


class IslandConfig(Model):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    pins: list[Pin] = Field(default_factory=list, max_length=64)
    recent_apps: list[RecentApp] = Field(default_factory=list, max_length=100)
    projects: list[Project] = Field(default_factory=list, max_length=64)
    hotkeys: Hotkeys = Field(default_factory=Hotkeys)
    appearance: Appearance = Field(default_factory=Appearance)
    connection: Connection = Field(default_factory=Connection)

    @model_validator(mode="after")
    def unique_ids(self):
        for items in (self.pins, self.projects):
            if len({p.id for p in items}) != len(items):
                raise ValueError("Duplicate IDs")
        app_ids = [p.app_id for p in self.pins if p.app_id is not None]
        if len(set(app_ids)) != len(app_ids):
            raise ValueError("Duplicate indexed favourites")
        return self


def config_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    return base / "FRIDAY" / "island" / "config.json"


@contextmanager
def locked(path: Path):
    """Lock byte zero, interoperable with Rust's fs2 whole-file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        for attempt in range(60):
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if attempt == 59:
                    raise TimeoutError("Island config is busy")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_write(path: Path, config: IslandConfig) -> None:
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(config.model_dump(), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_config(path: Path | None = None) -> IslandConfig:
    path = path or config_path()
    with locked(path):
        if path.exists():
            try:
                if path.stat().st_size > 1024 * 1024:
                    raise ValueError("Island config exceeds 1 MiB")
                raw = path.read_text(encoding="utf-8-sig")
                config = IslandConfig.model_validate_json(raw)
                if "token" not in json.loads(raw).get("connection", {}):
                    atomic_write(path, config)
                return config
            except (ValueError, UnicodeError):
                # Keep the exact damaged bytes; never silently discard hand edits.
                backup = path.with_name(f"config.corrupt-{time.time_ns()}.json")
                backup.write_bytes(path.read_bytes())
        config = IslandConfig()
        atomic_write(path, config)
        return config
