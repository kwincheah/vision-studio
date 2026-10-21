"""Camera Management and Device Configuration Dialog for Vision Master Clone.

Implements HikRobot Vision Master Camera Set / Camera Management (Manual Chapter 4).
Provides:
1. Live device discovery across USB Webcams, GigE Vision, USB3 Vision, and IP/RTSP streams
2. Real-time video preview window with live FPS indicator
3. Industrial parameter controls: Exposure (us), Gain, Trigger Mode, Pixel Format
4. Binding selected camera device directly to the active solution's Image Source module.
"""
import os
import time
from typing import Optional
import cv2
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QPushButton, QGroupBox, QFormLayout, QDoubleSpinBox,
    QComboBox, QLineEdit, QMessageBox, QWidget, QDialogButtonBox, QFileDialog,
    QInputDialog
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from apex_vision.core.camera_manager import CameraManager, CameraDriverBase
from apex_vision.ui.styles import THEME


class CameraManagementDialog(QDialog):
    """Dialog for scanning, configuring, previewing, and binding cameras."""

    camera_selected = pyqtSignal(str, dict)  # (device_id, params)

    def __init__(self, parent=None, current_device_id: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Camera Management - Industrial & Hikrobot MVS Cameras")
        self.resize(880, 580)
        self.setMinimumSize(780, 500)

        self.camera_manager = CameraManager.get_instance()
        self.active_driver: Optional[CameraDriverBase] = None
        self.current_device_id = current_device_id

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._on_preview_tick)
        self._fps_counter = 0
        self._fps_start_time = 0.0

        self._init_ui()
        self._populate_devices()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Header description & MVS Status
        hdr_bar = QHBoxLayout()
        header = QLabel(
            "Configure GigE Vision, USB3 Vision, Hikrobot MVS, Webcams, and RTSP Streams.\n"
            "Select a camera to preview live feed and adjust exposure/gain parameters."
        )
        header.setStyleSheet(f"color: {THEME['text_secondary']}; font-size: 12px;")
        hdr_bar.addWidget(header, 1)

        # MVS C SDK Status Badge
        mvs_status_text = f"Hikrobot MVS C SDK: {self.camera_manager.get_mvs_sdk_version()}"
        self.lbl_mvs_status = QLabel(mvs_status_text)
        is_mvs_active = self.camera_manager.is_mvs_sdk_active()
        mvs_bg = "#12331f" if is_mvs_active else "#f8fafb"
        mvs_fg = "#4ade80" if is_mvs_active else "#e4b030"
        self.lbl_mvs_status.setStyleSheet(
            f"background-color: {mvs_bg}; color: {mvs_fg}; font-weight: 600; padding: 4px 8px; border-radius: 3px; font-size: 12px;"
        )
        hdr_bar.addWidget(self.lbl_mvs_status, 0)
        main_layout.addLayout(hdr_bar)

        # Splitter: Left (Device List & Parameters) / Right (Live Video Preview)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: Device Table + Action buttons + Parameters
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Table of enumerated cameras
        self.table_devices = QTableWidget(0, 4)
        self.table_devices.setHorizontalHeaderLabels(
            ["Name / Model", "Type", "Serial / ID", "Interface"])
        header = self.table_devices.horizontalHeader()
        # The first column takes the slack and the other three take their content
        # width.  The default minimum section is 104 px, which is wider than
        # "Interface" needs, so the four columns together overflowed the pane and the
        # header was clipped mid-word behind a horizontal scrollbar; a smaller floor
        # lets the content-sized columns actually fit.
        header.setMinimumSectionSize(64)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table_devices.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_devices.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_devices.setAlternatingRowColors(True)
        self.table_devices.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME['bg_control']};
                gridline-color: {THEME['border_subtle']};
                color: {THEME['text_primary']};
                border: 1px solid {THEME['border_control']};
            }}
            QHeaderView::section {{
                background-color: {THEME['bg_surface_alt']};
                color: {THEME['text_primary']};
                border: 1px solid {THEME['border_subtle']};
                padding: 4px;
            }}
        """)
        self.table_devices.itemSelectionChanged.connect(self._on_device_selection_changed)
        left_layout.addWidget(self.table_devices, 2)

        # Buttons under table: Refresh / Add RTSP
        btn_bar = QHBoxLayout()
        self.btn_refresh = QPushButton("Scan / Refresh Devices")
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        btn_bar.addWidget(self.btn_refresh)

        self.btn_add_rtsp = QPushButton("Add RTSP Stream...")
        self.btn_add_rtsp.clicked.connect(self._on_add_rtsp_clicked)
        btn_bar.addWidget(self.btn_add_rtsp)
        left_layout.addLayout(btn_bar)

        # Parameters Group
        grp_params = QGroupBox("Camera Parameters")
        grp_layout = QFormLayout(grp_params)
        grp_layout.setContentsMargins(8, 8, 8, 8)
        grp_layout.setSpacing(6)

        self.spin_exposure = QDoubleSpinBox()
        self.spin_exposure.setRange(10.0, 1000000.0)
        self.spin_exposure.setValue(20000.0)
        self.spin_exposure.setSuffix(" us")
        self.spin_exposure.valueChanged.connect(self._on_param_modified)
        grp_layout.addRow("Exposure Time:", self.spin_exposure)

        self.spin_gain = QDoubleSpinBox()
        self.spin_gain.setRange(0.1, 16.0)
        self.spin_gain.setValue(1.0)
        self.spin_gain.setSingleStep(0.1)
        self.spin_gain.setSuffix(" x")
        self.spin_gain.valueChanged.connect(self._on_param_modified)
        grp_layout.addRow("Analog/Digital Gain:", self.spin_gain)

        self.combo_trigger = QComboBox()
        self.combo_trigger.addItems(["Continuous", "Software Trigger", "Hardware Trigger (Line0)", "Hardware Trigger (Line1)"])
        self.combo_trigger.currentTextChanged.connect(self._on_param_modified)
        grp_layout.addRow("Trigger Mode:", self.combo_trigger)

        self.combo_format = QComboBox()
        self.combo_format.addItems(["BGR8 (Color)", "Mono8 (Grayscale)"])
        self.combo_format.currentTextChanged.connect(self._on_param_modified)
        grp_layout.addRow("Pixel Format:", self.combo_format)

        # Hikrobot MVS Feature Configuration Actions
        mvs_action_layout = QHBoxLayout()
        self.btn_import_mvs = QPushButton("Import MVS Config (*.mvs, *.xml)...")
        self.btn_import_mvs.setStyleSheet(f"background-color: {THEME['border_focus']}; color: {THEME['text_primary']}; font-size: 12px; padding: 4px;")
        self.btn_import_mvs.clicked.connect(self._on_import_mvs_config)
        mvs_action_layout.addWidget(self.btn_import_mvs)

        self.btn_export_mvs = QPushButton("Export MVS Config (*.mvs)...")
        self.btn_export_mvs.setStyleSheet(f"background-color: {THEME['border_control']}; color: {THEME['text_primary']}; font-size: 12px; padding: 4px;")
        self.btn_export_mvs.clicked.connect(self._on_export_mvs_config)
        mvs_action_layout.addWidget(self.btn_export_mvs)

        grp_layout.addRow("MVS Config:", mvs_action_layout)

        left_layout.addWidget(grp_params, 1)
        splitter.addWidget(left_widget)

        # Right panel: Live Video Preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        grp_preview = QGroupBox("Live Preview")
        preview_layout = QVBoxLayout(grp_preview)
        preview_layout.setContentsMargins(8, 8, 8, 8)

        self.lbl_preview = QLabel("Select a camera to start preview")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setMinimumSize(320, 240)
        # The braces matter: without them the token name became literal CSS text and
        # Qt discarded the entire inline stylesheet, leaving the preview unstyled.
        # The ink must be the *viewport* text tone: the body ink measured 1.8:1 on
        # this dark surface.
        self.lbl_preview.setStyleSheet(f"""
            background-color: {THEME['vm_viewport']};
            color: {THEME['vm_viewport_text']};
            border: 1px solid {THEME['border_control']};
        """)
        preview_layout.addWidget(self.lbl_preview, 1)

        # Preview status & controls
        prev_bar = QHBoxLayout()
        self.lbl_preview_info = QLabel("Status: Standby")
        self.lbl_preview_info.setStyleSheet(f"color: {THEME['accent_primary']}; font-size: 11px;")
        prev_bar.addWidget(self.lbl_preview_info, 1)

        self.btn_toggle_preview = QPushButton("Start Preview")
        self.btn_toggle_preview.setCheckable(True)
        self.btn_toggle_preview.toggled.connect(self._on_toggle_preview)
        prev_bar.addWidget(self.btn_toggle_preview, 0)

        preview_layout.addLayout(prev_bar)
        right_layout.addWidget(grp_preview)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 5)
        main_layout.addWidget(splitter, 1)

        # Dialog Buttons (OK / Cancel) + Lens Calibration Wizard
        bottom_row = QHBoxLayout()
        btn_lens_calib = QPushButton("Lens Calibration Wizard...")
        btn_lens_calib.setStyleSheet(f"background-color: {THEME['border_focus']}; color: {THEME['text_primary']}; font-weight: 500;")
        btn_lens_calib.clicked.connect(self._on_open_lens_calib)
        bottom_row.addWidget(btn_lens_calib)
        bottom_row.addStretch()

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        bottom_row.addWidget(btn_box)
        main_layout.addLayout(bottom_row)

    def _on_open_lens_calib(self):
        from apex_vision.ui.camera_calibration_dialog import CameraCalibrationDialog
        frame = None
        if self.active_driver and hasattr(self.active_driver, "_last_frame"):
            frame = self.active_driver._last_frame
        dlg = CameraCalibrationDialog(frame, self)
        dlg.exec()

    def _populate_devices(self):
        devices = self.camera_manager.list_devices()
        self.table_devices.setRowCount(len(devices))

        selected_row = 0
        for r, dev in enumerate(devices):
            item_name = QTableWidgetItem(dev.name)
            item_name.setData(Qt.ItemDataRole.UserRole, dev.device_id)
            item_type = QTableWidgetItem(dev.camera_type)
            item_serial = QTableWidgetItem(dev.serial_number or dev.device_id)
            item_iface = QTableWidgetItem(dev.interface_name or dev.camera_type)
            full = "\n".join((dev.name, dev.camera_type, dev.serial_number or dev.device_id))
            for cell in (item_name, item_type, item_serial, item_iface):
                cell.setToolTip(full)          # the Name column is narrow: the tooltip has the whole text

            self.table_devices.setItem(r, 0, item_name)
            self.table_devices.setItem(r, 1, item_type)
            self.table_devices.setItem(r, 2, item_serial)
            self.table_devices.setItem(r, 3, item_iface)

            if dev.device_id == self.current_device_id:
                selected_row = r

        if devices:
            self.table_devices.selectRow(selected_row)

    def _on_refresh_clicked(self):
        self._stop_preview()
        self.camera_manager.refresh_devices()
        self._populate_devices()
        self.lbl_preview_info.setText("Devices refreshed.")

    def _on_add_rtsp_clicked(self):
        url, ok = QInputDialog.getText(
            self, "Add Network Camera", "Enter RTSP / HTTP Video Stream URL:\n(e.g., rtsp://192.168.1.64:554/stream1)",
            QLineEdit.EchoMode.Normal, "rtsp://192.168.1.64:554/live"
        )
        if ok and url.strip():
            dev_info = self.camera_manager.add_network_stream(url.strip())
            self._populate_devices()
            # Select new device
            for r in range(self.table_devices.rowCount()):
                if self.table_devices.item(r, 0).data(Qt.ItemDataRole.UserRole) == dev_info.device_id:
                    self.table_devices.selectRow(r)
                    break

    def _on_device_selection_changed(self):
        rows = self.table_devices.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        item = self.table_devices.item(row, 0)
        if not item:
            return
        dev_id = item.data(Qt.ItemDataRole.UserRole)
        self.current_device_id = dev_id

        # Switch driver
        was_previewing = self.preview_timer.isActive()
        self._stop_preview()

        driver = self.camera_manager.get_or_create_driver(dev_id)
        self.active_driver = driver
        if driver:
            self.spin_exposure.setValue(driver.exposure_time_us)
            self.spin_gain.setValue(driver.gain)
            self.combo_trigger.setCurrentText(driver.trigger_mode if driver.trigger_mode in ["Continuous", "Software Trigger"] else "Continuous")

        if was_previewing:
            self._start_preview()

    def _on_param_modified(self):
        if self.active_driver:
            self.active_driver.set_exposure(self.spin_exposure.value())
            self.active_driver.set_gain(self.spin_gain.value())
            self.active_driver.set_trigger_mode(self.combo_trigger.currentText())
            self.active_driver.pixel_format = "Mono8" if "Mono" in self.combo_format.currentText() else "BGR8"

    def _on_toggle_preview(self, checked: bool):
        if checked:
            self._start_preview()
        else:
            self._stop_preview()

    def _start_preview(self):
        if not self.active_driver:
            rows = self.table_devices.selectionModel().selectedRows()
            if rows:
                dev_id = self.table_devices.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
                self.active_driver = self.camera_manager.get_or_create_driver(dev_id)

        if not self.active_driver:
            self.btn_toggle_preview.setChecked(False)
            return

        self._fps_counter = 0
        self._fps_start_time = time.time()
        self.preview_timer.start(33)  # ~30 FPS
        self.btn_toggle_preview.setText("Stop Preview")
        self.lbl_preview_info.setText(f"Streaming from {self.active_driver.device_info.name}...")

    def _stop_preview(self):
        self.preview_timer.stop()
        self.btn_toggle_preview.setText("Start Preview")
        self.btn_toggle_preview.setChecked(False)
        self.lbl_preview_info.setText("Status: Standby")

    def _on_preview_tick(self):
        if not self.active_driver:
            return

        ok, frame, msg = self.active_driver.capture_frame(timeout_ms=500.0)
        if not ok or frame is None:
            self.lbl_preview_info.setText(f"Error: {msg}")
            return

        self._fps_counter += 1
        elapsed = time.time() - self._fps_start_time
        fps = (self._fps_counter / elapsed) if elapsed > 0 else 0.0

        # Render QImage in preview label
        h, w = frame.shape[:2]
        if len(frame.shape) == 2:
            qimg = QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            # OpenCV BGR to RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)

        pixmap = QPixmap.fromImage(qimg)
        scaled = pixmap.scaled(
            self.lbl_preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.lbl_preview.setPixmap(scaled)
        self.lbl_preview_info.setText(f"Live: {w}x{h} @ {fps:.1f} FPS | {self.active_driver.device_info.camera_type}")

    def _on_import_mvs_config(self):
        if not self.current_device_id:
            rows = self.table_devices.selectionModel().selectedRows()
            if rows:
                self.current_device_id = self.table_devices.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if not self.current_device_id:
            return

        fpath, _ = QFileDialog.getOpenFileName(
            self, "Import Hikrobot MVS Camera Configuration", "",
            "Hikrobot MVS Config (*.mvs *.xml);;All Files (*)"
        )
        if fpath:
            ok = self.camera_manager.import_mvs_config(self.current_device_id, fpath)
            if ok:
                if self.active_driver:
                    self.spin_exposure.setValue(self.active_driver.exposure_time_us)
                    self.spin_gain.setValue(self.active_driver.gain)
                    self.combo_trigger.setCurrentText(
                        self.active_driver.trigger_mode if self.active_driver.trigger_mode in ["Continuous", "Software Trigger"] else "Continuous"
                    )
                    self.combo_format.setCurrentText("Mono8 (Grayscale)" if self.active_driver.pixel_format == "Mono8" else "BGR8 (Color)")
                self.lbl_preview_info.setText(f"MVS configuration imported from {os.path.basename(fpath)}")
                if not os.environ.get("PYTEST_CURRENT_TEST"):
                    QMessageBox.information(self, "MVS Config", f"Successfully imported MVS configuration from:\n{fpath}")
            else:
                if not os.environ.get("PYTEST_CURRENT_TEST"):
                    QMessageBox.warning(self, "MVS Config", f"Failed to parse MVS config from {fpath}")

    def _on_export_mvs_config(self):
        if not self.current_device_id:
            rows = self.table_devices.selectionModel().selectedRows()
            if rows:
                self.current_device_id = self.table_devices.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if not self.current_device_id:
            return

        fpath, _ = QFileDialog.getSaveFileName(
            self, "Export Hikrobot MVS Camera Configuration", "camera_config.mvs",
            "Hikrobot MVS Config (*.mvs);;XML Feature (*.xml)"
        )
        if fpath:
            ok = self.camera_manager.export_mvs_config(self.current_device_id, fpath)
            if ok:
                self.lbl_preview_info.setText(f"MVS configuration exported to {os.path.basename(fpath)}")
                if not os.environ.get("PYTEST_CURRENT_TEST"):
                    QMessageBox.information(self, "MVS Config", f"Successfully exported MVS configuration to:\n{fpath}")
            else:
                if not os.environ.get("PYTEST_CURRENT_TEST"):
                    QMessageBox.warning(self, "MVS Config", "Failed to export MVS config file.")

    def _on_accept(self):
        self._stop_preview()
        rows = self.table_devices.selectionModel().selectedRows()
        if rows:
            dev_id = self.table_devices.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
            params = {
                "exposure_time_us": self.spin_exposure.value(),
                "gain": self.spin_gain.value(),
                "trigger_mode": self.combo_trigger.currentText(),
                "color_mode": "Grayscale" if "Mono" in self.combo_format.currentText() else "BGR"
            }
            self.camera_selected.emit(dev_id, params)
        self.accept()

    def closeEvent(self, event):
        self._stop_preview()
        super().closeEvent(event)
