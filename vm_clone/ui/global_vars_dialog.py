"""
Global Variables Management Dialog.
Matches HikRobot Vision Master Global Variables (Manual p. 108-112).
Allows vision engineers to define, view, edit, and bind up to 32 global solution variables.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit, QComboBox, QMessageBox
)
from PyQt6.QtCore import Qt
from typing import Dict, Any


from vm_clone.ui.styles import THEME


class GlobalVariablesDialog(QDialog):
    def __init__(self, global_vars: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Global Variables - Apex Industrial Vision Studio")
        self.resize(600, 420)
        self.global_vars = global_vars

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header Info
        lbl_info = QLabel("Solution Global Variables (Shared across Multi-Flows, Communication, & Logic Modules):")
        lbl_info.setStyleSheet(f"color: {THEME['text_primary']}; font-weight: 600; font-size: 12px;")
        layout.addWidget(lbl_info)

        # Table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Variable Name", "Type", "Current Value"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Controls Row
        ctrl_layout = QHBoxLayout()
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Variable Name (e.g., g_TargetOffset)")
        ctrl_layout.addWidget(self.txt_name, stretch=2)

        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["Integer", "Float", "String", "Boolean"])
        ctrl_layout.addWidget(self.cmb_type, stretch=1)

        self.txt_val = QLineEdit()
        self.txt_val.setPlaceholderText("Initial Value")
        ctrl_layout.addWidget(self.txt_val, stretch=2)

        btn_add = QPushButton("+ Add Variable")
        btn_add.setStyleSheet(f"border-color: {THEME['accent_primary']}; color: {THEME['accent_primary']}; font-weight: 600;")
        btn_add.clicked.connect(self.on_add_variable)
        ctrl_layout.addWidget(btn_add)

        layout.addLayout(ctrl_layout)

        # Dialog Buttons
        btn_box = QHBoxLayout()
        btn_del = QPushButton("Delete Selected")
        btn_del.clicked.connect(self.on_delete_variable)
        btn_box.addWidget(btn_del)

        btn_box.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)

        layout.addLayout(btn_box)

        self._populate_table()

    def _populate_table(self):
        self.table.setRowCount(0)
        for k, v in self.global_vars.items():
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Name
            self.table.setItem(row, 0, QTableWidgetItem(str(k)))

            # Type
            vtype = type(v).__name__
            self.table.setItem(row, 1, QTableWidgetItem(vtype))

            # Value
            self.table.setItem(row, 2, QTableWidgetItem(str(v)))

    def on_add_variable(self):
        name = self.txt_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Variable name cannot be empty.")
            return

        typ = self.cmb_type.currentText()
        raw_val = self.txt_val.text().strip()

        try:
            if typ == "Integer":
                val = int(raw_val) if raw_val else 0
            elif typ == "Float":
                val = float(raw_val) if raw_val else 0.0
            elif typ == "Boolean":
                val = raw_val.lower() in ("true", "1", "yes")
            else:
                val = str(raw_val)

            self.global_vars[name] = val
            self._populate_table()
            self.txt_name.clear()
            self.txt_val.clear()
        except Exception as e:
            QMessageBox.critical(self, "Format Error", f"Cannot parse value: {str(e)}")

    def on_delete_variable(self):
        curr_row = self.table.currentRow()
        if curr_row >= 0:
            k = self.table.item(curr_row, 0).text()
            if k in self.global_vars:
                del self.global_vars[k]
                self._populate_table()
