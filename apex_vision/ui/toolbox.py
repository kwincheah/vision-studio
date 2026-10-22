"""reference- Tool Box: left category rail + icon-grid flyout.

Structure verified against the bundled the reference product manual:

* p.72 "Tool Box"  - a narrow vertical rail down the left edge of the flow
  workspace showing one glyph per module category.
* p.74 "Group Module1" - clicking a rail glyph opens a flyout panel titled with
  the category name ("I  Locating") holding a 3-column grid of tool cells where
  each cell is an icon with a wrapped label underneath.

Both the rail and the flyout are real Qt widgets (not painted mock-ups) so the
category selection, search filtering, selection state and drag-and-drop onto the
flow canvas all behave as genuine interactions.
"""
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QRectF, QMimeData, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QDrag, QFont, QIcon
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLineEdit,
    QLabel, QToolButton, QSizePolicy, QAbstractItemView
)

from apex_vision.core.registry import list_categories, get_tool_class
from apex_vision.ui.styles import THEME
from apex_vision.ui.icons import get_tool_icon, get_action_icon
from apex_vision.ui import layout_metrics as LM

# reference orange accent applied to toolbox glyphs (manual p.74).
VM_ACCENT = QColor(THEME["vm_accent"])


CATEGORY_ORDER = [
    "Acquisition",
    "Location",
    "Measurement",
    "Image Generation",
    "Image Processing",
    "Color Processing",
    "Recognition",
    "Defect Detection",
    "Calibration",
    "Communication",
    "Logic Tools",
]

# Rail shortcuts per category (manual p.70/p.72 icon inventory).
CATEGORY_GLYPH = {
    "Acquisition": "cam",
    "Location": "loc",
    "Measurement": "cal",
    "Image Generation": "gen",
    "Image Processing": "dsp",
    "Color Processing": "col",
    "Recognition": "ocr",
    "Defect Detection": "def",
    "Calibration": "clb",
    "Communication": "com",
    "Logic Tools": "lif",
}


# =============================================================================
# Rail glyphs - original vector drawings in the reference icon language
# =============================================================================
def _rail_painter(size: int, color=None):
    """Painter for the category rail's glyphs.

    The rail is dark chrome, so the default ink is the chrome tone: the previous
    body-ink default rendered dark-on-dark at under 2:1.  `color` overrides it for
    the selected item, whose fill is light.
    """
    from PyQt6.QtGui import QPixmap
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ink = QColor(color) if color is not None else QColor(THEME["text_on_chrome"])
    pen = QPen(ink, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    return pix, p


def get_rail_icon(glyph: str, size: int = 22, color: Optional[QColor] = None) -> QIcon:
    """Rail/category glyph matching the reference icon strip (manual p.72)."""
    pix, p = _rail_painter(size)
    if color is not None:
        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
    s = float(size)
    if glyph == "cam":
        p.drawRoundedRect(QRectF(s * 0.08, s * 0.26, s * 0.84, s * 0.58), 2.5, 2.5)
        p.drawEllipse(QRectF(s * 0.33, s * 0.40, s * 0.34, s * 0.32))
        p.drawLine(int(s * 0.28), int(s * 0.26), int(s * 0.38), int(s * 0.14))
        p.drawLine(int(s * 0.38), int(s * 0.14), int(s * 0.58), int(s * 0.14))
    elif glyph == "loc":
        p.drawEllipse(QRectF(s * 0.2, s * 0.2, s * 0.6, s * 0.6))
        p.drawLine(int(s * 0.5), int(s * 0.05), int(s * 0.5), int(s * 0.22))
        p.drawLine(int(s * 0.5), int(s * 0.78), int(s * 0.5), int(s * 0.95))
        p.drawLine(int(s * 0.05), int(s * 0.5), int(s * 0.22), int(s * 0.5))
        p.drawLine(int(s * 0.78), int(s * 0.5), int(s * 0.95), int(s * 0.5))
    elif glyph == "cal":
        p.drawLine(int(s * 0.18), int(s * 0.22), int(s * 0.18), int(s * 0.78))
        p.drawLine(int(s * 0.5), int(s * 0.22), int(s * 0.5), int(s * 0.78))
        p.drawLine(int(s * 0.82), int(s * 0.22), int(s * 0.82), int(s * 0.78))
        p.drawLine(int(s * 0.18), int(s * 0.5), int(s * 0.82), int(s * 0.5))
        p.drawLine(int(s * 0.18), int(s * 0.5), int(s * 0.34), int(s * 0.34))
        p.drawLine(int(s * 0.82), int(s * 0.5), int(s * 0.66), int(s * 0.34))
    elif glyph == "gen":
        p.drawRoundedRect(QRectF(s * 0.14, s * 0.24, s * 0.52, s * 0.42), 2, 2)
        p.drawLine(int(s * 0.78), int(s * 0.14), int(s * 0.78), int(s * 0.86))
        p.drawLine(int(s * 0.66), int(s * 0.26), int(s * 0.9), int(s * 0.26))
        p.drawLine(int(s * 0.66), int(s * 0.74), int(s * 0.9), int(s * 0.74))
    elif glyph == "dsp":
        p.drawRoundedRect(QRectF(s * 0.12, s * 0.16, s * 0.76, s * 0.68), 2, 2)
        p.drawLine(int(s * 0.34), int(s * 0.16), int(s * 0.34), int(s * 0.84))
        p.drawLine(int(s * 0.58), int(s * 0.16), int(s * 0.58), int(s * 0.84))
        p.drawLine(int(s * 0.12), int(s * 0.5), int(s * 0.88), int(s * 0.5))
    elif glyph == "col":
        p.drawEllipse(QRectF(s * 0.16, s * 0.34, s * 0.42, s * 0.42))
        p.drawEllipse(QRectF(s * 0.42, s * 0.34, s * 0.42, s * 0.42))
        p.drawEllipse(QRectF(s * 0.29, s * 0.14, s * 0.42, s * 0.42))
    elif glyph == "ocr":
        p.drawRoundedRect(QRectF(s * 0.12, s * 0.12, s * 0.76, s * 0.76), 2, 2)
        p.drawRect(QRectF(s * 0.24, s * 0.24, s * 0.2, s * 0.2))
        p.drawRect(QRectF(s * 0.56, s * 0.24, s * 0.2, s * 0.2))
        p.drawRect(QRectF(s * 0.24, s * 0.56, s * 0.2, s * 0.2))
        p.drawLine(int(s * 0.56), int(s * 0.76), int(s * 0.76), int(s * 0.56))
    elif glyph == "def":
        path_pts = [
            (s * 0.5, s * 0.08), (s * 0.9, s * 0.26), (s * 0.9, s * 0.56),
            (s * 0.5, s * 0.94), (s * 0.1, s * 0.56), (s * 0.1, s * 0.26),
        ]
        from PyQt6.QtGui import QPolygonF
        from PyQt6.QtCore import QPointF
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in path_pts]))
        p.drawLine(int(s * 0.5), int(s * 0.3), int(s * 0.5), int(s * 0.58))
        p.drawPoint(int(s * 0.5), int(s * 0.7))
    elif glyph == "clb":
        p.drawRoundedRect(QRectF(s * 0.1, s * 0.1, s * 0.8, s * 0.8), 2, 2)
        for fx in (0.32, 0.5, 0.68):
            for fy in (0.32, 0.5, 0.68):
                p.drawPoint(int(s * fx), int(s * fy))
    elif glyph == "com":
        p.drawRoundedRect(QRectF(s * 0.24, s * 0.2, s * 0.52, s * 0.4), 2, 2)
        p.drawRoundedRect(QRectF(s * 0.1, s * 0.62, s * 0.32, s * 0.26), 2, 2)
        p.drawRoundedRect(QRectF(s * 0.58, s * 0.62, s * 0.32, s * 0.26), 2, 2)
        p.drawLine(int(s * 0.5), int(s * 0.6), int(s * 0.5), int(s * 0.75))
    elif glyph == "lif":
        p.drawLine(int(s * 0.24), int(s * 0.12), int(s * 0.24), int(s * 0.88))
        p.drawLine(int(s * 0.5), int(s * 0.12), int(s * 0.5), int(s * 0.88))
        p.drawLine(int(s * 0.24), int(s * 0.5), int(s * 0.5), int(s * 0.5))
        p.drawLine(int(s * 0.5), int(s * 0.28), int(s * 0.82), int(s * 0.28))
        p.drawLine(int(s * 0.5), int(s * 0.72), int(s * 0.82), int(s * 0.72))
    else:
        p.drawRoundedRect(QRectF(s * 0.2, s * 0.2, s * 0.6, s * 0.6), 2, 2)
    p.end()
    return QIcon(pix)


def get_brand_mark(size: int = 22) -> QIcon:
    """Original product brand mark for Apex Vision Studio."""
    pix, p = _rail_painter(size)
    s = float(size)
    accent = QColor(THEME["vm_accent"])
    accent_hover = QColor(THEME["vm_accent_hover"])
    from PyQt6.QtGui import QPolygonF
    from PyQt6.QtCore import QPointF
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(accent)
    # Dynamic Apex "A" prism polygon
    p.drawPolygon(QPolygonF([
        QPointF(s * 0.50, s * 0.12),
        QPointF(s * 0.86, s * 0.86),
        QPointF(s * 0.64, s * 0.86),
        QPointF(s * 0.50, s * 0.54),
        QPointF(s * 0.36, s * 0.86),
        QPointF(s * 0.14, s * 0.86),
    ]))
    p.setBrush(accent_hover)
    p.drawPolygon(QPolygonF([
        QPointF(s * 0.50, s * 0.12),
        QPointF(s * 0.64, s * 0.86),
        QPointF(s * 0.50, s * 0.54),
    ]))
    p.end()
    return QIcon(pix)


# =============================================================================
# Tool grid cell  (icon above wrapped label - manual p.74)
# =============================================================================
class _ToolCell(QListWidgetItem):
    pass


class ToolGridWidget(QListWidget):
    """Icon+label grid with drag-out support onto the flow canvas.

    Cell metrics follow the reference flyout (manual p.74): a large glyph with a
    two-line wrapped label underneath, packed into a dense multi-column grid.
    """

    ICON_PX = 30
    CELL_W = 76
    #: 92 rather than 84.  The longest tool name, "Lens Distortion Calibration", wraps to
    #: three lines at the 11 px label size and needs 85 px of content height, so at 84 the
    #: final line touched the cell's bottom edge.  Measured by
    #: `tests/test_ui_alignment.py`, which sweeps every category rather than the handful a
    #: spot check would pick.
    CELL_H = 92
    #: The label's own size, set explicitly rather than inherited.  The cells were
    #: picking up the 13 px label size from the stylesheet cascade, which made
    #: 'Linear Edge Defect' wrap onto three lines and run past the bottom of the 84 px
    #: cell (an earlier audit script measured 91 px needed).  At 11 px a long
    #: name wraps to two lines and needs 70 px.  Setting
    #: it here also stops the printed text `image_canvas` uses from drifting from it.
    LABEL_PX = 11

    tool_activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolGrid")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setMovement(QListWidget.Movement.Static)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(self.ICON_PX, self.ICON_PX))
        self.setGridSize(QSize(self.CELL_W, self.CELL_H))
        self.setSpacing(0)
        self.setWordWrap(True)
        # The cell label size, set on the view.  Without this the view resolves its font
        # through the stylesheet cascade to the 13 px label size, and a long tool name
        # ("Linear Edge Defect") wraps onto three lines that run past the bottom of the
        # cell.  At 11 px the longest name needs 71 px of an 84 px cell.
        cell_font = QFont(THEME.get("font_family", "Segoe UI"))
        cell_font.setPixelSize(self.LABEL_PX)
        self.setFont(cell_font)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.itemDoubleClicked.connect(self._on_double_click)

    def column_count(self) -> int:
        """How many cells currently fit per row (used by layout tests)."""
        width = self.viewport().width()
        if self.CELL_W <= 0:
            return 0
        return max(1, width // self.CELL_W)

    def _on_double_click(self, item: QListWidgetItem):
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self.tool_activated.emit(name)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        name = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not name:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(name)
        drag.setMimeData(mime)
        drag.setPixmap(item.icon().pixmap(self.ICON_PX, self.ICON_PX))
        drag.exec(Qt.DropAction.CopyAction)


# =============================================================================
# Flyout panel
# =============================================================================
class ToolFlyoutPanel(QWidget):
    """Category popup holding the searchable tool grid (manual p.74)."""

    tool_activated = pyqtSignal(str)
    hidden_by_user = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("vmToolFlyout")
        # A QWidget subclass does not paint its `#objectName` background from
        # the stylesheet unless it is told to; without this it falls back to
        # the global light `QWidget` background.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._all_categories: Dict[str, List[str]] = {}
        self._current_category: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.lbl_header = QLabel("Tool Box")
        self.lbl_header.setObjectName("flyoutCategoryHeader")
        root.addWidget(self.lbl_header)

        self.txt_search = QLineEdit()
        self.txt_search.setObjectName("toolSearch")
        self.txt_search.setPlaceholderText("Search modules...")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.addAction(get_action_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.txt_search.textChanged.connect(self._on_search)
        search_wrap = QWidget()
        sw = QVBoxLayout(search_wrap)
        sw.setContentsMargins(8, 7, 8, 7)
        sw.setSpacing(0)
        sw.addWidget(self.txt_search)
        root.addWidget(search_wrap)

        self.lbl_hint = QLabel("Double-click or drag a module onto the flow.")
        self.lbl_hint.setObjectName("flyoutHint")
        self.lbl_hint.setWordWrap(True)
        root.addWidget(self.lbl_hint)

        self.grid = ToolGridWidget()
        self.grid.tool_activated.connect(self.tool_activated)
        root.addWidget(self.grid, 1)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    @property
    def preferred_flyout_width(self) -> int:
        return self.FLYOUT_W

    def keyPressEvent(self, event):
        """Esc closes the flyout, matching the reference toolbox behaviour."""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.hidden_by_user.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- data ---------------------------------------------------------------
    def set_categories(self, categories: Dict[str, List[str]]):
        self._all_categories = categories

    def show_category(self, category: str):
        self._current_category = category
        self.lbl_header.setText(category)
        self.txt_search.blockSignals(True)
        self.txt_search.clear()
        self.txt_search.blockSignals(False)
        self._populate(category, "")

    def _populate(self, category: Optional[str], search: str):
        self.grid.clear()
        flt = search.strip().lower()

        if flt:
            matched_categories = list(self._all_categories.keys())
        else:
            matched_categories = [category] if category else []

        for cat in matched_categories:
            for tool in self._all_categories.get(cat, []):
                if flt and flt not in tool.lower() and flt not in cat.lower():
                    continue
                self._add_cell(tool, cat, show_category=bool(flt))

    def _add_cell(self, tool: str, category: str, show_category: bool = False):
        label = tool if not show_category else f"{tool}"
        item = _ToolCell(label)
        item.setData(Qt.ItemDataRole.UserRole, tool)
        item.setIcon(get_tool_icon(tool, ToolGridWidget.ICON_PX, VM_ACCENT))
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        item.setSizeHint(QSize(ToolGridWidget.CELL_W, ToolGridWidget.CELL_H))
        cls = get_tool_class(tool)
        desc = getattr(cls, "description", "") if cls else ""
        item.setToolTip(f"<b>{tool}</b><br><span>{category}</span><br>{desc}")
        self.grid.addItem(item)

    def _on_search(self, text: str):
        self._populate(self._current_category, text)

    # -- compatibility ------------------------------------------------------
    def category_tree(self):
        """Expose category -> tools mapping (used by tests / API consumers)."""
        return self._all_categories


# =============================================================================
# Horizontal category rail
# =============================================================================
class ToolCategoryRail(QWidget):
    """Vertical glyph rail; emits the selected category (manual p.72)."""

    category_selected = pyqtSignal(str)
    search_requested = pyqtSignal()

    #: Measured from the vendor figure: the module box glyph rail is ~22 px at a
    #: 1388 px window (0.0159); widened to a usable click target.  Sourced from
    #: `layout_metrics` so the measurement lives in exactly one place.
    RAIL_W = LM.RAIL_W

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("vmCategoryRail")
        self.setFixedWidth(self.RAIL_W)
        # A QWidget subclass does not paint its `#objectName` background from
        # the stylesheet unless it is told to.  Without this the rail fell back to
        # the global light `QWidget` background, which left the light rail glyphs
        # invisible on a light strip.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(0)

        self._buttons: Dict[str, QToolButton] = {}

        self._layout.addWidget(self._make_button("__brand__", "Brand", get_brand_mark(24)))
        self._layout.addSpacing(6)

        self._stretch_item = self._layout.addStretch(1)

        self.btn_search = self._make_button(
            "__search__", "Search all modules", get_action_icon("search", 24)
        )
        self.btn_search.clicked.connect(self.search_requested)
        self._layout.addWidget(self.btn_search)

        self.refresh_categories()

    def refresh_categories(self):
        """Re-synchronizes rail buttons with active tool categories in registry."""
        registered_cats = list_categories()
        all_cats = list(CATEGORY_ORDER)
        for cat in registered_cats:
            if cat not in all_cats:
                all_cats.append(cat)
        active_cats = [c for c in all_cats if c in registered_cats or c in CATEGORY_ORDER]

        # 1. Remove stale buttons (e.g. unloaded custom plugin categories)
        for cat in list(self._buttons.keys()):
            if cat not in active_cats:
                btn = self._buttons.pop(cat)
                self._layout.removeWidget(btn)
                btn.setParent(None)
                btn.deleteLater()

        # 2. Add newly registered category buttons before stretch item
        stretch_idx = self._layout.indexOf(self._stretch_item)
        if stretch_idx < 0:
            stretch_idx = self._layout.count() - 1

        for cat in active_cats:
            if cat not in self._buttons:
                glyph = CATEGORY_GLYPH.get(cat, "gen")
                btn = self._make_button(cat, cat, get_rail_icon(glyph, 24), checkable=True)
                btn.clicked.connect(lambda _=False, c=cat: self._on_category_clicked(c))
                self._buttons[cat] = btn
                self._layout.insertWidget(stretch_idx, btn)
                stretch_idx += 1

    def _make_button(self, key: str, tip: str, icon: QIcon, checkable: bool = False) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("railCategory")
        btn.setIcon(icon)
        btn.setIconSize(QSize(24, 24))
        btn.setFixedSize(self.RAIL_W, 40)
        btn.setCheckable(checkable)
        btn.setAutoRaise(True)
        btn.setToolTip(tip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _on_category_clicked(self, category: str):
        btn = self._buttons.get(category)
        for other in self._buttons.values():
            other.setChecked(False)
        if btn is not None:
            btn.setChecked(True)
        self.category_selected.emit(category)

    def select_category(self, category: str):
        """Check the chosen glyph and re-ink it.

        The selected glyph sits on the flyout's light fill, so a light icon would be
        invisible; the ink is swapped to the dark body colour for the selected item
        and back to the chrome ink for the rest.  This is the icon-side half of the
        `QToolButton#railCategory:checked` rule.
        """
        for name, btn in self._buttons.items():
            selected = name == category
            btn.setChecked(selected)
            glyph = CATEGORY_GLYPH.get(name, "gen")
            ink = QColor(THEME["text_primary"] if selected
                         else THEME["text_on_chrome"])
            btn.setIcon(get_rail_icon(glyph, 24, ink))

    def category_names(self) -> List[str]:
        return list(self._buttons.keys())


class ToolBoxPanel(QWidget):
    """Composite: rail on the left, flyout grid to its right (manual p.72/74)."""

    tool_activated = pyqtSignal(str)
    #: Emitted when the flyout opens or closes, so the window can re-apply the
    #: measured column split.
    rail_width_changed = pyqtSignal()

    #: Flyout width.  The reference module box is a narrow rail plus a flyout that
    #: opens over the canvas; the measured module-box region is only ~4 % of the
    #: window width, so the flyout is kept tight (see the storyboard's deviations).
    FLYOUT_W = LM.FLYOUT_W
    RAIL_W = ToolCategoryRail.RAIL_W

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("vmToolBox")
        self._last_toggled: Optional[str] = None

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.rail = ToolCategoryRail()
        row.addWidget(self.rail)

        self.flyout = ToolFlyoutPanel()
        # The flyout must be able to give width back to the flow canvas on small
        # displays: a hard fixed width made the whole Tool Box dock refuse to
        # shrink, starving the central workspace.
        self.flyout.setMinimumWidth(120)
        self.flyout.setMaximumWidth(self.FLYOUT_W)
        self.flyout.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.flyout.tool_activated.connect(self.tool_activated)
        self.flyout.hidden_by_user.connect(self._on_flyout_hidden)
        row.addWidget(self.flyout, 1)

        self.rail.category_selected.connect(self._on_category)
        self.rail.search_requested.connect(self._focus_search)

        self.flyout.set_categories(list_categories())
        first = next((c for c in CATEGORY_ORDER if c in list_categories()), None)
        if first:
            self.rail.select_category(first)
            self.flyout.show_category(first)
        # The measured reference rail is a bare glyph strip with no persistent
        # flyout, so the resting layout starts collapsed and the rail opens it.
        self.flyout.setVisible(LM.FLYOUT_OPEN_BY_DEFAULT)
        self._sync_rail_width()

    def _on_category(self, category: str):
        """Clicking the active rail glyph collapses the flyout again."""
        if self.flyout.isVisible() and self.flyout.lbl_header.text() == category \
                and self._last_toggled == category:
            self.flyout.hide()
            self._last_toggled = None
            self._sync_rail_width()
            return
        self.flyout.show_category(category)
        self.flyout.show()
        self._last_toggled = category
        self._sync_rail_width()

    def _on_flyout_hidden(self):
        self._last_toggled = None
        self._sync_rail_width()

    def _sync_rail_width(self):
        """Let the dock shrink back to the measured rail when the flyout closes.

        The width change is published so the window can re-apply the measured
        column split: a dock whose minimum width shrinks keeps its old width until
        something asks for it back, which would otherwise starve the canvas.
        """
        if self.flyout.isVisible():
            # The dock is pinned to the rail at rest, so its minimum has to be
            # raised before the flyout can be shown; the window widens the dock to
            # match (see `_apply_reference_proportions`).
            self.setMinimumWidth(self.FLYOUT_W)
            self.setMaximumWidth(16777215)
        else:
            self.setMinimumWidth(self.RAIL_W)
            self.setMaximumWidth(self.RAIL_W)
        self.rail_width_changed.emit()

    def _focus_search(self):
        self.flyout.show()
        self.flyout.txt_search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.flyout.txt_search.selectAll()
        self._sync_rail_width()

    def refresh_tools(self):
        """Refreshes the flyout and rail with newly registered plugin categories and tools."""
        self.rail.refresh_categories()
        cats = list_categories()
        self.flyout.set_categories(cats)
        if self.flyout._current_category and self.flyout._current_category in cats:
            self.flyout.show_category(self.flyout._current_category)
        else:
            first = next((c for c in CATEGORY_ORDER if c in cats), next(iter(cats), None))
            if first:
                self.rail.select_category(first)
                self.flyout.show_category(first)
            else:
                self.flyout.grid.clear()
                self.flyout.lbl_header.setText("Tool Box")

    # -- compatibility ------------------------------------------------------
    @property
    def is_collapsed(self) -> bool:
        return not self.flyout.isVisible()

    def set_flyout_visible(self, visible: bool):
        self.flyout.setVisible(visible)
