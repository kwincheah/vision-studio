"""Result display area — the reference's "结果显示区" (manual region 12).

Reference: Vision Master 4.3.0 manual Fig. 5-2, zoomed at
`docs/references/external/ui_crops/right_column_zoom.png`.  The vendor's result
block is a tab widget with exactly three tabs:

    当前结果 | 历史结果 | 帮助          (Current Result | History Result | Help)

and the Current Result tab holds a table with **one column per output
parameter**, not a fixed module-log schema.  The vendor's BLOB module renders as:

    序号 | 面积 | 周长 | 质心X | 质心Y | 角度 | 长轴 | 短轴 | 圆形度
    Index| Area |Perim |CentroidX|CentroidY|Angle|Major|Minor|Circularity

one row per detected feature.  Modules whose outputs are scalar fall back to a
two-column `Parameter | Value` presentation inside the same grid.

The per-module execution trace this project needs for diagnostics is *not* a tab
here (the vendor has no such tab); it lives in the hidden Module Log dock.
"""
from typing import Any, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QScrollArea
)

from apex_vision.core.base_tool import ToolExecutionResult, ToolStatus
from apex_vision.ui.styles import THEME


# ---------------------------------------------------------------------------
# Feature extraction: turn a tool result into (columns, rows)
# ---------------------------------------------------------------------------

#: Ordered preference for the columns of a per-feature result table.  The labels
#: mirror the vendor table; the aliases match the output names this project's
#: tools actually emit.
FEATURE_COLUMNS: Sequence[Tuple[str, str, Sequence[str]]] = (
    ("Index", "Index", ("index", "idx", "id", "label")),
    ("Class", "Class", ("class", "class_name", "cls", "category")),
    ("Area", "Area", ("area", "region_area", "pixel_area")),
    ("Perimeter", "Perimeter", ("perimeter", "circumference")),
    ("CentroidX", "Centroid X", ("centroidx", "center_x", "cx", "x", "center_x_px")),
    ("CentroidY", "Centroid Y", ("centroidy", "center_y", "cy", "y", "center_y_px")),
    ("Angle", "Angle", ("angle", "theta", "orientation", "rotation")),
    ("Major", "Major", ("major", "major_axis", "length", "long_axis")),
    ("Minor", "Minor", ("minor", "minor_axis", "width", "short_axis")),
    ("Circularity", "Circularity", ("circularity", "roundness")),
    ("Score", "Score", ("score", "match_score", "similarity")),
    ("Radius", "Radius", ("radius", "r")),
    ("Defect", "Defect", ("defect_count", "defects", "count")),
    ("Value", "Value", ("value", "result", "measure", "distance")),
)

#: Legacy column headers kept so `_module_log_headers` stays stable for callers.
MODULE_LOG_HEADERS = ["Module", "Kernel", "Status", "Latency", "Message / Details"]


def _norm(text: Any) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt(v) for v in value)
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_fmt(v)}" for k, v in value.items()) + "}"
    if hasattr(value, "shape") and len(getattr(value, "shape", ())) >= 2:
        return f"Image ({value.shape[1]}x{value.shape[0]})"
    return str(value)


def _is_image(value: Any) -> bool:
    return hasattr(value, "shape") and len(getattr(value, "shape", ())) >= 2


def extract_feature_rows(result: ToolExecutionResult) -> Tuple[List[str], List[List[str]]]:
    """Return ``(headers, rows)`` for a per-feature result table.

    A per-feature table is produced when the module reports a list of records
    (the vendor's BLOB/circle/defect style).  Otherwise the caller should use
    :func:`extract_parameter_rows`.
    """
    outputs = result.outputs or {}

    # 1. Explicit record lists, e.g. "Blobs": [{...}, {...}]
    for key, value in outputs.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            records = value
            break
    else:
        records = None

    if records:
        present = []
        for canonical, label, aliases in FEATURE_COLUMNS:
            wanted = {_norm(a) for a in aliases}
            if any(_norm(k) in wanted for k in records[0].keys()):
                present.append((canonical, label, wanted))
        if present:
            headers = ["Index"] + [label for canonical, label, _ in present
                                   if canonical != "Index"]
            rows = []
            for i, rec in enumerate(records):
                by_norm = {_norm(k): v for k, v in rec.items()}
                row = [str(i)]
                for canonical, _label, wanted in present:
                    if canonical == "Index":
                        continue
                    found = next((by_norm[w] for w in wanted if w in by_norm), "")
                    row.append(_fmt(found) if found != "" else "")
                rows.append(row)
            return headers, rows

    # 2. Parallel scalar lists, e.g. "CenterX": [1,2,3], "Radius": [4,5,6]
    lists = {k: v for k, v in outputs.items()
             if isinstance(v, (list, tuple)) and v and not isinstance(v[0], (dict, list))}
    if lists and len(lists) >= 2:
        headers = ["Index"]
        ordered: List[Tuple[str, List[Any]]] = []
        for canonical, label, aliases in FEATURE_COLUMNS:
            wanted = {_norm(a) for a in aliases}
            for key, value in lists.items():
                if _norm(key) in wanted and key not in [k for k, _ in ordered]:
                    headers.append(label)
                    ordered.append((key, list(value)))
                    break
        if len(ordered) >= 2:
            n = max(len(v) for _, v in ordered)
            rows = []
            for i in range(n):
                row = [str(i)]
                for _key, value in ordered:
                    row.append(_fmt(value[i]) if i < len(value) else "")
                rows.append(row)
            return headers, rows

    return [], []


def extract_parameter_rows(result: ToolExecutionResult) -> Tuple[List[str], List[List[str]]]:
    """Return ``(headers, rows)`` for a scalar result presented as Parameter|Value."""
    rows: List[List[str]] = []
    for key, value in (result.outputs or {}).items():
        if _is_image(value):
            continue
        rows.append([key.replace("_", " "), _fmt(value)])
    return ["Parameter", "Value"], rows


def build_result_table(result: Optional[ToolExecutionResult]) -> Tuple[List[str], List[List[str]]]:
    """Choose the best tabular presentation for a module result."""
    if result is None:
        return [], []
    headers, rows = extract_feature_rows(result)
    if headers and rows:
        return headers, rows
    return extract_parameter_rows(result)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------
class ResultTableWidget(QTableWidget):
    """Read-only result grid with the reference's header/row styling.

    Column widths are re-applied whenever the viewport is resized: the right
    column is a dock that the operator drags, and QTableWidget otherwise keeps the
    widths it computed for the previous (narrower) viewport, eliding the parameter
    column header.
    """

    def __init__(self, parent=None):
        super().__init__(0, 0, parent)
        self.setObjectName("resultGrid")
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(True)
        self.verticalHeader().setDefaultSectionSize(21)
        self.horizontalHeader().setDefaultSectionSize(96)
        self.horizontalHeader().setMinimumSectionSize(48)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.setWordWrap(False)
        self.setShowGrid(True)
        self._headers: List[str] = []

    def set_table(self, headers: List[str], rows: List[List[str]]):
        self._headers = list(headers)
        self.clear()
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(rows))
        mono = QFont("Consolas", 10)
        for r, row in enumerate(rows):
            for c in range(len(headers)):
                text = row[c] if c < len(row) else ""
                item = QTableWidgetItem(text)
                item.setFont(mono if c else QFont("Segoe UI", 10))
                item.setToolTip(text)
                if c == 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.setItem(r, c, item)
        self._apply_widths()

    def _apply_widths(self):
        """Give the first column room for its own header text."""
        if self.columnCount() == 0:
            return
        first = 52 if self._headers and self._headers[0] == "Index" else 150
        self.setColumnWidth(0, first)
        for c in range(1, self.columnCount()):
            self.setColumnWidth(c, 104)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_widths()


class ResultDisplayArea(QWidget):
    """Current Result / History / Module Log / Help tabs over the result grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("resultDisplayArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("resultTabs")
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs)

        # ---- Current Result: module-specific parameter columns (region 12) --
        current = QWidget()
        cv = QVBoxLayout(current)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        self.lbl_current_title = QLabel("No module selected")
        self.lbl_current_title.setObjectName("resultCaption")
        self.lbl_current_title.setContentsMargins(8, 3, 8, 3)
        self.lbl_current_title.setWordWrap(True)
        cv.addWidget(self.lbl_current_title)

        self.table = ResultTableWidget()
        # Keeps the header plus a couple of data rows readable when the dock is
        # shallow; the pane's size hint is released so the right column's measured
        # split can be applied (see `layout_metrics.split_right_column`).
        self.table.setMinimumHeight(56)
        cv.addWidget(self.table, 1)
        self.tabs.addTab(current, "Current Result")

        # ---- History ---------------------------------------------------------
        self.history_table = QTableWidget(0, 6)
        self.history_table.setObjectName("historyGrid")
        self.history_table.setHorizontalHeaderLabels(
            ["Cycle", "Flow", "Verdict", "Flow Time", "Failed Module", "Details"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive)
        for col, width in ((0, 56), (1, 108), (2, 74), (3, 96), (4, 150)):
            self.history_table.setColumnWidth(col, width)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.history_table, "History")

        # ---- Module Log: off-surface, exposed for the hidden diagnostics dock --
        # The vendor's result block has no such tab, so this table is built but
        # never added here; `main_window` mounts it in the Module Log dock.
        self.log_table = QTableWidget(0, len(MODULE_LOG_HEADERS))
        self.log_table.setObjectName("moduleLogGrid")
        self.log_table.setHorizontalHeaderLabels(MODULE_LOG_HEADERS)
        self.log_table.verticalHeader().setVisible(True)
        self.log_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.log_table.horizontalHeader().setStretchLastSection(True)
        for col, width in ((0, 190), (1, 150), (2, 72), (3, 92)):
            self.log_table.setColumnWidth(col, width)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # ---- Help ------------------------------------------------------------
        help_widget = QWidget()
        hl = QVBoxLayout(help_widget)
        hl.setContentsMargins(0, 0, 0, 0)
        self.lbl_help = QLabel("")
        self.lbl_help.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_help.setWordWrap(True)
        self.lbl_help.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_help.setStyleSheet(f"color: {THEME['text_secondary']};")
        help_scroll = QScrollArea()
        help_scroll.setWidgetResizable(True)
        help_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        help_scroll.setWidget(self.lbl_help)
        help_scroll.setMinimumHeight(60)
        hl.addWidget(help_scroll)
        self.tabs.addTab(help_widget, "Help")

        # Compatibility aliases for existing callers/tests.
        self.current_tab = current
        self.help_tab = help_widget

    # ------------------------------------------------------------------ API
    def set_module_result(self, module_name: str, result: Optional[ToolExecutionResult],
                          tool_name: str = ""):
        """Render one module's results using the best available table shape."""
        if result is None:
            self.lbl_current_title.setText(
                f"{module_name} — not executed yet" if module_name else "No module selected")
            self.table.set_table([], [])
            return

        status = result.status.value.upper()
        colour = (THEME["status_ok_text"] if result.status in
                  (ToolStatus.OK, ToolStatus.READY, ToolStatus.BYPASS)
                  else THEME["status_warn_text"] if result.status == ToolStatus.TIMEOUT
                  else THEME["status_error_text"])
        kind = f" &middot; {tool_name}" if tool_name else ""
        self.lbl_current_title.setText(
            f"<b>{module_name}</b>{kind} &nbsp; "
            f"<span style='color:{colour}'>{status}</span> &nbsp; "
            f"<span style='color:{THEME['text_muted']}'>{result.elapsed_ms:.2f} ms</span>"
            f"<br><span style='color:{THEME['text_secondary']}'>{result.message or ''}</span>"
        )

        headers, rows = build_result_table(result)
        self.table.set_table(headers, rows)
        self.table.setToolTip(f"{len(rows)} row(s), {len(headers)} parameter column(s)")

    def set_help_text(self, html: str):
        self.lbl_help.setText(html)
