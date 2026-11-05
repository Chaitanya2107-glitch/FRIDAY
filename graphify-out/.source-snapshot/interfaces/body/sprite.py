"""
interfaces/body/sprite.py

FRIDAY's body, drawn pixel by pixel: a round lavender-white robot with a curved antenna, dark ear
pods, four stubby feet and a teal screen for a face (after the reference sprite the Boss picked). Every
frame is drawn from a Pose, so the face can show anything: sparkle eyes, blinks, ^^, hearts, a
lock-on target, sleepy lines, a talking waveform, thinking dots, scrolling text.

render(pose) → an RGB image SCALE× bigger, with KEY where it's see-through (the window makes KEY
transparent, so no anti-aliasing anywhere — every pixel is one of the palette colours).
"""

import random
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

W, H = 56, 64          # the drawing grid; the window is SCALE× this
SCALE = 3
CX, CY = 28, 40        # centre of the round body
BASE = CY + 16         # where the body meets the ground (squash is anchored here)
KEY = (255, 0, 255)    # see-through (never used in the art)

OUT = (37, 36, 66)
BODY = (232, 231, 237)
BODY_HI = (250, 250, 253)
SHADE = (196, 192, 207)
SHADE2 = (150, 145, 163)
EAR = (52, 50, 80)
EAR_DOT = (222, 222, 236)
BEZEL = (69, 72, 96)
SCREEN = (84, 154, 164)
SCREEN_HI = (110, 178, 186)
EYE = (250, 240, 170)
EYE_HI = (255, 255, 236)
EYE_DIM = (170, 210, 190)
BLUSH = (232, 146, 170)
HEART = (236, 96, 120)
GLOW = (120, 232, 255)
ZZZ = (205, 205, 232)
HOT = [(84, 154, 164), (214, 150, 80), (214, 86, 72)]      # the screen as typing heats up
FRESH = (96, 190, 120)                                      # the screen during a stretch

EYE_STYLES = ("sparkle", "blink", "happy", "wide", "target", "sleep", "side", "heart", "focus", "alarm")
MOUTHS = ("line", "smile", "o", "flat", "wave", "none", "dots")


@dataclass
class Pose:
    dy: int = 0                    # up (negative) / down
    squash: float = 1.0            # < 1 squashed, > 1 stretched (anchored at the feet)
    look: tuple = (0, 0)           # eyes: -2..2 across, -1..1 up/down
    eyes: str = "sparkle"
    mouth: str = "line"
    wave: tuple = (1, 2, 1, 2, 1)  # mouth heights while talking (0-2)
    dots: int = 0                  # which thinking dot is lit
    screen: str = "face"           # "face" or "scroll"
    scroll: int = 0                # scrolling text phase
    heat: float = 0.0              # 0 teal … 1 red
    fresh: float = 0.0             # 0 teal … 1 green (stretching)
    blush: bool = False
    antenna: int = 0               # tip sway, -2..2
    glow: bool = False             # antenna tip lit (listening)
    feet: tuple = (0, 0, 0, 0)     # lift per foot (outer-left, inner-left, inner-right, outer-right)
    dangle: bool = False           # held in the air: feet hang
    extras: list = field(default_factory=list)  # (kind, x, y): "heart", "z", "!", "?", "note", "puff1", "puff2", "cloud"


def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def screen_colour(heat: float, fresh: float = 0.0):
    base = _mix(HOT[0], HOT[1], heat * 2) if heat < 0.5 else _mix(HOT[1], HOT[2], heat * 2 - 1)
    return _mix(base, FRESH, fresh)


def _px(d: ImageDraw.ImageDraw, pts, colour):
    for p in pts:
        d.point(p, fill=colour)


# ── Parts ─────────────────────────────────────────────────────────────────────

def _feet(d, pose: Pose, front: bool):
    spots = [(-13, 11), (-6, 14), (4, 14), (11, 11)]  # (x, top): the outer two sit further back
    for i, (fx, top) in enumerate(spots):
        if (i in (1, 2)) != front:
            continue
        y = CY + top - pose.feet[i] + (2 if pose.dangle else 0)
        x = CX + fx
        d.ellipse((x - 2, y, x + 3, y + 4), fill=EAR, outline=OUT)
        d.point((x - 1, y + 1), fill=SHADE2)


def _body(d):
    d.ellipse((CX - 17, CY - 17, CX + 17, CY + 16), fill=SHADE2, outline=OUT)
    d.ellipse((CX - 16, CY - 16, CX + 15, CY + 14), fill=SHADE)
    d.ellipse((CX - 16, CY - 16, CX + 13, CY + 11), fill=BODY)
    d.ellipse((CX - 12, CY - 14, CX - 5, CY - 11), fill=BODY_HI)
    d.point((CX - 13, CY - 9), fill=BODY_HI)


def _ears(d):
    d.ellipse((CX - 22, CY - 4, CX - 14, CY + 6), fill=EAR, outline=OUT)
    d.rectangle((CX - 20, CY, CX - 19, CY + 1), fill=EAR_DOT)
    d.ellipse((CX + 14, CY - 3, CX + 20, CY + 5), fill=EAR, outline=OUT)
    d.point((CX + 17, CY), fill=EAR_DOT)


def _antenna(d, pose: Pose):
    stalk = [(0, -17), (0, -18), (0, -19), (0, -20), (-1, -21), (-2, -22), (-3, -23)]
    for i, (x, y) in enumerate(stalk):
        sway = round(pose.antenna * i / (len(stalk) - 1))
        px, py = CX + x + sway, CY + y
        _px(d, [(px - 1, py), (px + 2, py)], OUT)
        _px(d, [(px, py), (px + 1, py)], BODY if i < 4 else SHADE)
    tx, ty = CX - 5 + pose.antenna, CY - 27  # the tip: a small dark ball
    d.rectangle((tx, ty + 1, tx + 3, ty + 2), fill=OUT)
    d.rectangle((tx + 1, ty, tx + 2, ty + 3), fill=OUT)
    d.point((tx + 1, ty + 1), fill=GLOW if pose.glow else EAR_DOT)
    if pose.glow:
        _px(d, [(tx + 1, ty - 2), (tx + 2, ty - 2), (tx - 2, ty + 1), (tx + 5, ty + 2), (tx + 1, ty + 5), (tx + 2, ty + 5)], GLOW)


def _eye(d, x, y, style):
    """One eye in a 4×4 box whose top-left is (x, y)."""
    if style == "sparkle":  # a chunky rounded sparkle, like the reference
        d.rectangle((x + 1, y, x + 2, y + 3), fill=EYE)
        d.rectangle((x, y + 1, x + 3, y + 2), fill=EYE)
        d.point((x + 1, y + 1), fill=EYE_HI)
    elif style == "blink":
        d.line((x, y + 2, x + 3, y + 2), fill=EYE)
    elif style == "happy":
        _px(d, [(x, y + 2), (x + 1, y + 1), (x + 2, y + 1), (x + 3, y + 2)], EYE)
    elif style == "wide":
        d.rectangle((x, y, x + 3, y + 3), fill=EYE)
        d.rectangle((x + 1, y + 1, x + 1, y + 1), fill=EYE_HI)
    elif style == "target":
        d.rectangle((x, y, x + 3, y + 3), outline=EYE)
        d.rectangle((x + 1, y + 1, x + 2, y + 2), fill=HOT[2])
    elif style == "sleep":
        d.line((x, y + 3, x + 3, y + 3), fill=EYE_DIM)
    elif style == "side":
        d.rectangle((x, y + 2, x + 3, y + 3), fill=EYE)
        d.line((x, y, x + 3, y), fill=BEZEL)
    elif style == "heart":
        _px(d, [(x, y), (x + 3, y)], HEART)
        d.rectangle((x, y + 1, x + 3, y + 1), fill=HEART)
        d.rectangle((x + 1, y + 2, x + 2, y + 2), fill=HEART)
        d.point((x + 1, y + 3), fill=HEART)
        d.point((x + 2, y + 3), fill=HEART)
    elif style == "focus":
        d.rectangle((x, y + 1, x + 3, y + 2), fill=EYE)
    elif style == "alarm":
        d.rectangle((x + 1, y - 1, x + 2, y + 3), fill=EYE_HI)


def _mouth(d, pose: Pose, x, y):
    style = pose.mouth
    if style == "line":
        _px(d, [(x - 1, y), (x, y), (x + 1, y)], EYE)
    elif style == "smile":
        _px(d, [(x - 2, y - 1), (x - 1, y), (x, y), (x + 1, y), (x + 2, y - 1)], EYE)
    elif style == "o":
        d.rectangle((x - 1, y - 1, x, y), fill=EYE)
    elif style == "flat":
        _px(d, [(x - 2, y), (x - 1, y), (x, y), (x + 1, y), (x + 2, y)], EYE_DIM)
    elif style == "wave":
        for i, h in enumerate(pose.wave[:5]):
            d.line((x - 2 + i, y - max(0, min(2, h)), x - 2 + i, y), fill=EYE)
    elif style == "dots":
        for i, dx in enumerate((-3, 0, 3)):
            d.point((x + dx, y), fill=EYE_HI if i == pose.dots % 3 else EYE_DIM)


def _screen(d, pose: Pose):
    d.rounded_rectangle((CX - 13, CY - 7, CX + 12, CY + 9), radius=3, fill=BEZEL, outline=OUT)
    colour = screen_colour(pose.heat, pose.fresh)
    d.rounded_rectangle((CX - 11, CY - 5, CX + 10, CY + 7), radius=2, fill=colour)
    d.line((CX - 9, CY - 5, CX + 8, CY - 5), fill=_mix(colour, SCREEN_HI, 0.6))
    if pose.screen == "scroll":
        widths = (14, 9, 16, 6, 12, 10)
        for i, width in enumerate(widths):
            y = CY - 4 + (i * 3 - pose.scroll) % 12
            if CY - 4 <= y <= CY + 6:
                d.line((CX - 9, y, CX - 9 + width, y), fill=EYE if i % 2 else EYE_DIM)
        return
    lx, ly = max(-2, min(2, pose.look[0])), max(-1, min(1, pose.look[1]))
    _eye(d, CX - 8 + lx, CY - 3 + ly, pose.eyes)
    _eye(d, CX + 3 + lx, CY - 3 + ly, pose.eyes)
    if pose.blush:
        _px(d, [(CX - 10 + lx, CY + 3), (CX - 9 + lx, CY + 3), (CX + 7 + lx, CY + 3), (CX + 8 + lx, CY + 3)], BLUSH)
    _mouth(d, pose, CX + (lx + 1) // 2, CY + 5 + (1 if ly > 0 else 0))


def _extra(d, kind, x, y):
    if kind == "heart":
        _px(d, [(x - 1, y), (x + 1, y), (x - 2, y + 1), (x - 1, y + 1), (x, y + 1), (x + 1, y + 1), (x + 2, y + 1),
                (x - 1, y + 2), (x, y + 2), (x + 1, y + 2), (x, y + 3)], HEART)
    elif kind == "z":
        d.line((x, y, x + 3, y), fill=ZZZ)
        _px(d, [(x + 2, y + 1), (x + 1, y + 2)], ZZZ)
        d.line((x, y + 3, x + 3, y + 3), fill=ZZZ)
    elif kind == "!":
        d.line((x, y, x, y + 3), fill=HOT[2])
        d.point((x, y + 5), fill=HOT[2])
    elif kind == "?":
        _px(d, [(x, y), (x + 1, y), (x + 2, y + 1), (x + 1, y + 2), (x + 1, y + 4)], EYE)
    elif kind == "puff1":  # the thought trail: a small bubble, a bigger one, then the cloud
        d.rectangle((x, y, x + 2, y + 2), fill=BODY, outline=OUT)
    elif kind == "puff2":
        d.ellipse((x, y, x + 4, y + 3), fill=BODY, outline=OUT)
    elif kind == "cloud":
        for bump in ((x, y + 2, x + 6, y + 8), (x + 4, y, x + 10, y + 7), (x + 7, y + 2, x + 13, y + 8)):
            d.ellipse(bump, fill=OUT)
        for bump in ((x + 1, y + 3, x + 5, y + 7), (x + 5, y + 1, x + 9, y + 6), (x + 8, y + 3, x + 12, y + 7)):
            d.ellipse(bump, fill=BODY)
        _px(d, [(x + 4, y + 5), (x + 6, y + 5), (x + 8, y + 5)], SHADE2)
    elif kind == "note":
        _px(d, [(x + 2, y), (x + 2, y + 1), (x + 2, y + 2), (x + 1, y + 3), (x + 2, y + 3), (x + 3, y)], GLOW)


# ── A frame ───────────────────────────────────────────────────────────────────

def render(pose: Pose) -> Image.Image:
    """One frame, SCALE× bigger, KEY where see-through."""
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    _antenna(d, pose)
    _body(d)
    _ears(d)
    _screen(d, pose)
    if pose.squash != 1.0:  # squash & stretch, anchored where the body meets the ground
        new_w, new_h = max(8, round(W * (2 - pose.squash))), max(8, round(BASE * pose.squash))
        top = body.crop((0, 0, W, BASE)).resize((new_w, new_h), Image.NEAREST)
        body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        body.paste(top, ((W - new_w) // 2, BASE - new_h), top)
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _feet(ImageDraw.Draw(frame), pose, front=False)
    frame.paste(body, (0, 0), body)
    _feet(ImageDraw.Draw(frame), pose, front=True)
    if pose.dy:  # a hop (up) or a landing (down)
        moved = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        moved.paste(frame, (0, pose.dy), frame)
        frame = moved
    ed = ImageDraw.Draw(frame)
    for kind, x, y in pose.extras:
        _extra(ed, kind, x, y)
    out = Image.new("RGB", (W, H), KEY)
    out.paste(frame, mask=frame.split()[3].point(lambda a: 255 if a > 0 else 0))
    return out.resize((W * SCALE, H * SCALE), Image.NEAREST)


def talking_wave(rng: random.Random = random) -> tuple:
    return tuple(rng.randint(0, 2) for _ in range(5))
