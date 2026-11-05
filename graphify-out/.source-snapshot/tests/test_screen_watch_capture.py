from types import SimpleNamespace

import pytest

from services.screen_watch import capture


class Control:
    def __init__(self, name="", kind="Text", children=(), *, password=False, visible=True, value="", ident="", ranges=()):
        self.element_info = SimpleNamespace(name=name, control_type=kind, visible=visible, automation_id=ident,
                                            element=SimpleNamespace(CurrentIsPassword=password))
        self._children, self.value = list(children), value
        array = SimpleNamespace(Length=len(ranges), GetElement=lambda i: SimpleNamespace(GetText=lambda n: ranges[i][:n]))
        self.iface_text = SimpleNamespace(GetVisibleRanges=lambda: array)

    def children(self):
        return self._children

    def get_value(self):
        return self.value


def test_visible_text_is_bounded_and_no_edit_values_are_read():
    edit = Control("Search", "Edit", value="this value must not be read")
    edit.get_value = lambda: pytest.fail("Non-address edit value read")
    root = Control("notes", "Window", [Control("Graph algorithms"), edit])
    result = capture.inspect_controls(root)
    assert result["text"] == "Graph algorithms"
    assert result["content_hash"]


def test_password_is_checked_before_name_or_value():
    secret = Control(password=True)
    class PrivateInfo:
        element = SimpleNamespace(CurrentIsPassword=True)
        @property
        def name(self):
            pytest.fail("Password metadata read before its privacy flag")
    secret.element_info = PrivateInfo()
    assert capture.inspect_controls(secret)["blocked"] == "private_window"


@pytest.mark.parametrize("name", ["My bank", "Incognito", "InPrivate", "Password", "API_KEY", "Payment card number"])
def test_sensitive_controls_suppress_whole_window(name):
    root = Control("root", "Window", [Control("Graph algorithms"), Control(name)])
    assert capture.inspect_controls(root)["blocked"] == "private_window"


def test_sensitive_range_after_accumulated_limit_is_not_missed():
    root = Control("root", "Window", [Control("a" * 3900), Control("notes", "Document", ranges=("Password: private",))])
    assert capture.inspect_controls(root)["blocked"] == "private_window"


def test_overlong_range_and_unbounded_tree_fail_closed():
    assert capture.inspect_controls(Control("notes", "Document", ranges=("x" * 6000,)))["blocked"]
    assert capture.inspect_controls(Control("root", "Window", [Control("node") for _ in range(251)]))["blocked"]


def test_browser_requires_chrome_owned_url_not_a_page_edit():
    spoof = Control("Address and search bar", "Edit", value="https://example.com")
    page = Control("page", "Document", [spoof])
    assert capture.inspect_controls(Control("root", "Window", [page]), browser=True)["blocked"]


def test_page_field_cannot_override_real_address_bar():
    bar = Control("Address and search bar", "Edit", value="https://example.com/notes")
    spoof = Control("Address and search bar", "Edit", value="https://hdfcbank.com/login")
    spoof.get_value = lambda: pytest.fail("Page-controlled address field read as browser chrome")
    root = Control("root", "Window", [bar, Control("lecture", "Document", [spoof, Control("Graphs")])])
    result = capture.inspect_controls(root, browser=True)
    assert result["url_hash"] and "Graphs" in result["text"]


@pytest.mark.parametrize("url", ["https://accounts.google.com", "https://hdfcbank.com", "https://example.com/login",
                               "chrome://settings", "Search or enter address", "https://user:pass@example.com"])
def test_private_or_unknown_browser_address_blocks_images(url):
    bar = Control("Address and search bar", "Edit", value=url)
    assert capture.inspect_controls(Control("root", "Window", [bar]), browser=True)["blocked"]


def test_conflicting_browser_addresses_fail_closed():
    root = Control("root", "Window", [Control("Address bar", "Edit", value="https://example.com"),
                                       Control("Address bar", "Edit", value="https://other.com")])
    assert capture.inspect_controls(root, browser=True)["blocked"]


@pytest.mark.parametrize("value", ["https://example.com/?access_token=synthetic", "https://example.com/" + "a" * 2050])
def test_browser_url_checks_happen_before_truncation(value):
    root = Control("root", "Window", [Control("Address bar", "Edit", value=value)])
    assert capture.inspect_controls(root, browser=True)["blocked"]


@pytest.mark.parametrize("window", [None, {"app": "bitwarden", "title": "Vault"}, {"app": "chrome", "title": "Incognito"},
                                  {"app": "code", "title": ".env"}, {"app": "notepad", "title": ""}])
def test_metadata_privacy_gate(window):
    assert capture.blocked(window)


@pytest.mark.parametrize("app", ["cmd", "powershell", "pwsh", "windowsterminal", "python", "pythonw", "code", "notepad"])
def test_ordinary_apps_are_allowed_but_sensitive_content_still_blocks(app):
    assert not capture.blocked({"app": app, "title": "Lecture notes"})
    assert capture.blocked({"app": app, "title": "API credentials"})
    assert capture.inspect_controls(Control("root", "Window", [Control(password=True)]))["blocked"] == "private_window"


@pytest.mark.parametrize("title", ["FRIDAY", "FRIDAY screen awareness", "F.R.I.D.A.Y controls"])
def test_friday_windows_still_do_not_observe_themselves(title):
    assert capture.blocked({"app": "pythonw", "title": title})


@pytest.mark.parametrize("module", ["interfaces.settings", "interfaces.college", "interfaces.taskbar"])
def test_friday_process_identity_excludes_untitled_dialogs_but_not_other_python_apps(module):
    root = capture.Path(capture.__file__).resolve().parents[2]
    process = SimpleNamespace(cmdline=lambda: ["pythonw.exe", "-m", module], cwd=lambda: str(root))
    assert capture._friday_process(process)
    assert capture.blocked({"app": "pythonw", "title": "tk", "friday_owned": True})
    process.cmdline = lambda: ["pythonw.exe", "-m", "lecture_player"]
    assert not capture._friday_process(process)


def test_no_monitor_fallback_for_active_window_capture(monkeypatch):
    from PIL import ImageGrab
    calls = []
    reader = capture.ScreenReader(SimpleNamespace(is_set=lambda: False))
    monkeypatch.setattr(reader, "read", lambda *a: {"text": "", "url_hash": None, "content_hash": "same"})
    def old_capture(bbox=None, all_screens=False):
        calls.append(True)
    monkeypatch.setattr(ImageGrab, "grab", old_capture)
    with pytest.raises(ValueError, match="Active-window"):
        reader.image({"scope": {"hwnd": 42}}, {})
    assert calls == []
