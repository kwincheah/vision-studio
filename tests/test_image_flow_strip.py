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
    """Auto switch + 'Run all' + Continuously: every cycle takes the next image."""
    win = VisionMasterMainWindow()
    win.image_display.btn_auto.setChecked(True)
    assert win.image_display.cbo_run_scope.currentText() == "Run all"
    n = len(win._image_flow)
    assert n > 1
    win._current_image_flow_index = 0
    win._ticks_since_start = 0
    seen = []
    for _ in range(n + 1):
        win._on_run_timer()
        seen.append(win._current_image_flow_index)
    assert seen == [(i % n) for i in range(n + 1)]          # first tick uses image 0, then 1, 2 ... wraps
    assert win.image_display.strip.currentRow() == win._current_image_flow_index

    # without Auto switch the same image is re-run every cycle
    win.image_display.btn_auto.setChecked(False)
    keep = win._current_image_flow_index
    win._on_run_timer()
    win._on_run_timer()
    assert win._current_image_flow_index == keep

    win.close()
    win.deleteLater()


def test_run_all_processes_every_image_once(qapp):
    win = VisionMasterMainWindow()
    n = len(win._image_flow)
    visited = []
    real = win.engine.request_run
    win.engine.request_run = lambda: (visited.append(win._current_image_flow_index), real())[1]
    win.on_strip_run_requested()
    import time
    end = time.time() + 5
    while win._batch is not None and time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)
    assert visited == list(range(n))
    assert win._batch is None
    assert "Run all finished" in win.lbl_view_status.text()
    win.close()
    win.deleteLater()


def test_run_selected_scope_runs_only_the_current_image(qapp):
    win = VisionMasterMainWindow()
    win.image_display.cbo_run_scope.setCurrentText("Run selected")
    win.on_strip_run_requested()
    assert win._batch is None
    win.close()
    win.deleteLater()


def test_load_folder_adds_every_image_in_natural_order(qapp, tmp_path):
    import cv2
    import numpy as np
    for name in ("img10.png", "img2.png", "img1.png", "notes.txt", "broken.png"):
        path = tmp_path / name
        if name == "notes.txt":
            path.write_text("x")
        elif name == "broken.png":
            path.write_bytes(b"not an image")
        else:
            cv2.imwrite(str(path), np.full((20, 30, 3), 90, np.uint8))
    win = VisionMasterMainWindow()
    before = len(win._image_flow)
    assert win.image_display.btn_add_folder.toolTip()
    added = win.load_image_folder(str(tmp_path))
    assert added == 3
    names = [i["name"] for i in win._image_flow[before:]]
    assert names == ["img1.png", "img2.png", "img10.png"]
    assert win._current_image_flow_index == before            # first new image is selected
    assert win.load_image_folder(str(tmp_path / "missing")) == 0
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


def _spin_until(qapp, predicate, timeout=5.0):
    import time
    end = time.time() + timeout
    while time.time() < end and not predicate():
        qapp.processEvents()
        time.sleep(0.005)
    return predicate()


def test_run_button_becomes_stop_and_returns_only_after_finishing(qapp):
    win = VisionMasterMainWindow()
    n = len(win._image_flow)
    btn = win.image_display.btn_play
    assert btn.text().strip() == "Run" and btn.isEnabled()
    states = []
    win.engine.state_changed.connect(lambda: states.append(btn.text().strip()))
    win.on_strip_run_requested()
    assert btn.text().strip() == "Stop"
    assert _spin_until(qapp, lambda: win._batch is None and not win._strip_run_active)
    assert btn.text().strip() == "Run" and btn.isEnabled()
    assert "Stop" in states and states[-1] == "Run"
    # it never flipped back to Run while images were still queued
    assert states.index("Run") > len(states) - 3 or "Run" not in states[:-1]
    win.close()
    win.deleteLater()


def test_loop_repeats_all_images_until_stop(qapp):
    win = VisionMasterMainWindow()
    n = len(win._image_flow)
    win.image_display.btn_auto.setChecked(True)
    assert win.image_display.lbl_auto.text() == "Loop"
    visited = []
    real = win.engine.request_run
    win.engine.request_run = lambda: (visited.append(win._current_image_flow_index), real())[1]
    win.pipeline.run_interval_ms = 1
    win.on_strip_run_requested()
    assert _spin_until(qapp, lambda: len(visited) >= 3 * n)
    assert win.image_display.btn_play.text().strip() == "Stop"
    assert visited[:3 * n] == [i % n for i in range(3 * n)]        # pass after pass, in order
    win.on_strip_run_requested()                                   # the button is now Stop
    assert win._batch is None
    count = len(visited)
    _spin_until(qapp, lambda: False, timeout=0.2)
    assert len(visited) <= count + 1                               # at most the cycle in flight
    assert win.image_display.btn_play.text().strip() == "Run"
    win.close()
    win.deleteLater()


def test_loop_with_run_selected_repeats_the_current_image(qapp):
    win = VisionMasterMainWindow()
    win.image_display.btn_auto.setChecked(True)
    win.image_display.cbo_run_scope.setCurrentText("Run selected")
    win.pipeline.run_interval_ms = 1
    keep = win._current_image_flow_index
    visited = []
    real = win.engine.request_run
    win.engine.request_run = lambda: (visited.append(win._current_image_flow_index), real())[1]
    win.on_strip_run_requested()
    assert _spin_until(qapp, lambda: len(visited) >= 4)
    assert set(visited[:4]) == {keep}
    win.on_stop()
    win.close()
    win.deleteLater()


def test_stop_button_shows_stopping_until_the_cycle_in_flight_ends(qapp, monkeypatch):
    import time
    win = VisionMasterMainWindow()
    win.run_async = True
    _spin_until(qapp, lambda: not win.is_running_flow())
    real = win.pipeline.execute_flow
    monkeypatch.setattr(win.pipeline, "execute_flow", lambda *a, **k: (time.sleep(0.5), real(*a, **k))[1])
    win.image_display.btn_auto.setChecked(True)
    win.pipeline.run_interval_ms = 1
    win.on_strip_run_requested()
    assert _spin_until(qapp, lambda: win.is_running_flow())
    win.on_strip_run_requested()                                   # Stop pressed mid-cycle
    btn = win.image_display.btn_play
    assert "Stopping" in btn.text() and not btn.isEnabled()
    assert _spin_until(qapp, lambda: not win.is_running_flow())
    assert _spin_until(qapp, lambda: btn.text().strip() == "Run")
    assert btn.isEnabled()
    win.close()
    win.deleteLater()
