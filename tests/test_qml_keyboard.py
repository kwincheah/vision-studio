"""Keyboard-only operation of the flow canvas (no mouse after focusing it)."""
import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QPoint, Qt

from test_qml_interaction import fresh, ui  # noqa: F401

SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT_SHIFT = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier
CTRL = Qt.KeyboardModifier.ControlModifier


def nid(ui, title):
    return next(n["id"] for n in ui.be.nodes if n["title"] == title)


def focus_canvas(ui):
    ui.click(QPoint(700, 860))                                 # an empty spot on the canvas
    assert ui.main.property("selectedLink") is None


def wire_active(ui):
    return bool(ui.main.property("wireDrag").toVariant()["active"])


def selected_title(ui):
    sel = ui.main.property("selectedNode")
    return next(n["title"] for n in ui.be.nodes if n["id"] == sel)


def select(ui, title):
    ui.main.setProperty("selectedNode", nid(ui, title))
    ui.spin(10)


def test_arrow_keys_walk_the_flow_spatially(ui):
    focus_canvas(ui)
    select(ui, "01 ImageAcquisition")
    ui.key(Qt.Key.Key_Right)
    assert selected_title(ui) == "02 IC_Alignment"
    ui.key(Qt.Key.Key_Down)
    assert selected_title(ui) == "03 MountingHole"
    ui.key(Qt.Key.Key_Down)
    assert selected_title(ui) == "04 TraceWidthCaliper"
    ui.key(Qt.Key.Key_Up)
    assert selected_title(ui) == "03 MountingHole"
    ui.key(Qt.Key.Key_Left)
    assert selected_title(ui) == "01 ImageAcquisition"
    ui.key(Qt.Key.Key_Left)                                    # nothing further left: stays put
    assert selected_title(ui) == "01 ImageAcquisition"


def test_shift_arrows_move_the_module_in_one_undo_step(ui):
    focus_canvas(ui)
    select(ui, "03 MountingHole")
    card = ui.cards()["03 MountingHole"]
    x0, y0 = card.property("x"), card.property("y")
    for _ in range(3):
        ui.key(Qt.Key.Key_Right, SHIFT)
    ui.key(Qt.Key.Key_Down, SHIFT)
    ui.key(Qt.Key.Key_Down, ALT_SHIFT)
    card = ui.cards()["03 MountingHole"]
    assert card.property("x") == x0 + 30 and card.property("y") == y0 + 11
    pos = ui.be._pipeline.node_positions[nid(ui, "03 MountingHole")]
    assert pos == [x0 + 30, y0 + 11], "the engine was not told about the keyboard move"
    ui.be.undo()
    ui.spin(40)
    card = ui.cards()["03 MountingHole"]
    assert (card.property("x"), card.property("y")) == (x0, y0), "a burst of key presses must undo as one step"


def test_wires_follow_a_keyboard_move(ui):
    focus_canvas(ui)
    select(ui, "03 MountingHole")
    for _ in range(4):
        ui.key(Qt.Key.Key_Right, SHIFT)
    ui.spin(20)
    card = ui.cards()["03 MountingHole"]
    inp = (card.property("x") - 0.5, card.property("y") + 34.5)
    assert any(abs(b.x() - inp[0]) < 1 and abs(b.y() - inp[1]) < 1 for _a, b in ui.wires())


def test_enter_opens_configuration_and_escape_closes_it(ui):
    focus_canvas(ui)
    select(ui, "02 IC_Alignment")
    ui.key(Qt.Key.Key_Return)
    assert ui.dialog == "moduleConfig"
    ui.key(Qt.Key.Key_Escape)
    assert ui.dialog == ""


def test_k_cycles_links_and_delete_removes_the_selected_one(ui):
    focus_canvas(ui)
    n = len(ui.be.connections)
    ui.key(Qt.Key.Key_K)
    first = ui.main.property("selectedLink")
    assert first is not None
    ui.key(Qt.Key.Key_K)
    assert ui.main.property("selectedLink") != first
    ui.key(Qt.Key.Key_K, SHIFT)
    assert ui.main.property("selectedLink") == first
    ui.key(Qt.Key.Key_Delete)
    assert len(ui.be.connections) == n - 1
    ui.be.undo()
    ui.spin(30)
    assert len(ui.be.connections) == n
    ui.key(Qt.Key.Key_K)
    ui.key(Qt.Key.Key_Escape)
    assert ui.main.property("selectedLink") is None


def test_keyboard_wiring_connects_and_escape_cancels(ui):
    focus_canvas(ui)
    dst = nid(ui, "03 MountingHole")
    link = next(c for c in ui.be.connections if c["to"] == dst)
    ui.be.disconnectInput(dst, link["toPort"])
    ui.spin(50)
    assert not any(c["to"] == dst for c in ui.be.connections)
    select(ui, "01 ImageAcquisition")
    ui.key(Qt.Key.Key_L)
    assert wire_active(ui), "no visible wire while linking from the keyboard"
    ui.key(Qt.Key.Key_Right)                                   # 02
    ui.key(Qt.Key.Key_Down)                                    # 03
    assert selected_title(ui) == "03 MountingHole"
    ui.key(Qt.Key.Key_1)
    ui.key(Qt.Key.Key_Return)
    assert any(c["to"] == dst and c["from"] == link["from"] for c in ui.be.connections)
    assert not wire_active(ui)
    # cancel path
    n = len(ui.be.connections)
    select(ui, "01 ImageAcquisition")
    ui.key(Qt.Key.Key_L)
    ui.key(Qt.Key.Key_Right)
    ui.key(Qt.Key.Key_Escape)
    ui.key(Qt.Key.Key_Return)                                  # no longer in link mode: opens the dialog instead
    assert len(ui.be.connections) == n and not wire_active(ui)
    ui.key(Qt.Key.Key_Escape)


def test_keyboard_wiring_rejects_a_target_with_no_choice(ui):
    focus_canvas(ui)
    select(ui, "01 ImageAcquisition")
    n = len(ui.be.connections)
    ui.key(Qt.Key.Key_L)
    ui.key(Qt.Key.Key_Return)                                  # Enter before picking a target does nothing
    assert len(ui.be.connections) == n
    assert wire_active(ui)
    ui.key(Qt.Key.Key_Escape)
    assert not wire_active(ui)


def test_zoom_pan_and_fit_from_the_keyboard(ui):
    focus_canvas(ui)
    z = ui.main.property("zoom")
    ui.key(Qt.Key.Key_Plus)
    assert ui.main.property("zoom") > z
    ui.key(Qt.Key.Key_Minus)
    ui.key(Qt.Key.Key_Minus)
    assert ui.main.property("zoom") < z
    px = ui.main.property("panX")
    ui.key(Qt.Key.Key_Left, CTRL)
    assert ui.main.property("panX") == px + 60
    ui.key(Qt.Key.Key_Home)
    assert 0.25 <= ui.main.property("zoom") <= 1.5


def test_selection_scrolls_into_view(ui):
    focus_canvas(ui)
    select(ui, "01 ImageAcquisition")
    ui.main.setProperty("panX", -3000.0)                       # the modules are now far off screen
    ui.key(Qt.Key.Key_Right)                                   # selects 02 and scrolls to it
    card = ui.cards()["02 IC_Alignment"]
    assert ui.on_canvas(card), "the newly selected module was not scrolled into view"


def test_canvas_is_in_the_tab_order_and_shows_a_focus_ring(ui):
    focus_canvas(ui)
    canvas = next(c for c in ui.of_type("QQuickRectangle") if c.property("activeFocusOnTab") and c.property("activeFocus"))
    assert not ui.warnings
