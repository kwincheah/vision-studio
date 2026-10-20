"""Image display area — the reference's "图像显示区域" (manual region 6).

From the annotated main-interface figure in the Vision Master 4.3.0 manual
(`docs/references/external/ui_crops/main_interface_map.png`) and §5.2.3 of that
manual, the vendor's image area is a vertical stack:

    Image | Module Results            <- tabs
    ┌──────────────────────────────────────────────────────────┐
    │ <image source name>   [▣▣] [+] [−] [1:1] [⤢]              │  header + view toolbar
    │  ◀             <image>                            ▶      │  paged viewport
    │ <timestamp>     1280*1024 | X:0937 Y:0177 | R G B        │  status line
    ├──────────────────────────────────────────────────────────┤
    │ <source> (1/1)      [auto switch]      [Run all ▾]        │  image strip header
    │ [ thumbnail ] [ thumbnail ] ...                          │  image strip
    └──────────────────────────────────────────────────────────┘

Only the behaviours text-confirmed in §5.2.3 are implemented: module-image
display, single/double view switching, zoom in/out, 1:1, fit, the crosshair
auxiliary line toggle, and the image strip with its index counter.  The strip is
populated from the images a flow run produced, which is how the vendor's
"Module Images" collection behaves for a single-image solution.
"""
from typing import List, Optional
import numpy as np

from PyQt6.QtCore import Qt, QSize, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QFont, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QListWidget,
    QListWidgetItem, QSizePolicy, QFrame, QComboBox, QPushButton
)

from vm_clone.ui.styles import THEME
from vm_clone.ui.elided_label import ElidedLabel
from vm_clone.ui.image_canvas import ImageCanvasWidget
from vm_clone.ui.icons import get_action_icon
from vm_clone.ui import layout_metrics as LM


def _icon_button(glyph: str, tooltip: str, checkable: bool = False) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName("viewToolButton")
    btn.setIcon(_view_icon(glyph, 18))
    btn.setIconSize(QSize(18, 18))
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    btn.setAutoRaise(True)
    btn.setFixedSize(26, 24)
    return btn


def _view_icon(glyph: str, size: int = 18) -> QIcon:
    """Small original glyphs for the image-display toolbar."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if size != 16:
        p.scale(size / 16.0, size / 16.0)
    pen = QPen(QColor(THEME['text_secondary']), 1.3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    if glyph == "single":
        p.drawRoundedRect(QRectF(1.5, 3.5, 13.0, 9.0), 1.0, 1.0)
    elif glyph == "double":
        p.drawRoundedRect(QRectF(1.0, 3.5, 6.5, 9.0), 1.0, 1.0)
        p.drawRoundedRect(QRectF(8.5, 3.5, 6.5, 9.0), 1.0, 1.0)
    elif glyph == "zoom_in":
        p.drawEllipse(QRectF(1.5, 1.5, 9.0, 9.0))
        p.drawLine(QPointF(4.5, 6.0), QPointF(7.5, 6.0))
        p.drawLine(QPointF(6.0, 4.5), QPointF(6.0, 7.5))
        p.drawLine(QPointF(9.5, 9.5), QPointF(14.0, 14.0))
    elif glyph == "zoom_out":
        p.drawEllipse(QRectF(1.5, 1.5, 9.0, 9.0))
        p.drawLine(QPointF(4.5, 6.0), QPointF(7.5, 6.0))
        p.drawLine(QPointF(9.5, 9.5), QPointF(14.0, 14.0))
    elif glyph == "one_to_one":
        p.drawRoundedRect(QRectF(1.5, 2.5, 13.0, 11.0), 1.2, 1.2)
        p.setFont(QFont("Consolas", 6, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 16, 16), Qt.AlignmentFlag.AlignCenter, "1:1")
    elif glyph == "fit":
        p.drawRoundedRect(QRectF(5.0, 5.0, 6.0, 6.0), 1.0, 1.0)
        p.drawLine(QPointF(1.5, 1.5), QPointF(4.0, 1.5))
        p.drawLine(QPointF(1.5, 1.5), QPointF(1.5, 4.0))
        p.drawLine(QPointF(14.5, 14.5), QPointF(12.0, 14.5))
        p.drawLine(QPointF(14.5, 14.5), QPointF(14.5, 12.0))
    elif glyph == "expand":
        p.drawRoundedRect(QRectF(1.5, 1.5, 13.0, 13.0), 1.5, 1.5)
        p.drawLine(QPointF(5.5, 1.5), QPointF(5.5, 14.5))
        p.drawLine(QPointF(1.5, 8.0), QPointF(14.5, 8.0))
    elif glyph == "crosshair":
        p.drawEllipse(QRectF(3.0, 3.0, 10.0, 10.0))
        p.drawLine(QPointF(8.0, 1.0), QPointF(8.0, 5.0))
        p.drawLine(QPointF(8.0, 11.0), QPointF(8.0, 15.0))
        p.drawLine(QPointF(1.0, 8.0), QPointF(5.0, 8.0))
        p.drawLine(QPointF(11.0, 8.0), QPointF(15.0, 8.0))
    elif glyph == "prev":
        p.drawLine(QPointF(11.0, 2.5), QPointF(4.5, 8.0))
        p.drawLine(QPointF(4.5, 8.0), QPointF(11.0, 13.5))
    elif glyph == "next":
        p.drawLine(QPointF(5.0, 2.5), QPointF(11.5, 8.0))
        p.drawLine(QPointF(11.5, 8.0), QPointF(5.0, 13.5))
    elif glyph == "collapse_down":
        p.drawLine(QPointF(4.0, 6.0), QPointF(8.0, 10.0))
        p.drawLine(QPointF(8.0, 10.0), QPointF(12.0, 6.0))
    elif glyph == "add":
        p.drawLine(QPointF(8.0, 3.5), QPointF(8.0, 12.5))
        p.drawLine(QPointF(3.5, 8.0), QPointF(12.5, 8.0))
    elif glyph == "folder":
        path = QPainterPath()
        path.moveTo(2.0, 12.5)
        path.lineTo(2.0, 4.0)
        path.lineTo(6.0, 4.0)
        path.lineTo(7.5, 5.8)
        path.lineTo(13.0, 5.8)
        path.lineTo(13.0, 12.5)
        path.closeSubpath()
        p.drawPath(path)
    elif glyph == "clear":
        p.drawLine(QPointF(4.0, 4.0), QPointF(12.0, 12.0))
        p.drawLine(QPointF(12.0, 4.0), QPointF(4.0, 12.0))
    else:
        p.drawRoundedRect(QRectF(2.0, 2.0, 12.0, 12.0), 1.5, 1.5)

    p.end()
    return QIcon(pix)


class ToggleSwitch(QToolButton):
    """Industrial capsule toggle switch with pill track and sliding knob."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(32, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        rect = QRectF(0.0, 0.0, w, h)
        if self.isChecked():
            track_color = QColor(THEME['vm_accent'])
            knob_x = w - h + 2.0
        else:
            track_color = QColor(THEME['text_muted'])
            knob_x = 2.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(rect, h / 2.0, h / 2.0)

        knob_dia = h - 4.0
        p.setBrush(QColor(THEME['text_primary']) if self.isChecked() else QColor(THEME['text_secondary']))
        p.drawEllipse(QRectF(knob_x, 2.0, knob_dia, knob_dia))
        p.end()


class ImageDisplayArea(QWidget):
    """Image viewport with the reference's header, view toolbar and image strip."""

    view_mode_changed = pyqtSignal(bool)   # True = dual view
    image_selected = pyqtSignal(int)       # index into the image strip
    add_image_requested = pyqtSignal()     # request to add images to the flow
    add_folder_requested = pyqtSignal()    # request to add every image in a folder
    clear_images_requested = pyqtSignal()   # request to clear the flow images
    run_requested = pyqtSignal()           # request to execute the flow

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("imageDisplayArea")
        # A QWidget subclass does not paint its `#objectName` background from
        # the stylesheet unless it is told to; without this it falls back to
        # the global light `QWidget` background.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # The header row (source name + 8 view controls) must not pin the right
        # column wider than the measured floor; the name label elides instead.
        self.setMinimumWidth(LM.MIN_RIGHT_COL_W)
        self._dual = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- header: image source name + view toolbar ------------------------
        header = QWidget()
        header.setObjectName("imageHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(7, 3, 5, 3)
        hl.setSpacing(4)

        self.lbl_source = ElidedLabel("No image")
        self.lbl_source.setObjectName("imageSourceLabel")
        self.lbl_source.setMinimumWidth(60)
        self.lbl_source.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        self.lbl_source.setToolTip("Image currently shown (module output or flow output)")
        hl.addWidget(self.lbl_source, 1)

        self.btn_single = _icon_button("single", "Single image view")
        self.btn_double = _icon_button("double", "Dual image view (side by side)")
        self.btn_double.setCheckable(True)
        self.btn_double.toggled.connect(self._on_dual_toggled)
        hl.addWidget(self.btn_single)
        hl.addWidget(self.btn_double)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setObjectName("viewToolSeparator")
        hl.addWidget(sep)

        self.btn_zoom_in = _icon_button("zoom_in", "Zoom in")
        self.btn_zoom_out = _icon_button("zoom_out", "Zoom out")
        self.btn_zoom_1_1 = _icon_button("one_to_one", "1:1 pixel view")
        self.btn_fit = _icon_button("fit", "Fit image to window")
        self.btn_crosshair = _icon_button("crosshair", "Crosshair auxiliary line",
                                          checkable=True)
        self.btn_crosshair.setChecked(True)
        self.btn_expand = _icon_button("expand", "Expand the image display")
        for btn in (self.btn_zoom_in, self.btn_zoom_out, self.btn_zoom_1_1,
                    self.btn_fit, self.btn_crosshair, self.btn_expand):
            hl.addWidget(btn)
        root.addWidget(header)

        # ---- viewport (clean image viewport) --------------------------------
        viewport = QWidget()
        vl = QHBoxLayout(viewport)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        self.canvas = ImageCanvasWidget()
        vl.addWidget(self.canvas, 1)

        root.addWidget(viewport, 1)

        # ---- status bar: image identifier & pixel/resolution info -----------
        self.status_bar = QWidget()
        self.status_bar.setObjectName("imageStatusBar")
        self.status_bar.setFixedHeight(22)
        sb_layout = QHBoxLayout(self.status_bar)
        sb_layout.setContentsMargins(8, 0, 8, 0)
        sb_layout.setSpacing(8)

        self.lbl_status_id = QLabel("")
        self.lbl_status_id.setObjectName("imageStatusId")
        sb_layout.addWidget(self.lbl_status_id)

        sb_layout.addStretch(1)

        self.lbl_status_coords = ElidedLabel("0 * 0 | X,---- Y,---- | R:--- G:--- B:---")
        self.lbl_status_coords.setObjectName("imageStatusCoords")
        sb_layout.addWidget(self.lbl_status_coords)

        root.addWidget(self.status_bar)

        # ---- image strip header ----------------------------------------------
        strip_header = QWidget()
        strip_header.setObjectName("imageStripHeader")
        strip_header.setFixedHeight(36)
        sl = QHBoxLayout(strip_header)
        sl.setContentsMargins(10, 4, 8, 4)
        sl.setSpacing(8)

        self.lbl_strip = ElidedLabel("Image Source (0/0)")
        self.lbl_strip.setObjectName("imageStripLabel")
        self.lbl_strip.setMinimumWidth(72)
        sl.addWidget(self.lbl_strip, 1)

        self.btn_add_image = _icon_button("add", "Add / Load Image Files to Flow...")
        self.btn_add_image.setObjectName("stripAddImage")
        self.btn_add_image.setFixedSize(24, 24)
        self.btn_add_image.clicked.connect(self.add_image_requested)
        sl.addWidget(self.btn_add_image)

        self.btn_add_folder = _icon_button("folder", "Load all images from a folder...")
        self.btn_add_folder.setObjectName("stripAddFolder")
        self.btn_add_folder.setFixedSize(24, 24)
        self.btn_add_folder.clicked.connect(self.add_folder_requested)
        sl.addWidget(self.btn_add_folder)

        self.btn_clear_strip = _icon_button("clear", "Clear image flow list")
        self.btn_clear_strip.setObjectName("stripClearImages")
        self.btn_clear_strip.setFixedSize(24, 24)
        self.btn_clear_strip.clicked.connect(self.clear_images_requested)
        sl.addWidget(self.btn_clear_strip)

        self.lbl_auto = QLabel("Loop")
        self.lbl_auto.setObjectName("imageStripCaption")
        self.lbl_auto.setMinimumWidth(self.lbl_auto.fontMetrics().horizontalAdvance("Loop") + 8)
        sl.addWidget(self.lbl_auto)

        self.btn_auto = ToggleSwitch()
        self.btn_auto.setObjectName("sliderToggle")
        self.btn_auto.setToolTip(
            "Loop: keep running the image(s) over and over until Stop is pressed. "
            "With 'Run all' every image in the strip is processed in turn.")
        sl.addWidget(self.btn_auto)

        self.cbo_run_scope = QComboBox()
        self.cbo_run_scope.setObjectName("runScopeCombo")
        self.cbo_run_scope.addItems(["Run all", "Run selected", "Single step"])
        self.cbo_run_scope.setToolTip("Flow execution scope")
        self.cbo_run_scope.setFixedHeight(26)
        # Size to the longest entry plus the drop-down arrow, so the row can shrink
        # without clipping the label down to "Ru".
        metrics = self.cbo_run_scope.fontMetrics()
        widest = max(metrics.horizontalAdvance(t) for t in
                     ("Run all", "Run selected", "Single step"))
        self.cbo_run_scope.setMinimumWidth(widest + 34)
        self.lbl_run_scope = self.cbo_run_scope
        setattr(self.cbo_run_scope, "text", lambda: self.cbo_run_scope.currentText())
        sl.addWidget(self.cbo_run_scope)

        self.btn_play = QPushButton(" Run")
        self.btn_play.setObjectName("stripPlayButton")
        self.btn_play.setIcon(get_action_icon("run_once", 16))
        self.btn_play.setIconSize(QSize(16, 16))
        self.btn_play.setFixedHeight(26)
        # Let the button take the width its icon + label need.  At the reference
        # window size this row is tight enough that a squeezed button clipped its
        # label to "Ru".
        self.btn_play.setMinimumWidth(max(self.btn_play.sizeHint().width(), 78))
        self.btn_play.setToolTip("Execute flow according to selected scope (Run all / selected / step)")
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.clicked.connect(self.run_requested.emit)
        self.btn_run_scope = self.btn_play
        self.btn_run = self.btn_play
        sl.addWidget(self.btn_play)

        self.btn_collapse = _icon_button("collapse_down", "Toggle thumbnail strip")
        self.btn_collapse.setFixedSize(24, 24)
        self.btn_collapse.clicked.connect(self._toggle_strip_visibility)
        sl.addWidget(self.btn_collapse)

        root.addWidget(strip_header)

        # ---- thumbnail strip row flanked by navigation arrows ---------------
        self.strip_row = QWidget()
        self.strip_row.setObjectName("imageStripRow")
        srl = QHBoxLayout(self.strip_row)
        srl.setContentsMargins(4, 2, 4, 2)
        srl.setSpacing(4)

        self.btn_prev = _icon_button("prev", "Previous image")
        self.btn_prev.setObjectName("stripNavPrev")
        self.btn_prev.setFixedSize(18, 48)
        srl.addWidget(self.btn_prev)

        self.strip = QListWidget()
        self.strip.setObjectName("imageStrip")
        self.strip.setViewMode(QListWidget.ViewMode.IconMode)
        self.strip.setFlow(QListWidget.Flow.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setMovement(QListWidget.Movement.Static)
        self.strip.setIconSize(QSize(56, 40))
        self.strip.setGridSize(QSize(62, 46))
        self.strip.setFixedHeight(50)
        self.strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strip.currentRowChanged.connect(self._on_strip_row_changed)
        srl.addWidget(self.strip, 1)

        self.btn_next = _icon_button("next", "Next image")
        self.btn_next.setObjectName("stripNavNext")
        self.btn_next.setFixedSize(18, 48)
        srl.addWidget(self.btn_next)

        root.addWidget(self.strip_row)

        # ---- wiring ----------------------------------------------------------
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        self.btn_zoom_1_1.clicked.connect(self.canvas.set_zoom_actual)
        self.btn_fit.clicked.connect(self.canvas.fit_to_window)
        self.btn_crosshair.toggled.connect(self.canvas.set_show_crosshair)
        self.btn_expand.clicked.connect(self._toggle_expand)
        self.btn_prev.clicked.connect(lambda: self._step_image(-1))
        self.btn_next.clicked.connect(lambda: self._step_image(1))
        self.canvas.cursor_info_changed.connect(self._on_cursor_info_changed)

        self._frames: List[str] = []
        self._update_page_buttons()

    # ------------------------------------------------------------ public API
    def set_source_label(self, text: str, tooltip: str = ""):
        self.lbl_source.setText(text or "No image")
        self.lbl_source.setToolTip(tooltip or text or "No image")
        self.lbl_status_id.setText(text or "")

    def set_frames(self, labels: List[str], current: int = 0):
        """Populate the image strip (one entry per available image)."""
        self._frames = list(labels)
        self.strip.blockSignals(True)
        self.strip.clear()
        for label in labels:
            item = QListWidgetItem("")
            item.setToolTip(label)
            item.setSizeHint(QSize(62, 46))
            ph = QPixmap(56, 40)
            ph.fill(QColor(THEME['vm_viewport']))
            p = QPainter(ph)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(QPen(QColor(THEME['border_control']), 1))
            p.drawRect(0, 0, 55, 39)
            p.setPen(QPen(QColor(THEME['text_muted']), 1))
            p.drawRoundedRect(QRectF(16, 11, 24, 18), 2, 2)
            p.drawEllipse(QRectF(24, 16, 8, 8))
            p.end()
            item.setIcon(QIcon(ph))
            self.strip.addItem(item)

        total = max(1, len(labels))
        disp_name = labels[current] if labels else "Image Source"
        self.lbl_strip.setText(f"{disp_name} ({current + 1}/{total})")
        if labels:
            self.strip.setCurrentRow(min(current, len(labels) - 1))
        self.strip.blockSignals(False)
        self._update_page_buttons()

    def set_frame_thumbnail(self, index: int, img_or_pixmap):
        """Set a thumbnail image for a specific strip entry."""
        if not (0 <= index < self.strip.count()) or img_or_pixmap is None:
            return
        item = self.strip.item(index)
        if item is None:
            return
        pix = None
        if isinstance(img_or_pixmap, QPixmap):
            pix = img_or_pixmap
        elif hasattr(img_or_pixmap, "shape"):
            import cv2
            from PyQt6.QtGui import QImage
            arr = img_or_pixmap
            if len(arr.shape) == 2:
                h, w = arr.shape
                step = max(1, min(h // 80, w // 112))
                sub = np.ascontiguousarray(arr[::step, ::step])
                thumb_cv = cv2.resize(sub, (56, 40), interpolation=cv2.INTER_AREA)
                qimg = QImage(thumb_cv.data, 56, 40, 56, QImage.Format.Format_Grayscale8)
                pix = QPixmap.fromImage(qimg)
            else:
                h, w, ch = arr.shape
                step = max(1, min(h // 80, w // 112))
                sub = np.ascontiguousarray(arr[::step, ::step])
                thumb_cv = cv2.resize(sub, (56, 40), interpolation=cv2.INTER_AREA)
                if ch == 3:
                    qimg = QImage(thumb_cv.data, 56, 40, 56 * 3, QImage.Format.Format_BGR888)
                else:
                    rgb = cv2.cvtColor(thumb_cv, cv2.COLOR_BGRA2RGBA)
                    qimg = QImage(rgb.data, 56, 40, 56 * 4, QImage.Format.Format_RGBA8888)
                pix = QPixmap.fromImage(qimg)

        if pix is not None and not pix.isNull():
            if pix.width() != 56 or pix.height() != 40:
                thumb = pix.scaled(56, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
            else:
                thumb = pix
            card = QPixmap(56, 40)
            card.fill(QColor(THEME['vm_viewport']))
            p = QPainter(card)
            ox = (56 - thumb.width()) // 2
            oy = (40 - thumb.height()) // 2
            p.drawPixmap(ox, oy, thumb)
            p.end()
            item.setIcon(QIcon(card))

    def mark_current_frame(self, pixmap: Optional[QPixmap]):
        """Give the active strip entry a thumbnail of the rendered image."""
        if pixmap is None or self.strip.count() == 0:
            return
        row = max(0, self.strip.currentRow())
        self.set_frame_thumbnail(row, pixmap)

    # ---------------------------------------------------------- interactions
    def _toggle_strip_visibility(self):
        visible = not self.strip_row.isVisible()
        self.strip_row.setVisible(visible)

    def _on_cursor_info_changed(self, info: str):
        if info:
            self.lbl_status_coords.setText(info)

    # ---------------------------------------------------------- interactions
    def _on_dual_toggled(self, checked: bool):
        self._dual = checked
        self.btn_single.setEnabled(not checked)
        self.view_mode_changed.emit(checked)

    def _zoom_in(self):
        self.canvas.zoom_at_center(1.2)

    def _zoom_out(self):
        self.canvas.zoom_at_center(1 / 1.2)

    def _toggle_expand(self):
        """Expand/collapse the image share of its parent splitter."""
        splitter = self.parentWidget()
        while splitter is not None and not hasattr(splitter, "setSizes"):
            splitter = splitter.parentWidget()
        if splitter is None:
            return

        sizes = splitter.sizes()
        if len(sizes) < 2:
            return
        total = sum(sizes) or 1
        expanded = sizes[0] >= int(total * 0.85)
        if expanded:
            splitter.setSizes([int(total * 0.6), total - int(total * 0.6)])
        else:
            splitter.setSizes([int(total * 0.9), total - int(total * 0.9)])

    def set_running(self, running: bool, stopping: bool = False):
        """Turn the Run button into a Stop button while the strip is processing.

        ``stopping`` shows a disabled 'Stopping...' until the cycle in flight has ended, so
        the button only returns to 'Run' once everything has actually finished.
        """
        btn = self.btn_play
        if running:
            btn.setText(" Stopping..." if stopping else " Stop")
            btn.setIcon(get_action_icon("stop", 16, QColor("#ffffff")))
            btn.setToolTip("Stop processing")
        else:
            btn.setText(" Run")
            btn.setIcon(get_action_icon("run_once", 16))
            btn.setToolTip("Execute flow according to selected scope (Run all / selected / step)")
        btn.setEnabled(not stopping)
        btn.setProperty("running", bool(running))
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def select_frame(self, row: int):
        """Highlight a strip entry without announcing it (no re-run is triggered)."""
        if not (0 <= row < self.strip.count()):
            return
        self.strip.blockSignals(True)
        self.strip.setCurrentRow(row)
        self.strip.scrollToItem(self.strip.item(row))
        self.strip.blockSignals(False)
        label = self._frames[row] if row < len(self._frames) else ""
        self.lbl_strip.setText(f"{label} ({row + 1}/{max(1, self.strip.count())})")
        self._update_page_buttons()

    def _step_image(self, delta: int):
        if self.strip.count() == 0:
            return
        row = (self.strip.currentRow() + delta) % self.strip.count()
        self.strip.setCurrentRow(row)

    def _on_strip_row_changed(self, row: int):
        if row < 0:
            return
        total = max(1, self.strip.count())
        label = self._frames[row] if row < len(self._frames) else ""
        self.lbl_strip.setText(f"{label} ({row + 1}/{total})")
        self._update_page_buttons()
        self.image_selected.emit(row)

    def _update_page_buttons(self):
        many = self.strip.count() > 1
        self.btn_prev.setEnabled(many)
        self.btn_next.setEnabled(many)
