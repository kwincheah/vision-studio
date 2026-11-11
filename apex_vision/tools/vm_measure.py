"""VisionMaster guide, chapter "Measurement": L2C (line to circle), P2C (point to circle) and C2C (circle to circle).

The guide takes the line and circle from earlier modules (By Line / By Circle), from points, or typed (By Coordinate / By Parameter).
Distances are in pixels unless a scale (units per pixel) is set.
"""
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import circle as as_circle, define, err, ok, port, val
from apex_vision.tools.vm_lines import _line_from

CAT = "Measurement"
RANGES = ["-180 to 180", "-90 to 90"]
MODES = ["By Line", "By Point", "By Coordinate"]


def _fold(angle: float, rng: str) -> float:
    """Bring an angle in degrees into the chosen output range (-90..90 adds or removes 180)."""
    a = (angle + 180.0) % 360.0 - 180.0
    if rng.startswith("-90"):
        if a > 90.0:
            a -= 180.0
        elif a < -90.0:
            a += 180.0
    return a


def _circle_from(t, ctx, which: int = 1, prefix: str = "circle") -> Optional[Tuple[float, float, float]]:
    suffix = "" if which == 1 else "2"
    mode = str(t.get_param("input_mode"))
    if mode == "By Coordinate":
        c = (float(t.get_param(f"{prefix}{suffix}_x")), float(t.get_param(f"{prefix}{suffix}_y")), float(t.get_param(f"{prefix}{suffix}_r")))
    else:
        c = as_circle(ctx.get("Circle" if which == 1 else "Circle2"))
    if c is None or not all(math.isfinite(v) for v in c) or c[2] <= 0:
        return None
    return c


def _circle_overlay(c, colour) -> Dict[str, Any]:
    return {"type": "circle", "center": (int(round(c[0])), int(round(c[1]))), "radius": max(1, int(round(c[2]))), "color": colour}


CIRCLE_PARAMS = {"circle_x": 300.0, "circle_y": 200.0, "circle_r": 60.0}
CIRCLE_SCHEMA = {"circle_x": num(-1e6, 1e6, 1, "px", 2), "circle_y": num(-1e6, 1e6, 1, "px", 2), "circle_r": num(0.01, 1e6, 1, "px", 2)}


# ---------------------------------------------------------------------------------------------------------------------------
@define("L2C Measure", CAT,
        "Measures between a line and a circle: the distance from the circle's centre to the line and from the line to the circle's edge, the "
        "angle of the connection between the centre and the line, the closest point on the circle, the foot of the centre on the line, and "
        "where the line cuts the circle (if it does). The line comes from a Line Search, two points or typed coordinates; the circle from a "
        "Circle Search or typed values.",
        inputs=[port("Line", "line", "Line (By Line)"), port("Circle", "circle", "Circle {cx, cy, r}"),
                port("Point1_Start", "pt", "Line start (By Point)"), port("Point1_End", "pt", "Line end (By Point)")],
        outputs=[val("Distance", "From the line to the circle's edge; negative when the line cuts the circle"), val("Center_Distance", "From the circle's centre to the line"),
                 val("Abs_Distance"), val("Angle_Deg", "Of the centre-to-line connection against the horizontal"),
                 port("Nearest_Point", "pt", "Point on the circle closest to the line"), port("Foot", "pt", "Centre projected on the line"),
                 port("Cross_Points", "any", "Where the line meets the circle (0, 1 or 2 points)"), val("Cross_Count")],
        params={"input_mode": "By Coordinate", "line1": [100, 100, 500, 120], **CIRCLE_PARAMS, "angle_range": "-180 to 180", "scale_factor": 1.0},
        schema={"input_mode": enum(*MODES), "line1": {"kind": "line"}, **CIRCLE_SCHEMA, "angle_range": enum(*RANGES),
                "scale_factor": num(0.000001, 1e6, 0.01, decimals=6)})
def l2c(t, ctx):
    l = _line_from(t, ctx, 1)
    c = _circle_from(t, ctx)
    if l is None:
        return err("no line chosen, or it has no length: connect it, or type its coordinates")
    if c is None:
        return err("no circle chosen, or its radius is not positive: connect it, or type its values")
    cx, cy, r = c
    sc = float(t.get_param("scale_factor"))
    fx, fy = g.point_line_foot((cx, cy), l)
    dx, dy = fx - cx, fy - cy
    d = math.hypot(dx, dy)
    if d > 1e-9:
        ux, uy = dx / d, dy / d
    else:                                                                                  # centre on the line: use the line's normal
        ux, uy = -(l["y2"] - l["y1"]) / l["length"], (l["x2"] - l["x1"]) / l["length"]
    near = (cx + ux * r, cy + uy * r)
    ang = _fold(math.degrees(math.atan2(dy, dx)) if d > 1e-9 else math.degrees(math.atan2(uy, ux)), str(t.get_param("angle_range")))
    dirx, diry = (l["x2"] - l["x1"]) / l["length"], (l["y2"] - l["y1"]) / l["length"]
    crosses: List[Tuple[float, float]] = []
    if d < r - 1e-9:
        h = math.sqrt(r * r - d * d)
        crosses = [(fx - dirx * h, fy - diry * h), (fx + dirx * h, fy + diry * h)]
    elif abs(d - r) <= 1e-9:
        crosses = [(fx, fy)]
    gap = (d - r) * sc
    over = [g.line_overlay(l), _circle_overlay(c, (0, 255, 255)), {"type": "line", "pt1": (int(round(cx)), int(round(cy))), "pt2": (int(round(fx)), int(round(fy))), "color": (255, 180, 0), "thickness": 1},
            g.cross_overlay(*near, (0, 0, 255)), g.cross_overlay(fx, fy, (0, 255, 0))] + [g.cross_overlay(px, py, (255, 0, 255)) for px, py in crosses]
    over.append({"type": "text", "text": f"{gap:.2f}", "pt": (int((cx + fx) / 2) + 6, int((cy + fy) / 2)), "color": (0, 255, 255)})
    return ok(f"line to circle {gap:.2f}; centre to line {d * sc:.2f}; angle {ang:.1f} deg", over, Distance=gap, Center_Distance=d * sc, Abs_Distance=abs(gap), Angle_Deg=ang,
              Nearest_Point=(near[0], near[1]), Foot=(fx, fy), Cross_Points=[list(p) for p in crosses], Cross_Count=len(crosses))


# ---------------------------------------------------------------------------------------------------------------------------
@define("P2C Measure", CAT,
        "Measures between a point and a circle: the distance from the point to the circle's centre and to its edge (negative when the point is "
        "inside), the closest point on the circle, and the angle of the connection.",
        inputs=[port("Point", "pt", "Point"), port("Circle", "circle", "Circle {cx, cy, r}")],
        outputs=[val("Distance", "Point to the circle's edge; negative when inside"), val("Center_Distance"), val("Abs_Distance"), val("Delta_X"), val("Delta_Y"),
                 val("Angle_Deg", "Of the point-to-centre connection against the horizontal"), port("Nearest_Point", "pt", "Point on the circle closest to the point")],
        params={"input_mode": "By Coordinate", "point_x": 100.0, "point_y": 100.0, **CIRCLE_PARAMS, "angle_range": "-180 to 180", "scale_factor": 1.0},
        schema={"input_mode": enum("By Circle", "By Coordinate"), "point_x": num(-1e6, 1e6, 1, "px", 2), "point_y": num(-1e6, 1e6, 1, "px", 2), **CIRCLE_SCHEMA,
                "angle_range": enum(*RANGES), "scale_factor": num(0.000001, 1e6, 0.01, decimals=6)})
def p2c(t, ctx):
    coord = str(t.get_param("input_mode")) == "By Coordinate"
    p = (float(t.get_param("point_x")), float(t.get_param("point_y"))) if coord else t.as_point(ctx.get("Point"))
    c = _circle_from(t, ctx)
    if p is None or not all(math.isfinite(v) for v in p):
        return err("no point chosen: connect it, or type its coordinates")
    if c is None:
        return err("no circle chosen, or its radius is not positive: connect it, or type its values")
    cx, cy, r = c
    sc = float(t.get_param("scale_factor"))
    dx, dy = cx - p[0], cy - p[1]
    d = math.hypot(dx, dy)
    ang = _fold(math.degrees(math.atan2(dy, dx)), str(t.get_param("angle_range")))
    if d > 1e-9:
        near = (cx - dx / d * r, cy - dy / d * r)
    else:
        near = (cx + r, cy)
    gap = (d - r) * sc
    over = [_circle_overlay(c, (0, 255, 255)), g.cross_overlay(*p, (0, 255, 0)), g.cross_overlay(*near, (0, 0, 255)),
            {"type": "line", "pt1": (int(round(p[0])), int(round(p[1]))), "pt2": (int(round(near[0])), int(round(near[1]))), "color": (255, 180, 0), "thickness": 1}]
    over.append({"type": "text", "text": f"{gap:.2f}", "pt": (int(p[0]) + 6, int(p[1]) - 6), "color": (0, 255, 255)})
    return ok(f"point to circle {gap:.2f}; to centre {d * sc:.2f}", over, Distance=gap, Center_Distance=d * sc, Abs_Distance=abs(gap), Delta_X=dx * sc, Delta_Y=dy * sc, Angle_Deg=ang,
              Nearest_Point=near)


# ---------------------------------------------------------------------------------------------------------------------------
@define("C2C Measure", CAT,
        "Measures between two circles: the distance between their centres, the shortest gap between the outlines (0 where they cross, and for "
        "one inside the other the gap between them), the largest span, the angle of the line through both centres, the two closest points, "
        "and where the circles cross.",
        inputs=[port("Circle", "circle", "First circle"), port("Circle2", "circle", "Second circle")],
        outputs=[val("Distance", "Shortest distance between the outlines"), val("Center_Distance"), val("Max_Distance", "Largest distance between points on the two outlines"),
                 val("Radius_Diff"), val("Angle_Deg", "Of the line from the first centre to the second"), port("Point1", "pt", "Closest point on the first circle"),
                 port("Point2", "pt", "Closest point on the second circle"), port("Cross_Points", "any", "Where the outlines cross (0, 1 or 2)"), val("Cross_Count"),
                 val("Relation", "Apart, Crossing, Touching or Inside")],
        params={"input_mode": "By Coordinate", **CIRCLE_PARAMS, "circle2_x": 500.0, "circle2_y": 200.0, "circle2_r": 40.0, "angle_range": "-180 to 180", "scale_factor": 1.0},
        schema={"input_mode": enum("By Circle", "By Coordinate"), **CIRCLE_SCHEMA, "circle2_x": num(-1e6, 1e6, 1, "px", 2), "circle2_y": num(-1e6, 1e6, 1, "px", 2),
                "circle2_r": num(0.01, 1e6, 1, "px", 2), "angle_range": enum(*RANGES), "scale_factor": num(0.000001, 1e6, 0.01, decimals=6)})
def c2c(t, ctx):
    a, b = _circle_from(t, ctx, 1), _circle_from(t, ctx, 2)
    if a is None or b is None:
        return err("both circles must be chosen with a positive radius: connect them, or type their values")
    sc = float(t.get_param("scale_factor"))
    (x1, y1, r1), (x2, y2, r2) = a, b
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    ux, uy = (dx / d, dy / d) if d > 1e-9 else (1.0, 0.0)
    ang = _fold(math.degrees(math.atan2(uy, ux)), str(t.get_param("angle_range")))
    eps = 1e-9
    if d > r1 + r2 + eps:
        rel, gap = "Apart", d - r1 - r2
        p1, p2 = (x1 + ux * r1, y1 + uy * r1), (x2 - ux * r2, y2 - uy * r2)
    elif d < abs(r1 - r2) - eps:
        rel, gap = "Inside", abs(r1 - r2) - d
        s = 1.0 if r1 >= r2 else -1.0                                                          # the smaller circle sits inside the larger one
        p1 = (x1 + ux * r1 * s, y1 + uy * r1 * s)
        p2 = (x2 + ux * r2 * s, y2 + uy * r2 * s)
    elif abs(d - (r1 + r2)) <= eps or abs(d - abs(r1 - r2)) <= eps:
        rel, gap = "Touching", 0.0
        p1 = (x1 + ux * r1, y1 + uy * r1) if abs(d - (r1 + r2)) <= eps else (x1 + ux * r1 * (1 if r1 >= r2 else -1), y1 + uy * r1 * (1 if r1 >= r2 else -1))
        p2 = p1
    else:
        rel, gap = "Crossing", 0.0
        p1, p2 = (x1 + ux * r1, y1 + uy * r1), (x2 - ux * r2, y2 - uy * r2)
    crosses: List[Tuple[float, float]] = []
    if d > eps and abs(r1 - r2) - eps <= d <= r1 + r2 + eps:
        a_ = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
        h2 = r1 * r1 - a_ * a_
        h = math.sqrt(max(0.0, h2))
        mx, my = x1 + ux * a_, y1 + uy * a_
        crosses = [(mx - uy * h, my + ux * h), (mx + uy * h, my - ux * h)] if h > 1e-6 else [(mx, my)]
    over = [_circle_overlay(a, (0, 255, 255)), _circle_overlay(b, (0, 200, 255)),
            {"type": "line", "pt1": (int(round(x1)), int(round(y1))), "pt2": (int(round(x2)), int(round(y2))), "color": (255, 180, 0), "thickness": 1},
            g.cross_overlay(*p1, (0, 0, 255)), g.cross_overlay(*p2, (0, 255, 0))] + [g.cross_overlay(px, py, (255, 0, 255)) for px, py in crosses]
    over.append({"type": "text", "text": f"{gap * sc:.2f}", "pt": (int((x1 + x2) / 2) + 6, int((y1 + y2) / 2) - 6), "color": (0, 255, 255)})
    return ok(f"circles {rel.lower()}; gap {gap * sc:.2f}, centres {d * sc:.2f} apart", over, Distance=gap * sc, Center_Distance=d * sc, Max_Distance=(d + r1 + r2) * sc,
              Radius_Diff=abs(r1 - r2) * sc, Angle_Deg=ang, Point1=p1, Point2=p2, Cross_Points=[list(p) for p in crosses], Cross_Count=len(crosses), Relation=rel)
