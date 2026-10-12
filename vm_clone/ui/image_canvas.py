"""
Industrial Vision Canvas.
Clear, high-contrast engineering viewport:
- Smooth subpixel pan and zoom
- Non-distracting coordinate crosshairs and measurement tags
- Clean ROI manipulation
- Real-time pixel inspector (X, Y, Gray/RGB)
- Toggleable intensity histogram HUD
"""
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QImage, QPixmap, QColor, QPen, QFont, QWheelEvent, QMouseEvent, QBrush
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, pyqtSignal
import numpy as np
import cv2
import os
from typing import List, Dict, Any, Optional


class ImageCanvasWidget(QWidget):
    roi_changed = pyqtSignal(list)  # [x, y, w, h]
    cursor_info_changed = pyqtSignal(str)  # "1280 * 1024 | X,0592 Y,1000 | R:000 G:000 B:000"
    image_file_dropped = pyqtSignal(str)  # absolute file path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)

        self._image_pixmap: Optional[QPixmap] = None
        self._raw_cv_image: Optional[np.ndarray] = None
        self._overlays: List[Dict[str, Any]] = []

        self._empty_message: str = "No Image Loaded"
        self._empty_subtext: str = "Drop image file here, or click 'Load Image' (Ctrl+I)"
        self._is_error_state: bool = False

        self._scale: float = 1.0
        self._offset: QPoint = QPoint(0, 0)
        self._fit_mode: bool = True
        self._dragging_pan: bool = False
        self._last_mouse_pos: QPoint = QPoint()

        self._draw_roi_mode: bool = False
        self._drawing_roi: bool = False
        self._roi_start: Optional[QPoint] = None
        self._roi_curr: Optional[QPoint] = None
        self._active_roi: Optional[List[int]] = None

        # Interactive ROI handle resizing & translation
        self._hovered_handle: Optional[str] = None
        self._resizing_roi: bool = False
        self._active_handle: Optional[str] = None
        self._drag_start_roi: Optional[List[int]] = None
        self._drag_start_mouse: QPoint = QPoint()

        # Overlay layer filtering
        self._show_overlays: bool = True
        self._show_rois: bool = True
        self._show_measurements: bool = True
        self._show_datums: bool = True
        self._show_crosshair: bool = True

        self._cursor_img_pos: Optional[QPoint] = None
        self._cursor_val_str: str = ""
        self._show_hist: bool = False

    def set_draw_roi_mode(self, enabled: bool):
        self._draw_roi_mode = enabled
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)

    def set_show_histogram(self, show: bool):
        self._show_hist = show
        self.update()

    def set_active_roi(self, roi: Optional[List[int]]):
        self._active_roi = list(roi) if roi else None
        self.update()

    def get_active_roi(self) -> Optional[List[int]]:
        return self._active_roi

    def set_overlay_visibility(self, all_overlays: bool = True, rois: bool = True, measurements: bool = True, datums: bool = True):
        self._show_overlays = all_overlays
        self._show_rois = rois
        self._show_measurements = measurements
        self._show_datums = datums
        self.update()

    def set_show_overlays(self, show: bool):
        """Master overlay switch (Operation Interface "All Overlays")."""
        self._show_overlays = show
        self.update()

    def set_show_crosshair(self, show: bool):
        self._show_crosshair = show
        self.update()

    def set_empty_state(self, message: str, is_error: bool = False, subtext: str = ""):
        """Configures the message and error severity when no image is displayed."""
        self._empty_message = message
        self._is_error_state = is_error
        self._empty_subtext = subtext or ("Check image file path or acquisition settings" if is_error else "Drop image file here, or click 'Load Image' (Ctrl+I)")
        self.update()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                ext = os.path.splitext(url.toLocalFile())[1].lower()
                if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                fpath = url.toLocalFile()
                ext = os.path.splitext(fpath)[1].lower()
                if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp") and os.path.exists(fpath):
                    self.image_file_dropped.emit(fpath)
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

    def _get_roi_screen_rect(self) -> Optional[QRectF]:
        if not self._active_roi:
            return None
        rx, ry, rw, rh = self._active_roi
        sx = self._offset.x() + rx * self._scale
        sy = self._offset.y() + ry * self._scale
        sw = rw * self._scale
        sh = rh * self._scale
        return QRectF(sx, sy, sw, sh)

    def _get_handles(self) -> Dict[str, QRectF]:
        srect = self._get_roi_screen_rect()
        if not srect:
            return {}
        sx, sy, sw, sh = srect.x(), srect.y(), srect.width(), srect.height()
        sz = 7.0
        hsz = sz / 2.0
        return {
            "nw": QRectF(sx - hsz, sy - hsz, sz, sz),
            "n": QRectF(sx + sw / 2.0 - hsz, sy - hsz, sz, sz),
            "ne": QRectF(sx + sw - hsz, sy - hsz, sz, sz),
            "e": QRectF(sx + sw - hsz, sy + sh / 2.0 - hsz, sz, sz),
            "se": QRectF(sx + sw - hsz, sy + sh - hsz, sz, sz),
            "s": QRectF(sx + sw / 2.0 - hsz, sy + sh - hsz, sz, sz),
            "sw": QRectF(sx - hsz, sy + sh - hsz, sz, sz),
            "w": QRectF(sx - hsz, sy + sh / 2.0 - hsz, sz, sz),
        }

    def _get_handle_at(self, pos: QPoint) -> Optional[str]:
        handles = self._get_handles()
        p = QPointF(float(pos.x()), float(pos.y()))
        for name, rect in handles.items():
            if rect.adjusted(-3, -3, 3, 3).contains(p):
                return name
        srect = self._get_roi_screen_rect()
        if srect and srect.contains(p):
            return "body"
        return None

    def _cursor_for_handle(self, handle: Optional[str]) -> Qt.CursorShape:
        if handle in ("nw", "se"):
            return Qt.CursorShape.SizeFDiagCursor
        elif handle in ("ne", "sw"):
            return Qt.CursorShape.SizeBDiagCursor
        elif handle in ("n", "s"):
            return Qt.CursorShape.SizeVerCursor
        elif handle in ("e", "w"):
            return Qt.CursorShape.SizeHorCursor
        elif handle == "body":
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.ArrowCursor

    def set_cv_image(self, img: Optional[np.ndarray], overlays: Optional[List[Dict[str, Any]]] = None):
        if img is None:
            self._image_pixmap = None
            self._raw_cv_image = None
            self._overlays = []
            self.cursor_info_changed.emit("")
            self.update()
            return

        self._raw_cv_image = img
        self._overlays = overlays or []

        if len(img.shape) == 2:
            h, w = img.shape
            bytes_per_line = w
            qimg = QImage(img.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)
        else:
            h, w, ch = img.shape
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            bytes_per_line = ch * w
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

        self._image_pixmap = QPixmap.fromImage(qimg)
        w, h = self._image_pixmap.width(), self._image_pixmap.height()
        self._cursor_val_str = f"{w} * {h} | X,---- Y,---- | R:--- G:--- B:---"
        self.cursor_info_changed.emit(self._cursor_val_str)

        if self._scale == 1.0 and self._offset == QPoint(0, 0):
            self.fit_to_window()
            self._fit_mode = True

        self.update()

    def resizeEvent(self, event):
        """Keep the whole image visible when the viewport changes size.

        The Image|Result column shares its height with the result grid, so the
        viewport is routinely resized after the first frame is drawn.  Without
        re-fitting, the image would be cropped to whatever fraction of it fits.
        """
        super().resizeEvent(event)
        if self._fit_mode and self._image_pixmap is not None:
            self.fit_to_window()

    def fit_to_window(self):
        if not self._image_pixmap:
            return
        w_view, h_view = self.width(), self.height()
        w_img, h_img = self._image_pixmap.width(), self._image_pixmap.height()
        if w_img == 0 or h_img == 0:
            return

        scale_x = (w_view - 24) / w_img
        scale_y = (h_view - 24) / h_img
        self._scale = max(0.05, min(scale_x, scale_y, 1.0))
        ox = int((w_view - w_img * self._scale) / 2)
        oy = int((h_view - h_img * self._scale) / 2)
        self._offset = QPoint(ox, oy)
        self._fit_mode = True
        self.update()

    def set_zoom_actual(self):
        self._scale = 1.0
        self._fit_mode = False
        if self._image_pixmap:
            ox = int((self.width() - self._image_pixmap.width()) / 2)
            oy = int((self.height() - self._image_pixmap.height()) / 2)
            self._offset = QPoint(ox, oy)
        self.update()

    def zoom_at_center(self, factor: float):
        """Zoom about the viewport centre (used by the image-display toolbar)."""
        if not self._image_pixmap:
            return
        centre = QPoint(self.width() // 2, self.height() // 2)
        old_scale = self._scale
        new_scale = max(0.05, min(old_scale * factor, 40.0))
        if abs(new_scale - old_scale) < 1e-9:
            return
        ratio = new_scale / old_scale
        offset_x = centre.x() - (centre.x() - self._offset.x()) * ratio
        offset_y = centre.y() - (centre.y() - self._offset.y()) * ratio
        self._scale = new_scale
        self._offset = QPoint(int(offset_x), int(offset_y))
        self._fit_mode = False
        self.update()

    def current_pixmap(self):
        """The rendered frame, used to build image-strip thumbnails."""
        return self._image_pixmap

    def wheelEvent(self, event: QWheelEvent):
        if not self._image_pixmap:
            return
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 0.85

        # A manual zoom is an explicit viewport choice: stop auto-refitting.
        self._fit_mode = False

        mouse_pos = event.position().toPoint()
        old_scale = self._scale
        new_scale = max(0.05, min(old_scale * factor, 40.0))

        offset_x = mouse_pos.x() - (mouse_pos.x() - self._offset.x()) * (new_scale / old_scale)
        offset_y = mouse_pos.y() - (mouse_pos.y() - self._offset.y()) * (new_scale / old_scale)

        self._scale = new_scale
        self._offset = QPoint(int(offset_x), int(offset_y))
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if self._draw_roi_mode and event.button() == Qt.MouseButton.LeftButton:
            if self._scale > 0:
                ix = int((event.pos().x() - self._offset.x()) / self._scale)
                iy = int((event.pos().y() - self._offset.y()) / self._scale)
                self._drawing_roi = True
                self._roi_start = QPoint(ix, iy)
                self._roi_curr = QPoint(ix, iy)
                self.update()
                return

        if event.button() == Qt.MouseButton.LeftButton and self._active_roi and not self._draw_roi_mode:
            h = self._get_handle_at(event.pos())
            if h:
                self._resizing_roi = True
                self._active_handle = h
                self._drag_start_roi = list(self._active_roi)
                self._drag_start_mouse = event.pos()
                return

        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._dragging_pan = True
            self._last_mouse_pos = event.pos()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drawing_roi and self._scale > 0:
            ix = int((event.pos().x() - self._offset.x()) / self._scale)
            iy = int((event.pos().y() - self._offset.y()) / self._scale)
            self._roi_curr = QPoint(ix, iy)
            self.update()
            return

        if self._resizing_roi and self._drag_start_roi and self._active_handle and self._scale > 0:
            dx = (event.pos().x() - self._drag_start_mouse.x()) / self._scale
            dy = (event.pos().y() - self._drag_start_mouse.y()) / self._scale
            ox, oy, ow, oh = self._drag_start_roi
            nx, ny, nw, nh = ox, oy, ow, oh

            if self._active_handle == "body":
                nx = int(ox + dx)
                ny = int(oy + dy)
                if self._image_pixmap:
                    nx = max(0, min(nx, self._image_pixmap.width() - ow))
                    ny = max(0, min(ny, self._image_pixmap.height() - oh))
            elif self._active_handle == "se":
                nw = max(8, int(ow + dx))
                nh = max(8, int(oh + dy))
            elif self._active_handle == "e":
                nw = max(8, int(ow + dx))
            elif self._active_handle == "s":
                nh = max(8, int(oh + dy))
            elif self._active_handle == "nw":
                cur_x2, cur_y2 = ox + ow, oy + oh
                cand_x = min(cur_x2 - 8, int(ox + dx))
                cand_y = min(cur_y2 - 8, int(oy + dy))
                nx = max(0, cand_x)
                ny = max(0, cand_y)
                nw = cur_x2 - nx
                nh = cur_y2 - ny
            elif self._active_handle == "ne":
                cur_y2 = oy + oh
                cand_y = min(cur_y2 - 8, int(oy + dy))
                ny = max(0, cand_y)
                nw = max(8, int(ow + dx))
                nh = cur_y2 - ny
            elif self._active_handle == "sw":
                cur_x2 = ox + ow
                cand_x = min(cur_x2 - 8, int(ox + dx))
                nx = max(0, cand_x)
                nw = cur_x2 - nx
                nh = max(8, int(oh + dy))
            elif self._active_handle == "n":
                cur_y2 = oy + oh
                cand_y = min(cur_y2 - 8, int(oy + dy))
                ny = max(0, cand_y)
                nh = cur_y2 - ny
            elif self._active_handle == "w":
                cur_x2 = ox + ow
                cand_x = min(cur_x2 - 8, int(ox + dx))
                nx = max(0, cand_x)
                nw = cur_x2 - nx

            self._active_roi = [nx, ny, nw, nh]
            self.update()
            return

        if self._dragging_pan:
            delta = event.pos() - self._last_mouse_pos
            self._offset += delta
            self._last_mouse_pos = event.pos()
            self._fit_mode = False
            self.update()

        # Update hover handle & cursor
        if not self._dragging_pan and not self._drawing_roi and not self._draw_roi_mode and self._active_roi:
            h = self._get_handle_at(event.pos())
            self._hovered_handle = h
            self.setCursor(self._cursor_for_handle(h))
        elif not self._draw_roi_mode:
            self._hovered_handle = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

        if self._image_pixmap and self._scale > 0:
            ix = int((event.pos().x() - self._offset.x()) / self._scale)
            iy = int((event.pos().y() - self._offset.y()) / self._scale)
            w = self._image_pixmap.width()
            h = self._image_pixmap.height()
            if 0 <= ix < w and 0 <= iy < h:
                self._cursor_img_pos = QPoint(ix, iy)
                if self._raw_cv_image is not None:
                    val = self._raw_cv_image[iy, ix]
                    if len(self._raw_cv_image.shape) == 3:
                        b, g, r = val[:3]
                        self._cursor_val_str = f"{w} * {h} | X,{ix:04d} Y,{iy:04d} | R:{int(r):03d} G:{int(g):03d} B:{int(b):03d}"
                    else:
                        self._cursor_val_str = f"{w} * {h} | X,{ix:04d} Y,{iy:04d} | Gray:{int(val):03d}"
                else:
                    self._cursor_val_str = f"{w} * {h} | X,{ix:04d} Y,{iy:04d}"
            else:
                self._cursor_img_pos = None
                self._cursor_val_str = f"{w} * {h} | X,---- Y,---- | R:--- G:--- B:---"
            self.cursor_info_changed.emit(self._cursor_val_str)
            self.update()

    def leaveEvent(self, event):
        self._cursor_img_pos = None
        if self._image_pixmap:
            w = self._image_pixmap.width()
            h = self._image_pixmap.height()
            self._cursor_val_str = f"{w} * {h} | X,---- Y,---- | R:--- G:--- B:---"
        else:
            self._cursor_val_str = ""
        self.cursor_info_changed.emit(self._cursor_val_str)
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._drawing_roi and event.button() == Qt.MouseButton.LeftButton:
            self._drawing_roi = False
            if self._roi_start and self._roi_curr:
                x1 = min(self._roi_start.x(), self._roi_curr.x())
                y1 = min(self._roi_start.y(), self._roi_curr.y())
                w = abs(self._roi_curr.x() - self._roi_start.x())
                h = abs(self._roi_curr.y() - self._roi_start.y())
                if w > 4 and h > 4:
                    self._active_roi = [x1, y1, w, h]
                    self.roi_changed.emit(self._active_roi)
            self.update()
            return

        if self._resizing_roi and event.button() == Qt.MouseButton.LeftButton:
            self._resizing_roi = False
            self._active_handle = None
            if self._active_roi:
                self.roi_changed.emit(self._active_roi)
            self.update()
            return

        self._dragging_pan = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Viewport Neutral Dark
        painter.fillRect(self.rect(), QColor(18, 20, 26))

        if not self._image_pixmap:
            cx = self.width() // 2
            cy = self.height() // 2
            box_w = min(460, max(280, self.width() - 40))
            box_h = 100
            box_rect = QRectF(cx - box_w / 2, cy - box_h / 2, box_w, box_h)

            border_color = QColor(239, 68, 68) if self._is_error_state else QColor(59, 130, 246, 120)
            bg_color = QColor(40, 20, 24, 220) if self._is_error_state else QColor(24, 28, 38, 220)

            painter.setPen(QPen(border_color, 1.2, Qt.PenStyle.DashLine if not self._is_error_state else Qt.PenStyle.SolidLine))
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(box_rect, 4.0, 4.0)

            title_color = QColor(248, 113, 113) if self._is_error_state else QColor(226, 232, 240)
            painter.setPen(title_color)
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            painter.drawText(
                QRectF(box_rect.x(), box_rect.y() + 16, box_rect.width(), 24),
                Qt.AlignmentFlag.AlignCenter,
                self._empty_message
            )

            sub_color = QColor(203, 213, 225) if self._is_error_state else QColor(148, 163, 184)
            painter.setPen(sub_color)
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(
                QRectF(box_rect.x() + 10, box_rect.y() + 45, box_rect.width() - 20, 44),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._empty_subtext
            )
            return

        # Image Transform
        painter.save()
        painter.translate(self._offset)
        painter.scale(self._scale, self._scale)

        painter.drawPixmap(0, 0, self._image_pixmap)

        # Image Frame Border
        pen_border = QPen(QColor(42, 48, 62), 1.0 / self._scale)
        painter.setPen(pen_border)
        painter.drawRect(0, 0, self._image_pixmap.width(), self._image_pixmap.height())

        self._draw_overlays(painter)

        # Active ROI drawing box
        if self._drawing_roi and self._roi_start and self._roi_curr:
            rx = min(self._roi_start.x(), self._roi_curr.x())
            ry = min(self._roi_start.y(), self._roi_curr.y())
            rw = abs(self._roi_curr.x() - self._roi_start.x())
            rh = abs(self._roi_curr.y() - self._roi_start.y())
            painter.setPen(QPen(QColor(245, 158, 11), 1.5 / self._scale, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(245, 158, 11, 25)))
            painter.drawRect(rx, ry, rw, rh)
        elif self._active_roi:
            rx, ry, rw, rh = self._active_roi
            painter.setPen(QPen(QColor(59, 130, 246), 1.5 / self._scale, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(59, 130, 246, 20)))
            painter.drawRect(rx, ry, rw, rh)

            # Corner brackets (L-shape accents)
            bracket_len = min(rw, rh, 12)
            if bracket_len > 4:
                bpen = QPen(QColor(59, 130, 246), 2.0 / self._scale)
                painter.setPen(bpen)
                painter.drawLine(rx, ry, rx + bracket_len, ry)
                painter.drawLine(rx, ry, rx, ry + bracket_len)
                painter.drawLine(rx + rw, ry, rx + rw - bracket_len, ry)
                painter.drawLine(rx + rw, ry, rx + rw, ry + bracket_len)
                painter.drawLine(rx, ry + rh, rx + bracket_len, ry + rh)
                painter.drawLine(rx, ry + rh, rx, ry + rh - bracket_len)
                painter.drawLine(rx + rw, ry + rh, rx + rw - bracket_len, ry + rh)
                painter.drawLine(rx + rw, ry + rh, rx + rw, ry + rh - bracket_len)

        painter.restore()

        # Draw active ROI handles & HUD in screen coordinates
        if self._active_roi and not self._drawing_roi:
            srect = self._get_roi_screen_rect()
            if srect:
                handles = self._get_handles()
                for h_name, h_rect in handles.items():
                    if h_name == self._hovered_handle or h_name == self._active_handle:
                        painter.setPen(QPen(QColor(40, 45, 60), 1.0))
                        painter.setBrush(QBrush(QColor(245, 158, 11)))  # Amber active
                    else:
                        painter.setPen(QPen(QColor(40, 45, 60), 1.0))
                        painter.setBrush(QBrush(QColor(59, 130, 246)))  # Blue normal
                    painter.drawRect(h_rect)

                # ROI Dimension badge
                rx, ry, rw, rh = self._active_roi
                dim_str = f"ROI: {rw}x{rh} @ ({rx}, {ry})"
                painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
                badge_w = len(dim_str) * 6.5 + 8
                badge_y = max(8.0, srect.y() - 16.0)
                painter.setPen(QPen(QColor(42, 48, 62), 1.0))
                painter.setBrush(QColor(24, 27, 36, 235))
                painter.drawRect(QRectF(srect.x(), badge_y, badge_w, 14.0))
                painter.setPen(QColor(96, 165, 250))
                painter.drawText(QPointF(srect.x() + 4, badge_y + 11), dim_str)

        # Measurement Crosshair Reticle (Discrete)
        if self._show_crosshair and self._cursor_img_pos and self._scale > 0:
            cx = self._offset.x() + int(self._cursor_img_pos.x() * self._scale)
            cy = self._offset.y() + int(self._cursor_img_pos.y() * self._scale)
            painter.setPen(QPen(QColor(100, 116, 139, 140), 1, Qt.PenStyle.DashLine))
            painter.drawLine(cx, 0, cx, self.height())
            painter.drawLine(0, cy, self.width(), cy)

        # Histogram HUD
        if self._show_hist and self._raw_cv_image is not None:
            self._draw_histogram_hud(painter)

    def _draw_overlays(self, painter: QPainter):
        if not self._show_overlays:
            return

        for item in self._overlays:
            itype = item.get("type")
            if itype == "rect" and not self._show_rois:
                continue
            if itype in ("circle", "line", "text") and not self._show_measurements:
                continue
            if itype == "cross" and not self._show_datums:
                continue

            col = item.get("color", (0, 255, 0))
            qcol = QColor(col[2], col[1], col[0]) if len(col) == 3 else QColor(40, 167, 69)
            pen = QPen(qcol, max(1.2, 1.8 / self._scale))
            painter.setPen(pen)

            if itype == "rect":
                b = item.get("box", [0, 0, 0, 0])
                rx, ry, rw, rh = b[0], b[1], b[2], b[3]
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rx, ry, rw, rh)

                label = item.get("label")
                if label:
                    painter.setFont(QFont("Segoe UI", max(8, int(9 / self._scale)), QFont.Weight.Bold))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(20, 24, 32, 220))
                    text_w = len(label) * int(6.8 / self._scale) + 8
                    text_h = int(14 / self._scale)
                    painter.drawRect(rx, max(0, ry - text_h - 2), text_w, text_h)
                    painter.setPen(qcol)
                    painter.drawText(rx + 4, max(9, ry - 4), label)

            elif itype == "circle":
                cx, cy = item.get("center", (0, 0))
                r = item.get("radius", 10)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
                label = item.get("label")
                if label:
                    painter.setFont(QFont("Consolas", max(8, int(9 / self._scale)), QFont.Weight.Bold))
                    painter.drawText(cx + r + 4, cy + 4, label)

            elif itype == "line":
                p1 = item.get("pt1", (0, 0))
                p2 = item.get("pt2", (0, 0))
                th = item.get("thickness", 2)
                pen.setWidthF(th / self._scale)
                painter.setPen(pen)
                painter.drawLine(p1[0], p1[1], p2[0], p2[1])

            elif itype == "cross":
                pt = item.get("pt", (0, 0))
                sz = item.get("size", 8)
                painter.drawLine(pt[0] - sz, pt[1], pt[0] + sz, pt[1])
                painter.drawLine(pt[0], pt[1] - sz, pt[0], pt[1] + sz)

            elif itype == "text":
                txt = item.get("text", "")
                pt = item.get("pt", (10, 20))
                painter.setFont(QFont("Segoe UI", max(8, int(9.5 / self._scale)), QFont.Weight.Bold))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(20, 24, 32, 220))
                tw = len(txt) * int(6.8 / self._scale) + 8
                th = int(14 / self._scale)
                painter.drawRect(pt[0] - 2, pt[1] - th + 2, tw, th)
                painter.setPen(qcol)
                painter.drawText(pt[0] + 2, pt[1], txt)

    def _draw_histogram_hud(self, painter: QPainter):
        gray = cv2.cvtColor(self._raw_cv_image, cv2.COLOR_BGR2GRAY) if len(self._raw_cv_image.shape) == 3 else self._raw_cv_image
        hist = cv2.calcHist([gray], [0], None, [128], [0, 256]).flatten()
        max_h = max(1.0, float(np.max(hist)))

        hw, hh = 180, 80
        hx = self.width() - hw - 10
        hy = self.height() - hh - 36

        painter.setPen(QPen(QColor(42, 48, 62), 1))
        painter.setBrush(QColor(22, 25, 34, 230))
        painter.drawRect(QRectF(hx, hy, hw, hh))

        painter.setPen(QColor(160, 172, 188))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(hx + 8, hy + 13, "Histogram (0-255)")

        bar_w = (hw - 16) / 128.0
        plot_h = hh - 22
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(74, 144, 226, 200))

        for i, val in enumerate(hist):
            bar_len = (val / max_h) * plot_h
            bx = hx + 8 + i * bar_w
            by = hy + hh - 6 - bar_len
            painter.drawRect(QRectF(bx, by, max(1.0, bar_w), bar_len))
