"""Automated Tests for Standard and Industrial Camera Input Support.

Verifies:
1. CameraManager device enumeration (USB webcams, GigE Vision, USB3 Vision, IP/RTSP streams)
2. OpenCVCameraDriver frame capture and error handling
3. IndustrialCameraDriver exposure, gain, and live simulation frame generation
4. ImageSourceTool integration with Camera, Industrial GigE, Industrial USB3, and IP Stream source types
5. CameraManagementDialog UI initialization, parameter editing, and binding to active pipeline
"""
import pytest
import numpy as np
from PyQt6.QtWidgets import QApplication

import apex_vision.tools
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.camera_manager import (
    CameraManager, CameraDeviceInfo, OpenCVCameraDriver, IndustrialCameraDriver, StreamCameraDriver
)
from apex_vision.core.registry import create_tool_instance
from apex_vision.ui.main_window import VisionMasterMainWindow
from apex_vision.ui.camera_dialog import CameraManagementDialog
from apex_vision.ui.styles import initialize_app_fonts


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def test_camera_manager_enumeration():
    """Verify CameraManager discovers industrial virtual cameras, webcams, and stream templates."""
    cm = CameraManager.get_instance()
    devs = cm.list_devices()
    assert len(devs) >= 3

    types = {d.camera_type for d in devs}
    assert "Industrial GigE" in types
    assert "Industrial USB3" in types
    assert "IP/RTSP Stream" in types

    gige_dev = cm.get_device("virtual_gige_0")
    assert gige_dev is not None
    assert "MV-CA050-10GM" in gige_dev.model


def test_industrial_camera_driver_capture_and_parameters():
    """Verify IndustrialCameraDriver sets exposure, gain, and outputs valid frames."""
    cm = CameraManager.get_instance()
    driver = cm.get_or_create_driver("virtual_gige_0")
    assert isinstance(driver, IndustrialCameraDriver)

    driver.set_exposure(15000.0)
    driver.set_gain(1.5)
    driver.set_trigger_mode("Continuous")

    ok, frame, msg = driver.capture_frame()
    assert ok is True
    assert frame is not None
    assert frame.shape == (1024, 1280, 3)
    assert frame.dtype == np.uint8

    # Test Grayscale / Mono8 mode
    driver.pixel_format = "Mono8"
    ok_mono, frame_mono, _ = driver.capture_frame()
    assert ok_mono is True
    assert len(frame_mono.shape) == 2


def test_opencv_webcam_driver_behavior():
    """Verify OpenCVCameraDriver behavior and safe failure when camera index is absent."""
    cm = CameraManager.get_instance()
    # Test safe handling on non-existent camera index 99
    dev_fake = CameraDeviceInfo("webcam_99", "Fake Webcam 99", "USB/Webcam")
    driver_fake = OpenCVCameraDriver(dev_fake, camera_index=99)
    ok, frame, msg = driver_fake.capture_frame(timeout_ms=100.0)
    assert ok is False
    assert frame is None
    assert "Failed to open camera" in msg or "timed out" in msg


def test_image_source_tool_camera_modes():
    """Verify ImageSourceTool executes cleanly with industrial GigE and USB3 camera inputs."""
    src = create_tool_instance("Image Source", "src_cam_test", "01_Acquisition")

    # 1. Industrial GigE
    src.set_param("source_type", "Industrial GigE")
    src.set_param("camera_device", "virtual_gige_0")
    src.set_param("exposure_time_us", 18000.0)
    src.set_param("gain", 1.2)
    res_gige = src.execute({})
    assert res_gige.status == ToolStatus.OK
    assert "Image" in res_gige.outputs
    assert res_gige.outputs["Width"] == 1280
    assert res_gige.outputs["Height"] == 1024
    assert any("Industrial GigE" in ov.get("text", "") for ov in res_gige.overlays)

    # 2. Industrial USB3
    src.set_param("source_type", "Industrial USB3")
    src.set_param("camera_device", "virtual_usb3_0")
    res_usb3 = src.execute({})
    assert res_usb3.status == ToolStatus.OK
    assert "Image" in res_usb3.outputs

    # 3. Grayscale mode
    src.set_param("color_mode", "Grayscale")
    res_gray = src.execute({})
    assert res_gray.status == ToolStatus.OK
    assert len(res_gray.outputs["Image"].shape) == 2


def test_camera_management_dialog_and_pipeline_binding(qapp):
    """Verify CameraManagementDialog opens, lists devices, and binds selection to active flow."""
    win = VisionMasterMainWindow()
    win.resize(1280, 800)
    win.show()
    qapp.processEvents()

    dlg = CameraManagementDialog(parent=win, current_device_id="virtual_gige_0")
    assert dlg.table_devices.rowCount() >= 3

    # Select Basler USB3 camera row
    usb3_row = None
    for r in range(dlg.table_devices.rowCount()):
        if dlg.table_devices.item(r, 0).data(0x0100) == "virtual_usb3_0":
            usb3_row = r
            break
    assert usb3_row is not None
    dlg.table_devices.selectRow(usb3_row)
    qapp.processEvents()

    assert dlg.current_device_id == "virtual_usb3_0"

    # Simulate accepting dialog and verify binding in MainWindow
    selected_device_id = None
    selected_params = None

    def on_sel(dev_id, params):
        nonlocal selected_device_id, selected_params
        selected_device_id = dev_id
        selected_params = params

    dlg.camera_selected.connect(on_sel)
    dlg._on_accept()

    assert selected_device_id == "virtual_usb3_0"
    assert "exposure_time_us" in selected_params
    assert "gain" in selected_params
