import asyncio
import random

from interfaces.api.routes import body as body_route
from interfaces.body import sounds, sprite
from interfaces.body.animator import SLEEP_AFTER, Animator, Inputs
from interfaces.body.sprite import Pose
from services import body_state


# ── The art ───────────────────────────────────────────────────────────────────

def test_every_expression_draws_with_only_palette_colours():
    palette = {v for k, v in vars(sprite).items() if isinstance(v, tuple) and len(v) == 3 and k.isupper()}
    palette |= set(sprite.HOT) | {sprite.screen_colour(h / 10) for h in range(11)} | {sprite.screen_colour(0, 1)}
    for eyes in sprite.EYE_STYLES:
        for mouth in sprite.MOUTHS:
            img = sprite.render(Pose(eyes=eyes, mouth=mouth, blush=True, glow=True, extras=[("heart", 44, 12), ("z", 40, 8)]))
            assert img.size == (sprite.W * sprite.SCALE, sprite.H * sprite.SCALE)
            colours = {c for _, c in img.getcolors(10000)}
            assert sprite.KEY in colours and len(colours - palette) <= 3  # heat blends are the only extras


def test_squash_hop_and_scroll_draw():
    for pose in (Pose(squash=0.8), Pose(squash=1.2, fresh=1), Pose(dy=-7), Pose(dy=2, dangle=True),
                 Pose(screen="scroll", scroll=5), Pose(heat=1.0)):
        assert sprite.render(pose).size == (sprite.W * sprite.SCALE, sprite.H * sprite.SCALE)


# ── What she does ─────────────────────────────────────────────────────────────

def run(anim, seconds, start, **kw):
    """Step at 30 fps; returns the frames."""
    frames, t = [], start
    while t < start + seconds:
        frames.append(anim.step(Inputs(t=t, **kw)))
        t += 1 / 30
    return frames


def fresh(t=0.0):
    a = Animator(t, rng=random.Random(1))
    a.next_stretch = 10 ** 9  # tests that want a stretch set it
    return a


def test_she_blinks_and_follows_the_cursor():
    frames = run(fresh(), 8, 0, cursor=(600, -400))
    assert any(f.pose.eyes == "blink" for f in frames)
    assert frames[-1].pose.look == (2, -1)


def test_typing_taps_her_feet_and_heats_the_screen():
    a = fresh()
    frames = run(a, 2, 0, keys=1)  # 30 keys a second
    assert any(f.pose.eyes == "focus" and any(f.pose.feet) for f in frames)
    assert frames[-1].pose.heat > 0.5
    calm = run(a, 4, 2)
    assert calm[-1].pose.heat < 0.1


def test_scrolling_scrolls_her_screen():
    assert fresh().step(Inputs(t=0, wheel=2)).pose.screen == "scroll"


def test_shaking_the_mouse_near_her_starts_a_hunt():
    a = fresh()
    poses = []
    for i in range(30):
        poses.append(a.step(Inputs(t=i / 30, cursor=(-250 if i % 2 else 250, 0))).pose)
    assert any(p.eyes == "target" for p in poses)


def test_stroking_her_head_makes_her_purr():
    a = fresh()
    frames = [a.step(Inputs(t=i / 30, cursor=(i * 3, -80), over_head=True)) for i in range(30)]
    assert any(f.pose.eyes == "heart" for f in frames) and ["hum"] in [f.sounds for f in frames]
    assert any(kind == "heart" for f in frames for kind, _, _ in f.pose.extras)


def test_she_falls_asleep_and_wakes_up():
    a = fresh()
    sleepy = run(a, 3, 0, idle=SLEEP_AFTER + 1)
    assert sleepy[-1].pose.eyes == "sleep" and any(k == "z" for k, _, _ in sleepy[-1].pose.extras)
    woke = a.step(Inputs(t=3.1, idle=0.2))
    assert "boop" in woke.sounds and woke.pose.eyes == "wide"


def test_dragging_and_landing():
    a = fresh()
    held = a.step(Inputs(t=0, dragging=True, drag_velocity=(900, -600)))
    assert held.pose.dangle and held.pose.squash > 1
    landed = a.step(Inputs(t=0.05))
    assert "boop" in landed.sounds and landed.pose.squash < 1


def test_a_stretch_now_and_then():
    a = fresh()
    a.next_stretch = 1.0
    frames = run(a, 2.5, 0)
    assert any(f.pose.squash > 1.1 and f.pose.fresh > 0.5 for f in frames)
    assert a.next_stretch > 20 * 60


def test_thinking_shows_a_thought_cloud_and_still_follows_the_cursor():
    frames = run(fresh(), 2, 0, cursor=(-600, 400), mind={"thinking": True})
    assert any(kind == "cloud" for f in frames for kind, _, _ in f.pose.extras)
    assert frames[-1].pose.look == (-2, 1)


def test_her_mind_shows_on_her_face():
    a = fresh()
    talking = run(a, 0.5, 0, mind={"speaking": True})
    assert talking[-1].pose.mouth == "wave" and len({f.pose.wave for f in talking}) > 1
    assert run(a, 0.2, 1, mind={"thinking": True})[-1].pose.mouth == "dots"
    listening = run(a, 1, 2, mind={"listening": True})
    assert any(f.pose.glow for f in listening) and listening[-1].pose.mouth == "o"
    assert run(a, 0.3, 4, mind={"study_gaming": True})[-1].pose.eyes in ("side", "blink")


def test_events_jump_alert_hearts_and_bubbles():
    a = fresh()
    first = a.step(Inputs(t=0, events=[{"kind": "done"}]))
    assert "chirp" in first.sounds and first.bubbles
    assert any(f.pose.dy < -3 for f in run(a, 1, 0.03))                      # a happy double jump
    alarm = a.step(Inputs(t=2, events=[{"kind": "permission"}]))
    assert "alert" in alarm.sounds and any(k == "!" for k, _, _ in alarm.pose.extras)
    asked = a.step(Inputs(t=8, events=[{"kind": "say", "text": "What are you building, Boss?"}]))
    assert asked.bubbles == [("What are you building, Boss?", 90.0)]
    laugh = run(a, 1, 9, events=[])
    a.step(Inputs(t=10, events=[{"kind": "laugh"}]))
    assert any(k == "heart" for f in run(a, 1, 10.03) for k, _, _ in f.pose.extras) and laugh


def test_robot_sounds_are_made_once(tmp_path):
    files = sounds.ensure(tmp_path)
    assert set(files) == {"chirp", "boop", "hum", "alert"} and all(p.stat().st_size > 1000 for p in files.values())
    stamp = files["chirp"].stat().st_mtime
    assert sounds.ensure(tmp_path)["chirp"].stat().st_mtime == stamp


# ── Her mind, from the backend ────────────────────────────────────────────────

def test_claude_working_is_thinking_and_done_is_an_event():
    start = body_state.last_id()
    body_state.claude({"hook_event_name": "UserPromptSubmit", "session_id": "s1"})
    assert body_state.snapshot()["thinking"]
    body_state.claude({"hook_event_name": "PermissionRequest", "session_id": "s1"})
    body_state.claude({"hook_event_name": "Stop", "session_id": "s1"})
    assert not body_state.snapshot()["thinking"]
    assert [e["kind"] for e in body_state.events_since(start)] == ["permission", "done"]


def test_ai_calls_show_as_thinking():
    with body_state.thinking():
        assert body_state.snapshot()["thinking"]
    assert not body_state.snapshot()["thinking"]


def test_the_body_route():
    body_state.push("say", "Hello, Boss.")
    last = body_state.last_id()
    data = asyncio.run(body_route.body(since=last - 1))
    assert data["last"] == last and data["events"][-1]["text"] == "Hello, Boss."
    assert {"speaking", "listening", "thinking", "study_gaming"} <= set(data)
