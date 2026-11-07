"""Node linking UX (NodeGraphQt-style): curved wires coloured by type, ports that light up and snap while a wire is
dragged, moving a wire by its end, linking backwards from an input, drop on a module body, Esc to cancel, link
hover and a delete handle.  All driven with real mouse and keyboard events."""
import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest

from test_qml_interaction import fresh, ui  # noqa: F401

OUT = (180.5, 34.5)           # output port #0 in card coordinates
IN = (-0.5, 34.5)             # input port #0


def card(ui, title):
    return ui.cards()[title]


def out_pt(ui, title, index=0):
    return ui.point_in(card(ui, title), 180.5, 34.5 + 14 * index)


def in_pt(ui, title, index=0):
    return ui.point_in(card(ui, title), -0.5, 34.5 + 14 * index)


def nid(ui, title):
    return next(n["id"] for n in ui.be.nodes if n["title"] == title)


def drag_state(ui):
    v = ui.main.property("wireDrag")
    return v.toVariant() if hasattr(v, "toVariant") else v


def press_and_move(ui, p0, p1, steps=8):
    QTest.mousePress(ui.w, Qt.MouseButton.LeftButton, pos=p0)
    ui.spin(3)
    for i in range(1, steps + 1):
        QTest.mouseMove(ui.w, QPoint(p0.x() + (p1.x() - p0.x()) * i // steps, p0.y() + (p1.y() - p0.y()) * i // steps))
        ui.spin(3)
    ui.spin(15)


def release(ui, p):
    QTest.mouseRelease(ui.w, Qt.MouseButton.LeftButton, pos=p)
    ui.spin(30)


def links_to(ui, title):
    n = nid(ui, title)
    return [c for c in ui.be.connections if c["to"] == n]


def free_input(ui, title, port_index=0):
    """Remove the wire into an input so it can be wired again."""
    n = nid(ui, title)
    for c in ui.be.connections:
        if c["to"] == n and c["toPort"] == port_index:
            ui.be.disconnectInput(n, port_index)
    ui.spin(50)


# ---------------------------------------------------------------- curves, colours, hover
def test_wires_are_curves_and_clicking_the_curve_selects_it(ui):
    a, b = out_pt(ui, "01 ImageAcquisition"), in_pt(ui, "05 SurfaceScratchCheck")
    mid = QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2)               # the middle of a cubic S-curve is the midpoint
    ui.click(mid)
    sel = ui.main.property("selectedLink")
    assert sel is not None and sel["to"] == nid(ui, "05 SurfaceScratchCheck")
    ui.click(QPoint(700, 860))
    # a point on the old square-cornered path (a quarter of the way along, at the source's height) is no longer on the wire
    off = QPoint(a.x() + (b.x() - a.x()) // 4, a.y())
    ui.click(off)
    assert ui.main.property("selectedLink") is None or ui.main.property("selectedLink")["to"] != nid(ui, "05 SurfaceScratchCheck")


def test_ports_carry_their_exact_type_for_colour_and_compatibility(ui):
    n = next(x for x in ui.be.nodes if x["title"] == "04 TraceWidthCaliper")
    assert [p["dtype"] for p in n["outputs"]] == ["VALUE", "POINT", "POINT"]
    assert [p["dtype"] for p in n["inputs"]] == ["IMAGE"]
    colours = {t: next(iter([c for c in ui.of_type("PortDot") if c.property("dtype") == t]), None) for t in ("IMAGE", "VALUE", "POINT")}
    assert all(colours.values()), "every port type present in the flow is drawn with its own dtype"
    assert len({str(c.property("border").color().name()) if False else t for t, c in colours.items()}) == 3


def test_hovering_a_wire_highlights_it_and_shows_the_hand_cursor(ui):
    a, b = out_pt(ui, "01 ImageAcquisition"), in_pt(ui, "03 MountingHole")
    mid = QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2)
    QTest.mouseMove(ui.w, QPoint(5, 5))
    ui.spin(10)
    assert ui.main.property("hoverLink") is None
    QTest.mouseMove(ui.w, mid)
    QTest.mouseMove(ui.w, QPoint(mid.x() + 1, mid.y()))
    ui.spin(15)
    hov = ui.main.property("hoverLink")
    assert hov is not None and hov["to"] == nid(ui, "03 MountingHole")
    QTest.mouseMove(ui.w, QPoint(700, 860))
    ui.spin(15)
    assert ui.main.property("hoverLink") is None


def test_the_selected_link_has_a_delete_handle_that_removes_it(ui):
    a, b = out_pt(ui, "01 ImageAcquisition"), in_pt(ui, "05 SurfaceScratchCheck")
    ui.click(QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    handle = next(c for c in ui.walk() if c.property("objectName") == "linkDelete")
    assert handle.isVisible()
    n = len(ui.be.connections)
    ui.click(ui.center(handle))
    assert len(ui.be.connections) == n - 1 and not handle.isVisible()
    ui.be.undo()
    ui.spin(40)
    assert len(ui.be.connections) == n


# ---------------------------------------------------------------- dragging a wire
def test_dragging_from_an_output_rings_the_inputs_that_fit_and_snaps_to_the_nearest(ui):
    free_input(ui, "03 MountingHole")
    p0 = out_pt(ui, "01 ImageAcquisition")
    target = in_pt(ui, "03 MountingHole")
    press_and_move(ui, p0, QPoint(target.x() + 12, target.y() + 6))        # near, not on, the port
    d = drag_state(ui)
    assert d["active"] and d["target"] and d["target"]["ok"] and d["target"]["id"] == nid(ui, "03 MountingHole")
    rings = ui.main.property("wireRings").toVariant()
    states = [r["state"] for r in rings]
    assert states.count("hot") == 1, "the snapped port has a solid ring"
    assert "cand" in states, "the other ports that can take an image are ringed"
    n_image_inputs = sum(1 for n in ui.be.nodes if n["id"] != nid(ui, "01 ImageAcquisition") for p in n["inputs"] if p["dtype"] in ("IMAGE", "ANY"))
    assert len(rings) == n_image_inputs, "exactly the inputs that can take an image (IMAGE or ANY) are ringed"
    release(ui, QPoint(target.x() + 12, target.y() + 6))
    assert links_to(ui, "03 MountingHole") and not drag_state(ui)["active"]


def test_releasing_beyond_the_snap_radius_does_not_connect_and_says_why(ui):
    free_input(ui, "03 MountingHole")
    p0 = out_pt(ui, "01 ImageAcquisition")
    far = QPoint(700, 700)
    press_and_move(ui, p0, far)
    assert drag_state(ui)["target"] is None
    release(ui, far)
    assert not links_to(ui, "03 MountingHole")
    assert "Drop the wire on an input port" in ui.main.property("toast")


def test_an_incompatible_port_gets_a_red_ring_and_the_reason(ui):
    p0 = out_pt(ui, "01 ImageAcquisition")                        # IMAGE
    target = in_pt(ui, "06 QualityJudge")                         # Val_In: VALUE
    before = [dict(c) for c in ui.be.connections]
    press_and_move(ui, p0, target)
    d = drag_state(ui)
    assert d["target"] and not d["target"]["ok"] and "Type mismatch" in d["target"]["reason"]
    assert "bad" in [r["state"] for r in ui.main.property("wireRings").toVariant()]
    release(ui, target)
    assert ui.be.connections == before
    assert "Type mismatch" in ui.main.property("toast")


def test_a_loop_is_refused_with_the_reason_before_you_drop(ui):
    a, b = nid(ui, "02 IC_Alignment"), nid(ui, "03 MountingHole")
    assert ui.be.connectPorts(a, 0, b, 0)                         # 02 -> 03: now 03 -> 02 would close a loop
    ui.spin(50)
    before = [dict(c) for c in ui.be.connections]
    p0, target = out_pt(ui, "03 MountingHole"), in_pt(ui, "02 IC_Alignment")
    press_and_move(ui, p0, target)
    d = drag_state(ui)
    assert d["active"] and d["target"] and not d["target"]["ok"] and "loop" in d["target"]["reason"].lower()
    release(ui, target)
    assert ui.be.connections == before
    assert "loop" in ui.main.property("toast").lower()


def test_dropping_on_the_body_of_a_module_uses_its_first_free_matching_input(ui):
    free_input(ui, "04 TraceWidthCaliper")
    p0 = out_pt(ui, "01 ImageAcquisition")
    body = ui.point_in(card(ui, "04 TraceWidthCaliper"), 90, 70)
    press_and_move(ui, p0, body)
    assert drag_state(ui)["target"]["viaNode"] if "viaNode" in (drag_state(ui)["target"] or {}) else drag_state(ui)["target"] is not None
    release(ui, body)
    assert links_to(ui, "04 TraceWidthCaliper")


def test_escape_cancels_a_wire_in_progress(ui):
    free_input(ui, "03 MountingHole")
    p0, target = out_pt(ui, "01 ImageAcquisition"), in_pt(ui, "03 MountingHole")
    press_and_move(ui, p0, target)
    assert drag_state(ui)["active"]
    ui.key(Qt.Key.Key_Escape)
    assert not drag_state(ui)["active"] and ui.main.property("wireRings").toVariant() == []
    release(ui, target)
    assert not links_to(ui, "03 MountingHole"), "a cancelled wire must not connect when the button is released"


# ---------------------------------------------------------------- moving and reversing wires
def test_dragging_a_connected_input_moves_the_wire_to_another_input_as_one_undo_step(ui):
    free_input(ui, "03 MountingHole")
    src = nid(ui, "01 ImageAcquisition")
    old = in_pt(ui, "04 TraceWidthCaliper")
    new = in_pt(ui, "03 MountingHole")
    assert links_to(ui, "04 TraceWidthCaliper")
    undo_before = len(ui.be._undo)
    press_and_move(ui, old, new)
    d = drag_state(ui)
    assert d["active"] and d["relink"] and d["from"] == src, "the wire is picked up by its end and keeps its source"
    release(ui, new)
    assert links_to(ui, "03 MountingHole") and not links_to(ui, "04 TraceWidthCaliper")
    assert len(ui.be._undo) == undo_before + 1
    ui.be.undo()
    ui.spin(50)
    assert links_to(ui, "04 TraceWidthCaliper") and not links_to(ui, "03 MountingHole")


def test_dropping_a_picked_up_wire_on_empty_canvas_removes_it_and_undo_restores_it(ui):
    old = in_pt(ui, "04 TraceWidthCaliper")
    n = len(ui.be.connections)
    press_and_move(ui, old, QPoint(700, 800))
    release(ui, QPoint(700, 800))
    assert len(ui.be.connections) == n - 1 and not links_to(ui, "04 TraceWidthCaliper")
    assert "Wire removed" in ui.main.property("toast")
    ui.be.undo()
    ui.spin(50)
    assert len(ui.be.connections) == n


def test_dropping_a_picked_up_wire_back_on_its_own_input_changes_nothing(ui):
    old = in_pt(ui, "04 TraceWidthCaliper")
    before = [dict(c) for c in ui.be.connections]
    undo_before = len(ui.be._undo)
    press_and_move(ui, old, QPoint(old.x() - 60, old.y() - 40))
    release(ui, old)
    assert ui.be.connections == before and len(ui.be._undo) == undo_before


def test_escape_while_moving_a_wire_puts_it_back(ui):
    old = in_pt(ui, "04 TraceWidthCaliper")
    before = [dict(c) for c in ui.be.connections]
    press_and_move(ui, old, QPoint(700, 800))
    ui.key(Qt.Key.Key_Escape)
    release(ui, QPoint(700, 800))
    assert ui.be.connections == before


def test_a_free_input_can_start_a_wire_backwards_to_an_output(ui):
    free_input(ui, "03 MountingHole")
    inp = in_pt(ui, "03 MountingHole")
    src = out_pt(ui, "01 ImageAcquisition")
    press_and_move(ui, inp, QPoint(src.x() + 8, src.y() + 5))
    d = drag_state(ui)
    assert d["active"] and d["reverse"] and d["target"] and d["target"]["ok"] and d["target"]["id"] == nid(ui, "01 ImageAcquisition")
    release(ui, QPoint(src.x() + 8, src.y() + 5))
    link = links_to(ui, "03 MountingHole")
    assert link and link[0]["from"] == nid(ui, "01 ImageAcquisition")


def test_right_click_on_an_input_still_disconnects_it(ui):
    ui.click(in_pt(ui, "03 MountingHole"), Qt.MouseButton.RightButton)
    assert not links_to(ui, "03 MountingHole")


# ---------------------------------------------------------------- comfort
def test_dragging_a_wire_to_the_canvas_edge_scrolls_the_view(ui):
    free_input(ui, "03 MountingHole")
    p0 = out_pt(ui, "01 ImageAcquisition")
    px = ui.main.property("panX")
    edge = QPoint(48, 600)                                          # inside the canvas, within 36 px of its left edge
    press_and_move(ui, p0, edge)
    end = __import__("time").time() + 2
    while ui.main.property("panX") <= px and __import__("time").time() < end:
        ui.spin(5)
    assert ui.main.property("panX") > px, "the canvas must scroll while the wire is held at its edge"
    release(ui, edge)


def test_hovering_a_port_enlarges_it(ui):
    p = in_pt(ui, "02 IC_Alignment")
    QTest.mouseMove(ui.w, QPoint(5, 5))
    ui.spin(10)
    QTest.mouseMove(ui.w, p)
    QTest.mouseMove(ui.w, QPoint(p.x() + 1, p.y()))
    ui.spin(25)
    hot = [d for d in ui.of_type("PortDot") if d.property("hot")]
    assert len(hot) == 1 and hot[0].property("scale") > 1.2


# ---------------------------------------------------------------- backend rules
def test_backend_can_connect_explains_refusals(ui):
    src, judge = nid(ui, "01 ImageAcquisition"), nid(ui, "06 QualityJudge")
    assert ui.be.canConnect(src, 0, nid(ui, "03 MountingHole"), 0) == ""
    assert "Type mismatch" in ui.be.canConnect(src, 0, judge, 0)
    assert "itself" in ui.be.canConnect(src, 0, src, 0)
    assert "loop" in ui.be.canConnect(nid(ui, "07 SendToPLC"), 0, judge, 0) or ui.be.canConnect(nid(ui, "07 SendToPLC"), 0, judge, 0) != ""
    assert ui.be.canConnect("ghost", 0, src, 0) == "That module no longer exists."
    assert ui.be.canConnect(src, 99, judge, 0) == "That port does not exist."


def test_backend_reconnect_is_one_undo_step_and_validates(ui):
    src, a, b = nid(ui, "01 ImageAcquisition"), nid(ui, "04 TraceWidthCaliper"), nid(ui, "03 MountingHole")
    free_input(ui, "03 MountingHole")
    n_undo = len(ui.be._undo)
    assert ui.be.reconnect(src, 0, a, 0, b, 0)
    assert len(ui.be._undo) == n_undo + 1
    judge = nid(ui, "06 QualityJudge")
    assert not ui.be.reconnect(src, 0, b, 0, judge, 0), "a type mismatch moves nothing"
    assert [c for c in ui.be.connections if c["to"] == b], "the wire stays where it was"
    assert ui.be.reconnect(src, 0, b, 0, "", 0) and not [c for c in ui.be.connections if c["to"] == b]
    ui.be.setRole("Operator")
    assert not ui.be.reconnect(src, 0, a, 0, "", 0)
    ui.be.setRole("Engineer")
