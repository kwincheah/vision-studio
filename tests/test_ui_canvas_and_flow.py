"""
Unit and integration tests for UI Canvas interactive handles, overlay layer filters,
multi-flow solution tab switcher, and pipeline stress execution.
"""
import pytest
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent, QPixmap

from apex_vision.ui.image_canvas import ImageCanvasWidget
from apex_vision.ui.main_window import ApexMainWindow
from apex_vision.samples.pcb_solution import create_pcb_inspection_solution
from apex_vision.core.base_tool import ToolStatus
from apex_vision.ui.styles import initialize_app_fonts


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def test_image_canvas_interactive_handles(qapp):
    canvas = ImageCanvasWidget()
    canvas.resize(800, 600)

    # Set test image
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    canvas.set_cv_image(img)
    canvas._scale = 1.0
    canvas._offset = QPoint(0, 0)

    # Set active ROI [100, 100, 200, 150]
    canvas.set_active_roi([100, 100, 200, 150])
    assert canvas.get_active_roi() == [100, 100, 200, 150]

    # Verify 8 handles
    handles = canvas._get_handles()
    assert len(handles) == 8
    for h_name in ("nw", "n", "ne", "e", "se", "s", "sw", "w"):
        assert h_name in handles

    # Hit testing
    # NW handle is around (100, 100)
    assert canvas._get_handle_at(QPoint(100, 100)) == "nw"
    # SE handle is around (300, 250)
    assert canvas._get_handle_at(QPoint(300, 250)) == "se"
    # Inside body around (150, 150)
    assert canvas._get_handle_at(QPoint(150, 150)) == "body"
    # Outside around (10, 10)
    assert canvas._get_handle_at(QPoint(10, 10)) is None

    # Test ROI translation drag
    emitted_rois = []
    canvas.roi_changed.connect(lambda r: emitted_rois.append(list(r)))

    # Press inside body using QPointF
    press_event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(150.0, 150.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier
    )
    canvas.mousePressEvent(press_event)
    assert canvas._resizing_roi is True
    assert canvas._active_handle == "body"

    # Move by dx=30, dy=20
    move_event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(180.0, 170.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier
    )
    canvas.mouseMoveEvent(move_event)
    assert canvas._active_roi == [130, 120, 200, 150]

    # Release
    release_event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(180.0, 170.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier
    )
    canvas.mouseReleaseEvent(release_event)
    assert canvas._resizing_roi is False
    assert len(emitted_rois) == 1
    assert emitted_rois[0] == [130, 120, 200, 150]


def test_image_canvas_layer_filtering_and_render(qapp):
    canvas = ImageCanvasWidget()
    canvas.resize(800, 600)

    img = np.zeros((400, 400, 3), dtype=np.uint8)
    overlays = [
        {"type": "rect", "box": [50, 50, 100, 100], "label": "Defect"},
        {"type": "circle", "center": (200, 200), "radius": 30, "label": "Hole"},
        {"type": "line", "pt1": (10, 10), "pt2": (100, 10), "thickness": 2},
        {"type": "cross", "pt": (200, 200), "size": 10},
        {"type": "text", "pt": (50, 20), "text": "Score: 0.99"}
    ]
    canvas.set_cv_image(img, overlays)

    # Test toggling layers
    canvas.set_overlay_visibility(all_overlays=True, rois=True, measurements=False, datums=True)
    assert canvas._show_rois is True
    assert canvas._show_measurements is False
    assert canvas._show_datums is True

    # Render to offscreen pixmap to ensure paintEvent handles layers gracefully
    pix = QPixmap(800, 600)
    canvas.render(pix)
    assert not pix.isNull()


def test_sub_flow_tab_bar_and_solution(qapp):
    win = ApexMainWindow()
    win.resize(1200, 800)

    # Check initial flow tab
    assert win.flow_tab_bar.count() == 1
    assert "Flow1" in win.flow_tab_bar.tabText(0)

    # Add a new flow
    win.on_add_flow_tab()
    assert win.flow_tab_bar.count() == 2
    assert win.solution.active_flow_name == "Flow2"

    # Switch back to Flow1
    win.on_flow_tab_changed(0)
    assert win.solution.active_flow_name == "Flow1"

    # Run all flows
    win.on_run_all_flows()
    tab_text = win.flow_tab_bar.tabText(0)
    assert "Flow1" in tab_text
    assert ("FAIL" in tab_text) or ("PASS" in tab_text)

    # Remove Flow2
    win.on_flow_tab_closed(1)
    assert win.flow_tab_bar.count() == 1
    assert win.solution.active_flow_name == "Flow1"


def test_continuous_stress_execution():
    pipeline = create_pcb_inspection_solution()

    # Run 100 continuous cycles
    for cycle in range(100):
        results = pipeline.execute_flow()
        assert len(results) >= 6
        assert results["node_source"].status == ToolStatus.OK
        assert results["node_template"].status == ToolStatus.OK
        assert pipeline.last_flow_time_ms > 0
