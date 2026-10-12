"""
Script to capture high-resolution screenshot of CameraCalibrationDialog
with synthetic views loaded, pattern corners detected, and solution metrics solved.
"""
import sys
import os
import cv2
import numpy as np

# Ensure root path is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSize
from vm_clone.core.lens_calibration import LensCalibrationModel
from vm_clone.ui.camera_calibration_dialog import CameraCalibrationDialog

def capture_calibration_dialog():
    os.environ["PYTEST_CURRENT_TEST"] = "1"
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    from PyQt6.QtGui import QFont
    app.setFont(QFont("Segoe UI", 9))

    # 1. Generate distorted chessboard views
    distorted_0, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(
        width=800, height=600, grid_size=(9, 6), square_size_px=42, rotation_deg=0.0, k1=-0.28, k2=0.08
    )
    distorted_rot1, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(
        width=800, height=600, grid_size=(9, 6), square_size_px=42, rotation_deg=8.0, k1=-0.28, k2=0.08
    )
    distorted_rot2, _, _ = LensCalibrationModel.generate_synthetic_distorted_chessboard(
        width=800, height=600, grid_size=(9, 6), square_size_px=42, rotation_deg=-7.5, k1=-0.28, k2=0.08
    )

    # 2. Instantiate dialog with the primary view
    dialog = CameraCalibrationDialog(distorted_0)
    dialog.resize(1120, 720)

    # 3. Add additional views to build multi-view pool
    dialog._add_image_frame(distorted_rot1, name="View_Rot_Pos8deg")
    dialog._add_image_frame(distorted_rot2, name="View_Rot_Neg7.5deg")

    # 4. Compute calibration
    dialog._on_compute_calibration()
    dialog.rb_corners.setChecked(True)
    dialog._set_view_mode("Corners")

    # 5. Render dialog to pixmap
    pixmap = dialog.grab()
    
    out_dir = r"C:\Users\winch\.gemini\antigravity\brain\7d3601f0-70b1-4ca6-8295-7780bcda97be"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "camera_lens_calibration_wizard.png")
    pixmap.save(out_path)
    print(f"Saved calibration wizard screenshot to: {out_path}")

if __name__ == "__main__":
    capture_calibration_dialog()
