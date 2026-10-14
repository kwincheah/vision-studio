"""
Comprehensive Robustness & Edge-Case Test Suite.
Tests all registered Vision Master tools against invalid types, out-of-bounds ROIs,
corrupted images, zero-dimension buffers, and UI undo macro atomic operations.
"""
import pytest
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QKeyEvent

import vm_clone.tools
from vm_clone.core.registry import list_all_tools, create_tool_instance
from vm_clone.core.base_tool import ToolStatus
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.ui.flow_editor import (
    FlowScene,
    FlowEditorView,
    AddNodeCommand,
    AddConnectionCommand,
    ConnectionItem,
    FlowNodeItem
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_all_tools_fuzz_contexts():
    """All registered tools must execute safely without uncaught exceptions on edge-case inputs."""
    tools = list_all_tools()
    assert len(tools) >= 35, f"Expected at least 35 registered tools, got {len(tools)}"

    fuzz_contexts = [
        {},
        {"Image": None},
        {"Image": "string_not_ndarray"},
        {"Image": 42},
        {"Image": [1, 2, 3]},
        {"Image": np.zeros((0, 0), dtype=np.uint8)},
        {"Image": np.zeros((0, 0, 3), dtype=np.uint8)},
        {"Image": np.zeros((1, 1), dtype=np.uint8)},
        {"Image": np.zeros((1, 1, 3), dtype=np.uint8)},
        {"Image": np.zeros((10, 10, 5), dtype=np.uint8)},
        {"Pixel_X": None, "Pixel_Y": "invalid_str"},
        {"Val_In": None, "Val_A": "invalid", "Val_B": None, "Condition_In": None},
        {"Trigger_Signal": None, "Input_Text": None}
    ]

    for name in tools:
        tool = create_tool_instance(name, f"fuzz_{name}")
        for ctx in fuzz_contexts:
            try:
                res = tool.execute(ctx)
                assert res is not None
                assert hasattr(res, "status")
            except Exception as exc:
                pytest.fail(f"Tool '{name}' raised unhandled exception {type(exc).__name__}: {exc} on context {ctx}")


def test_tools_out_of_bounds_rois():
    """Tools must gracefully clamp or reject out-of-bounds ROIs without crashing."""
    img = np.full((100, 100, 3), 128, dtype=np.uint8)

    # Test tools that accept 'roi' parameter
    roi_tools = [
        "Color Measurement",
        "Intensity Measure",
        "Pixel Count",
        "Histogram",
        "Defect Detection",
        "Linear Edge Defect",
        "OCR Recognition",
        "Object Detection"
    ]

    oob_rois = [
        [-500, -500, 50, 50],
        [200, 200, 300, 300],
        [0, 0, 9999, 9999],
        [50, 50, 0, 0],
        [50, 50, -20, -20],
        "invalid_roi_type"
    ]

    for name in roi_tools:
        if name == "Object Detection":
            try:
                import ultralytics  # noqa: F401
            except ImportError:
                continue

        tool = create_tool_instance(name, f"roi_{name}")
        for roi in oob_rois:
            tool.set_param("roi", roi)
            res = tool.execute({"Image": img})
            assert res is not None
            assert res.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.READY)


def test_location_and_measurement_extreme_parameters():
    """Test Location and Measurement tools with extreme thresholds and parameters."""
    img = np.full((200, 200, 3), 200, dtype=np.uint8)

    # Caliper extreme thresholds
    caliper = create_tool_instance("Caliper", "cal1")
    caliper.set_param("edge_threshold", 999999.0)
    caliper.set_param("start_pt", [-100, -100])
    caliper.set_param("end_pt", [5000, 5000])
    res = caliper.execute({"Image": img})
    assert res.status == ToolStatus.NG

    # Circle Search with inverted radius
    circle = create_tool_instance("Circle Search", "cir1")
    circle.set_param("min_radius", 100)
    circle.set_param("max_radius", 10)  # min > max
    res_cir = circle.execute({"Image": img})
    assert res_cir.status in (ToolStatus.OK, ToolStatus.NG)

    # Blob Analysis with inverted area filter
    blob = create_tool_instance("BLOB Analysis", "blob1")
    blob.set_param("min_area", 5000)
    blob.set_param("max_area", 10)  # min > max
    res_blob = blob.execute({"Image": img})
    assert res_blob.status in (ToolStatus.OK, ToolStatus.NG)
    assert res_blob.outputs.get("Count") == 0


def test_flow_editor_multi_selection_undo_macro(qapp):
    """Verify that deleting multiple selected nodes and connections forms an atomic macro undo/redo."""
    pipeline = VisionPipeline()
    t1 = create_tool_instance("Image Source", "n1")
    t2 = create_tool_instance("Image Binarization", "n2")
    t3 = create_tool_instance("BLOB Analysis", "n3")

    scene = FlowScene(pipeline)
    view = FlowEditorView(scene)

    scene.undo_stack.push(AddNodeCommand(scene, t1, QPointF(50, 50)))
    scene.undo_stack.push(AddNodeCommand(scene, t2, QPointF(250, 50)))
    scene.undo_stack.push(AddNodeCommand(scene, t3, QPointF(450, 50)))

    scene.undo_stack.push(AddConnectionCommand(scene, "n1", "Image", "n2", "Image"))
    scene.undo_stack.push(AddConnectionCommand(scene, "n2", "Image", "n3", "Image"))

    assert len(pipeline.nodes) == 3
    assert len(pipeline.connections) == 2

    # Select node 2 and node 3 together
    scene.clearSelection()
    item2 = scene.node_items["n2"]
    item3 = scene.node_items["n3"]
    item2.setSelected(True)
    item3.setSelected(True)

    # Simulate Delete key event on FlowEditorView
    del_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    view.keyPressEvent(del_event)

    # Both nodes should be removed
    assert "n2" not in pipeline.nodes
    assert "n3" not in pipeline.nodes
    assert "n1" in pipeline.nodes
    assert len(pipeline.connections) == 0

    # Single Undo must restore BOTH nodes atomically thanks to beginMacro / endMacro
    scene.undo_stack.undo()

    assert "n2" in pipeline.nodes
    assert "n3" in pipeline.nodes
    assert "n1" in pipeline.nodes
    # Connections should be restored
    assert len(pipeline.connections) == 2

    # Single Redo must re-delete BOTH nodes atomically
    scene.undo_stack.redo()
    assert "n2" not in pipeline.nodes
    assert "n3" not in pipeline.nodes
    assert len(pipeline.connections) == 0
