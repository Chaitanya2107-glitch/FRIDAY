"""State-driven desktop orb, drawn with the Pillow already used by the body.

The waveform is an animation of speech activity, not measured audio amplitude.
Rendering and hit testing are pure so previews never need a microphone/backend.
"""

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 168, 192
KEY = (255, 0, 255)
STALE_SECONDS = 2.0
THEMES = {
    "ready": ((101, 211, 234), "READY"),
    "listening": ((67, 238, 204), "LISTENING"),
    "thinking": ((133, 156, 255), "THINKING"),
    "speaking": ((201, 156, 255), "SPEAKING"),
    "attention": ((255, 203, 119), "FOR YOU"),
    "reconnecting": ((145, 157, 181), "RECONNECTING"),
}


def state_for(mind: dict, *, fresh: bool, attention: bool = False) -> str:
    """Never display stale activity as a live microphone or speech state."""
    if not fresh:
        return "reconnecting"
    for state in ("speaking", "listening", "thinking"):
        if mind.get(state):
            return state
    return "attention" if attention else "ready"


def control_at(x: float, y: float, *, expanded: bool) -> str | None:
    if expanded and 158 <= y <= 184:
        if 16 <= x <= 80:
            return "talk"
        if 88 <= x <= 152:
            return "chat"
    return None


@lru_cache(maxsize=12)
def _font(size: int):
    try:
        return ImageFont.truetype("segoeui.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def render(state: str, t: float, *, expanded: bool = False, reduced_motion: bool = False,
           dragging: bool = False) -> Image.Image:
    """Draw into the existing 168 x 192 transparent host, without resizing it."""
    accent, label = THEMES.get(state, THEMES["reconnecting"])
    if reduced_motion:
        t = 0.0
    scale = 2
    image = Image.new("RGBA", (WIDTH * scale, HEIGHT * scale))
    draw = ImageDraw.Draw(image)
    cx, cy = 84, 75
    active = state in ("listening", "thinking", "speaking", "attention")
    pulse = math.sin(t * (3.8 if active else 1.6))
    radius = 39 + pulse * (1.5 if active else .6) + (2 if expanded else 0)

    def box(r):
        return tuple(round(v * scale) for v in (cx - r, cy - r, cx + r, cy + r))

    def line(points, fill, width=1):
        draw.line([(round(x * scale), round(y * scale)) for x, y in points],
                  fill=fill, width=max(1, round(width * scale)))

    # Restrained concentric bloom outside a deep, glassy core.
    for r in range(61, 43, -1):
        alpha = round((62 - r) * (2.1 if active or expanded else 1.1))
        draw.ellipse(box(r), outline=(*accent, alpha), width=scale)
    for r in range(43, 0, -1):
        edge = (r / 43) ** 3
        color = tuple(round(a * edge * .20 + b * (1 - edge))
                      for a, b in zip(accent, (13, 19, 38)))
        draw.ellipse(box(r), fill=(*color, 255))

    draw.ellipse(box(radius), outline=(*accent, 210), width=scale)
    draw.ellipse(box(radius - 3), outline=(*accent, 50), width=scale)
    angle = t * (100 if state == "thinking" else 22)
    for offset, length in ((0, 68), (180, 32)):
        draw.arc(box(radius + 6), angle + offset, angle + offset + length,
                 fill=(*accent, 205), width=2 * scale)

    # Three flowing filaments form the recognizable core of Friday's presence.
    for band in range(3):
        points = []
        for step in range(89):
            x = -29 + step * 58 / 88
            envelope = max(0, 1 - (x / 31) ** 2)
            strength = 10 if state == "speaking" else 5 if state == "listening" else 3
            y = math.sin(x / 9 + t * (4 if active else 1) + band * 1.6)
            points.append((cx + x, cy + (band - 1) * 5 + y * strength * envelope))
        line(points, (*accent, 205 - band * 45), 1.4)

    if state == "listening":
        phase = (t * .6) % 1
        draw.ellipse(box(47 + phase * 10), outline=(*accent, round(150 * (1 - phase))), width=scale)
    elif state == "thinking":
        for i in range(3):
            a = math.radians(-angle * 1.5 + i * 120)
            x, y = cx + 30 * math.cos(a), cy + 30 * math.sin(a)
            draw.ellipse(tuple(round(v * scale) for v in (x - 2, y - 2, x + 2, y + 2)),
                         fill=(*accent, 240))
    elif state == "attention":
        draw.ellipse((81 * scale, 48 * scale, 87 * scale, 54 * scale), fill=(*accent, 255))

    # Typography remains legible without hovering; controls appear on approach.
    draw.text((84 * scale, 125 * scale), "F R I D A Y", font=_font(10 * scale),
              anchor="mm", fill=(229, 239, 250, 255))
    draw.text((84 * scale, 143 * scale), "MOVE ME" if dragging else label,
              font=_font(8 * scale), anchor="mm", fill=(*accent, 255))
    if expanded:
        for left, right, text in ((16, 80, "STOP" if state == "listening" else "TALK"),
                                  (88, 152, "CHAT")):
            draw.rounded_rectangle((left * scale, 158 * scale, right * scale, 184 * scale),
                                   radius=10 * scale, fill=(16, 24, 42, 255),
                                   outline=(*accent, 145), width=scale)
            draw.text(((left + right) / 2 * scale, 171 * scale), text,
                      font=_font(9 * scale), anchor="mm", fill=(233, 242, 251, 255))

    # Color-key windows require hard alpha edges. Threshold after supersampling
    # to retain smooth interior detail without a magenta fringe on the desktop.
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    result = Image.new("RGB", image.size, KEY)
    result.paste(image.convert("RGB"), mask=image.getchannel("A").point(lambda a: 255 if a >= 100 else 0))
    return result
