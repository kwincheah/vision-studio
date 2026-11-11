"""VisionMaster guide, chapter "Location": Matrix Circle Search, Ellipse Search, Rect Search, Quadrilateral Search, Peak Search,
Edge Intersection, Parallel Lines Search, Line Group Search and Multi-line Search.

They all work the same way: calipers (strips) scan for brightness steps, the edge points found are fitted robustly with the options the
guide lists (edge type, polarity, threshold, filter size, caliper number, projection width, reject number, distance to remove, fit mode),
and the fitted shapes are reported.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import as_gray, define, err, get_image, img, ng, no_image, ok, port, val

CAT = "Location"


def _edge_args(t) -> Dict[str, Any]:
    return dict(width=int(t.get_param("projection_width")), polarity=str(t.get_param("edge_polarity")), edge_type=str(t.get_param("edge_type")),
                threshold=float(t.get_param("edge_threshold")), filter_size=int(t.get_param("filter_size")))


def _fit_args(t) -> Dict[str, Any]:
    return dict(mode=str(t.get_param("fit_mode")), reject=int(t.get_param("reject_number")), dist=float(t.get_param("distance_to_remove")))


def _pts(found) -> np.ndarray:
    return np.array([[f[0], f[1]] for f in found], np.float64).reshape(-1, 2)


# ---------------------------------------------------------------------------------------------------------------------------
# Matrix Circle Search
# ---------------------------------------------------------------------------------------------------------------------------
def ring_search(gray, cx, cy, rmin, rmax, rays, t) -> Optional[Dict[str, Any]]:
    e = _edge_args(t)
    found = []
    for i in range(int(rays)):
        a = 2 * math.pi * i / rays
        u = (math.cos(a), math.sin(a))
        r = g.caliper(gray, (cx + rmin * u[0], cy + rmin * u[1]), (cx + rmax * u[0], cy + rmax * u[1]), **e)
        if r:
            found.append(r)
    if len(found) < 5:
        return None
    return g.fit_circle(_pts(found), **_fit_args(t))


@define("Matrix Circle Search", CAT,
        "Finds several circles that sit in a grid (rows x columns) inside a region: it searches each cell for a circle with a ring of "
        "calipers and reports every circle with its row and column.",
        inputs=[img()], outputs=[img(), val("Count"), port("Circles", "any", "[{cx, cy, r, row, column}, ...]"),
                                 port("Centers", "any", "[[x, y], ...] in row order"), port("Radii", "any", "Radius of each circle")],
        params={"roi": [50, 50, 300, 200], "array_rows": 2, "array_columns": 3, "min_radius": 8.0, "max_radius": 40.0, "min_count": 1,
                **g.edge_params(caliper_number=24)},
        schema={"roi": {"kind": "rect"}, "array_rows": num(1, 100), "array_columns": num(1, 100), "min_radius": num(1, 5000, 0.5, "px", 1),
                "max_radius": num(2, 5000, 0.5, "px", 1), "min_count": num(0, 10000), **g.edge_schema()})
def matrix_circle_search(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    x, y, w, h = g.clamp_roi(t.get_param("roi"), a.shape)
    rows, cols = int(t.get_param("array_rows")), int(t.get_param("array_columns"))
    rmin, rmax = float(t.get_param("min_radius")), float(t.get_param("max_radius"))
    if rmax <= rmin:
        return err("the maximum radius must be larger than the minimum radius")
    circles, over = [], []
    for r in range(rows):
        for c in range(cols):
            cx, cy = x + (c + 0.5) * w / cols, y + (r + 0.5) * h / rows
            f = ring_search(gray, cx, cy, rmin, min(rmax, 0.5 * min(w / cols, h / rows) * 1.2), int(t.get_param("caliper_number")), t)
            if f and rmin * 0.6 <= f["r"] <= rmax * 1.2 and abs(f["cx"] - cx) <= w / cols and abs(f["cy"] - cy) <= h / rows:
                circles.append({"cx": f["cx"], "cy": f["cy"], "r": f["r"], "row": r, "column": c})
                over.append({"type": "circle", "center": (int(f["cx"]), int(f["cy"])), "radius": int(f["r"]), "color": (0, 255, 0)})
    over.append({"type": "rect", "box": [int(x), int(y), int(w), int(h)], "color": (160, 160, 160)})
    status = ok if len(circles) >= max(0, int(t.get_param("min_count"))) and circles else ng
    return status(f"found {len(circles)} of {rows * cols} circles", over, Image=a, Count=len(circles), Circles=circles,
                  Centers=[[c["cx"], c["cy"]] for c in circles], Radii=[c["r"] for c in circles])


# ---------------------------------------------------------------------------------------------------------------------------
# Ellipse Search
# ---------------------------------------------------------------------------------------------------------------------------
@define("Ellipse Search", CAT,
        "Finds one ellipse: calipers run from an inner to an outer ellipse (both scaled from the region you draw) and the edge points are "
        "fitted to an ellipse. Gives its centre, the two axis lengths and its angle.",
        inputs=[img()], outputs=[img(), val("Center_X"), val("Center_Y"), val("Axis_A", "Long axis length"), val("Axis_B", "Short axis length"),
                                 val("Angle_Deg", "Angle of the long axis"), port("Ellipse", "dict", "{cx, cy, a, b, angle}")],
        params={"roi": [100, 80, 200, 140], "inner_scale": 0.5, "outer_scale": 1.1, **g.edge_params(caliper_number=36, distance_to_remove=6.0)},
        schema={"roi": {"kind": "rect"}, "inner_scale": num(0.05, 1.0, 0.05, decimals=2), "outer_scale": num(0.2, 3.0, 0.05, decimals=2), **g.edge_schema()})
def ellipse_search(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    x, y, w, h = g.clamp_roi(t.get_param("roi"), a.shape)
    cx, cy = x + w / 2.0, y + h / 2.0
    ki, ko = float(t.get_param("inner_scale")), float(t.get_param("outer_scale"))
    if ko <= ki:
        return err("the outer scale must be larger than the inner scale")
    n = int(t.get_param("caliper_number"))
    found = []
    for i in range(n):
        th = 2 * math.pi * i / n
        c, s = math.cos(th), math.sin(th)
        p1 = (cx + ki * (w / 2) * c, cy + ki * (h / 2) * s)
        p2 = (cx + ko * (w / 2) * c, cy + ko * (h / 2) * s)
        r = g.caliper(gray, p1, p2, **_edge_args(t))
        if r:
            found.append(r)
    if len(found) < 5:
        return ng(f"only {len(found)} edge points found, an ellipse needs at least 5", Image=a)
    f = g.fit_ellipse(_pts(found), reject=int(t.get_param("reject_number")), dist=float(t.get_param("distance_to_remove")))
    if f is None:
        return ng("the edge points do not form an ellipse", Image=a)
    ring = []
    th = np.linspace(0, 2 * np.pi, 60)
    ca, sa = math.cos(math.radians(f["angle"])), math.sin(math.radians(f["angle"]))
    pts = [(f["cx"] + (f["a"] / 2) * math.cos(u) * ca - (f["b"] / 2) * math.sin(u) * sa,
            f["cy"] + (f["a"] / 2) * math.cos(u) * sa + (f["b"] / 2) * math.sin(u) * ca) for u in th]
    over = [{"type": "line", "pt1": (int(pts[i][0]), int(pts[i][1])), "pt2": (int(pts[(i + 1) % 60][0]), int(pts[(i + 1) % 60][1])),
             "color": (0, 255, 0), "thickness": 2} for i in range(60)] + [g.cross_overlay(f["cx"], f["cy"], (255, 0, 0), 8)]
    return ok(f"ellipse {f['a']:.1f} x {f['b']:.1f} at ({f['cx']:.1f}, {f['cy']:.1f}), {f['angle']:.1f} deg", over, Image=a, Center_X=f["cx"],
              Center_Y=f["cy"], Axis_A=f["a"], Axis_B=f["b"], Angle_Deg=f["angle"],
              Ellipse={"cx": f["cx"], "cy": f["cy"], "a": f["a"], "b": f["b"], "angle": f["angle"]})


# ---------------------------------------------------------------------------------------------------------------------------
# Rect Search and Quadrilateral Search
# ---------------------------------------------------------------------------------------------------------------------------
def search_quad(gray, quad: np.ndarray, margin: float, t) -> Tuple[List[Optional[Dict[str, float]]], List[int]]:
    """Fit one line along each side of the quadrilateral ``quad`` (4 x 2): calipers cross each side from ``margin`` pixels inside
    to ``margin`` pixels outside."""
    cx, cy = quad.mean(axis=0)
    lines, counts = [], []
    n = int(t.get_param("caliper_number"))
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        d = (b - a) / max(1e-9, np.hypot(*(b - a)))
        nrm = np.array([-d[1], d[0]])
        if (np.array([cx, cy]) - (a + b) / 2.0) @ nrm < 0:                      # make the normal point to the inside
            nrm = -nrm
        found = []
        for k in range(n):
            f = (k + 0.5) / n
            mid = a + (b - a) * f
            r = g.caliper(gray, tuple(mid + nrm * margin), tuple(mid - nrm * margin), **_edge_args(t))
            if r:
                found.append(r)
        counts.append(len(found))
        fit = g.fit_line(_pts(found), **_fit_args(t)) if len(found) >= 2 else None
        lines.append(g.fit_to_line_dict(fit) if fit else None)
    return lines, counts


def _quad_result(a, quad, lines, counts, name):
    if any(l is None for l in lines):
        bad = [i for i, l in enumerate(lines) if l is None]
        return ng(f"no edge line found on side(s) {bad}", Image=a)
    corners = []
    for i in range(4):
        p = g.intersect(lines[i], lines[(i + 1) % 4])
        if p is None:
            return ng("two neighbouring sides are parallel, so there is no corner", Image=a)
        corners.append(p)
    corners = np.array(corners, np.float32)
    (cx, cy), (w, h), ang = cv2.minAreaRect(corners)
    if ang >= 45:
        w, h, ang = h, w, ang - 90.0
    elif ang <= -45:
        w, h, ang = h, w, ang + 90.0
    over = [g.line_overlay(l) for l in lines] + [g.cross_overlay(p[0], p[1], (255, 0, 0), 6) for p in corners]
    return ok(f"{name}: centre ({cx:.1f}, {cy:.1f}), {w:.1f} x {h:.1f}, {-ang:.1f} deg", over, Image=a,
              Center_X=float(cx), Center_Y=float(cy), Width=float(w), Height=float(h), Angle_Deg=float(-ang),
              Corners=[[float(p[0]), float(p[1])] for p in corners], Lines=lines, Box={"cx": float(cx), "cy": float(cy), "w": float(w), "h": float(h), "angle": float(-ang)})


QUAD_OUT = [img(), val("Center_X"), val("Center_Y"), val("Width"), val("Height"), val("Angle_Deg"), port("Corners", "any", "[[x, y] x 4]"),
            port("Lines", "any", "The four edge lines"), port("Box", "dict", "{cx, cy, w, h, angle}")]


@define("Rect Search", CAT,
        "Finds a rectangle: one line is fitted along each of the four sides of the region you draw (searching a band either side of it) and "
        "the corners are where the lines meet. Gives the centre, width, height and angle.",
        inputs=[img()], outputs=QUAD_OUT,
        params={"roi": [100, 80, 240, 160], "roi_angle": 0.0, "search_margin": 20.0, **g.edge_params(caliper_number=16)},
        schema={"roi": {"kind": "rect"}, "roi_angle": num(-360, 360, 0.5, "deg", 2), "search_margin": num(2, 1000, 1, "px", 1), **g.edge_schema()})
def rect_search(t, ctx):
    from apex_vision.tools.vm_image import roi_corners
    a = get_image(ctx)
    if a is None:
        return no_image()
    quad = roi_corners(t.get_param("roi"), float(t.get_param("roi_angle"))).astype(np.float64)
    lines, counts = search_quad(as_gray(a), quad, float(t.get_param("search_margin")), t)
    return _quad_result(a, quad, lines, counts, "rectangle")


@define("Quadrilateral Search", CAT,
        "Finds a four-sided shape of any outline: give the four corners of the region; one line is fitted along each side and the corners "
        "are where neighbouring lines meet.",
        inputs=[img()], outputs=QUAD_OUT,
        params={"quad_points": [[100, 80], [340, 90], [330, 240], [95, 230]], "search_margin": 20.0, **g.edge_params(caliper_number=16)},
        schema={"quad_points": {"kind": "points"}, "search_margin": num(2, 1000, 1, "px", 1), **g.edge_schema()})
def quadrilateral_search(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    q = np.asarray(t.get_param("quad_points"), np.float64).reshape(-1, 2)
    if len(q) != 4:
        return err("the quadrilateral needs exactly 4 corner points")
    lines, counts = search_quad(as_gray(a), q, float(t.get_param("search_margin")), t)
    return _quad_result(a, q, lines, counts, "quadrilateral")


# ---------------------------------------------------------------------------------------------------------------------------
# Peak Search
# ---------------------------------------------------------------------------------------------------------------------------
@define("Peak Search", CAT,
        "Finds the tip of an object: scans across a region, takes the first edge each scan meets, and reports the edge point that lies "
        "nearest the side the scan started from (the peak), with its strength, polarity and distance from that side.",
        inputs=[img()], outputs=[img(), val("Peak_X"), val("Peak_Y"), val("Peak_Score"), port("Peak_Polarity", "str", "Dark to Light or Light to Dark"),
                                 val("Peak_Distance", "Distance from the region's starting side"), val("Edge_Number", "Edge points found")],
        params={"roi": [100, 60, 200, 160], "search_direction": "Top to Bottom", "scan_width": 4, "edge_threshold": 20, "filter_size": 3,
                "edge_polarity": "Any", "edge_type": "First Edge"},
        schema={"roi": {"kind": "rect"}, "search_direction": enum(*g.DIRECTIONS), "scan_width": num(1, 500, unit="px"), "edge_threshold": num(0, 255),
                "filter_size": num(1, 50), "edge_polarity": enum(*g.POLARITIES), "edge_type": enum(*g.EDGE_TYPES)})
def peak_search(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    x, y, w, h = g.clamp_roi(t.get_param("roi"), a.shape)
    d = str(t.get_param("search_direction"))
    horizontal = g.direction_vector(d)[0] != 0
    sw = max(1, int(t.get_param("scan_width")))
    across = h if horizontal else w
    n = max(2, int(across // sw))
    found = g.scan_edges(gray, (x, y, w, h), d, n, sw, str(t.get_param("edge_polarity")), str(t.get_param("edge_type")),
                         float(t.get_param("edge_threshold")), int(t.get_param("filter_size")))
    if not found:
        return ng("no edge found in the region", Image=a, Edge_Number=0)
    dx, dy = g.direction_vector(d)
    start = {"Left to Right": x, "Right to Left": x + w, "Top to Bottom": y, "Bottom to Top": y + h}[d]
    dist = [abs((f[0] if dx else f[1]) - start) for f in found]
    k = int(np.argmin(dist))
    f = found[k]
    over = [{"type": "rect", "box": [int(x), int(y), int(w), int(h)], "color": (160, 160, 160)}] + [g.cross_overlay(p[0], p[1], (0, 255, 255), 2) for p in found] \
        + [g.cross_overlay(f[0], f[1], (0, 0, 255), 9)]
    return ok(f"peak at ({f[0]:.1f}, {f[1]:.1f}), {dist[k]:.1f} px from the start side", over, Image=a, Peak_X=f[0], Peak_Y=f[1], Peak_Score=f[2],
              Peak_Polarity="Dark to Light" if f[3] > 0 else "Light to Dark", Peak_Distance=dist[k], Edge_Number=len(found))


# ---------------------------------------------------------------------------------------------------------------------------
# Edge Intersection
# ---------------------------------------------------------------------------------------------------------------------------
def find_edge_line(gray, roi, direction, t) -> Tuple[Optional[Dict[str, float]], int]:
    e = _edge_args(t)
    found = g.scan_edges(gray, roi, direction, int(t.get_param("caliper_number")), e["width"], e["polarity"], e["edge_type"], e["threshold"], e["filter_size"])
    if len(found) < 2:
        return None, len(found)
    fit = g.fit_line(_pts(found), **_fit_args(t))
    return (g.fit_to_line_dict(fit) if fit else None), len(found)


@define("Edge Intersection", CAT,
        "Finds the corner where two edges meet. Use one region (an edge in each of two directions) or two regions (one edge in each); the "
        "corner is where the two fitted lines cross, even if they do not quite touch.",
        inputs=[img()], outputs=[img(), val("Intersection_X"), val("Intersection_Y"), port("Line_0", "line", "First edge"), port("Line_1", "line", "Second edge"),
                                 val("Line_0_Angle"), val("Line_1_Angle")],
        params={"roi_count": 1, "roi1": [100, 80, 200, 160], "roi2": [100, 80, 200, 160], "direction1": "Left to Right", "direction2": "Top to Bottom",
                **g.edge_params()},
        schema={"roi_count": num(1, 2), "roi1": {"kind": "rect"}, "roi2": {"kind": "rect"}, "direction1": enum(*g.DIRECTIONS),
                "direction2": enum(*g.DIRECTIONS), **g.edge_schema()})
def edge_intersection(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    r1 = g.clamp_roi(t.get_param("roi1"), a.shape)
    r2 = g.clamp_roi(t.get_param("roi2"), a.shape) if int(t.get_param("roi_count")) == 2 else r1
    l1, n1 = find_edge_line(gray, r1, str(t.get_param("direction1")), t)
    l2, n2 = find_edge_line(gray, r2, str(t.get_param("direction2")), t)
    if l1 is None or l2 is None:
        return ng(f"could not find both edges ({n1} and {n2} edge points)", Image=a)
    p = g.intersect(l1, l2)
    if p is None:
        return ng("the two edges are parallel", Image=a, Line_0=l1, Line_1=l2)
    over = [g.line_overlay(l1), g.line_overlay(l2), g.cross_overlay(p[0], p[1], (0, 0, 255), 9)]
    return ok(f"corner at ({p[0]:.1f}, {p[1]:.1f}), edges {g.line_angle(l1):.1f} / {g.line_angle(l2):.1f} deg", over, Image=a, Intersection_X=p[0],
              Intersection_Y=p[1], Line_0=l1, Line_1=l2, Line_0_Angle=g.line_angle(l1), Line_1_Angle=g.line_angle(l2))


# ---------------------------------------------------------------------------------------------------------------------------
# Parallel Lines Search
# ---------------------------------------------------------------------------------------------------------------------------
def caliper_pair(gray, a, b, t, pair_type: str):
    """Two edges of opposite polarity in one strip. Returns ((x, y) of the first, (x, y) of the second) or None."""
    e = _edge_args(t)
    first = g.caliper(gray, a, b, e["width"], e["polarity"], "First Edge" if pair_type != "Last Pair" else "Last Edge", e["threshold"], e["filter_size"])
    if first is None:
        return None
    # the second edge: scan on from the first one, opposite polarity
    opposite = {"Dark to Light": "Light to Dark", "Light to Dark": "Dark to Light"}.get(e["polarity"], "Any")
    pa = np.array(a, float)
    pb = np.array(b, float)
    d = (pb - pa) / max(1e-9, np.hypot(*(pb - pa)))
    if pair_type == "Last Pair":
        second = g.caliper(gray, b, tuple(np.array([first[0], first[1]]) - d * 2), e["width"], opposite, "First Edge", e["threshold"], e["filter_size"])
        if second is None:
            return None
        return (second[0], second[1]), (first[0], first[1])
    start = np.array([first[0], first[1]]) + d * (e["filter_size"] + 2)
    second = g.caliper(gray, tuple(start), b, e["width"], opposite, "Strongest Edge" if pair_type == "Strongest Pair" else "First Edge",
                       e["threshold"], e["filter_size"])
    if second is None:
        return None
    return (first[0], first[1]), (second[0], second[1])


@define("Parallel Lines Search", CAT,
        "Finds two lines that are roughly parallel (a bar, a slot, a cable): at each caliper it takes an edge pair, fits a line through each "
        "side, checks they are parallel within the tolerance, and gives both lines, the centre line between them and their spacing.",
        inputs=[img()], outputs=[img(), port("Line_1", "line", "First line"), port("Line_2", "line", "Second line"), port("Center_Line", "line", "Line half-way between"),
                                 val("Distance", "Spacing between the lines"), val("Angle_Deg", "Angle of the centre line")],
        params={"roi": [100, 80, 240, 160], "search_direction": "Top to Bottom", "edge_pair_type": "Strongest Pair", "max_angle_tolerance": 3.0,
                **g.edge_params(edge_threshold=15)},
        schema={"roi": {"kind": "rect"}, "search_direction": enum(*g.DIRECTIONS), "edge_pair_type": enum("Strongest Pair", "First Pair", "Last Pair"),
                "max_angle_tolerance": num(0, 90, 0.5, "deg", 1), **g.edge_schema()})
def parallel_lines_search(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    x, y, w, h = g.clamp_roi(t.get_param("roi"), a.shape)
    d = str(t.get_param("search_direction"))
    dx, dy = g.direction_vector(d)
    n = int(t.get_param("caliper_number"))
    pa, pb = [], []
    for i in range(n):
        f = (i + 0.5) / n
        if dx:
            yy = y + f * h
            s, e = ((x, yy), (x + w, yy)) if dx > 0 else ((x + w, yy), (x, yy))
        else:
            xx = x + f * w
            s, e = ((xx, y), (xx, y + h)) if dy > 0 else ((xx, y + h), (xx, y))
        r = caliper_pair(gray, s, e, t, str(t.get_param("edge_pair_type")))
        if r:
            pa.append(r[0])
            pb.append(r[1])
    if len(pa) < 2:
        return ng(f"only {len(pa)} edge pairs found", Image=a)
    fa, fb = g.fit_line(np.array(pa), **_fit_args(t)), g.fit_line(np.array(pb), **_fit_args(t))
    if fa is None or fb is None:
        return ng("could not fit the two lines", Image=a)
    l1, l2 = g.fit_to_line_dict(fa), g.fit_to_line_dict(fb)
    diff = g.angle_between(l1, l2)
    if diff > float(t.get_param("max_angle_tolerance")):
        return ng(f"the lines are {diff:.2f} deg apart, more than the {float(t.get_param('max_angle_tolerance')):g} deg allowed", [g.line_overlay(l1, (0, 0, 255)), g.line_overlay(l2, (0, 0, 255))],
                  Image=a, Line_1=l1, Line_2=l2)
    mid = g.line_to_dict((l1["x1"] + l2["x1"]) / 2, (l1["y1"] + l2["y1"]) / 2, (l1["x2"] + l2["x2"]) / 2, (l1["y2"] + l2["y2"]) / 2)
    dist = float(np.mean([abs(((p[0] - l2["x1"]) * (l2["y2"] - l2["y1"]) - (p[1] - l2["y1"]) * (l2["x2"] - l2["x1"])) / max(1e-9, l2["length"])) for p in pa]))
    return ok(f"two lines {dist:.2f} px apart, {diff:.2f} deg off parallel", [g.line_overlay(l1), g.line_overlay(l2), g.line_overlay(mid, (255, 200, 0), 1)],
              Image=a, Line_1=l1, Line_2=l2, Center_Line=mid, Distance=dist, Angle_Deg=g.line_angle(mid))


# ---------------------------------------------------------------------------------------------------------------------------
# Line Group Search
# ---------------------------------------------------------------------------------------------------------------------------
@define("Line Group Search", CAT,
        "Fits one line through edge points taken from several separate stretches: list the segments where the edge should be; each is searched "
        "a band either side, and all points found are combined into a single line.",
        inputs=[img()], outputs=[img(), port("Line", "line", "The combined line"), val("Angle_Deg"), val("Point_Count"), port("Segment_Counts", "any", "Points found per segment")],
        params={"segments": [[100, 150, 220, 152], [300, 154, 420, 156]], "search_band": 15.0, **g.edge_params(caliper_number=10)},
        schema={"segments": {"kind": "json"}, "search_band": num(2, 1000, 1, "px", 1), **g.edge_schema()})
def line_group_search(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    segs = t.get_param("segments")
    try:
        segs = [[float(v) for v in s[:4]] for s in segs]
    except (TypeError, ValueError):
        return err("'segments' must be a list of [x1, y1, x2, y2]")
    band, n = float(t.get_param("search_band")), int(t.get_param("caliper_number"))
    pts, counts = [], []
    for x1, y1, x2, y2 in segs:
        d = np.array([x2 - x1, y2 - y1], float)
        ln = np.hypot(*d)
        if ln < 3:
            counts.append(0)
            continue
        d /= ln
        nrm = np.array([-d[1], d[0]])
        c = 0
        for k in range(n):
            m = np.array([x1, y1]) + (np.array([x2, y2]) - np.array([x1, y1])) * (k + 0.5) / n
            r = g.caliper(gray, tuple(m - nrm * band), tuple(m + nrm * band), **_edge_args(t))
            if r:
                pts.append(r)
                c += 1
        counts.append(c)
    if len(pts) < 2:
        return ng(f"only {len(pts)} edge points found", Image=a, Point_Count=len(pts), Segment_Counts=counts)
    fit = g.fit_line(_pts(pts), **_fit_args(t))
    line = g.fit_to_line_dict(fit)
    over = [{"type": "line", "pt1": (int(s[0]), int(s[1])), "pt2": (int(s[2]), int(s[3])), "color": (160, 160, 160), "thickness": 1} for s in segs] \
        + [g.line_overlay(line)] + [g.cross_overlay(p[0], p[1], (0, 255, 255), 2) for p in pts]
    return ok(f"line through {len(pts)} points from {len(segs)} segments, {g.line_angle(line):.2f} deg", over, Image=a, Line=line,
              Angle_Deg=g.line_angle(line), Point_Count=len(pts), Segment_Counts=counts)


# ---------------------------------------------------------------------------------------------------------------------------
# Multi-line Search
# ---------------------------------------------------------------------------------------------------------------------------
@define("Multi-line Search", CAT,
        "Finds several straight edges in a region at once. Edge points are pulled from the picture's brightness gradient and lines are found "
        "one after another (strongest first), each checked for how much of its length is really covered by edge points.",
        inputs=[img()], outputs=[img(), port("Lines", "any", "[{x1, y1, x2, y2, length, angle, coverage, inliers}, ...]"), val("Count"),
                                 port("Angles", "any", "Angle of each line")],
        params={"roi": [0, 0, 0, 0], "filter_half_width": 2, "projection_length": 5, "threshold_type": "Absolute", "edge_threshold": 25.0,
                "edge_polarity": "Any", "edge_angle_tolerance": 15.0, "edge_distance_tolerance": 2.5, "max_lines": 5, "coverage_rate": 30.0,
                "min_line_length": 20.0, "search_direction_angle": 90.0, "linear_rotation_tolerance": 90.0, "fit_mode": "Least Squares"},
        schema={"roi": {"kind": "rect"}, "filter_half_width": num(1, 50), "projection_length": num(1, 200, unit="px"),
                "threshold_type": enum("Absolute", "Relative"), "edge_threshold": num(0, 255, 0.5, decimals=1),
                "edge_polarity": enum("Any", "Black to White", "White to Black"), "edge_angle_tolerance": num(0, 90, 0.5, "deg", 1),
                "edge_distance_tolerance": num(0.1, 100, 0.1, "px", 1), "max_lines": num(1, 100), "coverage_rate": num(0, 100, 1, "%", 0),
                "min_line_length": num(2, 10000, 1, "px", 0), "search_direction_angle": num(-180, 180, 1, "deg", 0),
                "linear_rotation_tolerance": num(0, 90, 1, "deg", 0), "fit_mode": enum(*g.FIT_MODES)})
def multi_line_search(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    x, y, w, h = [int(v) for v in t.get_param("roi")]
    if w <= 0 or h <= 0:
        x, y, w, h = 0, 0, a.shape[1], a.shape[0]
    else:
        x, y, w, h = [int(v) for v in g.clamp_roi((x, y, w, h), a.shape)]
    sub = gray[y:y + h, x:x + w]
    k = int(t.get_param("filter_half_width")) * 2 + 1
    blur = cv2.GaussianBlur(sub, (k, k), 0).astype(np.float32)
    gx, gy = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3) / 8.0, cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    mag = np.hypot(gx, gy)
    thr = float(t.get_param("edge_threshold"))
    if str(t.get_param("threshold_type")) == "Relative":
        thr = float(mag.max()) * thr / 100.0
    pol = str(t.get_param("edge_polarity"))
    ys, xs = np.nonzero(mag >= thr)
    if len(xs) < 8:
        return ng("no edge points above the threshold", Image=a, Lines=[], Count=0, Angles=[])
    # thin the points: keep local maxima of the gradient along its own direction (non-maximum suppression)
    ang_g = np.arctan2(gy, gx)
    mx = np.cos(ang_g[ys, xs]).round().astype(int)
    my = np.sin(ang_g[ys, xs]).round().astype(int)
    h2, w2 = mag.shape
    n1 = mag[np.clip(ys + my, 0, h2 - 1), np.clip(xs + mx, 0, w2 - 1)]
    n2 = mag[np.clip(ys - my, 0, h2 - 1), np.clip(xs - mx, 0, w2 - 1)]
    keep = (mag[ys, xs] >= n1) & (mag[ys, xs] >= n2)
    ys, xs = ys[keep], xs[keep]
    theta = ang_g[ys, xs]
    sgn = np.sign(gx[ys, xs] * np.cos(theta) + gy[ys, xs] * np.sin(theta))                # +: brightness increases along the gradient
    pts = np.column_stack([xs, ys]).astype(np.float64)
    if len(pts) > 6000:                                                                  # keep it quick on busy pictures
        sel = np.random.default_rng(0).choice(len(pts), 6000, replace=False)
        pts, theta = pts[sel], theta[sel]
    rng = np.random.default_rng(1)
    dist_tol, ang_tol = float(t.get_param("edge_distance_tolerance")), math.radians(float(t.get_param("edge_angle_tolerance")))
    search = math.radians(float(t.get_param("search_direction_angle")))
    rot_tol = math.radians(float(t.get_param("linear_rotation_tolerance")))
    plen = max(1, int(t.get_param("projection_length")))
    min_len, cover_need = float(t.get_param("min_line_length")), float(t.get_param("coverage_rate")) / 100.0
    alive = np.ones(len(pts), bool)
    found = []
    for _ in range(int(t.get_param("max_lines"))):
        idx = np.nonzero(alive)[0]
        if len(idx) < 8:
            break
        best = None
        for _it in range(250):
            i, j = rng.choice(idx, 2, replace=False)
            d = pts[j] - pts[i]
            ln = float(np.hypot(*d))
            if ln < min_len * 0.5:
                continue
            d /= ln
            nrm = np.array([-d[1], d[0]])
            nang = math.atan2(nrm[1], nrm[0])
            if abs(((nang - search + math.pi / 2) % math.pi) - math.pi / 2) > rot_tol:
                continue
            dd = np.abs((pts[idx] - pts[i]) @ nrm)
            da = np.abs(((theta[idx] - nang + math.pi / 2) % math.pi) - math.pi / 2)         # gradient parallel (either way) to the normal
            ok_pt = (dd <= dist_tol) & (da <= ang_tol)
            if pol != "Any":                                                                  # brightness rises / falls along the search direction
                want = 1 if pol == "Black to White" else -1
                ok_pt &= (np.sign(np.cos(theta[idx] - search)) == want)
            n_in = int(ok_pt.sum())
            if n_in < 6 or (best is not None and n_in <= best[0]):
                continue
            tt = (pts[idx[ok_pt]] - pts[i]) @ d
            span = float(tt.max() - tt.min())
            if span < min_len:
                continue
            bins = np.unique(np.floor(tt / plen).astype(int)).size
            cover = min(1.0, bins / max(1.0, span / plen))
            if cover < cover_need:
                continue
            best = (n_in, idx[ok_pt], cover)
        if best is None:
            break
        sel = best[1]
        fit = g.fit_line(pts[sel], mode=str(t.get_param("fit_mode")), reject=0, dist=dist_tol * 2)
        if fit is None:
            alive[sel] = False
            continue
        line = g.fit_to_line_dict(fit)
        line = {k_: (v + x if k_ in ("x1", "x2") else v + y if k_ in ("y1", "y2") else v) for k_, v in line.items()}
        line.update({"angle": g.line_angle(line), "coverage": round(float(best[2]), 3), "inliers": int(fit["inliers"])})
        found.append(line)
        alive[sel] = False
    over = [g.line_overlay(l, (0, 255, 0)) for l in found]
    over.append({"type": "rect", "box": [x, y, w, h], "color": (160, 160, 160)})
    if not found:
        return ng("no straight edge found", over, Image=a, Lines=[], Count=0, Angles=[])
    return ok(f"{len(found)} line(s) found", over, Image=a, Lines=found, Count=len(found), Angles=[l["angle"] for l in found])
