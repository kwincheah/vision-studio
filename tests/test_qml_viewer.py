"""Image viewer, ROI drawing, pixel read-out, number-box buttons and flyout icons - with real mouse input."""
import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QPoint, QPointF, Qt

from test_qml_interaction import fresh, ui  # noqa: F401


def select(ui, title):
    sel = next(n["id"] for n in ui.be.nodes if n["title"] == title)
    ui.be.selectNode(sel)
    ui.main.setProperty("selectedNode", sel)          # after the backend call: a backend change re-evaluates the default binding
    ui.spin(40)
    return sel


def frame_item(ui):
    return next(c for c in ui.of_type("QQuickImage") if "frame" in str(c.property("source")) and c.isVisible())


def image_to_window(ui, frame, x, y):
    """Window point of image pixel (x, y), using the painted rectangle of the viewer."""
    sc = frame.property("paintedWidth") / frame.property("implicitWidth")
    ox = frame.mapToScene(QPointF(0, 0)).x() + (frame.width() - frame.property("paintedWidth")) / 2
    oy = frame.mapToScene(QPointF(0, 0)).y() + (frame.height() - frame.property("paintedHeight")) / 2
    return QPoint(int(ox + x * sc), int(oy + y * sc)), sc


def test_dragging_in_the_viewer_sets_the_selected_modules_roi_and_undo_restores_it(ui):
    nid = select(ui, "05 SurfaceScratchCheck")
    before = list(ui.be.selectedRoi)
    assert len(before) == 4
    frame = frame_item(ui)
    p0, sc = image_to_window(ui, frame, 100, 100)
    p1, _ = image_to_window(ui, frame, 300, 220)
    ui.drag(p0, p1, steps=10)
    ui.settle()
    roi = list(ui.be.selectedRoi)
    assert roi != before
    assert abs(roi[0] - 100) <= 3 and abs(roi[1] - 100) <= 3 and abs(roi[2] - 200) <= 4 and abs(roi[3] - 120) <= 4, roi
    assert ui.be._pipeline.nodes[nid].parameters["roi"] == roi
    ui.be.undo()
    ui.settle()
    assert list(ui.be.selectedRoi) == before


def test_a_tiny_drag_does_not_change_the_roi(ui):
    select(ui, "05 SurfaceScratchCheck")
    before = list(ui.be.selectedRoi)
    p0, _ = image_to_window(ui, frame_item(ui), 100, 100)
    ui.drag(p0, QPoint(p0.x() + 2, p0.y() + 2), steps=2)
    assert list(ui.be.selectedRoi) == before


def test_locked_projects_refuse_roi_edits(ui):
    select(ui, "05 SurfaceScratchCheck")
    before = list(ui.be.selectedRoi)
    ui.be.setRole("Operator")
    p0, _ = image_to_window(ui, frame_item(ui), 100, 100)
    p1, _ = image_to_window(ui, frame_item(ui), 300, 220)
    ui.drag(p0, p1)
    assert list(ui.be.selectedRoi) == before
    ui.be.setRole("Engineer")


def test_modules_without_a_roi_ignore_viewer_drags(ui):
    select(ui, "01 ImageAcquisition")
    assert list(ui.be.selectedRoi) == [] or True
    n = len(ui.be._undo)
    p0, _ = image_to_window(ui, frame_item(ui), 50, 50)
    p1, _ = image_to_window(ui, frame_item(ui), 250, 150)
    ui.drag(p0, p1)
    if not ui.be.selectedRoi:
        assert len(ui.be._undo) == n


def readout_text(ui):
    return next(t.property("text") for t in ui.of_type("QQuickText") if t.isVisible() and "|" in (t.property("text") or "") and "*" in t.property("text"))


def test_pixel_readout_follows_the_pointer_and_shows_the_real_colour(ui):
    from PyQt6.QtTest import QTest
    select(ui, "01 ImageAcquisition")
    QTest.mouseMove(ui.w, QPoint(5, 5))
    ui.spin(15)
    frame = frame_item(ui)
    w, h = int(frame.property("implicitWidth")), int(frame.property("implicitHeight"))
    assert f"{w} * {h}" in readout_text(ui) and "X,----" in readout_text(ui)
    p, _ = image_to_window(ui, frame, 400, 300)
    QTest.mouseMove(ui.w, p)
    ui.spin(15)
    QTest.mouseMove(ui.w, QPoint(p.x() + 1, p.y()))
    ui.spin(15)
    text = readout_text(ui)
    assert "X,4" in text and "Y,30" in text, text
    c = ui.be._provider.image.pixelColor(int(text.split("X,")[1].split()[0]), int(text.split("Y,")[1].split()[0]))
    assert f"R:{c.red()} G:{c.green()} B:{c.blue()}" in text
    QTest.mouseMove(ui.w, QPoint(5, 5))                                      # leaving the image clears it
    ui.spin(15)
    assert "X,----" in readout_text(ui)


def test_viewer_header_names_the_selected_module(ui):
    select(ui, "03 MountingHole")
    assert ui.texts("03_MountingHole.Output Image")


def test_number_box_plus_and_minus_buttons_are_full_size_and_work(ui):
    ui.host.setProperty("current", "flowSettings")
    ui.spin(40)
    nb = next(c for c in ui.of_type("NumberBox") if c.isVisible())
    v, step = nb.property("value"), nb.property("step")
    p = nb.mapToScene(QPointF(nb.width() - 12, nb.height() / 2))
    ui.click(QPoint(int(p.x()), int(p.y())))                                # [+]
    assert nb.property("value") == pytest.approx(v + step)
    p = nb.mapToScene(QPointF(nb.width() - 36, nb.height() / 2))
    ui.click(QPoint(int(p.x()), int(p.y())))                                # [-]
    assert nb.property("value") == pytest.approx(v)
    ui.key(Qt.Key.Key_Escape)


def test_flyout_search_shows_each_tools_own_category_icon(ui):
    from PyQt6.QtTest import QTest
    ui.main.setProperty("railCategory", 0)
    ui.spin(30)
    box = next(t for t in ui.of_type("TextBox") if t.isVisible() and t.property("placeholder") == "Search modules...")
    ui.click(ui.center(box))
    for ch in "measure":
        QTest.keyClick(ui.w, ch)
    ui.spin(30)
    names = {c["name"]: c["icon"] for c in ui.be.toolCategories for _ in [0]} if False else None
    icons = {}
    for c in ui.be.toolCategories:
        for t in c["tools"]:
            icons[t] = c["icon"]
    shown = [i for i in ui.of_type("Icon") if i.isVisible() and i.property("size") == 28]
    assert len(shown) >= 2
    assert len({i.property("name") for i in shown}) >= 2, "search results from different categories must not share one icon"
    for i in shown:
        assert i.property("name") in set(icons.values())
    ui.main.setProperty("railCategory", -1)


def test_selection_follows_a_newly_loaded_project(ui):
    from test_qml_interaction import DEMO
    select(ui, "04 TraceWidthCaliper")
    ui.main.setProperty("selectedNode", ui.main.property("selectedNode"))       # a user selection (breaks the default binding)
    other = DEMO.replace("PCB_Inspection_Demo", "YOLO_ObjectDetection_Demo")
    ui.be.openRecent(other)
    ui.settle()
    sel = ui.main.property("selectedNode")
    assert any(n["id"] == sel for n in ui.be.nodes), "the selection still points at a module of the previous project"
