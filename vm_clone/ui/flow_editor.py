"""
Engineering Flow Graph Editor.
Professional machine vision block diagram:
- Clean matte rectangular nodes with discrete status badge
- Crisp high-contrast port pins with hit testing
- Interactive drag-to-connect bezier wires with release target resolution
- Selectable and deletable connection wires
- Smooth mouse-wheel zoom and middle/right click pan
- Drag-and-drop tool instantiation from Tool Library
- Topological hierarchical node auto-layout preserving manual arrangements
"""
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsRectItem,
    QGraphicsPathItem, QMenu, QMessageBox, QWidget, QHBoxLayout, QLabel,
    QToolButton
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QPainterPath,
    QPainterPathStroker, QUndoStack, QUndoCommand
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QPoint, pyqtSignal, QObject
import math
from typing import Dict, List, Optional
from vm_clone.core.base_tool import VisionToolBase, ToolStatus
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.ui.styles import THEME
from vm_clone.ui.icons import get_tool_icon


class NodeSignals(QObject):
    node_selected = pyqtSignal(str)   # instance_id
    node_deleted = pyqtSignal(str)    # instance_id
    connection_added = pyqtSignal(str, str, str, str)  # from_node, from_port, to_node, to_port
    connection_rejected = pyqtSignal(str)              # reason
    run_single_tool = pyqtSignal(str) # instance_id
    tool_dropped = pyqtSignal(str, float, float)       # tool_name, scene_x, scene_y
    validation_requested = pyqtSignal()
    configure_module = pyqtSignal(str)                 # instance_id


# =============================================================================
# Undo / Redo Commands for Flow Diagram Editing
# =============================================================================
def _rebuild_scene(scene: "FlowScene"):
    """Rebuild the scene even while locking protection is engaged.

    Undo/redo is an explicit operator action, so it must be able to refresh the
    view even though ``build_from_pipeline`` is gated by the lock.
    """
    was_locked = scene.is_locked()
    if was_locked:
        scene.set_locked(False)
    scene.build_from_pipeline(preserve_positions=True)
    if was_locked:
        scene.set_locked(True)


class AddConnectionCommand(QUndoCommand):
    def __init__(self, scene: "FlowScene", from_node: str, from_port: str, to_node: str, to_port: str):
        super().__init__(f"Connect {from_port} -> {to_port}")
        self.scene = scene
        self.from_node = from_node
        self.from_port = from_port
        self.to_node = to_node
        self.to_port = to_port

    def redo(self):
        self.scene.pipeline.connect(self.from_node, self.from_port, self.to_node, self.to_port, force=True)
        _rebuild_scene(self.scene)

    def undo(self):
        self.scene.pipeline.disconnect(self.to_node, self.to_port)
        _rebuild_scene(self.scene)


class DeleteConnectionCommand(QUndoCommand):
    def __init__(self, scene: "FlowScene", from_node: str, from_port: str, to_node: str, to_port: str):
        super().__init__(f"Disconnect {from_port} -> {to_port}")
        self.scene = scene
        self.from_node = from_node
        self.from_port = from_port
        self.to_node = to_node
        self.to_port = to_port

    def redo(self):
        self.scene.pipeline.disconnect(self.to_node, self.to_port)
        _rebuild_scene(self.scene)

    def undo(self):
        self.scene.pipeline.connect(self.from_node, self.from_port, self.to_node, self.to_port, force=True)
        _rebuild_scene(self.scene)


class AddNodeCommand(QUndoCommand):
    def __init__(self, scene: "FlowScene", tool: VisionToolBase, pos: QPointF):
        super().__init__(f"Add Module {tool.name}")
        self.scene = scene
        self.tool = tool
        self.pos = pos

    def redo(self):
        self.scene.pipeline.add_node(self.tool)
        _rebuild_scene(self.scene)
        if self.tool.instance_id in self.scene.node_items:
            self.scene.node_items[self.tool.instance_id].setPos(self.pos)
            self.scene.update_connections()
        if self.scene.signals:
            self.scene.signals.node_selected.emit(self.tool.instance_id)

    def undo(self):
        self.scene.pipeline.remove_node(self.tool.instance_id)
        _rebuild_scene(self.scene)


class DeleteNodeCommand(QUndoCommand):
    def __init__(self, scene: "FlowScene", instance_id: str):
        tool = scene.pipeline.nodes.get(instance_id)
        super().__init__(f"Delete Module {tool.name if tool else instance_id}")
        self.scene = scene
        self.instance_id = instance_id
        self.tool = tool
        self.pos = scene.node_items[instance_id].pos() if instance_id in scene.node_items else QPointF(50, 50)
        self.connections = [
            (c.from_node, c.from_port, c.to_node, c.to_port)
            for c in scene.pipeline.connections
            if c.from_node == instance_id or c.to_node == instance_id
        ]

    def redo(self):
        self.scene.pipeline.remove_node(self.instance_id)
        _rebuild_scene(self.scene)
        if self.scene.signals:
            self.scene.signals.node_deleted.emit(self.instance_id)

    def undo(self):
        if self.tool:
            self.scene.pipeline.add_node(self.tool)
            for fn, fp, tn, tp in self.connections:
                self.scene.pipeline.connect(fn, fp, tn, tp, force=True)
            _rebuild_scene(self.scene)
            if self.instance_id in self.scene.node_items:
                self.scene.node_items[self.instance_id].setPos(self.pos)
                self.scene.update_connections()


class MoveNodeCommand(QUndoCommand):
    def __init__(self, scene: "FlowScene", instance_id: str, old_pos: QPointF, new_pos: QPointF):
        super().__init__("Move Module")
        self.scene = scene
        self.instance_id = instance_id
        self.old_pos = old_pos
        self.new_pos = new_pos

    def redo(self):
        if self.instance_id in self.scene.node_items:
            self.scene.node_items[self.instance_id].setPos(self.new_pos)
            self.scene.update_connections()

    def undo(self):
        if self.instance_id in self.scene.node_items:
            self.scene.node_items[self.instance_id].setPos(self.old_pos)
            self.scene.update_connections()


class PortItem(QGraphicsRectItem):
    PORT_SIZE = 9

    def __init__(self, node_item, port_name: str, is_output: bool, data_type: str):
        super().__init__(-self.PORT_SIZE / 2, -self.PORT_SIZE / 2, self.PORT_SIZE, self.PORT_SIZE)
        self.node_item = node_item
        self.port_name = port_name
        self.is_output = is_output
        self.data_type = data_type
        self._hovered = False

        # Color port by type using standard functional colors
        if data_type == "Image":
            self.base_color = QColor("#3b82f6")      # Blue (image stream)
        elif data_type in ("Value", "Point", "Circle", "Line", "Region"):
            self.base_color = QColor("#f59e0b")      # Amber (geometry / numeric)
        elif data_type == "Boolean":
            self.base_color = QColor("#a855f7")      # Purple (verdict logic)
        elif data_type == "String":
            base = QColor("#14b8a6")                 # Teal (text)
            self.base_color = base
        else:
            self.base_color = QColor("#22c55e")      # Green (generic)

        self.setBrush(QBrush(self.base_color))
        self.setPen(QPen(QColor("#ffffff"), 1.0))
        self.setZValue(3)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(f"{port_name} [{data_type}] - {'Output' if is_output else 'Input'}")

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def boundingRect(self) -> QRectF:
        # Generous hit area so precision wiring is comfortable at any zoom.
        grow = 3.0 if not self._hovered else 5.0
        return QRectF(
            -self.PORT_SIZE / 2 - grow, -self.PORT_SIZE / 2 - grow,
            self.PORT_SIZE + grow * 2, self.PORT_SIZE + grow * 2
        )

    def get_center_scene_pos(self) -> QPointF:
        return self.scenePos()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = float(self.PORT_SIZE)
        rect = QRectF(-s / 2.0, -s / 2.0, s, s)

        # Subtle dark border
        border_col = QColor(20, 24, 30, 200)
        fill_col = self.base_color.lighter(135) if self._hovered else self.base_color

        painter.setPen(QPen(border_col, 1.2))
        painter.setBrush(QBrush(fill_col))
        painter.drawRoundedRect(rect, 2.0, 2.0)

        # Center highlight / pin dot
        core_rect = rect.adjusted(2.0, 2.0, -2.0, -2.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 230 if self._hovered else 170)))
        painter.drawRoundedRect(core_rect, 1.0, 1.0)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene = self.scene()
            if isinstance(scene, FlowScene):
                scene.start_connection_drag(self)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        scene = self.scene()
        if isinstance(scene, FlowScene) and scene.is_dragging_connection():
            scene.finish_connection_drag_at_pos(event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ConnectionItem(QGraphicsPathItem):
    """Module dependency wire.

    Rendered in the VisionMaster language: orthogonal routed wire with smooth
    rounded corners (fillets), collision-avoiding gutters for backward / wrapped
    links, and an arrowhead at the target port accurately aligned with the
    incoming arrival vector.
    """
    PORT_CLEARANCE = 24.0
    FILLET_RADIUS = 8.0
    ARROW_LEN = 7.5
    ARROW_WIDTH = 7.0

    def __init__(self, from_port: PortItem, to_port: PortItem):
        super().__init__()
        self.from_port = from_port
        self.to_port = to_port
        self._waypoints: List[QPointF] = []
        self.setZValue(-1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._hovered = False
        self.update_path()

    @staticmethod
    def _build_filleted_path(points: List[QPointF], radius: float = 8.0) -> QPainterPath:
        path = QPainterPath()
        if not points:
            return path
        if len(points) < 3:
            path.moveTo(points[0])
            for pt in points[1:]:
                path.lineTo(pt)
            return path

        path.moveTo(points[0])
        for i in range(1, len(points) - 1):
            p_prev = points[i - 1]
            p_curr = points[i]
            p_next = points[i + 1]

            v_in = p_curr - p_prev
            v_out = p_next - p_curr
            len_in = math.hypot(v_in.x(), v_in.y())
            len_out = math.hypot(v_out.x(), v_out.y())

            if len_in < 1e-3 or len_out < 1e-3:
                path.lineTo(p_curr)
                continue

            u_in = QPointF(v_in.x() / len_in, v_in.y() / len_in)
            u_out = QPointF(v_out.x() / len_out, v_out.y() / len_out)

            # Cap fillet radius to less than half of either adjacent segment
            r = min(radius, len_in * 0.45, len_out * 0.45)
            p_start_corner = p_curr - u_in * r
            p_end_corner = p_curr + u_out * r

            path.lineTo(p_start_corner)
            path.quadTo(p_curr, p_end_corner)

        path.lineTo(points[-1])
        return path

    def _compute_waypoints(self, p1: QPointF, p2: QPointF, from_node=None, to_node=None) -> List[QPointF]:
        clr = self.PORT_CLEARANCE
        p1_exit_x = p1.x() + clr
        p2_entry_x = p2.x() - clr

        # Case 1: Forward connection with sufficient horizontal gap
        if p2_entry_x >= p1_exit_x:
            if abs(p2.y() - p1.y()) < 2.0:
                # Straight horizontal connection
                return [p1, p2]
            else:
                mid_x = (p1.x() + p2.x()) * 0.5
                mid_x = max(p1_exit_x, min(p2_entry_x, mid_x))
                return [
                    p1,
                    QPointF(mid_x, p1.y()),
                    QPointF(mid_x, p2.y()),
                    p2
                ]

        # Case 2: Backward, wrapped, or overlapping placement (p2.x < p1.x + 2*clr)
        # Route through the inter-column and inter-row gutters to avoid cutting cards
        if from_node and to_node:
            fn_pos = from_node.scenePos()
            tn_pos = to_node.scenePos()
            fn_w = getattr(from_node, "WIDTH", 176.0)
            fn_h = getattr(from_node, "height", 80.0)
            tn_w = getattr(to_node, "WIDTH", 176.0)
            tn_h = getattr(to_node, "height", 80.0)

            x_right = max(p1.x() + clr, fn_pos.x() + fn_w + 16.0)
            x_left = min(p2.x() - clr, tn_pos.x() - 16.0)

            if tn_pos.y() >= fn_pos.y() + fn_h:
                # Destination is below source
                y_mid = (fn_pos.y() + fn_h + tn_pos.y()) * 0.5
            elif fn_pos.y() >= tn_pos.y() + tn_h:
                # Destination is above source
                y_mid = (tn_pos.y() + tn_h + fn_pos.y()) * 0.5
            else:
                # Overlapping vertically: route around the bottom of both nodes
                y_mid = max(fn_pos.y() + fn_h, tn_pos.y() + tn_h) + 18.0

            return [
                p1,
                QPointF(x_right, p1.y()),
                QPointF(x_right, y_mid),
                QPointF(x_left, y_mid),
                QPointF(x_left, p2.y()),
                p2
            ]

        # Fallback if node items not found
        mid_y = p1.y() + (p2.y() - p1.y()) * 0.5
        return [
            p1,
            QPointF(p1_exit_x, p1.y()),
            QPointF(p1_exit_x, mid_y),
            QPointF(p2_entry_x, mid_y),
            QPointF(p2_entry_x, p2.y()),
            p2
        ]

    def update_path(self):
        p1 = self.from_port.get_center_scene_pos()
        p2 = self.to_port.get_center_scene_pos()

        from_node = getattr(self.from_port, "node_item", None)
        to_node = getattr(self.to_port, "node_item", None)

        self._waypoints = self._compute_waypoints(p1, p2, from_node, to_node)
        path = self._build_filleted_path(self._waypoints, self.FILLET_RADIUS)
        self.setPath(path)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12.0)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stroke = stroker.createStroke(self.path())
        stroke.addPath(self._arrow_head())
        return stroke

    def _arrow_head(self) -> QPainterPath:
        p2 = self.to_port.get_center_scene_pos()
        if hasattr(self, "_waypoints") and len(self._waypoints) >= 2:
            p_prev = self._waypoints[-2]
            dx = p2.x() - p_prev.x()
            dy = p2.y() - p_prev.y()
            length = math.hypot(dx, dy)
            if length > 1e-3:
                direction = QPointF(dx / length, dy / length)
            else:
                direction = QPointF(1.0, 0.0)
        else:
            direction = QPointF(1.0, 0.0)

        # Tip touches the edge of the destination port pin
        tip = QPointF(p2.x() - 1.0, p2.y()) if direction.x() > 0.5 else p2
        back = tip - direction * self.ARROW_LEN
        perp = QPointF(-direction.y(), direction.x())
        half = self.ARROW_WIDTH * 0.5

        head = QPainterPath()
        head.moveTo(tip)
        head.lineTo(back + perp * half)
        # Slight notch for sleek industrial arrowhead
        notch = back + direction * 1.5
        head.lineTo(notch)
        head.lineTo(back - perp * half)
        head.closeSubpath()
        return head

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        dtype = self.from_port.data_type
        if dtype == "Image":
            base_col = QColor(THEME["accent_primary"]) if self.isSelected() else QColor("#3b82f6")
        elif dtype in ("Value", "Point", "Circle", "Line", "Region"):
            base_col = QColor(THEME["vm_accent_hover"]) if self.isSelected() else QColor("#f59e0b")
        elif dtype == "Boolean":
            base_col = QColor("#c084fc") if self.isSelected() else QColor("#a855f7")
        else:
            base_col = QColor(THEME["vm_accent_hover"]) if self.isSelected() else QColor(THEME["vm_wire"])

        wire_col = base_col
        if self._hovered:
            wire_col = wire_col.lighter(130)

        width = 2.4 if self.isSelected() else (2.2 if self._hovered else 1.8)
        style = Qt.PenStyle.DashLine if self.isSelected() else Qt.PenStyle.SolidLine

        # Outer soft contrast halo
        halo_width = width + 2.4
        halo_col = QColor(10, 12, 16, 95)
        halo = QPen(halo_col, halo_width)
        halo.setCapStyle(Qt.PenCapStyle.RoundCap)
        halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(halo)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())

        # Main wire stroke
        pen = QPen(wire_col, width, style)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(self.path())

        # Arrowhead at destination port
        head_path = self._arrow_head()
        painter.setPen(QPen(halo_col, 1.2))
        painter.setBrush(QBrush(wire_col))
        painter.drawPath(head_path)

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        del_act = menu.addAction("Delete Connection Wire")
        action = menu.exec(event.screenPos())
        if action == del_act:
            scene = self.scene()
            if isinstance(scene, FlowScene):
                scene.remove_connection_item(self)


class FlowNodeItem(QGraphicsItem):
    """VisionMaster module card (manual p.74 / p.95).

    White rounded card with a category icon in the top-right corner, the module
    display name (the numeric ``NN_`` execution index is picked out in the
    functional orange accent exactly as in the reference), a per-port list, and
    a latency footer.  The card border carries the execution state so the whole
    flow reads at a glance: idle grey, running blue, PASS green, FAIL red.
    """
    WIDTH = 202
    #: Measured from the reference cards (`ui_crops/card_zoom.png`): the vendor
    #: module is a white rounded pill whose width is set by the module name, with
    #: a green capsule badge carrying the category glyph on the left edge.  Port
    #: rows are packed at a 14 px pitch and the state is a thin accent strip.
    WIDTH = 176
    HEADER_H = 26
    PORT_ROW_H = 14
    FOOTER_H = 15

    def __init__(self, tool: VisionToolBase, signals: NodeSignals, pos: QPointF = QPointF(100, 100)):
        super().__init__()
        self.tool = tool
        self.signals = signals
        self.setPos(pos)
        self._press_pos: QPointF = pos
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )

        self.in_ports: Dict[str, PortItem] = {}
        self.out_ports: Dict[str, PortItem] = {}
        self.status = ToolStatus.READY
        self.elapsed_ms = 0.0

        port_count = max(len(tool.inputs), len(tool.outputs), 1)
        self.height = self.HEADER_H + port_count * self.PORT_ROW_H + self.FOOTER_H

        self._init_ui()

    # -- geometry helpers ---------------------------------------------------
    def _port_label_rects(self):
        """Return (left_rect, right_rect) used to clip port label painting."""
        top = self.HEADER_H + 1
        bottom = self.height - self.FOOTER_H
        half = self.WIDTH / 2.0
        left = QRectF(9, top, half - 11, bottom - top)
        right = QRectF(half + 2, top, half - 11, bottom - top)
        return left, right

    def _init_ui(self):
        y_offset = self.HEADER_H + self.PORT_ROW_H / 2.0
        for port_name, port in self.tool.inputs.items():
            p_item = PortItem(self, port_name, is_output=False, data_type=port.data_type.value)
            p_item.setParentItem(self)
            p_item.setPos(0, y_offset)
            self.in_ports[port_name] = p_item
            y_offset += self.PORT_ROW_H

        y_offset = self.HEADER_H + self.PORT_ROW_H / 2.0
        for port_name, port in self.tool.outputs.items():
            p_item = PortItem(self, port_name, is_output=True, data_type=port.data_type.value)
            p_item.setParentItem(self)
            p_item.setPos(self.WIDTH, y_offset)
            self.out_ports[port_name] = p_item
            y_offset += self.PORT_ROW_H

    def boundingRect(self) -> QRectF:
        return QRectF(-8, -8, self.WIDTH + 16, self.height + 20)

    def _status_style(self):
        if not self.tool.enabled:
            return QColor("#9aa0a6"), "BYPASS"
        if self.status == ToolStatus.OK:
            return QColor("#22c55e"), "PASS"
        if self.status == ToolStatus.NG:
            return QColor("#ef4444"), "FAIL"
        if self.status == ToolStatus.RUNNING:
            return QColor("#38bdf8"), "RUN"
        if self.status == ToolStatus.TIMEOUT:
            return QColor("#f59e0b"), "TIME"
        if self.status == ToolStatus.ERROR:
            return QColor("#ef4444"), "ERR"
        return QColor("#b9bec6"), "IDLE"

    def paint(self, painter: QPainter, option, widget=None):
        """Paint the module card in the reference's pill style.

        Measured from `docs/references/external/ui_crops/card_zoom.png`: a white
        rounded pill with a green capsule badge on the left edge holding the
        category glyph, the ``index name`` text beside it, the port names on the
        left/right edges, and a thin accent strip on the right carrying the
        execution state.  Selection is the orange border.
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        st_col, st_text = self._status_style()
        radius = min(10.0, self.HEADER_H / 2.0)
        card = QRectF(0, 0, self.WIDTH, self.height)

        # --- ambient drop shadow for elevated dark workstation cards ---------
        painter.setPen(QPen(QColor(0, 0, 0, 90), 3.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card.adjusted(1.2, 2.0, 1.2, 2.0), radius, radius)

        # --- card body: border colour is the primary state channel -----------
        painter.setBrush(QColor(THEME["vm_node"]))
        if self.isSelected():
            border_col, border_w = QColor(THEME["vm_accent"]), 2.0
        elif not self.tool.enabled:
            border_col, border_w = QColor("#475569"), 1.2
        elif self.status == ToolStatus.READY:
            border_col, border_w = QColor(THEME["vm_node_border"]), 1.2
        else:
            border_col, border_w = st_col, 1.5
        painter.setPen(QPen(border_col, border_w))
        painter.drawRoundedRect(card, radius, radius)

        # --- subtle header banner for elevated dark workstation cards --------
        painter.save()
        painter.setClipPath(self._card_clip_path(card, radius))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#242c3b"))
        painter.drawRect(QRectF(0, 0, self.WIDTH, self.HEADER_H))
        painter.restore()

        # --- state strip on the left edge (under the badge) -------------------
        if self.status != ToolStatus.READY or not self.tool.enabled:
            painter.save()
            painter.setClipPath(self._card_clip_path(card, radius))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(st_col)
            painter.drawRect(QRectF(0, 0, 3.0, self.height))
            painter.restore()

        # --- integrated hardware badge straddling the left edge --------------
        badge_h = min(18.0, self.HEADER_H - 5.0)
        badge_w = badge_h + 7.0
        badge = QRectF(-badge_w / 2.0 + 1.0, (self.HEADER_H - badge_h) / 2.0,
                       badge_w, badge_h)
        badge_border = QColor(THEME["vm_accent"]) if self.isSelected() else QColor("#334155")
        badge_bg = QColor(THEME["vm_accent_dim"]) if self.isSelected() else QColor("#141a24")
        painter.setPen(QPen(badge_border, 1.2))
        painter.setBrush(badge_bg)
        painter.drawRoundedRect(badge, badge_h / 2.0, badge_h / 2.0)
        glyph_icon = get_tool_icon(self.tool.tool_name, 13,
                                   QColor(THEME["vm_accent"]) if self.isSelected() else QColor("#38bdf8"))
        glyph_icon.paint(painter, badge.adjusted(4.5, 3.5, -3.5, -3.5).toRect())

        # --- module name, with the execution index in the accent colour ------
        name = self.tool.name or self.tool.tool_name
        idx_part, _, rest = name.partition("_")
        if rest and idx_part.isdigit():
            num_txt, name_txt = f"{idx_part} ", rest.replace("_", " ")
        else:
            num_txt, name_txt = "", name.replace("_", " ")

        text_rect = QRectF(badge_w / 2.0 + 4.0, 2, self.WIDTH - badge_w / 2.0 - 11, self.HEADER_H - 4)
        fm_num = QFontMetrics(QFont("Segoe UI", 9, QFont.Weight.Bold))
        num_w = fm_num.horizontalAdvance(num_txt)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QColor(THEME["vm_accent"]))
        painter.drawText(QRectF(text_rect.x(), text_rect.y(), num_w, text_rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, num_txt)
        name_font = QFont("Segoe UI", 9)
        fm_name = QFontMetrics(name_font)
        avail = text_rect.width() - num_w
        painter.setFont(name_font)
        painter.setPen(QColor(THEME["vm_node_text"]))
        painter.drawText(
            QRectF(text_rect.x() + num_w, text_rect.y(), avail, text_rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm_name.elidedText(name_txt.strip(), Qt.TextElideMode.ElideRight, max(0, int(avail)))
        )

        # --- port rows -------------------------------------------------------
        left_rect, right_rect = self._port_label_rects()
        font_port = QFont("Segoe UI", 8)
        fm_port = QFontMetrics(font_port)
        painter.setFont(font_port)

        for i, (port_name, p_item) in enumerate(self.in_ports.items()):
            row = QRectF(left_rect.x(), left_rect.y() + i * self.PORT_ROW_H,
                         left_rect.width(), self.PORT_ROW_H)
            painter.setPen(QColor(THEME["vm_node_text_dim"]))
            painter.drawText(row, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             fm_port.elidedText(port_name, Qt.TextElideMode.ElideRight,
                                                max(0, int(row.width()))))

        for i, (port_name, p_item) in enumerate(self.out_ports.items()):
            row = QRectF(right_rect.x(), right_rect.y() + i * self.PORT_ROW_H,
                         right_rect.width(), self.PORT_ROW_H)
            painter.setPen(QColor(THEME["vm_node_text_dim"]))
            painter.drawText(row, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             fm_port.elidedText(port_name, Qt.TextElideMode.ElideRight,
                                                max(0, int(row.width()))))

        # --- footer strip: verdict + latency, right aligned ------------------
        footer_y = self.height - self.FOOTER_H
        painter.setPen(QPen(QColor("#2b3547"), 1.0))
        painter.drawLine(QPointF(6, footer_y), QPointF(self.WIDTH - 6, footer_y))

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.setPen(st_col)
        painter.drawText(QRectF(8, footer_y, 52, self.FOOTER_H),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, st_text)

        if self.elapsed_ms > 0:
            painter.setPen(QColor(THEME["vm_node_text_dim"]))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(QRectF(self.WIDTH - 74, footer_y, 66, self.FOOTER_H),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{self.elapsed_ms:.1f} ms")

    def _card_clip_path(self, card: QRectF, radius: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        return path

    def mouseDoubleClickEvent(self, event):
        """Double-click opens the module configuration window (§8.1)."""
        if self.signals:
            self.signals.configure_module.emit(self.tool.instance_id)
        event.accept()

    def mousePressEvent(self, event):
        self._press_pos = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if hasattr(self, "_press_pos") and self.pos() != self._press_pos:
            scene = self.scene()
            if isinstance(scene, FlowScene):
                scene.undo_stack.push(MoveNodeCommand(scene, self.tool.instance_id, self._press_pos, self.pos()))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if self.scene() and isinstance(self.scene(), FlowScene):
                self.scene().update_connections()
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if value and self.signals:
                self.signals.node_selected.emit(self.tool.instance_id)
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        menu = QMenu()
        config_act = menu.addAction("Module Configuration...")
        run_act = menu.addAction("Execute Module")
        toggle_act = menu.addAction("Bypass Module" if self.tool.enabled else "Enable Module")
        menu.addSeparator()
        del_act = menu.addAction("Delete Module")

        action = menu.exec(event.screenPos())
        if action == config_act:
            if self.signals:
                self.signals.configure_module.emit(self.tool.instance_id)
        elif action == run_act:
            if self.signals:
                self.signals.run_single_tool.emit(self.tool.instance_id)
        elif action == toggle_act:
            self.tool.enabled = not self.tool.enabled
            self.update()
        elif action == del_act:
            scene = self.scene()
            if isinstance(scene, FlowScene):
                cmd = DeleteNodeCommand(scene, self.tool.instance_id)
                scene.undo_stack.push(cmd)


class FlowScene(QGraphicsScene):
    def __init__(self, pipeline: VisionPipeline, signals: Optional[NodeSignals] = None, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.signals = signals if signals is not None else NodeSignals()
        self.node_items: Dict[str, FlowNodeItem] = {}
        self.connection_items: List[ConnectionItem] = []
        self.undo_stack: QUndoStack = QUndoStack(self)

        self._drag_start_port: Optional[PortItem] = None
        self._temp_line: Optional[QGraphicsPathItem] = None
        self._show_grid: bool = True
        self._locked: bool = False

        self.setBackgroundBrush(QBrush(QColor(THEME["vm_canvas"])))

    def set_grid_visible(self, visible: bool):
        self._show_grid = visible
        self.update()

    def set_locked(self, locked: bool):
        """Locking protection (manual p.70): block adding, deleting and moving."""
        self._locked = locked
        for item in self.node_items.values():
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not locked)
        for conn in self.connection_items:
            conn.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not locked)

    def is_locked(self) -> bool:
        return self._locked

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """Dotted alignment grid, sampled from the reference canvas (manual p.74)."""
        painter.fillRect(rect, QColor(THEME["vm_canvas"]))
        if not self._show_grid:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        minor, major = 20, 100
        left = int(rect.left()) - (int(rect.left()) % minor)
        top = int(rect.top()) - (int(rect.top()) % minor)

        minor_pen = QPen(QColor(THEME["vm_canvas_dot"]))
        minor_pen.setWidth(1)
        major_pen = QPen(QColor(THEME["vm_canvas_dot_major"]))
        major_pen.setWidth(1)

        for x in range(left, int(rect.right()) + minor, minor):
            for y in range(top, int(rect.bottom()) + minor, minor):
                if x % major == 0 and y % major == 0:
                    painter.setPen(major_pen)
                    painter.drawPoint(x, y)
                else:
                    painter.setPen(minor_pen)
                    painter.drawPoint(x, y)

    def can_edit(self) -> bool:
        """False while editing lock protection is engaged (manual p.70)."""
        if self._locked and self.signals:
            self.signals.connection_rejected.emit("Editing is locked (Locking protection engaged)")
        return not self._locked

    def is_dragging_connection(self) -> bool:
        return self._drag_start_port is not None

    def start_connection_drag(self, port: PortItem):
        if not self.can_edit():
            return
        self._drag_start_port = port
        self._temp_line = QGraphicsPathItem()
        self._temp_line.setZValue(10)
        self._temp_line.setPen(QPen(QColor(THEME["vm_accent"]), 2.0, Qt.PenStyle.DashLine))
        self.addItem(self._temp_line)

    def mouseMoveEvent(self, event):
        if self._drag_start_port and self._temp_line:
            p1 = self._drag_start_port.get_center_scene_pos()
            p2 = event.scenePos()
            path = QPainterPath()
            path.moveTo(p1)
            dx = max(30.0, abs(p2.x() - p1.x()) * 0.5)
            path.cubicTo(QPointF(p1.x() + dx, p1.y()), QPointF(p2.x() - dx, p2.y()), p2)
            self._temp_line.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def finish_connection_drag_at_pos(self, pos: QPointF):
        if not self._drag_start_port:
            return

        src_port = self._drag_start_port
        if self._temp_line:
            self.removeItem(self._temp_line)
            self._temp_line = None
        self._drag_start_port = None

        # Find target port under or near the cursor.
        target_port = None
        for item in self.items(pos):
            if isinstance(item, PortItem) and item.node_item is not src_port.node_item:
                target_port = item
                break
            if isinstance(item, FlowNodeItem) and item is not src_port.node_item:
                for p_item in item.in_ports.values():
                    p_pos = p_item.scenePos()
                    dist = (pos.x() - p_pos.x()) ** 2 + (pos.y() - p_pos.y()) ** 2
                    if dist <= 900:  # within 30px
                        target_port = p_item
                        break
                if target_port:
                    break

        if target_port and target_port.is_output != src_port.is_output:
            # Normalise direction so either drag direction produces the same link.
            if src_port.is_output:
                out_port, in_port = src_port, target_port
            else:
                out_port, in_port = target_port, src_port

            from_node = out_port.node_item.tool.instance_id
            from_p = out_port.port_name
            to_node = in_port.node_item.tool.instance_id
            to_p = in_port.port_name

            can, reason = self.pipeline.can_connect(from_node, from_p, to_node, to_p)
            if not can:
                if self.signals:
                    self.signals.connection_rejected.emit(reason)
                return

            cmd = AddConnectionCommand(self, from_node, from_p, to_node, to_p)
            self.undo_stack.push(cmd)
            if self.signals:
                self.signals.connection_added.emit(from_node, from_p, to_node, to_p)

    def mouseReleaseEvent(self, event):
        if self._drag_start_port:
            self.finish_connection_drag_at_pos(event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def remove_connection_item(self, c_item: ConnectionItem):
        dst_node = c_item.to_port.node_item.tool.instance_id
        dst_port = c_item.to_port.port_name
        src_node = c_item.from_port.node_item.tool.instance_id
        src_port = c_item.from_port.port_name

        cmd = DeleteConnectionCommand(self, src_node, src_port, dst_node, dst_port)
        self.undo_stack.push(cmd)

    def build_from_pipeline(self, preserve_positions: bool = True):
        if self._locked:
            return
        saved_positions = {}
        if preserve_positions:
            for nid, item in self.node_items.items():
                saved_positions[nid] = item.pos()

        self.clear()
        self.node_items.clear()
        self.connection_items.clear()

        for nid in self.pipeline.execution_order:
            node = self.pipeline.nodes.get(nid)
            if not node:
                continue

            pos = saved_positions.get(nid, QPointF(50, 50))
            item = FlowNodeItem(node, self.signals, pos)
            self.addItem(item)
            self.node_items[nid] = item

        if not saved_positions and len(self.node_items) > 0:
            self.arrange_nodes_hierarchically()

        for conn in self.pipeline.connections:
            src_node = self.node_items.get(conn.from_node)
            dst_node = self.node_items.get(conn.to_node)
            if src_node and dst_node:
                p_from = src_node.out_ports.get(conn.from_port)
                p_to = dst_node.in_ports.get(conn.to_port)
                if p_from and p_to:
                    c_item = ConnectionItem(p_from, p_to)
                    self.addItem(c_item)
                    self.connection_items.append(c_item)

    def arrange_nodes_hierarchically(self):
        """Topological hierarchical layout with predecessor alignment and crossing reduction."""
        levels = {}
        for nid in self.pipeline.execution_order:
            preds = [c.from_node for c in self.pipeline.connections if c.to_node == nid]
            if not preds:
                levels[nid] = 0
            else:
                levels[nid] = max((levels.get(p, 0) for p in preds), default=-1) + 1

        level_nodes: Dict[int, List[str]] = {}
        for nid, lvl in levels.items():
            level_nodes.setdefault(lvl, []).append(nid)

        col_w = 260.0
        row_h = 135.0
        start_x = 50.0
        start_y = 50.0

        # Sort nodes in each level to minimize edge crossings and align with predecessors
        node_row_indices = {}
        for lvl in sorted(level_nodes.keys()):
            nids = level_nodes[lvl]
            if lvl == 0:
                for r_idx, nid in enumerate(nids):
                    node_row_indices[nid] = r_idx
            else:
                def get_barycenter(nid: str) -> float:
                    preds = [c.from_node for c in self.pipeline.connections if c.to_node == nid]
                    if not preds:
                        return 0.0
                    pred_rows = [node_row_indices.get(p, 0) for p in preds]
                    return sum(pred_rows) / len(pred_rows)

                nids.sort(key=get_barycenter)
                used_rows = set()
                for nid in nids:
                    preds = [c.from_node for c in self.pipeline.connections if c.to_node == nid]
                    target_row = int(round(get_barycenter(nid))) if preds else 0
                    while target_row in used_rows:
                        target_row += 1
                    used_rows.add(target_row)
                    node_row_indices[nid] = target_row

            for nid in nids:
                r_idx = node_row_indices[nid]
                item = self.node_items.get(nid)
                if item:
                    item.setPos(QPointF(start_x + lvl * col_w, start_y + r_idx * row_h))

        self.update_connections()

    def align_selected(self, mode: str):
        """Align selected modules (left, top, distribute_h, distribute_v)."""
        selected_nodes = [item for item in self.selectedItems() if isinstance(item, FlowNodeItem)]
        if len(selected_nodes) < 2:
            return

        if mode == "left":
            min_x = min(node.pos().x() for node in selected_nodes)
            for node in selected_nodes:
                node.setPos(min_x, node.pos().y())
        elif mode == "top":
            min_y = min(node.pos().y() for node in selected_nodes)
            for node in selected_nodes:
                node.setPos(node.pos().x(), min_y)
        elif mode == "distribute_h":
            selected_nodes.sort(key=lambda n: n.pos().x())
            min_x = selected_nodes[0].pos().x()
            max_x = selected_nodes[-1].pos().x()
            span = (max_x - min_x) / (len(selected_nodes) - 1)
            for i, node in enumerate(selected_nodes):
                node.setPos(min_x + i * span, node.pos().y())
        elif mode == "distribute_v":
            selected_nodes.sort(key=lambda n: n.pos().y())
            min_y = selected_nodes[0].pos().y()
            max_y = selected_nodes[-1].pos().y()
            span = (max_y - min_y) / (len(selected_nodes) - 1)
            for i, node in enumerate(selected_nodes):
                node.setPos(node.pos().x(), min_y + i * span)

        self.update_connections()

    def update_connections(self):
        for c in self.connection_items:
            c.update_path()

    def select_node(self, instance_id: str):
        """Select exactly one module (used for initial selection / navigation)."""
        for nid, item in self.node_items.items():
            item.setSelected(nid == instance_id)
        if instance_id in self.node_items:
            self.node_items[instance_id].update()

    def update_node_status(self, instance_id: str, status: ToolStatus, elapsed_ms: float):
        if instance_id in self.node_items:
            node_item = self.node_items[instance_id]
            node_item.status = status
            node_item.elapsed_ms = elapsed_ms
            node_item.update()

    def contextMenuEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform() if self.views() else None)
        if item is not None and not isinstance(item, QGraphicsScene):
            super().contextMenuEvent(event)
            return

        menu = QMenu()
        u_text = f"Undo {self.undo_stack.undoText()}" if self.undo_stack.canUndo() else "Undo (Ctrl+Z)"
        r_text = f"Redo {self.undo_stack.redoText()}" if self.undo_stack.canRedo() else "Redo (Ctrl+Y)"
        undo_act = menu.addAction(u_text)
        undo_act.setEnabled(self.undo_stack.canUndo())
        redo_act = menu.addAction(r_text)
        redo_act.setEnabled(self.undo_stack.canRedo())

        menu.addSeparator()
        align_menu = menu.addMenu("Align Selected Modules")
        act_al_left = align_menu.addAction("Align Left")
        act_al_top = align_menu.addAction("Align Top")
        act_dist_h = align_menu.addAction("Distribute Horizontally")
        act_dist_v = align_menu.addAction("Distribute Vertically")

        menu.addSeparator()
        act_arrange = menu.addAction("Auto-Arrange Flow (Hierarchical)")
        act_validate = menu.addAction("Validate Flow Diagnostics...")

        action = menu.exec(event.screenPos())
        if action == undo_act:
            self.undo_stack.undo()
        elif action == redo_act:
            self.undo_stack.redo()
        elif action == act_al_left:
            self.align_selected("left")
        elif action == act_al_top:
            self.align_selected("top")
        elif action == act_dist_h:
            self.align_selected("distribute_h")
        elif action == act_dist_v:
            self.align_selected("distribute_v")
        elif action == act_arrange:
            self.arrange_nodes_hierarchically()
        elif action == act_validate:
            if self.signals:
                self.signals.validation_requested.emit()


class FlowZoomTool(QWidget):
    """Flow-area zoom control (manual region 11).

    The reference places a small square control in the lower-left corner of the
    flow canvas.  This reproduces it as a live control: a percentage read-out
    together with zoom-out / zoom-in / fit, so the operator can change the canvas
    scale without a mouse wheel.
    """

    def __init__(self, view: "FlowEditorView", parent=None):
        super().__init__(parent or view)
        self.view = view
        self.setObjectName("flowZoomTool")
        self.setFixedSize(112, 24)
        self.setToolTip("Flow canvas zoom")

        row = QHBoxLayout(self)
        row.setContentsMargins(3, 2, 3, 2)
        row.setSpacing(1)

        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setObjectName("flowZoomLabel")
        self.lbl_zoom.setFixedWidth(34)
        self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.lbl_zoom)

        self.btn_out = self._button("\u2212", "Zoom out")
        self.btn_in = self._button("+", "Zoom in")
        self.btn_fit = self._button("\u25a1", "Fit the flow to the canvas")
        self.btn_out.clicked.connect(view.zoom_out)
        self.btn_in.clicked.connect(view.zoom_in)
        self.btn_fit.clicked.connect(view.fit_to_view)
        for btn in (self.btn_out, self.btn_in, self.btn_fit):
            row.addWidget(btn)

        self.refresh()

    def _button(self, text: str, tip: str) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("flowZoomButton")
        btn.setText(text)
        btn.setToolTip(tip)
        btn.setAutoRaise(True)
        btn.setFixedSize(20, 18)
        return btn

    def refresh(self):
        self.lbl_zoom.setText(f"{self.view.zoom_percent()}%")

    def reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        w, h = parent.width(), parent.height()
        if w <= 0 or h <= 0:
            return
        # Lower-left corner of the canvas, as in the vendor figure (region 11).
        x = self.MARGIN_LEFT
        y = max(0, h - self.height() - 8)
        if self.pos() != QPoint(x, y):
            self.move(x, y)

    MARGIN_LEFT = 8


class FlowTelemetryBar(QWidget):
    """Flow-processing time bar (manual Fig. 6-2 region 8).
    Displays Flow processing time, tool execution count, and algorithm execution time.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("flowTelemetryBar")
        self.setFixedHeight(22)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(10)

        self.lbl_flow = QLabel("Flow: 0.00ms")
        self.lbl_flow.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
        row.addWidget(self.lbl_flow)

        self.lbl_tools = QLabel("Tools: 0")
        self.lbl_tools.setStyleSheet("color: #94a3b8; font-size: 11px;")
        row.addWidget(self.lbl_tools)

        self.lbl_algo = QLabel("Algorithm: 0.00ms")
        self.lbl_algo.setStyleSheet("color: #a78bfa; font-size: 11px;")
        row.addWidget(self.lbl_algo)

        self.setStyleSheet(
            f"background-color: {THEME['bg_surface']}; "
            f"border: 1px solid {THEME['border_subtle']}; border-radius: 2px;"
        )

    def update_telemetry(self, flow_ms: float, tool_count: int, algo_ms: float):
        self.lbl_flow.setText(f"Flow: {flow_ms:.2f}ms")
        self.lbl_tools.setText(f"Tools: {tool_count}")
        self.lbl_algo.setText(f"Algorithm: {algo_ms:.2f}ms")

    def reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        w, h = parent.width(), parent.height()
        if w <= 0 or h <= 0:
            return
        x = FlowZoomTool.MARGIN_LEFT + 120
        y = max(0, h - self.height() - 8)
        self.move(x, y)


class FlowEditorView(QGraphicsView):
    """Interactive viewport with smooth mouse-wheel zoom, middle/right drag pan, and drag-and-drop."""
    def __init__(self, scene: FlowScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setStyleSheet("border: none; background: transparent;")
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAcceptDrops(True)

        self._is_panning: bool = False
        self._pan_start: QPointF = QPointF()

        # Flow-area zoom control (manual Fig. 5-2 region 11) — the only floating
        # instrument the reference canvas carries.
        self.zoom_tool = FlowZoomTool(self, self)
        self.zoom_tool.reposition()
        self.zoom_tool.show()

        # Flow-processing time area (manual Fig. 6-2 region 8)
        self.telemetry_bar = FlowTelemetryBar(self)
        self.telemetry_bar.reposition()
        self.telemetry_bar.show()

    def update_telemetry(self, flow_ms: float, tool_count: int, algo_ms: float):
        if hasattr(self, "telemetry_bar"):
            self.telemetry_bar.update_telemetry(flow_ms, tool_count, algo_ms)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "zoom_tool"):
            self.zoom_tool.reposition()
        if hasattr(self, "telemetry_bar"):
            self.telemetry_bar.reposition()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if hasattr(self, "zoom_tool"):
            self.zoom_tool.refresh()

    def zoom_in(self):
        self._zoom_by(1.2)

    def zoom_out(self):
        self._zoom_by(1.0 / 1.2)

    def _zoom_by(self, factor: float):
        cur = self.transform().m11()
        if (factor > 1.0 and cur >= 3.0) or (factor < 1.0 and cur <= 0.25):
            return
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.scale(factor, factor)
        self._sync_zoom_tool()

    def reset_zoom(self):
        self.resetTransform()
        self._sync_zoom_tool()

    def zoom_percent(self) -> int:
        return int(round(self.transform().m11() * 100))

    def fit_to_view(self):
        rect = self.scene().itemsBoundingRect() if self.scene() else QRectF()
        if rect.isEmpty():
            self.reset_zoom()
            return
        self.fitInView(rect.adjusted(-30, -30, 30, 30), Qt.AspectRatioMode.KeepAspectRatio)
        self._sync_zoom_tool()

    def _sync_zoom_tool(self):
        tool = getattr(self, "zoom_tool", None)
        if tool is not None:
            tool.refresh()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self._zoom_by(1.15 if delta > 0 else 0.85)
        self._sync_zoom_tool()

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._is_panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_panning and event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        scene = self.scene()
        if isinstance(scene, FlowScene):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if event.key() == Qt.Key.Key_Z:
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        scene.undo_stack.redo()
                    else:
                        scene.undo_stack.undo()
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_Y:
                    scene.undo_stack.redo()
                    event.accept()
                    return

            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if not scene.can_edit():
                    event.accept()
                    return
                selected = list(scene.selectedItems())
                conns = [it for it in selected if isinstance(it, ConnectionItem)]
                nodes = [it for it in selected if isinstance(it, FlowNodeItem)]
                if not conns and not nodes:
                    event.accept()
                    return

                scene.undo_stack.beginMacro("Delete Selection")
                try:
                    node_ids = {n.tool.instance_id for n in nodes}
                    for c_item in conns:
                        try:
                            dst_node = c_item.to_port.node_item.tool.instance_id
                            src_node = c_item.from_port.node_item.tool.instance_id
                            if dst_node in node_ids or src_node in node_ids:
                                continue
                            scene.remove_connection_item(c_item)
                        except Exception:
                            pass
                    for n_item in nodes:
                        cmd = DeleteNodeCommand(scene, n_item.tool.instance_id)
                        scene.undo_stack.push(cmd)
                finally:
                    scene.undo_stack.endMacro()
                event.accept()
                return

        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasText():
            tool_name = event.mimeData().text()
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            scene_pos = self.mapToScene(pos)
            scene = self.scene()
            if isinstance(scene, FlowScene) and scene.signals:
                scene.signals.tool_dropped.emit(tool_name, float(scene_pos.x()), float(scene_pos.y()))
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

