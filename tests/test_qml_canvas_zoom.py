"""Zooming and moving things on the flow canvas, driven with the real mouse and wheel: the point under the cursor stays put, a
gentle scroll zooms gently, a module follows the pointer exactly at any zoom, and Fit really fits."""
import math

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QGuiApplication, QWheelEvent
from PyQt6.QtTest import QTest

from test_qml_interaction import fresh, ui, port  # noqa: F401  (fixtures)

MINUS = "−"
FIT = "□"


def named(ui, name):
    return next(t for t in ui.walk() if t.property("objectName") == name)


def wheel(ui, pos, delta):
    ev = QWheelEvent(QPointF(pos), QPointF(ui.w.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QGuiApplication.sendEvent(ui.w, ev)
    ui.spin(4)


def view(ui):
    return ui.main.property("zoom"), ui.main.property("panX"), ui.main.property("panY")


def set_view(ui, z, px=0.0, py=0.0):
    ui.main.setProperty("zoom", float(z))
    ui.main.setProperty("panX", float(px))
    ui.main.setProperty("panY", float(py))
    ui.spin(25)


def canvas_rect(ui):
    c = named(ui, "flowCanvas")
    tl = c.mapToScene(QPointF(0, 0))
    return tl.x(), tl.y(), tl.x() + c.width(), tl.y() + c.height()


def visible_button(ui, text):
    return next(t for t in ui.walk() if t.property("text") == text and t.isVisible())


def leave(ui):
    """Take the pointer off the modules (a hand does this after a drag), so no hover tooltip is left open when the next test reloads."""
    QTest.mouseMove(ui.w, QPoint(780, 870))
    ui.spin(40)


def handle_of(card):
    return next(c for c in card.childItems() if c.property("objectName") == "cardHandle")


def press(ui, pos, handle):
    """Move the pointer onto the module and press, as a real mouse does. If the very first press is taken by a hover tooltip that
    the previous test left open (its module was destroyed while the tooltip showed), press again, as a user would."""
    QTest.keyClick(ui.w, Qt.Key.Key_Escape)
    ui.spin(10)
    QTest.mouseMove(ui.w, pos)
    ui.spin(8)
    for _ in range(3):
        QTest.mousePress(ui.w, Qt.MouseButton.LeftButton, pos=pos)
        ui.spin(3)
        if handle.property("pressed"):
            return
        QTest.mouseRelease(ui.w, Qt.MouseButton.LeftButton, pos=pos)
        ui.spin(25)
    raise AssertionError("the module never received the press")


# ---- wheel ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("where", [(700, 700), (90, 200), (900, 880)])
def test_the_point_under_the_cursor_stays_put_when_zooming(ui, where):
    set_view(ui, 1.0)
    card = ui.cards()["03 MountingHole"]
    before, z0 = ui.center(card), ui.main.property("zoom")
    c = QPoint(*where)
    wheel(ui, c, 120)
    z1, after = ui.main.property("zoom"), ui.center(ui.cards()["03 MountingHole"])
    k = z1 / z0
    want = QPointF(c.x() + (before.x() - c.x()) * k, c.y() + (before.y() - c.y()) * k)
    assert math.hypot(after.x() - want.x(), after.y() - want.y()) < 2.5, "what is under the cursor does not slide"


def test_the_amount_zoomed_follows_the_amount_scrolled(ui):
    c = QPoint(600, 500)
    set_view(ui, 1.0)
    wheel(ui, c, 120)
    assert ui.main.property("zoom") == pytest.approx(1.15, abs=1e-3), "one mouse notch = 15%"
    set_view(ui, 1.0)
    for _ in range(30):
        wheel(ui, c, 12)                                       # a precision touchpad: many tiny steps, three notches in all
    assert ui.main.property("zoom") == pytest.approx(1.15 ** 3, rel=0.01)
    set_view(ui, 1.0)
    wheel(ui, c, 240)
    assert ui.main.property("zoom") == pytest.approx(1.15 ** 2, rel=0.01)
    set_view(ui, 1.0)
    wheel(ui, c, 120 * 40)
    assert ui.main.property("zoom") == pytest.approx(1.15 ** 4, rel=0.01), "one huge event cannot jump straight to the limit"


def test_zooming_in_then_out_returns_to_where_it_started_and_stops_at_the_limits(ui):
    c = QPoint(640, 480)
    set_view(ui, 1.0, 30, 20)
    for _ in range(4):
        wheel(ui, c, 120)
    for _ in range(4):
        wheel(ui, c, -120)
    z, px, py = view(ui)
    assert z == pytest.approx(1.0, abs=1e-6) and px == pytest.approx(30, abs=0.01) and py == pytest.approx(20, abs=0.01)
    for _ in range(40):
        wheel(ui, c, 120)
    top = view(ui)
    assert top[0] == 2.5
    wheel(ui, c, 120)
    assert view(ui) == top, "at the limit nothing drifts"
    for _ in range(80):
        wheel(ui, c, -120)
    assert ui.main.property("zoom") == 0.25
    bottom = view(ui)
    wheel(ui, c, -120)
    assert view(ui) == bottom


def test_zoom_buttons_zoom_about_the_middle_of_the_canvas(ui):
    set_view(ui, 1.0)
    ui.click(ui.center(visible_button(ui, "+")))
    assert ui.main.property("zoom") == pytest.approx(1.2, abs=1e-3)
    ui.click(ui.center(visible_button(ui, MINUS)))
    ui.click(ui.center(visible_button(ui, MINUS)))
    assert ui.main.property("zoom") == pytest.approx(1.0 / 1.2, abs=1e-3)


# ---- moving modules while zoomed -------------------------------------------------------------------------------------
@pytest.mark.parametrize("z,px,py", [(1.0, 0, 0), (2.0, -300, -150), (0.5, 100, 80), (1.5, -100, -50), (0.25, 300, 300)])
def test_a_module_follows_the_pointer_exactly_at_any_zoom(ui, z, px, py):
    set_view(ui, z, px, py)
    card = ui.cards()["03 MountingHole"]
    start = ui.point_in(card, card.width() / 2, 12)
    if not (60 < start.x() < 900 and 170 < start.y() < 840):
        pytest.skip("the module is off the visible canvas at this zoom")
    x0, y0 = card.property("x"), card.property("y")
    press(ui, start, handle_of(card))
    for i in range(1, 13):
        QTest.mouseMove(ui.w, QPoint(start.x() + 6 * i, start.y() + 4 * i))
        ui.spin(3)
        moved_x = (ui.cards()["03 MountingHole"].property("x") - x0) * z
        moved_y = (ui.cards()["03 MountingHole"].property("y") - y0) * z
        assert abs(moved_x - 6 * i) <= 1.5 and abs(moved_y - 4 * i) <= 1.5, \
            f"step {i}: mouse (+{6 * i}, +{4 * i}), card ({moved_x:.1f}, {moved_y:.1f})"
    QTest.mouseRelease(ui.w, Qt.MouseButton.LeftButton, pos=QPoint(start.x() + 72, start.y() + 48))
    ui.spin(10)
    card = ui.cards()["03 MountingHole"]
    assert abs((card.property("x") - x0) * z - 72) <= 1.5 and abs((card.property("y") - y0) * z - 48) <= 1.5
    leave(ui)


def test_a_click_selects_without_moving_and_a_drag_does_not_select(ui):
    set_view(ui, 2.0, -200, -100)
    card = ui.cards()["03 MountingHole"]
    p = ui.point_in(card, card.width() / 2, 12)
    x0, y0 = card.property("x"), card.property("y")
    press(ui, p, handle_of(card))
    QTest.mouseMove(ui.w, p + QPoint(2, 1))                     # a shaky click: inside the dead zone
    ui.spin(3)
    QTest.mouseRelease(ui.w, Qt.MouseButton.LeftButton, pos=p + QPoint(2, 1))
    ui.spin(10)
    card = ui.cards()["03 MountingHole"]
    assert card.property("x") == x0 and card.property("y") == y0, "a jittery click does not nudge the module"
    nid = next(n["id"] for n in ui.be.nodes if n["title"] == "03 MountingHole")
    assert ui.main.property("selectedNode") == nid
    other = ui.cards()["05 SurfaceScratchCheck"]
    q = ui.point_in(other, other.width() / 2, 12)
    ui.drag(q, q + QPoint(30, 0))
    assert ui.main.property("selectedNode") == nid, "dragging a module is not the same as clicking it"
    leave(ui)


def test_a_module_cannot_be_dragged_off_the_top_left_of_the_canvas(ui):
    set_view(ui, 1.0, 0, 0)
    card = ui.cards()["03 MountingHole"]
    p = ui.point_in(card, card.width() / 2, 12)
    ui.drag(p, p + QPoint(-2000, -2000), steps=10)
    card = ui.cards()["03 MountingHole"]
    assert card.property("x") >= 0 and card.property("y") >= 0
    leave(ui)


def test_wires_still_connect_when_zoomed_in(ui):
    set_view(ui, 1.0)
    dst = next(n["id"] for n in ui.be.nodes if n["title"] == "03 MountingHole")
    ui.be.disconnectInput(dst, next(c for c in ui.be.connections if c["to"] == dst)["toPort"])
    ui.spin(60)
    set_view(ui, 1.6, -60, -40)
    cards = ui.cards()
    src, dstc = cards["01 ImageAcquisition"], cards["03 MountingHole"]
    a, b = ui.point_in(src, 180.5, 34.5), ui.point_in(dstc, -0.5, 34.5)
    if not (60 < a.x() < 900 and 170 < a.y() < 880 and 60 < b.x() < 900 and 170 < b.y() < 880):
        pytest.skip("ports off-screen at this zoom")
    ui.drag(a, b)
    assert any(c["to"] == dst for c in ui.be.connections)
    leave(ui)


# ---- Fit -------------------------------------------------------------------------------------------------------------------
def assert_everything_in_view(ui):
    left, top, right, bottom = canvas_rect(ui)
    for title, card in ui.cards().items():
        tl = card.mapToScene(QPointF(0, 0))
        br = card.mapToScene(QPointF(card.width(), card.height()))
        assert tl.x() >= left - 1 and tl.y() >= top - 1 and br.x() <= right + 1 and br.y() <= bottom + 1, \
            f"{title} is cut off after Fit: {tl.x():.0f},{tl.y():.0f} - {br.x():.0f},{br.y():.0f} in canvas {left:.0f},{top:.0f} - {right:.0f},{bottom:.0f}"


@pytest.mark.parametrize("z,px,py", [(1.0, 0, 0), (2.5, -900, -500), (0.25, 400, 300), (1.7, 250, -300)])
def test_fit_brings_every_module_fully_into_view(ui, z, px, py):
    set_view(ui, z, px, py)
    ui.click(ui.center(visible_button(ui, FIT)))
    ui.spin(30)
    assert_everything_in_view(ui)
    assert 0.25 <= ui.main.property("zoom") <= 1.5


def test_fit_still_works_after_modules_are_dragged_far_apart(ui):
    set_view(ui, 1.0, 0, 0)
    card = ui.cards()["07 SendToPLC"]
    p = ui.point_in(card, card.width() / 2, 12)
    ui.drag(p, p + QPoint(-20, 600), steps=12)
    leave(ui)
    ui.click(ui.center(visible_button(ui, FIT)))
    ui.spin(30)
    assert_everything_in_view(ui)


# ---- pinch (touchpad / touch screen) and Ctrl + wheel --------------------------------------------------------------------------
from PyQt6.QtCore import QObject                                  # noqa: E402
from PyQt6.QtGui import QNativeGestureEvent, QPointingDevice     # noqa: E402

NATIVE = Qt.NativeGestureType


def handler(ui, name):
    h = ui.w.findChild(QObject, name)
    assert h is not None, f"{name} is missing"
    return h


def gesture(ui, kind, value, pos):
    """A touchpad gesture event. (The test machine has no touchpad, so it goes through the mouse's own device; the handler is told
    to accept that device for the duration of the test.)"""
    dev = QPointingDevice.primaryPointingDevice()
    p = QPointF(pos)
    ev = QNativeGestureEvent(kind, dev, 2, p, p, QPointF(ui.w.mapToGlobal(pos)), value, QPointF(0, 0))
    QGuiApplication.sendEvent(ui.w, ev)
    ui.spin(4)


def pinch(ui, pos, steps, per_step):
    gesture(ui, NATIVE.BeginNativeGesture, 0.0, pos)
    for _ in range(steps):
        gesture(ui, NATIVE.ZoomNativeGesture, per_step, pos)
    gesture(ui, NATIVE.EndNativeGesture, 0.0, pos)


def test_the_pinch_handlers_exist_and_take_touch_devices_but_not_the_mouse(ui):
    for name in ("canvasPinch", "viewerPinch"):
        h = handler(ui, name)
        devices = h.property("acceptedDevices")
        assert "TouchScreen" in str(devices) and "TouchPad" in str(devices) and "Mouse" not in str(devices), \
            "a mouse must not pinch (it draws regions and pans)"
    set_view(ui, 1.0)
    pinch(ui, QPoint(600, 500), 5, 0.1)                           # the mouse device is refused by default
    assert view(ui) == (1.0, 0.0, 0.0)


def test_a_touchpad_pinch_zooms_about_the_fingers_and_the_view_stays_under_them(ui):
    handler(ui, "canvasPinch").setProperty("acceptedDevices", 7)
    try:
        set_view(ui, 1.0)
        card = ui.cards()["03 MountingHole"]
        before, c = ui.center(card), QPoint(600, 500)
        pinch(ui, c, 5, 0.1)
        z = ui.main.property("zoom")
        assert z == pytest.approx(1.1 ** 5, rel=0.01), "five +10% steps compound"
        after = ui.center(ui.cards()["03 MountingHole"])
        want = QPointF(c.x() + (before.x() - c.x()) * z, c.y() + (before.y() - c.y()) * z)
        assert math.hypot(after.x() - want.x(), after.y() - want.y()) < 3, "what is between the fingers does not slide"
        pinch(ui, c, 5, -0.1 / 1.1)                                # and back out
        assert ui.main.property("zoom") < z
    finally:
        handler(ui, "canvasPinch").setProperty("acceptedDevices", 6)


def test_pinching_respects_the_zoom_limits(ui):
    handler(ui, "canvasPinch").setProperty("acceptedDevices", 7)
    try:
        set_view(ui, 1.0)
        pinch(ui, QPoint(600, 500), 40, 0.3)
        assert ui.main.property("zoom") == 2.5
        pinch(ui, QPoint(600, 500), 80, -0.3)
        assert ui.main.property("zoom") == 0.25
    finally:
        handler(ui, "canvasPinch").setProperty("acceptedDevices", 6)


def test_ctrl_wheel_which_is_how_a_windows_touchpad_reports_a_pinch_zooms_smoothly(ui):
    c = QPoint(600, 500)
    for mods in (Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
        set_view(ui, 1.0)
        for _ in range(8):                                         # eight small pinch increments
            ev = QWheelEvent(QPointF(c), QPointF(ui.w.mapToGlobal(c)), QPoint(0, 0), QPoint(0, 15), Qt.MouseButton.NoButton, mods,
                             Qt.ScrollPhase.NoScrollPhase, False)
            QGuiApplication.sendEvent(ui.w, ev)
            ui.spin(3)
        assert ui.main.property("zoom") == pytest.approx(1.15 ** 1.0, rel=0.01), "8 x 15/120 of a notch = one notch"


def test_pinching_the_image_viewer_zooms_it_and_stops_at_its_limits(ui):
    vp = named(ui, "viewportRect")
    centre = ui.point_in(vp, vp.width() / 2, vp.height() / 2)
    handler(ui, "viewerPinch").setProperty("acceptedDevices", 7)
    try:
        vp.setProperty("viewZoom", 1.0)
        pinch(ui, centre, 5, 0.1)
        assert vp.property("viewZoom") == pytest.approx(1.1 ** 5, rel=0.02)
        pinch(ui, centre, 60, 0.3)
        assert vp.property("viewZoom") == 16
        pinch(ui, centre, 120, -0.3)
        assert vp.property("viewZoom") == 1
    finally:
        handler(ui, "viewerPinch").setProperty("acceptedDevices", 6)
        vp.setProperty("viewZoom", 1.0)
