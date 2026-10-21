"""
Camera Lens Distortion Calibration Wizard Dialog.
Provides an interactive multi-view calibration workspace for machine vision cameras:
- Detects planar chessboard and circle grid patterns with subpixel refinement
- Accumulates multi-angle calibration frames
- Computes camera intrinsic matrix and 5-parameter radial/tangential distortion coefficients
- Visualizes detected corner grids and before/after distortion rectification
- Exports/imports calibration profile JSON files
- Direct application to the active inspection pipeline
"""
import os
import cv2
from apex_vision.core.imageio import imread
import numpy as np
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QListWidgetItem,
    QSplitter, QGroupBox, QFormLayout, QFileDialog, QMessageBox,
    QFrame, QRadioButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QColor

from apex_vision.core.sessions import LensSession
from apex_vision.ui.styles import THEME


class CameraCalibrationDialog(QDialog):
    """Interactive camera lens distortion calibration wizard."""

    calibration_applied = pyqtSignal(dict)  # Emits calibration dictionary

    def __init__(self, current_image: Optional[np.ndarray] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera Lens Distortion Calibration Wizard - Apex Studio")
        self.resize(1150, 720)
        self.setMinimumSize(960, 600)

        self.session = LensSession()      # views, solving and previews: shared with the QML front end
        self._current_input_image = current_image.copy() if current_image is not None else None
        self._selected_index = -1
        self._view_mode = "Corners"  # Corners, Original, Undistorted

        self._init_ui()
        self._apply_styling()

        # Seed initial image if available, or generate a synthetic target
        if self._current_input_image is not None:
            self._add_image_frame(self._current_input_image, "Live Camera/Flow Image")
        else:
            self._on_generate_synthetic()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(8)
        root_layout.setContentsMargins(12, 10, 12, 10)

        # ---------------------------------------------------------------------
        # 1. Top Pattern Configuration Bar
        # ---------------------------------------------------------------------
        top_bar = QFrame()
        top_bar.setObjectName("calibTopBar")
        bar_layout = QHBoxLayout(top_bar)
        bar_layout.setContentsMargins(10, 6, 10, 6)
        bar_layout.setSpacing(12)

        lbl_pattern = QLabel("Target Pattern:")
        lbl_pattern.setStyleSheet(f"font-weight: 600; color: {THEME['text_primary']};")
        self.combo_pattern = QComboBox()
        self.combo_pattern.addItems(["Chessboard", "Circles Grid", "Asymmetric Circles"])

        lbl_cols = QLabel("Inner Cols:")
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(3, 30)
        self.spin_cols.setValue(9)

        lbl_rows = QLabel("Inner Rows:")
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(3, 30)
        self.spin_rows.setValue(6)

        lbl_sq = QLabel("Square Size:")
        self.spin_sq = QDoubleSpinBox()
        self.spin_sq.setRange(0.1, 1000.0)
        self.spin_sq.setSingleStep(5.0)
        self.spin_sq.setSuffix(" mm")
        self.spin_sq.setValue(25.0)

        bar_layout.addWidget(lbl_pattern)
        bar_layout.addWidget(self.combo_pattern)
        bar_layout.addWidget(lbl_cols)
        bar_layout.addWidget(self.spin_cols)
        bar_layout.addWidget(lbl_rows)
        bar_layout.addWidget(self.spin_rows)
        bar_layout.addWidget(lbl_sq)
        bar_layout.addWidget(self.spin_sq)
        bar_layout.addStretch()

        root_layout.addWidget(top_bar)

        # ---------------------------------------------------------------------
        # 2. Central Splitter (Left: Frame List | Center: Visualizer | Right: Metrics)
        # ---------------------------------------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # === Left Panel: Image Frames Pool ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        lbl_frames = QLabel("Calibration Views Pool")
        lbl_frames.setStyleSheet(f"font-weight: 600; color: {THEME['text_primary']}; font-size: 12px;")
        left_layout.addWidget(lbl_frames)

        self.list_views = QListWidget()
        self.list_views.currentRowChanged.connect(self._on_view_selection_changed)
        left_layout.addWidget(self.list_views)

        btn_row1 = QHBoxLayout()
        self.btn_add_files = QPushButton("Add Files...")
        self.btn_add_files.clicked.connect(self._on_add_files)
        self.btn_add_live = QPushButton("Capture Live")
        self.btn_add_live.clicked.connect(self._on_capture_live)
        btn_row1.addWidget(self.btn_add_files)
        btn_row1.addWidget(self.btn_add_live)
        left_layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.btn_synth = QPushButton("Generate Synthetic")
        self.btn_synth.clicked.connect(self._on_generate_synthetic)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self._on_remove_view)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self._on_clear_views)
        btn_row2.addWidget(self.btn_synth)
        btn_row2.addWidget(self.btn_remove)
        btn_row2.addWidget(self.btn_clear)
        left_layout.addLayout(btn_row2)

        splitter.addWidget(left_panel)

        # === Center Panel: Image Inspection & View Mode ===
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(4, 0, 4, 0)
        center_layout.setSpacing(6)

        mode_bar = QHBoxLayout()
        mode_bar.addWidget(QLabel("View Mode:"))
        self.rb_corners = QRadioButton("Detected Corners")
        self.rb_corners.setChecked(True)
        self.rb_corners.toggled.connect(lambda: self._set_view_mode("Corners"))
        self.rb_orig = QRadioButton("Distorted (Raw)")
        self.rb_orig.toggled.connect(lambda: self._set_view_mode("Original"))
        self.rb_undistort = QRadioButton("Undistorted (Rectified)")
        self.rb_undistort.toggled.connect(lambda: self._set_view_mode("Undistorted"))

        mode_bar.addWidget(self.rb_corners)
        mode_bar.addWidget(self.rb_orig)
        mode_bar.addWidget(self.rb_undistort)
        mode_bar.addStretch()

        center_layout.addLayout(mode_bar)

        self.lbl_image = QLabel()
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setStyleSheet(f"background-color: {THEME['bg_app']}; border: 1px solid {THEME['vm_card']}; border-radius: 4px;")
        self.lbl_image.setMinimumSize(460, 380)
        self.lbl_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_layout.addWidget(self.lbl_image)

        self.lbl_view_caption = QLabel("Select or add an image to inspect detected pattern corners.")
        self.lbl_view_caption.setStyleSheet(f"color: {THEME['vm_node_text_dim']}; font-size: 12px;")
        center_layout.addWidget(self.lbl_view_caption)

        splitter.addWidget(center_panel)

        # === Right Panel: Calibration Metrics & Solve Actions ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        lbl_results_title = QLabel("Calibration Solution")
        lbl_results_title.setStyleSheet(f"font-weight: 600; color: {THEME['text_primary']}; font-size: 12px;")
        right_layout.addWidget(lbl_results_title)

        self.lbl_status_badge = QLabel("NOT CALIBRATED")
        self.lbl_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status_badge.setStyleSheet(
            "background-color: #fcfcfc; color: #4f565c; font-weight: 600; padding: 6px; border-radius: 3px;"
        )
        right_layout.addWidget(self.lbl_status_badge)

        form_group = QGroupBox("Camera Intrinsics && Distortion")
        form_layout = QFormLayout(form_group)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setSpacing(6)

        self.lbl_rms = QLabel("--")
        self.lbl_views_count = QLabel("0")
        self.lbl_focal = QLabel("--")
        self.lbl_center = QLabel("--")
        self.lbl_radial_k = QLabel("--")
        self.lbl_tangential_p = QLabel("--")

        form_layout.addRow("RMS Error:", self.lbl_rms)
        form_layout.addRow("Valid Views:", self.lbl_views_count)
        form_layout.addRow("Focal Length (fx, fy):", self.lbl_focal)
        form_layout.addRow("Principal Point (cx, cy):", self.lbl_center)
        form_layout.addRow("Radial (k1, k2, k3):", self.lbl_radial_k)
        form_layout.addRow("Tangential (p1, p2):", self.lbl_tangential_p)

        right_layout.addWidget(form_group)

        # Calibration Actions
        self.btn_calibrate = QPushButton("Compute Lens Calibration")
        self.btn_calibrate.setStyleSheet(
            "background-color: #0078b0; color: #1a2024; font-weight: 600; padding: 8px; border-radius: 3px;"
        )
        self.btn_calibrate.clicked.connect(self._on_compute_calibration)
        right_layout.addWidget(self.btn_calibrate)

        self.btn_save = QPushButton("Save Profile (*.calib.json)...")
        self.btn_save.clicked.connect(self._on_save_profile)
        right_layout.addWidget(self.btn_save)

        self.btn_load = QPushButton("Load Profile...")
        self.btn_load.clicked.connect(self._on_load_profile)
        right_layout.addWidget(self.btn_load)

        self.btn_apply = QPushButton("Apply to Active Flow")
        self.btn_apply.setStyleSheet(
            "background-color: #10b981; color: #1a2024; font-weight: 600; padding: 6px; border-radius: 3px;"
        )
        self.btn_apply.clicked.connect(self._on_apply_to_flow)
        right_layout.addWidget(self.btn_apply)

        right_layout.addStretch()
        splitter.addWidget(right_panel)

        splitter.setSizes([220, 560, 270])
        root_layout.addWidget(splitter)

        # ---------------------------------------------------------------------
        # 3. Bottom Close / Help row
        # ---------------------------------------------------------------------
        bottom_bar = QHBoxLayout()
        lbl_hint = QLabel("Tip: 3 to 10 angled chessboard frames produce optimal sub-pixel lens correction.")
        lbl_hint.setStyleSheet(f"color: {THEME['text_muted']}; font-size: 12px;")
        bottom_bar.addWidget(lbl_hint)
        bottom_bar.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)
        root_layout.addLayout(bottom_bar)

    def _apply_styling(self):
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {THEME['vm_chrome']};
                color: {THEME['text_primary']};
            }}
            QFrame#calibTopBar {{
                background-color: {THEME['vm_panel_header']};
                border: 1px solid THEME['bg_control'];
                border-radius: 3px;
            }}
            QGroupBox {{
                background-color: {THEME['vm_panel']};
                border: 1px solid THEME['border_subtle'];
                border-radius: 3px;
                margin-top: 8px;
                padding-top: 8px;
                font-weight: 600;
                color: THEME['text_primary'];
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 4px;
            }}
            QListWidget {{
                background-color: THEME['vm_chrome'];
                border: 1px solid THEME['bg_control'];
                color: THEME['text_primary'];
                font-size: 12px;
                border-radius: {THEME['r_control']}px;
            }}
            QListWidget::item {{
                padding: 4px 6px;
                border-bottom: 1px solid THEME['bg_surface_alt'];
            }}
            QListWidget::item:selected {{
                background-color: {THEME['vm_accent_dim']};
                color: THEME['text_primary'];
            }}
            QPushButton {{
                background-color: THEME['vm_rail_hover'];
                color: THEME['text_primary'];
                border: 1px solid THEME['border_control'];
                padding: 4px 8px;
                border-radius: {THEME['r_control']}px;
            }}
            QPushButton:hover {{
                background-color: THEME['border_control'];
                border-color: THEME['text_secondary'];
            }}
            QComboBox, QSpinBox, QDoubleSpinBox {{
                background-color: THEME['bg_header'];
                border: 1px solid THEME['border_control'];
                color: THEME['text_primary'];
                padding: 2px 4px;
                border-radius: {THEME['r_control']}px;
            }}
        """)

    @property
    def model(self):
        return self.session.model

    # -------------------------------------------------------------------------
    # Frame Management Actions
    # -------------------------------------------------------------------------
    def _add_image_frame(self, image: np.ndarray, name: str):
        self.session.pattern = self.combo_pattern.currentText()
        self.session.cols, self.session.rows = self.spin_cols.value(), self.spin_rows.value()
        self.session.square_mm = self.spin_sq.value()
        ok, _msg = self.session.add_image(image, name)
        self._append_view_item(ok, name)

    def _append_view_item(self, ok: bool, name: str):
        item = QListWidgetItem()
        if ok:
            item.setText(f"[OK] {name}")
            item.setForeground(QColor("#22c55e"))
        else:
            item.setText(f"[NG] {name}")
            item.setForeground(QColor("#ef4444"))

        self.list_views.addItem(item)
        self.list_views.setCurrentRow(self.list_views.count() - 1)
        self._update_metrics_view()

    def _on_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Calibration Chessboard Images", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif);;All Files (*)"
        )
        for fpath in files:
            img = imread(fpath)
            if img is not None:
                self._add_image_frame(img, os.path.basename(fpath))

    def _on_capture_live(self):
        if self._current_input_image is not None:
            name = f"Captured Frame {self.list_views.count() + 1}"
            self._add_image_frame(self._current_input_image, name)
        else:
            QMessageBox.information(
                self, "Live Capture",
                "No live camera or pipeline image available. Load image files or generate synthetic targets."
            )

    def _on_generate_synthetic(self):
        """Generates synthetic distorted chessboard views at slight perspective angles."""
        self.session.pattern = self.combo_pattern.currentText()
        self.session.cols, self.session.rows = self.spin_cols.value(), self.spin_rows.value()
        self.session.square_mm = self.spin_sq.value()
        ok, _msg = self.session.add_synthetic()
        self._append_view_item(ok, self.session.views[-1]["name"])

    def _on_remove_view(self):
        row = self.list_views.currentRow()
        if 0 <= row < len(self.session.views):
            self.session.remove(row)               # keeps the model's point lists in step with NG views
            self.list_views.takeItem(row)
            self._update_metrics_view()
            self._refresh_display()

    def _on_clear_views(self):
        self.session.clear()
        self.list_views.clear()
        self.lbl_image.clear()
        self._update_metrics_view()

    # -------------------------------------------------------------------------
    # Visualization & Display
    # -------------------------------------------------------------------------
    def _on_view_selection_changed(self, row: int):
        self._selected_index = row
        self._refresh_display()

    def _set_view_mode(self, mode: str):
        self._view_mode = mode
        self._refresh_display()

    def _refresh_display(self):
        if 0 <= self._selected_index < len(self.session.views):
            view = self.session.views[self._selected_index]
            mode = {"Corners": "Detected Corners", "Undistorted": "Undistorted (Rectified)"}.get(
                self._view_mode, "Distorted (Raw)")
            disp_img = self.session.preview(self._selected_index, mode)
            raw_img = view["image"]
            self._render_image_to_label(disp_img)
            self.lbl_view_caption.setText(
                f"Inspecting '{view['name']}' ({raw_img.shape[1]}x{raw_img.shape[0]}) | Corners: {view['corners']}"
            )
        else:
            self.lbl_image.clear()
            self.lbl_view_caption.setText("No view selected.")

    def _render_image_to_label(self, cv_img: np.ndarray):
        h, w = cv_img.shape[:2]
        if len(cv_img.shape) == 3:
            rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            bytes_per_line = 3 * w
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        else:
            bytes_per_line = w
            qimg = QImage(cv_img.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)

        pix = QPixmap.fromImage(qimg)
        scaled = pix.scaled(
            self.lbl_image.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.lbl_image.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_display()

    # -------------------------------------------------------------------------
    # Calibration Solve & File Actions
    # -------------------------------------------------------------------------
    def _on_compute_calibration(self):
        if len(self.model.object_points_list) < 1:
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                QMessageBox.warning(
                    self, "Calibration",
                    "Please add at least 1 valid calibration view with detected pattern corners."
                )
            self.lbl_view_caption.setText("Warning: Please add at least 1 valid calibration view.")
            return

        ok, rms, msg = self.model.compute_calibration()
        if ok:
            self.lbl_status_badge.setText(f"CALIBRATED (RMS: {rms:.4f} px)")
            self.lbl_status_badge.setStyleSheet(
                "background-color: #12331f; color: #4ade80; font-weight: 600; padding: 6px; border-radius: 3px;"
            )
            self.lbl_view_caption.setText(f"Calibration successful: {msg}")
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                QMessageBox.information(self, "Calibration Complete", msg)
        else:
            self.lbl_status_badge.setText("CALIBRATION FAILED")
            self.lbl_status_badge.setStyleSheet(
                "background-color: #3b181c; color: #f87171; font-weight: 600; padding: 6px; border-radius: 3px;"
            )
            self.lbl_view_caption.setText(f"Calibration failed: {msg}")
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                QMessageBox.warning(self, "Calibration Error", msg)

        self._update_metrics_view()
        self._refresh_display()

    def _update_metrics_view(self):
        views_count = len(self.model.object_points_list)
        self.lbl_views_count.setText(str(views_count))

        if self.model.is_calibrated:
            fx, fy = self.model.get_focal_length()
            cx, cy = self.model.get_principal_point()
            k1, k2, k3 = self.model.get_radial_distortion()
            p1, p2 = self.model.get_tangential_distortion()

            self.lbl_rms.setText(f"{self.model.rms_error:.4f} px")
            self.lbl_focal.setText(f"fx={fx:.2f}, fy={fy:.2f}")
            self.lbl_center.setText(f"cx={cx:.2f}, cy={cy:.2f}")
            self.lbl_radial_k.setText(f"k1={k1:.4f}, k2={k2:.4f}, k3={k3:.4f}")
            self.lbl_tangential_p.setText(f"p1={p1:.5f}, p2={p2:.5f}")
        else:
            self.lbl_rms.setText("--")
            self.lbl_focal.setText("--")
            self.lbl_center.setText("--")
            self.lbl_radial_k.setText("--")
            self.lbl_tangential_p.setText("--")

    def _on_save_profile(self):
        if not self.model.is_calibrated:
            QMessageBox.warning(self, "Save Profile", "Please compute lens calibration before saving.")
            return

        fpath, _ = QFileDialog.getSaveFileName(
            self, "Save Camera Calibration Profile", "camera_lens.calib.json",
            "Calibration Profile (*.calib.json);;Hikrobot MVS Profile (*.mvs *.xml);;JSON (*.json)"
        )
        if fpath:
            if fpath.lower().endswith((".mvs", ".xml")):
                self.model.save_mvs_xml(fpath)
            else:
                self.model.save_json(fpath)
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                QMessageBox.information(self, "Profile Saved", f"Lens profile saved to:\n{fpath}")

    def _on_load_profile(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Load Camera Calibration Profile", "",
            "All Supported (*.calib.json *.mvs *.xml *.json);;Hikrobot MVS Profile (*.mvs *.xml);;JSON (*.calib.json *.json);;All Files (*)"
        )
        if fpath:
            loaded = self.model.load_json(fpath)
            if loaded:
                self.lbl_status_badge.setText(f"LOADED (RMS: {self.model.rms_error:.4f} px)")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #12331f; color: #4ade80; font-weight: 600; padding: 6px; border-radius: 3px;"
                )
                self._update_metrics_view()
                self._refresh_display()
                QMessageBox.information(self, "Profile Loaded", f"Loaded profile: {os.path.basename(fpath)}")
            else:
                QMessageBox.warning(self, "Load Error", "Failed to parse calibration profile.")

    def _on_apply_to_flow(self):
        if not self.model.is_calibrated:
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                QMessageBox.warning(self, "Apply Calibration", "Compute or load a valid calibration model first.")
            return

        data = self.model.to_dict()
        self.calibration_applied.emit(data)
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            QMessageBox.information(
                self, "Calibration Applied",
                "Lens distortion calibration profile applied to the active inspection pipeline."
            )
        self.accept()
