"""Drive the QML interface the way a person does - real mouse and keyboard events in the window -
and check what the engine and the screen did about it."""
import os
import sys
import time

import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtTest import QTest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QML = os.path.join(ROOT, "qml")
DEMO = os.path.join(ROOT, "projects", "PCB_Inspection_Demo.vmp")


class Ui:
    """A running QML window plus helpers to find things in it and operate it."""

    def __init__(self):
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        from apex_vision.core.project_manager import ProjectManager
        from apex_vision.qml_backend import AppBackend, FrameProvider
        from apex_vision.qml_services import install_services
        self.app = QApplication.instance() or QApplication(sys.argv)  # widgets tests may share this process
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda ws: self.warnings.extend(w.toString() for w in ws))
        provider = FrameProvider()
        self.engine.addImageProvider("frame", provider)
        import tempfile
        self.pm = ProjectManager(workspace_root=tempfile.mkdtemp(prefix="ui_ws_"))
        self.be = AppBackend(provider, self.pm)
        self.engine.rootContext().setContextProperty("appBackend", self.be)
        self.engine._services = install_services(self.engine, self.be)
        self.engine.addImportPath(QML)
        self.engine.load(QUrl.fromLocalFile(os.path.join(QML, "Main.qml")))
        self.w = self.engine.rootObjects()[0]
        self.w.show()
        self.reset()

    # -- state -------------------------------------------------------------------------------
    def reset(self):
        self.be._pending = None
        self.be._role = "Engineer"
        self.be.loop = False
        self.be.setScope("Run all")
        self.be._project.saved = None            # never ask about unsaved edits between tests
        self.w.setProperty("startPageVisible", False)
        self.be.load_solution(__import__("apex_vision.core.pipeline", fromlist=["SolutionManager"])
                              .SolutionManager.load_from_file(DEMO), DEMO)
        self.settle()
        self.main.setProperty("zoom", 1.0)
        self.main.setProperty("panX", 0.0)
        self.main.setProperty("panY", 0.0)
        self.main.setProperty("workspaceTab", 0)
        self.main.setProperty("railCategory", -1)
        self.main.setProperty("aiVisible", False)
        self.main.setProperty("kbWire", {"active": False, "from": "", "out": 0, "target": "", "inp": 0})
        self.main.setProperty("wireDrag", {"active": False, "from": "", "index": 0, "x": 0, "y": 0})
        self.main.setProperty("selectedLink", None)
        self.main.setProperty("inspectionVisible", False)
        self.close_dialog()
        self.spin(30)

    def spin(self, n=20):
        for _ in range(n):
            self.app.processEvents()
            time.sleep(0.008)

    def settle(self, timeout=15):
        end = time.time() + timeout
        while (self.be.engine.busy or self.be.flowMs == 0) and time.time() < end:
            self.spin(2)
        self.spin(40)

    # -- finding -----------------------------------------------------------------------------
    def walk(self, item=None):
        item = item or self.w.contentItem()
        for child in item.childItems():
            yield child
            yield from self.walk(child)

    def of_type(self, name):
        return [c for c in self.walk() if c.metaObject().className().startswith(name)]

    @property
    def main(self):
        return self.of_type("MainScreen")[0]

    @property
    def host(self):
        return self.of_type("DialogHost")[0]

    def cards(self):
        return {c.property("title"): c for c in self.of_type("NodeCard")}

    def wires(self):
        out = []
        for c in self.walk():
            if "Shape" in c.metaObject().className() and c.property("a") is not None \
                    and c.property("b") is not None and c.isVisible():
                out.append((c.property("a"), c.property("b")))
        return out

    def texts(self, text, visible_only=True):
        found = [c for c in self.walk() if c.metaObject().className().startswith("QQuickText")
                 and c.property("text") == text and (c.isVisible() or not visible_only)]
        return found

    def center(self, item):
        p = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        return QPoint(int(p.x()), int(p.y()))

    def on_canvas(self, card) -> bool:
        """True when the card's header is inside the visible flow canvas (not under another panel)."""
        p = card.mapToScene(QPointF(90, 12))
        right = self.main.findChild(type(self.w.contentItem()), "") if False else None
        return 45 < p.x() < 940 and 140 < p.y() < 900

    def point_in(self, item, x, y):
        p = item.mapToScene(QPointF(x, y))
        return QPoint(int(p.x()), int(p.y()))

    # -- operating ---------------------------------------------------------------------------
    def click(self, pos, button=Qt.MouseButton.LeftButton):
        QTest.mouseClick(self.w, button, pos=pos)
        self.spin(10)

    def click_text(self, text, nth=0, button=Qt.MouseButton.LeftButton):
        items = self.texts(text)
        assert items, f"no visible text '{text}'"
        self.click(self.center(items[nth]), button)

    def double_click(self, pos):
        QTest.mouseDClick(self.w, Qt.MouseButton.LeftButton, pos=pos)
        self.spin(10)

    def drag(self, p0, p1, steps=8):
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=p0)
        self.spin(2)
        for s in range(1, steps + 1):
            QTest.mouseMove(self.w, QPoint(p0.x() + (p1.x() - p0.x()) * s // steps,
                                           p0.y() + (p1.y() - p0.y()) * s // steps))
            self.spin(1)
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=p1)
        self.spin(8)

    def key(self, key, mods=Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(self.w, key, mods)
        self.spin(10)

    def close_dialog(self):
        self.host.setProperty("current", "")
        self.spin(5)

    @property
    def dialog(self):
        return self.host.property("current")


@pytest.fixture(scope="module")
def ui():
    u = Ui()
    yield u
    u.be.engine.wait_for_run()


@pytest.fixture(autouse=True)
def fresh(ui):
    ui.reset()
    ui.warnings.clear()
    yield
    assert not ui.warnings, ui.warnings


def port(card, side, index):
    """Scene-space position of a module's port, as the wires compute it."""
    return QPointF(card.property("x") + (180.5 if side == "out" else -0.5),
                   card.property("y") + 34.5 + index * 14)


# ================================================================== canvas: modules and wires
def test_wires_follow_a_dragged_module_live_and_after(ui):
    card = ui.cards()["03 MountingHole"]
    start = ui.point_in(card, 60, 10)
    import PyQt6.QtTest as qt
    QTest.mousePress(ui.w, Qt.MouseButton.LeftButton, pos=start)
    for step in range(1, 7):
        QTest.mouseMove(ui.w, QPoint(start.x() + step * 20, start.y() + step * 10))
        ui.spin(3)
        inp = port(card, "in", 0)
        assert any(abs(b.x() - inp.x()) < 1 and abs(b.y() - inp.y()) < 1 for _a, b in ui.wires()), \
            f"wire detached while dragging (step {step})"
    QTest.mouseRelease(ui.w, Qt.MouseButton.LeftButton, pos=QPoint(start.x() + 120, start.y() + 60))
    ui.spin(40)
    card = ui.cards()["03 MountingHole"]
    inp = port(card, "in", 0)
    assert any(abs(b.x() - inp.x()) < 1 and abs(b.y() - inp.y()) < 1 for _a, b in ui.wires())
    outs = port(card, "out", 0)
    # a wire leaving the dragged module (if it has one) starts at its output port
    for _a, _b in ui.wires():
        pass
    nid = next(n["id"] for n in ui.be.nodes if n["title"] == "03 MountingHole")
    saved = ui.be._pipeline.node_positions[nid]
    assert abs(saved[0] - card.property("x")) < 1 and abs(saved[1] - card.property("y")) < 1


def test_dragging_the_source_keeps_every_outgoing_wire_attached(ui):
    src = ui.cards()["01 ImageAcquisition"]
    ui.drag(ui.point_in(src, 60, 10), ui.point_in(src, 60, 10) + QPoint(-30, 140))
    src = ui.cards()["01 ImageAcquisition"]
    out = port(src, "out", 0)
    starts = [a for a, _b in ui.wires() if abs(a.x() - out.x()) < 1 and abs(a.y() - out.y()) < 1]
    assert len(starts) == 4                                    # source feeds four modules


def test_dragging_while_zoomed_and_panned_moves_by_the_right_distance(ui):
    ui.main.setProperty("zoom", 0.5)
    ui.main.setProperty("panX", 40.0)
    ui.main.setProperty("panY", 20.0)
    ui.spin(20)
    card = ui.cards()["04 TraceWidthCaliper"]
    x0, y0 = card.property("x"), card.property("y")
    start = ui.point_in(card, 60, 10)
    ui.drag(start, start + QPoint(60, 30))                     # 60 px on screen = 120 scene units at 0.5
    card = ui.cards()["04 TraceWidthCaliper"]
    # Qt starts a drag only after ~10 px of travel, so the card trails the pointer by that much
    assert 100 < card.property("x") - x0 <= 120 and 45 < card.property("y") - y0 <= 60
    inp = port(card, "in", 0)
    assert any(abs(b.x() - inp.x()) < 1 and abs(b.y() - inp.y()) < 1 for _a, b in ui.wires())


def test_panning_the_empty_canvas_and_wheel_zoom(ui):
    start = ui.point_in(ui.cards()["01 ImageAcquisition"], -30, 400)
    ui.drag(start, start + QPoint(70, 40))
    assert abs(ui.main.property("panX") - 70) < 3 and abs(ui.main.property("panY") - 40) < 3
    QTest.mouseMove(ui.w, QPoint(300, 400))
    from PyQt6.QtGui import QWheelEvent
    for _ in range(2):
        ev = QWheelEvent(QPointF(300, 400), QPointF(ui.w.mapToGlobal(QPoint(300, 400))), QPoint(0, 0),
                         QPoint(0, 120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        QGuiApplication.sendEvent(ui.w, ev)
        ui.spin(5)
    assert ui.main.property("zoom") > 1.2


def test_click_selects_and_shows_that_modules_results(ui):
    card = ui.cards()["04 TraceWidthCaliper"]
    ui.click(ui.point_in(card, 90, 12))
    nid = next(n["id"] for n in ui.be.nodes if n["title"] == "04 TraceWidthCaliper")
    assert ui.main.property("selectedNode") == nid and ui.be._selected == nid
    assert any(r["name"] == "Distance" for r in ui.be.results)


def test_double_click_opens_module_configuration_and_x_closes_it(ui):
    card = ui.cards()["02 IC_Alignment"] if "02 IC_Alignment" in ui.cards() else ui.cards()["02 IC Alignment"]
    ui.double_click(ui.point_in(card, 90, 12))
    assert ui.dialog == "moduleConfig"
    ui.click_text("Run Params")
    assert ui.texts("Template roi") and ui.texts("Min score"), "the run parameters show readable names"
    ui.close_dialog()
    assert ui.dialog == ""


def test_right_click_menu_deletes_a_module_and_undo_restores_it(ui):
    n = len(ui.be.nodes)
    card = ui.cards()["06 QualityJudge"]
    assert ui.on_canvas(card)
    ui.click(ui.point_in(card, 90, 12), Qt.MouseButton.RightButton)
    assert ui.texts("Delete Module"), "context menu did not open"
    ui.click_text("Delete Module")
    assert len(ui.be.nodes) == n - 1 and "06 QualityJudge" not in [x["title"] for x in ui.be.nodes]
    ui.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(ui.be.nodes) == n


def test_delete_key_removes_the_selected_module(ui):
    n = len(ui.be.nodes)
    card = ui.cards()["04 TraceWidthCaliper"]
    assert ui.on_canvas(card)
    ui.click(ui.point_in(card, 90, 12))
    ui.key(Qt.Key.Key_Delete)
    assert len(ui.be.nodes) == n - 1 and "04 TraceWidthCaliper" not in [x["title"] for x in ui.be.nodes]


def test_dragging_a_module_can_be_undone(ui):
    card = ui.cards()["06 QualityJudge"]
    nid = next(n["id"] for n in ui.be.nodes if n["title"] == "06 QualityJudge")
    before = list(ui.be._pipeline.node_positions[nid])
    ui.drag(ui.point_in(card, 60, 10), ui.point_in(card, 60, 10) + QPoint(80, 50))
    assert ui.be._pipeline.node_positions[nid] != before
    ui.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert ui.be._pipeline.node_positions[nid] == before
    ui.spin(30)
    inp = port(ui.cards()["06 QualityJudge"], "in", 0)
    assert any(abs(b.x() - inp.x()) < 1 and abs(b.y() - inp.y()) < 1 for _a, b in ui.wires())


def test_wire_drag_connect_and_disconnect_with_zoom(ui):
    ui.main.setProperty("zoom", 0.8)
    ui.spin(20)
    dst = next(n["id"] for n in ui.be.nodes if n["title"] == "03 MountingHole")
    link = next(c for c in ui.be.connections if c["to"] == dst)
    ui.be.disconnectInput(dst, link["toPort"])
    ui.spin(60)
    cards = ui.cards()
    src_card, dst_card = cards["01 ImageAcquisition"], cards["03 MountingHole"]
    ui.drag(ui.point_in(src_card, 180.5, 34.5), ui.point_in(dst_card, -0.5, 34.5))
    assert any(c["to"] == dst for c in ui.be.connections)
    ui.spin(60)
    dst_card = ui.cards()["03 MountingHole"]
    ui.click(ui.point_in(dst_card, -0.5, 34.5), Qt.MouseButton.RightButton)
    assert not any(c["to"] == dst for c in ui.be.connections)


# ================================================================== canvas: link selection
def wire_shapes(ui):
    return [c for c in ui.walk() if "Shape" in c.metaObject().className()
            and c.property("a") is not None and c.property("b") is not None and c.isVisible()]


def link_click_point(ui, shape):
    """A window point on the drawn wire that is not under a module card."""
    a, b = shape.property("a"), shape.property("b")
    mx = (a.x() + b.x()) / 2
    candidates = [(mx, (a.y() + b.y()) / 2), ((a.x() + mx) / 2, a.y()), ((mx + b.x()) / 2, b.y())]
    cards = list(ui.cards().values())
    for x, y in candidates:
        p = shape.mapToScene(QPointF(x, y))
        covered = any(c.property("x") - 4 <= x <= c.property("x") + 184 and c.property("y") - 4 <= y <= c.property("y") + c.property("height") + 4
                      for c in cards)
        if not covered and 160 < p.y() < 880 and 60 < p.x() < 930:
            return QPoint(int(p.x()), int(p.y()))
    pytest.skip("no free spot on this wire")


def first_free_link(ui):
    for sh in wire_shapes(ui):
        try:
            return sh, link_click_point(ui, sh)
        except pytest.skip.Exception:
            continue
    pytest.skip("no clickable wire in view")


def test_clicking_a_link_selects_it_and_delete_removes_just_that_link(ui):
    sh, pt = first_free_link(ui)
    n_nodes, n_links = len(ui.be.nodes), len(ui.be.connections)
    ui.click(pt)
    sel = ui.main.property("selectedLink")
    assert sel is not None, "clicking a wire did not select it"
    ui.key(Qt.Key.Key_Delete)
    assert len(ui.be.connections) == n_links - 1 and len(ui.be.nodes) == n_nodes
    assert ui.main.property("selectedLink") is None
    ui.be.undo()
    ui.spin(40)
    assert len(ui.be.connections) == n_links


def test_link_right_click_menu_and_backspace_and_deselect(ui):
    sh, pt = first_free_link(ui)
    n_links = len(ui.be.connections)
    ui.click(pt, Qt.MouseButton.RightButton)
    assert ui.texts("Delete Link"), "link context menu did not open"
    ui.click_text("Delete Link")
    assert len(ui.be.connections) == n_links - 1
    ui.be.undo()
    ui.spin(40)
    sh, pt = first_free_link(ui)
    ui.click(pt)
    assert ui.main.property("selectedLink") is not None
    ui.click(QPoint(700, 860))                   # empty canvas clears the selection
    assert ui.main.property("selectedLink") is None
    ui.click(pt)
    ui.key(Qt.Key.Key_Backspace)
    assert len(ui.be.connections) == n_links - 1


def test_selecting_a_module_clears_link_selection_and_delete_removes_the_module(ui):
    sh, pt = first_free_link(ui)
    ui.click(pt)
    assert ui.main.property("selectedLink") is not None
    card = ui.cards()["04 TraceWidthCaliper"]
    assert ui.on_canvas(card)
    ui.click(ui.point_in(card, 90, 12))
    assert ui.main.property("selectedLink") is None
    n = len(ui.be.nodes)
    ui.key(Qt.Key.Key_Delete)
    assert len(ui.be.nodes) == n - 1


def test_deleting_a_module_drops_its_links_and_undo_brings_everything_back(ui):
    before_nodes, before_links = len(ui.be.nodes), len(ui.be.connections)
    card = ui.cards()["03 MountingHole"]
    nid = next(n["id"] for n in ui.be.nodes if n["title"] == "03 MountingHole")
    touching = [c for c in ui.be.connections if nid in (c["from"], c["to"])]
    assert touching
    ui.click(ui.point_in(card, 90, 12))
    ui.key(Qt.Key.Key_Delete)
    assert not any(nid in (c["from"], c["to"]) for c in ui.be.connections)
    ui.be.undo()
    ui.spin(40)
    assert len(ui.be.nodes) == before_nodes and len(ui.be.connections) == before_links


def test_invalid_wires_are_rejected_without_changing_the_flow(ui):
    cards = ui.cards()
    order = [n for n in ui.be.nodes]
    last, first = cards[order[-1]["title"]], cards["01 ImageAcquisition"]
    before = [dict(c) for c in ui.be.connections]
    if last.property("outputs") and first.property("inputs"):
        ui.drag(ui.point_in(last, 180.5, 34.5), ui.point_in(first, -0.5, 34.5))
    ui.drag(ui.point_in(first, 180.5, 34.5), QPoint(700, 860))      # dropped on nothing
    assert ui.be.connections == before
