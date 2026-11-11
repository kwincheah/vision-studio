"""
More Measurement modules: point-to-line distance, angle between three points, and where two lines cross.
Points are ``(x, y)`` pairs and lines are ``{x1, y1, x2, y2}`` mappings, the same shapes the existing modules use.
"""
import math
from typing import Any, Dict

from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from apex_vision.core.registry import register_tool


def _bad(port: str, kind: str, raw: Any) -> ToolExecutionResult:
    return ToolExecutionResult(status=ToolStatus.ERROR, message=f"{port} is not a valid {kind}: {raw!r:.80}")


@register_tool
class P2LMeasureTool(VisionToolBase):
    category = "Measurement"
    tool_name = "P2L Measure"
    description = "Shortest (perpendicular) distance from a point to an infinite line, and the point on the line closest to it."

    def _init_ports(self):
        self.inputs["Point"] = ToolPort("Point", DataType.POINT, "The point (x, y)")
        self.inputs["Line"] = ToolPort("Line", DataType.LINE, "The line")
        self.outputs["Distance"] = ToolPort("Distance", DataType.VALUE, "Perpendicular distance")
        self.outputs["Foot"] = ToolPort("Foot", DataType.POINT, "Closest point on the line")

    def _init_parameters(self):
        self.parameters = {
            "scale_factor": 1.0,
            "default_point": [200, 100],
            "default_line": [100, 200, 400, 200],
            "min_distance": 0.0,
            "max_distance": 1000.0,
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        raw_p = context.get("Point")
        raw_l = context.get("Line")
        p = self.as_point(raw_p if raw_p is not None else self.get_param("default_point"))
        if p is None:
            return _bad("Point", "point (need x,y)", raw_p)
        line = self.as_line(raw_l if raw_l is not None else self.get_param("default_line"))
        if line is None:
            return _bad("Line", "line (need x1,y1,x2,y2)", raw_l)
        x1, y1, x2, y2 = line
        dx, dy = x2 - x1, y2 - y1
        length2 = dx * dx + dy * dy
        if length2 < 1e-12:
            return ToolExecutionResult(status=ToolStatus.NG, message="The line has no length")
        t = ((p[0] - x1) * dx + (p[1] - y1) * dy) / length2
        fx, fy = x1 + t * dx, y1 + t * dy
        scale = self.as_float(self.get_param("scale_factor", 1.0), 1.0)
        dist = math.hypot(p[0] - fx, p[1] - fy) * scale
        lo, hi = self.as_float(self.get_param("min_distance", 0.0)), self.as_float(self.get_param("max_distance", 1000.0), 1000.0)
        ok = lo <= dist <= hi
        return ToolExecutionResult(
            status=ToolStatus.OK if ok else ToolStatus.NG,
            message=f"P2L distance: {dist:.2f}",
            outputs={"Distance": dist, "Foot": (fx, fy)},
            overlays=[{"type": "cross", "pt": (int(p[0]), int(p[1])), "size": 8, "color": (0, 255, 0)},
                      {"type": "line", "pt1": (int(p[0]), int(p[1])), "pt2": (int(fx), int(fy)), "color": (255, 255, 0), "thickness": 2},
                      {"type": "text", "text": f"P2L: {dist:.2f}", "pt": (int((p[0] + fx) / 2) + 6, int((p[1] + fy) / 2)), "color": (255, 255, 0)}])


@register_tool
class AngleMeasureTool(VisionToolBase):
    category = "Measurement"
    tool_name = "Angle Measure"
    description = "The angle at a vertex between two other points (A - Vertex - C), from 0 to 180 degrees."

    def _init_ports(self):
        self.inputs["Point_A"] = ToolPort("Point_A", DataType.POINT, "First arm end")
        self.inputs["Vertex"] = ToolPort("Vertex", DataType.POINT, "The corner of the angle")
        self.inputs["Point_C"] = ToolPort("Point_C", DataType.POINT, "Second arm end")
        self.outputs["Angle_Deg"] = ToolPort("Angle_Deg", DataType.VALUE, "Angle in degrees (0-180)")

    def _init_parameters(self):
        self.parameters = {
            "default_a": [300, 200],
            "default_vertex": [200, 200],
            "default_c": [200, 100],
            "min_angle": 0.0,
            "max_angle": 180.0,
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        pts = {}
        for port, key in (("Point_A", "default_a"), ("Vertex", "default_vertex"), ("Point_C", "default_c")):
            raw = context.get(port)
            pt = self.as_point(raw if raw is not None else self.get_param(key))
            if pt is None:
                return _bad(port, "point (need x,y)", raw)
            pts[port] = pt
        a, v, c = pts["Point_A"], pts["Vertex"], pts["Point_C"]
        ux, uy, wx, wy = a[0] - v[0], a[1] - v[1], c[0] - v[0], c[1] - v[1]
        nu, nw = math.hypot(ux, uy), math.hypot(wx, wy)
        if nu < 1e-9 or nw < 1e-9:
            return ToolExecutionResult(status=ToolStatus.NG, message="An arm has no length (a point sits on the vertex)")
        cosang = max(-1.0, min(1.0, (ux * wx + uy * wy) / (nu * nw)))
        ang = math.degrees(math.acos(cosang))
        lo, hi = self.as_float(self.get_param("min_angle", 0.0)), self.as_float(self.get_param("max_angle", 180.0), 180.0)
        ok = lo <= ang <= hi
        iv = (int(v[0]), int(v[1]))
        return ToolExecutionResult(
            status=ToolStatus.OK if ok else ToolStatus.NG, message=f"Angle: {ang:.2f} deg",
            outputs={"Angle_Deg": ang},
            overlays=[{"type": "line", "pt1": iv, "pt2": (int(a[0]), int(a[1])), "color": (255, 255, 0), "thickness": 2},
                      {"type": "line", "pt1": iv, "pt2": (int(c[0]), int(c[1])), "color": (255, 255, 0), "thickness": 2},
                      {"type": "cross", "pt": iv, "size": 8, "color": (0, 255, 0)},
                      {"type": "text", "text": f"{ang:.1f} deg", "pt": (iv[0] + 10, iv[1] - 10), "color": (255, 255, 0)}])


@register_tool
class LineIntersectionTool(VisionToolBase):
    category = "Measurement"
    tool_name = "Line Intersection"
    description = "The point where two lines cross (extended to infinity), and the angle between them. Parallel lines fail."

    def _init_ports(self):
        self.inputs["Line1"] = ToolPort("Line1", DataType.LINE, "First line")
        self.inputs["Line2"] = ToolPort("Line2", DataType.LINE, "Second line")
        self.outputs["Point"] = ToolPort("Point", DataType.POINT, "The crossing point")
        self.outputs["X"] = ToolPort("X", DataType.VALUE, "Crossing X")
        self.outputs["Y"] = ToolPort("Y", DataType.VALUE, "Crossing Y")
        self.outputs["Angle_Deg"] = ToolPort("Angle_Deg", DataType.VALUE, "Angle between the lines (0-90)")

    def _init_parameters(self):
        self.parameters = {"default_l1": [100, 100, 400, 100], "default_l2": [250, 50, 250, 300]}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        lines = []
        for port, key in (("Line1", "default_l1"), ("Line2", "default_l2")):
            raw = context.get(port)
            ln = self.as_line(raw if raw is not None else self.get_param(key))
            if ln is None:
                return _bad(port, "line (need x1,y1,x2,y2)", raw)
            lines.append(ln)
        (x1, y1, x2, y2), (x3, y3, x4, y4) = lines
        d1x, d1y, d2x, d2y = x2 - x1, y2 - y1, x4 - x3, y4 - y3
        if math.hypot(d1x, d1y) < 1e-9 or math.hypot(d2x, d2y) < 1e-9:
            return ToolExecutionResult(status=ToolStatus.NG, message="A line has no length")
        den = d1x * d2y - d1y * d2x
        if abs(den) < 1e-9 * math.hypot(d1x, d1y) * math.hypot(d2x, d2y):
            return ToolExecutionResult(status=ToolStatus.NG, message="The lines are parallel: they do not cross")
        t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / den
        px, py = x1 + t * d1x, y1 + t * d1y
        ang = abs(math.degrees(math.atan2(d1x * d2y - d1y * d2x, d1x * d2x + d1y * d2y)))
        ang = min(ang, 180.0 - ang)
        return ToolExecutionResult(
            status=ToolStatus.OK, message=f"Lines cross at ({px:.1f}, {py:.1f}), {ang:.1f} deg apart",
            outputs={"Point": (px, py), "X": px, "Y": py, "Angle_Deg": ang},
            overlays=[{"type": "cross", "pt": (int(px), int(py)), "size": 10, "color": (0, 255, 0)},
                      {"type": "text", "text": f"({px:.0f}, {py:.0f})", "pt": (int(px) + 12, int(py) - 8), "color": (255, 255, 0)}])
