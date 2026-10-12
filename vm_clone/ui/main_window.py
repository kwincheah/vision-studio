"""
Apex Industrial Vision Studio - Main Application Window.

Workspace architecture follows the HikRobot Vision Master reference
(`HikRobotVMHelp_compressed.pdf`):

* p.40 / p.70  - menu bar (File / Settings / Tools / System / Help) above a
                 single Control Toolbar icon strip: Save, Open, Undo, Redo,
                 Locking, Camera Set, Controller Management, Global Variable,
                 Communication Management, Global Trigger, Global Script,
                 Once, Continuously, Stop, Operation Interface.
* p.72 / p.74  - left Tool Box: vertical category rail + icon-grid flyout.
* p.74         - central flow canvas with white module cards and orange wires.
* p.40 / p.87  - right Image / Result split with the
                 "Param Name | Current Result | Global Variable" grid.
* p.40 item 7  - segmented status bar (component / flow / tools / algorithm).
* p.95         - Multi-Flow overview tab.

All controls are wired to real behaviour: editing, validation, execution,
persistence, ROI drawing, layer filtering and CSV export.
"""
import sys
import os
import time
import json
import csv
import cv2
import numpy as np
from typing import Optional, List, Dict, Any
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QDockWidget, QTreeWidget, QTreeWidgetItem, QToolBar, QPushButton,
    QLabel, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QStatusBar, QApplication, QInputDialog,
    QLineEdit, QTabBar, QMenu, QDialog, QFormLayout, QSpinBox, QCheckBox,
    QDialogButtonBox, QToolButton, QSizePolicy, QPlainTextEdit, QScrollArea,
    QComboBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QMimeData, QPoint, QPointF, QSize
from PyQt6.QtGui import QIcon, QAction, QFont, QColor, QDrag, QKeySequence

from vm_clone.core.registry import list_categories, create_tool_instance, get_tool_class
from vm_clone.core.pipeline import VisionPipeline, SolutionManager
from vm_clone.core.base_tool import ToolStatus
from vm_clone.samples.pcb_solution import (
    create_pcb_inspection_solution,
    create_calibration_robot_solution,
    create_precision_measurement_solution,
    create_object_detection_solution
)
from vm_clone.core.project_manager import ProjectManager
from vm_clone.ui.start_page import StartPageDialog, NewProjectDialog
from vm_clone.ui.image_display import ImageDisplayArea
from vm_clone.ui.flow_editor import FlowScene, FlowEditorView, NodeSignals, AddNodeCommand
from vm_clone.ui.global_vars_dialog import GlobalVariablesDialog
from vm_clone.ui.styles import INDUSTRIAL_THEME_QSS, THEME
from vm_clone.ui.vm_theme import VM_THEME_QSS
from vm_clone.ui.icons import get_category_icon, get_tool_icon, get_action_icon
from vm_clone.ui.toolbox import ToolBoxPanel, get_brand_mark, CATEGORY_ORDER
from vm_clone.ui.result_panel import ModuleResultPanel
from vm_clone.ui.result_display import ResultDisplayArea, MODULE_LOG_HEADERS
from vm_clone.ui.module_config import ModuleConfigDialog
from vm_clone.ui import layout_metrics as LM
from vm_clone.ui.flow_overview import FlowOverviewWidget
import vm_clone.tools


class DraggableToolTree(QTreeWidget):
    """Tool Library tree supporting double-click and drag-and-drop onto flow canvas."""
    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item and item.data(0, Qt.ItemDataRole.UserRole):
            tool_name = item.data(0, Qt.ItemDataRole.UserRole)
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(tool_name)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)
        else:
            super().startDrag(supportedActions)


class FlowSettingsDialog(QDialog):
    """Flow Parameters configuration dialog matching Hikrobot VM manual (Run Interval, Stop on NG, Timeout, Enabled)."""
    def __init__(self, pipeline: VisionPipeline, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Flow Configuration - {pipeline.name}")
        self.setFixedSize(380, 240)
        self.pipeline = pipeline

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(0, 10000)
        self.spin_interval.setSingleStep(10)
        self.spin_interval.setSuffix(" ms")
        self.spin_interval.setValue(int(pipeline.run_interval_ms))
        form.addRow("Run Interval:", self.spin_interval)

        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(100, 60000)
        self.spin_timeout.setSingleStep(500)
        self.spin_timeout.setSuffix(" ms")
        self.spin_timeout.setValue(int(pipeline.flow_timeout_ms))
        form.addRow("Flow Timeout:", self.spin_timeout)

        self.chk_stop_on_ng = QCheckBox("Halt continuous cycle on NG defect")
        self.chk_stop_on_ng.setChecked(pipeline.stop_on_ng)
        form.addRow("Stop on NG:", self.chk_stop_on_ng)

        self.chk_enabled = QCheckBox("Enable flow execution")
        self.chk_enabled.setChecked(pipeline.enabled)
        form.addRow("Flow Switch:", self.chk_enabled)

        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def accept(self):
        self.pipeline.run_interval_ms = float(self.spin_interval.value())
        self.pipeline.flow_timeout_ms = float(self.spin_timeout.value())
        self.pipeline.stop_on_ng = self.chk_stop_on_ng.isChecked()
        self.pipeline.enabled = self.chk_enabled.isChecked()
        super().accept()


class FlowValidationDialog(QDialog):
    """Flow diagnostic report dialog displaying topological and connection validation results."""
    def __init__(self, issues: list, parent=None, title: str = "Flow Validation Diagnostics"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 340)
        self.resize(820, 380)
        layout = QVBoxLayout(self)

        errors = sum(1 for i in issues if i.get("severity") == "error")
        warnings = sum(1 for i in issues if i.get("severity") == "warning")
        lbl = QLabel(
            f"<b>Flow Diagnostics:</b> {len(issues)} finding(s) &mdash; "
            f"<span style='color:{THEME['status_error_text']}'>{errors} error(s)</span>, "
            f"<span style='color:{THEME['status_warn_text']}'>{warnings} warning(s)</span>"
        )
        layout.addWidget(lbl)

        table = QTableWidget(len(issues), 3)
        table.setHorizontalHeaderLabels(["Severity", "Module", "Diagnostic Message"])
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(22)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(0, 84)
        header.resizeSection(1, 128)
        table.setWordWrap(False)
        table.setToolTip("Hover a row to read the full diagnostic message")

        for row, issue in enumerate(issues):
            sev = issue.get("severity", "info").upper()
            sev_item = QTableWidgetItem(sev)
            if sev == "ERROR":
                sev_item.setForeground(QColor(THEME["status_error_text"]))
            elif sev == "WARNING":
                sev_item.setForeground(QColor(THEME["status_warn_text"]))
            else:
                sev_item.setForeground(QColor(THEME["text_secondary"]))
            sev_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            table.setItem(row, 0, sev_item)

            table.setItem(row, 1, QTableWidgetItem(issue.get("node_id", "System/Graph")))
            msg_item = QTableWidgetItem(issue.get("message", ""))
            msg_item.setToolTip(issue.get("message", ""))
            table.setItem(row, 2, msg_item)

        layout.addWidget(table)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)



class VisionMasterMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apex Industrial Vision Studio v4.3")
        self.resize(1600, 950)

        # Multi-flow solution manager
        self.solution = SolutionManager(name="IndustrialSolution")
        pcb_pipe = create_pcb_inspection_solution()
        self.solution.flows["Flow1"] = pcb_pipe
        self.solution.active_flow_name = "Flow1"

        self.node_signals = NodeSignals()
        self.node_signals.node_selected.connect(self.on_node_selected)
        self.node_signals.node_deleted.connect(self.on_node_deleted)
        self.node_signals.connection_added.connect(self.on_connection_added)
        self.node_signals.connection_rejected.connect(self.on_connection_rejected)
        self.node_signals.run_single_tool.connect(self.on_run_single_tool)
        self.node_signals.tool_dropped.connect(self.on_tool_dropped)
        self.node_signals.validation_requested.connect(self.on_validate_active_flow)
        self.node_signals.configure_module.connect(self.on_open_module_config)

        self.run_timer = QTimer(self)
        self.run_timer.timeout.connect(self.run_pipeline_step)

        self.selected_node_id = "node_source"
        self._locked = False
        self._toolbar_actions = {}
        self._image_strip_nodes: list = []
        self._image_flow: list = []
        self._current_image_flow_index: int = 0
        self._last_balance_width: int = 0

        # Project and solution manager for Startup Page & recent projects
        self.project_manager = ProjectManager()
        self.project_manager.seed_default_samples_if_empty()
        # Discover and load custom plugins
        from vm_clone.sdk.manager import PluginManager
        self.plugin_manager = PluginManager.get_instance()
        self.plugin_manager.discover_and_load_all()

        self._init_menu_bar()
        self._init_control_toolbars()
        self._init_central_workspace()
        self._init_tool_library_dock()
        self._init_property_dock()
        self._init_default_image_flow()
        self._init_module_log_dock()
        self._init_status_bar()
        self._apply_measured_stretch()
        self._layout_settling = False
        self._layout_settled = False
        self._apply_reference_proportions()

        self.image_canvas.roi_changed.connect(self.on_canvas_roi_changed)

        self.setStyleSheet(VM_THEME_QSS)

        self._refresh_flow_tabs()
        self.flow_scene.build_from_pipeline()
        self.flow_overview.rebuild(self.solution.flows, self.solution.get_trigger_flow_name())
        # Start with the entry module selected so the Inspector and the Result
        # grid are populated immediately, as in the reference workspace.
        first_id = next(iter(self.pipeline.execution_order), self.selected_node_id)
        if first_id in self.pipeline.nodes:
            self.flow_scene.select_node(first_id)
            self.on_node_selected(first_id)
        self._apply_responsive_chrome()
        self.run_pipeline_step()

    @property
    def pipeline(self) -> VisionPipeline:
        return self.solution.get_active_flow()

    # =====================================================================
    # Menu bar (manual p.40 item 1 / p.70)
    # =====================================================================
    def _init_menu_bar(self):
        mb = self.menuBar()

        # --- File ---------------------------------------------------------
        file_menu = mb.addMenu("&File")
        self._add_action(file_menu, "Start Page...", self.show_start_page, "Ctrl+H")
        file_menu.addSeparator()
        self._add_action(file_menu, "New Solution...", self.on_new_solution, "Ctrl+N")
        self._add_action(file_menu, "Open Solution...", self.on_open_solution, "Ctrl+O")
        self._add_action(file_menu, "Save Solution", self.on_save_solution, "Ctrl+S")
        self._add_action(file_menu, "Save Solution As...", self.on_save_solution_as, "Ctrl+Shift+S")
        file_menu.addSeparator()
        self._add_action(file_menu, "Load Image File...", self.on_load_image_file, "Ctrl+I")
        file_menu.addSeparator()
        sample_menu = file_menu.addMenu("Load Example Solution")
        self._add_action(sample_menu, "PCB Inspection & Defect Analysis",
                         lambda: self._load_solution_instance(create_pcb_inspection_solution()))
        self._add_action(sample_menu, "Precision Dimensional Measurement",
                         lambda: self._load_solution_instance(create_precision_measurement_solution()))
        self._add_action(sample_menu, "Deep Learning Object Detection (YOLOv11)",
                         lambda: self._load_solution_instance(create_object_detection_solution()))
        self._add_action(sample_menu, "Color Extraction & Robot Calibration",
                         lambda: self._load_solution_instance(create_calibration_robot_solution()))
        self._add_action(file_menu, "Export Results to CSV...", self.on_export_results_csv)
        self._add_action(file_menu, "Export Flow as XML...", self.on_export_flow_xml)
        self._add_action(file_menu, "Import Flow from XML...", self.on_import_flow_xml)
        self._add_action(file_menu, "Export Flow Procedure (.prc)...", self.on_export_active_flow)
        self._add_action(file_menu, "Import Flow Procedure (.prc)...", self.on_import_flow_procedure)
        file_menu.addSeparator()
        self._add_action(file_menu, "Exit", self.close, "Alt+F4")

        # --- Settings -----------------------------------------------------
        settings_menu = mb.addMenu("&Settings")
        self._add_action(settings_menu, "Global Variables...", self.on_open_global_vars)
        self._add_action(settings_menu, "Hardware Trigger Settings", self.on_hardware_trigger_settings)
        self._add_action(settings_menu, "Communication Configuration", self.on_communication_config)

        # --- Tools --------------------------------------------------------
        tools_menu = mb.addMenu("&Tools")
        self._add_action(tools_menu, "Camera Lens Distortion Calibration Wizard...", self.on_open_lens_calibration_wizard)
        self._add_action(tools_menu, "N-Point Spatial Calibration Wizard", self.on_calibration_wizard)
        self._add_action(tools_menu, "Calibration Target Generator",
                         lambda: self._info("Calibration Target Generator",
                                            "Generates a 9-point calibration target image and its\n"
                                            "world-coordinate table for N-point spatial calibration."))
        self._add_action(tools_menu, "Module Generator",
                         lambda: self._info("Module Generator",
                                            "Scaffolds a new vision module with ports, parameters and\n"
                                            "the plugin registration boilerplate."))
        self._add_action(tools_menu, "Plugin Manager...", self.on_open_plugin_manager)
        self._add_action(tools_menu, "Plugin Marketplace...", lambda: self.on_open_plugin_manager(initial_tab=1))
        self._add_action(tools_menu, "Create Vision Plugin...", lambda: self.on_open_plugin_manager(initial_tab=3))
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Validate Active Flow", self.on_validate_active_flow)
        self._add_action(tools_menu, "Arrange Modules Hierarchically",
                         lambda: self.flow_scene.arrange_nodes_hierarchically())

        # --- System -------------------------------------------------------
        system_menu = mb.addMenu("S&ystem")
        self._add_action(system_menu, "Camera Set", self.on_camera_set)
        self._add_action(system_menu, "Controller Management", self.on_controller_management)
        self._add_action(system_menu, "Log Viewer", self.on_show_log_viewer)
        system_menu.addSeparator()
        self._add_action(system_menu, "Performance Options", self.on_performance_options)

        # --- View ---------------------------------------------------------
        view_menu = self._init_view_menu(mb)

        # --- Help ---------------------------------------------------------
        help_menu = mb.addMenu("&Help")
        self._add_action(help_menu, "User Manual", self.on_help_manual, "F1")
        self._add_action(help_menu, "Keyboard Shortcuts", self.on_help_shortcuts)
        self._add_action(help_menu, "Language / 语言", self.on_switch_language)
        help_menu.addSeparator()
        self._add_action(help_menu, "Version Information", self.on_version_info)
        self._add_action(help_menu, "About Apex Industrial Vision Studio", self.on_about)

        # Figure 6-2: Top Right Corner Widget: Solution Name dropdown + Save + Role Switchover
        corner = QWidget()
        corner.setObjectName("menuCornerWidget")
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.setSpacing(6)

        self.cbo_solution = QComboBox()
        self.cbo_solution.setObjectName("comboSolution")
        self.cbo_solution.setMinimumWidth(130)
        self.cbo_solution.setFixedHeight(22)
        self.cbo_solution.addItems(["PCB_AOI_Solution", "Robot_Calibration_Solution", "Precision_Measurement_Solution"])
        self.cbo_solution.setToolTip("Currently-Loaded Solution (Figure 6-2 Item 3)")
        self.cbo_solution.currentIndexChanged.connect(self._on_solution_combo_changed)
        cl.addWidget(self.cbo_solution)

        self.btn_menu_save = QToolButton()
        self.btn_menu_save.setObjectName("btnMenuSave")
        self.btn_menu_save.setIcon(get_action_icon("save", 16))
        self.btn_menu_save.setFixedSize(22, 22)
        self.btn_menu_save.setToolTip("Save Solution (Ctrl+S)")
        self.btn_menu_save.clicked.connect(self.on_save_solution)
        cl.addWidget(self.btn_menu_save)

        self.cbo_role = QComboBox()
        self.cbo_role.setObjectName("comboRole")
        self.cbo_role.setMinimumWidth(125)
        self.cbo_role.setFixedHeight(22)
        self.cbo_role.addItems(["Operating Mode", "Administrator", "Engineer", "Operator"])
        self.cbo_role.setToolTip("Role Switchover (Figure 6-2 Item 4)")
        cl.addWidget(self.cbo_role)

        mb.setCornerWidget(corner, Qt.Corner.TopRightCorner)

    def _init_view_menu(self, mb) -> QMenu:
        view_menu = mb.addMenu("&View")

        self.act_show_flow = QAction("Flow Diagram", self)
        self.act_show_flow.setShortcut("Ctrl+1")
        self.act_show_flow.triggered.connect(lambda: self._show_workspace_tab(0))
        view_menu.addAction(self.act_show_flow)

        self.act_show_operation = QAction("Operation Interface", self)
        self.act_show_operation.setShortcut("Ctrl+2")
        self.act_show_operation.triggered.connect(lambda: self._show_workspace_tab(1))
        view_menu.addAction(self.act_show_operation)

        self.act_show_overview = QAction("Multi-Flow Overview", self)
        self.act_show_overview.setShortcut("Ctrl+3")
        self.act_show_overview.triggered.connect(lambda: self._show_workspace_tab(2))
        view_menu.addAction(self.act_show_overview)

        view_menu.addSeparator()
        act_fit = QAction("Fit Modules to View", self)
        act_fit.setShortcut("Ctrl+0")
        act_fit.triggered.connect(lambda: self.flow_view.fit_to_view())
        view_menu.addAction(act_fit)
        act_arrange = QAction("Auto-Arrange Modules", self)
        act_arrange.triggered.connect(lambda: self.flow_scene.arrange_nodes_hierarchically())
        view_menu.addAction(act_arrange)

        view_menu.addSeparator()
        self.act_toggle_grid = QAction("Show Canvas Alignment Grid", self, checkable=True)
        self.act_toggle_grid.setChecked(True)
        self.act_toggle_grid.toggled.connect(lambda chk: self.flow_scene.set_grid_visible(chk))
        view_menu.addAction(self.act_toggle_grid)

        view_menu.addSeparator()
        self.dock_menu = view_menu.addMenu("Panels")
        return view_menu

    def _add_action(self, menu: QMenu, text: str, slot, shortcut: str = None) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _show_workspace_tab(self, index: int):
        self.tab_workspace.setCurrentIndex(index)

    def _on_solution_combo_changed(self, index: int):
        if index == 0:
            self._load_solution_instance(create_pcb_inspection_solution())
        elif index == 1:
            self._load_solution_instance(create_calibration_robot_solution())
        elif index == 2:
            self._load_solution_instance(create_precision_measurement_solution())

    # =====================================================================
    # Control Toolbar - resource group (manual p.70, first icon row)
    # =====================================================================
    def _make_icon_button(self, action_key: str, tooltip: str, slot, checkable: bool = False) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("toolbarButton")
        btn.setIcon(get_action_icon(action_key, 22))
        btn.setIconSize(QSize(18, 18))
        btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        btn.setAutoRaise(True)
        # Measured reference toolbar metrics: a 40 px pitch with a 26 px icon and
        # a 30 px strip (see `layout_metrics.TOOLBAR_BUTTON`), which is what makes
        # the chrome land on the measured 0.1496 of the window height.
        btn.setFixedSize(LM.TOOLBAR_BUTTON[0], LM.TOOLBAR_BUTTON[1])
        if checkable:
            # Checkable controls must react to programmatic state changes too
            # (they are mirrored across the toolbar and the Operation Interface).
            btn.toggled.connect(slot)
        else:
            btn.clicked.connect(slot)
        return btn

    def _init_control_toolbars(self):
        """The reference's two visible chrome rows (manual 4.3.0 Fig. 5-2).

        Measured from the top-left crop of the uncropped figure
        (`docs/references/external/ui_crops/r3_topleft.png`, 3x):

        * the **brand mark sits on the first row at the far left**, then the icon
          strip (save, open, page, copy, lock, camera, controller, global
          variable, communication, global trigger, global script, once,
          continuous) with a separator before the last two;
        * the **second row starts with the flow tab** (flow-tree glyph, `Flow1`,
          once, continuous, plus, then a right-aligned dropdown) followed by the
          viewport controls (operation-interface, histogram, ROI, fit, zoom) on
          the right, which is where the reference puts them.

        The reference reaches the same two rows by wrapping one strip; this keeps
        two explicit rows so no control is ever pushed into the overflow popup.
        """
        # ---- row 1: brand + file/resource management + execution -------------
        row1 = QToolBar("Control Toolbar", self)
        row1.setObjectName("controlToolbar")
        row1.setMovable(False)
        row1.setFloatable(False)
        row1.setIconSize(QSize(LM.TOOLBAR_ICON, LM.TOOLBAR_ICON))
        row1.setMinimumHeight(LM.TOOLBAR_H + 14)
        # Scroll instead of collapsing the tail into an overflow popup: a hidden
        # control is worse than a scroll arrow in an operator console.
        row1.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, row1)
        self.toolbar_resources = row1

        brand = QLabel()
        brand.setPixmap(get_brand_mark(18).pixmap(18, 18))
        brand.setToolTip("Apex Industrial Vision Studio")
        brand.setFixedWidth(26)
        row1.addWidget(brand)

        for key, tip, slot in (
            ("save", "Save Solution (Ctrl+S)", self.on_save_solution),
            ("open", "Open Solution (Ctrl+O)", self.on_open_solution),
            ("load_image", "Load Image File (Ctrl+I)", self.on_load_image_file),
            ("undo", "Undo (Ctrl+Z)", self.on_undo),
            ("redo", "Redo (Ctrl+Y)", self.on_redo),
        ):
            self._add_toolbar_button(row1, self._make_icon_button(key, tip, slot))
        row1.addSeparator()

        self.btn_lock = self._make_icon_button(
            "lock", "Locking - freeze module and wire editing", self.on_toggle_lock, checkable=True
        )
        self._add_toolbar_button(row1, self.btn_lock)
        for key, tip, slot in (
            ("camera_set", "Camera Set - manage global cameras", self.on_camera_set),
            ("controller", "Controller Management", self.on_controller_management),
            ("global_var", "Global Variable - up to 32 variables", self.on_open_global_vars),
            ("communication", "Communication Management", self.on_communication_config),
            ("trigger", "Global Trigger - event / string trigger", self.on_global_trigger),
            ("global_script", "Global Script", self.on_global_script),
        ):
            self._add_toolbar_button(row1, self._make_icon_button(key, tip, slot))
        row1.addSeparator()

        # Execution controls, exactly as the reference orders them: Once, then
        # Continuous, then the run-mode selector.
        self.btn_run_once = self._make_icon_button("once", "Once - execute the active flow a single time",
                                                   self.on_run_once)
        self.btn_run_once.setObjectName("btnRunOnce")
        self._add_toolbar_button(row1, self.btn_run_once)

        self.btn_continuous = self._make_icon_button("continuously",
                                                     "Continuously - execute the active flow in a loop",
                                                     self.on_toggle_continuous, checkable=True)
        self._add_toolbar_button(row1, self.btn_continuous)

        self.btn_stop = self._make_icon_button("stop", "Stop - halt all flows", self.on_stop)
        self.btn_stop.setObjectName("btnStop")
        self._add_toolbar_button(row1, self.btn_stop)

        row1.addSeparator()
        self.lbl_global_status = QLabel("READY")
        self.lbl_global_status.setObjectName("flowStatusBadge")
        self._set_status_badge("READY", "ok")
        row1.addWidget(self.lbl_global_status)

        spacer1 = QWidget()
        spacer1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row1.addWidget(spacer1)

        # ---- row 2: flow tabs (left) + viewport controls (right) -------------
        row2 = QToolBar("Flow Toolbar", self)
        row2.setObjectName("flowToolbar")
        row2.setMovable(False)
        row2.setFloatable(False)
        row2.setIconSize(QSize(LM.TOOLBAR_ICON, LM.TOOLBAR_ICON))
        row2.setMinimumHeight(LM.TOOLBAR_H + 14)
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, row2)
        self.toolbar_flows = row2

        self.flow_tab_bar = QTabBar()
        self.flow_tab_bar.setObjectName("flowTabBar")
        self.flow_tab_bar.setDrawBase(False)
        self.flow_tab_bar.setTabsClosable(True)
        self.flow_tab_bar.setExpanding(False)
        self.flow_tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.flow_tab_bar.setUsesScrollButtons(True)
        self.flow_tab_bar.setMaximumWidth(420)
        self.flow_tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.flow_tab_bar.customContextMenuRequested.connect(self.on_flow_tab_context_menu)
        self.flow_tab_bar.currentChanged.connect(self.on_flow_tab_changed)
        self.flow_tab_bar.tabCloseRequested.connect(self.on_flow_tab_closed)
        row2.addWidget(self.flow_tab_bar)

        # The reference places the three flow-scoped controls *immediately after*
        # the tab: the tab's own run-once glyph, its continuous glyph, then plus.
        self.btn_flow_once = self._make_icon_button(
            "once", "Execute the active flow once", self.on_run_once)
        self.btn_flow_once.setObjectName("btnFlowOnce")
        self._add_toolbar_button(row2, self.btn_flow_once)

        self.btn_loop_flow = self._make_icon_button("continuously", "Loop the active flow",
                                                    self.on_toggle_continuous, checkable=True)
        self._add_toolbar_button(row2, self.btn_loop_flow)

        self.btn_add_flow = self._make_icon_button("add_flow", "Add a new sub-flow", self.on_add_flow_tab)
        self._add_toolbar_button(row2, self.btn_add_flow)

        self.btn_activate_flow = self._make_icon_button("check", "Set as the active trigger flow",
                                                        self.on_activate_flow)
        self._add_toolbar_button(row2, self.btn_activate_flow)

        spacer2 = QWidget()
        spacer2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row2.addWidget(spacer2)

        # Viewport / display controls, right-aligned as in the reference.
        self.btn_layers = self._make_icon_button("operation", "Operation Interface - overlay display options",
                                                self.on_toggle_operation_panel, checkable=True)
        self.btn_layers.setObjectName("btnOperation")
        self._add_toolbar_button(row2, self.btn_layers)

        self.btn_hist = self._make_icon_button("histogram", "Live intensity histogram",
                                               self.on_toggle_histogram, checkable=True)
        self.btn_hist.setObjectName("btnHistogram")
        self._add_toolbar_button(row2, self.btn_hist)

        self.btn_draw_roi = self._make_icon_button("draw_roi", "Draw ROI on the image",
                                                   self.on_toggle_roi_mode, checkable=True)
        self._add_toolbar_button(row2, self.btn_draw_roi)

        self.btn_fit = self._make_icon_button("fit", "Fit Image to Window",
                                             lambda: self.image_canvas.fit_to_window())
        self._add_toolbar_button(row2, self.btn_fit)
        self.btn_zoom_100 = self._make_icon_button("zoom_100", "1:1 Pixel Zoom",
                                                  lambda: self.image_canvas.set_zoom_actual())
        self._add_toolbar_button(row2, self.btn_zoom_100)
        self.btn_arrange = self._make_icon_button("arrange", "Auto-arrange the flow hierarchically",
                                                 lambda: self.flow_scene.arrange_nodes_hierarchically())
        self._add_toolbar_button(row2, self.btn_arrange)

    def _init_central_workspace(self):
        """Central tabs: Flow Diagram / Operation Interface / Multi-Flow Overview."""
        self.tab_workspace = QTabWidget()
        self.tab_workspace.setObjectName("workspaceTabs")
        self.tab_workspace.setDocumentMode(True)

        # View 1: Flow Diagram Editor (manual p.74)
        self.flow_scene = FlowScene(self.pipeline, self.node_signals)
        self.flow_view = FlowEditorView(self.flow_scene)
        self.tab_workspace.addTab(self.flow_view, "Flow Diagram")

        # View 2: Operation Interface - module properties + formatting (p.96)
        self.operation_panel = self._build_operation_panel()
        self.tab_workspace.addTab(self.operation_panel, "Operation Interface")

        # View 3: Multi-Flow overview (manual p.95)
        self.flow_overview = FlowOverviewWidget()
        self.flow_overview.flow_activated.connect(self.on_overview_flow_activated)
        self.flow_overview.flow_run_requested.connect(self.on_overview_flow_run)
        self.flow_overview.flow_loop_toggled.connect(self.on_overview_flow_loop)
        self.flow_overview.flow_settings_requested.connect(self.on_overview_flow_settings)
        self.tab_workspace.addTab(self.flow_overview, "Multi-Flow")

        self.setCentralWidget(self.tab_workspace)

    def _build_operation_panel(self) -> QWidget:
        """Operation Interface: formatting/overlay switches (manual p.40 item 5, p.96)."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Display & Formatting")
        title.setStyleSheet("font-weight: 600; color: #d5d8dd; font-size: 13px;")
        layout.addWidget(title)

        hints = QLabel(
            "Control which result overlays are rendered over the inspection image.\n"
            "Layer switches apply immediately to the live image view."
        )
        hints.setStyleSheet("color: #9ba0a7;")
        layout.addWidget(hints)

        self.act_layer_all = QAction("All Overlays", self, checkable=True)
        self.act_layer_all.setChecked(True)
        self.act_layer_all.toggled.connect(self.on_toggle_layer_all)
        self.act_layer_rois = QAction("ROIs & Defect Boxes", self, checkable=True)
        self.act_layer_rois.setChecked(True)
        self.act_layer_rois.toggled.connect(self.on_update_layers)
        self.act_layer_metrics = QAction("Measurements & Labels", self, checkable=True)
        self.act_layer_metrics.setChecked(True)
        self.act_layer_metrics.toggled.connect(self.on_update_layers)
        self.act_layer_datums = QAction("Datum & Crosshairs", self, checkable=True)
        self.act_layer_datums.setChecked(True)
        self.act_layer_datums.toggled.connect(self.on_update_layers)
        self.act_layer_reticle = QAction("Coordinate Reticle Crosshair", self, checkable=True)
        self.act_layer_reticle.setChecked(True)
        self.act_layer_reticle.toggled.connect(lambda chk: self.image_canvas.set_show_crosshair(chk))
        self.act_layer_hist = QAction("Intensity Histogram HUD", self, checkable=True)
        self.act_layer_hist.toggled.connect(self.on_toggle_histogram)
        self.act_layer_grid = QAction("Flow Canvas Alignment Grid", self, checkable=True)
        self.act_layer_grid.setChecked(True)
        self.act_layer_grid.toggled.connect(lambda chk: self.flow_scene.set_grid_visible(chk))

        self._layer_actions = [
            self.act_layer_all, self.act_layer_rois, self.act_layer_metrics,
            self.act_layer_datums, self.act_layer_reticle, self.act_layer_hist,
            self.act_layer_grid,
        ]

        # Mirror each layer switch with a checkbox. The action remains the
        # single source of truth so the toolbar button, the operation panel and
        # the canvas never disagree; state changes are applied once per toggle
        # and re-entrant updates are explicitly guarded against.
        self._syncing_layers = False
        for act in self._layer_actions:
            chk = QCheckBox(act.text())
            chk.setChecked(act.isChecked())
            self._bind_layer_action(act, chk)
            layout.addWidget(chk)

        layout.addSpacing(8)
        sub = QLabel("Module Result Linking")
        sub.setStyleSheet("font-weight: 600; color: #d5d8dd;")
        layout.addWidget(sub)
        link_hint = QLabel(
            "Select a module in the Flow Diagram, then use the Result tab on the right\n"
            "to subscribe individual output parameters to global variables."
        )
        link_hint.setStyleSheet("color: #9ba0a7;")
        layout.addWidget(link_hint)

        layout.addStretch(1)

        # Formatting tool preview (manual p.96 "Output Params")
        fmt = QLabel("Output Parameter Formatting")
        fmt.setStyleSheet("font-weight: 600; color: #d5d8dd;")
        layout.addWidget(fmt)
        self.txt_format_preview = QPlainTextEdit()
        self.txt_format_preview.setReadOnly(True)
        self.txt_format_preview.setMaximumHeight(120)
        self.txt_format_preview.setPlaceholderText(
            "Run the flow to preview the formatted output string."
        )
        layout.addWidget(self.txt_format_preview)
        # The page's natural hint is ~394 px, which raised the window's minimum
        # height to 920 px and diluted every measured ratio against the reference
        # size.  Wrapping the content in a scroll area lets the page (and therefore
        # the window) shrink to the reference height while keeping every control
        # reachable.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumHeight(150)
        scroll.setWidget(panel)
        return scroll

    def _bind_layer_action(self, act: QAction, chk: QCheckBox):
        """Keep a layer QAction and its operation-panel checkbox in sync once."""

        def from_action(checked: bool):
            if self._syncing_layers:
                return
            self._syncing_layers = True
            try:
                if chk.isChecked() != checked:
                    chk.setChecked(checked)
            finally:
                self._syncing_layers = False

        def from_checkbox(checked: bool):
            if self._syncing_layers:
                return
            self._syncing_layers = True
            try:
                if act.isChecked() != checked:
                    act.setChecked(checked)
            finally:
                self._syncing_layers = False

        act.toggled.connect(from_action)
        chk.toggled.connect(from_checkbox)

    def _set_layer_action_state(self, act: QAction, checked: bool):
        """Set a layer action's state without triggering its handler again."""
        if act.isChecked() == checked:
            return
        act.blockSignals(True)
        act.setChecked(checked)
        act.blockSignals(False)

    def _init_tool_library_dock(self):
        """Left Tool Box: category rail + icon-grid flyout (manual p.72/p.74)."""
        dock = QDockWidget("Tool Box", self)
        dock.setObjectName("toolBoxDock")
        # Permanent left-column panel: locked to LeftDockWidgetArea, non-closable,
        # non-movable, and non-floatable so it functions as a permanent part of the main window.
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        empty_title = QWidget()
        empty_title.setFixedHeight(0)
        dock.setTitleBarWidget(empty_title)
        dock.closeEvent = lambda event: event.ignore()

        self.toolbox = ToolBoxPanel()
        self.toolbox.tool_activated.connect(self.on_add_tool_by_name)
        dock.setWidget(self.toolbox)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.tool_dock = dock

        # Public aliases kept for API compatibility with earlier revisions and
        # for the automated tool-navigation tests.
        self.tool_flyout = self.toolbox.flyout
        self.tool_grid = self.toolbox.flyout.grid
        self.txt_tool_search = self.toolbox.flyout.txt_search
        self.tool_rail = self.toolbox.rail

        self.tool_tree = QTreeWidget()
        self.tool_tree.setObjectName("toolTreeCompat")
        self.tool_tree.setHeaderHidden(True)
        self.tool_tree.setIconSize(QSize(16, 16))
        self.tool_tree.setColumnCount(1)
        self._populate_tool_tree()
        self.tool_tree.itemDoubleClicked.connect(self.on_add_tool_from_tree)
        self.tool_tree.hide()

        act_dock = dock.toggleViewAction()
        act_dock.setChecked(True)
        act_dock.setEnabled(False)
        self.dock_menu.addAction(act_dock)

    def _populate_tool_tree(self, filter_text: str = ""):
        """Populate the compatibility tree (kept in sync with the flyout)."""
        self.tool_tree.clear()
        categories = list_categories()
        flt = filter_text.lower().strip()

        for cat_name, tools in categories.items():
            matching_tools = [t for t in tools if not flt or flt in t.lower() or flt in cat_name.lower()]
            if not matching_tools:
                continue

            cat_item = QTreeWidgetItem(self.tool_tree, [cat_name])
            cat_item.setIcon(0, get_category_icon(cat_name, 16))
            cat_item.setExpanded(True)
            cat_item.setFont(0, QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            cat_item.setForeground(0, QColor(THEME['text_secondary']))
            for t_name in matching_tools:
                t_item = QTreeWidgetItem(cat_item, [t_name])
                t_item.setIcon(0, get_tool_icon(t_name, 16))
                t_item.setData(0, Qt.ItemDataRole.UserRole, t_name)
                t_item.setFont(0, QFont("Segoe UI", 9))
                t_item.setForeground(0, QColor(THEME['text_primary']))
                tool_cls = get_tool_class(t_name)
                desc = getattr(tool_cls, "description", "") if tool_cls else ""
                if desc:
                    t_item.setToolTip(0, f"<b>{t_name}</b><br>{desc}")
                else:
                    t_item.setToolTip(0, t_name)

    def on_filter_tools(self, text: str):
        self._populate_tool_tree(text)

    def _init_property_dock(self):
        """Right column, reproduced strictly from the vendor's annotated figure.

        Reference: Vision Master 4.3.0 manual Fig. 5-2 (region 6 "图像显示区域" and
        region 12 "结果显示区"), zoomed crop at
        `docs/references/external/ui_crops/right_column_zoom.png`.

        The vendor's right column is a **two-row vertical stack, each row being its
        own tab widget with its own tab bar**:

            ┌─ 图像 | 模块结果 ────────────────────────────────┐   tab bar row 1
            │ 图像源1.输出图像   [▣][▣▣] [+] [−] [1:1] [⤢]     │   name + view tools
            │  ◀            <image>                    ▶      │   paged viewport
            │ 0153880-Image_202    1280*1024 | X | Y | R G B   │   status line
            ├─────────────────────────────────────────────────┤
            │ 图像源 (1/1)     自动切换 [==]    运行全部 ▾      │   image strip
            └─────────────────────────────────────────────────┘
            ┌─ 当前结果 | 历史结果 | 帮助 ─────────────────────┐   tab bar row 2
            │ 序号 面积 周长 质心X 质心Y 角度 长轴 短轴 圆形度   │   per-parameter table
            └─────────────────────────────────────────────────┘

        Both tab bars are visible at the same time.  The upper bar switches the whole
        display area between the image and the module's result tree; the lower bar
        switches the result table between the current result, the run history and
        help.
        """
        dock = QDockWidget("Image  |  Result", self)
        dock.setObjectName("imageResultDock")
        # Permanent right-column panel: locked to RightDockWidgetArea, non-closable,
        # non-movable, and non-floatable so it functions as a permanent part of the main window.
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        empty_title = QWidget()
        empty_title.setFixedHeight(0)
        dock.setTitleBarWidget(empty_title)
        dock.closeEvent = lambda event: event.ignore()

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Outer vertical split: the display block (Image | Result) over the
        # result block (Current Result | History | Help), exactly two rows as in the
        # vendor figure.  Parameters are edited in the per-module configuration
        # window (frame 6), which is where the reference keeps them, so there is no
        # parameter pane on the canvas.
        self.split_right = QSplitter(Qt.Orientation.Vertical)
        self.split_right.setChildrenCollapsible(False)

        # ---- row 1: Image | Result ------------------------------------------
        # The reference's upper tab pair: `图像 | 结果` in the annotated figure and
        # `图像 | 模块结果` in the maintenance edition — the two pages of the display
        # block.  The heading follows the uncropped figure, which is the measurement
        # source (see `docs/VISIONMASTER_STORYBOARD.md` §0).
        self.data_tabs = QTabWidget()
        self.data_tabs.setObjectName("displayTabs")
        self.data_tabs.setDocumentMode(True)

        self.image_display = ImageDisplayArea()
        self.image_canvas = self.image_display.canvas
        self.image_display.image_selected.connect(self.on_image_strip_selected)
        self.image_display.add_image_requested.connect(self.on_load_image_file)
        self.image_display.clear_images_requested.connect(self.on_clear_image_flow)
        self.image_canvas.image_file_dropped.connect(self.load_image_from_path)
        self.data_tabs.addTab(self.image_display, "Image")

        self.result_panel = ModuleResultPanel(self.solution.global_variables)
        self.result_panel.setObjectName("resultPanel")
        # Neither tab page may pin the column wider than the measured floor, nor
        # taller than the splitter's measured share: the splitter honours the
        # configured sizes only when the panes can actually shrink to them.
        self.result_panel.setMinimumWidth(LM.MIN_RIGHT_COL_W)
        self.image_display.setMinimumHeight(0)
        self.result_panel.setMinimumHeight(0)
        self.data_tabs.addTab(self.result_panel, "Result")
        self.data_tabs.currentChanged.connect(self._on_data_tab_changed)
        self.split_right.addWidget(self.data_tabs)

        # ---- row 2: Current Result | History Result | Help -------------------
        self.result_display = ResultDisplayArea()
        self.result_display.setMinimumHeight(0)
        self.bottom_tabs = self.result_display.tabs
        self.results_table = self.result_display.log_table
        self.history_table = self.result_display.history_table
        self.lbl_help = self.result_display.lbl_help
        self.split_right.addWidget(self.result_display)

        self.split_right.setStretchFactor(0, 3)
        self.split_right.setStretchFactor(1, 2)
        # The splitter honours child minimum size hints over `setSizes`, and both
        # panes report a tall hint.  The heights are therefore driven from the
        # measured ratios in `_size_right_column`, which sets each pane's band.
        self._right_panes = (self.data_tabs, self.result_display)

        self.toolbox.rail_width_changed.connect(self._apply_reference_proportions)

        vbox.addWidget(self.split_right)
        dock.setWidget(container)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.property_dock = dock
        dock.setMinimumWidth(LM.MIN_RIGHT_COL_W)
        act_dock = dock.toggleViewAction()
        act_dock.setChecked(True)
        act_dock.setEnabled(False)
        self.dock_menu.addAction(act_dock)

        # Backwards-compatible aliases.
        self.tab_workspace_canvas = self.image_canvas
        self.image_result_pane = self.data_tabs.widget(0)

    def _init_module_log_dock(self):
        """Module-execution trace, kept off the workspace by default.

        The vendor's layout has no such surface, so to preserve the reference
        layout exactly this dock is hidden at start-up and reachable from
        `View > Panels > Module Log` or `System > Log Viewer`.  The per-module log
        is still needed for this project's diagnostics.
        """
        dock = QDockWidget("Module Log", self)
        dock.setObjectName("moduleLogDock")
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)

        # Reuse the result display area's log table (it is built but deliberately
        # not a tab of the vendor's 3-tab result block).
        self.module_log_table = self.result_display.log_table
        dock.setWidget(self.module_log_table)
        dock.setMinimumHeight(120)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.hide()
        self.module_log_dock = dock
        # Alias kept for existing callers: this is now the project's only bottom
        # dock, and it starts hidden so the workspace matches the reference.
        self.result_dock = dock
        self.dock_menu.addAction(dock.toggleViewAction())

    def _shortcut_help_text(self) -> str:
        return (
            "<b>Flow Diagram</b><br>"
            "Drag from a port to another module's port to create a wire &middot; "
            "Delete removes the selection &middot; Ctrl+Z / Ctrl+Y undo / redo &middot; "
            "right-drag pans &middot; wheel zooms &middot; double-click a Tool Box cell to insert.<br><br>"
            "<b>Image</b><br>Wheel zooms at the cursor &middot; drag to pan &middot; "
            "Draw ROI then drag on the image to set a region &middot; the ROI is written "
            "back into the selected module's parameters.<br><br>"
            "<b>Result</b><br>Double-click the link column (or right-click) to subscribe an output "
            "parameter to one of the 32 global variables."
        )

    def _init_status_bar(self):
        """Segmented status bar matching manual p.40 item 7.

        The advisory message text lives here rather than on a third toolbar row:
        a bottom strip costs no additional chrome height and can never compress
        the control strips above it.
        """
        sb = self.statusBar()
        sb.setSizeGripEnabled(True)

        self.lbl_component_state = QLabel("Component Config Completed")
        self.lbl_component_state.setObjectName("statusLeading")
        sb.addWidget(self.lbl_component_state)

        self.lbl_view_status = QLabel("Ready")
        self.lbl_view_status.setObjectName("statusMessage")
        sb.addWidget(self.lbl_view_status, 1)

        self.lbl_flow_time = QLabel("Flow 0.00ms")
        self.lbl_flow_time.setObjectName("statusSegment")
        sb.addPermanentWidget(self.lbl_flow_time)

        self.lbl_tool_count = QLabel("Tools  0")
        self.lbl_tool_count.setObjectName("statusSegment")
        sb.addPermanentWidget(self.lbl_tool_count)

        self.lbl_algo_time = QLabel("Algorithm 0.00ms")
        self.lbl_algo_time.setObjectName("statusSegment")
        sb.addPermanentWidget(self.lbl_algo_time)

        self.lbl_vm_version = QLabel("V4.3.0 Build20230510")
        self.lbl_vm_version.setObjectName("statusVersion")
        self.lbl_vm_version.setStyleSheet("color: #64748b; font-size: 10px; padding-left: 6px;")
        sb.addPermanentWidget(self.lbl_vm_version)

    # =====================================================================
    # Small helpers
    # =====================================================================
    def _on_data_tab_changed(self, index: int):
        """Re-run the result grid column model when the Image|Result pane shows."""
        panel = getattr(self, "result_panel", None)
        if panel is not None:
            panel.refresh_columns()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_chrome()
        # Every resize re-derives the measured column split: the ratios are the
        # layout contract, and a dock layout computed for the previous size leaves
        # the right column clipped or the canvas over-wide.  The residual
        # correction inside `_apply_reference_proportions` makes re-applying
        # idempotent, so this cannot oscillate.
        self._apply_reference_proportions()
        panel = getattr(self, "result_panel", None)
        if panel is not None:
            panel.refresh_columns()

    def _add_toolbar_button(self, tb: QToolBar, btn: QToolButton) -> QToolButton:
        """Add a button to a toolbar and remember its QWidgetAction.

        Visibility of a QToolBar widget is owned by the QWidgetAction that wraps
        it; hiding the button widget alone leaves the action (and its reserved
        space) in place, which is what pushed the toolbar tail into the overflow
        popup at narrower widths.
        """
        action = tb.addWidget(btn)
        self._toolbar_actions[btn] = action
        return btn

    def _set_button_visible(self, btn: QToolButton, visible: bool):
        if btn is None:
            return
        action = self._toolbar_actions.get(btn)
        if action is not None:
            action.setVisible(visible)
        btn.setVisible(visible)

    def _apply_responsive_chrome(self):
        """Keep every toolbar control reachable at narrow window widths.

        Qt pushes the tail of an over-long toolbar into an overflow popup once the
        strip runs out of room.  For an operator console that is a usability
        regression - a control you cannot see is a control you cannot use - so the
        chrome degrades explicitly and in a fixed order instead:

        >= 1560 px : everything
        >= 1220 px : drop the two secondary viewport tools
        <  1220 px : clamp the flow tab strip so the primary controls always fit
        """
        w = self.width()
        have_extra = w >= 1220

        for btn in (getattr(self, "btn_arrange", None),
                    getattr(self, "btn_fit", None),
                    getattr(self, "btn_zoom_100", None)):
            self._set_button_visible(btn, have_extra)

        if hasattr(self, "flow_tab_bar"):
            # Reserve room for the fixed controls in row 2 (3 flow buttons +
            # separator + 6 operation/viewport controls + margins).
            reserved = 26 * 6 + 11 + 30
            self.flow_tab_bar.setMaximumWidth(max(160, w - reserved - 60))

    def _apply_reference_proportions(self):
        """Split the window using the *measured* reference proportions.

        Every ratio comes from `vm_clone/ui/layout_metrics.py`, which is derived
        from pixel measurements of the vendor figures (see
        `docs/VISIONMASTER_STORYBOARD.md` §2).  The flanks are clamped to their
        minimum usable sizes so alignment survives at the smallest window.

        ``resizeDocks`` wants absolute widths for the lateral docks, and the dock
        separators take a few pixels off the central widget, so the canvas is the
        remainder and the right column is sized from the window width directly.
        """
        # Qt distributes the leftover width according to size hints, and the
        # central tab widget's hint is far larger than its usable minimum, which
        # squeezed the right column to its floor.  Pinning the canvas to the
        # measured minimum lets `resizeDocks` place both flanks exactly.
        self.centralWidget().setMinimumWidth(LM.MIN_CANVAS_W)

        # The dock area insets the client area by a few pixels (measured 6 px at
        # 1400 and 1600), so targeting the window width leaves the canvas ~1.4 %
        # wide.  Measure the laid-out content width once and re-derive the split
        # from it; the reference ratios then hold exactly.
        content = (self.tool_dock.width() + self.centralWidget().width()
                   + self.property_dock.width())
        flyout_open = getattr(self.toolbox, "flyout", None) is not None \
            and self.toolbox.flyout.isVisible()
        left, _canvas, right = LM.split_horizontal(
            content if content > 400 else self.width(), flyout_open=flyout_open)
        self.resizeDocks([self.property_dock], [right], Qt.Orientation.Horizontal)
        self.resizeDocks([self.tool_dock], [left], Qt.Orientation.Horizontal)

        self._size_right_column()

        # The first pass runs before Qt has finalized the dock frames, so the
        # content width it measured is the window width, not the client width.
        # A bounded deferred pass re-derives the split from the settled geometry,
        # which is what makes the measured ratios hold rather than land wide.
        if not getattr(self, "_layout_settling", False):
            self._layout_settling = True
            QTimer.singleShot(0, self._reapply_measured_split)

    def _reapply_measured_split(self):
        """Converge the measured split once Qt has settled the dock geometry.

        The canvas is the layout's leftover space, so it silently absorbs the
        fixed dock-frame overhead and any residual fed back into the docks makes
        the split oscillate.  The overhead is therefore measured directly
        (``content - left - right - canvas``) and solved for in one step.
        """
        total = (self.tool_dock.width() + self.centralWidget().width()
                 + self.property_dock.width())
        if total <= 400:
            return
        left, canvas_target, _right = LM.split_horizontal(
            total, flyout_open=self.toolbox.flyout.isVisible())
        overhead = (total - self.tool_dock.width()
                    - self.property_dock.width()
                    - self.centralWidget().width())
        right = max(LM.MIN_RIGHT_COL_W, total - left - canvas_target - overhead)
        self.resizeDocks([self.property_dock], [right], Qt.Orientation.Horizontal)
        self.resizeDocks([self.tool_dock], [left], Qt.Orientation.Horizontal)

        self._size_right_column()
        self._layout_settled = True
        if LM.DEBUG:
            total = (self.tool_dock.width() + self.centralWidget().width()
                     + self.property_dock.width())
            print(f"[layout-settled] content {total} overhead {overhead} -> l/c/r "
                  f"{self.tool_dock.width()}/{self.centralWidget().width()}/"
                  f"{self.property_dock.width()} "
                  f"ratios {self.tool_dock.width() / total:.4f}/"
                  f"{self.centralWidget().width() / total:.4f}/"
                  f"{self.property_dock.width() / total:.4f} "
                  f"split_right {self.split_right.sizes()}")

    def _size_right_column(self):
        """Set the right column's two bands to the measured heights.

        The panes' own size hints would otherwise hold the image block below its
        measured share, so each pane gets a matching maximum with a usability floor.
        """
        panes = getattr(self, "_right_panes", None)
        if not panes:
            return
        column_h = self._column_height()
        if column_h <= 160:
            return
        image_h, result_h = LM.split_right_column(column_h)
        # The maximum holds the band against the panes' tall size hints, which would
        # otherwise keep the image block below its measured share.  The minimum is
        # only the usability floor, not the band: a fixed minimum would also fix the
        # *window's* minimum height and the window could then never reach the
        # reference size.
        floors = (LM.MIN_IMAGE_H, LM.MIN_RESULT_TABLE_H)
        for pane, band, floor in zip(panes, (image_h, result_h), floors):
            pane.setMinimumHeight(floor)
            pane.setMaximumHeight(band)
        self.split_right.setSizes([image_h, result_h])

    def _column_height(self) -> int:
        """Height available to the right column, derived from the window size.

        Deriving this from the window rather than reading the dock's height back is
        what makes the first application correct: at construction time the dock has
        no size yet, and bands computed from an unsettled height would clamp the
        column permanently (the panes' min/max pair then blocks any growth).
        """
        used = (self.menuBar().height() + self.toolbar_resources.height()
                + self.toolbar_flows.height() + self.statusBar().height())
        return self.height() - used - 6

    def _apply_measured_stretch(self):
        """Release the vertical constraints before the measured bands are set.

        ``_size_right_column`` assigns each right-column pane its measured band, and
        any pre-existing minimum would fight it.  This hook therefore only clears
        those constraints; the bands themselves are applied from the measured ratios
        once Qt has settled the geometry.
        """
        self.data_tabs.setMinimumHeight(0)
        self.result_display.setMinimumHeight(0)

    def _set_status_badge(self, text: str, kind: str):
        palette = {
            "ok": (THEME["status_ok_bg"], THEME["status_ok_text"], THEME["status_ok_border"]),
            "warn": (THEME["status_warn_bg"], THEME["status_warn_text"], THEME["status_warn_border"]),
            "error": (THEME["status_error_bg"], THEME["status_error_text"], THEME["status_error_border"]),
            "run": (THEME["status_running_bg"], THEME["status_running_text"], THEME["status_running_border"]),
        }
        bg, fg, border = palette.get(kind, palette["ok"])
        self.lbl_global_status.setText(f" {text} ")
        self.lbl_global_status.setStyleSheet(
            f"font-weight: bold; font-size: 11px; padding: 2px 12px; border-radius: 2px; "
            f"background-color: {bg}; color: {fg}; border: 1px solid {border};"
        )

    def _info(self, title: str, message: str):
        QMessageBox.information(self, title, message)

    def _set_hint(self, text: str, timeout_ms: int = 0):
        """Advisory message lives in the status bar, never in a control strip."""
        self.lbl_view_status.setText(text)
        self.lbl_view_status.setToolTip(text)
        if timeout_ms:
            QTimer.singleShot(
                timeout_ms,
                lambda: (self.lbl_view_status.setText("Ready"),
                         self.lbl_view_status.setToolTip("Ready")),
            )

    def _flow_tab_text(self, flow_name: str, verdict: str, ms: float) -> str:
        """Compact flow tab label: state dot, name, verdict, cycle time.

        A middle-elided name keeps the verdict and timing readable no matter how
        long the flow name is (the reference shows the same three fields).
        """
        name = flow_name if len(flow_name) <= 16 else flow_name[:7] + "…" + flow_name[-7:]
        return f"● {name}  {verdict}  {ms:.0f}ms"

    # =====================================================================
    # Resource toolbar slots (manual p.70)
    # =====================================================================
    @pyqtSlot()
    def on_undo(self):
        if self.flow_scene.undo_stack.canUndo():
            text = self.flow_scene.undo_stack.undoText()
            self.flow_scene.undo_stack.undo()
            self._set_hint(f"Undo: {text}", 3000)
            self.run_pipeline_step()
        else:
            self._set_hint("Nothing to undo", 2000)

    @pyqtSlot()
    def on_redo(self):
        if self.flow_scene.undo_stack.canRedo():
            text = self.flow_scene.undo_stack.redoText()
            self.flow_scene.undo_stack.redo()
            self._set_hint(f"Redo: {text}", 3000)
            self.run_pipeline_step()
        else:
            self._set_hint("Nothing to redo", 2000)

    @pyqtSlot(bool)
    def on_toggle_lock(self, locked: bool):
        self._locked = locked
        self.flow_scene.set_locked(locked)
        self._set_hint("Editing locked" if locked else "Editing unlocked", 2500)

    @pyqtSlot()
    def on_camera_set(self):
        from vm_clone.ui.camera_dialog import CameraManagementDialog
        src_node = None
        for nid, node in self.pipeline.nodes.items():
            if node.tool_name == "Image Source":
                src_node = node
                break

        curr_dev = src_node.get_param("camera_device", "") if src_node else ""
        dlg = CameraManagementDialog(parent=self, current_device_id=curr_dev)

        def _apply_selected_cam(dev_id: str, params: dict):
            nonlocal src_node
            if src_node is None:
                src_node_id = f"src_{int(time.time() * 1000) % 10000}"
                from vm_clone.core.registry import create_tool_instance
                src_node = create_tool_instance("Image Source", src_node_id, "01_Acquisition")
                self.pipeline.add_node(src_node)
                self.flow_scene.build_from_pipeline(preserve_positions=True)

            # Map camera type
            from vm_clone.core.camera_manager import CameraManager
            info = CameraManager.get_instance().get_device(dev_id)
            if info:
                src_node.set_param("source_type", info.camera_type)
            else:
                src_node.set_param("source_type", "Camera")

            src_node.set_param("camera_device", dev_id)
            for pk, pv in params.items():
                src_node.set_param(pk, pv)

            if "webcam_" in dev_id:
                try:
                    src_node.set_param("camera_index", int(dev_id.split("webcam_")[1]))
                except Exception:
                    pass

            self.run_pipeline_step()
            self._set_hint(f"Bound camera '{info.name if info else dev_id}' to active flow", 3500)

        dlg.camera_selected.connect(_apply_selected_cam)
        dlg.exec()

    @pyqtSlot()
    def on_controller_management(self):
        self._info(
            "Controller Management",
            "No external motion controller is bound to this solution.\n\n"
            "Add a controller to exchange inspection results (position, verdict)\n"
            "with a PLC or robot over the Communication Management channel."
        )

    @pyqtSlot()
    def on_global_trigger(self):
        self._info(
            "Global Trigger",
            "Global triggers fire a flow from an external event or a string command.\n\n"
            "Available event sources: hardware I/O line, TCP string, timer."
        )

    @pyqtSlot()
    def on_global_script(self):
        script = getattr(self, "_global_script_text",
                         "# Global script: runs once per flow cycle\n"
                         "# Available: GlobalVariable, inputs, results\n"
                         "def process(context):\n"
                         "    context.set_global('CycleStamp', 1)\n")
        text, ok = QInputDialog.getMultiLineText(
            self, "Global Script", "Global script source (executed by the solution):", script
        )
        if ok:
            self._global_script_text = text
            self._set_hint("Global script updated", 3000)

    @pyqtSlot()
    def on_help_manual(self):
        self._info(
            "User Manual",
            "Apex Industrial Vision Studio - Operator Manual\n\n"
            "1. Drag a module from the Tool Box onto the flow canvas.\n"
            "2. Wire the Image output of the acquisition module into the next module.\n"
            "3. Set parameters in the Property Inspector and draw the ROI on the image.\n"
            "4. Press Once to execute the flow, or Continuously to loop it.\n"
            "5. Read per-module verdicts in the Result Display and export them to CSV."
        )

    @pyqtSlot()
    def on_help_shortcuts(self):
        self._info("Keyboard Shortcuts",
                   "Ctrl+N  New Solution        Ctrl+O  Open Solution\n"
                   "Ctrl+S  Save Solution       Ctrl+Shift+S  Save As\n"
                   "Ctrl+Z  Undo                Ctrl+Y  Redo\n"
                   "Ctrl+1  Flow Diagram        Ctrl+2  Operation Interface\n"
                   "Ctrl+3  Multi-Flow Overview Ctrl+0  Fit Modules to View\n"
                   "Delete  Remove selected modules / wires\n"
                   "F1      User Manual")

    @pyqtSlot()
    def on_switch_language(self):
        languages = ["English", "简体中文"]
        name, ok = QInputDialog.getItem(
            self, "Language", "Interface language:", languages, 0, False
        )
        if ok and name != "English":
            self._info("Language",
                       "Chinese localisation resources are not bundled with this build.\n"
                       "The interface remains in English.")
        elif ok:
            self._set_hint("Interface language: English", 2500)

    @pyqtSlot()
    def on_version_info(self):
        self._info(
            "Version Information",
            "Apex Industrial Vision Studio v4.3\n"
            "Engine: Python 3.12 / PyQt6 / OpenCV 4.x / NumPy\n"
            "Flow engine: typed multi-flow DAG executor\n"
            "Build: reference-aligned workspace (VisionMaster-style UI)"
        )

    @pyqtSlot()
    def on_show_log_viewer(self):
        """Show the per-module execution trace (kept off the main workspace)."""
        self.module_log_dock.show()
        self.module_log_dock.raise_()
        self._set_hint("Module Log opened", 2500)

    @pyqtSlot()
    def on_performance_options(self):
        self._info(
            "Performance Options",
            "Continuous cycle interval is configured per flow\n"
            "(right-click a flow tab -> Flow Settings...).\n\n"
            "Image processing runs on the flow executor so the interface stays responsive."
        )

    @pyqtSlot()
    def on_hardware_trigger_settings(self):
        self._info(
            "Hardware Trigger Settings",
            "Trigger source: Software (free-run) / Line 0 / Encoder\n"
            "Debounce: 0 ms      Strobe delay: 0 us\n\n"
            "This build runs the flow from the software trigger."
        )

    @pyqtSlot()
    def on_communication_config(self):
        self._info(
            "Communication Management",
            "Send Event: TCP Client -> 127.0.0.1:8000 (JSON payload)\n"
            "Receive Event: disabled\n"
            "Heartbeat: 1000 ms\n\n"
            "Use the TCP Send module inside a flow to emit a result payload."
        )

    @pyqtSlot()
    def on_calibration_wizard(self):
        issues = [
            {"severity": "info", "node_id": "Wizard",
             "message": "N-point spatial calibration converts pixel (u, v) into world (X, Y) in mm."},
            {"severity": "info", "node_id": "Wizard",
             "message": "Add an 'N-Point Calibration' module to the flow and set Calibration Mode."},
        ]
        FlowValidationDialog(issues, self, title="Calibration Wizard").exec()

    @pyqtSlot()
    def on_open_lens_calibration_wizard(self):
        from vm_clone.ui.camera_calibration_dialog import CameraCalibrationDialog

        curr_img = None
        if hasattr(self, "_image_flow") and self._image_flow and 0 <= self._current_image_flow_index < len(self._image_flow):
            curr_img = self._image_flow[self._current_image_flow_index].get("image")
        elif hasattr(self, "image_canvas") and self.image_canvas._raw_cv_image is not None:
            curr_img = self.image_canvas._raw_cv_image

        dlg = CameraCalibrationDialog(curr_img, self)
        dlg.calibration_applied.connect(self.on_lens_calibration_applied)
        dlg.exec()

    def on_lens_calibration_applied(self, calib_data: dict):
        """Applies calibration results directly to the active pipeline."""
        calib_node_id = None
        for nid, node in self.pipeline.nodes.items():
            if node.tool_name == "Lens Distortion Calibration":
                calib_node_id = nid
                break

        if calib_node_id is None:
            calib_node_id = f"lens_calib_{int(time.time())}"
            calib_tool = create_tool_instance("Lens Distortion Calibration", calib_node_id, "LensDistortionCorrection")
            if calib_tool:
                self.pipeline.add_node(calib_tool)
                src_id = None
                for nid, node in self.pipeline.nodes.items():
                    if node.tool_name == "Image Source":
                        src_id = nid
                        break
                if src_id:
                    self.pipeline.connect(src_id, "Image", calib_node_id, "Image", force=True)

        node = self.pipeline.nodes.get(calib_node_id)
        if node:
            intrinsics = calib_data.get("intrinsics", {})
            dist = calib_data.get("distortion", {})
            node.set_param("mode", "Manual Coefficients")
            node.set_param("manual_fx", intrinsics.get("fx", 650.0))
            node.set_param("manual_fy", intrinsics.get("fy", 650.0))
            node.set_param("manual_cx", intrinsics.get("cx", 400.0))
            node.set_param("manual_cy", intrinsics.get("cy", 300.0))
            node.set_param("manual_k1", dist.get("k1", -0.15))
            node.set_param("manual_k2", dist.get("k2", 0.03))
            node.set_param("manual_p1", dist.get("p1", 0.0))
            node.set_param("manual_p2", dist.get("p2", 0.0))

            if hasattr(self, "flow_scene"):
                self.flow_scene.build_from_pipeline(preserve_positions=True)
            if hasattr(self, "inspector"):
                self.inspector.set_selected_node(node)

    def on_open_plugin_manager(self, initial_tab: int = 0):
        from vm_clone.ui.plugin_dialog import PluginManagerDialog
        dlg = PluginManagerDialog(self, initial_tab=initial_tab)
        dlg.plugins_changed.connect(lambda: self.toolbox.refresh_tools() if hasattr(self, "toolbox") else None)
        dlg.exec()

    @pyqtSlot(bool)
    def on_toggle_operation_panel(self, checked: bool):
        self.tab_workspace.setCurrentIndex(1 if checked else 0)

    @pyqtSlot(bool)
    def on_toggle_histogram(self, checked: bool):
        self.image_canvas.set_show_histogram(checked)
        for other in (getattr(self, "btn_hist", None), getattr(self, "act_layer_hist", None)):
            if other is None:
                continue
            self._set_layer_action_state(other, checked)

    # =====================================================================
    # Multi-Flow overview slots (manual p.95)
    # =====================================================================
    @pyqtSlot(str)
    def on_overview_flow_activated(self, flow_name: str):
        if flow_name not in self.solution.flows:
            return
        self.solution.active_flow_name = flow_name
        idx = list(self.solution.flows.keys()).index(flow_name)
        self.flow_tab_bar.setCurrentIndex(idx)
        self.tab_workspace.setCurrentIndex(0)

    @pyqtSlot(str)
    def on_overview_flow_run(self, flow_name: str):
        flow = self.solution.flows.get(flow_name)
        if not flow:
            return
        flow.execute_flow(global_vars=self.solution.global_variables)
        self.flow_overview.refresh_status()
        self._refresh_flow_tabs()
        if flow_name == self.solution.active_flow_name:
            self.run_pipeline_step()
        self._set_hint(f"Executed flow '{flow_name}'", 3000)

    @pyqtSlot(str, bool)
    def on_overview_flow_loop(self, flow_name: str, looping: bool):
        self._set_hint(
            f"Flow '{flow_name}' {'looping' if looping else 'single shot'}", 2500
        )

    @pyqtSlot(str)
    def on_overview_flow_settings(self, flow_name: str):
        flow = self.solution.flows.get(flow_name)
        if not flow:
            return
        dlg = FlowSettingsDialog(flow, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.flow_overview.refresh_status()
            self._set_hint(f"Updated parameters for '{flow_name}'", 2500)

    @pyqtSlot()
    def on_open_global_vars(self):
        dlg = GlobalVariablesDialog(self.solution.global_variables, self)
        dlg.exec()

    def _refresh_flow_tabs(self):
        self.flow_tab_bar.blockSignals(True)
        while self.flow_tab_bar.count() > 0:
            self.flow_tab_bar.removeTab(0)

        active_idx = 0
        for i, (fname, flow) in enumerate(self.solution.flows.items()):
            has_results = bool(flow.last_results)
            overall_ok = True
            if has_results:
                overall_ok = all(r.status != ToolStatus.NG for r in flow.last_results.values())
            if not has_results:
                color = THEME["text_secondary"]
                verdict = "NOT RUN"
            elif overall_ok:
                color = THEME["status_ok_text"]
                verdict = "PASS"
            else:
                color = THEME["status_error_text"]
                verdict = "FAIL"
            # The tab carries the reference's state dot, the flow name, the
            # verdict and the last cycle time; the tooltip expands on it.
            self.flow_tab_bar.addTab(self._flow_tab_text(fname, verdict, flow.last_flow_time_ms))
            self.flow_tab_bar.setTabTextColor(i, QColor(color))
            self.flow_tab_bar.setTabToolTip(
                i,
                f"{fname}\nVerdict: {verdict}\nLast flow time: {flow.last_flow_time_ms:.2f} ms\n"
                f"Modules: {len(flow.nodes)}   Runs: {flow.execution_count}"
            )
            if fname == self.solution.active_flow_name:
                active_idx = i

        self.flow_tab_bar.setCurrentIndex(active_idx)
        self.flow_tab_bar.blockSignals(False)

    @pyqtSlot(int)
    def on_flow_tab_changed(self, index: int):
        flow_names = list(self.solution.flows.keys())
        if 0 <= index < len(flow_names):
            target_name = flow_names[index]
            self.solution.active_flow_name = target_name
            active_pipe = self.solution.get_active_flow()
            self.flow_scene.pipeline = active_pipe
            self.flow_scene.build_from_pipeline()
            self.run_pipeline_step()
            self.statusBar().showMessage(f"Switched to sub-flow: {target_name}", 2000)

    @pyqtSlot(int)
    def on_flow_tab_closed(self, index: int):
        flow_names = list(self.solution.flows.keys())
        if len(flow_names) <= 1:
            self.statusBar().showMessage("Cannot close primary sub-flow.", 2500)
            return
        if 0 <= index < len(flow_names):
            target_name = flow_names[index]
            self.solution.remove_flow(target_name)
            self._refresh_flow_tabs()
            self.flow_scene.pipeline = self.solution.get_active_flow()
            self.flow_scene.build_from_pipeline()
            self.run_pipeline_step()
            self.statusBar().showMessage(f"Removed sub-flow: {target_name}", 2500)

    @pyqtSlot(QPoint)
    def on_flow_tab_context_menu(self, pos: QPoint):
        tab_idx = self.flow_tab_bar.tabAt(pos)
        flow_names = list(self.solution.flows.keys())
        if not (0 <= tab_idx < len(flow_names)):
            return

        flow_name = flow_names[tab_idx]
        target_flow = self.solution.flows[flow_name]

        menu = QMenu(self)
        act_rename = menu.addAction(get_action_icon("edit"), f"Rename '{flow_name}'...")
        act_copy = menu.addAction(get_action_icon("copy"), f"Duplicate Flow")
        act_settings = menu.addAction(get_action_icon("settings"), f"Flow Settings...")
        menu.addSeparator()
        act_export_xml = menu.addAction(get_action_icon("save"), f"Export Flow as XML...")
        act_export = menu.addAction(get_action_icon("save"), f"Export Flow (.prc / .xml)...")
        act_import = menu.addAction(get_action_icon("open"), f"Import Flow (.prc / .xml)...")
        menu.addSeparator()
        act_validate = menu.addAction(get_action_icon("validate"), f"Validate Flow Integrity")
        act_del = menu.addAction(get_action_icon("stop"), f"Delete Flow")
        if len(flow_names) <= 1:
            act_del.setEnabled(False)

        action = menu.exec(self.flow_tab_bar.mapToGlobal(pos))
        if action == act_rename:
            new_name, ok = QInputDialog.getText(self, "Rename Flow", "New flow name:", text=flow_name)
            if ok and new_name and new_name != flow_name:
                if new_name in self.solution.flows:
                    QMessageBox.warning(self, "Rename Error", f"A flow named '{new_name}' already exists.")
                else:
                    self.solution.flows[new_name] = self.solution.flows.pop(flow_name)
                    target_flow.name = new_name
                    if self.solution.active_flow_name == flow_name:
                        self.solution.active_flow_name = new_name
                    self._refresh_flow_tabs()
                    self.statusBar().showMessage(f"Renamed flow to '{new_name}'", 2500)

        elif action == act_copy:
            dup_flow = self.solution.duplicate_flow(flow_name)
            self._refresh_flow_tabs()
            self.statusBar().showMessage(f"Duplicated flow '{flow_name}' -> '{dup_flow.name}'", 3000)

        elif action == act_settings:
            dlg = FlowSettingsDialog(target_flow, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.statusBar().showMessage(f"Updated flow parameters for '{flow_name}'", 2500)

        elif action == act_export_xml:
            fpath, _ = QFileDialog.getSaveFileName(
                self, f"Export Flow '{flow_name}' as XML", f"{flow_name}.xml",
                "XML Flow Files (*.xml);;All Files (*.*)"
            )
            if fpath:
                try:
                    self.solution.export_flow(flow_name, fpath)
                    QMessageBox.information(self, "Export Flow", f"Flow exported successfully to XML:\n{fpath}")
                except Exception as e:
                    QMessageBox.critical(self, "Export Error", str(e))

        elif action == act_export:
            fpath, _ = QFileDialog.getSaveFileName(
                self, f"Export Flow '{flow_name}'", f"{flow_name}.xml",
                "XML Flow Files (*.xml);;Flow Procedure (*.prc);;JSON Files (*.json);;All Files (*.*)"
            )
            if fpath:
                try:
                    self.solution.export_flow(flow_name, fpath)
                    QMessageBox.information(self, "Export Flow", f"Flow exported successfully to:\n{fpath}")
                except Exception as e:
                    QMessageBox.critical(self, "Export Error", str(e))

        elif action == act_import:
            fpath, _ = QFileDialog.getOpenFileName(
                self, "Import Flow Procedure", "",
                "XML Flow Files (*.xml);;Flow Procedure (*.prc);;JSON Files (*.json);;All Files (*.*)"
            )
            if fpath:
                try:
                    imp_flow = self.solution.import_flow(fpath)
                    self._refresh_flow_tabs()
                    QMessageBox.information(self, "Import Flow", f"Imported flow '{imp_flow.name}' successfully.")
                except Exception as e:
                    QMessageBox.critical(self, "Import Error", str(e))

        elif action == act_validate:
            self.on_validate_active_flow()

        elif action == act_del:
            self.on_flow_tab_closed(tab_idx)

    @pyqtSlot()
    def on_validate_active_flow(self):
        issues = self.pipeline.validate_flow()
        dlg = FlowValidationDialog(issues, self)
        dlg.exec()

    @pyqtSlot(str)
    def on_connection_rejected(self, reason: str):
        self.statusBar().showMessage(f"Connection Rejected: {reason}", 4000)
        self.lbl_global_status.setText(" REJECTED ")
        self.lbl_global_status.setStyleSheet(
            f"font-weight: bold; font-size: 11px; padding: 4px 12px; border-radius: 4px; "
            f"background-color: {THEME['status_warn_bg']}; color: {THEME['status_warn_text']}; "
            f"border: 1px solid {THEME['status_warn_border']};"
        )

    @pyqtSlot()
    def on_add_flow_tab(self):
        new_name = f"Flow{len(self.solution.flows) + 1}"
        new_pipe = self.solution.add_flow(new_name)
        src = create_tool_instance("Image Source", f"src_{int(time.time()*1000)%10000}", "01_Acquisition")
        new_pipe.add_node(src)
        self.solution.active_flow_name = new_name
        self._refresh_flow_tabs()
        self.flow_scene.pipeline = new_pipe
        self.flow_scene.build_from_pipeline()
        self.run_pipeline_step()
        self.statusBar().showMessage(f"Created sub-flow: {new_name}", 3000)

    @pyqtSlot()
    def on_run_all_flows(self):
        all_results = self.solution.execute_all_flows()
        self._refresh_flow_tabs()
        self.run_pipeline_step()
        self.statusBar().showMessage(f"Executed {len(all_results)} sub-flows in solution.", 3000)

    @pyqtSlot(bool)
    def on_toggle_layer_all(self, checked: bool):
        # "All Overlays" is a master switch: it does not disable the individual
        # sub-switches (their state is preserved and re-applied on re-enable).
        self.image_canvas.set_show_overlays(checked)

    def on_update_layers(self):
        self.image_canvas.set_overlay_visibility(
            all_overlays=self.act_layer_all.isChecked(),
            rois=self.act_layer_rois.isChecked(),
            measurements=self.act_layer_metrics.isChecked(),
            datums=self.act_layer_datums.isChecked()
        )

    @pyqtSlot()
    def on_run_once(self):
        self.run_pipeline_step()
        self._set_hint("Flow executed once", 2000)

    @pyqtSlot(bool)
    def on_toggle_continuous(self, checked: bool):
        for btn in (self.btn_continuous, self.btn_loop_flow):
            if btn.isChecked() != checked:
                btn.blockSignals(True)
                btn.setChecked(checked)
                btn.blockSignals(False)
        if checked:
            interval = max(10, int(self.pipeline.run_interval_ms))
            self.run_timer.start(interval)
            self.btn_continuous.setToolTip("Continuous execution running - click to stop")
            self._set_status_badge("RUNNING", "run")
        else:
            self.run_timer.stop()
            self.btn_continuous.setToolTip("Continuously - execute the flow in a loop")
            self._set_hint("Continuous execution stopped", 2000)

    @pyqtSlot()
    def on_stop(self):
        self.run_timer.stop()
        for btn in (self.btn_continuous, self.btn_loop_flow):
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
        self._set_status_badge("STOPPED", "warn")
        self.lbl_component_state.setText("Stopped")
        self._set_hint("All flows stopped", 2500)

    @pyqtSlot(bool)
    def on_toggle_roi_mode(self, enabled: bool):
        self.image_canvas.set_draw_roi_mode(enabled)
        if enabled:
            self.focus_image_view()
            self._set_hint("Drag on the image to define the ROI", 4000)

    @pyqtSlot()
    def on_start_roi_draw(self):
        self.btn_draw_roi.setChecked(True)
        self.focus_image_view()
        self._set_hint("Drag on the image to define the ROI", 4000)

    def focus_image_view(self):
        """Bring the image viewport forward with enough height to draw on.

        The result grid shares the Image|Result column with the viewport, so ROI
        drawing also raises the canvas share of that splitter.
        """
        if hasattr(self, "data_tabs"):
            self.data_tabs.setCurrentIndex(0)
        if hasattr(self, "split_right") and self.split_right.count() >= 3:
            # Give the image the bulk of the display block while drawing.
            sizes = self.split_right.sizes()
            total = sum(sizes) or 1
            self.split_right.setSizes([int(total * 0.55), int(total * 0.20),
                                       max(120, total - int(total * 0.55) - int(total * 0.20))])
        if hasattr(self, "property_dock"):
            self.property_dock.show()
        self.image_canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    @pyqtSlot(list)
    def on_canvas_roi_changed(self, roi: list):
        self.btn_draw_roi.setChecked(False)
        # The ROI is written straight into the selected module's parameters, which
        # is where the reference keeps it (the module configuration window shows it).
        tool = self.pipeline.nodes.get(self.selected_node_id)
        if tool is not None:
            tool.set_param("roi", list(roi))
        self._set_hint(f"ROI applied: {roi}", 3000)
        self.run_pipeline_step()

    def run_pipeline_step(self):
        t0 = time.perf_counter()
        results = self.pipeline.execute_flow(global_vars=self.solution.global_variables)
        total_ms = (time.perf_counter() - t0) * 1000.0

        current_img = None
        all_overlays = []
        overall_ok = True
        algo_ms = 0.0
        failed_modules = []

        for nid, res in results.items():
            node = self.pipeline.nodes.get(nid)
            if not node:
                continue

            self.flow_scene.update_node_status(nid, res.status, res.elapsed_ms)
            algo_ms += res.elapsed_ms

            if "Image" in res.outputs and res.outputs["Image"] is not None:
                current_img = res.outputs["Image"]

            all_overlays.extend(res.overlays)
            if res.status == ToolStatus.NG:
                overall_ok = False
                failed_modules.append(node.name)

        if current_img is not None and (algo_ms <= 0.0):
            algo_ms = self.pipeline.last_flow_time_ms
        if current_img is None:
            err_msg = ""
            for nid in self.pipeline.execution_order:
                r = results.get(nid)
                if r and r.status in (ToolStatus.NG, ToolStatus.ERROR) and r.message:
                    err_msg = r.message
                    break
            if err_msg:
                self.image_canvas.set_empty_state("Acquisition / Processing Failed", is_error=True, subtext=err_msg)
            else:
                self.image_canvas.set_empty_state("No Image Source", is_error=False)

        if self.selected_node_id in self.pipeline.nodes:
            sel_res = results.get(self.selected_node_id)
            sel_img = sel_res.outputs.get("Image") if sel_res else None
            if sel_img is None:
                sel_img = self._get_input_image_for_node(self.selected_node_id)
            if sel_img is not None:
                self.image_canvas.set_cv_image(sel_img, sel_res.overlays if sel_res else [])
            else:
                self.image_canvas.set_cv_image(current_img, all_overlays)
        else:
            self.image_canvas.set_cv_image(current_img, all_overlays)

        self._refresh_image_display(results)

        self.results_table.setRowCount(0)
        for nid in self.pipeline.execution_order:
            res = results.get(nid)
            node = self.pipeline.nodes.get(nid)
            if not res or not node:
                continue

            row = self.results_table.rowCount()
            self.results_table.insertRow(row)

            self.results_table.setItem(row, 0, QTableWidgetItem(node.name))
            self.results_table.setItem(row, 1, QTableWidgetItem(node.tool_name))

            is_pass = (res.status == ToolStatus.OK)
            st_item = QTableWidgetItem(res.status.value.upper())
            st_color = QColor(THEME['status_ok_text']) if is_pass else QColor(THEME['status_error_text'])
            st_item.setForeground(st_color)
            st_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            self.results_table.setItem(row, 2, st_item)

            self.results_table.setItem(row, 3, QTableWidgetItem(f"{res.elapsed_ms:.2f} ms"))
            self.results_table.setItem(row, 4, QTableWidgetItem(res.message))

        self._append_history_row(overall_ok, failed_modules, results)
        self._update_status_segments(algo_ms, total_ms)

        if overall_ok:
            self._set_status_badge("PASS", "ok")
        else:
            self._set_status_badge("FAIL", "error")

        cur_idx = self.flow_tab_bar.currentIndex()
        if cur_idx >= 0:
            self._set_flow_tab_label(cur_idx, self.solution.active_flow_name, overall_ok)

        if self.selected_node_id in self.pipeline.nodes:
            res = results.get(self.selected_node_id)
            node = self.pipeline.nodes[self.selected_node_id]
            # Two views of the same module result, mirroring the vendor layout:
            # the compact tree inside the image display column (region 6) and the
            # per-parameter table in the result display area (region 12).
            self.result_panel.set_module_result(node.name, res)
            self.result_display.set_module_result(node.name, res, node.tool_name)
        elif results and not self.pipeline.nodes:
            self.result_display.set_module_result("", None)

        if getattr(self, "flow_overview", None) is not None:
            self.flow_overview.refresh_status()

        # Check Hikrobot Stop Flow Executed NG behavior
        if not overall_ok and self.pipeline.stop_on_ng and self.run_timer.isActive():
            self.on_stop()
            self.statusBar().showMessage(
                "Flow stopped automatically: NG defect detected (Stop on NG active).", 5000
            )

        # Check HikRobot Auto switch in image strip
        if hasattr(self, "image_display") and self.image_display.btn_auto.isChecked() and len(self._image_flow) > 1:
            next_idx = (self._current_image_flow_index + 1) % len(self._image_flow)
            self._current_image_flow_index = next_idx
            next_item = self._image_flow[next_idx]
            for nid, node in self.pipeline.nodes.items():
                if node.tool_name == "Image Source":
                    if next_item.get("path"):
                        node.set_param("source_type", "File")
                        node.set_param("file_path", next_item["path"])
                    if next_item.get("image") is not None:
                        node._override_image = next_item["image"]
                        node._override_name = next_item["name"]
                    break

    def _init_default_image_flow(self):
        """Seed the image flow with initial sample images (golden PCB and defect sample)."""
        self._image_flow = []
        self._current_image_flow_index = 0
        samples_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "samples"))

        # 1. Golden PCB sample
        pcb_path = os.path.join(samples_dir, "pcb_sample.png")
        if os.path.exists(pcb_path):
            img1 = cv2.imread(pcb_path)
            if img1 is not None:
                self._image_flow.append({
                    "name": "pcb_sample.png",
                    "path": pcb_path,
                    "image": img1
                })

        # 2. Defect PCB sample
        defect_path = os.path.join(samples_dir, "pcb_sample_defect.png")
        if os.path.exists(defect_path):
            img2 = cv2.imread(defect_path)
            if img2 is not None:
                self._image_flow.append({
                    "name": "pcb_sample_defect.png",
                    "path": defect_path,
                    "image": img2
                })
        elif len(self._image_flow) >= 1 and self._image_flow[0]["image"] is not None:
            def_img = self._image_flow[0]["image"].copy()
            cv2.line(def_img, (285, 270), (415, 330), (0, 0, 240), 3)
            cv2.circle(def_img, (350, 300), 12, (0, 0, 255), -1)
            self._image_flow.append({
                "name": "pcb_sample_defect.png",
                "path": None,
                "image": def_img
            })

        # Preload the first image into Image Source tool
        if self._image_flow:
            first_item = self._image_flow[0]
            for nid, node in self.pipeline.nodes.items():
                if node.tool_name == "Image Source":
                    if first_item.get("path"):
                        node.set_param("source_type", "File")
                        node.set_param("file_path", first_item["path"])
                    if first_item.get("image") is not None:
                        node._override_image = first_item["image"]
                        node._override_name = first_item["name"]
                    break

    def _refresh_image_display(self, results: dict):
        """Label the image area and populate its image strip (manual §5.2.3).

        The strip lists the flow of images added (image pool), not outputs from different nodes.
        """
        display = getattr(self, "image_display", None)
        if display is None:
            return

        self._last_results = dict(results or {})

        node = self.pipeline.nodes.get(self.selected_node_id)
        if node is not None:
            display.set_source_label(
                f"{node.name}.Output Image",
                f"{node.name} [{node.tool_name}] output image",
            )
        else:
            display.set_source_label("Flow output image")

        # If image flow is empty, seed from current Image Source tool or results
        if not getattr(self, "_image_flow", None):
            self._image_flow = []
            src_img = None
            src_path = None
            for nid, n in self.pipeline.nodes.items():
                if n.tool_name == "Image Source":
                    res = results.get(nid)
                    if res and res.outputs.get("Image") is not None:
                        src_img = res.outputs["Image"]
                    src_path = n.get_param("file_path", None)
                    break
            if src_img is not None:
                self._image_flow.append({
                    "name": os.path.basename(src_path) if src_path else "Default Sample",
                    "path": src_path,
                    "image": src_img
                })

        labels = [item["name"] for item in self._image_flow]
        if not labels:
            display.set_frames([])
            return

        current = max(0, min(self._current_image_flow_index, len(labels) - 1))
        self._current_image_flow_index = current
        display.set_frames(labels, current)
        for idx, item in enumerate(self._image_flow):
            if item.get("image") is not None:
                display.set_frame_thumbnail(idx, item["image"])
        display.mark_current_frame(self.image_canvas.current_pixmap())

    @pyqtSlot(int)
    def on_image_strip_selected(self, row: int):
        """Show the added image selected by the operator and execute the flow with it."""
        if getattr(self, "_strip_selecting", False):
            return
        self._strip_selecting = True
        try:
            flow = getattr(self, "_image_flow", [])
            if not (0 <= row < len(flow)):
                return
            self._current_image_flow_index = row
            item = flow[row]

            # Feed this added image into the active flow's Image Source
            src_tool = None
            for nid, node in self.pipeline.nodes.items():
                if node.tool_name == "Image Source":
                    src_tool = node
                    break

            if src_tool is not None:
                if item.get("path"):
                    src_tool.set_param("source_type", "File")
                    src_tool.set_param("file_path", item["path"])
                if item.get("image") is not None:
                    src_tool._override_image = item["image"]
                    src_tool._override_name = item["name"]

            # Re-run pipeline against the selected image in the flow
            self.run_pipeline_step()
        finally:
            self._strip_selecting = False

    def _update_status_segments(self, algo_ms: float, total_ms: float):
        # The reference status bar carries exactly three right-hand segments:
        # Flow / Tools / Algorithm (see `ui_crops/ref_statusbar.png`).
        self.lbl_tool_count.setText(f"Tools  {len(self.pipeline.nodes)}")
        self.lbl_flow_time.setText(f"Flow {self.pipeline.last_flow_time_ms:.2f}ms")
        self.lbl_algo_time.setText(f"Algorithm {algo_ms:.2f}ms")
        self.lbl_component_state.setText(
            "Component Config Completed" if self.pipeline.validate_flow() else "Component Config Incomplete"
        )
        if hasattr(self, "flow_view") and hasattr(self.flow_view, "update_telemetry"):
            self.flow_view.update_telemetry(self.pipeline.last_flow_time_ms, len(self.pipeline.nodes), algo_ms)

    def _append_history_row(self, overall_ok: bool, failed_modules: list, results: dict):
        if not hasattr(self, "history_table"):
            return
        row = self.history_table.rowCount()
        self.history_table.insertRow(row)

        verdict = "PASS" if overall_ok else "NG"
        cells = [
            str(self.pipeline.execution_count),
            self.solution.active_flow_name,
            verdict,
            f"{self.pipeline.last_flow_time_ms:.2f} ms",
            ", ".join(failed_modules) if failed_modules else "-",
            self._history_details(results, overall_ok),
        ]
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if col == 2:
                item.setForeground(
                    QColor(THEME['status_ok_text']) if overall_ok else QColor(THEME['status_error_text'])
                )
                item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            self.history_table.setItem(row, col, item)

        if self.history_table.rowCount() > 500:
            self.history_table.removeRow(0)
        self.history_table.scrollToBottom()

    def _history_details(self, results: dict, overall_ok: bool) -> str:
        if overall_ok:
            return f"{len(results)} module(s) verified OK"
        msgs = [r.message for r in results.values() if r.status == ToolStatus.NG and r.message]
        return "; ".join(msgs) if msgs else "NG verdict reported"

    def _set_flow_tab_label(self, index: int, flow_name: str, overall_ok: bool):
        flow = self.solution.flows.get(flow_name)
        dot = "●"
        if self.run_timer.isActive():
            color = "#38bdf8"
            verdict = "RUNNING"
        elif overall_ok:
            color = THEME["status_ok_text"]
            verdict = "PASS"
        else:
            color = THEME["status_error_text"]
            verdict = "FAIL"
        ms = flow.last_flow_time_ms if flow else 0.0
        self.flow_tab_bar.setTabText(index, self._flow_tab_text(flow_name, verdict, ms))
        self.flow_tab_bar.setTabTextColor(index, QColor(color))
        self.flow_tab_bar.setTabToolTip(
            index,
            f"{flow_name}\nVerdict: {verdict}\nLast flow time: {ms:.2f} ms\n"
            f"Modules: {len(flow.nodes) if flow else 0}   Runs: {flow.execution_count if flow else 0}"
        )

    def _on_module_connection_changed(self, inst_id: str, port_name: str):
        self.flow_scene.build_from_pipeline(preserve_positions=True)
        self.run_pipeline_step()

    @pyqtSlot(str)
    def on_open_module_config(self, instance_id: str):
        """Open the tabbed module configuration window (manual §8.1/§8.2).

        The dialog mirrors the vendor's Input Params / Output Params / Run Params /
        Display Setup tabs with an Execute / Continuous / OK footer, so a module can
        be verified without leaving its configuration.
        """
        tool = self.pipeline.nodes.get(instance_id)
        if tool is None:
            return
        self.on_node_selected(instance_id)
        dlg = ModuleConfigDialog(tool, self.pipeline.last_results.get(instance_id), self, pipeline=self.pipeline)
        dlg.execute_requested.connect(lambda _id: self.run_pipeline_step())
        dlg.continuous_requested.connect(lambda _id: self.btn_continuous.setChecked(True))
        dlg.connection_changed.connect(self._on_module_connection_changed)
        dlg.exec()
        # Re-read the edited parameters into both result surfaces.
        self.run_pipeline_step()

    @pyqtSlot(str)
    def on_node_selected(self, instance_id: str):
        self.selected_node_id = instance_id
        if instance_id in self.pipeline.nodes:
            tool = self.pipeline.nodes[instance_id]
            last_res = self.pipeline.last_results.get(instance_id)

            # Sync tool ROI to canvas for interactive manipulation
            roi_val = tool.parameters.get("roi") or tool.parameters.get("template_roi")
            if roi_val and isinstance(roi_val, list) and len(roi_val) == 4:
                self.image_canvas.set_active_roi(roi_val)
            else:
                self.image_canvas.set_active_roi(None)

            # Update Result surfaces immediately
            self.result_panel.set_module_result(tool.name, last_res)
            self.result_display.set_module_result(tool.name, last_res, tool.tool_name)

            # Update Image Display and Canvas to show selected node's image and overlays
            if last_res is not None:
                img = last_res.outputs.get("Image")
                overlays = last_res.overlays
                if img is None:
                    img = self._get_input_image_for_node(instance_id)
                if img is not None:
                    self.image_canvas.set_cv_image(img, overlays)
                    self.image_display.set_source_label(
                        f"{tool.name}.Output Image" if last_res.outputs.get("Image") is not None else f"{tool.name} Result",
                        f"{tool.name} [{tool.tool_name}] output",
                    )
                    self.image_display.mark_current_frame(self.image_canvas.current_pixmap())

    @pyqtSlot(str)
    def on_node_deleted(self, instance_id: str):
        self.pipeline.remove_node(instance_id)
        self.flow_scene.build_from_pipeline(preserve_positions=True)
        self.run_pipeline_step()

    @pyqtSlot(str, str, str, str)
    def on_connection_added(self, f_node, f_port, t_node, t_port):
        self.run_pipeline_step()

    @pyqtSlot(str)
    def on_run_single_tool(self, instance_id: str):
        self.run_pipeline_step()

    @pyqtSlot(str, object)
    def on_param_changed(self, key: str, value):
        if not self.run_timer.isActive():
            self.run_pipeline_step()

    @pyqtSlot(QTreeWidgetItem, int)
    def on_add_tool_from_tree(self, item: QTreeWidgetItem, column: int):
        tool_name = item.data(0, Qt.ItemDataRole.UserRole)
        if not tool_name:
            return
        self.on_add_tool_by_name(tool_name)

    @pyqtSlot(str)
    def on_add_tool_by_name(self, tool_name: str):
        """Insert a module selected in the Tool Box flyout (manual p.74).

        The insertion goes through the flow scene's undo stack so Ctrl+Z and the
        toolbar Undo button both reverse it, exactly like a canvas drag.
        """
        if self.flow_scene.is_locked():
            self._set_hint("Editing is locked - unlock to insert modules", 3000)
            return

        idx = len(self.pipeline.nodes) + 1
        inst_id = f"node_{int(time.time()*1000)%100000}"
        tool = create_tool_instance(tool_name, inst_id, f"{idx:02d}_{tool_name.replace(' ', '')}")

        view_rect = self.flow_view.mapToScene(self.flow_view.viewport().rect()).boundingRect()
        drop_pos = QPointF(view_rect.left() + 40, view_rect.top() + 40)
        if self.flow_scene.node_items:
            last_item = list(self.flow_scene.node_items.values())[-1]
            drop_pos = QPointF(last_item.pos().x(), last_item.pos().y() + 150)

        self.flow_scene.undo_stack.push(AddNodeCommand(self.flow_scene, tool, drop_pos))

        # Auto-wire the Image input from the closest upstream image producer so
        # a newly inserted module is immediately runnable.
        if "Image" in tool.inputs:
            for prev_id in reversed(self.pipeline.execution_order):
                if prev_id != inst_id and prev_id in self.pipeline.nodes:
                    prev_node = self.pipeline.nodes[prev_id]
                    if "Image" in prev_node.outputs:
                        self.pipeline.connect(prev_id, "Image", inst_id, "Image")
                        break
            self.flow_scene.update_connections()

        self.tab_workspace.setCurrentIndex(0)
        self.on_node_selected(inst_id)
        self.run_pipeline_step()
        self._set_hint(f"Inserted module: {tool_name}", 2500)

    @pyqtSlot()
    def on_activate_flow(self):
        """Mark the active flow as the converging trigger flow (manual p.95)."""
        name = self.solution.active_flow_name
        self.solution.set_trigger_flow(name)
        self.flow_overview.rebuild(self.solution.flows, self.solution.get_trigger_flow_name())
        self._set_hint(f"'{name}' set as the trigger flow for the overview", 3000)

    @pyqtSlot(str, float, float)
    def on_tool_dropped(self, tool_name: str, x: float, y: float):
        if self.flow_scene.is_locked():
            self._set_hint("Editing is locked - unlock to insert modules", 3000)
            return
        idx = len(self.pipeline.nodes) + 1
        inst_id = f"node_{int(time.time()*1000)%100000}"
        tool = create_tool_instance(tool_name, inst_id, f"{idx:02d}_{tool_name.replace(' ', '')}")
        self.pipeline.add_node(tool)
        if "Image" in tool.inputs:
            for prev_id in reversed(self.pipeline.execution_order):
                if prev_id != inst_id and prev_id in self.pipeline.nodes:
                    prev_node = self.pipeline.nodes[prev_id]
                    if "Image" in prev_node.outputs:
                        self.pipeline.connect(prev_id, "Image", inst_id, "Image")
                        break
        self.flow_scene.build_from_pipeline(preserve_positions=True)
        if inst_id in self.flow_scene.node_items:
            self.flow_scene.node_items[inst_id].setPos(QPointF(x, y))
            self.flow_scene.update_connections()
        self.on_node_selected(inst_id)
        self.run_pipeline_step()
        self._set_hint(f"Dropped module: {tool_name}", 2500)

    def _get_input_image_for_node(self, instance_id: str) -> Optional[np.ndarray]:
        """Resolves the upstream image routed or executed before the target node."""
        for conn in self.pipeline.connections:
            if conn.to_node == instance_id and conn.to_port == "Image":
                upstream_res = self.pipeline.last_results.get(conn.from_node)
                if upstream_res and upstream_res.outputs.get("Image") is not None:
                    return upstream_res.outputs["Image"]
        # Fallback: scan backwards in execution order
        if instance_id in self.pipeline.execution_order:
            idx = self.pipeline.execution_order.index(instance_id)
            for prev_id in reversed(self.pipeline.execution_order[:idx]):
                res = self.pipeline.last_results.get(prev_id)
                if res and res.outputs.get("Image") is not None:
                    return res.outputs["Image"]
        for nid in self.pipeline.execution_order:
            res = self.pipeline.last_results.get(nid)
            if res and res.outputs.get("Image") is not None:
                return res.outputs["Image"]
        return None

    @pyqtSlot()
    def on_load_image_file(self):
        """Prompt user to select real image file(s) and add them to the flow."""
        fpaths, _ = QFileDialog.getOpenFileNames(
            self, "Add / Load Image Files to Flow", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*.*)"
        )
        if fpaths:
            for i, fp in enumerate(fpaths):
                self.add_image_to_flow(fp, execute=(i == 0))

    def load_image_from_path(self, filepath: str) -> bool:
        """Loads an image into the active flow's image list and executes the pipeline."""
        return self.add_image_to_flow(filepath, execute=True)

    def add_image_to_flow(self, image_or_path, name: Optional[str] = None, execute: bool = True) -> bool:
        """Adds an image (file path or numpy array) to the flow of added images (image pool)."""
        img = None
        path = None
        disp_name = name

        if isinstance(image_or_path, str):
            clean_path = image_or_path.strip().strip('"').strip("'") if image_or_path else ""
            if not clean_path or not os.path.exists(clean_path):
                self.statusBar().showMessage(f"Image file not found: {image_or_path}", 4000)
                self._set_hint(f"Image file does not exist: {image_or_path}", 4000)
                if hasattr(self, "image_canvas"):
                    self.image_canvas.set_empty_state("Image file does not exist", is_error=True, subtext=f"Path not found:\n{image_or_path}")
                return False

            path = os.path.abspath(clean_path)
            disp_name = disp_name or os.path.basename(path)
            try:
                img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                img = None
            if img is None:
                img = cv2.imread(path)
            if img is None:
                self.statusBar().showMessage(f"Failed to decode image: {image_or_path}", 4000)
                self._set_hint(f"Could not load image file format: {image_or_path}", 4000)
                if hasattr(self, "image_canvas"):
                    self.image_canvas.set_empty_state("Failed to decode image", is_error=True, subtext=f"Supported: PNG, JPG, BMP, TIFF\n{image_or_path}")
                return False
        elif isinstance(image_or_path, np.ndarray):
            img = image_or_path
            path = None
            disp_name = disp_name or f"Image_{len(self._image_flow) + 1}"
        else:
            return False

        # Find or create ImageSourceTool in active pipeline
        src_node_id = None
        for nid, node in self.pipeline.nodes.items():
            if node.tool_name == "Image Source":
                src_node_id = nid
                break

        if src_node_id is None:
            src_node_id = f"src_{int(time.time() * 1000) % 10000}"
            src_tool = create_tool_instance("Image Source", src_node_id, "01_Acquisition")
            self.pipeline.add_node(src_tool)
            self.flow_scene.build_from_pipeline(preserve_positions=True)
        else:
            src_tool = self.pipeline.nodes[src_node_id]

        # Check if already in flow list
        existing_idx = -1
        for i, item in enumerate(self._image_flow):
            if path and item.get("path") == path:
                existing_idx = i
                break
            elif not path and item.get("name") == disp_name:
                existing_idx = i
                break

        if existing_idx >= 0:
            self._current_image_flow_index = existing_idx
            self._image_flow[existing_idx]["image"] = img
        else:
            self._image_flow.append({
                "name": disp_name,
                "path": path,
                "image": img
            })
            self._current_image_flow_index = len(self._image_flow) - 1

        if path:
            src_tool.set_param("source_type", "File")
            src_tool.set_param("file_path", path)
        src_tool._override_image = img
        src_tool._override_name = disp_name

        if execute:
            self.flow_scene.select_node(src_node_id)
            self.run_pipeline_step()
            self.on_node_selected(src_node_id)
            self.statusBar().showMessage(f"Loaded image into flow: {disp_name}", 3500)
            self._set_hint(f"Loaded {disp_name} into {src_tool.name}", 3000)

        return True

    def on_clear_image_flow(self):
        """Clears the added image list in the image bar."""
        self._image_flow.clear()
        self._current_image_flow_index = 0
        if hasattr(self, "image_display"):
            self.image_display.set_frames([])
            self.image_display.set_source_label("No image")
        self.statusBar().showMessage("Cleared image flow.", 2500)

    @pyqtSlot()
    def on_save_solution_as(self):
        self.on_save_solution()

    @pyqtSlot()
    def on_export_flow_xml(self):
        flow_name = self.solution.active_flow_name
        fpath, _ = QFileDialog.getSaveFileName(
            self, f"Export Flow '{flow_name}' as XML", f"{flow_name}.xml",
            "XML Flow Files (*.xml);;All Files (*.*)"
        )
        if not fpath:
            return
        try:
            self.solution.export_flow_xml(flow_name, fpath)
            self._set_hint(f"Flow exported to XML: {fpath}", 5000)
            QMessageBox.information(self, "Export Flow", f"Flow '{flow_name}' exported successfully to XML:\n{fpath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    @pyqtSlot()
    def on_import_flow_xml(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Import Flow from XML", "",
            "XML Flow Files (*.xml);;All Files (*.*)"
        )
        if not fpath:
            return
        try:
            imp_flow = self.solution.import_flow_xml(fpath)
            self._refresh_flow_tabs()
            self.flow_overview.rebuild(self.solution.flows, self.solution.get_trigger_flow_name())
            self._set_hint(f"Imported flow '{imp_flow.name}' from XML", 4000)
            QMessageBox.information(self, "Import Flow", f"Imported flow '{imp_flow.name}' successfully from XML.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    @pyqtSlot()
    def on_export_active_flow(self):
        flow_name = self.solution.active_flow_name
        fpath, _ = QFileDialog.getSaveFileName(
            self, f"Export Flow '{flow_name}'", f"{flow_name}.xml",
            "XML Flow Files (*.xml);;Flow Procedure (*.prc);;JSON Files (*.json);;All Files (*.*)"
        )
        if not fpath:
            return
        try:
            self.solution.export_flow(flow_name, fpath)
            self._set_hint(f"Flow exported to {fpath}", 5000)
            QMessageBox.information(self, "Export Flow", f"Flow exported successfully to:\n{fpath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    @pyqtSlot()
    def on_import_flow_procedure(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Import Flow Procedure", "",
            "XML Flow Files (*.xml);;Flow Procedure (*.prc);;JSON Files (*.json);;All Files (*.*)"
        )
        if not fpath:
            return
        try:
            imp_flow = self.solution.import_flow(fpath)
            self._refresh_flow_tabs()
            self.flow_overview.rebuild(self.solution.flows, self.solution.get_trigger_flow_name())
            self._set_hint(f"Imported flow '{imp_flow.name}'", 4000)
            QMessageBox.information(self, "Import Flow", f"Imported flow '{imp_flow.name}' successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def show_start_page(self) -> bool:
        """Displays the Vision Master Start Page dialog.
        If the main window is not yet visible, only shows the main window after the user
        finishes opening/creating a project or entering workspace.
        """
        was_visible = self.isVisible()
        dlg = StartPageDialog(project_manager=self.project_manager, parent=self if was_visible else None)
        dlg.solution_ready.connect(lambda sol, path: self.load_solution_manager(sol, filepath=path))
        res = dlg.exec()
        if res == QDialog.DialogCode.Accepted:
            if not was_visible:
                self.show()
            return True
        return False

    def run_startup_flow(self) -> bool:
        """
        Executes the initial startup flow.
        If 'show_on_startup' is enabled in preferences, displays the Start Page first
        while keeping the main window hidden. Only shows the main window once the user has
        finished opening/creating a project or entering workspace.
        Returns True if the application should proceed to the event loop, or False if the
        user cancelled / closed the start page without opening a project.
        """
        if self.project_manager.get_show_on_startup():
            return self.show_start_page()
        else:
            self.show()
            return True

    def load_solution_manager(self, solution: SolutionManager, filepath: Optional[str] = None):
        """Loads a full SolutionManager containing multiple flows and global variables."""
        self.solution = solution
        if filepath:
            self.current_project_path = filepath
            self.project_manager.add_recent_project(
                filepath,
                name=solution.name,
                flow_count=len(solution.flows)
            )
            self.setWindowTitle(f"Apex Industrial Vision Studio v4.3 - [{solution.name}]")

        active_name = solution.active_flow_name
        if active_name not in solution.flows and solution.flows:
            active_name = list(solution.flows.keys())[0]
            solution.active_flow_name = active_name

        self._refresh_flow_tabs()
        active_pipe = solution.get_active_flow()
        self.flow_scene.pipeline = active_pipe
        self.flow_scene.build_from_pipeline()
        if getattr(self, "flow_overview", None) is not None:
            self.flow_overview.rebuild(self.solution.flows, self.solution.get_trigger_flow_name())
        self.result_panel.global_variables = self.solution.global_variables
        self.run_pipeline_step()
        self._set_hint(f"Loaded solution '{solution.name}' ({len(solution.flows)} flow(s))", 4000)

    def _load_solution_instance(self, new_pipe: VisionPipeline):
        sol = SolutionManager(name=new_pipe.name)
        sol.flows = {new_pipe.name: new_pipe}
        sol.active_flow_name = new_pipe.name
        sol.set_trigger_flow(new_pipe.name)
        self.load_solution_manager(sol)

    def on_new_solution(self):
        dlg = NewProjectDialog(self.project_manager, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.created_solution and dlg.created_filepath:
                self.load_solution_manager(dlg.created_solution, filepath=dlg.created_filepath)

    def on_open_solution(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Open Solution File", self.project_manager.default_projects_dir,
            "Vision Solution (*.vmp *.sol *.json *.xml);;All Files (*.*)"
        )
        if fpath:
            try:
                sol = self.project_manager.load_project(fpath)
                self.load_solution_manager(sol, filepath=fpath)
                QMessageBox.information(self, "Solution Loaded", f"Solution '{sol.name}' loaded successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to load solution: {str(e)}")

    def on_save_solution(self):
        default_dir = self.current_project_path or os.path.join(
            self.project_manager.default_projects_dir, f"{self.solution.name}.vmp"
        )
        fpath, _ = QFileDialog.getSaveFileName(
            self, "Save Solution File", default_dir,
            "Vision Project (*.vmp);;Vision Solution (*.json);;All Files (*.*)"
        )
        if fpath:
            try:
                self.project_manager.save_project(self.solution, fpath)
                self.current_project_path = fpath
                self.setWindowTitle(f"Apex Industrial Vision Studio v4.3 - [{self.solution.name}]")
                QMessageBox.information(self, "Solution Saved", f"Solution saved successfully to:\n{fpath}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save solution: {str(e)}")

    def on_export_results_csv(self):
        fpath, _ = QFileDialog.getSaveFileName(self, "Export Results to CSV", "diagnostic_results.csv", "CSV Files (*.csv)")
        if fpath:
            try:
                with open(fpath, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Module", "Kernel", "Status", "Latency_ms", "Message"])
                    for nid in self.pipeline.execution_order:
                        res = self.pipeline.last_results.get(nid)
                        node = self.pipeline.nodes.get(nid)
                        if res and node:
                            writer.writerow([node.name, node.tool_name, res.status.value.upper(), f"{res.elapsed_ms:.2f}", res.message])
                QMessageBox.information(self, "Export Complete", f"Saved results to {fpath}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    def on_about(self):
        QMessageBox.about(
            self,
            "About Apex Industrial Vision Studio",
            "<h3>Apex Industrial Vision Studio v4.3</h3>"
            "<p>Professional desktop machine vision development and deployment platform.</p>"
            "<p><b>Architecture:</b> Multi-Flow DAG Execution, High-Density Diagnostic Grid, Subpixel Vision Canvas.</p>"
            "<p><b>Engine:</b> Python 3.12, OpenCV 4.x, NumPy, PyQt6</p>"
        )


# Backward-compatible alias
MainWindow = VisionMasterMainWindow

