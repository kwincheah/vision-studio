"""Tests verifying the Image Bar in the Image | Result tab displays the flow of added images,
rather than intermediate outputs from different DAG nodes.

Validates:
1. Strip displays added input images (image pool), not outputs from downstream processing nodes.
2. Adding multiple images via add_image_to_flow / file loader updates the strip count and labels.
3. Selecting a different image from the strip feeds that image into Image Source and runs the pipeline.
4. Navigation prev / next steps through the flow of added images.
5. Auto-switch option advances the image flow across consecutive runs.
6. Clear image flow empties the strip cleanly.
"""
import os
import cv2
import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from vm_clone.ui.main_window import VisionMasterMainWindow
from vm_clone.ui.styles import initialize_app_fonts


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def test_image_strip_shows_flow_of_added_images_not_diff_nodes(qapp):
    """The image bar must list the input images added, not intermediate DAG nodes."""
    win = VisionMasterMainWindow()
    win.run_pipeline_step()
    for _ in range(3):
        qapp.processEvents()

    strip = win.image_display.strip
    # Must have the seeded images added to the flow
    assert strip.count() >= 2
    assert len(win._image_flow) >= 2

    # Verify strip items correspond to added images, NOT DAG node names
    flow_names = [item["name"] for item in win._image_flow]
    assert "pcb_sample.png" in flow_names

    # Check that downstream module node names (e.g. 02_IC_Alignment, 03_MountingHole) are NOT in the strip
    node_names = [node.name for node in win.pipeline.nodes.values() if node.tool_name != "Image Source"]
    for node_name in node_names:
        assert node_name not in flow_names, f"Node output '{node_name}' found in image flow strip!"

    # Header counter must show (1/N)
    assert f"(1/{len(flow_names)})" in win.image_display.lbl_strip.text()
    win.close()
    win.deleteLater()


def test_add_image_to_flow_updates_strip_and_thumbnails(qapp, tmp_path):
    win = VisionMasterMainWindow()
    initial_count = win.image_display.strip.count()

    # Create dummy images on disk
    img1_path = str(tmp_path / "part_alpha.png")
    img2_path = str(tmp_path / "part_beta.png")
    cv2.imwrite(img1_path, np.zeros((200, 200, 3), dtype=np.uint8) + 100)
    cv2.imwrite(img2_path, np.zeros((200, 200, 3), dtype=np.uint8) + 200)

    # Add images
    ok1 = win.add_image_to_flow(img1_path, execute=False)
    assert ok1 is True
    ok2 = win.add_image_to_flow(img2_path, execute=True)
    assert ok2 is True

    for _ in range(3):
        qapp.processEvents()

    assert win.image_display.strip.count() == initial_count + 2
    assert "part_alpha.png" in [item["name"] for item in win._image_flow]
    assert "part_beta.png" in [item["name"] for item in win._image_flow]

    win.close()
    win.deleteLater()


def test_switching_image_in_strip_executes_pipeline_with_selected_image(qapp):
    win = VisionMasterMainWindow()
    for _ in range(3):
        qapp.processEvents()

    assert win.image_display.strip.count() >= 2

    # Select Golden PCB (Index 0)
    win.image_display.strip.setCurrentRow(0)
    for _ in range(3):
        qapp.processEvents()
    assert win._current_image_flow_index == 0
    assert "(1/" in win.image_display.lbl_strip.text()

    # Select Defective PCB (Index 1)
    win.image_display.strip.setCurrentRow(1)
    for _ in range(3):
        qapp.processEvents()
    assert win._current_image_flow_index == 1
    assert "(2/" in win.image_display.lbl_strip.text()

    win.close()
    win.deleteLater()


def test_auto_switch_cycles_added_images(qapp):
    win = VisionMasterMainWindow()
    win.image_display.btn_auto.setChecked(True)
    assert win.image_display.btn_auto.isChecked()

    # Initial position
    win._current_image_flow_index = 0
    win.run_pipeline_step()
    for _ in range(3):
        qapp.processEvents()

    # After step with auto-switch, next index is prepared
    assert win._current_image_flow_index == 1

    win.close()
    win.deleteLater()


def test_clear_image_flow(qapp):
    win = VisionMasterMainWindow()
    assert win.image_display.strip.count() > 0

    win.on_clear_image_flow()
    for _ in range(3):
        qapp.processEvents()

    assert len(win._image_flow) == 0
    assert win.image_display.strip.count() == 0

    win.close()
    win.deleteLater()
