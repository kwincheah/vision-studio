"""
Acquisition Tools: Image Source, Synthetic Generator, Camera / Video capture.
Matches HikRobot Vision Master Acquisition category.
"""
import os
import cv2
import numpy as np
from typing import Dict, Any, List
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class ImageSourceTool(VisionToolBase):
    category = "Acquisition"
    tool_name = "Image Source"
    description = "Load image from local disk, camera, or synthetic test pattern."

    def _init_ports(self):
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Acquired color or grayscale image")
        self.outputs["Width"] = ToolPort("Width", DataType.VALUE, "Image width")
        self.outputs["Height"] = ToolPort("Height", DataType.VALUE, "Image height")

    def _init_parameters(self):
        default_sample = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "samples", "pcb_sample.png"))
        self.parameters = {
            "source_type": "Synthetic",  # File, Synthetic, Camera, Industrial GigE, Industrial USB3, IP Stream, Hikrobot MVS
            "file_path": default_sample,
            "pattern_type": "PCB Inspection",  # PCB Inspection, Calibration Grid, Circles & Holes, Barcode Sample
            "color_mode": "BGR",  # BGR or Grayscale
            "camera_device": "mvs_gige_0",  # Device ID or Camera name
            "camera_index": 0,  # Legacy USB camera index
            "exposure_time_us": 20000.0,  # Exposure time in microseconds
            "gain": 1.0,  # Camera gain factor
            "trigger_mode": "Continuous",  # Continuous, Software Trigger, Hardware Trigger
            "mvs_config_file": "",  # Hikrobot MVS .mvs or .xml feature profile
            "mvs_trigger_source": "Software",  # Software, Line0, Line1
            "stream_url": "rtsp://192.168.1.64:554/ch1/main"  # For IP/RTSP cameras
        }

    def _generate_synthetic_image(self, pattern: str) -> np.ndarray:
        w, h = 800, 600
        img = np.zeros((h, w, 3), dtype=np.uint8)

        if pattern == "PCB Inspection":
            # Dark green PCB background
            img[:] = (35, 75, 40)
            # Traces
            cv2.line(img, (50, 150), (450, 150), (40, 190, 180), 3)
            cv2.line(img, (450, 150), (550, 250), (40, 190, 180), 3)
            cv2.line(img, (550, 250), (750, 250), (40, 190, 180), 3)
            cv2.line(img, (80, 400), (600, 400), (40, 190, 180), 3)

            # Solder pads / holes
            cv2.circle(img, (150, 150), 18, (60, 215, 230), -1)
            cv2.circle(img, (150, 150), 8, (15, 15, 15), -1)

            cv2.circle(img, (350, 150), 18, (60, 215, 230), -1)
            cv2.circle(img, (350, 150), 8, (15, 15, 15), -1)

            # IC Chip
            cv2.rectangle(img, (260, 240), (440, 360), (30, 30, 30), -1)
            cv2.putText(img, "APEX-VISION", (278, 305), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 2)
            # IC Pins
            for x in range(275, 430, 25):
                cv2.rectangle(img, (x, 225), (x + 12, 240), (180, 180, 180), -1)
                cv2.rectangle(img, (x, 360), (x + 12, 375), (180, 180, 180), -1)

            # Circular mounting hole with high contrast
            cv2.circle(img, (680, 480), 45, (200, 200, 200), 4)
            cv2.circle(img, (680, 480), 35, (10, 10, 10), -1)

            # Text / Serial number
            cv2.putText(img, "SN-APEX-2026-X89", (80, 520), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (240, 240, 240), 2)

        elif pattern == "Calibration Grid":
            img[:] = 230
            for r in range(50, 550, 50):
                for c in range(50, 750, 50):
                    cv2.circle(img, (c, r), 12, (20, 20, 20), -1)

        elif pattern == "Distorted Chessboard":
            from vm_clone.core.lens_calibration import LensCalibrationModel
            dist, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(
                width=w, height=h, grid_size=(9, 6), square_size_px=45, k1=-0.30, k2=0.08
            )
            return dist

        elif pattern == "Circles & Holes":
            img[:] = 45
            centers = [(200, 200, 60), (450, 220, 45), (650, 350, 70), (280, 420, 30)]
            for cx, cy, r in centers:
                cv2.circle(img, (cx, cy), r, (220, 220, 220), -1)
                cv2.circle(img, (cx, cy), int(r * 0.4), (45, 45, 45), -1)

        else:  # Barcode / QR placeholder
            img[:] = 240
            cv2.rectangle(img, (150, 150), (650, 450), (255, 255, 255), -1)
            # Simulated barcode lines
            np.random.seed(42)
            curr_x = 180
            while curr_x < 620:
                bw = np.random.randint(2, 8)
                cv2.rectangle(img, (curr_x, 180), (curr_x + bw, 350), (0, 0, 0), -1)
                curr_x += bw + np.random.randint(2, 6)
            cv2.putText(img, "6901234567890", (280, 400), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        return img

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        src_type = self.get_param("source_type", "Synthetic")
        color_mode = self.get_param("color_mode", "BGR")
        camera_label = ""

        if hasattr(self, "_override_image") and self._override_image is not None:
            img = self._override_image.copy()
            camera_label = getattr(self, "_override_name", "Input Image")
        elif src_type == "File":
            fpath = str(self.get_param("file_path", "")).strip().strip('"').strip("'")
            if not fpath:
                sample_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "samples", "pcb_sample.png"))
                if os.path.exists(sample_path):
                    fpath = sample_path
                    self.set_param("file_path", fpath)
                else:
                    return ToolExecutionResult(
                        status=ToolStatus.NG,
                        message="No file path specified. Click 'Browse...' in Property Inspector to select an image."
                    )

            if not os.path.exists(fpath):
                # Try relative to current working directory
                rel_candidate = os.path.abspath(fpath)
                if os.path.exists(rel_candidate):
                    fpath = rel_candidate
                else:
                    return ToolExecutionResult(
                        status=ToolStatus.NG,
                        message=f"File not found: '{fpath}'. Click 'Browse...' in Property Inspector to select an image file."
                    )

            # Robust image reading (including Windows Unicode / spaces in paths)
            img = None
            try:
                img = cv2.imdecode(np.fromfile(fpath, dtype=np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                img = None

            if img is None:
                img = cv2.imread(fpath)

            if img is None:
                return ToolExecutionResult(
                    status=ToolStatus.NG,
                    message=f"Failed to read image at: {fpath}"
                )
        elif src_type in ("Camera", "Industrial GigE", "Industrial USB3", "IP Stream", "Hikrobot MVS"):
            from vm_clone.core.camera_manager import CameraManager
            cm = CameraManager.get_instance()

            # Determine device ID
            target_device_id = str(self.get_param("camera_device", "")).strip()
            if not target_device_id:
                if src_type == "Hikrobot MVS":
                    target_device_id = "mvs_gige_0"
                elif src_type == "Industrial GigE":
                    target_device_id = "virtual_gige_0"
                elif src_type == "Industrial USB3":
                    target_device_id = "virtual_usb3_0"
                elif src_type == "IP Stream":
                    target_device_id = "ip_stream_custom"
                else:
                    cidx = int(self.get_param("camera_index", 0))
                    target_device_id = f"webcam_{cidx}"

            stream_url = str(self.get_param("stream_url", "")).strip()
            driver = cm.get_or_create_driver(target_device_id, stream_url=stream_url)

            if driver is None:
                # Fallback candidates
                if src_type == "Hikrobot MVS":
                    driver = cm.get_or_create_driver("mvs_gige_0")
                else:
                    cidx = int(self.get_param("camera_index", 0))
                    driver = cm.get_or_create_driver(f"webcam_{cidx}")
                    if driver is None:
                        driver = cm.get_or_create_driver("virtual_gige_0")

            if driver is None:
                return ToolExecutionResult(
                    status=ToolStatus.NG,
                    message=f"No camera driver available for device '{target_device_id}'"
                )

            # Check if an external MVS configuration profile is specified
            mvs_cfg = str(self.get_param("mvs_config_file", "")).strip().strip('"')
            if mvs_cfg and os.path.exists(mvs_cfg) and hasattr(driver, "load_mvs_config_file"):
                driver.load_mvs_config_file(mvs_cfg)

            # Apply exposure and gain settings to driver
            exp_val = float(self.get_param("exposure_time_us", 20000.0))
            gain_val = float(self.get_param("gain", 1.0))
            driver.set_exposure(exp_val)
            driver.set_gain(gain_val)
            driver.set_trigger_mode(str(self.get_param("trigger_mode", "Continuous")))
            if hasattr(driver, "set_trigger_source"):
                driver.set_trigger_source(str(self.get_param("mvs_trigger_source", "Software")))

            ok, img, err_msg = driver.capture_frame(timeout_ms=3000.0)
            if not ok or img is None:
                return ToolExecutionResult(
                    status=ToolStatus.NG,
                    message=f"Camera acquisition failed ({driver.device_info.name}): {err_msg}"
                )
            camera_label = f"[{driver.device_info.camera_type}] {driver.device_info.name}"

        else:  # Synthetic
            pattern = self.get_param("pattern_type", "PCB Inspection")
            img = self._generate_synthetic_image(pattern)

        if color_mode == "Grayscale" and len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        h, w = img.shape[:2]
        desc = camera_label or f"Source: {src_type}"
        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Acquired image {w}x{h} from {desc}",
            outputs={
                "Image": img,
                "Width": w,
                "Height": h
            },
            overlays=[
                {"type": "text", "text": f"{desc} ({w}x{h})", "pt": (15, 25), "color": (0, 255, 0)}
            ]
        )
