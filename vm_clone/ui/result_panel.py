"""Module result display panel (manual p.87 "Result Display Area").

The reference shows a three column grid:

    Param Name | Current Result | Global Variable

where parameter groups (``OutputCircle``, ``Center Point``, ``CircleContourPoint``)
are collapsible rows and every leaf value carries a link glyph in the third
column so it can be subscribed to a global variable.  This module reproduces
that structure with a real ``QTreeWidget`` so expansion, selection and
subscription are genuine interactions.
"""
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QHeaderView, QMenu,
    QInputDialog, QMessageBox
)

from vm_clone.core.base_tool import ToolExecutionResult, ToolStatus
from vm_clone.ui.styles import THEME
from vm_clone.ui.icons import get_action_icon


COL_PARAM = 0
COL_VALUE = 1
COL_LINK = 2


def _link_icon(color: str = "#4f565c") -> QIcon:
    """Chain-link subscription glyph used in the reference third column."""
    return get_action_icon("link", 14)


class ResultTreeWidget(QTreeWidget):
    """Result grid.

    ``QTreeWidget``'s own size hint reflects the summed column widths, which made
    the enclosing dock refuse to shrink and pushed the third column out of view.
    A modest fixed-size hint lets the dock be resized freely while the column
    model (see ``ModuleResultPanel._apply_columns``) redistributes the width.
    """

    MIN_W = 150
    MIN_H = 96

    def sizeHint(self):
        return QSize(self.MIN_W, self.MIN_H)

    def minimumSizeHint(self):
        return QSize(self.MIN_W, self.MIN_H)


class ModuleResultPanel(QWidget):
    """Param Name / Current Result / Global Variable result grid."""

    variable_bound = pyqtSignal(str, str)   # path, variable name
    variable_unbound = pyqtSignal(str)      # path

    def __init__(self, global_variables: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.global_variables = global_variables if global_variables is not None else {}
        self._bindings: Dict[str, str] = {}
        self._module_name = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tree = ResultTreeWidget()
        self.tree.setObjectName("resultTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Param Name", "Current Result", "Global Var."])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(12)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)

        header = self.tree.header()
        header.setSectionResizeMode(COL_PARAM, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_VALUE, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_LINK, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(56)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.tree.setHorizontalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(self.tree)

        # Column model: the reference's three columns must all stay readable.
        # The link (global-variable) column is a fixed 30 px glyph column which
        # folds away in very narrow docks; the remaining width is split 42/58
        # between the parameter name and the value.
        self._link_visible = True
        self._col_initialised = False
        self._apply_columns()

    # ------------------------------------------------------------- layout
    def refresh_columns(self):
        """Public entry point: re-apply the column model (call after resize/show)."""
        self._apply_columns()

    def _apply_columns(self):
        """Distribute the tree width so no column is clipped.

        Uses the parent-dock width rather than ``tree.viewport().width()``: the
        viewport reports its stale (pre-layout) width while the dock is being
        resized, which is what caused the third column to be pushed out of view.
        """
        header = self.tree.header()
        margins = self.layout().contentsMargins()
        parent = self.parentWidget()
        parent_w = parent.width() if parent is not None else 0
        vp = self.tree.viewport().width()

        # The tree lives inside a QStackedWidget that reports the dock width, but
        # the tree's own viewport keeps a stale width until the layout settles.
        # Use the smaller of the two so a narrow dock is never over-estimated.
        candidates = [w for w in (parent_w, vp) if w > 60]
        avail = min(candidates) if candidates else 190
        avail = max(120, avail - margins.left() - margins.right())
        # Width of the global-variable column: enough for the header label and a
        # variable name such as "g_CountOK", without starving the value column.
        link_full = 96
        link_w = link_full if self._link_visible else 0

        if avail < 300 and self._link_visible:
            # Too narrow for three readable columns: keep name + value readable
            # and drop the subscription column (binding stays available through
            # the row context menu / double-click).
            self._link_visible = False
            link_w = 0
        elif avail >= 330 and not self._link_visible:
            self._link_visible = True
            link_w = link_full

        header.setSectionHidden(COL_LINK, not self._link_visible)
        body = max(110, avail - link_w)
        name_w = max(70, int(body * 0.48))
        value_w = max(80, body - name_w)
        header.resizeSection(COL_PARAM, name_w)
        header.resizeSection(COL_VALUE, value_w)
        header.resizeSection(COL_LINK, link_w)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_columns()
        # The enclosing QDockWidget finishes its own resize after this event, so
        # re-run the column model once the geometry has settled.
        QTimer.singleShot(0, self._apply_columns)

    def showEvent(self, event):
        """Re-fit columns when the tab becomes visible.

        A QStackedWidget only lays out the current page, so this panel can keep a
        stale width from construction time until it is first shown; the column
        model must run again once the real geometry is known.
        """
        super().showEvent(event)
        self._apply_columns()
        QTimer.singleShot(0, self._apply_columns)

    # ------------------------------------------------------------------ data
    def set_module_result(self, module_name: str, result: Optional[ToolExecutionResult]):
        self._module_name = module_name
        self.tree.clear()
        self._apply_columns()
        if result is None:
            return

        is_ok = result.status == ToolStatus.OK
        status_color = THEME["status_ok_text"] if is_ok else THEME["status_error_text"]

        root = QTreeWidgetItem([module_name, "", ""])
        root.setFirstColumnSpanned(False)
        root.setExpanded(True)
        bold = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        root.setFont(COL_PARAM, bold)
        root.setForeground(COL_PARAM, QColor(THEME['text_primary']))
        self.tree.addTopLevelItem(root)
        root.setExpanded(True)

        self._add_leaf(root, "ModuStatus", "1" if is_ok else "0", status_color)
        self._add_leaf(root, "TimeCost", f"{result.elapsed_ms:.4f}")
        self._add_leaf(root, "ModuStatusMsg", result.message)

        outputs_group = QTreeWidgetItem(["Outputs", "", ""])
        outputs_group.setExpanded(True)
        outputs_group.setFont(COL_PARAM, bold)
        outputs_group.setForeground(COL_PARAM, QColor(THEME['text_secondary']))
        root.addChild(outputs_group)
        outputs_group.setExpanded(True)

        for key, value in result.outputs.items():
            if hasattr(value, "shape") and len(getattr(value, "shape", ())) >= 2:
                text = f"Image ({value.shape[1]}x{value.shape[0]})"
            elif isinstance(value, float):
                text = f"{value:.4f}"
            elif isinstance(value, (list, tuple, dict)):
                text = ", ".join(str(v) for v in value) if not isinstance(value, dict) else str(value)
            else:
                text = str(value)
            self._add_leaf(outputs_group, str(key), text)

        # Module parameter groups so the panel is never empty before a run.
        for key, value in getattr(result, "meta", {}).items():
            self._add_leaf(outputs_group, str(key), str(value))

    def set_from_outputs(self, module_name: str, outputs: Dict[str, Any], elapsed_ms: float = 0.0,
                         status: Optional[ToolStatus] = None, message: str = ""):
        res = ToolExecutionResult(
            status=status or ToolStatus.READY,
            message=message,
            elapsed_ms=elapsed_ms,
            outputs=dict(outputs),
        )
        self.set_module_result(module_name, res)

    # ------------------------------------------------------------------ rows
    def _add_leaf(self, parent: QTreeWidgetItem, name: str, value: str, value_color: Optional[str] = None):
        item = QTreeWidgetItem([name, value, ""])
        item.setForeground(COL_PARAM, QColor(THEME['text_secondary']))
        item.setFont(COL_VALUE, QFont("Consolas", 10))
        item.setForeground(COL_VALUE, QColor(value_color or THEME['text_primary']))
        item.setData(COL_PARAM, Qt.ItemDataRole.UserRole, name)
        if value_color:
            item.setFont(COL_VALUE, QFont("Consolas", 10, QFont.Weight.Bold))
        item.setIcon(COL_LINK, _link_icon())
        item.setToolTip(COL_PARAM, name)
        item.setToolTip(COL_VALUE, value)
        item.setToolTip(COL_LINK, "Bind this parameter to a global variable")
        parent.addChild(item)
        return item

    def add_group(self, title: str, rows: List[tuple]) -> QTreeWidgetItem:
        """Public helper used by tests / callers to append a result group."""
        group = QTreeWidgetItem([title, "", ""])
        group.setExpanded(True)
        group.setFont(COL_PARAM, QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        group.setForeground(COL_PARAM, QColor(THEME['text_secondary']))
        self.tree.addTopLevelItem(group)
        for name, value in rows:
            self._add_leaf(group, name, str(value))
        return group

    def row_count(self) -> int:
        """Total number of leaf rows currently displayed."""
        count = 0
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            node = stack.pop()
            count += 1
            stack.extend(node.child(i) for i in range(node.childCount()))
        return count

    def binding_for(self, path: str) -> Optional[str]:
        return self._bindings.get(path)

    # ------------------------------------------------------------ interaction
    def _selected_path(self) -> Optional[str]:
        item = self.tree.currentItem()
        if not item:
            return None
        return item.text(COL_PARAM)

    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        if column == COL_LINK:
            self._bind_current()

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        act_bind = menu.addAction("Bind to Global Variable...")
        act_unbind = menu.addAction("Remove Binding")
        act_unbind.setEnabled(item.text(COL_PARAM) in self._bindings)
        menu.addSeparator()
        act_copy = menu.addAction("Copy Value")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen == act_bind:
            self._bind_current()
        elif chosen == act_unbind:
            self._unbind(item)
        elif chosen == act_copy:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(item.text(COL_VALUE))

    def _bind_current(self):
        item = self.tree.currentItem()
        if not item:
            return
        path = f"{self._module_name}.{item.text(COL_PARAM)}"
        names = list(self.global_variables.keys())
        if not names:
            QMessageBox.information(
                self, "Global Variables",
                "No global variables are defined.\nAdd one from Settings > Global Variables."
            )
            return
        name, ok = QInputDialog.getItem(
            self, "Bind Global Variable",
            f"Bind '{path}' to global variable:", names, 0, False
        )
        if not ok or not name:
            return
        self._bindings[path] = name
        item.setText(COL_LINK, name)
        item.setIcon(COL_LINK, _link_icon(THEME["vm_accent"]))
        self.variable_bound.emit(path, name)

    def _unbind(self, item: QTreeWidgetItem):
        path = f"{self._module_name}.{item.text(COL_PARAM)}"
        self._bindings.pop(path, None)
        item.setText(COL_LINK, "")
        item.setIcon(COL_LINK, _link_icon())
        self.variable_unbound.emit(path)
