"""The Explorer menu only writes Friday's per-user registration."""

from contextlib import contextmanager

import pytest

from interfaces import shell_menu


class Registry:
    HKEY_CURRENT_USER = "current-user"
    REG_SZ = 1

    def __init__(self):
        self.values = {}
        self.deleted = []

    @contextmanager
    def CreateKey(self, hive, path):
        assert hive == self.HKEY_CURRENT_USER
        self.values.setdefault(path, {})
        yield path

    def SetValueEx(self, key, name, reserved, kind, value):
        assert kind == self.REG_SZ
        self.values[key][name] = value

    def DeleteKey(self, hive, path):
        assert hive == self.HKEY_CURRENT_USER
        if path not in self.values:
            raise FileNotFoundError(path)
        if any(key.startswith(path + "\\") for key in self.values):
            raise OSError("key has children")
        self.deleted.append(path)
        del self.values[path]


@pytest.fixture
def registry(monkeypatch):
    registry = Registry()
    monkeypatch.setattr(shell_menu, "winreg", registry)
    monkeypatch.setattr(shell_menu, "_pythonw", lambda: r"C:\Program Files\Python\pythonw.exe")
    return registry


def test_registers_both_channels_for_single_selected_file(registry):
    assert shell_menu.register_menu(8123)
    parent = registry.values[shell_menu.MENU_KEY]
    assert parent["MUIVerb"] == "Send to Chaitu through Friday"
    assert parent["SubCommands"] == ""
    assert parent[""] == ""
    assert parent["MultiSelectModel"] == "Single"
    for channel in ("telegram", "whatsapp"):
        verb = shell_menu.MENU_KEY + "\\shell\\" + channel
        assert registry.values[verb]["MUIVerb"] == ("WhatsApp" if channel == "whatsapp" else "Telegram")
        assert registry.values[verb]["MultiSelectModel"] == "Single"
        command = registry.values[verb + "\\command"][""]
        assert command.startswith('"C:\\Program Files\\Python\\pythonw.exe" "')
        assert 'file_share_handler.py"' in command
        assert command.endswith(f' {channel} "%1" 8123')
        assert "cmd.exe" not in command
        assert "powershell" not in command


def test_register_updates_port_without_duplicating_keys(registry):
    shell_menu.register_menu(8000)
    keys = set(registry.values)
    shell_menu.register_menu(8999)
    assert set(registry.values) == keys
    assert registry.values[shell_menu.MENU_KEY + "\\shell\\telegram\\command"][""].endswith("8999")


def test_remove_is_idempotent_and_preserves_unrelated_menu(registry):
    other = r"Software\Classes\*\shell\OtherApplication"
    registry.values[other] = {"": "Other"}
    shell_menu.register_menu(8000)
    assert shell_menu.unregister_menu()
    assert shell_menu.unregister_menu()
    assert registry.values == {other: {"": "Other"}}
    assert all(key.startswith(shell_menu.MENU_KEY) for key in registry.deleted)


def test_remove_does_not_recursively_delete_unrecognized_children(registry):
    shell_menu.register_menu(8000)
    child = shell_menu.MENU_KEY + "\\unrecognized"
    registry.values[child] = {}
    assert not shell_menu.unregister_menu()
    assert child in registry.values


def test_registry_permission_failure_does_not_break_startup(registry, monkeypatch, caplog):
    def denied(*args):
        raise PermissionError("denied")
    monkeypatch.setattr(registry, "CreateKey", denied)
    assert not shell_menu.register_menu(8000)
    assert "right-click menu" in caplog.text.lower()


@pytest.mark.parametrize("port", [0, -1, 65536, "8000 & calc", True])
def test_rejects_invalid_port_before_registry_write(registry, port):
    assert not shell_menu.register_menu(port)
    assert not registry.values


def test_non_windows_is_noop(monkeypatch):
    monkeypatch.setattr(shell_menu, "winreg", None)
    assert not shell_menu.register_menu(8000)
    assert not shell_menu.unregister_menu()


def test_missing_pythonw_does_not_create_a_broken_menu(registry, monkeypatch):
    monkeypatch.setattr(shell_menu, "_pythonw", lambda: None)
    assert not shell_menu.register_menu(8000)
    assert not registry.values
