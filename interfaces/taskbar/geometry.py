"""Pure screen-coordinate placement for the taskbar button and its flyout."""

Rect = tuple[int, int, int, int]


def native_obstacle(bar: Rect, rect: Rect, name: str) -> Rect | None:
    """Clip controls to the bar, excluding only known container placeholders."""
    if name == "Windows.UI.Composition.DesktopWindowContentBridge" and rect == bar:
        return None
    if name == "Windows.UI.Core.CoreWindow" and rect[2] - rect[0] == rect[3] - rect[1] == 65535:
        return None
    clipped = max(bar[0], rect[0]), max(bar[1], rect[1]), min(bar[2], rect[2]), min(bar[3], rect[3])
    return clipped if clipped[0] < clipped[2] and clipped[1] < clipped[3] else None


def widget_slot(bar: Rect, apps: Rect, tray: Rect, intrusions=(), dpi: int = 96) -> Rect | None:
    """Use the first safe gap at the left end, before Start and app controls."""
    left, top, right, bottom = bar
    if right <= left or bottom <= top or right - left <= bottom - top:
        return None
    if not (left <= apps[0] < apps[2] <= tray[0] < tray[2] <= right):
        return None
    for rect in (apps, tray):
        if rect[1] >= bottom or rect[3] <= top:
            return None
    scale = max(1, dpi) / 96
    pad, preferred, minimum = round(8 * scale), round(140 * scale), round(44 * scale)
    start, end = left + pad, apps[0] - pad
    intervals = sorted((max(start, r[0] - pad), min(end, r[2] + pad)) for r in intrusions
                       if r[0] < end and r[2] > start and r[1] < bottom and r[3] > top)
    gaps, cursor = [], start
    for a, b in intervals + [(end, end)]:
        if a > cursor:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    fitting = [(a, b) for a, b in gaps if b - a >= minimum]
    if not fitting:
        return None
    a, b = fitting[0]
    width = min(preferred, b - a)
    inset = min(round(5 * scale), (bottom - top) // 4)
    return a, top + inset, a + width, bottom - inset


def flyout_position(anchor: Rect, width: int, height: int, work: Rect, gap: int = 8) -> tuple[int, int]:
    left, top, right, bottom = work
    x = min(max(anchor[2] - width, left + gap), max(left + gap, right - width - gap))
    y = anchor[1] - height - gap
    if y < top + gap:
        y = anchor[3] + gap
    y = min(max(y, top + gap), max(top + gap, bottom - height - gap))
    return x, y
