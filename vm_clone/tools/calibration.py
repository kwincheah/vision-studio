"""
Calibration & Coordinate Transformation Tools.
Implements:
- N-Point Calibration (Affine / Homography transformation from Pixel coordinates (u, v) to World/Robot coordinates (X, Y) in mm)
- Camera Calibration / Distortion Correction (Pinhole camera model undistortion)
"""
import cv2
import numpy as np
from typing import Dict, Any, List
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class NPointCalibrationTool(VisionToolBase):
    category = "Calibration"
    tool_name = "N-Point Calibration"
    description = "Calibrates camera pixel coordinates to real-world/robot coordinates (mm) using N-Point pairs."

    def _init_ports(self):
        self.inputs["Pixel_X"] = ToolPort("Pixel_X", DataType.VALUE, "Input pixel X coordinate")
        self.inputs["Pixel_Y"] = ToolPort("Pixel_Y", DataType.VALUE, "Input pixel Y coordinate")
        self.outputs["World_X"] = ToolPort("World_X", DataType.VALUE, "Calibrated World X (mm)")
        self.outputs["World_Y"] = ToolPort("World_Y", DataType.VALUE, "Calibrated World Y (mm)")
        self.outputs["Scale_X"] = ToolPort("Scale_X", DataType.VALUE, "Horizontal scale (mm/pixel)")
        self.outputs["Scale_Y"] = ToolPort("Scale_Y", DataType.VALUE, "Vertical scale (mm/pixel)")

    def _init_parameters(self):
        self.parameters = {
            "calibration_mode": "9-Point Affine",  # 4-Point Homography, 9-Point Affine, 2-Point Scaling
            # Default 9-point grid: (u, v) -> (X_mm, Y_mm)
            "pixel_points": [
                [100, 100], [400, 100], [700, 100],
                [100, 300], [400, 300], [700, 300],
                [100, 500], [400, 500], [700, 500]
            ],
            "world_points": [
                [10.0, 10.0], [40.0, 10.0], [70.0, 10.0],
                [10.0, 30.0], [40.0, 30.0], [70.0, 30.0],
                [10.0, 50.0], [40.0, 50.0], [70.0, 50.0]
            ]
        }
        self.transform_matrix = None
        self._compute_transform()

    def _compute_transform(self):
        try:
            pts_pix = np.array(self.get_param("pixel_points", []), dtype=np.float32)
            pts_world = np.array(self.get_param("world_points", []), dtype=np.float32)

            if pts_pix.ndim == 2 and pts_world.ndim == 2 and len(pts_pix) >= 3 and len(pts_world) >= 3 and len(pts_pix) == len(pts_world):
                matrix, inliers = cv2.estimateAffine2D(pts_pix, pts_world)
                self.transform_matrix = matrix
            else:
                self.transform_matrix = None
        except Exception:
            self.transform_matrix = None

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        self._compute_transform()

        raw_px = context.get("Pixel_X", 400.0)
        raw_py = context.get("Pixel_Y", 300.0)
        try:
            px = float(raw_px) if raw_px is not None else 400.0
        except (ValueError, TypeError):
            px = 400.0
        try:
            py = float(raw_py) if raw_py is not None else 300.0
        except (ValueError, TypeError):
            py = 300.0

        if self.transform_matrix is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="Calibration matrix computation failed")

        pt_vec = np.array([[px, py]], dtype=np.float32)
        transformed = cv2.transform(pt_vec.reshape(-1, 1, 2), self.transform_matrix).reshape(-1, 2)
        wx = float(transformed[0][0])
        wy = float(transformed[0][1])

        # Calculate local pixel scales
        scale_x = float(np.hypot(self.transform_matrix[0, 0], self.transform_matrix[0, 1]))
        scale_y = float(np.hypot(self.transform_matrix[1, 0], self.transform_matrix[1, 1]))

        overlays = [
            {"type": "cross", "pt": (int(px), int(py)), "size": 10, "color": (255, 0, 255)},
            {"type": "text", "text": f"World: ({wx:.2f}mm, {wy:.2f}mm)", "pt": (int(px) + 12, int(py) - 10), "color": (255, 0, 255)}
        ]

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Pixel ({px:.1f}, {py:.1f}) -> World ({wx:.3f} mm, {wy:.3f} mm)",
            outputs={
                "World_X": wx,
                "World_Y": wy,
                "Scale_X": scale_x,
                "Scale_Y": scale_y
            },
            overlays=overlays
        )


@register_tool
class CameraCalibrationTool(VisionToolBase):
    category = "Calibration"
    tool_name = "Lens Distortion Calibration"
    description = "Rectifies camera lens optical distortion (barrel/pincushion) using calibrated camera matrix and coefficients."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Raw distorted input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Undistorted rectified image")
        self.outputs["RMS_Error"] = ToolPort("RMS_Error", DataType.VALUE, "Reprojection RMS error (px)")
        self.outputs["Focal_Length_X"] = ToolPort("Focal_Length_X", DataType.VALUE, "Focal length fx (px)")
        self.outputs["Focal_Length_Y"] = ToolPort("Focal_Length_Y", DataType.VALUE, "Focal length fy (px)")
        self.outputs["Principal_X"] = ToolPort("Principal_X", DataType.VALUE, "Optical center cx (px)")
        self.outputs["Principal_Y"] = ToolPort("Principal_Y", DataType.VALUE, "Optical center cy (px)")
        self.outputs["Dist_K1"] = ToolPort("Dist_K1", DataType.VALUE, "Radial distortion k1")
        self.outputs["Dist_K2"] = ToolPort("Dist_K2", DataType.VALUE, "Radial distortion k2")

    def _init_parameters(self):
        self.parameters = {
            "mode": "Manual Coefficients",  # Profile File, Manual Coefficients, Live Chessboard
            "calibration_file": "",
            "alpha": 0.0,  # 0.0 = crop black borders, 1.0 = retain all valid pixels
            "manual_fx": 650.0,
            "manual_fy": 650.0,
            "manual_cx": 400.0,
            "manual_cy": 300.0,
            "manual_k1": -0.20,
            "manual_k2": 0.05,
            "manual_p1": 0.0,
            "manual_p2": 0.0,
            "show_overlay": True
        }
        from vm_clone.core.lens_calibration import LensCalibrationModel
        self._model = LensCalibrationModel()
        self._last_loaded_file = ""

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        from vm_clone.core.lens_calibration import LensCalibrationModel

        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(
                status=ToolStatus.NG,
                message="No valid input image provided for lens distortion calibration."
            )

        h, w = img.shape[:2]
        mode = self.get_param("mode", "Manual Coefficients")
        alpha = float(self.get_param("alpha", 0.0))
        show_overlay = bool(self.get_param("show_overlay", True))

        if mode == "Profile File":
            calib_file = str(self.get_param("calibration_file", "")).strip().strip('"')
            if calib_file and os.path.exists(calib_file):
                if calib_file != self._last_loaded_file or not self._model.is_calibrated:
                    loaded = self._model.load_json(calib_file)
                    if loaded:
                        self._last_loaded_file = calib_file
                    else:
                        return ToolExecutionResult(
                            status=ToolStatus.NG,
                            message=f"Failed to parse calibration profile: '{calib_file}'"
                        )
            else:
                # Fall back to manual if no file specified
                mode = "Manual Coefficients"

        if mode == "Live Chessboard":
            # Attempt inline single-frame calibration
            temp_model = LensCalibrationModel(image_size=(w, h))
            ok, msg, _ = temp_model.add_image(img, "Live Frame")
            if ok:
                success, rms, c_msg = temp_model.compute_calibration()
                if success:
                    self._model = temp_model

        if mode == "Manual Coefficients" or not self._model.is_calibrated:
            fx = float(self.get_param("manual_fx", w * 0.85))
            fy = float(self.get_param("manual_fy", w * 0.85))
            cx = float(self.get_param("manual_cx", w / 2.0))
            cy = float(self.get_param("manual_cy", h / 2.0))
            k1 = float(self.get_param("manual_k1", -0.15))
            k2 = float(self.get_param("manual_k2", 0.03))
            p1 = float(self.get_param("manual_p1", 0.0))
            p2 = float(self.get_param("manual_p2", 0.0))

            K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1.0]], dtype=np.float64)
            D = np.array([k1, k2, p1, p2, 0.0], dtype=np.float64)
            self._model = LensCalibrationModel(
                camera_matrix=K,
                dist_coeffs=D,
                image_size=(w, h),
                rms_error=0.0
            )

        # Execute undistortion
        undistorted = self._model.undistort(img, alpha=alpha)

        fx, fy = self._model.get_focal_length()
        cx, cy = self._model.get_principal_point()
        k1, k2, _ = self._model.get_radial_distortion()

        overlays = []
        if show_overlay:
            overlays.append({
                "type": "cross",
                "pt": (int(cx), int(cy)),
                "size": 14,
                "color": (14, 165, 233)
            })
            overlays.append({
                "type": "text",
                "text": f"Optical Center ({cx:.1f}, {cy:.1f}) | k1={k1:.3f}",
                "pt": (int(cx) + 10, int(cy) - 8),
                "color": (14, 165, 233)
            })

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Lens rectified ({w}x{h}). Focal: ({fx:.1f}, {fy:.1f}), Center: ({cx:.1f}, {cy:.1f}), k1: {k1:.4f}",
            outputs={
                "Image": undistorted,
                "RMS_Error": self._model.rms_error,
                "Focal_Length_X": fx,
                "Focal_Length_Y": fy,
                "Principal_X": cx,
                "Principal_Y": cy,
                "Dist_K1": k1,
                "Dist_K2": k2
            },
            overlays=overlays
        )
