"""
Camera Lens Distortion Calibration Engine.
Provides industrial-grade pinhole camera calibration:
- Pinhole camera intrinsic parameters estimation (fx, fy, cx, cy)
- Lens radial distortion (k1, k2, k3) and tangential distortion (p1, p2)
- Chessboard, symmetric circle grid, and asymmetric circle grid pattern detectors
- Subpixel corner refinement
- High-performance distortion rectification (cv2.undistort / cv2.remap)
- Calibration file import/export (.calib.json)
- Realistic synthetic distorted target generator for testing without physical hardware
"""
import os
import json
import xml.etree.ElementTree as ET
import cv2
import numpy as np
from typing import Dict, Any, List, Tuple, Optional


class LensCalibrationModel:
    """Represents a calibrated camera lens distortion model."""

    def __init__(
        self,
        camera_matrix: Optional[np.ndarray] = None,
        dist_coeffs: Optional[np.ndarray] = None,
        image_size: Tuple[int, int] = (800, 600),
        rms_error: float = 0.0,
        pattern_type: str = "Chessboard",
        grid_size: Tuple[int, int] = (9, 6),
        square_size_mm: float = 25.0
    ):
        self.camera_matrix: np.ndarray = (
            np.array(camera_matrix, dtype=np.float64)
            if camera_matrix is not None
            else np.eye(3, dtype=np.float64)
        )
        self.dist_coeffs: np.ndarray = (
            np.array(dist_coeffs, dtype=np.float64).reshape(-1)
            if dist_coeffs is not None
            else np.zeros(5, dtype=np.float64)
        )
        self.image_size: Tuple[int, int] = tuple(image_size)
        self.rms_error: float = float(rms_error)
        self.pattern_type: str = pattern_type
        self.grid_size: Tuple[int, int] = tuple(grid_size)
        self.square_size_mm: float = float(square_size_mm)

        # Captured calibration frames: list of (objpoints, imgpoints, img_bgr)
        self.object_points_list: List[np.ndarray] = []
        self.image_points_list: List[np.ndarray] = []
        self.calibration_images: List[Dict[str, Any]] = []

        # Precomputed remap caches
        self._cached_mapx: Optional[np.ndarray] = None
        self._cached_mapy: Optional[np.ndarray] = None
        self._cached_alpha: float = -1.0

    @property
    def is_calibrated(self) -> bool:
        """True if camera matrix contains calibrated focal lengths and non-zero dimensions."""
        if self.camera_matrix is None or self.dist_coeffs is None:
            return False
        fx = self.camera_matrix[0, 0]
        fy = self.camera_matrix[1, 1]
        return fx > 1.0 and fy > 1.0 and (self.rms_error > 0.0 or np.any(self.dist_coeffs != 0))

    def get_focal_length(self) -> Tuple[float, float]:
        """Returns (fx, fy) in pixels."""
        return float(self.camera_matrix[0, 0]), float(self.camera_matrix[1, 1])

    def get_principal_point(self) -> Tuple[float, float]:
        """Returns (cx, cy) optical center in pixels."""
        return float(self.camera_matrix[0, 2]), float(self.camera_matrix[1, 2])

    def get_radial_distortion(self) -> Tuple[float, float, float]:
        """Returns (k1, k2, k3)."""
        d = self.dist_coeffs.ravel()
        k1 = float(d[0]) if len(d) > 0 else 0.0
        k2 = float(d[1]) if len(d) > 1 else 0.0
        k3 = float(d[4]) if len(d) > 4 else 0.0
        return k1, k2, k3

    def get_tangential_distortion(self) -> Tuple[float, float]:
        """Returns (p1, p2)."""
        d = self.dist_coeffs.ravel()
        p1 = float(d[2]) if len(d) > 2 else 0.0
        p2 = float(d[3]) if len(d) > 3 else 0.0
        return p1, p2

    def reset(self):
        """Resets captured points and calibration state."""
        self.object_points_list.clear()
        self.image_points_list.clear()
        self.calibration_images.clear()
        self.rms_error = 0.0
        self.camera_matrix = np.eye(3, dtype=np.float64)
        self.dist_coeffs = np.zeros(5, dtype=np.float64)
        self._invalidate_map_cache()

    def _invalidate_map_cache(self):
        self._cached_mapx = None
        self._cached_mapy = None
        self._cached_alpha = -1.0

    @staticmethod
    def detect_pattern(
        image: np.ndarray,
        pattern_type: str = "Chessboard",
        grid_size: Tuple[int, int] = (9, 6)
    ) -> Tuple[bool, Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Detects calibration pattern corners in an image.
        Returns:
            (found, corners_subpix, annotated_image)
        """
        if image is None or image.size == 0:
            return False, None, None

        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            annotated = image.copy()
        else:
            gray = image.copy()
            annotated = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        cols, rows = grid_size
        found = False
        corners = None

        if pattern_type == "Chessboard":
            flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE + cv2.CALIB_CB_FAST_CHECK
            found, raw_corners = cv2.findChessboardCorners(gray, (cols, rows), flags)
            if not found:
                # Retry without fast check for tricky borders
                found, raw_corners = cv2.findChessboardCorners(gray, (cols, rows), cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)
            if found and raw_corners is not None:
                criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
                corners = cv2.cornerSubPix(gray, raw_corners, (11, 11), (-1, -1), criteria)
                cv2.drawChessboardCorners(annotated, (cols, rows), corners, found)

        elif pattern_type == "Circles Grid":
            found, raw_corners = cv2.findCirclesGrid(gray, (cols, rows), cv2.CALIB_CB_SYMMETRIC_GRID)
            if found and raw_corners is not None:
                corners = raw_corners
                cv2.drawChessboardCorners(annotated, (cols, rows), corners, found)

        elif pattern_type == "Asymmetric Circles":
            found, raw_corners = cv2.findCirclesGrid(gray, (cols, rows), cv2.CALIB_CB_ASYMMETRIC_GRID)
            if found and raw_corners is not None:
                corners = raw_corners
                cv2.drawChessboardCorners(annotated, (cols, rows), corners, found)

        return found, corners, annotated

    def add_image(
        self,
        image: np.ndarray,
        name: str = "Frame",
        pattern_type: Optional[str] = None,
        grid_size: Optional[Tuple[int, int]] = None,
        square_size_mm: Optional[float] = None
    ) -> Tuple[bool, str, Optional[np.ndarray]]:
        """
        Detects corners and adds a frame to the calibration set.
        """
        p_type = pattern_type or self.pattern_type
        g_size = grid_size or self.grid_size
        sq_mm = square_size_mm if square_size_mm is not None else self.square_size_mm

        h, w = image.shape[:2]
        self.image_size = (w, h)

        found, corners, annotated = self.detect_pattern(image, p_type, g_size)
        if not found or corners is None:
            return False, f"Could not detect {p_type} pattern with {g_size[0]}x{g_size[1]} corners", annotated

        # Generate 3D real-world coordinates for the planar target (Z=0)
        cols, rows = g_size
        objp = np.zeros((cols * rows, 3), np.float32)
        if p_type == "Asymmetric Circles":
            for i in range(rows):
                for j in range(cols):
                    objp[i * cols + j] = [(2 * j + i % 2) * sq_mm * 0.5, i * sq_mm * 0.5, 0.0]
        else:
            objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * sq_mm

        self.object_points_list.append(objp)
        self.image_points_list.append(corners)

        self.calibration_images.append({
            "name": name,
            "corners_count": len(corners),
            "image": image.copy(),
            "annotated": annotated,
            "corners": corners
        })

        return True, f"Detected {len(corners)} corners successfully", annotated

    def compute_calibration(self) -> Tuple[bool, float, str]:
        """
        Runs OpenCV camera calibration on accumulated points.
        Returns:
            (success, rms_reprojection_error, status_message)
        """
        if len(self.object_points_list) < 1:
            return False, 0.0, "At least 1 valid pattern view is required (>= 3 recommended for optimal accuracy)."

        w, h = self.image_size
        init_K = self.camera_matrix.copy()
        if init_K[0, 0] <= 1.0 or init_K[1, 1] <= 1.0:
            f = float(max(w, h))
            init_K = np.array([[f, 0.0, w / 2.0], [0.0, f, h / 2.0], [0.0, 0.0, 1.0]], dtype=np.float64)

        try:
            flags = cv2.CALIB_USE_INTRINSIC_GUESS
            ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
                self.object_points_list,
                self.image_points_list,
                (w, h),
                init_K,
                None,
                flags=flags
            )
            self.rms_error = float(ret)
            self.camera_matrix = mtx
            self.dist_coeffs = dist.ravel()[:5]  # Standard 5-coeff model (k1, k2, p1, p2, k3)
            self._invalidate_map_cache()
            return True, self.rms_error, f"Calibration converged. RMS error: {self.rms_error:.4f} px across {len(self.object_points_list)} views."
        except Exception as e:
            return False, 0.0, f"OpenCV calibration failed: {str(e)}"

    def undistort(self, image: np.ndarray, alpha: float = 0.0) -> np.ndarray:
        """
        Removes lens distortion from an image using the calibrated model.
        Args:
            image: Input color or grayscale image.
            alpha: Free scaling parameter between 0 (zoom in to retain only valid pixels)
                   and 1 (zoom out to retain all source pixels, leaving black edges).
        """
        if not self.is_calibrated or image is None:
            return image

        h, w = image.shape[:2]
        if (w, h) != self.image_size or self._cached_mapx is None or self._cached_alpha != alpha:
            new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
                self.camera_matrix, self.dist_coeffs, (w, h), alpha, (w, h)
            )
            mapx, mapy = cv2.initUndistortRectifyMap(
                self.camera_matrix, self.dist_coeffs, None, new_camera_matrix, (w, h), 5
            )
            self._cached_mapx = mapx
            self._cached_mapy = mapy
            self._cached_alpha = alpha
            self.image_size = (w, h)

        return cv2.remap(image, self._cached_mapx, self._cached_mapy, cv2.INTER_LINEAR)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes calibration model to dictionary."""
        k1, k2, k3 = self.get_radial_distortion()
        p1, p2 = self.get_tangential_distortion()
        fx, fy = self.get_focal_length()
        cx, cy = self.get_principal_point()
        return {
            "version": "1.0",
            "is_calibrated": bool(self.is_calibrated),
            "rms_error": self.rms_error,
            "image_size": list(self.image_size),
            "camera_matrix": self.camera_matrix.tolist(),
            "dist_coeffs": self.dist_coeffs.tolist(),
            "intrinsics": {
                "fx": fx,
                "fy": fy,
                "cx": cx,
                "cy": cy
            },
            "distortion": {
                "k1": k1,
                "k2": k2,
                "k3": k3,
                "p1": p1,
                "p2": p2
            },
            "pattern_type": self.pattern_type,
            "grid_size": list(self.grid_size),
            "square_size_mm": self.square_size_mm,
            "total_views": len(self.object_points_list)
        }

    def from_dict(self, data: Dict[str, Any]):
        """Deserializes calibration model from dictionary."""
        if "camera_matrix" in data and "dist_coeffs" in data:
            self.camera_matrix = np.array(data["camera_matrix"], dtype=np.float64)
            self.dist_coeffs = np.array(data["dist_coeffs"], dtype=np.float64).ravel()
            self.rms_error = float(data.get("rms_error", 0.0))
            self.image_size = tuple(data.get("image_size", (800, 600)))
            self.pattern_type = data.get("pattern_type", "Chessboard")
            self.grid_size = tuple(data.get("grid_size", (9, 6)))
            self.square_size_mm = float(data.get("square_size_mm", 25.0))
            self._invalidate_map_cache()

    def save_json(self, filepath: str):
        """Saves calibration profile to a JSON file."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def load_json(self, filepath: str) -> bool:
        """Loads calibration profile from a JSON or MVS XML file."""
        if not os.path.exists(filepath):
            return False
        if filepath.lower().endswith((".xml", ".mvs")):
            return self.load_mvs_xml(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.from_dict(data)
            return True
        except Exception:
            return self.load_mvs_xml(filepath)

    def save_mvs_xml(self, filepath: str) -> bool:
        """Saves calibration profile to Hikrobot MVS XML format (*.mvs / *.calib.mvs / *.xml)."""
        root = ET.Element("HikrobotLensCalibration", attrib={
            "FormatVersion": "1.0",
            "Manufacturer": "Hikrobot",
            "Software": "MVS / Vision Master"
        })
        ET.SubElement(root, "RMS_Error").text = f"{self.rms_error:.6f}"
        ET.SubElement(root, "ImageWidth").text = str(self.image_size[0])
        ET.SubElement(root, "ImageHeight").text = str(self.image_size[1])

        fx, fy = self.get_focal_length()
        cx, cy = self.get_principal_point()
        k1, k2, k3 = self.get_radial_distortion()
        p1, p2 = self.get_tangential_distortion()

        intrinsics = ET.SubElement(root, "CameraMatrix")
        ET.SubElement(intrinsics, "fx").text = f"{fx:.6f}"
        ET.SubElement(intrinsics, "fy").text = f"{fy:.6f}"
        ET.SubElement(intrinsics, "cx").text = f"{cx:.6f}"
        ET.SubElement(intrinsics, "cy").text = f"{cy:.6f}"

        dist = ET.SubElement(root, "DistortionCoefficients")
        ET.SubElement(dist, "k1").text = f"{k1:.6f}"
        ET.SubElement(dist, "k2").text = f"{k2:.6f}"
        ET.SubElement(dist, "p1").text = f"{p1:.6f}"
        ET.SubElement(dist, "p2").text = f"{p2:.6f}"
        ET.SubElement(dist, "k3").text = f"{k3:.6f}"

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        tree.write(filepath, encoding="utf-8", xml_declaration=True)
        return True

    def load_mvs_xml(self, filepath: str) -> bool:
        """Loads calibration profile from Hikrobot MVS XML (*.mvs, *.xml)."""
        if not os.path.exists(filepath):
            return False
        try:
            from vm_clone.core.xml_safe import safe_parse_file
            tree = safe_parse_file(filepath)
            root = tree.getroot()

            def get_f(tag: str, default: float = 0.0) -> float:
                el = root.find(f".//{tag}")
                if el is not None and el.text:
                    try:
                        return float(el.text.strip())
                    except ValueError:
                        pass
                return default

            fx = get_f("fx", 800.0)
            fy = get_f("fy", 800.0)
            cx = get_f("cx", 400.0)
            cy = get_f("cy", 300.0)
            k1 = get_f("k1", 0.0)
            k2 = get_f("k2", 0.0)
            p1 = get_f("p1", 0.0)
            p2 = get_f("p2", 0.0)
            k3 = get_f("k3", 0.0)
            rms = get_f("RMS_Error", get_f("rms", 0.0))
            w = int(get_f("ImageWidth", 800))
            h = int(get_f("ImageHeight", 600))

            K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1.0]], dtype=np.float64)
            D = np.array([k1, k2, p1, p2, k3], dtype=np.float64)

            self.camera_matrix = K
            self.dist_coeffs = D
            self.image_size = (w, h)
            self.rms_error = rms
            self._invalidate_map_cache()
            return True
        except Exception:
            return False

    @staticmethod
    def generate_synthetic_distorted_chessboard(
        width: int = 800,
        height: int = 600,
        grid_size: Tuple[int, int] = (9, 6),
        square_size_px: int = 44,
        k1: float = -0.32,
        k2: float = 0.10,
        p1: float = 0.0005,
        p2: float = -0.0005,
        rotation_deg: float = 0.0,
        noise_level: float = 0.0
    ) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
        """
        Synthesizes an ideal chessboard and projects optical barrel/pincushion distortion.
        Returns:
            (distorted_bgr, ideal_bgr, ground_truth_meta)
        """
        cols, rows = grid_size
        img = np.ones((height, width, 3), dtype=np.uint8) * 245

        total_w = (cols + 1) * square_size_px
        total_h = (rows + 1) * square_size_px
        start_x = max(10, (width - total_w) // 2)
        start_y = max(10, (height - total_h) // 2)

        # Draw clean high-contrast checkerboard
        for r in range(rows + 1):
            for c in range(cols + 1):
                if (r + c) % 2 == 1:
                    x0 = start_x + c * square_size_px
                    y0 = start_y + r * square_size_px
                    cv2.rectangle(img, (x0, y0), (x0 + square_size_px, y0 + square_size_px), (25, 25, 25), -1)

        # Rotation if requested
        if abs(rotation_deg) > 0.01:
            m_rot = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), rotation_deg, 1.0)
            img = cv2.warpAffine(img, m_rot, (width, height), borderValue=(245, 245, 245))

        ideal = img.copy()

        # Camera matrix
        fx = fy = float(max(width, height) * 0.95)
        cx = width / 2.0
        cy = height / 2.0
        K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1.0]], dtype=np.float64)
        D = np.array([k1, k2, p1, p2, 0.0], dtype=np.float64)

        # Remap forward distortion
        mapx, mapy = cv2.initUndistortRectifyMap(K, D, None, K, (width, height), 5)
        distorted = cv2.remap(ideal, mapx, mapy, cv2.INTER_LINEAR, borderValue=(245, 245, 245))

        if noise_level > 0.0:
            noise = np.random.normal(0, noise_level, distorted.shape).astype(np.int16)
            distorted = np.clip(distorted.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        meta = {
            "K": K.tolist(),
            "D": D.tolist(),
            "fx": fx,
            "fy": fy,
            "cx": cx,
            "cy": cy,
            "k1": k1,
            "k2": k2,
            "grid_size": list(grid_size)
        }
        return distorted, ideal, meta
