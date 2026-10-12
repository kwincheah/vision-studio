"""Multi-Flow overview canvas (manual p.95 "Multi-Flow").

The reference is a schematic overview of a whole solution: one white rounded
card per sub-flow showing a title, play / continuous / formatting buttons, the
execution count and the last measured cycle time, plus orange dependency wires
converging on the trigger flow.  This module reproduces that screen with real
``QGraphicsItem`` cards so the overview is interactive (select a flow, run a
flow, drag cards) rather than a static picture.
"""
from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, QPointF, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QPainterPath
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QMenu, QWidget, QVBoxLayout,
    QHBoxLayout, QToolButton, QLabel, QSizePolicy
)

from vm_clone.core.base_tool import ToolStatus
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.ui.styles import THEME


class FlowOverviewSignals(QObject):
    flow_activated = pyqtSignal(str)      # flow name - open in the flow editor
    flow_run_requested = pyqtSignal(str)  # flow name - execute once
    flow_loop_toggled = pyqtSignal(str, bool)
    flow_settings_requested = pyqtSignal(str)


class FlowCardItem(QGraphicsItem):
    """White flow card with playback controls (manual p.95)."""

    WIDTH = 184
    HEIGHT = 106
    HEADER_H = 27

    def __init__(self, flow: VisionPipeline, is_trigger: bool, signals: FlowOverviewSignals):
        super().__init__()
        self.flow = flow
        self.is_trigger = is_trigger
        self.signals = signals
        self.looping = False
        self.hovered_button: Optional[str] = None
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self) -> QRectF:
        return QRectF(-6, -6, self.WIDTH + 12, self.HEIGHT + 14)

    # Button layout shared by paint + hit testing.
    def _buttons(self) -> Dict[str, QRectF]:
        y = self.HEADER_H + 6
        return {
            "play": QRectF(12, y, 24, 24),
            "loop": QRectF(42, y, 24, 24),
            "format": QRectF(self.WIDTH - 36, y, 24, 24),
        }

    def _status_text(self) -> str:
        if not self.flow.last_results:
            return "Not executed"
        ok = all(r.status != ToolStatus.NG for r in self.flow.last_results.values())
        return "PASS" if ok else "FAIL"

    def _status_color(self) -> QColor:
        if not self.flow.last_results:
            return QColor("#8b9096")
        ok = all(r.status != ToolStatus.NG for r in self.flow.last_results.values())
        return QColor(THEME["status_ok_text"] if ok else THEME["status_error_text"])

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        card = QRectF(0, 0, self.WIDTH, self.HEIGHT)

        painter.setPen(QPen(QColor(0, 0, 0, 50), 4.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card.adjusted(1.5, 3.0, 1.5, 3.0), 6, 6)

        if self.isSelected():
            painter.setPen(QPen(QColor(THEME["vm_accent"]), 2.0))
        elif self.is_trigger:
            painter.setPen(QPen(QColor(THEME["vm_accent"]), 1.6))
        else:
            painter.setPen(QPen(QColor(THEME["vm_node_border"]), 1.2))
        painter.setBrush(QColor(THEME["vm_card"]))
        painter.drawRoundedRect(card, 5, 5)

        # Header strip
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#242c3b"))
        painter.drawRoundedRect(QRectF(0.6, 0.6, self.WIDTH - 1.2, self.HEADER_H), 5, 5)
        painter.drawRect(QRectF(0.6, self.HEADER_H - 8, self.WIDTH - 1.2, 8))
        painter.setPen(QPen(QColor("#2b3547"), 1.0))
        painter.drawLine(QPointF(0, self.HEADER_H), QPointF(self.WIDTH, self.HEADER_H))

        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.setPen(QColor(THEME["vm_node_text"]))
        painter.drawText(QRectF(9, 0, self.WIDTH - 46, self.HEADER_H),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.flow.name)

        # Header glyphs: overview + delete
        painter.setPen(QPen(QColor("#94a3b8"), 1.3))
        painter.drawRect(QRectF(self.WIDTH - 38, 7, 9, 10))
        painter.drawLine(QPointF(self.WIDTH - 35, 5), QPointF(self.WIDTH - 32, 5))
        painter.drawLine(QPointF(self.WIDTH - 32, 5), QPointF(self.WIDTH - 32, 7))
        painter.drawRect(QRectF(self.WIDTH - 22, 7, 9, 10))
        painter.drawLine(QPointF(self.WIDTH - 19, 5), QPointF(self.WIDTH - 16, 5))
        painter.drawLine(QPointF(self.WIDTH - 16, 5), QPointF(self.WIDTH - 16, 7))

        # Playback controls
        for key, rect in self._buttons().items():
            active = self.hovered_button == key
            if key == "loop" and self.looping:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(THEME["vm_accent"]))
                painter.drawRoundedRect(rect, 4, 4)
                glyph = QColor("#ffffff")
            else:
                painter.setPen(QPen(QColor("#38455a"), 1.1))
                painter.setBrush(QColor("#273244") if active else QColor("#1c2330"))
                painter.drawEllipse(rect)
                glyph = QColor(THEME["vm_accent"]) if active else QColor("#94a3b8")

            painter.setPen(QPen(glyph, 1.5))
            cx = rect.center().x()
            cy = rect.center().y()
            if key == "play":
                path = QPainterPath()
                path.moveTo(cx - 3.5, cy - 5.0)
                path.lineTo(cx + 5.0, cy)
                path.lineTo(cx - 3.5, cy + 5.0)
                path.closeSubpath()
                painter.setBrush(QBrush(glyph))
                painter.drawPath(path)
            elif key == "loop":
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawArc(QRectF(cx - 5.5, cy - 5.5, 11, 11), 40 * 16, 280 * 16)
                painter.drawLine(QPointF(cx + 4.0, cy - 5.5), QPointF(cx + 5.5, cy - 1.5))
                painter.drawLine(QPointF(cx + 4.0, cy - 5.5), QPointF(cx + 0.4, cy - 5.6))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(cx - 6, cy - 5, 12, 10), 1.5, 1.5)
                painter.drawLine(QPointF(cx - 2.5, cy + 1.5), QPointF(cx + 1.5, cy - 3.0))
                painter.drawLine(QPointF(cx - 0.5, cy - 4.0), QPointF(cx + 2.0, cy - 4.0))
                painter.drawLine(QPointF(cx + 2.0, cy - 4.0), QPointF(cx + 2.0, cy - 1.5))

        # Divider below the buttons
        painter.setPen(QPen(QColor("#2b3547"), 1.0))
        painter.drawLine(QPointF(9, self.HEADER_H + 34), QPointF(self.WIDTH - 9, self.HEADER_H + 34))

        # Statistics block
        runs = getattr(self.flow, "execution_count", 0)
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(QColor(THEME["vm_node_text_dim"]))
        painter.drawText(QRectF(12, self.HEADER_H + 40, 90, 16),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{runs}Times")

        painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        painter.setPen(QColor(THEME["vm_node_text"]))
        painter.drawText(QRectF(12, self.HEADER_H + 58, 104, 16),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         f"{self.flow.last_flow_time_ms:.2f}ms")

        # Run/result toggle (slider)
        slider = QRectF(self.WIDTH - 66, self.HEADER_H + 46, 36, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#242c3b"))
        painter.drawRoundedRect(slider, 8, 8)
        if self.flow.enabled:
            painter.setBrush(QColor(THEME["vm_accent"]))
            painter.drawRoundedRect(QRectF(slider.left(), slider.top(), 18, 16), 8, 8)
            painter.setBrush(QColor(THEME["vm_accent_hover"]))
            knob_x = slider.right() - 8
        else:
            painter.setBrush(QColor("#ffffff"))
            knob_x = slider.left() + 8
        painter.drawEllipse(QPointF(knob_x, slider.center().y()), 6.5, 6.5)

        # Status footer
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(self._status_color())
        painter.drawText(QRectF(self.WIDTH - 76, self.HEADER_H + 62, 66, 14),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._status_text())

    # ------------------------------------------------------------ interaction
    def _button_at(self, pos) -> Optional[str]:
        point = QPointF(pos) if not isinstance(pos, QPointF) else pos
        for key, rect in self._buttons().items():
            if rect.contains(point):
                return key
        return None

    def hoverMoveEvent(self, event):
        btn = self._button_at(event.pos())
        if btn != self.hovered_button:
            self.hovered_button = btn
            self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered_button = None
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        btn = self._button_at(event.pos())
        if btn and event.button() == Qt.MouseButton.LeftButton:
            if btn == "play":
                self.signals.flow_run_requested.emit(self.flow.name)
            elif btn == "loop":
                self.looping = not self.looping
                self.signals.flow_loop_toggled.emit(self.flow.name, self.looping)
                self.update()
            elif btn == "format":
                self.signals.flow_settings_requested.emit(self.flow.name)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.signals.flow_activated.emit(self.flow.name)
        event.accept()

    def contextMenuEvent(self, event):
        menu = QMenu()
        act_open = menu.addAction(f"Open '{self.flow.name}' in Flow Editor")
        act_run = menu.addAction("Execute Flow Once")
        menu.addSeparator()
        act_enable = menu.addAction("Disable Flow" if self.flow.enabled else "Enable Flow")
        chosen = menu.exec(event.screenPos())
        if chosen == act_open:
            self.signals.flow_activated.emit(self.flow.name)
        elif chosen == act_run:
            self.signals.flow_run_requested.emit(self.flow.name)
        elif chosen == act_enable:
            self.flow.enabled = not self.flow.enabled
            self.update()


class FlowOverviewScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(QColor(THEME["vm_canvas"])))
        self.card_items: Dict[str, FlowCardItem] = {}
        self.trigger_name: Optional[str] = None

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QColor(THEME["vm_canvas"]))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        grid = 20
        left = int(rect.left()) - (int(rect.left()) % grid)
        top = int(rect.top()) - (int(rect.top()) % grid)
        painter.setPen(QPen(QColor(THEME["vm_canvas_dot"])))
        for x in range(left, int(rect.right()) + grid, grid):
            for y in range(top, int(rect.bottom()) + grid, grid):
                painter.drawPoint(x, y)

    def rebuild(self, flows: Dict[str, VisionPipeline], trigger_name: str,
                signals: FlowOverviewSignals, positions: Optional[Dict[str, QPointF]] = None):
        saved = positions if positions is not None else {
            name: item.pos() for name, item in self.card_items.items()
        }
        self.clear()
        self.card_items.clear()
        self.trigger_name = trigger_name

        names: List[str] = list(flows.keys())
        trigger = trigger_name if trigger_name in flows else (names[0] if names else None)
        others = [n for n in names if n != trigger]

        # Producers fan out on the first rows, the trigger flow sits centred
        # below them so the dependency wires converge (manual p.95).
        cols = 4
        row_h = 142
        col_w = 204
        for i, name in enumerate(others):
            default = QPointF(60 + (i % cols) * col_w, 46 + (i // cols) * row_h)
            card = FlowCardItem(flows[name], is_trigger=False, signals=signals)
            card.setPos(saved.get(name, default))
            self.addItem(card)
            self.card_items[name] = card

        rows_used = (len(others) + cols - 1) // cols
        default_trigger = QPointF(
            60 + max(0, min(cols - 1, len(others) // 2)) * col_w,
            46 + max(1, rows_used) * row_h,
        )
        tcard = FlowCardItem(flows[trigger], is_trigger=True, signals=signals) if trigger else None
        if tcard is not None:
            tcard.setPos(saved.get(trigger, default_trigger))
            self.addItem(tcard)
            self.card_items[trigger] = tcard

        self._build_wires(trigger)
        self.setSceneRect(self.itemsBoundingRect().adjusted(-60, -60, 60, 60))

    def _build_wires(self, trigger: Optional[str]):
        """Orange orthogonal dependency wires converging on the trigger flow."""
        if not trigger or trigger not in self.card_items:
            return
        t_card = self.card_items[trigger]
        t_top = t_card.pos() + QPointF(FlowCardItem.WIDTH / 2.0, 0)

        for name, card in self.card_items.items():
            if name == trigger:
                continue
            start = card.pos() + QPointF(FlowCardItem.WIDTH / 2.0, FlowCardItem.HEIGHT)
            path = QPainterPath()
            path.moveTo(start)
            bus_y = max(start.y(), t_top.y()) + 26
            path.lineTo(start.x(), bus_y)
            path.lineTo(t_top.x(), bus_y)
            path.lineTo(t_top.x(), t_top.y())

            item = self.addPath(
                path, QPen(QColor(THEME["vm_wire"]), 2.0, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            )
            item.setZValue(-2)
            item.setToolTip(f"{name} -> {trigger}")

            head = QPainterPath()
            head.moveTo(t_top)
            head.lineTo(t_top.x() - 5, t_top.y() - 8)
            head.lineTo(t_top.x() + 5, t_top.y() - 8)
            head.closeSubpath()
            arrow = self.addPath(head, QPen(Qt.PenStyle.NoPen), QBrush(QColor(THEME["vm_wire"])))
            arrow.setZValue(-1)

    def run_counts(self) -> Dict[str, int]:
        return {name: getattr(card.flow, "execution_count", 0) for name, card in self.card_items.items()}


class FlowOverviewWidget(QWidget):
    """Overview tab: toolbar + scene + hint, matching the multi-flow screen."""

    flow_activated = pyqtSignal(str)
    flow_run_requested = pyqtSignal(str)
    flow_loop_toggled = pyqtSignal(str, bool)
    flow_settings_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = FlowOverviewSignals()
        self.signals.flow_activated.connect(self.flow_activated)
        self.signals.flow_run_requested.connect(self.flow_run_requested)
        self.signals.flow_loop_toggled.connect(self.flow_loop_toggled)
        self.signals.flow_settings_requested.connect(self.flow_settings_requested)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setStyleSheet(f"background-color: {THEME['vm_panel_header']};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 5, 8, 5)
        bar_layout.setSpacing(8)
        title = QLabel("Solution Flows")
        title.setStyleSheet("font-weight: 600; color: #d5d8dd;")
        bar_layout.addWidget(title)
        self.lbl_hint = QLabel("Double-click a flow card to edit it, or use its play button to execute a single flow.")
        self.lbl_hint.setStyleSheet("color: #9ba0a7; font-size: 12px;")
        bar_layout.addWidget(self.lbl_hint)
        bar_layout.addStretch(1)
        root.addWidget(bar)

        self.scene = FlowOverviewScene()
        self.scene.setSceneRect(0, 0, 900, 520)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.view.setStyleSheet("background: transparent;")
        root.addWidget(self.view, 1)

        self._flows: Dict[str, VisionPipeline] = {}
        self._trigger = ""

    def rebuild(self, flows: Dict[str, VisionPipeline], trigger_name: str):
        self._flows = flows
        self._trigger = trigger_name
        self.scene.rebuild(flows, trigger_name, self.signals)

    def refresh_status(self):
        for card in self.scene.card_items.values():
            card.update()

    def reset_layout(self):
        self.scene.rebuild(self._flows, self._trigger, self.signals, positions={})
        self.view.fitInView(
            self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40),
            Qt.AspectRatioMode.KeepAspectRatio
        )
