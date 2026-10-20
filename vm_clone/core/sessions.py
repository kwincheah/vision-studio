"""Front-end independent sessions for the calibration and camera tools.

Like ``vm_clone.core.controller`` these hold everything a wizard or dialog needs, with no widget
and no QML, so any user interface can drive them.

* :func:`apply_lens_calibration` - write a computed calibration into the flow.
* :class:`LensSession`           - calibration views, pattern settings, solving, previews, profiles.
* :class:`CameraSession`         - device list, parameters and a threaded live preview.
"""
import os
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from vm_clone.core.imageio import imread


# =============================================================================
# Lens calibration
# =============================================================================
def apply_lens_calibration(pipeline, calib_data: Dict[str, Any]):
    """Write a computed calibration into the flow's Lens Distortion Calibration module.

    The module is created and wired to the Image Source when the flow has none. Returns it."""
    from vm_clone.core.registry import create_tool_instance, new_instance_id
    node = next((n for n in pipeline.nodes.values()
                 if n.tool_name == "Lens Distortion Calibration"), None)
    if node is None:
        node = create_tool_instance("Lens Distortion Calibration", new_instance_id("lens_calib"),
                                    "LensDistortionCorrection")
        pipeline.add_node(node)
        src = next((n for n in pipeline.nodes.values() if n.tool_name == "Image Source"), None)
        if src is not None:
            pipeline.connect(src.instance_id, "Image", node.instance_id, "Image", force=True)
    intr, dist = calib_data.get("intrinsics", {}), calib_data.get("distortion", {})
    node.set_param("mode", "Manual Coefficients")
    for key, source, name, default in (("manual_fx", intr, "fx", 650.0), ("manual_fy", intr, "fy", 650.0),
                                       ("manual_cx", intr, "cx", 400.0), ("manual_cy", intr, "cy", 300.0),
                                       ("manual_k1", dist, "k1", -0.15), ("manual_k2", dist, "k2", 0.03),
                                       ("manual_p1", dist, "p1", 0.0), ("manual_p2", dist, "p2", 0.0)):
        node.set_param(key, source.get(name, default))
    return node


class LensSession:
    """Calibration views, pattern settings and the computed model."""

    SYNTHETIC_ANGLES = (0.0, 5.0, -5.0, 8.0, -8.0)
    PREVIEW_MODES = ("Detected Corners", "Distorted (Raw)", "Undistorted (Rectified)")
    PATTERNS = ("Chessboard", "Circles Grid", "Asymmetric Circles")

    def __init__(self) -> None:
        from vm_clone.core.lens_calibration import LensCalibrationModel
        self.model = LensCalibrationModel()
        self.views: List[Dict[str, Any]] = []        # {"name", "ok", "corners", "image", "annotated"}
        self.pattern = "Chessboard"
        self.cols, self.rows, self.square_mm = 9, 6, 25.0
        self._synthetic_count = 0

    # -- views -----------------------------------------------------------
    def add_image(self, image: np.ndarray, name: str) -> Tuple[bool, str]:
        ok, message, annotated = self.model.add_image(
            image, name=name, pattern_type=self.pattern, grid_size=(self.cols, self.rows),
            square_size_mm=self.square_mm)
        corners = len(self.model.image_points_list[-1]) if ok else 0
        self.views.append({"name": name, "ok": ok, "corners": corners,
                           "image": image, "annotated": annotated})
        return ok, message

    def add_files(self, paths: Sequence[str]) -> int:
        added = 0
        for path in paths:
            img = imread(path)
            if img is not None:
                self.add_image(img, os.path.basename(path))
                added += 1
        return added

    def add_synthetic(self, angle: Optional[float] = None) -> Tuple[bool, str]:
        from vm_clone.core.lens_calibration import LensCalibrationModel
        if angle is None:
            angle = self.SYNTHETIC_ANGLES[self._synthetic_count % len(self.SYNTHETIC_ANGLES)]
            self._synthetic_count += 1
        distorted, _ideal, _meta = LensCalibrationModel.generate_synthetic_distorted_chessboard(
            width=800, height=600, grid_size=(self.cols, self.rows), square_size_px=45,
            k1=-0.28, k2=0.08, rotation_deg=angle)
        return self.add_image(distorted, f"Synthetic View {len(self.views) + 1} ({angle:+.0f} deg)")

    def remove(self, row: int) -> None:
        if not (0 <= row < len(self.views)):
            return
        view = self.views.pop(row)
        if view["ok"]:
            # the model keeps points only for the views that were detected, in order
            index = sum(1 for v in self.views[:row] if v["ok"])
            del self.model.object_points_list[index]
            del self.model.image_points_list[index]
            del self.model.calibration_images[index]

    def clear(self) -> None:
        from vm_clone.core.lens_calibration import LensCalibrationModel
        self.model = LensCalibrationModel()
        self.views.clear()

    # -- solving ---------------------------------------------------------
    def compute(self) -> Tuple[bool, str]:
        ok, _rms, message = self.model.compute_calibration()
        return ok, message

    @property
    def calibrated(self) -> bool:
        return bool(self.model.is_calibrated)

    def result(self) -> Dict[str, Any]:
        m = self.model
        fx, fy = m.get_focal_length()
        cx, cy = m.get_principal_point()
        k1, k2, k3 = m.get_radial_distortion()
        p1, p2 = m.get_tangential_distortion()
        return {"calibrated": self.calibrated, "rms": float(m.rms_error),
                "valid_views": len(m.object_points_list), "fx": fx, "fy": fy, "cx": cx, "cy": cy,
                "k1": k1, "k2": k2, "k3": k3, "p1": p1, "p2": p2}

    def preview(self, row: int, mode: str = "Detected Corners") -> Optional[np.ndarray]:
        if not (0 <= row < len(self.views)):
            return None
        view = self.views[row]
        if mode == "Undistorted (Rectified)" and self.calibrated:
            return self.model.undistort(view["image"])
        if mode == "Distorted (Raw)":
            return view["image"]
        return view["annotated"] if view["annotated"] is not None else view["image"]

    # -- profiles --------------------------------------------------------
    def save(self, path: str) -> None:
        self.model.save_json(path)

    def load(self, path: str) -> bool:
        return bool(self.model.load_json(path))


# =============================================================================
# Camera session
# =============================================================================
class CameraSession(QObject):
    """Device list, parameters and a live preview for one camera at a time.

    Frames are captured on a worker thread and delivered through ``frame`` on the owner's thread,
    so a slow camera never freezes the interface."""

    frame = pyqtSignal(object)
    status = pyqtSignal(str)
    _tick = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.manager = None
        self.driver = None
        self.device_id = ""
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._latest: Optional[np.ndarray] = None
        self._tick.connect(self._deliver)

    def _mgr(self):
        if self.manager is None:
            from vm_clone.core.camera_manager import CameraManager
            self.manager = CameraManager.get_instance()
        return self.manager

    def devices(self, refresh: bool = False) -> List[Dict[str, str]]:
        mgr = self._mgr()
        infos = mgr.refresh_devices() if refresh else mgr.list_devices()
        return [{"id": d.device_id, "name": d.name, "type": d.camera_type,
                 "serial": d.serial_number, "iface": d.interface_name} for d in infos]

    def sdk_status(self) -> str:
        mgr = self._mgr()
        return mgr.get_mvs_sdk_version() if mgr.is_mvs_sdk_active() else "not installed (emulated mode)"

    def select(self, device_id: str) -> bool:
        self.stop_preview()
        self.driver = self._mgr().get_or_create_driver(device_id)
        self.device_id = device_id if self.driver is not None else ""
        return self.driver is not None

    def apply(self, exposure_us: float, gain: float, trigger: str, pixel_format: str) -> None:
        if self.driver is None:
            return
        self.driver.set_exposure(exposure_us)
        self.driver.set_gain(gain)
        self.driver.set_trigger_mode(trigger)
        self.driver.pixel_format = "Mono8" if "Mono" in pixel_format else "BGR8"

    def start_preview(self) -> bool:
        if self.driver is None:
            return False
        if self._running:
            return True
        self._running = True

        def work():
            while self._running:
                ok, frame, _message = self.driver.capture_frame(timeout_ms=500.0)
                if ok and frame is not None:
                    self._latest = frame
                    try:
                        self._tick.emit()
                    except RuntimeError:         # the session was destroyed
                        return
                else:
                    time.sleep(0.05)

        self._thread = threading.Thread(target=work, name="camera-preview", daemon=True)
        self._thread.start()
        self.status.emit(f"Streaming from {self.driver.device_info.name}...")
        return True

    def stop_preview(self) -> None:
        self._running = False
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.5)

    def _deliver(self) -> None:
        frame, self._latest = self._latest, None
        if frame is not None:
            self.frame.emit(frame)

    def capture_once(self) -> Optional[np.ndarray]:
        if self.driver is None:
            return None
        ok, frame, _message = self.driver.capture_frame(timeout_ms=1000.0)
        return frame if ok else None
