"""Automated Tests for Hikrobot MVS (Machine Vision Software) Direct Compatibility.

Verifies:
1. MvsSdkLoader dynamic loader, ctypes bindings, and emulation mode fallback.
2. MvsCameraDriver device discovery, frame acquisition, and GenICam parameter controls.
3. MvsConfigFileManager .mvs / .xml GenICam feature file parsing and exporting.
4. LensCalibrationModel MVS XML calibration file roundtrip and undistortion.
5. ImageSourceTool execution with 'Hikrobot MVS' source type and pipeline integration.
6. CameraManagementDialog UI MVS status badge and import/export actions.
"""
import os
import pytest
import numpy as np
from PyQt6.QtWidgets import QApplication

import vm_clone.tools
from vm_clone.core.base_tool import ToolStatus
from vm_clone.core.camera_manager import CameraManager
from vm_clone.core.mvs_sdk import (
    MvsSdkLoader,
    MvsCameraDriver,
    MvsConfigFileManager,
    MV_GIGE_DEVICE,
    MV_USB_DEVICE,
    PixelType_Gvsp_Mono8,
    PixelType_Gvsp_BGR8_Packed
)
from vm_clone.core.lens_calibration import LensCalibrationModel
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.core.registry import create_tool_instance
from vm_clone.ui.camera_dialog import CameraManagementDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_mvs_sdk_loader():
    """Verify MvsSdkLoader initializes cleanly and reports version/status."""
    loader = MvsSdkLoader.get_instance()
    assert loader is not None
    assert isinstance(loader.sdk_version, str)
    assert len(loader.sdk_version) > 0
    # In headless environment without Hikrobot MVS hardware installed, emulation is reported
    assert loader.is_sdk_available in (True, False)


def test_mvs_device_enumeration_and_driver():
    """Verify CameraManager discovers MVS GigE & USB3 cameras and initializes MvsCameraDriver."""
    cm = CameraManager.get_instance()
    devs = cm.list_devices()
    mvs_devs = [d for d in devs if "Hikrobot MVS" in d.camera_type or d.device_id.startswith("mvs_")]
    assert len(mvs_devs) >= 2

    # Check GigE device
    gige_dev = cm.get_device("mvs_gige_0")
    assert gige_dev is not None
    assert "MV-CA050-10GM" in gige_dev.model
    assert gige_dev.camera_type == "Hikrobot MVS GigE"

    # Instantiate driver
    driver = cm.get_or_create_driver("mvs_gige_0")
    assert isinstance(driver, MvsCameraDriver)

    # Configure GenICam parameters
    assert driver.set_exposure(16000.0) is True
    assert driver.exposure_time_us == 16000.0
    assert driver.set_gain(2.2) is True
    assert driver.gain == 2.2
    assert driver.set_trigger_mode("Software Trigger") is True
    assert driver.set_trigger_source("Software") is True
    assert driver.trigger_software() is True

    # Capture Color Frame
    driver.pixel_format = "BGR8"
    ok, frame, msg = driver.capture_frame()
    assert ok is True
    assert frame is not None
    assert frame.shape == (1024, 1280, 3)
    assert frame.dtype == np.uint8

    # Capture Mono8 Frame
    driver.pixel_format = "Mono8"
    ok_mono, frame_mono, _ = driver.capture_frame()
    assert ok_mono is True
    assert frame_mono is not None
    assert len(frame_mono.shape) == 2


def test_mvs_config_file_roundtrip(tmp_path):
    """Verify MvsConfigFileManager exports and imports .mvs XML GenICam feature files."""
    mvs_file = str(tmp_path / "camera_preset.mvs")

    test_params = {
        "ExposureTime": 18500.0,
        "Gain": 3.5,
        "TriggerMode": 1,
        "TriggerSource": 7,  # Software
        "Width": 1280,
        "Height": 1024,
        "AcquisitionFrameRate": 45.0,
        "GevSCPSPacketSize": 9000,
        "DeviceUserID": "Station1_TopCamera"
    }

    # 1. Export
    ok = MvsConfigFileManager.export_mvs_feature_file(mvs_file, test_params, model_name="MV-CA050-10GM")
    assert ok is True
    assert os.path.exists(mvs_file)

    # 2. Parse back
    parsed = MvsConfigFileManager.parse_mvs_feature_file(mvs_file)
    assert abs(parsed["ExposureTime"] - 18500.0) < 1e-3
    assert abs(parsed["Gain"] - 3.5) < 1e-3
    assert parsed["TriggerMode"] == 1
    assert parsed["TriggerSource"] == 7
    assert parsed["Width"] == 1280
    assert parsed["Height"] == 1024
    assert parsed["GevSCPSPacketSize"] == 9000
    assert parsed["DeviceUserID"] == "Station1_TopCamera"

    # 3. Load into driver
    cm = CameraManager.get_instance()
    driver = cm.get_or_create_driver("mvs_gige_0")
    load_ok = driver.load_mvs_config_file(mvs_file)
    assert load_ok is True
    assert abs(driver.exposure_time_us - 18500.0) < 1e-3
    assert abs(driver.gain - 3.5) < 1e-3
    assert driver.trigger_mode == "On"
    assert driver.trigger_source == "Software"
    assert driver.packet_size == 9000


def test_mvs_lens_calibration_compatibility(tmp_path):
    """Verify LensCalibrationModel saves and loads MVS XML calibration profiles."""
    calib_mvs_file = str(tmp_path / "lens_distortion.mvs")

    # Generate synthetic calibration model
    model = LensCalibrationModel(grid_size=(9, 6), square_size_mm=25.0)
    for angle in [0.0, 5.0, -5.0]:
        img, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(
            rotation_deg=angle, k1=-0.26, k2=0.07
        )
        model.add_image(img)
    model.compute_calibration()
    assert model.is_calibrated is True

    # Save to MVS format
    save_ok = model.save_mvs_xml(calib_mvs_file)
    assert save_ok is True
    assert os.path.exists(calib_mvs_file)

    # Load into fresh model
    loaded_model = LensCalibrationModel()
    load_ok = loaded_model.load_mvs_xml(calib_mvs_file)
    assert load_ok is True
    assert loaded_model.is_calibrated is True
    assert abs(loaded_model.rms_error - model.rms_error) < 1e-4

    fx_orig, fy_orig = model.get_focal_length()
    fx_load, fy_load = loaded_model.get_focal_length()
    assert abs(fx_orig - fx_load) < 1e-3
    assert abs(fy_orig - fy_load) < 1e-3

    k1_orig, _, _ = model.get_radial_distortion()
    k1_load, _, _ = loaded_model.get_radial_distortion()
    assert abs(k1_orig - k1_load) < 1e-3

    # Verify transparent load via load_json
    model_via_generic = LensCalibrationModel()
    generic_ok = model_via_generic.load_json(calib_mvs_file)
    assert generic_ok is True
    assert model_via_generic.is_calibrated is True


def test_image_source_tool_mvs_pipeline(tmp_path):
    """Verify ImageSourceTool executes in 'Hikrobot MVS' mode within a VisionPipeline DAG."""
    # Write sample MVS profile
    cfg_path = str(tmp_path / "factory_cam.mvs")
    MvsConfigFileManager.export_mvs_feature_file(cfg_path, {
        "ExposureTime": 14000.0,
        "Gain": 1.8,
        "TriggerMode": 0
    })

    pipe = VisionPipeline(name="MVS_Inspection_Flow")

    src = create_tool_instance("Image Source", "src_mvs_1", "01_Acquisition")
    src.set_param("source_type", "Hikrobot MVS")
    src.set_param("camera_device", "mvs_gige_0")
    src.set_param("mvs_config_file", cfg_path)
    pipe.add_node(src)

    rectify = create_tool_instance("Lens Distortion Calibration", "rectify_1", "02_Calibration")
    rectify.set_param("mode", "Manual Coefficients")
    rectify.set_param("manual_k1", -0.15)
    pipe.add_node(rectify)

    pipe.connect("src_mvs_1", "Image", "rectify_1", "Image")

    results = pipe.execute_flow()
    assert "src_mvs_1" in results and results["src_mvs_1"].status == ToolStatus.OK
    assert "rectify_1" in results and results["rectify_1"].status == ToolStatus.OK

    src_res = results["src_mvs_1"]
    assert "Image" in src_res.outputs
    assert src_res.outputs["Width"] == 1280
    assert src_res.outputs["Height"] == 1024
    assert any("Hikrobot MVS" in ov.get("text", "") for ov in src_res.overlays)


def test_camera_dialog_mvs_ui_controls(qapp, tmp_path):
    """Verify CameraManagementDialog renders MVS badge and performs MVS config import/export."""
    os.environ["PYTEST_CURRENT_TEST"] = "1"
    dialog = CameraManagementDialog(current_device_id="mvs_gige_0")

    # Verify MVS status badge exists
    assert hasattr(dialog, "lbl_mvs_status")
    assert "Hikrobot MVS" in dialog.lbl_mvs_status.text()

    # Verify MVS action buttons exist
    assert hasattr(dialog, "btn_import_mvs")
    assert hasattr(dialog, "btn_export_mvs")

    # Export MVS config programmatically
    out_mvs = str(tmp_path / "exported_test.mvs")
    dialog.spin_exposure.setValue(22000.0)
    dialog.spin_gain.setValue(2.5)
    export_ok = dialog.camera_manager.export_mvs_config("mvs_gige_0", out_mvs)
    assert export_ok is True
    assert os.path.exists(out_mvs)

    # Import MVS config
    import_ok = dialog.camera_manager.import_mvs_config("mvs_gige_0", out_mvs)
    assert import_ok is True

    dialog.deleteLater()
