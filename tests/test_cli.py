import io
import json

from interfaces.cli import friday


class Piped(io.BytesIO):
    """stdin with text piped in: not a terminal, bytes underneath."""
    def isatty(self):
        return False

    @property
    def buffer(self):
        return self


def test_piped_output_is_attached_and_its_end_kept():
    assert friday.build_message("why did this fail", "") == "why did this fail"
    assert friday.build_message("", "error") == "Explain this.\n\nTerminal output:\nerror"
    long = "x" * 10_000 + "TypeError at the end"
    message = friday.build_message("why", long)
    assert len(message) <= friday.MAX_MESSAGE and message.endswith("TypeError at the end")


def test_main_sends_question_and_pipe(monkeypatch, capsys):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"response": "Missing semicolon — obviously."}).encode())
    monkeypatch.setattr(friday.urllib.request, "urlopen", fake_urlopen)
    assert friday.main(["why", "did", "this", "fail"], Piped("npm ERR! — oops".encode())) == 0
    assert sent[0]["message"] == "why did this fail\n\nTerminal output:\nnpm ERR! — oops"
    assert capsys.readouterr().out == "Missing semicolon — obviously.\n"


def test_friday_not_running(monkeypatch):
    def refused(request, timeout):
        raise friday.urllib.error.URLError("refused")
    monkeypatch.setattr(friday.urllib.request, "urlopen", refused)
    assert friday.ask("hi").startswith("FRIDAY isn't running")
