"""Module configuration dialog — the vendor's per-module parameter window.

Reference: Vision Master 4.3.0 user manual §8.1 and §8.2
(`docs/references/external/ui_crops/module_common_config.png` and
`docs/references/external/ui_chapters_cn.txt`).  The vendor's module window is a
modal dialog titled with the module id and name, carrying four tabs and a footer
of execution buttons:

    ┌──────────────────────────────────────────────────────────┐
    │ 10002  Process                                      [x]  │
    ├──────────────────────────────────────────────────────────┤
    │ Input Params | Output Params | Run Params | Display Setup│
    ├──────────────────────────────────────────────────────────┤
    │  Param        Type        Subscribe                      │
    │  ...                                                     │
    ├──────────────────────────────────────────────────────────┤
    │                        [Continuous] [Execute] [OK]        │
    └──────────────────────────────────────────────────────────┘

Documented behaviour reproduced here (§8.2):

* **Basic parameters** subscribe an image input and configure the ROI.
* **Run parameters** are grouped by category, e.g. 图像相关参数 (image cache,
  capture interval, stop-on-last-frame) and 边缘相关参数 (edge type, polarity,
  threshold).
* **Result display** is the per-parameter output table.
* The footer's *Execute* / *Continuous* run the flow so the operator can verify a
  module without leaving the dialog.
"""
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QPushButton, QWidget,
    QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
    QScrollArea, QTreeWidget, QTreeWidgetItem
)

from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, is_compatible_type
from apex_vision.ui.styles import THEME


# Run-parameter groups, mirroring the vendor's 运行参数 categories.
RUN_PARAM_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Image Parameters", ("interval", "cache", "image_count", "delay", "timeout",
                          "stop_on", "frame", "buffer")),
    ("Edge Parameters", ("edge", "polarity", "threshold", "contrast", "sigma",
                         "transition", "filter")),
    ("Search Parameters", ("angle", "scale", "score", "min_score", "max_match",
                           "tolerance", "search")),
    ("Measurement Parameters", ("unit", "scale_factor", "calibration", "offset",
                                "decimals")),
)


class ModuleConfigDialog(QDialog):
    """Tabbed module configuration window (manual §8.1/§8.2)."""

    execute_requested = pyqtSignal(str)          # instance_id, once
    continuous_requested = pyqtSignal(str)       # instance_id, loop
    connection_changed = pyqtSignal(str, str)    # instance_id, port_name

    def __init__(self, tool: VisionToolBase, last_result: Optional[ToolExecutionResult] = None,
                 parent=None, pipeline=None):
        super().__init__(parent)
        self.tool = tool
        self.pipeline = pipeline
        if self.pipeline is None and parent is not None and hasattr(parent, "pipeline"):
            self.pipeline = parent.pipeline

        self.setWindowTitle(f"{tool.name}   [{tool.tool_name}]")
        self.setMinimumSize(560, 440)
        self.resize(640, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("moduleConfigTabs")
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        self._build_input_tab()
        self._build_output_tab()
        self._build_run_tab(tool)
        self._build_display_tab()

        # ---- footer: Continuous | Execute | OK (vendor order) ---------------
        footer = QHBoxLayout()
        footer.addStretch(1)

        self.btn_continuous = QPushButton("Continuous")
        self.btn_continuous.setToolTip("Run the flow continuously")
        self.btn_continuous.clicked.connect(
            lambda: self.continuous_requested.emit(self.tool.instance_id))
        footer.addWidget(self.btn_continuous)

        self.btn_execute = QPushButton("Execute")
        self.btn_execute.setToolTip("Run the flow once to verify this module")
        self.btn_execute.setObjectName("btnExecuteOnce")
        self.btn_execute.clicked.connect(
            lambda: self.execute_requested.emit(self.tool.instance_id))
        footer.addWidget(self.btn_execute)

        self.btn_ok = QPushButton("OK")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        footer.addWidget(self.btn_ok)

        root.addLayout(footer)

    # ------------------------------------------------------------------ tabs
    def _build_input_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        hint = QLabel(
            "Basic parameters: subscribe the module's input parameters to upstream connection lines. "
            "Input parameter follows the connection line it is related to; changing the source updates the wire."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {THEME['text_secondary']}; font-size: 11px;")
        layout.addWidget(hint)

        table = QTableWidget(len(self.tool.inputs), 3)
        table.setObjectName("paramTable")
        table.setHorizontalHeaderLabels(["Param", "Type", "Source"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(0, 120)
        table.setColumnWidth(1, 90)
        table.setAlternatingRowColors(True)

        for row, (name, port) in enumerate(self.tool.inputs.items()):
            p_item = QTableWidgetItem(name)
            p_item.setFlags(p_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, p_item)

            t_item = QTableWidgetItem(port.data_type.value)
            t_item.setFlags(t_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 1, t_item)

            if self.pipeline:
                current_conn = None
                for c in self.pipeline.connections:
                    if c.to_node == self.tool.instance_id and c.to_port == name:
                        current_conn = c
                        break

                combo = QComboBox()
                combo.setObjectName(f"inputCombo_{name}")
                combo.addItem("<None (Disconnected)>", None)
                sel_idx = 0
                idx = 1
                for nid, other_tool in self.pipeline.nodes.items():
                    if nid == self.tool.instance_id:
                        continue
                    for out_name, out_port in other_tool.outputs.items():
                        if is_compatible_type(out_port.data_type, port.data_type):
                            label = f"{other_tool.name} [{out_name}]"
                            combo.addItem(label, (nid, out_name))
                            if current_conn and current_conn.from_node == nid and current_conn.from_port == out_name:
                                sel_idx = idx
                            idx += 1

                combo.setCurrentIndex(sel_idx)

                def _make_conn_handler(p_name=name, cb=combo):
                    def _handler(index):
                        data = cb.itemData(index)
                        if data is None:
                            self.pipeline.disconnect(self.tool.instance_id, p_name)
                        else:
                            src_node, src_port = data
                            self.pipeline.connect(src_node, src_port, self.tool.instance_id, p_name, force=True)
                        self.connection_changed.emit(self.tool.instance_id, p_name)
                    return _handler

                combo.currentIndexChanged.connect(_make_conn_handler())
                table.setCellWidget(row, 2, combo)
                table.setItem(row, 2, QTableWidgetItem(combo.currentText()))
            else:
                s_item = QTableWidgetItem(port.description or "-")
                s_item.setFlags(s_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, 2, s_item)

        layout.addWidget(table, 1)
        self.tabs.addTab(page, "Input Params")

    def _build_output_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        hint = QLabel(
            "Output parameters. Tick a parameter to expose it to the flow and to the "
            "global-variable subscription list."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {THEME['text_secondary']}; font-size: 11px;")
        layout.addWidget(hint)

        self.output_tree = QTreeWidget()
        self.output_tree.setObjectName("resultTree")
        self.output_tree.setColumnCount(3)
        self.output_tree.setHeaderLabels(["Param Name", "Type", "Subscribe"])
        self.output_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.output_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.output_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.output_tree.setColumnWidth(1, 86)
        self.output_tree.setColumnWidth(2, 78)
        self.output_tree.setAlternatingRowColors(True)
        self.output_tree.setRootIsDecorated(True)

        root = QTreeWidgetItem([self.tool.name, "", ""])
        root.setExpanded(True)
        self.output_tree.addTopLevelItem(root)
        for name, port in self.tool.outputs.items():
            item = QTreeWidgetItem([name, port.data_type.value, ""])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(2, Qt.CheckState.Checked)
            item.setToolTip(0, port.description or name)
            root.addChild(item)
        root.setExpanded(True)
        self.output_tree.expandAll()
        layout.addWidget(self.output_tree, 1)
        self.tabs.addTab(page, "Output Params")

    def _build_run_tab(self, tool: VisionToolBase):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        container.setObjectName("paramContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.run_editors: Dict[str, QWidget] = {}
        assigned: List[str] = []

        for group_name, tokens in RUN_PARAM_GROUPS:
            keys = [k for k in tool.parameters
                    if k not in assigned and any(t in k.lower() for t in tokens)]
            if not keys:
                continue
            group = QWidget()
            gl = QVBoxLayout(group)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(4)

            title = QLabel(group_name)
            title.setStyleSheet(
                f"font-weight: 600; color: {THEME['accent_primary']}; font-size: 12px;")
            gl.addWidget(title)

            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(8)
            form.setVerticalSpacing(5)
            for key in keys:
                editor = self._editor_for(key, tool.parameters[key])
                if editor is None:
                    continue
                self.run_editors[key] = editor
                lbl = QLabel(f"{key.replace('_', ' ').title()}:")
                lbl.setFixedWidth(120)
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                form.addRow(lbl, editor)
                assigned.append(key)
            gl.addLayout(form)
            layout.addWidget(group)

        remaining = [k for k in tool.parameters if k not in assigned and k != "code"]
        if remaining or not layout.count():
            group = QWidget()
            gl = QVBoxLayout(group)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(4)
            title = QLabel("Module Parameters")
            title.setStyleSheet(
                f"font-weight: 600; color: {THEME['accent_primary']}; font-size: 12px;")
            gl.addWidget(title)
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(8)
            form.setVerticalSpacing(5)
            for key in remaining:
                editor = self._editor_for(key, tool.parameters[key])
                if editor is None:
                    continue
                self.run_editors[key] = editor
                lbl = QLabel(f"{key.replace('_', ' ').title()}:")
                lbl.setFixedWidth(120)
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                form.addRow(lbl, editor)
            gl.addLayout(form)
            layout.addWidget(group)

        layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        self.tabs.addTab(page, "Run Params")

    def _build_display_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        hint = QLabel(
            "Display settings choose which image the image display area presents after "
            "the flow runs. Selecting this module subscribes its output image."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {THEME['text_secondary']}; font-size: 11px;")
        layout.addWidget(hint)

        table = QTableWidget(0, 3)
        table.setObjectName("paramTable")
        table.setHorizontalHeaderLabels(["Param Name", "Type", "Association"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(1, 90)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        image_outputs = [(n, p) for n, p in self.tool.outputs.items()
                         if p.data_type.value in ("Image", "Region", "Any")]
        table.setRowCount(len(image_outputs))
        for row, (name, port) in enumerate(image_outputs):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(port.data_type.value))
            table.setItem(row, 2, QTableWidgetItem("Output image"))
        layout.addWidget(table, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Crosshair auxiliary line:"))
        self.chk_crosshair = QCheckBox()
        self.chk_crosshair.setChecked(True)
        row.addWidget(self.chk_crosshair)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(page, "Display Setup")

    # --------------------------------------------------------------- helpers
    def _editor_for(self, key: str, value) -> Optional[QWidget]:
        """Enum / path / typed editor, matching the inspector's parameter vocabulary.

        Mirrors the vendor's parameter editor kinds (manual §8.2, p. 109):
        dropdown select, enable toggle, numeric entry, and a path field with a
        picker (shown abbreviated with the full value in the tooltip).
        """
        from apex_vision.ui.inspector import (PARAM_ENUMS, FIELD_H, BROWSE_W, _is_path_key,
                                           _is_dir_key, abbreviate_path)

        def _commit(v):
            self.tool.set_param(key, v)

        from apex_vision.core import param_schema
        tool_name = getattr(self.tool, "tool_name", "")
        options = param_schema.choices_for(tool_name, key) or (None if tool_name in param_schema.SCHEMA else PARAM_ENUMS.get(key))
        if isinstance(value, str) and options:
            editor = QComboBox()
            editor.addItems(options)
            if value in options:
                editor.setCurrentText(value)
            editor.setFixedHeight(FIELD_H)
            editor.currentTextChanged.connect(lambda v, k=key: self.tool.set_param(k, v))
            return editor

        if isinstance(value, bool):
            editor = QCheckBox()
            editor.setChecked(value)
            editor.setFixedHeight(FIELD_H)
            editor.toggled.connect(lambda v, k=key: self.tool.set_param(k, v))
            return editor

        if isinstance(value, int):
            editor = QSpinBox()
            editor.setRange(-99999, 99999)
            editor.setValue(value)
            editor.setFixedHeight(FIELD_H)
            editor.valueChanged.connect(lambda v, k=key: self.tool.set_param(k, v))
            return editor

        if isinstance(value, float):
            editor = QDoubleSpinBox()
            editor.setRange(-99999.0, 99999.0)
            editor.setDecimals(3)
            editor.setValue(value)
            editor.setFixedHeight(FIELD_H)
            editor.valueChanged.connect(lambda v, k=key: self.tool.set_param(k, v))
            return editor

        if isinstance(value, str):
            line = QLineEdit()
            line.setFixedHeight(FIELD_H)
            if _is_path_key(key):
                full = str(value or "")
                line.setProperty("realPath", full)
                line.setText(abbreviate_path(full))
                line.setToolTip(full)
                line.textEdited.connect(
                    lambda _t, k=key, ed=line: self._commit_typed_path(k, ed))
            else:
                line.setText(value)
                line.textChanged.connect(lambda v, k=key: self.tool.set_param(k, v))
                return line

            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(line, 1)
            btn = QPushButton("Browse")
            btn.setObjectName("fieldAction")
            btn.setFixedWidth(BROWSE_W)
            btn.setFixedHeight(FIELD_H)
            is_dir = _is_dir_key(key)
            btn.setToolTip("Select a folder from local disk" if is_dir
                           else "Select an image file from local disk")
            btn.clicked.connect(
                lambda _=False, k=key, ed=line, d=is_dir: self._pick_path(k, ed, d))
            row.addWidget(btn, 0)
            return holder

        return None

    def _commit_typed_path(self, key: str, line: QLineEdit):
        typed = line.text().strip()
        previous = line.property("realPath") or ""
        if not typed or typed in (previous,):
            return
        self.tool.set_param(key, typed)
        line.setProperty("realPath", typed)
        line.setToolTip(typed)

    def _pick_path(self, key: str, line: QLineEdit, is_dir: bool):
        import os
        from PyQt6.QtWidgets import QFileDialog
        from apex_vision.ui.inspector import abbreviate_path

        previous = str(line.property("realPath") or "")
        start = previous if os.path.exists(previous) else ""
        if is_dir:
            picked = QFileDialog.getExistingDirectory(self, "Select Directory", start)
        else:
            picked, _ = QFileDialog.getOpenFileName(
                self, "Select Image File", os.path.dirname(start) if start else "",
                "Image Files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*.*)")
        if not picked:
            return
        picked = os.path.normpath(picked)
        line.setProperty("realPath", picked)
        line.setText(abbreviate_path(picked))
        line.setToolTip(picked)
        self.tool.set_param(key, picked)

    def run_parameter_values(self) -> Dict[str, object]:
        """Current values of every editor on the Run Params tab."""
        return {key: self.tool.parameters.get(key) for key in self.run_editors}
