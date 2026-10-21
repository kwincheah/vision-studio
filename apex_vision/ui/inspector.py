"""Property Inspector Panel for Vision Master Clone.

Layout mirrors the reference module panel (manual p.96): identity header,
aligned parameter form, and a compact live verification strip.  The full
output-port table lives in the Image|Result column (manual p.87) so the
inspector does not compete with it for vertical space.
"""
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QSpinBox,
    QDoubleSpinBox, QComboBox, QCheckBox, QGroupBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QTextEdit,
    QFileDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor
from typing import Dict, List
from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, is_compatible_type
from apex_vision.ui.styles import THEME


# Parameter-form metrics.  A single label column width keeps every field on the
# same vertical axis; the control height is fixed so spin boxes, combo boxes,
# line edits and check boxes share one baseline.
LABEL_W = 92
FIELD_H = 24
BROWSE_W = 66

# Keys that address the file system. Deliberately excludes the bare "file"
# token: "File Format" is an enum, not a location, and must not grow a Browse
# button meant for paths.
_PATH_KEYS = ("path", "dir", "folder")


def _is_path_key(key: str) -> bool:
    k = key.lower()
    return any(token in k for token in _PATH_KEYS)


def _is_dir_key(key: str) -> bool:
    k = key.lower()
    return "dir" in k or "folder" in k


#: Enum parameters presented as dropdowns. Mirrors the vendor's documented
#: "dropdown select" editor kind (manual §8.2, p. 109).
PARAM_ENUMS: Dict[str, List[str]] = {
    "source_type": ["Synthetic", "File", "Camera", "Industrial GigE", "Industrial USB3", "IP Stream"],
    "pattern_type": ["PCB Inspection", "Calibration Grid", "Circles & Holes", "Barcode Sample"],
    "color_mode": ["BGR", "Grayscale"],
    "trigger_mode": ["Continuous", "Software Trigger", "Hardware Trigger (Line0)", "Hardware Trigger (Line1)"],
    "method": ["Otsu", "Adaptive", "Manual"],
    "filter_type": ["Gaussian", "Median", "Sharpen", "Bilateral"],
    "operation": ["Open", "Close", "Dilate", "Erode", "Gradient"],
    "operator": [">=", "<=", ">", "<", "==", "!=", "Between"],
    "preset_color": ["Green", "Red", "Blue", "Yellow", "Custom"],
    "mask_output": ["Color Keep", "Binary Mask", "Inverse"],
    "calibration_mode": ["9-Point Affine", "4-Point Homography", "2-Point Scaling"],
    "mode": ["Simulation (Loopback Log)", "TCP Client"],
    "format": ["CSV", "JSON", "Plain Text"],
    "file_format": ["PNG", "JPEG", "BMP"],
    "save_mode": ["Always Save", "Only on NG", "Only on OK"],
    "device": ["cpu", "cuda", "auto"],
}


def abbreviate_path(value: str, max_chars: int = 38) -> str:
    """Shorten a path for display while keeping the informative tail.

    ``C:\\Users\\me\\apex_vision\\samples\\pcb_sample.png`` becomes
    ``…\\samples\\pcb_sample.png``.  The complete filename is always preserved;
    only the directory chain is dropped, and only as far as needed to fit
    ``max_chars``.  The full value stays on the widget and in its tooltip, so
    abbreviation never loses data.
    """
    if not value:
        return ""
    raw = str(value).strip().strip('"').strip("'")
    if not raw:
        return ""
    if len(raw) <= max_chars:
        return raw

    sep = "\\" if "\\" in raw else ("/" if "/" in raw else None)
    if sep is None:
        # Not a path at all - keep the leading characters, as is conventional for
        # a plain value that is simply too long.
        return raw[: max(1, max_chars - 1)] + "…"

    parts = [p for p in raw.split(sep) if p]
    tail = parts[-1] if parts else raw
    if len(tail) + 2 > max_chars:
        # Even the bare filename does not fit: keep its most specific tail.
        return "…" + tail[-(max_chars - 1):]

    for count in range(2, len(parts) + 1):
        candidate = sep.join(parts[-count:])
        if len(candidate) + 2 > max_chars:
            break
        tail = candidate
    return "…" + sep + tail


class ParameterInspectorWidget(QWidget):
    param_changed = pyqtSignal(str, object)
    request_roi_draw = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_tool: VisionToolBase = None
        self.last_result: ToolExecutionResult = None

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(6, 6, 6, 6)
        self.layout.setSpacing(5)

        # ---- identity header ------------------------------------------------
        self.header_card = QWidget()
        self.header_card.setStyleSheet(
            f"background-color: {THEME['bg_surface']}; "
            f"border: 1px solid {THEME['border_subtle']}; border-radius: {THEME['r_control']}px;"
        )
        h_card_layout = QVBoxLayout(self.header_card)
        h_card_layout.setContentsMargins(7, 5, 7, 5)
        h_card_layout.setSpacing(2)

        self.lbl_title = QLabel("NO MODULE SELECTED")
        self.lbl_title.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {THEME['accent_primary']};"
        )
        h_card_layout.addWidget(self.lbl_title)

        self.lbl_desc = QLabel("Select a module in the flow graph or tool box.")
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet(f"color: {THEME['text_secondary']}; font-size: 11px;")
        h_card_layout.addWidget(self.lbl_desc)

        self.layout.addWidget(self.header_card, 0)

        # ---- parameter surface ---------------------------------------------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {THEME['border_subtle']}; "
            f"background-color: {THEME['bg_app']}; }}"
        )
        self.param_container = QWidget()
        self.param_container.setObjectName("paramContainer")
        self.param_layout = QFormLayout(self.param_container)
        self.param_layout.setContentsMargins(8, 8, 8, 8)
        self.param_layout.setHorizontalSpacing(8)
        self.param_layout.setVerticalSpacing(6)
        self.param_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.param_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.param_layout.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.param_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.scroll.setWidget(self.param_container)
        # A form's implicit width is the sum of every row, which would let a long
        # path force the dock wider; a small fixed hint keeps the dock shrinkable.
        self.param_container.setMinimumWidth(180)
        self.layout.addWidget(self.scroll, stretch=1)

        # ---- live verification strip ----------------------------------------
        self.lbl_verdict = QLabel("Not executed")
        self.lbl_verdict.setObjectName("inspectorVerdict")
        self.lbl_verdict.setWordWrap(True)
        self.lbl_verdict.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_verdict.setStyleSheet(
            f"background-color: {THEME['bg_surface_alt']}; "
            f"border: 1px solid {THEME['border_subtle']}; border-radius: {THEME['r_control']}px; "
            f"padding: 4px 6px; color: {THEME['text_secondary']}; font-size: 11px;"
        )
        self.layout.addWidget(self.lbl_verdict, 0)

        # Compatibility surface: earlier revisions exposed a per-port table here.
        # It is retained off-layout so existing callers keep working, while the
        # visible result grid is the Image|Result panel (manual p.87).
        self.result_table = QTableWidget(0, 2)
        self.result_table.setHorizontalHeaderLabels(["PORT", "VALUE"])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.result_table.hide()

        self.result_group = QGroupBox("MODULE OUTPUTS")
        self.res_layout = QVBoxLayout(self.result_group)
        self.res_layout.setContentsMargins(0, 0, 0, 0)
        self.res_layout.addWidget(self.result_table)
        self.result_group.hide()

    def set_tool(self, tool: VisionToolBase, last_result: ToolExecutionResult = None, pipeline=None):
        self.current_tool = tool
        self.pipeline = pipeline
        self.lbl_title.setText(f"{tool.name}  [{tool.tool_name}]")
        self.lbl_desc.setText(tool.description)

        self._clear_param_form()

        # Input parameters following connected lines (Hikrobot VM line subscription)
        if self.pipeline and getattr(tool, "inputs", None):
            for in_name, in_port in tool.inputs.items():
                lbl_text = f"{in_name} In:"
                combo = QComboBox()
                combo.setFixedHeight(FIELD_H)
                combo.setObjectName(f"inWire_{in_name}")
                combo.addItem("<None>", None)
                sel_i = 0
                idx = 1
                curr = None
                for c in self.pipeline.connections:
                    if c.to_node == tool.instance_id and c.to_port == in_name:
                        curr = c
                        break
                for nid, other in self.pipeline.nodes.items():
                    if nid == tool.instance_id:
                        continue
                    for out_n, out_p in other.outputs.items():
                        if is_compatible_type(out_p.data_type, in_port.data_type):
                            combo.addItem(f"{other.name}.{out_n}", (nid, out_n))
                            if curr and curr.from_node == nid and curr.from_port == out_n:
                                sel_i = idx
                            idx += 1
                combo.setCurrentIndex(sel_i)

                def _wire_change(index, p_n=in_name, cb=combo):
                    d = cb.itemData(index)
                    if d is None:
                        self.pipeline.disconnect(tool.instance_id, p_n)
                    else:
                        fn, fp = d
                        self.pipeline.connect(fn, fp, tool.instance_id, p_n, force=True)
                    self.param_changed.emit(f"wire_{p_n}", d)

                combo.currentIndexChanged.connect(_wire_change)
                self.param_layout.addRow(lbl_text, combo)

        for key, val in tool.parameters.items():
            if key == "code":
                lbl = QLabel("Python Logic Script")
                lbl.setStyleSheet(
                    f"font-weight: 600; color: {THEME['accent_primary']}; font-size: 11px;"
                )
                self.param_layout.addRow(lbl)
                code_edit = QTextEdit(str(val))
                code_edit.setFont(QFont("Consolas", 10))
                code_edit.setMinimumHeight(96)
                code_edit.setStyleSheet(
                    f"background-color: {THEME['bg_control']}; color: {THEME['text_primary']}; "
                    f"border: 1px solid {THEME['border_control']};"
                )
                code_edit.textChanged.connect(
                    lambda k=key, ed=code_edit: self._on_val_changed(k, ed.toPlainText())
                )
                self.param_layout.addRow(code_edit)
                continue

            label_text = key.replace("_", " ").title()
            widget = self._build_param_widget(key, val)
            if widget is None:
                continue

            hint = self._help_for_key(key)
            if hint:
                widget.setToolTip(hint)
            field = self._wrap_field(widget, key, val)
            if isinstance(widget, QLineEdit) and widget.property("realPath") is not None:
                # The visible text is abbreviated, so the full value must be
                # recoverable from the field's tooltip.
                full = widget.property("realPath")
                base = f"{hint}\n\n" if hint else ""
                tooltip = f"{base}{full}" if full else (hint or "No path set")
                widget.setToolTip(tooltip)
                field.setToolTip(tooltip)
            self.param_layout.addRow(f"{label_text}:", field)

        self.param_layout.addRow(self._make_stretch_row())
        QTimer.singleShot(0, self._align_label_column)
        self.update_results(last_result)

    # ------------------------------------------------------------------ form
    def _clear_param_form(self):
        """Remove every row of the parameter form (labels included)."""
        while self.param_layout.rowCount():
            self.param_layout.removeRow(0)

    def _align_label_column(self):
        """Force one label width so all fields share a vertical axis."""
        for row in range(self.param_layout.rowCount()):
            item = self.param_layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, QLabel):
                widget.setFixedWidth(LABEL_W)
                widget.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )

    def _make_stretch_row(self) -> QWidget:
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        spacer.setMinimumHeight(4)
        return spacer

    def _wrap_field(self, widget: QWidget, key: str, val) -> QWidget:
        """Attach a trailing action button (Browse / Draw) when the key needs one.

        The buttons live in a fixed-width container so the input fields of every
        row end on the same vertical line.
        """
        button = None
        if _is_path_key(key):
            is_dir = _is_dir_key(key)
            button = QPushButton("Browse")
            button.setObjectName("fieldAction")
            button.setFixedWidth(BROWSE_W)
            button.setFixedHeight(FIELD_H)
            button.setToolTip(
                "Select a folder from local disk" if is_dir
                else "Select an image file from local disk"
            )
            button.clicked.connect(
                lambda _=False, k=key, line=widget, d=is_dir: (
                    self._on_browse_dir(k, line) if d else self._on_browse_file(k, line)
                )
            )
        elif isinstance(val, list) and "roi" in key.lower():
            button = QPushButton("Draw")
            button.setObjectName("fieldAction")
            button.setFixedWidth(BROWSE_W)
            button.setFixedHeight(FIELD_H)
            button.setToolTip("Draw this ROI on the image viewport")
            button.clicked.connect(self.request_roi_draw.emit)

        if button is None:
            return widget

        wrap = QWidget()
        wrap.setObjectName("fieldRow")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(widget, 1)
        row.addWidget(button, 0)
        return wrap

    def _build_param_widget(self, key: str, val) -> QWidget:
        """Create the value editor for a parameter, matching its Python type and ParamDef schema."""
        pdef = None
        if self.current_tool and hasattr(self.current_tool, "get_param_defs"):
            pdefs = self.current_tool.get_param_defs()
            pdef = pdefs.get(key) if isinstance(pdefs, dict) else None

        # 1. Handle Enum / Choices schema explicitly
        options = []
        if pdef and getattr(pdef, "choices", None):
            options = [str(c) for c in pdef.choices]
        elif isinstance(val, str):
            options = self._get_options_for_key(key)

        if options:
            combo = QComboBox()
            combo.addItems(options)
            cur_str = str(val)
            if cur_str in options:
                combo.setCurrentText(cur_str)
            combo.setFixedHeight(FIELD_H)

            def _handle_choice_change(text: str, k=key, original_val=val):
                if isinstance(original_val, int) and not isinstance(original_val, bool):
                    try:
                        self._on_val_changed(k, int(text))
                        return
                    except ValueError:
                        pass
                elif isinstance(original_val, float):
                    try:
                        self._on_val_changed(k, float(text))
                        return
                    except ValueError:
                        pass
                self._on_val_changed(k, text)

            combo.currentTextChanged.connect(_handle_choice_change)
            return combo

        if isinstance(val, bool):
            chk = QCheckBox()
            chk.setChecked(val)
            chk.setFixedHeight(FIELD_H)
            chk.toggled.connect(lambda state, k=key: self._on_val_changed(k, state))
            return chk

        if isinstance(val, int):
            sp = QSpinBox()
            min_v = int(pdef.min_value) if pdef and pdef.min_value is not None else -99999
            max_v = int(pdef.max_value) if pdef and pdef.max_value is not None else 99999
            step = int(pdef.step) if pdef and pdef.step is not None else 1
            sp.setRange(min_v, max_v)
            sp.setSingleStep(step)
            sp.setValue(val)
            sp.setFixedHeight(FIELD_H)
            sp.valueChanged.connect(lambda v, k=key: self._on_val_changed(k, v))
            return sp

        if isinstance(val, float):
            dsp = QDoubleSpinBox()
            min_v = float(pdef.min_value) if pdef and pdef.min_value is not None else -99999.0
            max_v = float(pdef.max_value) if pdef and pdef.max_value is not None else 99999.0
            step = float(pdef.step) if pdef and pdef.step is not None else 0.1
            dsp.setRange(min_v, max_v)
            dsp.setSingleStep(step)
            dsp.setDecimals(3)
            dsp.setValue(val)
            dsp.setFixedHeight(FIELD_H)
            dsp.valueChanged.connect(lambda v, k=key: self._on_val_changed(k, v))
            return dsp

        if isinstance(val, str):
            le = QLineEdit()
            le.setFixedHeight(FIELD_H)
            if _is_path_key(key):
                self._set_path_display(le, val)
                le.textEdited.connect(
                    lambda text, k=key, line=le: self._on_path_edited(k, line)
                )
            else:
                le.setText(str(val))
                le.textChanged.connect(
                    lambda text, k=key: self._on_val_changed(k, text)
                )
            return le

        if isinstance(val, list):
            le = QLineEdit(str(val))
            le.setFixedHeight(FIELD_H)
            le.textChanged.connect(lambda text, k=key: self._on_list_changed(k, text))
            return le

        return None

    # ------------------------------------------------------------- path fields
    def _set_path_display(self, line_edit: QLineEdit, raw_value: str):
        """Store the real path on the widget and show an abbreviated form."""
        full = str(raw_value or "").strip().strip('"').strip("'")
        line_edit.setProperty("realPath", full)
        line_edit.setText(abbreviate_path(full))
        line_edit.setCursorPosition(len(line_edit.text()))
        line_edit.setToolTip(full or "No path set")

    def _on_path_edited(self, key: str, line_edit: QLineEdit):
        """Commit a hand-typed path.

        The visible text may be abbreviated, so this only commits when what the
        operator typed is a usable path (or when it is left unchanged).
        """
        typed = line_edit.text().strip()
        previous = line_edit.property("realPath") or ""
        if typed in ("", previous, abbreviate_path(previous)):
            return

        candidate = os.path.normpath(typed) if os.path.exists(typed) else typed
        line_edit.setProperty("realPath", candidate)
        line_edit.setToolTip(candidate)
        self._on_val_changed(key, candidate)

    def _help_for_key(self, key: str) -> str:
        if self.current_tool and hasattr(self.current_tool, "get_param_defs"):
            pdefs = self.current_tool.get_param_defs()
            if isinstance(pdefs, dict) and key in pdefs and getattr(pdefs[key], "description", None):
                return pdefs[key].description

        k = key.lower()
        if "template" in k and "roi" in k:
            return "Template search region within the image (x, y, width, height)."
        if "roi" in k:
            return "Region of interest within the image (x, y, width, height)."
        if "file" in k and "path" in k:
            return ("Image or resource file to load from local disk. "
                    "Use Browse to pick a file.")
        if "dir" in k or "folder" in k:
            return "Output folder for written results. Use Browse to pick a folder."
        return ""

    def _on_browse_file(self, key: str, line_edit: QLineEdit):
        previous = line_edit.property("realPath") or line_edit.text()
        current = str(previous).strip().strip('"').strip("'")
        start_dir = os.path.dirname(current) if os.path.exists(current) else ""
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Image File",
            start_dir,
            "Image Files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*.*)"
        )
        if fpath:
            norm_path = os.path.normpath(fpath)
            self._set_path_display(line_edit, norm_path)
            self._on_val_changed(key, norm_path)

    def _on_browse_dir(self, key: str, line_edit: QLineEdit):
        previous = line_edit.property("realPath") or line_edit.text()
        current = str(previous).strip().strip('"').strip("'")
        start_dir = current if os.path.exists(current) else ""
        dpath = QFileDialog.getExistingDirectory(self, "Select Directory", start_dir)
        if dpath:
            norm_path = os.path.normpath(dpath)
            self._set_path_display(line_edit, norm_path)
            self._on_val_changed(key, norm_path)

    def update_roi_from_canvas(self, roi_coords: list):
        if not self.current_tool:
            return
        for key in ["roi", "template_roi"]:
            if key in self.current_tool.parameters:
                self.current_tool.set_param(key, roi_coords)
                self.set_tool(self.current_tool)
                self.param_changed.emit(key, roi_coords)
                break

    def _get_options_for_key(self, key: str) -> list:
        # 1. Check if tool exposes typed ParamDef with enum choices
        if self.current_tool and hasattr(self.current_tool, "get_param_defs"):
            pdefs = self.current_tool.get_param_defs()
            if key in pdefs and pdefs[key].choices:
                return pdefs[key].choices

        if key == "camera_device":
            try:
                from apex_vision.core.camera_manager import CameraManager
                cm = CameraManager.get_instance()
                devs = cm.list_devices()
                return [d.device_id for d in devs]
            except Exception:
                return ["virtual_gige_0", "virtual_usb3_0", "webcam_0", "ip_stream_custom"]
        if self.current_tool is not None:                      # per-tool choices: the same key means different things on different tools
            from apex_vision.core import param_schema
            per_tool = param_schema.choices_for(getattr(self.current_tool, "tool_name", ""), key)
            if per_tool:
                return per_tool
            if getattr(self.current_tool, "tool_name", "") in param_schema.SCHEMA:
                return []
        return PARAM_ENUMS.get(key, [])

    def _on_val_changed(self, key: str, value):
        if self.current_tool:
            self.current_tool.set_param(key, value)
            self.param_changed.emit(key, value)
            if key == "source_type":
                self.set_tool(self.current_tool)

    def _on_list_changed(self, key: str, text: str):
        import ast
        import json
        val = None
        stripped = text.strip()
        try:
            val = json.loads(stripped)
        except Exception:
            try:
                val = ast.literal_eval(stripped)
            except Exception:
                val = None

        if isinstance(val, list) and self.current_tool:
            self.current_tool.set_param(key, val)
            self.param_changed.emit(key, val)

    def update_results(self, result: ToolExecutionResult):
        """Render the live verdict strip. The full port table lives in the
        Image|Result panel; this strip keeps the operator oriented without
        duplicating that surface."""
        self.last_result = result
        self.result_table.setRowCount(0)
        if not result:
            self.lbl_verdict.setText("Not executed")
            self.lbl_verdict.setStyleSheet(
                f"background-color: {THEME['bg_surface_alt']}; "
                f"border: 1px solid {THEME['border_subtle']}; border-radius: {THEME['r_control']}px; "
                f"padding: 4px 6px; color: {THEME['text_secondary']}; font-size: 11px;"
            )
            return

        is_ok = result.status in (ToolStatus.OK, ToolStatus.BYPASS, ToolStatus.READY)
        colour = THEME["status_ok_text"] if is_ok else (
            THEME["status_warn_text"] if result.status == ToolStatus.TIMEOUT
            else THEME["status_error_text"]
        )
        self.lbl_verdict.setText(
            f"<b style='color:{colour}'>{result.status.value.upper()}</b>"
            f"<span style='color:{THEME['text_muted']}'> &middot; {result.elapsed_ms:.2f} ms</span><br>"
            f"<span style='color:{THEME['text_secondary']}'>{result.message or 'No message'}</span>"
        )
        self.lbl_verdict.setStyleSheet(
            f"background-color: {THEME['bg_surface_alt']}; "
            f"border: 1px solid {THEME['border_subtle']}; border-radius: {THEME['r_control']}px; "
            f"padding: 4px 6px; color: {THEME['text_secondary']}; font-size: 11px;"
        )

        # Keep the compatibility table populated for API consumers.
        for k, v in result.outputs.items():
            if k in ("Image", "Mask") and hasattr(v, "shape"):
                val_str = f"Image ({v.shape[1]}x{v.shape[0]})"
            elif isinstance(v, float):
                val_str = f"{v:.4f}"
            else:
                val_str = str(v)
            self._add_row(k, val_str)

    def _add_row(self, key: str, val: str, is_status: bool = False, is_ok: bool = True):
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)

        k_item = QTableWidgetItem(key)
        k_item.setFont(QFont("Segoe UI", 10))
        v_item = QTableWidgetItem(val)
        v_item.setFont(QFont("Consolas", 10))

        if is_status:
            v_item.setForeground(QColor(THEME['status_ok_text']) if is_ok else QColor(THEME['status_error_text']))
            v_item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

        self.result_table.setItem(row, 0, k_item)
        self.result_table.setItem(row, 1, v_item)