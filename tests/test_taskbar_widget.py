"""Geometry checks protect the taskbar's native controls and monitor edges."""

from interfaces.taskbar.geometry import flyout_position, native_obstacle, widget_slot


def overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def test_native_taskbar_gap_handles_autohide_and_dpi():
    bar = (0, 1078, 1920, 1138)
    apps, tray = (713, 1078, 988, 1138), (1490, 1078, 1920, 1138)
    slot = widget_slot(bar, apps, tray, dpi=120)
    assert slot == (10, 1084, 185, 1132)
    assert not overlap(slot, apps) and not overlap(slot, tray)
    assert slot[2] < apps[0]
    assert widget_slot((-1920, 1078, 0, 1138), (-1207, 1078, -932, 1138),
                       (-430, 1078, 0, 1138), dpi=120) == (-1910, 1084, -1735, 1132)


def test_unknown_or_crowded_layout_never_covers_native_controls():
    bar = (0, 1020, 1920, 1080)
    assert widget_slot(bar, (0, 1020, 1480, 1080), (1490, 1020, 1920, 1080)) is None
    assert widget_slot(bar, (0, 0, 0, 0), (1490, 1020, 1920, 1080)) is None
    assert widget_slot(bar, (0, 0, 1000, 60), (1490, 1020, 1920, 1080)) is None
    assert widget_slot((0, 0, 60, 1080), (0, 0, 60, 500), (0, 800, 60, 1080)) is None


def test_other_native_controls_split_the_gap_safely():
    bar, apps, tray = (0, 1020, 1920, 1080), (600, 1020, 1000, 1080), (1500, 1020, 1920, 1080)
    intrusion = (0, 1020, 200, 1080)
    slot = widget_slot(bar, apps, tray, [intrusion])
    assert slot and not overlap(slot, intrusion)
    assert slot[0] >= intrusion[2] + 8
    assert widget_slot(bar, apps, tray, [(0, 1020, 600, 1080)]) is None


def test_flyout_anchors_above_and_clamps_to_negative_coordinate_monitors():
    anchor = (-300, 1020, -140, 1080)
    x, y = flyout_position(anchor, 390, 540, (-1920, 0, 0, 1020))
    assert (x, y) == (-530, 472)
    x, y = flyout_position((-1910, 1000, -1850, 1080), 390, 540, (-1920, 0, 0, 1020))
    assert -1920 < x and x + 390 < 0 and 0 < y and y + 540 < 1020
    x, y = flyout_position((100, 0, 240, 50), 390, 540, (0, 50, 1920, 1080))
    assert x == 8 and y == 58


def test_native_containers_and_partial_controls_are_distinguished():
    bar = (0, 1020, 1920, 1080)
    bridge = "Windows.UI.Composition.DesktopWindowContentBridge"
    core = "Windows.UI.Core.CoreWindow"
    assert native_obstacle(bar, bar, bridge) is None
    assert native_obstacle(bar, (0, 1020, 65535, 66555), core) is None
    for name in (bridge, core, "UnknownControl"):
        assert native_obstacle(bar, (1200, 1010, 1350, 1060), name) == (1200, 1020, 1350, 1060)
        assert native_obstacle(bar, (1200, 100, 1350, 200), name) is None
