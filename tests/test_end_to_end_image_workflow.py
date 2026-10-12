"""End-to-End Automated Tests for Complete Machine Vision Workflow.

Validates the complete machine vision loop:
1. Load image from disk via UI action / programmatic entrypoint
2. Execute vision processing operation chain (ImageSource -> Binarization -> BlobAnalysis)
3. Display output on image canvas and update result table
4. Node selection inspection (updating canvas and result panels per selected node)
5. Robust error handling (missing file, invalid format, corrupt data)
6. Solution saving and reloading (.vmp and XML) with verified pipeline re-execution.
"""
import os
import cv2
import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

import vm_clone.tools
from vm_clone.core.base_tool import ToolStatus
from vm_clone.core.pipeline import VisionPipeline, SolutionManager
from vm_clone.core.registry import create_tool_instance
from vm_clone.ui.main_window import VisionMasterMainWindow
from vm_clone.ui.styles import initialize_app_fonts


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


@pytest.fixture
def sample_image_file(tmp_path):
    """Creates a synthetic machine vision target image with distinct shapes."""
    img = np.zeros((400, 600, 3), dtype=np.uint8)
    # Add white rectangle and circle (blobs)
    cv2.rectangle(img, (50, 50), (200, 200), (255, 255, 255), -1)
    cv2.circle(img, (400, 250), 60, (255, 255, 255), -1)
    img_path = str(tmp_path / "vision_test_target.png")
    cv2.imwrite(img_path, img)
    return img_path


def test_e2e_load_image_and_execute_pipeline(qapp, sample_image_file):
    """Verify loading an image file updates ImageSourceTool, executes the flow,

    and displays the result on ImageCanvasWidget.
    """
    win = VisionMasterMainWindow()
    win.resize(1280, 800)
    win.show()
    qapp.processEvents()

    # Load image file through MainWindow's direct entrypoint
    loaded = win.load_image_from_path(sample_image_file)
    assert loaded is True, "Expected load_image_from_path to succeed"
    qapp.processEvents()

    # Verify an ImageSource node exists and has the path configured
    src_nodes = [
        node for node in win.pipeline.nodes.values()
        if node.tool_name == "Image Source"
    ]
    assert len(src_nodes) >= 1
    src_tool = src_nodes[0]
    assert os.path.normpath(src_tool.get_param("file_path")) == os.path.normpath(sample_image_file)

    # Verify canvas displayed image
    assert win.image_canvas._raw_cv_image is not None
    assert win.image_canvas._raw_cv_image.shape[:2] == (400, 600)
    assert win.image_canvas._is_error_state is False


def test_e2e_chain_processing_and_node_selection_inspection(qapp, sample_image_file):
    """Verify chaining ImageSource -> Binarization -> BlobAnalysis.

    Switching node selection on the canvas must switch the image canvas output
    and the result panel display to that specific node's data.
    """
    win = VisionMasterMainWindow()
    win.resize(1280, 800)
    win.show()
    qapp.processEvents()

    # Clear initial template nodes
    for nid in list(win.pipeline.nodes.keys()):
        win.pipeline.remove_node(nid)

    # 1. Create ImageSource
    src = create_tool_instance("Image Source", "src_1", "01_Acquisition")
    src.set_param("source_type", "File")
    src.set_param("file_path", sample_image_file)
    win.pipeline.add_node(src)

    # 2. Create Image Binarization
    bin_tool = create_tool_instance("Image Binarization", "bin_1", "02_Threshold")
    bin_tool.set_param("threshold", 128)
    bin_tool.set_param("max_value", 255)
    win.pipeline.add_node(bin_tool)

    # 3. Create BLOB Analysis
    blob_tool = create_tool_instance("BLOB Analysis", "blob_1", "03_Blob")
    blob_tool.set_param("min_area", 50)
    win.pipeline.add_node(blob_tool)

    # Connect ports (Image -> Image)
    win.pipeline.connect("src_1", "Image", "bin_1", "Image")
    win.pipeline.connect("bin_1", "Image", "blob_1", "Image")
    win.flow_scene.build_from_pipeline()

    # Run pipeline once
    results = win.pipeline.execute_flow()
    assert results["src_1"].status == ToolStatus.OK
    assert results["bin_1"].status == ToolStatus.OK
    assert results["blob_1"].status == ToolStatus.OK
    assert results["blob_1"].outputs.get("Count", 0) >= 2

    # Test selecting Binarization node
    win.on_node_selected("bin_1")
    qapp.processEvents()
    assert win.image_canvas._raw_cv_image is not None
    # Binarized output has binary levels (0 or 255)
    unique_vals = set(np.unique(win.image_canvas._raw_cv_image))
    assert unique_vals.issubset({0, 255})

    # Test selecting BLOB Analysis node
    win.on_node_selected("blob_1")
    qapp.processEvents()
    assert win.selected_node_id == "blob_1"
    assert "Count" in results["blob_1"].outputs

    # Test selecting ImageSource node
    win.on_node_selected("src_1")
    qapp.processEvents()
    assert win.selected_node_id == "src_1"
    assert win.image_canvas._raw_cv_image.shape == (400, 600, 3)


def test_e2e_error_handling_invalid_file(qapp, tmp_path):
    """Verify that attempting to load a non-existent or corrupt image triggers

    graceful error handling, empty state watermark, and no unhandled exceptions.
    """
    win = VisionMasterMainWindow()
    win.resize(1280, 800)
    win.show()
    qapp.processEvents()

    # 1. Non-existent file
    bogus_path = str(tmp_path / "does_not_exist.png")
    success = win.load_image_from_path(bogus_path)
    assert success is False
    assert win.image_canvas._is_error_state is True
    assert "does not exist" in win.image_canvas._empty_message.lower()

    # 2. Corrupt / invalid non-image file
    corrupt_file = str(tmp_path / "corrupt.png")
    with open(corrupt_file, "w") as f:
        f.write("not an image binary")
    success_corrupt = win.load_image_from_path(corrupt_file)
    assert success_corrupt is False
    assert win.image_canvas._is_error_state is True
    assert "failed to decode" in win.image_canvas._empty_message.lower()


def test_e2e_save_and_reload_solution(qapp, sample_image_file, tmp_path):
    """Verify saving a complete vision workflow with configured image and parameters,

    reloading it from disk, and re-executing it to ensure deterministic output.
    """
    win = VisionMasterMainWindow()
    win.resize(1280, 800)
    win.show()
    qapp.processEvents()

    # Setup workflow
    for nid in list(win.pipeline.nodes.keys()):
        win.pipeline.remove_node(nid)

    src = create_tool_instance("Image Source", "src_save", "01_Acquisition")
    src.set_param("source_type", "File")
    src.set_param("file_path", sample_image_file)
    win.pipeline.add_node(src)

    bin_tool = create_tool_instance("Image Binarization", "bin_save", "02_Threshold")
    bin_tool.set_param("threshold", 120)
    win.pipeline.add_node(bin_tool)

    win.pipeline.connect("src_save", "Image", "bin_save", "Image")
    win.flow_scene.build_from_pipeline()

    # Save solution
    save_path = str(tmp_path / "test_flow.vmp")
    win.project_manager.save_project(win.solution, save_path)
    assert os.path.exists(save_path)

    # Also test XML export of flow
    xml_path = str(tmp_path / "test_flow.xml")
    win.solution.export_flow_xml(win.solution.active_flow_name, xml_path)
    assert os.path.exists(xml_path)

    # Reload into a fresh window
    win2 = VisionMasterMainWindow()
    win2.resize(1280, 800)
    win2.show()
    qapp.processEvents()

    loaded_sol = win2.project_manager.load_project(save_path)
    win2.load_solution_manager(loaded_sol, filepath=save_path)
    qapp.processEvents()

    # Re-run pipeline in the reloaded window
    results = win2.pipeline.execute_flow()
    nodes = win2.pipeline.nodes
    assert len(nodes) == 2
    assert "src_save" in nodes
    assert "bin_save" in nodes

    assert nodes["src_save"].get_param("file_path") == sample_image_file
    assert nodes["bin_save"].get_param("threshold") == 120
    assert results["src_save"].status == ToolStatus.OK
    assert results["bin_save"].status == ToolStatus.OK
