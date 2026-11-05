"""Strict v1 manifest validation. Discovery never executes a plugin."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,63}$')
    name: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=40)
    api_version: Literal[1]
    description: str = Field(max_length=2000)
    author: str = Field(min_length=1, max_length=120)
    entry: str = 'main.py'
    permissions: list[Literal['events', 'files', 'clipboard', 'network', 'system_control', 'ui']]
    requires: list[str] = Field(default_factory=list)
    enabled_by_default: bool

    @field_validator('name', 'author')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value

    @field_validator('requires')
    @classmethod
    def packages(cls, values):
        import re
        if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value) for value in values):
            raise ValueError('requires accepts installed pip distribution names, without versions or URLs')
        return values

    @field_validator('entry')
    @classmethod
    def relative_python(cls, value):
        from pathlib import PureWindowsPath
        windows = PureWindowsPath(value)
        if windows.is_absolute() or windows.drive or '..' in windows.parts or '\\' in value or not value.endswith('.py'):
            raise ValueError('entry must be a relative .py path without traversal')
        return value


def read_manifest(path: Path) -> Manifest:
    if path.stat().st_size > 65536:
        raise ValueError('Manifest exceeds 64 KiB')
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(raw, dict) or type(raw.get('api_version')) is not int:
        raise ValueError('api_version must be integer 1')
    manifest = Manifest.model_validate(raw)
    entry = (path.parent / manifest.entry).resolve()
    if not entry.is_relative_to(path.parent.resolve()) or not entry.is_file():
        raise ValueError('entry must name an existing Python file inside its plugin folder')
    return manifest
