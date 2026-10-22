"""
Apex Vision Startup & Welcome Page Dialog.
Provides industrial-grade project creation, file loading, recent projects list
with real-time search, file deletion (disk vs list removal), and template scaffolding.
"""
import os
import subprocess
import sys
from typing import Optional, Dict, Any
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QCheckBox, QFrame, QComboBox, QMenu
)

from apex_vision.core.pipeline import SolutionManager
from apex_vision.core.project_manager import ProjectManager
from apex_vision.ui.theme import check_icon_url
from apex_vision.ui.styles import THEME


class NewProjectDialog(QDialog):
    """Modal dialog for creating a new Apex Vision solution project."""

    def __init__(self, project_manager: ProjectManager, parent=None):
        super().__init__(parent)
        self.pm = project_manager
        self.created_solution: Optional[SolutionManager] = None
        self.created_filepath: Optional[str] = None

        self.setWindowTitle("Create New Project")
        self.setMinimumWidth(520)
        self.resize(540, 320)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header title
        title_lbl = QLabel("Create New Solution Project")
        title_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {THEME['text_primary']};")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel("Configure solution name, destination directory, and starting template.")
        sub_lbl.setStyleSheet(f"font-size: 12px; color: {THEME['text_muted']};")
        layout.addWidget(sub_lbl)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {THEME['vm_panel_header']};")
        layout.addWidget(line)

        # Form
        form_layout = QVBoxLayout()
        form_layout.setSpacing(10)

        # 1. Project Name
        name_lbl = QLabel("Project Name:")
        name_lbl.setStyleSheet(f"font-weight: 600; color: {THEME['text_primary']}; font-size: 13px;")
        form_layout.addWidget(name_lbl)

        # Generate default name based on existing count
        existing_count = len(self.pm.get_recent_projects()) + 1
        self.edit_name = QLineEdit(f"VisionProject_{existing_count}")
        self.edit_name.setStyleSheet("""
            QLineEdit {
                background: #f8fafb;
                border: 1px solid #5a6069;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
                color: #1a2024;
            }
            QLineEdit:focus {
                border: 1px solid #0078b0;
            }
        """)
        form_layout.addWidget(self.edit_name)

        # 2. Location
        dir_lbl = QLabel("Save Location:")
        dir_lbl.setStyleSheet(f"font-weight: 600; color: {THEME['text_primary']}; font-size: 13px;")
        form_layout.addWidget(dir_lbl)

        dir_box = QHBoxLayout()
        self.edit_dir = QLineEdit(self.pm.default_projects_dir)
        self.edit_dir.setStyleSheet("""
            QLineEdit {
                background: #f8fafb;
                border: 1px solid #5a6069;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
                color: #1a2024;
            }
            QLineEdit:focus {
                border: 1px solid #0078b0;
            }
        """)
        dir_box.addWidget(self.edit_dir)

        btn_browse = QPushButton("Browse...")
        btn_browse.setStyleSheet("""
            QPushButton {
                background: #e4e7ea;
                border: 1px solid #5a6069;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
                color: #1a2024;
            }
            QPushButton:hover {
                background: #d8dcdf;
            }
        """)
        btn_browse.clicked.connect(self._browse_dir)
        dir_box.addWidget(btn_browse)
        form_layout.addLayout(dir_box)

        # 3. Template
        tpl_lbl = QLabel("Solution Template:")
        tpl_lbl.setStyleSheet(f"font-weight: 600; color: {THEME['text_primary']}; font-size: 13px;")
        form_layout.addWidget(tpl_lbl)

        self.combo_template = QComboBox()
        self.combo_template.addItems([
            "Blank Solution (Standard Acquisition)",
            "PCB Optical Inspection & Defect Analysis",
            "Precision Dimensional Measurement",
            "Deep Learning Object Detection (YOLOv11)",
            "Color Extraction & Robot Calibration"
        ])
        self.combo_template.setStyleSheet("""
            QComboBox {
                background: #f8fafb;
                border: 1px solid #5a6069;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
                color: #1a2024;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
        """)
        form_layout.addWidget(self.combo_template)

        layout.addLayout(form_layout)
        layout.addStretch()

        # Dialog Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background: #e4e7ea;
                border: 1px solid #5a6069;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
                color: #414850;
            }
            QPushButton:hover {
                background: #d8dcdf;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_create = QPushButton("Create Project")
        btn_create.setStyleSheet("""
            QPushButton {
                background: #0078b0;
                color: #1a2024;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #0078b0;
            }
        """)
        btn_create.clicked.connect(self._create_project)
        btn_layout.addWidget(btn_create)

        layout.addLayout(btn_layout)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Save Location", self.edit_dir.text())
        if d:
            self.edit_dir.setText(d)

    def _create_project(self):
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid project name.")
            return

        target_dir = self.edit_dir.text().strip()
        if not target_dir:
            target_dir = self.pm.default_projects_dir

        # Map template choice
        idx = self.combo_template.currentIndex()
        tpl_map = {
            0: "blank",
            1: "pcb",
            2: "measurement",
            3: "yolo",
            4: "calibration"
        }
        tpl_key = tpl_map.get(idx, "blank")

        existing = self.pm.project_path(name, target_dir)[1]
        if os.path.exists(existing):
            answer = QMessageBox.question(
                self, "Project Exists",
                f"A project file already exists at:\n{existing}\n\nReplace it with a new project?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            sol, filepath = self.pm.create_project(name, target_dir, template=tpl_key)
            self.created_solution = sol
            self.created_filepath = filepath
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Creation Error", f"Failed to create project: {str(e)}")


class ProjectRowWidget(QWidget):
    """Custom row widget representing a recent project item with action buttons."""

    open_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, project_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.data = project_data
        self.path = project_data.get("path", "")
        self.name = project_data.get("name", "Untitled")
        self.exists = project_data.get("file_exists", False)
        self.last_opened = project_data.get("last_opened", "")
        self.template = project_data.get("template", "Custom")

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # Top row: Name + Badge + Last Modified + Action Buttons
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)

        # Project name
        name_lbl = QLabel(self.name)
        name_lbl.setStyleSheet("""
            font-size: 14px;
            font-weight: 600;
            color: #1a2024;
        """)
        top_layout.addWidget(name_lbl)

        # Status Badge (Exists vs Missing)
        badge_lbl = QLabel(" Ready " if self.exists else " Missing ")
        if self.exists:
            badge_lbl.setStyleSheet("""
                background-color: #d8f0e2;
                color: #076b3a;
                border-radius: 3px;
                padding: 2px 4px;
                font-size: 11px;
                font-weight: bold;
            """)
        else:
            badge_lbl.setStyleSheet("""
                background-color: #fadadd;
                color: #b81c20;
                border-radius: 3px;
                padding: 2px 4px;
                font-size: 11px;
                font-weight: bold;
            """)
        top_layout.addWidget(badge_lbl)

        # Template tag
        if self.template and self.template != "Custom":
            tpl_badge = QLabel(self.template)
            tpl_badge.setStyleSheet("""
                background-color: #f6dcae;
                color: #0078b0;
                border-radius: 3px;
                padding: 2px 4px;
                font-size: 11px;
            """)
            top_layout.addWidget(tpl_badge)

        top_layout.addStretch()

        # Last opened date
        date_lbl = QLabel(self.last_opened)
        date_lbl.setStyleSheet(f"font-size: 12px; color: {THEME['text_muted']};")
        top_layout.addWidget(date_lbl)

        # Open button
        btn_open = QPushButton("Open")
        btn_open.setFixedHeight(22)
        btn_open.setStyleSheet("""
            QPushButton {
                background: #0078b0;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 2px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #0078b0;
            }
        """)
        btn_open.clicked.connect(lambda: self.open_requested.emit(self.path))
        top_layout.addWidget(btn_open)

        # Delete button
        btn_delete = QPushButton("Delete")
        btn_delete.setFixedHeight(22)
        btn_delete.setStyleSheet("""
            QPushButton {
                background: #fadadd;
                color: #b81c20;
                border: 1px solid #c8161a;
                border-radius: 3px;
                padding: 2px 8px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #c8161a;
                color: #b81c20;
            }
        """)
        btn_delete.clicked.connect(lambda: self.delete_requested.emit(self.path))
        top_layout.addWidget(btn_delete)

        layout.addLayout(top_layout)

        # Bottom row: File path with tooltip
        path_lbl = QLabel(self.path)
        path_lbl.setToolTip(self.path)
        path_lbl.setStyleSheet(f"font-size: 12px; color: {THEME['text_muted']}; font-family: Consolas, monospace;")
        layout.addWidget(path_lbl)


class StartPageDialog(QDialog):
    """
    Apex Vision Startup / Welcome Page Dialog.
    Allows user to create new solutions, open existing solutions, launch templates,
    and inspect/search/delete recent projects.
    """

    solution_ready = pyqtSignal(SolutionManager, str)

    def __init__(self, project_manager: Optional[ProjectManager] = None, parent=None):
        super().__init__(parent)
        self.pm = project_manager or ProjectManager()
        self.selected_solution: Optional[SolutionManager] = None
        self.selected_filepath: Optional[str] = None

        self.setWindowTitle("Apex Industrial Vision Studio - Start Page")
        self.setMinimumSize(960, 620)
        self.resize(1080, 680)

        # Allow resize and maximize
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinMaxButtonsHint |
            Qt.WindowType.WindowCloseButtonHint
        )

        if parent is None:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                x = (geo.width() - self.width()) // 2 + geo.x()
                y = (geo.height() - self.height()) // 2 + geo.y()
                self.move(max(0, x), max(0, y))

        self._setup_ui()
        self.refresh_recent_projects()

    def _setup_ui(self):
        # Root layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Header Banner
        header = QFrame()
        header.setFixedHeight(64)
        header.setObjectName("startHeader")
        header.setStyleSheet(f"QFrame#startHeader {{ background-color: {THEME['vm_panel_header']}; border: none; border-bottom: 2px solid {THEME['accent_hover']}; }}")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(24, 0, 24, 0)
        h_layout.setSpacing(14)

        # Brand Mark / Title
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        brand_lbl = QLabel("APEX VISION STUDIO")
        brand_lbl.setStyleSheet("""
            font-size: 16px;
            font-weight: 700;
            color: #1a2024;
            letter-spacing: 1.5px;
        """)
        title_box.addWidget(brand_lbl)

        sub_title = QLabel("Modular Industrial Machine Vision Platform & Flow Orchestration v4.3")
        sub_title.setStyleSheet(f"font-size: 12px; color: {THEME['text_muted']};")
        title_box.addWidget(sub_title)
        h_layout.addLayout(title_box)

        h_layout.addStretch()

        # Enter Workspace Button (skip start page)
        btn_enter = QPushButton("Enter Workspace  →")
        btn_enter.setStyleSheet("""
            QPushButton {
                background: #0078b0;
                color: #1a2024;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #0078b0;
            }
        """)
        btn_enter.clicked.connect(self.accept)
        h_layout.addWidget(btn_enter)

        root.addWidget(header)

        # 2. Main Two-Column Body
        body = QWidget()
        body.setObjectName("startBody")
        body.setStyleSheet("QWidget#startBody, QWidget#startBody > QWidget { background-color: #ecf0f0; }")
        b_layout = QHBoxLayout(body)
        b_layout.setContentsMargins(24, 20, 24, 20)
        b_layout.setSpacing(24)

        # --- LEFT COLUMN: Start Actions & Templates ---
        left_col = QWidget()
        left_col.setFixedWidth(340)
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(16)

        # Section: START
        sec_start_lbl = QLabel("GET STARTED")
        sec_start_lbl.setStyleSheet("""
            font-size: 12px;
            font-weight: 700;
            color: #5a6168;
            letter-spacing: 1px;
        """)
        left_layout.addWidget(sec_start_lbl)

        # Card: New Project
        self.btn_new_proj = QPushButton("+  New Project...")
        self.btn_new_proj.setFixedHeight(46)
        self.btn_new_proj.setStyleSheet("""
            QPushButton {
                background: #f8fafb;
                border: 1px solid #5a6069;
                border-left: 4px solid #0078b0;
                border-radius: 4px;
                padding: 12px 16px;
                font-size: 14px;
                font-weight: 600;
                color: #1a2024;
                text-align: left;
            }
            QPushButton:hover {
                background: #e4e7ea;
                border-color: #5a6168;
                border-left-color: #0078b0;
            }
        """)
        self.btn_new_proj.clicked.connect(self.on_new_project_clicked)
        left_layout.addWidget(self.btn_new_proj)

        # Card: Open Project
        self.btn_open_proj = QPushButton("📁  Open Project File...")
        self.btn_open_proj.setFixedHeight(46)
        self.btn_open_proj.setStyleSheet("""
            QPushButton {
                background: #f8fafb;
                border: 1px solid #5a6069;
                border-left: 4px solid #e4b030;
                border-radius: 4px;
                padding: 12px 16px;
                font-size: 14px;
                font-weight: 600;
                color: #1a2024;
                text-align: left;
            }
            QPushButton:hover {
                background: #e4e7ea;
                border-color: #5a6168;
                border-left-color: #e4b030;
            }
        """)
        self.btn_open_proj.clicked.connect(self.on_open_project_clicked)
        left_layout.addWidget(self.btn_open_proj)

        # Section: SAMPLE TEMPLATES
        sec_tpl_lbl = QLabel("SAMPLE TEMPLATES")
        sec_tpl_lbl.setStyleSheet("""
            font-size: 12px;
            font-weight: 700;
            color: #5a6168;
            letter-spacing: 1px;
            margin-top: 10px;
        """)
        left_layout.addWidget(sec_tpl_lbl)

        # Template quick cards
        tpl_cards = [
            ("PCB Inspection && Defects", "pcb", "IC alignment, mounting holes, trace calipers & scratch check"),
            ("Precision Measurement", "measurement", "Sub-pixel circle fitting, calipers, and tolerances"),
            ("YOLOv11 Object Detection", "yolo", "Real-time deep learning neural object detection"),
            ("Robot Coordinate Calibration", "calibration", "N-point affine calibration and color extraction")
        ]

        for title, key, desc in tpl_cards:
            t_btn = QPushButton(f"⚡  {title}")
            t_btn.setToolTip(desc)
            t_btn.setFixedHeight(36)
            t_btn.setStyleSheet("""
                QPushButton {
                    background: #f8fafb;
                    border: 1px solid #d8dcdf;
                    border-radius: 4px;
                    padding: 8px 12px;
                    font-size: 13px;
                    font-weight: 500;
                    color: #1a2024;
                    text-align: left;
                }
                QPushButton:hover {
                    background: #ecf0f0;
                    border-color: #0078b0;
                    color: #0078b0;
                }
            """)
            t_btn.clicked.connect(lambda checked, k=key: self.on_template_clicked(k))
            left_layout.addWidget(t_btn)

        left_layout.addStretch()
        b_layout.addWidget(left_col)

        # Separator line
        v_sep = QFrame()
        v_sep.setFrameShape(QFrame.Shape.VLine)
        v_sep.setStyleSheet("color: #d8dcdf;")
        b_layout.addWidget(v_sep)

        # --- RIGHT COLUMN: Recent Projects ---
        right_col = QWidget()
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # Header bar for Recent Projects
        rec_bar = QHBoxLayout()
        rec_bar.setSpacing(10)

        rec_title = QLabel("RECENT PROJECTS")
        rec_title.setStyleSheet("""
            font-size: 12px;
            font-weight: 700;
            color: #5a6168;
            letter-spacing: 1px;
        """)
        rec_bar.addWidget(rec_title)

        self.count_badge = QLabel("0")
        self.count_badge.setStyleSheet("""
            background: #d8dcdf;
            color: #414850;
            border-radius: 9px;
            padding: 2px 8px;
            font-size: 12px;
            font-weight: bold;
        """)
        rec_bar.addWidget(self.count_badge)

        rec_bar.addStretch()

        # Real-time search filter
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("Filter recent projects...")
        self.edit_search.setFixedWidth(240)
        self.edit_search.setStyleSheet("""
            QLineEdit {
                background: #f8fafb;
                border: 1px solid #5a6069;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
                color: #1a2024;
            }
            QLineEdit:focus {
                border-color: #0078b0;
            }
        """)
        self.edit_search.textChanged.connect(self._on_search_text_changed)
        rec_bar.addWidget(self.edit_search)

        # Clear list button
        btn_clear = QPushButton("Clear List")
        btn_clear.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #5a6168;
                font-size: 12px;
                padding: 4px 6px;
            }
            QPushButton:hover {
                color: #b81c20;
                text-decoration: underline;
            }
        """)
        btn_clear.clicked.connect(self.on_clear_recent_clicked)
        rec_bar.addWidget(btn_clear)

        right_layout.addLayout(rec_bar)

        # Recent Projects List
        self.list_projects = QListWidget()
        self.list_projects.setStyleSheet("""
            QListWidget {
                background-color: #f8fafb;
                border: 1px solid #5a6069;
                border-radius: 4px;
                outline: none;
            }
            QListWidget::item {
                background: #f8fafb;
                border-bottom: 1px solid #e4e7ea;
            }
            QListWidget::item:hover {
                background: #ecf0f0;
            }
            QListWidget::item:selected {
                background: #f6dcae;
                border-left: 3px solid #0078b0;
            }
        """)
        self.list_projects.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_projects.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_projects.customContextMenuRequested.connect(self._show_context_menu)
        right_layout.addWidget(self.list_projects)

        # Empty state label
        self.lbl_empty = QLabel("No recent projects found.\nClick 'New Project' or 'Open Project File' to get started.")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet("color: #5a6168; font-size: 14px; line-height: 1.5;")
        self.lbl_empty.setVisible(False)
        right_layout.addWidget(self.lbl_empty)

        b_layout.addWidget(right_col)
        root.addWidget(body)

        # 3. Footer Bar
        footer = QFrame()
        footer.setFixedHeight(48)
        footer.setObjectName("startFooter")
        footer.setStyleSheet("QFrame#startFooter { background-color: #e4e7ea; border: none; border-top: 1px solid #aab3b9; }")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(24, 0, 24, 0)

        # Show on startup checkbox
        self.chk_startup = QCheckBox("Show Start Page on startup")
        self.chk_startup.setChecked(self.pm.get_show_on_startup())
        self.chk_startup.setStyleSheet(("""
            QCheckBox {
                font-size: 13px;
                color: #414850;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #5a6168;
                border-radius: 3px;
                background: #f8fafb;
            }
            QCheckBox::indicator:checked {
                background: #0078b0;
                border-color: #0078b0;
                image: url(%s);
            }
        """) % check_icon_url("#ffffff"))
        self.chk_startup.toggled.connect(self._on_startup_toggled)
        f_layout.addWidget(self.chk_startup)

        f_layout.addStretch()

        # Close / Open workspace button
        btn_close = QPushButton("Open Workspace")
        btn_close.setStyleSheet("""
            QPushButton {
                background: #f8fafb;
                border: 1px solid #5a6069;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
                color: #1a2024;
            }
            QPushButton:hover {
                background: #d8dcdf;
            }
        """)
        btn_close.clicked.connect(self.accept)
        f_layout.addWidget(btn_close)

        root.addWidget(footer)

    # =========================================================================
    # Data & UI Refreshing
    # =========================================================================

    def refresh_recent_projects(self):
        """Populate list widget from ProjectManager recent projects."""
        self.list_projects.clear()
        query = self.edit_search.text().strip().lower()
        projects = self.pm.get_recent_projects()

        matching = []
        for p in projects:
            if not query or query in p["name"].lower() or query in p["path"].lower():
                matching.append(p)

        self.count_badge.setText(str(len(projects)))

        if not matching:
            self.list_projects.setVisible(False)
            self.lbl_empty.setVisible(True)
            return

        self.list_projects.setVisible(True)
        self.lbl_empty.setVisible(False)

        for p_data in matching:
            item = QListWidgetItem(self.list_projects)
            item.setSizeHint(QSize(0, 68))
            item.setData(Qt.ItemDataRole.UserRole, p_data)

            row_widget = ProjectRowWidget(p_data, self)
            row_widget.open_requested.connect(self.load_project_path)
            row_widget.delete_requested.connect(self.prompt_delete_project)

            self.list_projects.setItemWidget(item, row_widget)

    def _on_search_text_changed(self, text: str):
        self.refresh_recent_projects()

    def _on_startup_toggled(self, checked: bool):
        self.pm.set_show_on_startup(checked)

    # =========================================================================
    # User Actions
    # =========================================================================

    def on_new_project_clicked(self):
        """Open modal dialog to configure and create a new project."""
        dlg = NewProjectDialog(self.pm, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.created_solution and dlg.created_filepath:
                self.selected_solution = dlg.created_solution
                self.selected_filepath = dlg.created_filepath
                self.solution_ready.emit(dlg.created_solution, dlg.created_filepath)
                self.accept()

    def on_open_project_clicked(self):
        """Open file picker to select and load an existing project file."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open Vision Project File",
            self.pm.default_projects_dir,
            "Apex Vision Files (*.vmp *.sol *.json *.xml);;All Files (*.*)"
        )
        if filepath:
            self.load_project_path(filepath)

    def on_template_clicked(self, template_key: str):
        """Instantiate a project directly from template."""
        from datetime import datetime
        name = f"Solution_{template_key.upper()}_{datetime.now().strftime('%H%M%S')}"
        try:
            sol, fpath = self.pm.create_project(name, template=template_key)
            self.selected_solution = sol
            self.selected_filepath = fpath
            self.solution_ready.emit(sol, fpath)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Template Error", f"Failed to instantiate template: {str(e)}")

    def load_project_path(self, filepath: str):
        """Load project file from disk and emit solution_ready signal."""
        if not os.path.exists(filepath):
            QMessageBox.warning(
                self,
                "File Not Found",
                f"Project file does not exist on disk:\n{filepath}\n\n"
                f"You may remove it from the recent list using the Delete button."
            )
            return

        try:
            sol = self.pm.load_project(filepath)
            self.selected_solution = sol
            self.selected_filepath = filepath
            self.solution_ready.emit(sol, filepath)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load project file:\n{str(e)}")

    def prompt_delete_project(self, filepath: str):
        """
        Prompt user whether to delete project file from disk or remove from list.
        Fulfills: 'where user can create, load or delete project file with list of recently open projects'.
        """
        filename = os.path.basename(filepath)
        exists_on_disk = os.path.exists(filepath)

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Delete Project")
        msg_box.setIcon(QMessageBox.Icon.Question)

        if exists_on_disk:
            msg_box.setText(f"How would you like to delete project '<b>{filename}</b>'?")
            msg_box.setInformativeText(
                "You can permanently delete the project file from disk, "
                "or simply remove it from the recent projects list."
            )
            btn_disk = msg_box.addButton("Delete File from Disk", QMessageBox.ButtonRole.DestructiveRole)
            btn_list = msg_box.addButton("Remove from List Only", QMessageBox.ButtonRole.ActionRole)
            msg_box.addButton(QMessageBox.StandardButton.Cancel)

            msg_box.exec()
            clicked = msg_box.clickedButton()

            if clicked == btn_disk:
                success, msg = self.pm.delete_project_file(filepath, delete_file_from_disk=True)
                if not success:
                    QMessageBox.warning(self, "Delete Warning", msg)
                self.refresh_recent_projects()
            elif clicked == btn_list:
                self.pm.remove_recent_project(filepath)
                self.refresh_recent_projects()
        else:
            # File already missing from disk
            msg_box.setText(f"Project file '<b>{filename}</b>' was not found on disk.")
            msg_box.setInformativeText("Remove this entry from the recent projects list?")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)

            if msg_box.exec() == QMessageBox.StandardButton.Yes:
                self.pm.remove_recent_project(filepath)
                self.refresh_recent_projects()

    def on_clear_recent_clicked(self):
        """Clear all recent project records after user confirmation."""
        ans = QMessageBox.question(
            self,
            "Clear Recent Projects",
            "Are you sure you want to clear the entire recent projects list?\n"
            "(Project files on disk will not be deleted).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.pm.clear_recent_projects()
            self.refresh_recent_projects()

    def _on_item_double_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and "path" in data:
            self.load_project_path(data["path"])

    def _show_context_menu(self, pos):
        item = self.list_projects.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or "path" not in data:
            return

        filepath = data["path"]
        menu = QMenu(self)

        act_open = menu.addAction("Open Project")
        act_folder = menu.addAction("Open Containing Folder")
        menu.addSeparator()
        act_remove_list = menu.addAction("Remove from Recent List")
        act_delete_disk = menu.addAction("Delete File from Disk...")

        chosen = menu.exec(self.list_projects.mapToGlobal(pos))
        if chosen == act_open:
            self.load_project_path(filepath)
        elif chosen == act_folder:
            if os.path.exists(filepath):
                folder = os.path.dirname(filepath)
                if sys.platform == "win32":
                    subprocess.Popen(f'explorer /select,"{os.path.normpath(filepath)}"')
                else:
                    subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])
        elif chosen == act_remove_list:
            self.pm.remove_recent_project(filepath)
            self.refresh_recent_projects()
        elif chosen == act_delete_disk:
            self.prompt_delete_project(filepath)
