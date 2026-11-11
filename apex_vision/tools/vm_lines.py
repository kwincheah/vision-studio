"""VisionMaster guide, chapter "Location": the pure line-geometry modules (no picture needed).

Find Angle Bisector, Find Median Line, Calculate Parallel Lines and Find Vertical Line. Each takes its line(s) in one of the guide's three
ways: By Line (a line from an earlier module), By Point (two points per line) or By Coordinate (typed x1, y1, x2, y2).
"""
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import define, err, ng, ok, port, val

CAT = "Location"
MODES = ["By Line", "By Point", "By Coordinate"]


def _line_from(t, ctx, which: int) -> Optional[Dict[str, float]]:
    """Line number ``which`` (1 or 2) in the module's input mode, or None when it is missing / malformed."""
    mode = str(t.get_param("input_mode"))
    if mode == "By Line":
        v = ctx.get(f"Line{which}")
        l = t.as_line(v) if v is not None else None
    elif mode == "By Point":
        a, b = t.as_point(ctx.get(f"Point{which}_Start")), t.as_point(ctx.get(f"Point{which}_End"))
        l = (a[0], a[1], b[0], b[1]) if a is not None and b is not None else None
    else:
        raw = t.get_param(f"line{which}")
        l = t.as_line(raw)
    if l is None or math.hypot(l[2] - l[0], l[3] - l[1]) < 1e-9:
        return None
    return g.line_to_dict(*l)


LINE_INPUTS = [port("Line1", "line", "First line (By Line)"), port("Line2", "line", "Second line (By Line)"),
               port("Point1_Start", "pt", "First line's start (By Point)"), port("Point1_End", "pt", "First line's end (By Point)"),
               port("Point2_Start", "pt", "Second line's start (By Point)"), port("Point2_End", "pt", "Second line's end (By Point)")]
LINE_PARAMS = {"input_mode": "By Coordinate", "line1": [100, 200, 300, 160], "line2": [100, 100, 300, 160]}
LINE_SCHEMA = {"input_mode": enum(*MODES), "line1": {"kind": "line"}, "line2": {"kind": "line"}}


def _missing(which=""):
    return err(f"no {which} line chosen, or it has no length: connect it, or type its coordinates")


def _span(*lines) -> float:
    return max(max(l["length"] for l in lines), 10.0)


@define("Find Angle Bisector", CAT,
        "The line that splits the angle between two lines in half. It passes through the point where the lines cross and points between them; "
        "the other bisector (at a right angle to it) is given as well.",
        inputs=LINE_INPUTS, outputs=[port("Bisector", "line", "Bisects the angle between the two line segments' directions"), port("Bisector_2", "line", "The other bisector, at 90 degrees to the first"),
                                     port("Intersection", "pt", "Where the two lines cross"), val("Angle_Deg", "Angle between the two lines (0-180)"), val("Bisector_Angle")],
        params=dict(LINE_PARAMS), schema=dict(LINE_SCHEMA))
def find_angle_bisector(t, ctx):
    l1, l2 = _line_from(t, ctx, 1), _line_from(t, ctx, 2)
    if l1 is None:
        return _missing("first")
    if l2 is None:
        return _missing("second")
    p = g.intersect(l1, l2)
    if p is None:
        return ng("the lines are parallel, so they have no angle bisector")
    d1 = np.array([l1["x2"] - l1["x1"], l1["y2"] - l1["y1"]]) / l1["length"]
    d2 = np.array([l2["x2"] - l2["x1"], l2["y2"] - l2["y1"]]) / l2["length"]
    # point the first direction away from the crossing so both arms start at the corner
    mid1, mid2 = np.array([(l1["x1"] + l1["x2"]) / 2, (l1["y1"] + l1["y2"]) / 2]), np.array([(l2["x1"] + l2["x2"]) / 2, (l2["y1"] + l2["y2"]) / 2])
    pp = np.array(p)
    if (mid1 - pp) @ d1 < 0:
        d1 = -d1
    if (mid2 - pp) @ d2 < 0:
        d2 = -d2
    bis = d1 + d2
    if np.hypot(*bis) < 1e-9:                                                          # the two arms point in opposite directions
        bis = np.array([-d1[1], d1[0]])
    bis /= np.hypot(*bis)
    half = _span(l1, l2) / 2
    b1 = g.line_to_dict(p[0] - bis[0] * half, p[1] - bis[1] * half, p[0] + bis[0] * half, p[1] + bis[1] * half)
    other = np.array([-bis[1], bis[0]])
    b2 = g.line_to_dict(p[0] - other[0] * half, p[1] - other[1] * half, p[0] + other[0] * half, p[1] + other[1] * half)
    ang = math.degrees(math.acos(float(np.clip(d1 @ d2, -1, 1))))
    return ok(f"bisector at {g.line_angle(b1):.2f} deg through ({p[0]:.1f}, {p[1]:.1f}); the lines are {ang:.2f} deg apart",
              [g.line_overlay(l1, (0, 200, 255)), g.line_overlay(l2, (0, 200, 255)), g.line_overlay(b1, (0, 255, 0)), g.cross_overlay(p[0], p[1], (0, 0, 255), 7)],
              Bisector=b1, Bisector_2=b2, Intersection=(float(p[0]), float(p[1])), Angle_Deg=ang, Bisector_Angle=g.line_angle(b1))


@define("Find Median Line", CAT,
        "Joins the middle of the two lines' start points to the middle of their end points: the line half-way between two lines.",
        inputs=LINE_INPUTS, outputs=[port("Median_Line", "line", "The line between the two midpoints"), port("Start_Midpoint", "pt", "Middle of the two start points"),
                                     port("End_Midpoint", "pt", "Middle of the two end points"), val("Angle_Deg")],
        params=dict(LINE_PARAMS), schema=dict(LINE_SCHEMA))
def find_median_line(t, ctx):
    l1, l2 = _line_from(t, ctx, 1), _line_from(t, ctx, 2)
    if l1 is None:
        return _missing("first")
    if l2 is None:
        return _missing("second")
    ms = ((l1["x1"] + l2["x1"]) / 2, (l1["y1"] + l2["y1"]) / 2)
    me = ((l1["x2"] + l2["x2"]) / 2, (l1["y2"] + l2["y2"]) / 2)
    if math.hypot(me[0] - ms[0], me[1] - ms[1]) < 1e-9:
        return ng("both midpoints are the same point, so there is no line")
    m = g.line_to_dict(ms[0], ms[1], me[0], me[1])
    return ok(f"median line {m['length']:.1f} px long at {g.line_angle(m):.2f} deg",
              [g.line_overlay(l1, (0, 200, 255)), g.line_overlay(l2, (0, 200, 255)), g.line_overlay(m, (0, 255, 0))],
              Median_Line=m, Start_Midpoint=ms, End_Midpoint=me, Angle_Deg=g.line_angle(m))


@define("Calculate Parallel Lines", CAT,
        "Makes a line parallel to another: either through a point that is not on it, or a pair at a set distance either side of it.",
        inputs=[port("Line1", "line", "The line"), port("Point1_Start", "pt", "Line start (By Point)"), port("Point1_End", "pt", "Line end (By Point)"),
                port("Point", "pt", "The point the parallel passes through")],
        outputs=[port("Line_A", "line", "The parallel line (or the one on the left of the original)"), port("Line_B", "line", "The one on the right (Distance method only)"),
                 val("Distance", "How far the parallel is from the original")],
        params={"method": "A Point Outside the Line", "input_mode": "By Coordinate", "line1": [100, 200, 300, 160], "point": [200, 120], "distance": 30.0},
        schema={"method": enum("A Point Outside the Line", "A Distance from the Line"), "input_mode": enum(*MODES), "line1": {"kind": "line"},
                "point": {"kind": "point"}, "distance": num(0, 100000, 0.5, "px", 2)})
def calculate_parallel_lines(t, ctx):
    l = _line_from(t, ctx, 1)
    if l is None:
        return _missing("")
    d = np.array([l["x2"] - l["x1"], l["y2"] - l["y1"]]) / l["length"]
    nrm = np.array([-d[1], d[0]])
    half = l["length"] / 2.0
    if str(t.get_param("method")) == "A Distance from the Line":
        off = float(t.get_param("distance"))
        make = lambda s: g.line_to_dict(l["x1"] + nrm[0] * s, l["y1"] + nrm[1] * s, l["x2"] + nrm[0] * s, l["y2"] + nrm[1] * s)       # noqa: E731
        a_, b_ = make(-off), make(off)
        return ok(f"two parallels {off:g} px either side", [g.line_overlay(l, (0, 200, 255)), g.line_overlay(a_), g.line_overlay(b_)], Line_A=a_, Line_B=b_, Distance=off)
    p = ctx.get("Point") if ctx.get("Point") is not None else t.get_param("point")
    p = t.as_point(p)
    if p is None:
        return err("the point is missing or not a valid x, y pair")
    off = float((np.array(p) - np.array([l["x1"], l["y1"]])) @ nrm)
    mid = np.array(p)
    a_ = g.line_to_dict(mid[0] - d[0] * half, mid[1] - d[1] * half, mid[0] + d[0] * half, mid[1] + d[1] * half)
    return ok(f"parallel through ({p[0]:.1f}, {p[1]:.1f}), {abs(off):.1f} px from the original", [g.line_overlay(l, (0, 200, 255)), g.line_overlay(a_), g.cross_overlay(p[0], p[1], (0, 0, 255), 6)],
              Line_A=a_, Line_B=None, Distance=abs(off))


@define("Find Vertical Line", CAT,
        "Makes a line at a right angle to another: through a given point (and where it meets the line), or the perpendicular bisector that "
        "stands in the middle of the line segment.",
        inputs=[port("Line1", "line", "The line"), port("Point1_Start", "pt", "Line start (By Point)"), port("Point1_End", "pt", "Line end (By Point)"),
                port("Point", "pt", "The point the perpendicular passes through")],
        outputs=[port("Vertical_Line", "line", "The perpendicular line"), port("Foot", "pt", "Where it meets the original line"), val("Distance", "Length of the perpendicular from the point to the line")],
        params={"method": "Point Perpendicular", "input_mode": "By Coordinate", "line1": [100, 200, 300, 160], "point": [200, 120]},
        schema={"method": enum("Point Perpendicular", "Perpendicular Bisector"), "input_mode": enum(*MODES), "line1": {"kind": "line"}, "point": {"kind": "point"}})
def find_vertical_line(t, ctx):
    l = _line_from(t, ctx, 1)
    if l is None:
        return _missing("")
    d = np.array([l["x2"] - l["x1"], l["y2"] - l["y1"]]) / l["length"]
    nrm = np.array([-d[1], d[0]])
    if str(t.get_param("method")) == "Perpendicular Bisector":
        m = np.array([(l["x1"] + l["x2"]) / 2, (l["y1"] + l["y2"]) / 2])
        half = l["length"] / 2.0
        v = g.line_to_dict(m[0] - nrm[0] * half, m[1] - nrm[1] * half, m[0] + nrm[0] * half, m[1] + nrm[1] * half)
        return ok(f"perpendicular bisector through ({m[0]:.1f}, {m[1]:.1f})", [g.line_overlay(l, (0, 200, 255)), g.line_overlay(v)],
                  Vertical_Line=v, Foot=(float(m[0]), float(m[1])), Distance=0.0)
    p = ctx.get("Point") if ctx.get("Point") is not None else t.get_param("point")
    p = t.as_point(p)
    if p is None:
        return err("the point is missing or not a valid x, y pair")
    foot = g.point_line_foot(p, l)
    dist = math.hypot(p[0] - foot[0], p[1] - foot[1])
    if dist < 1e-9:                                                                       # the point is on the line: draw the perpendicular through it
        half = l["length"] / 2.0
        v = g.line_to_dict(p[0] - nrm[0] * half, p[1] - nrm[1] * half, p[0] + nrm[0] * half, p[1] + nrm[1] * half)
    else:
        v = g.line_to_dict(p[0], p[1], foot[0], foot[1])
    return ok(f"perpendicular from ({p[0]:.1f}, {p[1]:.1f}), {dist:.2f} px long, meets the line at ({foot[0]:.1f}, {foot[1]:.1f})",
              [g.line_overlay(l, (0, 200, 255)), g.line_overlay(v), g.cross_overlay(foot[0], foot[1], (0, 0, 255), 6)],
              Vertical_Line=v, Foot=(float(foot[0]), float(foot[1])), Distance=float(dist))
