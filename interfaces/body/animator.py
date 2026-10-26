"""
interfaces/body/animator.py

What FRIDAY's body is doing, frame by frame — pure logic, no windows (sprite.py draws the Pose).
Each frame gets Inputs (cursor, typing, scrolling, dragging, idle time, and her mind's state from
services/body_state.py) and returns a Frame: the pose, sounds to play and speech bubbles to show.

Everything the desktop pet does, robot-style:
  eyes follow the cursor · blinks every few seconds · looks around when nothing's happening
  typing → feet tap and the screen heats teal → orange → red with your speed
  scrolling → text scrolls across her screen
  shaking the mouse near her → lock-on eyes, a crouch and a hop (hunting)
  stroking her head with the cursor → heart eyes, blush, floating hearts, a hum
  dragging → she dangles, antenna swinging; a squash when she lands
  every 25–40 minutes → a big stretch (screen goes green)
  away for 5 minutes → she falls asleep (z z), and wakes up with a boop when you're back
  her mind: talking → the mouth is a waveform · listening → antenna glows · thinking (AI or Claude
  Code working) → thinking dots and a thought cloud · Claude done → a happy double jump · Claude needs permission → "!" ·
  you laughed at her joke → hearts · game in study mode → side-eye · her questions / reminders → bubbles
"""

import math
import random
from collections import deque
from dataclasses import dataclass, field

from interfaces.body.sprite import Pose, talking_wave

BLINK_EVERY = (2.2, 6.0)
BLINK_SECONDS = 0.16
TYPING_KEYS, TYPING_WINDOW = 5, 2.0     # this many keys in this many seconds = typing
PRESS_SECONDS = 0.15
HEAT_WINDOW, KPS_MIN, KPS_MAX, HEAT_EASE = 1.5, 2.0, 10.0, 0.12
SCROLL_HOLD = 0.6
SHAKE_SPEED = 1400.0                    # px/s of cursor movement that counts as shaking
SHAKE_NEAR = 500.0                      # only shaking this close to her
HUNT_SECONDS = 1.1
PURR_HOLD, HEART_EVERY = 1.0, 0.45
SLEEP_AFTER = 300.0
STRETCH_EVERY = (25 * 60, 40 * 60)
STRETCH_SECONDS = 2.4
HOP_SECONDS, HOP_HEIGHT = 0.45, 7
LAND_SECONDS = 0.35
LOOK_AROUND_AFTER = 8.0                 # cursor still this long → she glances around
TALK_WAVE_EVERY = 0.08
Z_EVERY = 1.2
THOUGHT_PUFFS_PER_SECOND = 2.5


@dataclass
class Inputs:
    t: float                            # seconds (monotonic)
    cursor: tuple = (0.0, 0.0)          # cursor relative to her centre, screen px
    over_head: bool = False             # cursor on her head
    keys: int = 0                       # key presses since the last frame (counted, never which key)
    wheel: int = 0                      # scroll-wheel notches since the last frame
    idle: float = 0.0                   # seconds since any input
    dragging: bool = False
    drag_velocity: tuple = (0.0, 0.0)   # px/s while dragged
    mind: dict = field(default_factory=dict)    # speaking / listening / thinking / study_gaming
    events: list = field(default_factory=list)  # from services/body_state.py


@dataclass
class Frame:
    pose: Pose
    sounds: list
    bubbles: list                       # (text, seconds)


class Animator:
    def __init__(self, t: float = 0.0, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.next_blink = t + self.rng.uniform(*BLINK_EVERY)
        self.blink_until = 0.0
        self.key_times: deque = deque()
        self.press_idx, self.press_until = 0, 0.0
        self.heat = 0.0
        self.scroll_until, self.scroll_phase = 0.0, 0.0
        self.shake, self.last_cursor, self.last_t = 0.0, None, t
        self.hunt_start = -99.0
        self.purr_until, self.next_heart, self.purr_sound_at = 0.0, 0.0, -99.0
        self.asleep, self.wake_until, self.next_z = False, 0.0, 0.0
        self.next_stretch = t + self.rng.uniform(*STRETCH_EVERY)
        self.stretch_start = -99.0
        self.hops: list[float] = []     # start times of queued hops
        self.land_until, self.was_dragging = 0.0, False
        self.alert_until, self.side_until, self.hearts_until = 0.0, 0.0, 0.0
        self.wonder_until = 0.0
        self.antenna, self.antenna_v = 0.0, 0.0
        self.look = [0.0, 0.0]
        self.still_since, self.glance, self.glance_until = t, (0, 0), 0.0
        self.wave, self.next_wave = (1, 2, 1, 2, 1), 0.0
        self.particles: list[dict] = []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def jump(self, t: float, hops: int = 2) -> None:
        start = max([t] + [h + HOP_SECONDS for h in self.hops])
        self.hops += [start + i * HOP_SECONDS for i in range(hops)]

    def _particle(self, kind: str, x: float, y: float, vx: float, vy: float, t: float, life: float) -> None:
        self.particles.append({"kind": kind, "x": x, "y": y, "vx": vx, "vy": vy, "until": t + life})

    def _events(self, inp: Inputs, sounds: list, bubbles: list) -> None:
        t = inp.t
        for e in inp.events:
            kind, text = e.get("kind"), e.get("text") or ""
            if kind == "done":
                self.jump(t, 2)
                sounds.append("chirp")
                bubbles.append(("Done! ✨", 3.0))
            elif kind == "permission":
                self.alert_until = t + 4.0
                self.jump(t, 1)
                sounds.append("alert")
                bubbles.append(("Claude needs your OK, Boss.", 5.0))
            elif kind == "laugh":
                self.hearts_until = t + 2.5
                sounds.append("chirp")
            elif kind == "roast":
                self.side_until = t + 6.0
                bubbles.append((text, 8.0))
            elif kind == "say":
                bubbles.append((text, 90.0))
            elif kind == "wonder":  # her brain noticed something it can't explain
                self.wonder_until = t + 4.0
            elif kind == "alert":
                self.jump(t, 2)
                sounds.append("alert")
                bubbles.append((text, 15.0))

    def _senses(self, inp: Inputs, sounds: list) -> None:
        t, dt = inp.t, max(1e-3, inp.t - self.last_t)
        for _ in range(inp.keys):
            self.key_times.append(t)
        while self.key_times and t - self.key_times[0] > max(TYPING_WINDOW, HEAT_WINDOW):
            self.key_times.popleft()
        if inp.keys and sum(1 for k in self.key_times if t - k <= TYPING_WINDOW) >= TYPING_KEYS:
            self.press_idx += 1
            self.press_until = t + PRESS_SECONDS
        kps = sum(1 for k in self.key_times if t - k <= HEAT_WINDOW) / HEAT_WINDOW
        target = max(0.0, min(1.0, (kps - KPS_MIN) / (KPS_MAX - KPS_MIN))) ** 2
        self.heat += (target - self.heat) * HEAT_EASE
        if inp.wheel:
            self.scroll_until = t + SCROLL_HOLD
            self.scroll_phase += inp.wheel
        # shaking the mouse near her → a hunt
        cx, cy = inp.cursor
        if self.last_cursor is not None:
            speed = math.hypot(cx - self.last_cursor[0], cy - self.last_cursor[1]) / dt
            self.shake *= 0.9
            if speed > SHAKE_SPEED and math.hypot(cx, cy) < SHAKE_NEAR:
                self.shake += min(0.3, (speed - SHAKE_SPEED) / 4000 + 0.1)
            if self.shake >= 1.0 and t - self.hunt_start > HUNT_SECONDS + 1:
                self.shake = 0.0
                self.hunt_start = t
            if inp.over_head and speed > 20:  # a stroke on the head
                if t >= self.purr_until and t - self.purr_sound_at > 2.0:
                    sounds.append("hum")
                    self.purr_sound_at = t
                self.purr_until = t + PURR_HOLD
            if speed > 5:
                self.still_since = t
        self.last_cursor = (cx, cy)
        # sleep / wake
        busy_mind = any(inp.mind.get(k) for k in ("speaking", "listening", "thinking"))
        if not self.asleep and inp.idle >= SLEEP_AFTER and not busy_mind:
            self.asleep = True
        elif self.asleep and (inp.idle < 1.0 or busy_mind or inp.events):
            self.asleep = False
            self.wake_until = t + 0.7
            sounds.append("boop")
        # landing after a drag
        if self.was_dragging and not inp.dragging:
            self.land_until = t + LAND_SECONDS
            sounds.append("boop")
        self.was_dragging = inp.dragging

    def _antenna(self, inp: Inputs, dt: float) -> None:
        push = -inp.drag_velocity[0] / 400 if inp.dragging else 0.0
        self.antenna_v += (-6.0 * self.antenna - 2.2 * self.antenna_v + push * 8) * dt * 4
        self.antenna += self.antenna_v * dt * 4
        self.antenna = max(-2.0, min(2.0, self.antenna))

    # ── A frame ───────────────────────────────────────────────────────────────

    def step(self, inp: Inputs) -> Frame:
        t = inp.t
        dt = max(1e-3, t - self.last_t)
        sounds, bubbles = [], []
        self._events(inp, sounds, bubbles)
        self._senses(inp, sounds)
        self._antenna(inp, dt)
        pose = Pose(heat=self.heat)

        # the eyes follow the cursor (and glance around when it's been still a while)
        tx, ty = max(-2.0, min(2.0, inp.cursor[0] / 150)), max(-1.0, min(1.0, inp.cursor[1] / 200))
        if t - self.still_since > LOOK_AROUND_AFTER:
            if t >= self.glance_until:
                self.glance = (self.rng.choice((-2, -1, 0, 1, 2)), self.rng.choice((-1, 0, 0, 1)))
                self.glance_until = t + self.rng.uniform(1.0, 2.5)
            tx, ty = self.glance
        self.look[0] += (tx - self.look[0]) * 0.25
        self.look[1] += (ty - self.look[1]) * 0.25
        pose.look = (round(self.look[0]), round(self.look[1]))

        if t >= self.next_blink:
            self.blink_until = t + BLINK_SECONDS
            self.next_blink = t + self.rng.uniform(*BLINK_EVERY)

        self.hops = [h for h in self.hops if t < h + HOP_SECONDS]
        hopping = [h for h in self.hops if h <= t]
        stretching = t - self.stretch_start < STRETCH_SECONDS
        hunting = t - self.hunt_start < HUNT_SECONDS
        if (not self.asleep and not stretching and not hopping and not hunting and not inp.dragging
                and t >= self.next_stretch and t >= self.press_until):
            self.stretch_start, stretching = t, True
            self.next_stretch = t + self.rng.uniform(*STRETCH_EVERY)
            sounds.append("chirp")

        # the main action (first match wins)
        if inp.dragging:
            pose.dangle, pose.eyes, pose.mouth = True, "wide", "o"
            pose.squash = 1.0 + min(0.15, abs(inp.drag_velocity[1]) / 3000)
        elif t < self.land_until:
            k = (self.land_until - t) / LAND_SECONDS
            pose.squash, pose.eyes = 1.0 - 0.2 * k, "happy"
        elif stretching:
            k = (t - self.stretch_start) / STRETCH_SECONDS
            up = math.sin(math.pi * min(1.0, k / 0.8))
            pose.squash, pose.fresh, pose.eyes, pose.mouth = 1.0 + 0.2 * up, up, "happy", "o"
            pose.feet = (1, 0, 0, 1) if up > 0.5 else (0, 0, 0, 0)
        elif hopping:
            k = (t - hopping[0]) / HOP_SECONDS
            pose.dy = -round(HOP_HEIGHT * math.sin(math.pi * k))
            pose.squash = 0.88 if k < 0.12 or k > 0.9 else 1.05
            pose.eyes, pose.mouth, pose.feet = "happy", "smile", (1, 1, 1, 1) if pose.dy < -2 else (0, 0, 0, 0)
        elif hunting:
            k = (t - self.hunt_start) / HUNT_SECONDS
            pose.eyes, pose.mouth = "target", "flat"
            pose.look = (2 if inp.cursor[0] > 0 else -2, pose.look[1])
            if k < 0.35:
                pose.squash = 0.85
            elif k < 0.8:
                pose.dy = -round(6 * math.sin(math.pi * (k - 0.35) / 0.45))
                pose.feet = (1, 1, 1, 1)
            else:
                pose.squash = 0.9
        elif self.asleep:
            pose.eyes, pose.mouth, pose.look, pose.antenna = "sleep", "line", (0, 0), 1
            pose.squash = 0.98 + 0.02 * math.sin(t * 1.6)
            if t >= self.next_z:
                self._particle("z", 40, 22, 4, -5, t, 3.0)
                self.next_z = t + Z_EVERY
        elif t < self.purr_until:
            pose.eyes, pose.mouth, pose.blush = "heart", "smile", True
            if t >= self.next_heart:
                self._particle("heart", self.rng.uniform(36, 46), 20, self.rng.uniform(-2, 2), -9, t, 1.6)
                self.next_heart = t + HEART_EVERY
        elif t < self.scroll_until:
            pose.screen, pose.scroll = "scroll", int(self.scroll_phase)
        elif t < self.press_until:
            pose.eyes = "focus"
            pose.feet = (0, 1, 0, 0) if self.press_idx % 2 else (0, 0, 1, 0)

        if pose.squash == 1.0 and not self.asleep and pose.dy == 0:
            pose.squash = 1.0 + 0.012 * math.sin(t * 2.2)  # idle breathing
            pose.squash = 1.0 if abs(pose.squash - 1.0) < 0.01 else pose.squash

        # her mind on top of whatever she's doing
        mind = inp.mind
        awake_face = not self.asleep and pose.screen == "face"
        if awake_face and (inp.mind.get("study_gaming") or t < self.side_until) and pose.eyes == "sparkle":
            pose.eyes, pose.mouth = "side", "flat"
        if awake_face and mind.get("thinking") and not mind.get("speaking"):
            # thinking dots on her mouth, and a thought trail puffs up beside her head —
            # small bubble, bigger bubble, then the cloud — while her eyes keep following the cursor
            pose.mouth, pose.dots = "dots", int(t * 4)
            puffs = int(t * THOUGHT_PUFFS_PER_SECOND) % 5  # 0-2 puffs appear, then all held for two beats
            pose.extras += [("puff1", 44, 22), ("puff2", 47, 17), ("cloud", 42, 2 + round(math.sin(t * 3)))][:puffs + 1]
        if mind.get("listening"):
            pose.glow = int(t * 3) % 2 == 0
            if awake_face and pose.eyes in ("sparkle", "focus", "side"):
                pose.eyes, pose.mouth = "wide", "o"
        if awake_face and mind.get("speaking"):
            if t >= self.next_wave:
                self.wave, self.next_wave = talking_wave(self.rng), t + TALK_WAVE_EVERY
            pose.mouth, pose.wave = "wave", self.wave
        if t < self.alert_until:
            pose.eyes = "alarm"
            pose.extras.append(("!", 44, 14))
        elif t < self.wonder_until:
            pose.extras.append(("?", 44, 14))
        if t < self.hearts_until:
            pose.eyes, pose.blush = "happy", True
            if t >= self.next_heart:
                self._particle("heart", self.rng.uniform(34, 48), 20, self.rng.uniform(-3, 3), -10, t, 1.6)
                self.next_heart = t + HEART_EVERY / 2
        if t < self.wake_until:
            pose.eyes = "wide"
        if t < self.blink_until and pose.eyes in ("sparkle", "focus", "wide", "side"):
            pose.eyes = "blink"
        if not pose.glow:
            pose.antenna = pose.antenna or round(self.antenna)

        # floating hearts and z's
        alive = []
        for p in self.particles:
            if t < p["until"]:
                p["x"] += p["vx"] * dt
                p["y"] += p["vy"] * dt
                alive.append(p)
                pose.extras.append((p["kind"], round(p["x"]), round(p["y"])))
        self.particles = alive
        self.last_t = t
        return Frame(pose, sounds, bubbles)
