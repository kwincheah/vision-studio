"""
Industrial Vector Icon Provider for Apex Industrial Vision Studio.
Grounded in Apple Design HIG principles for interface icons:
- Highly simplified, recognizable glyphs with immediate semantic clarity (icons.md)
- Optically balanced within 16x16 canvas with consistent 1.35px stroke weight (icons.md)
- Round caps and joins preventing sub-pixel corner clipping (sf-symbols.md)
- Cohesive typography and icon weight pairing (typography.md, icons.md)
- Purposeful accent coloring in sidebars and toolbars (sidebars.md, color.md)
"""
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QPainterPath, QFont
from PyQt6.QtCore import Qt, QRectF, QPointF
from typing import Dict, Optional


# Palette tokens for icon rendering
ICON_COLOR_ACCENT = QColor(59, 130, 246)     # Engineering Blue (#3b82f6)
ICON_COLOR_LIGHT = QColor(241, 245, 249)      # Slate 100 text (#f1f5f9)
ICON_COLOR_MUTED = QColor(148, 163, 184)      # Slate 400 (#94a3b8)
ICON_COLOR_DARK = QColor(22, 26, 34)          # Surface background


def _create_canvas(size: int = 16) -> tuple[QPixmap, QPainter]:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    return pix, p


def _create_pen(color: QColor, width: float = 1.35, style: Qt.PenStyle = Qt.PenStyle.SolidLine) -> QPen:
    pen = QPen(color, width, style)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def get_category_icon(category_name: str, size: int = 16, accent_color: Optional[QColor] = None) -> QIcon:
    """Returns a crisp, recognizable icon for each module category."""
    pix, p = _create_canvas(size)
    col = accent_color or ICON_COLOR_ACCENT
    pen = _create_pen(col, 1.35)
    p.setPen(pen)

    c = category_name.strip()
    if c == "Acquisition":
        # Camera with top lens ridge
        p.drawRoundedRect(QRectF(2.0, 4.5, 12.0, 9.0), 1.5, 1.5)
        p.drawEllipse(QRectF(5.5, 6.5, 5.0, 5.0))
        p.drawLine(QPointF(4.5, 4.5), QPointF(6.0, 2.5))
        p.drawLine(QPointF(6.0, 2.5), QPointF(8.0, 2.5))
    elif c == "Location":
        # Precision target reticle
        p.drawEllipse(QRectF(2.5, 2.5, 11.0, 11.0))
        p.drawLine(QPointF(8.0, 1.5), QPointF(8.0, 14.5))
        p.drawLine(QPointF(1.5, 8.0), QPointF(14.5, 8.0))
    elif c == "Measurement":
        # Precision vernier caliper dimension
        p.drawLine(QPointF(2.5, 3.0), QPointF(2.5, 13.0))
        p.drawLine(QPointF(13.5, 3.0), QPointF(13.5, 13.0))
        p.drawLine(QPointF(2.5, 8.0), QPointF(13.5, 8.0))
        p.drawLine(QPointF(2.5, 8.0), QPointF(5.0, 6.0))
        p.drawLine(QPointF(2.5, 8.0), QPointF(5.0, 10.0))
        p.drawLine(QPointF(13.5, 8.0), QPointF(11.0, 6.0))
        p.drawLine(QPointF(13.5, 8.0), QPointF(11.0, 10.0))
    elif c == "Image Generation":
        # Fitted geometry circle and tangent line
        p.drawEllipse(QRectF(3.0, 3.0, 10.0, 10.0))
        p.setPen(_create_pen(ICON_COLOR_LIGHT, 1.2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(1.5, 14.5), QPointF(14.5, 1.5))
    elif c == "Image Processing":
        # Filter adjustment disc with half-fill
        p.drawEllipse(QRectF(2.5, 2.5, 11.0, 11.0))
        p.setBrush(QBrush(col))
        path = QPainterPath()
        path.moveTo(8.0, 2.5)
        path.arcTo(QRectF(2.5, 2.5, 11.0, 11.0), 90, -180)
        path.closeSubpath()
        p.drawPath(path)
    elif c == "Color Processing":
        # Color droplet / spectrum pip
        p.drawEllipse(QRectF(5.0, 7.0, 6.0, 6.0))
        path = QPainterPath()
        path.moveTo(8.0, 2.0)
        path.lineTo(11.0, 7.5)
        path.lineTo(5.0, 7.5)
        path.closeSubpath()
        p.drawPath(path)
    elif c == "Recognition":
        # 2D Data matrix finder pattern
        p.drawRoundedRect(QRectF(2.5, 2.5, 4.5, 4.5), 1.0, 1.0)
        p.drawRoundedRect(QRectF(9.0, 2.5, 4.5, 4.5), 1.0, 1.0)
        p.drawRoundedRect(QRectF(2.5, 9.0, 4.5, 4.5), 1.0, 1.0)
        p.fillRect(QRectF(10.0, 10.0, 3.5, 3.5), col)
    elif c == "Defect Detection":
        # Magnifier inspecting surface crack anomaly
        p.drawEllipse(QRectF(2.0, 2.0, 10.0, 10.0))
        p.drawLine(QPointF(9.0, 9.0), QPointF(14.0, 14.0))
        p.drawLine(QPointF(5.0, 7.0), QPointF(7.0, 5.0))
        p.drawLine(QPointF(7.0, 5.0), QPointF(6.5, 8.5))
        p.drawLine(QPointF(6.5, 8.5), QPointF(9.0, 7.0))
    elif c == "Calibration":
        # Coordinate grid / 9-point spatial calibration
        p.drawRoundedRect(QRectF(1.5, 1.5, 13.0, 13.0), 1.5, 1.5)
        for row in (4.0, 8.0, 12.0):
            for col_x in (4.0, 8.0, 12.0):
                p.drawPoint(QPointF(col_x, row))
    elif c == "Communication":
        # Network bus & bidirectional port pins
        p.drawRoundedRect(QRectF(2.5, 3.5, 11.0, 7.5), 1.5, 1.5)
        p.drawLine(QPointF(5.0, 11.0), QPointF(5.0, 14.0))
        p.drawLine(QPointF(8.0, 11.0), QPointF(8.0, 14.0))
        p.drawLine(QPointF(11.0, 11.0), QPointF(11.0, 14.0))
    elif c == "Logic Tools":
        # Flowchart decision diamond
        path = QPainterPath()
        path.moveTo(8.0, 2.0)
        path.lineTo(14.0, 8.0)
        path.lineTo(8.0, 14.0)
        path.lineTo(2.0, 8.0)
        path.closeSubpath()
        p.drawPath(path)
    else:
        p.drawRoundedRect(QRectF(3.0, 3.0, 10.0, 10.0), 1.5, 1.5)

    p.end()
    return QIcon(pix)


def get_tool_icon(tool_name: str, size: int = 16, accent_color: Optional[QColor] = None) -> QIcon:
    """Returns a specific vector icon for any of the 34 machine vision tools."""
    pix, p = _create_canvas(size)
    col = accent_color or ICON_COLOR_ACCENT
    pen = _create_pen(col, 1.35)
    p.setPen(pen)

    t = tool_name.strip()
    if t == "Image Source":
        p.drawRoundedRect(QRectF(2.0, 4.0, 12.0, 9.0), 1.5, 1.5)
        p.drawEllipse(QRectF(5.5, 6.0, 5.0, 5.0))
    elif t == "Image Output":
        p.drawRoundedRect(QRectF(2.5, 2.5, 11.0, 11.0), 1.5, 1.5)
        p.drawLine(QPointF(8.0, 5.0), QPointF(8.0, 11.0))
        p.drawLine(QPointF(5.5, 8.5), QPointF(8.0, 11.0))
        p.drawLine(QPointF(10.5, 8.5), QPointF(8.0, 11.0))
    elif t == "Image Buffer":
        p.drawRoundedRect(QRectF(2.0, 2.0, 9.0, 7.0), 1.0, 1.0)
        p.drawRoundedRect(QRectF(5.0, 7.0, 9.0, 7.0), 1.0, 1.0)
    elif t == "Template Match":
        p.drawRoundedRect(QRectF(2.5, 2.5, 11.0, 11.0), 1.5, 1.5)
        p.drawRect(QRectF(5.5, 5.5, 5.0, 5.0))
        p.drawPoint(QPointF(8.0, 8.0))
    elif t == "Position Correction":
        p.drawEllipse(QRectF(2.5, 2.5, 7.0, 7.0))
        p.drawEllipse(QRectF(6.5, 6.5, 7.0, 7.0))
        p.drawLine(QPointF(4.0, 12.0), QPointF(12.0, 4.0))
    elif t == "Circle Search":
        p.drawEllipse(QRectF(3.0, 3.0, 10.0, 10.0))
        p.drawLine(QPointF(8.0, 1.0), QPointF(8.0, 4.0))
        p.drawLine(QPointF(8.0, 12.0), QPointF(8.0, 15.0))
        p.drawLine(QPointF(1.0, 8.0), QPointF(4.0, 8.0))
        p.drawLine(QPointF(12.0, 8.0), QPointF(15.0, 8.0))
    elif t == "Line Search":
        p.drawLine(QPointF(2.0, 14.0), QPointF(14.0, 2.0))
        for offset in (4.0, 7.0, 10.0, 13.0):
            p.drawLine(QPointF(offset - 1.5, offset - 1.5), QPointF(offset + 1.5, offset + 1.5))
    elif t == "Caliper":
        p.drawLine(QPointF(3.0, 3.0), QPointF(3.0, 13.0))
        p.drawLine(QPointF(13.0, 3.0), QPointF(13.0, 13.0))
        p.drawLine(QPointF(3.0, 8.0), QPointF(13.0, 8.0))
    elif t == "Edge Search":
        path = QPainterPath()
        path.moveTo(2.0, 12.0)
        path.lineTo(6.5, 12.0)
        path.lineTo(9.5, 4.0)
        path.lineTo(14.0, 4.0)
        p.drawPath(path)
    elif t == "BLOB Analysis":
        p.drawEllipse(QRectF(3.0, 3.0, 4.5, 4.5))
        p.drawEllipse(QRectF(8.5, 4.0, 4.0, 4.0))
        p.drawEllipse(QRectF(5.5, 8.5, 5.0, 5.0))
    elif t == "L2L Measure":
        p.drawLine(QPointF(2.0, 3.0), QPointF(14.0, 3.0))
        p.drawLine(QPointF(2.0, 13.0), QPointF(14.0, 13.0))
        p.drawLine(QPointF(8.0, 3.0), QPointF(8.0, 13.0))
        p.drawPoint(QPointF(8.0, 3.0))
        p.drawPoint(QPointF(8.0, 13.0))
    elif t == "P2P Measure":
        p.drawLine(QPointF(3.0, 13.0), QPointF(13.0, 3.0))
        p.drawEllipse(QRectF(1.5, 11.5, 3.0, 3.0))
        p.drawEllipse(QRectF(11.5, 1.5, 3.0, 3.0))
    elif t == "Intensity Measure":
        p.drawRoundedRect(QRectF(2.0, 3.0, 12.0, 10.0), 1.5, 1.5)
        p.drawLine(QPointF(5.0, 5.0), QPointF(5.0, 11.0))
        p.drawLine(QPointF(8.0, 5.0), QPointF(8.0, 11.0))
        p.drawLine(QPointF(11.0, 5.0), QPointF(11.0, 11.0))
    elif t == "Pixel Count":
        for y_pos in (3.5, 8.0, 12.5):
            for x_pos in (3.5, 8.0, 12.5):
                p.drawPoint(QPointF(x_pos, y_pos))
    elif t == "Edge Distance":
        p.drawLine(QPointF(4.0, 3.0), QPointF(4.0, 13.0))
        p.drawLine(QPointF(12.0, 3.0), QPointF(12.0, 13.0))
        p.setPen(_create_pen(col, 1.0, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(4.0, 8.0), QPointF(12.0, 8.0))
    elif t == "Histogram":
        p.drawLine(QPointF(2.0, 13.5), QPointF(14.0, 13.5))
        p.fillRect(QRectF(3.0, 9.0, 2.0, 4.0), col)
        p.fillRect(QRectF(6.0, 4.0, 2.0, 9.0), col)
        p.fillRect(QRectF(9.0, 7.0, 2.0, 6.0), col)
        p.fillRect(QRectF(12.0, 10.0, 1.5, 3.0), col)
    elif t in ("Circle/Line Fit", "Geometry Fit"):
        p.drawEllipse(QRectF(3.0, 3.0, 10.0, 10.0))
        p.drawPoint(QPointF(4.0, 5.0))
        p.drawPoint(QPointF(12.0, 5.0))
        p.drawPoint(QPointF(8.0, 13.0))
    elif t in ("Geometry Generation", "Geometry Gen"):
        p.drawLine(QPointF(8.0, 2.0), QPointF(8.0, 14.0))
        p.drawLine(QPointF(2.0, 8.0), QPointF(14.0, 8.0))
        p.drawEllipse(QRectF(4.5, 4.5, 7.0, 7.0))
    elif t == "Image Binarization":
        p.drawRoundedRect(QRectF(2.0, 2.0, 12.0, 12.0), 1.5, 1.5)
        p.fillRect(QRectF(2.0, 2.0, 6.0, 12.0), col)
    elif t == "Image Filter":
        p.drawEllipse(QRectF(3.0, 3.0, 10.0, 10.0))
        p.drawLine(QPointF(8.0, 3.0), QPointF(8.0, 13.0))
        p.drawLine(QPointF(3.0, 8.0), QPointF(13.0, 8.0))
    elif t == "Image Morphology":
        p.drawRect(QRectF(3.0, 3.0, 4.5, 4.5))
        p.drawRect(QRectF(8.5, 8.5, 4.5, 4.5))
        p.drawRect(QRectF(5.5, 5.5, 5.0, 5.0))
    elif t == "Color Extraction":
        path = QPainterPath()
        path.moveTo(8.0, 2.0)
        path.lineTo(12.0, 8.0)
        path.arcTo(QRectF(4.0, 6.0, 8.0, 8.0), 0, -180)
        path.closeSubpath()
        p.drawPath(path)
    elif t == "Color Measurement":
        p.drawEllipse(QRectF(2.0, 5.0, 7.0, 7.0))
        p.drawEllipse(QRectF(7.0, 5.0, 7.0, 7.0))
        p.drawEllipse(QRectF(4.5, 2.0, 7.0, 7.0))
    elif t in ("2D BCR Recognition", "2D Barcode"):
        p.drawRoundedRect(QRectF(2.0, 2.0, 12.0, 12.0), 1.5, 1.5)
        p.drawRect(QRectF(4.0, 4.0, 3.0, 3.0))
        p.drawRect(QRectF(9.0, 4.0, 3.0, 3.0))
        p.drawRect(QRectF(4.0, 9.0, 3.0, 3.0))
        p.drawPoint(QPointF(10.5, 10.5))
    elif t in ("BCR Recognition", "1D Barcode"):
        for x_pos in (3.0, 5.5, 7.5, 9.5, 11.5, 13.5):
            p.drawLine(QPointF(x_pos, 3.0), QPointF(x_pos, 13.0))
    elif t in ("OCR Recognition", "OCR"):
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 16, 16), Qt.AlignmentFlag.AlignCenter, "A")
    elif t == "Defect Detection":
        p.drawRoundedRect(QRectF(2.0, 2.0, 12.0, 12.0), 1.5, 1.5)
        p.drawLine(QPointF(5.0, 11.0), QPointF(8.0, 5.0))
        p.drawLine(QPointF(8.0, 5.0), QPointF(11.0, 11.0))
    elif t == "Linear Edge Defect":
        p.drawLine(QPointF(2.0, 8.0), QPointF(14.0, 8.0))
        p.drawLine(QPointF(6.0, 8.0), QPointF(8.0, 4.0))
        p.drawLine(QPointF(8.0, 4.0), QPointF(10.0, 8.0))
    elif t == "N-Point Calibration":
        p.drawRoundedRect(QRectF(2.0, 2.0, 12.0, 12.0), 1.5, 1.5)
        p.drawLine(QPointF(4.0, 4.0), QPointF(12.0, 12.0))
        p.drawLine(QPointF(12.0, 4.0), QPointF(4.0, 12.0))
    elif t in ("Lens Distortion Calibration", "Camera Calibration", "Undistort"):
        p.drawEllipse(QRectF(2.5, 2.5, 11.0, 11.0))
        p.drawArc(QRectF(4.0, 4.0, 8.0, 8.0), 45 * 16, 90 * 16)
        p.drawArc(QRectF(4.0, 4.0, 8.0, 8.0), 225 * 16, 90 * 16)
        p.drawPoint(QPointF(8.0, 8.0))
    elif t in ("Condition Branch", "Branch", "Branch String"):
        path = QPainterPath()
        path.moveTo(3.0, 8.0)
        path.lineTo(7.0, 8.0)
        path.lineTo(13.0, 4.0)
        path.moveTo(7.0, 8.0)
        path.lineTo(13.0, 12.0)
        p.drawPath(path)
    elif t == "If Module":
        path = QPainterPath()
        path.moveTo(8.0, 2.5)
        path.lineTo(13.5, 8.0)
        path.lineTo(8.0, 13.5)
        path.lineTo(2.5, 8.0)
        path.closeSubpath()
        p.drawPath(path)
    elif t == "Trigger":
        p.drawLine(QPointF(2.0, 8.0), QPointF(11.0, 8.0))
        p.drawLine(QPointF(8.0, 4.0), QPointF(12.0, 8.0))
        p.drawLine(QPointF(8.0, 12.0), QPointF(12.0, 8.0))
        p.drawEllipse(QRectF(11.0, 6.0, 4.0, 4.0))
    elif t == "Variable Calculation":
        p.drawLine(QPointF(4.0, 8.0), QPointF(12.0, 8.0))
        p.drawLine(QPointF(8.0, 4.0), QPointF(8.0, 12.0))
    elif t == "Script Tool":
        path = QPainterPath()
        path.moveTo(6.0, 4.0)
        path.lineTo(3.0, 8.0)
        path.lineTo(6.0, 12.0)
        path.moveTo(10.0, 4.0)
        path.lineTo(13.0, 8.0)
        path.lineTo(10.0, 12.0)
        p.drawPath(path)
    elif t == "TCP Send":
        p.drawRoundedRect(QRectF(2.0, 4.0, 12.0, 8.0), 1.5, 1.5)
        p.drawLine(QPointF(5.0, 8.0), QPointF(11.0, 8.0))
        p.drawLine(QPointF(9.0, 6.0), QPointF(11.0, 8.0))
        p.drawLine(QPointF(9.0, 10.0), QPointF(11.0, 8.0))
    elif t == "Camera IO":
        p.drawRoundedRect(QRectF(2.0, 3.0, 12.0, 10.0), 1.5, 1.5)
        p.drawEllipse(QRectF(6.0, 6.0, 4.0, 4.0))
    elif t in ("Object Detection", "YOLO Object Detection"):
        p.drawRoundedRect(QRectF(2.0, 2.0, 12.0, 12.0), 1.5, 1.5)
        p.drawRect(QRectF(5.0, 5.0, 6.0, 6.0))
        p.drawPoint(QPointF(8.0, 8.0))
    else:
        p.drawRoundedRect(QRectF(3.0, 3.0, 10.0, 10.0), 1.5, 1.5)

    p.end()
    return QIcon(pix)


def get_action_icon(action_name: str, size: int = 16) -> QIcon:
    """Returns a vector icon for command toolbar controls."""
    pix, p = _create_canvas(size)
    col = ICON_COLOR_LIGHT
    pen = _create_pen(col, 1.35)
    p.setPen(pen)

    a = action_name.lower().strip()
    if a in ("run_once", "once", "run"):
        # Play arrow (Success green fill)
        path = QPainterPath()
        path.moveTo(4.5, 3.0)
        path.lineTo(12.5, 8.0)
        path.lineTo(4.5, 13.0)
        path.closeSubpath()
        p.setBrush(QBrush(QColor(34, 197, 94)))
        p.setPen(_create_pen(QColor(22, 101, 52), 1.0))
        p.drawPath(path)
    elif a in ("run_all", "run_solution"):
        # Dual play arrows (Accent blue fill)
        p.setBrush(QBrush(ICON_COLOR_ACCENT))
        p.setPen(Qt.PenStyle.NoPen)
        path1 = QPainterPath()
        path1.moveTo(2.5, 3.5)
        path1.lineTo(8.5, 8.0)
        path1.lineTo(2.5, 12.5)
        path1.closeSubpath()
        p.drawPath(path1)

        path2 = QPainterPath()
        path2.moveTo(8.5, 3.5)
        path2.lineTo(14.5, 8.0)
        path2.lineTo(8.5, 12.5)
        path2.closeSubpath()
        p.drawPath(path2)
    elif a in ("continuous", "continuously"):
        # Cycle loop arrows (Amber stroke)
        p.setPen(_create_pen(QColor(245, 158, 11), 1.4))
        p.drawArc(QRectF(3.0, 3.0, 10.0, 10.0), 45 * 16, 270 * 16)
        p.drawLine(QPointF(12.5, 8.0), QPointF(12.5, 4.0))
        p.drawLine(QPointF(12.5, 4.0), QPointF(8.5, 4.0))
    elif a == "stop":
        # Square stop (Alert red fill)
        p.setBrush(QBrush(QColor(239, 68, 68)))
        p.setPen(_create_pen(QColor(153, 27, 27), 1.0))
        p.drawRoundedRect(QRectF(3.5, 3.5, 9.0, 9.0), 1.5, 1.5)
    elif a == "fit":
        # Window expand corners
        p.drawRoundedRect(QRectF(4.0, 4.0, 8.0, 8.0), 1.0, 1.0)
        p.drawLine(QPointF(2.0, 2.0), QPointF(5.0, 2.0))
        p.drawLine(QPointF(2.0, 2.0), QPointF(2.0, 5.0))
        p.drawLine(QPointF(14.0, 14.0), QPointF(11.0, 14.0))
        p.drawLine(QPointF(14.0, 14.0), QPointF(14.0, 11.0))
    elif a in ("zoom_100", "1:1"):
        # 1:1 symbol
        p.drawRoundedRect(QRectF(1.5, 2.0, 13.0, 12.0), 1.5, 1.5)
        p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 16, 16), Qt.AlignmentFlag.AlignCenter, "1:1")
    elif a == "draw_roi":
        # Dashed ROI bracket box
        p.setPen(_create_pen(ICON_COLOR_ACCENT, 1.35, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(3.0, 3.0, 10.0, 10.0))
        p.setPen(_create_pen(ICON_COLOR_LIGHT, 1.5))
        p.drawLine(QPointF(2.0, 2.0), QPointF(5.0, 2.0))
        p.drawLine(QPointF(2.0, 2.0), QPointF(2.0, 5.0))
        p.drawLine(QPointF(14.0, 14.0), QPointF(11.0, 14.0))
        p.drawLine(QPointF(14.0, 14.0), QPointF(14.0, 11.0))
    elif a == "histogram":
        p.drawLine(QPointF(2.0, 13.0), QPointF(14.0, 13.0))
        p.fillRect(QRectF(3.5, 9.0, 2.0, 4.0), col)
        p.fillRect(QRectF(7.0, 4.0, 2.0, 9.0), col)
        p.fillRect(QRectF(10.5, 7.0, 2.0, 6.0), col)
    elif a == "layers":
        p.drawLine(QPointF(8.0, 2.0), QPointF(14.0, 5.0))
        p.drawLine(QPointF(14.0, 5.0), QPointF(8.0, 8.0))
        p.drawLine(QPointF(8.0, 8.0), QPointF(2.0, 5.0))
        p.drawLine(QPointF(2.0, 5.0), QPointF(8.0, 2.0))
        p.drawLine(QPointF(2.0, 8.5), QPointF(8.0, 11.5))
        p.drawLine(QPointF(8.0, 11.5), QPointF(14.0, 8.5))
        p.drawLine(QPointF(2.0, 12.0), QPointF(8.0, 15.0))
        p.drawLine(QPointF(8.0, 15.0), QPointF(14.0, 12.0))
    elif a == "arrange":
        p.drawLine(QPointF(3.0, 8.0), QPointF(8.0, 8.0))
        p.drawLine(QPointF(8.0, 4.0), QPointF(8.0, 12.0))
        p.drawLine(QPointF(8.0, 4.0), QPointF(13.0, 4.0))
        p.drawLine(QPointF(8.0, 12.0), QPointF(13.0, 12.0))
        p.fillRect(QRectF(1.0, 6.0, 3.0, 4.0), ICON_COLOR_ACCENT)
        p.fillRect(QRectF(12.0, 2.0, 3.0, 4.0), col)
        p.fillRect(QRectF(12.0, 10.0, 3.0, 4.0), col)
    elif a == "add_flow":
        p.drawLine(QPointF(8.0, 3.0), QPointF(8.0, 13.0))
        p.drawLine(QPointF(3.0, 8.0), QPointF(13.0, 8.0))
    elif a in ("validate", "check"):
        # Checkmark icon
        p.setPen(_create_pen(QColor(22, 163, 74), 1.6))
        p.drawLine(QPointF(3.0, 8.5), QPointF(6.5, 12.0))
        p.drawLine(QPointF(6.5, 12.0), QPointF(13.0, 4.0))
    elif a == "search":
        p.drawEllipse(QRectF(2.5, 2.5, 8.5, 8.5))
        p.drawLine(QPointF(10.0, 10.0), QPointF(14.0, 14.0))
    elif a == "link":
        # Subscription chain used in the Result grid third column (manual p.87)
        p.drawEllipse(QRectF(1.5, 4.5, 5.5, 5.5))
        p.drawEllipse(QRectF(9.0, 4.5, 5.5, 5.5))
        p.drawLine(QPointF(5.2, 7.25), QPointF(10.8, 7.25))
    elif a == "save":
        # Floppy disk (manual p.70 "Save")
        p.drawRoundedRect(QRectF(2.0, 2.0, 12.0, 12.0), 1.2, 1.2)
        p.drawRect(QRectF(5.0, 2.0, 6.0, 5.0))
        p.drawRect(QRectF(4.5, 9.5, 7.0, 4.5))
    elif a in ("load_image", "image", "open_image"):
        # Image photo icon
        p.drawRoundedRect(QRectF(2.0, 2.5, 12.0, 11.0), 1.2, 1.2)
        p.drawEllipse(QRectF(4.0, 4.5, 2.5, 2.5))
        p.drawLine(QPointF(2.5, 11.5), QPointF(6.0, 8.0))
        p.drawLine(QPointF(6.0, 8.0), QPointF(9.5, 11.5))
        p.drawLine(QPointF(8.5, 10.5), QPointF(11.0, 8.0))
        p.drawLine(QPointF(11.0, 8.0), QPointF(13.5, 10.5))
    elif a == "open":
        # Folder (manual p.70 "Open")
        p.drawLine(QPointF(2.0, 12.5), QPointF(2.0, 4.0))
        p.drawLine(QPointF(2.0, 4.0), QPointF(6.5, 4.0))
        p.drawLine(QPointF(6.5, 4.0), QPointF(8.0, 6.0))
        p.drawLine(QPointF(8.0, 6.0), QPointF(14.0, 6.0))
        p.drawLine(QPointF(14.0, 6.0), QPointF(14.0, 12.5))
        p.drawLine(QPointF(14.0, 12.5), QPointF(2.0, 12.5))
    elif a == "undo":
        p.drawArc(QRectF(3.0, 4.5, 10.0, 8.0), 20 * 16, 250 * 16)
        p.drawLine(QPointF(3.3, 4.6), QPointF(3.6, 8.4))
        p.drawLine(QPointF(3.3, 4.6), QPointF(7.1, 4.9))
    elif a == "redo":
        p.drawArc(QRectF(3.0, 4.5, 10.0, 8.0), -90 * 16, 250 * 16)
        p.drawLine(QPointF(12.7, 4.6), QPointF(12.4, 8.4))
        p.drawLine(QPointF(12.7, 4.6), QPointF(8.9, 4.9))
    elif a == "lock":
        # Padlock (manual p.70 "Locking")
        p.drawRoundedRect(QRectF(3.0, 7.0, 10.0, 7.0), 1.2, 1.2)
        p.drawArc(QRectF(5.0, 2.0, 6.0, 7.0), 0, 180 * 16)
        p.drawLine(QPointF(5.0, 5.5), QPointF(5.0, 7.0))
        p.drawLine(QPointF(11.0, 5.5), QPointF(11.0, 7.0))
    elif a == "camera_set":
        p.drawRoundedRect(QRectF(2.0, 4.5, 10.0, 8.0), 1.2, 1.2)
        p.drawEllipse(QRectF(5.0, 6.5, 4.0, 4.0))
        p.drawLine(QPointF(12.0, 8.0), QPointF(15.0, 6.0))
        p.drawLine(QPointF(12.0, 8.0), QPointF(15.0, 10.0))
    elif a == "controller":
        # Rack of controlled axes (manual p.70 "Controller Management")
        p.drawRoundedRect(QRectF(2.0, 2.5, 12.0, 11.0), 1.2, 1.2)
        for y in (5.0, 8.0, 11.0):
            p.drawLine(QPointF(2.0, y), QPointF(14.0, y))
        p.drawLine(QPointF(4.5, 3.8), QPointF(4.5, 5.0))
        p.drawLine(QPointF(4.5, 6.8), QPointF(4.5, 8.0))
        p.drawLine(QPointF(4.5, 9.8), QPointF(4.5, 11.0))
    elif a == "global_var":
        # "var" badge (manual p.70 "Global Variable")
        p.drawRoundedRect(QRectF(1.5, 1.5, 13.0, 13.0), 1.5, 1.5)
        p.setFont(QFont("Segoe UI", 6, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 16, 16), Qt.AlignmentFlag.AlignCenter, "var")
    elif a == "communication":
        # Bidirectional bus ports (manual p.70 "Communication Management")
        p.drawRoundedRect(QRectF(2.0, 4.0, 12.0, 8.0), 1.2, 1.2)
        p.drawLine(QPointF(5.0, 8.0), QPointF(9.0, 8.0))
        p.drawLine(QPointF(7.5, 6.5), QPointF(9.0, 8.0))
        p.drawLine(QPointF(7.5, 9.5), QPointF(9.0, 8.0))
        p.drawLine(QPointF(11.0, 6.5), QPointF(11.0, 9.5))
    elif a == "trigger":
        # Event trigger lightning (manual p.70 "Global Trigger")
        path = QPainterPath()
        path.moveTo(9.0, 2.0)
        path.lineTo(4.5, 8.5)
        path.lineTo(8.0, 8.5)
        path.lineTo(6.5, 14.0)
        path.lineTo(12.0, 7.0)
        path.lineTo(8.5, 7.0)
        path.closeSubpath()
        p.drawPath(path)
    elif a == "global_script":
        # </> code script (manual p.70 "Global Script")
        p.drawRoundedRect(QRectF(1.5, 2.5, 13.0, 11.0), 1.2, 1.2)
        p.drawLine(QPointF(6.0, 6.0), QPointF(4.0, 8.0))
        p.drawLine(QPointF(4.0, 8.0), QPointF(6.0, 10.0))
        p.drawLine(QPointF(10.0, 6.0), QPointF(12.0, 8.0))
        p.drawLine(QPointF(12.0, 8.0), QPointF(10.0, 10.0))
    elif a == "operation":
        # Formatting / viewer panel (manual p.70 "Operation Interface")
        p.drawRoundedRect(QRectF(1.5, 2.5, 13.0, 11.0), 1.2, 1.2)
        p.drawLine(QPointF(6.5, 2.5), QPointF(6.5, 13.5))
        p.drawLine(QPointF(1.5, 7.0), QPointF(6.5, 7.0))
    elif a == "solution":
        # Flow-set overview (multi-flow canvas, manual p.95)
        p.drawRoundedRect(QRectF(2.0, 2.0, 5.5, 5.0), 1.0, 1.0)
        p.drawRoundedRect(QRectF(8.5, 2.0, 5.5, 5.0), 1.0, 1.0)
        p.drawRoundedRect(QRectF(2.0, 9.0, 5.5, 5.0), 1.0, 1.0)
        p.drawLine(QPointF(4.75, 7.0), QPointF(4.75, 9.0))
        p.drawLine(QPointF(11.25, 7.0), QPointF(11.25, 9.0))
        p.drawLine(QPointF(4.75, 9.0), QPointF(11.25, 9.0))
    elif a == "back":
        p.drawLine(QPointF(13.0, 8.0), QPointF(3.5, 8.0))
        p.drawLine(QPointF(7.0, 4.5), QPointF(3.5, 8.0))
        p.drawLine(QPointF(7.0, 11.5), QPointF(3.5, 8.0))
    elif a in ("settings", "config", "gear"):
        # Gear / settings icon
        p.drawEllipse(QRectF(5.0, 5.0, 6.0, 6.0))
        p.drawLine(QPointF(8.0, 1.5), QPointF(8.0, 4.0))
        p.drawLine(QPointF(8.0, 12.0), QPointF(8.0, 14.5))
        p.drawLine(QPointF(1.5, 8.0), QPointF(4.0, 8.0))
        p.drawLine(QPointF(12.0, 8.0), QPointF(14.5, 8.0))
    elif a in ("start_page", "home", "welcome"):
        # Home / Start page house icon
        path = QPainterPath()
        path.moveTo(8.0, 2.5)
        path.lineTo(13.5, 7.5)
        path.lineTo(12.0, 7.5)
        path.lineTo(12.0, 13.5)
        path.lineTo(4.0, 13.5)
        path.lineTo(4.0, 7.5)
        path.lineTo(2.5, 7.5)
        path.closeSubpath()
        p.drawPath(path)
        p.drawRect(QRectF(6.5, 9.0, 3.0, 4.5))
    else:
        p.drawRoundedRect(QRectF(3.0, 3.0, 10.0, 10.0), 1.5, 1.5)

    p.end()
    return QIcon(pix)


# Convenient alias
get_vector_icon = get_action_icon

