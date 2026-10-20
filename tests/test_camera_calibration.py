"""
Automated Unit and Acceptance Tests for Camera Lens Distortion Calibration.
Verifies:
1. Pattern corner detection on planar chessboard grids
2. Multi-view camera intrinsic calibration convergence
3. Radial and tangential distortion estimation
4. Undistortion / image rectification
5. Calibration profile JSON serialization roundtrip
6. CameraCalibrationTool DAG pipeline integration
7. CameraCalibrationDialog interactive workflow and signals
"""
import os
import json
import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from vm_clone.core.lens_calibration import LensCalibrationModel
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.core.registry import create_tool_instance, get_tool_class
from vm_clone.tools.calibration import CameraCalibrationTool
from vm_clone.ui.camera_calibration_dialog import CameraCalibrationDialog
from vm_clone.ui.styles import initialize_app_fonts


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def test_lens_calibration_model_synthetic_generation():
    """Verify synthetic distorted chessboard generator produces valid images and metadata."""
    distorted, ideal, meta = LensCalibrationModel.generate_synthetic_distorted_chessboard(
        width=800, height=600, grid_size=(9, 6), square_size_px=45, k1=-0.28, k2=0.08
    )
    assert distorted.shape == (600, 800, 3)
    assert ideal.shape == (600, 800, 3)
    assert meta["fx"] > 0 and meta["fy"] > 0
    assert meta["k1"] == -0.28
    assert meta["grid_size"] == [9, 6]

    # Verify distorted image differs from ideal due to optical curvature
    diff = np.abs(distorted.astype(float) - ideal.astype(float))
    assert np.mean(diff) > 1.0


def test_pattern_detection():
    """Verify chessboard corner detection and subpixel refinement."""
    distorted, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(
        width=800, height=600, grid_size=(9, 6)
    )
    found, corners, annotated = LensCalibrationModel.detect_pattern(
        distorted, pattern_type="Chessboard", grid_size=(9, 6)
    )
    assert found is True
    assert corners is not None
    assert len(corners) == 54  # 9 * 6
    assert annotated.shape == (600, 800, 3)


def test_multi_view_camera_calibration():
    """Verify calibration solver converges on multi-view distorted chessboard captures."""
    model = LensCalibrationModel(grid_size=(9, 6), square_size_mm=25.0)

    # Accumulate 3 views at varying rotations
    for angle in [0.0, 6.0, -6.0]:
        img, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(
            width=800, height=600, grid_size=(9, 6), rotation_deg=angle, k1=-0.25, k2=0.06
        )
        ok, msg, _ = model.add_image(img, name=f"View_{angle}")
        assert ok is True

    assert len(model.object_points_list) == 3
    assert len(model.image_points_list) == 3

    success, rms, msg = model.compute_calibration()
    assert success is True
    assert rms >= 0.0
    assert rms < 0.25  # Sub-pixel accuracy
    assert model.is_calibrated is True

    fx, fy = model.get_focal_length()
    cx, cy = model.get_principal_point()
    k1, k2, _ = model.get_radial_distortion()

    assert 400.0 < fx < 1200.0
    assert 400.0 < fy < 1200.0
    assert 300.0 < cx < 500.0
    assert 200.0 < cy < 400.0
    assert abs(k1) > 0.1  # Significant radial distortion captured


def test_undistort_rectification():
    """Verify lens rectification removes barrel distortion."""
    model = LensCalibrationModel(grid_size=(9, 6))
    for angle in [0.0, 5.0, -5.0]:
        img, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(
            width=800, height=600, grid_size=(9, 6), rotation_deg=angle, k1=-0.30
        )
        model.add_image(img)

    model.compute_calibration()

    test_img, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(
        width=800, height=600, grid_size=(9, 6), k1=-0.30
    )
    rectified = model.undistort(test_img, alpha=0.0)
    assert rectified.shape == test_img.shape
    assert not np.array_equal(rectified, test_img)


def test_calibration_profile_json_roundtrip(tmp_path):
    """Verify calibration profile serialization and deserialization."""
    model = LensCalibrationModel(grid_size=(9, 6), square_size_mm=30.0)
    img, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(grid_size=(9, 6))
    model.add_image(img)
    model.compute_calibration()

    fpath = str(tmp_path / "test_lens.calib.json")
    model.save_json(fpath)
    assert os.path.exists(fpath)

    loaded_model = LensCalibrationModel()
    ok = loaded_model.load_json(fpath)
    assert ok is True
    assert loaded_model.is_calibrated is True
    assert loaded_model.rms_error == model.rms_error
    assert np.allclose(loaded_model.camera_matrix, model.camera_matrix)
    assert np.allclose(loaded_model.dist_coeffs, model.dist_coeffs)


def test_camera_calibration_tool_pipeline():
    """Verify Lens Distortion Calibration tool inside VisionPipeline DAG."""
    pipe = VisionPipeline(name="Calibration_Test_Flow")

    src = create_tool_instance("Image Source", "src_1", "01_Acq")
    src.set_param("source_type", "Synthetic")
    src.set_param("pattern_type", "Distorted Chessboard")
    pipe.add_node(src)

    calib_tool = create_tool_instance("Lens Distortion Calibration", "calib_1", "02_LensRectify")
    calib_tool.set_param("mode", "Manual Coefficients")
    calib_tool.set_param("manual_k1", -0.25)
    calib_tool.set_param("manual_k2", 0.05)
    pipe.add_node(calib_tool)

    pipe.connect("src_1", "Image", "calib_1", "Image")

    results = pipe.execute_flow()
    assert "src_1" in results and results["src_1"].status.name == "OK"
    assert "calib_1" in results and results["calib_1"].status.name == "OK"

    calib_res = results["calib_1"]
    assert "Image" in calib_res.outputs
    assert calib_res.outputs["Image"].shape == (600, 800, 3)
    assert calib_res.outputs["Dist_K1"] == -0.25
    assert len(calib_res.overlays) >= 1


def test_calibration_dialog_ui(qapp):
    """Verify CameraCalibrationDialog interactive controls, solve, and signal emission."""
    distorted, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard()
    dialog = CameraCalibrationDialog(distorted)

    assert dialog.list_views.count() >= 1
    assert dialog.spin_cols.value() == 9
    assert dialog.spin_rows.value() == 6

    # Generate synthetic view
    dialog.btn_synth.click()
    assert dialog.list_views.count() >= 2

    # Compute calibration
    dialog._on_compute_calibration()
    assert dialog.model.is_calibrated is True
    assert "CALIBRATED" in dialog.lbl_status_badge.text()

    # Test apply signal
    applied_data = []
    dialog.calibration_applied.connect(applied_data.append)
    dialog._on_apply_to_flow()
    assert len(applied_data) == 1
    assert "intrinsics" in applied_data[0]
    assert "distortion" in applied_data[0]
    dialog.deleteLater()


def test_dialog_views_stay_aligned_with_the_model_when_a_view_is_ng(qapp, tmp_path):
    """An NG view has a list row but no model entry; selecting / removing later rows must still hit
    the right frame (this used to pop the wrong calibration view)."""
    import cv2
    import numpy as np
    from vm_clone.ui.camera_calibration_dialog import CameraCalibrationDialog
    dialog = CameraCalibrationDialog()
    try:
        dialog._on_clear_views()                       # the dialog seeds one synthetic view on open
        dialog._add_image_frame(np.full((120, 160, 3), 200, np.uint8), "blank")      # NG: no pattern
        dialog._on_generate_synthetic()
        dialog._on_generate_synthetic()
        assert [v["ok"] for v in dialog.session.views] == [False, True, True]
        assert dialog.list_views.count() == 3 and len(dialog.model.object_points_list) == 2
        dialog.list_views.setCurrentRow(1)
        dialog._on_view_selection_changed(1)
        assert "Synthetic View 2" in dialog.lbl_view_caption.text()
        dialog._on_remove_view()                       # removes the first synthetic view, not the wrong one
        assert [v["name"].split(" (")[0] for v in dialog.session.views] == ["blank", "Synthetic View 3"]
        assert len(dialog.model.object_points_list) == 1 and dialog.list_views.count() == 2
        dialog._on_clear_views()
        assert dialog.list_views.count() == 0 and not dialog.model.object_points_list
    finally:
        dialog.deleteLater()
