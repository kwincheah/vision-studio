"""
Automated unit tests for Flow Editor interactive behaviors:
- Drag-and-drop wire connections between nodes
- Wire selection and deletion
- Hierarchical auto-layout
- Node position preservation
- Tool drop event and placement
"""
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent, QWheelEvent

import vm_clone.tools
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.core.registry import create_tool_instance
from vm_clone.ui.flow_editor import FlowScene, FlowEditorView, NodeSignals, PortItem, ConnectionItem
from vm_clone.ui.styles import initialize_app_fonts


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def test_interactive_wire_connection(qapp):
    pipe = VisionPipeline()
    src = create_tool_instance("Image Source", "src_1", "01_Acq")
    bcr = create_tool_instance("2D BCR Recognition", "bcr_1", "02_BCR")
    pipe.add_node(src)
    pipe.add_node(bcr)

    signals = NodeSignals()
    scene = FlowScene(pipe, signals)
    scene.build_from_pipeline(preserve_positions=False)

    p_out = scene.node_items["src_1"].out_ports["Image"]
    p_in = scene.node_items["bcr_1"].in_ports["Image"]

    # Start drag on output port
    scene.start_connection_drag(p_out)
    assert scene.is_dragging_connection() is True

    # Complete drag at target input port location
    target_pos = p_in.get_center_scene_pos()
    scene.finish_connection_drag_at_pos(target_pos)

    # Verify connection was registered in pipeline
    assert len(pipe.connections) == 1
    assert pipe.connections[0].from_node == "src_1"
    assert pipe.connections[0].to_node == "bcr_1"
    assert len(scene.connection_items) == 1


def test_connection_selection_and_deletion(qapp):
    pipe = VisionPipeline()
    src = create_tool_instance("Image Source", "src_1", "01_Acq")
    bcr = create_tool_instance("2D BCR Recognition", "bcr_1", "02_BCR")
    pipe.add_node(src)
    pipe.add_node(bcr)
    pipe.connect("src_1", "Image", "bcr_1", "Image")

    signals = NodeSignals()
    scene = FlowScene(pipe, signals)
    scene.build_from_pipeline()

    assert len(scene.connection_items) == 1
    c_item = scene.connection_items[0]

    # Test wire shape and selection
    shape = c_item.shape()
    assert not shape.isEmpty()

    c_item.setSelected(True)
    assert c_item.isSelected() is True

    # Remove wire
    scene.remove_connection_item(c_item)
    assert len(pipe.connections) == 0
    assert len(scene.connection_items) == 0


def test_node_position_preservation(qapp):
    pipe = VisionPipeline()
    src = create_tool_instance("Image Source", "src_1")
    pipe.add_node(src)

    signals = NodeSignals()
    scene = FlowScene(pipe, signals)
    scene.build_from_pipeline()

    # Move node to custom position
    custom_pos = QPointF(320.0, 480.0)
    scene.node_items["src_1"].setPos(custom_pos)

    # Add a second node and rebuild with position preservation
    bcr = create_tool_instance("2D BCR Recognition", "bcr_1")
    pipe.add_node(bcr)
    scene.build_from_pipeline(preserve_positions=True)

    # First node must preserve its custom position
    assert scene.node_items["src_1"].pos() == custom_pos


def test_hierarchical_auto_layout(qapp):
    pipe = VisionPipeline()
    src = create_tool_instance("Image Source", "src_1")
    bin_tool = create_tool_instance("Image Binarization", "bin_1")
    blob_tool = create_tool_instance("BLOB Analysis", "blob_1")
    pipe.add_node(src)
    pipe.add_node(bin_tool)
    pipe.add_node(blob_tool)

    # Chain: src -> bin -> blob
    pipe.connect("src_1", "Image", "bin_1", "Image")
    pipe.connect("bin_1", "Image", "blob_1", "Image")

    signals = NodeSignals()
    scene = FlowScene(pipe, signals)
    scene.build_from_pipeline(preserve_positions=False)

    scene.arrange_nodes_hierarchically()

    pos_src = scene.node_items["src_1"].pos()
    pos_bin = scene.node_items["bin_1"].pos()
    pos_blob = scene.node_items["blob_1"].pos()

    # Check horizontal cascade by dependency level: x_src < x_bin < x_blob
    assert pos_src.x() < pos_bin.x() < pos_blob.x()


def test_flow_editor_view_zoom(qapp):
    pipe = VisionPipeline()
    signals = NodeSignals()
    scene = FlowScene(pipe, signals)
    view = FlowEditorView(scene)
    view.resize(600, 400)

    initial_scale = view.transform().m11()
    assert abs(initial_scale - 1.0) < 1e-4

    # Zoom in
    view.scale(1.15, 1.15)
    zoomed_scale = view.transform().m11()
    assert zoomed_scale > initial_scale


def test_flow_editor_drop_event(qapp):
    from PyQt6.QtGui import QDropEvent
    from PyQt6.QtCore import QMimeData, QPointF
    pipe = VisionPipeline()
    signals = NodeSignals()
    scene = FlowScene(pipe, signals)
    view = FlowEditorView(scene)
    view.resize(600, 400)

    dropped = []
    signals.tool_dropped.connect(lambda name, x, y: dropped.append((name, x, y)))

    mime = QMimeData()
    mime.setText("Image Binarization")

    event = QDropEvent(
        QPointF(150.0, 200.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.dropEvent(event)
    assert len(dropped) == 1
    assert dropped[0][0] == "Image Binarization"

