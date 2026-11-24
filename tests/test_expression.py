"""Local expression, cooldown, factual slots and privacy checks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from core.config import config
from services.automation import personality
from services.mind import expression, humour, wording

NOW = datetime(2026, 10, 21, 10)


def present(band="neutral", *, stressed=False, verbosity=.5, formality=.5, **state):
    return {
        "emotion": {"band": band, "owner_stressed": stressed},
        "character": {"traits": {"verbosity": verbosity, "formality": formality, "warmth": .5}},
        **state,
    }


def test_one_thousand_returns_vary_and_never_repeat_within_three_days():
    lines = {}
    for i in range(1000):
        now = NOW + timedelta(hours=6 * i)
        line = expression.render({"kind": "back"}, "chill", present(), now=now)
        assert line
        if line in lines:
            assert now - lines[line] >= expression.COOLDOWN
        lines[line] = now
    assert len(lines) >= 75


def test_the_cooldown_covers_a_template_and_a_line_across_threads():
    def speak(_):
        return expression.claim("template", "Done with the private item.", now=NOW, joke=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(speak, range(8))).count(True) == 1
    assert not expression.claim("different-template", "done with the PRIVATE item!", now=NOW)
    assert not expression.claim("template", "Done with another item.", now=NOW, joke=True)
    stored = (config.MEMORY_DIR / "mind" / "expression.db").read_bytes()
    assert b"private item" not in stored
    assert expression.claim("template", "Done with the private item.", now=NOW + expression.COOLDOWN, joke=True)


def test_stress_keeps_exact_exam_facts_and_a_short_serious_tone(monkeypatch):
    async def model(*args, **kwargs):
        raise AssertionError("Local phrasing must never call the gateway")

    monkeypatch.setattr("providers.failover.complete_with_failover", model)
    snapshot = present("bright", stressed=True, verbosity=1)
    exam = {"kind": "exam_soon", "subject": "Applied Physics exam", "when": "in 20 minutes"}
    line = wording.render(exam, "study", snapshot, now=NOW)
    assert "Applied Physics exam" in line and "in 20 minutes" in line
    assert len(line.split()) <= 11 and "!" not in line
    assert expression.render({"kind": "joke"}, "study", snapshot, now=NOW) is None
    ack = wording.render({"kind": "stress_ack"}, "study", snapshot, now=NOW)
    assert len(ack.split()) <= 8 and "!" not in ack


def test_a_new_explicit_joke_is_never_repeated_during_the_window():
    personality.path.write_text('{"off": false}', encoding='utf-8')
    raw = {"kind": "joke"}
    lines = [
        expression.render(raw, "chill", present(), now=NOW + timedelta(minutes=i))
        for i in range(10)
    ]
    heard = list(filter(None, lines))
    assert len(heard) == 6 and len(set(heard)) == 6
    assert lines[-1] is None
    assert expression.render(raw, "chill", present(), now=NOW + expression.COOLDOWN)


def test_verbosity_changes_length_and_formality_changes_address():
    raw = {"kind": "back", "before_leaving": "editing the report"}
    brief = expression.render(raw, "chill", present(verbosity=.1), now=NOW)
    long = expression.render(raw, "chill", present(verbosity=.9, formality=.9), now=NOW)
    assert brief and long and len(long.split()) > len(brief.split())
    assert "editing the report" in brief and "editing the report" in long
    assert "Boss" in brief and "Boss" not in long


def test_callback_needs_an_exact_explicit_local_memory_and_humour_permission(monkeypatch):
    personality.path.write_text('{"off": false}', encoding='utf-8')
    row = {
        "id": "temporal:1", "status": "completed", "subject": "DBMS revision",
        "quote": "I finished DBMS revision.", "source_noted": "2026-10-18T11:00:00",
    }
    raw = {"kind": "task_done", "name": "DBMS revision"}
    snapshot = present(situation={"closed": [row]})
    monkeypatch.setattr(humour, "should_joke", lambda *a, **kw: True)
    first = expression.render(raw, "chill", snapshot, now=NOW)
    assert "On October 18, you said you'd finished it." in first
    again = expression.render(raw, "chill", snapshot, now=NOW + timedelta(hours=1))
    assert "October 18" not in again
    later = NOW + expression.COOLDOWN
    row["quote"] = "I'll finish DBMS revision."
    unsupported = expression.render(raw, "chill", snapshot, now=later)
    assert "October 18" not in unsupported
    row["quote"] = "I completed DBMS revision."
    private = wording.render(raw, "chill", snapshot, now=later, private=True)
    assert "October 18" not in private
    monkeypatch.setattr(humour, "should_joke", lambda *a, **kw: False)
    blocked = expression.render(raw, "chill", snapshot, now=later)
    assert "October 18" not in blocked


def test_action_confirmation_is_literal_and_does_not_read_the_expression_store():
    raw = {"kind": "command", "fact": "Move D:\\Notes to the archive? Say yes or no."}
    assert wording.render(raw, "chill", present("bright", verbosity=1), now=NOW) == raw["fact"]
    raw["fact"] = "Step one succeeded.\nStep two needs your confirmation."
    assert wording.render(raw, "chill", present("bright", verbosity=1), now=NOW) == raw["fact"]
    assert not (config.MEMORY_DIR / "mind" / "expression.db").exists()

def test_only_approved_writer_frames_can_render_and_off_mode_keeps_them(monkeypatch):
    import asyncio
    from services.mind import writers_room

    approved_frame = "A quick result, Boss. {fact}"
    payload = {"kind": "command", "fact": "Opened Chrome."}
    snapshot = present()
    monkeypatch.setattr(writers_room, "_enabled", lambda: True)
    assert writers_room._stage([("command", "neutral", approved_frame)], "testing", NOW) == 1
    assert wording.render(payload, "chill", snapshot, now=NOW) == payload["fact"]
    draft_id = writers_room._pending(0)[0]["id"]
    assert asyncio.run(writers_room.handle(f"approve line {draft_id}")).success
    monkeypatch.setattr(config, "FRIDAY_LLM", "off")
    assert wording.render(payload, "chill", snapshot, now=NOW) == "A quick result, Boss. Opened Chrome."
    payload["fact"] = "Opened Edge."
    assert wording.render(payload, "chill", snapshot, now=NOW) == payload["fact"]
