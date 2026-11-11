"""VisionMaster guide, chapter "Defect Detection" (edges): Arc / Linear Edge Defect Detection, Arc-Pair / Line-Pair Defect Detection,
Edge Group / Edge Pair Group Defect Detection, Edge Model / Edge Pair Model Defect Detection, Edge Position Trend Analysis and
Edge Pair Trend Analysis.

All of them lay a row of calipers along a trajectory (a line or an arc), find an edge - or a pair of edges - in each, and judge the
resulting edge profile: how far the edge strays from its own best-fit line or circle (or from a trained model), how wide a pair is,
where the edge is missing.

"Left" and "right" are as seen travelling along the trajectory: from a line's start to its end, and round an arc in the direction of the
angle going up (counterclockwise on the picture). Each caliper is scanned from the right-hand side to the left-hand side, so the edge
polarity is given in that direction.
"""
import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.core.registry import create_tool_instance
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import as_gray, define, err, get_image, img, ng, no_image, ok, port, val
from apex_vision.tools.vm_lines import _line_from

CAT = "Defect Detection"
POL3 = ["Both", "Dark to Light", "Light to Dark"]
TYPES1 = ["Strongest Edge", "First Edge", "Last Edge"]
PAIR_TYPES = ["Widest Edge Pair", "Nearest Edge Pair", "Strongest & Nearest Edge Pair"]
PAIR_TYPES8 = ["Widest Edge Pair", "Narrowest Edge Pair", "Strongest Edge Pair", "Weakest Edge Pair", "First Edge Pair", "Last Edge Pair", "Nearest Edge Pair",
               "Farthest Edge Pair"]
SIDES = ["Both Defects", "Left Defect", "Right Defect"]


def _pol(name: str) -> str:
    return "Any" if name == "Both" else name


# ---------------------------------------------------------------------------------------------------------------------------
# trajectories
# ---------------------------------------------------------------------------------------------------------------------------
class Traj:
    """Station centres along a line or an arc, with the unit direction of travel and the unit vector to the left at each."""

    def __init__(self, pts: np.ndarray, tang: np.ndarray, kind: str, spacing: float, circle: Optional[Tuple[float, float, float]] = None):
        self.pts, self.tang, self.kind, self.spacing, self.circle = pts, tang, kind, spacing, circle
        self.left = np.column_stack([tang[:, 1], -tang[:, 0]])

    def __len__(self) -> int:
        return len(self.pts)

    def transform(self, mm: np.ndarray) -> "Traj":
        pts = self.pts @ mm[:, :2].T + mm[:, 2]
        tang = self.tang @ mm[:, :2].T
        tang = tang / np.maximum(np.hypot(*tang.T), 1e-9)[:, None]
        circ = None
        if self.circle:
            c = np.array(self.circle[:2]) @ mm[:, :2].T + mm[:, 2]
            circ = (float(c[0]), float(c[1]), float(self.circle[2] * np.hypot(mm[0, 0], mm[1, 0])))
        return Traj(pts, tang, self.kind, self.spacing, circ)


def line_traj(p1, p2, spacing: float) -> Optional[Traj]:
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    length = float(np.hypot(*(p2 - p1)))
    if length < 3.0:
        return None
    n = max(2, int(length / max(1.0, spacing)) + 1)
    u = (p2 - p1) / length
    t = np.linspace(0.0, length, n)
    return Traj(p1 + t[:, None] * u, np.tile(u, (n, 1)), "line", length / (n - 1))


def arc_traj(cx: float, cy: float, r: float, a0: float, rng: float, spacing: float) -> Optional[Traj]:
    if r < 2.0 or abs(rng) < 1e-6:
        return None
    arc_len = abs(math.radians(rng)) * r
    n = max(3, int(arc_len / max(1.0, spacing)) + 1)
    th = np.radians(np.linspace(a0, a0 + rng, n))
    pts = np.column_stack([cx + r * np.cos(th), cy - r * np.sin(th)])
    tang = np.column_stack([-np.sin(th), -np.cos(th)]) * (1.0 if rng > 0 else -1.0)
    return Traj(pts, tang, "arc", arc_len / (n - 1), (cx, cy, r))


def follow_matrix(t, ctx, centre: Tuple[float, float]) -> Optional[np.ndarray]:
    """The 2x3 correction from a Position Correction module (a matrix, or dx, dy, angle), or None when there is none."""
    m = ctx.get("Affine_Matrix")
    if m is not None:
        try:
            return np.asarray(m, np.float64).reshape(2, 3)
        except (ValueError, TypeError):
            return None
    if any(ctx.get(k) is not None for k in ("Delta_X", "Delta_Y", "Delta_Angle")):
        mm = cv2.getRotationMatrix2D((float(centre[0]), float(centre[1])), t.as_float(ctx.get("Delta_Angle")), 1.0)
        mm[0, 2] += t.as_float(ctx.get("Delta_X"))
        mm[1, 2] += t.as_float(ctx.get("Delta_Y"))
        return mm
    return None


# ---------------------------------------------------------------------------------------------------------------------------
# finding edges at the stations
# ---------------------------------------------------------------------------------------------------------------------------
def _steps(gray: np.ndarray, p1, p2, width: int, filt: int):
    """(profile positions index, step values, unit direction, length) of the strip p1 -> p2, or None when it is too short."""
    p1, p2 = np.asarray(p1, np.float64), np.asarray(p2, np.float64)
    length = float(np.hypot(*(p2 - p1)))
    if length < 3:
        return None
    n = int(math.ceil(length)) + 1
    d = (p2 - p1) / length
    nrm = np.array([-d[1], d[0]])
    tt = np.linspace(0.0, length, n)
    w = max(1, int(width))
    off = np.linspace(-(w - 1) / 2.0, (w - 1) / 2.0, w)
    xs = p1[0] + tt[None, :] * d[0] + off[:, None] * nrm[0]
    ys = p1[1] + tt[None, :] * d[1] + off[:, None] * nrm[1]
    prof = cv2.remap(gray.astype(np.float32), xs.astype(np.float32), ys.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).mean(axis=0)
    k = max(1, int(filt))
    if n < 2 * k + 2:
        return None
    c = np.cumsum(np.concatenate([[0.0], prof]))
    idx = np.arange(k, n - k + 1)
    step = (c[np.minimum(idx + k, n)] - c[idx]) / k - (c[idx] - c[idx - k]) / k
    return idx, step, d, length, prof


def _peaks(score: np.ndarray, thr: float) -> List[int]:
    return [j for j in range(len(score)) if score[j] >= thr and (j == 0 or score[j] >= score[j - 1]) and (j == len(score) - 1 or score[j] > score[j + 1])]


def _subpixel(score: np.ndarray, j: int, idx: np.ndarray) -> float:
    pos = float(idx[j]) - 0.5
    if 0 < j < len(score) - 1:
        a, b, c = score[j - 1], score[j], score[j + 1]
        den = a - 2 * b + c
        if abs(den) > 1e-9:
            pos += float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
    return pos


def edge_row(gray: np.ndarray, tr: Traj, length: float, height: int, pol: str, etype: str, thr: float, filt: int) -> np.ndarray:
    """For each station the edge as (x, y), with NaN where none was found. Scanned from the right-hand side to the left-hand side."""
    out = np.full((len(tr), 2), np.nan)
    for i in range(len(tr)):
        p1 = tr.pts[i] - tr.left[i] * length / 2.0
        p2 = tr.pts[i] + tr.left[i] * length / 2.0
        r = g.caliper(gray, p1, p2, height, _pol(pol), etype, thr, filt)
        if r is not None:
            out[i] = (r[0], r[1])
    return out


def pair_in_strip(gray: np.ndarray, p1, p2, height: int, pol0: str, pol1: str, kind: str, ideal: float, thr: float, filt: int):
    """The pair of edges (edge 0 first, scanning p1 -> p2) chosen by ``kind`` as (point 0, point 1, mean strength), or None."""
    s = _steps(gray, p1, p2, height, filt)
    if s is None:
        return None
    idx, step, d, ln, _ = s
    sc0 = step if pol0 == "Dark to Light" else -step if pol0 == "Light to Dark" else np.abs(step)
    sc1 = step if pol1 == "Dark to Light" else -step if pol1 == "Light to Dark" else np.abs(step)
    a, b = _peaks(sc0, thr), _peaks(sc1, thr)
    pairs = [(x, y) for x in a for y in b if idx[y] > idx[x] + 1]
    if not pairs:
        return None
    width = lambda q: float(idx[q[1]] - idx[q[0]])  # noqa: E731
    strength = lambda q: float(sc0[q[0]] + sc1[q[1]])  # noqa: E731
    if kind == "Widest Edge Pair":
        best = max(pairs, key=width)
    elif kind == "Narrowest Edge Pair":
        best = min(pairs, key=width)
    elif kind == "Strongest Edge Pair":
        best = max(pairs, key=strength)
    elif kind == "Weakest Edge Pair":
        best = min(pairs, key=strength)
    elif kind == "First Edge Pair":
        best = min(pairs, key=lambda q: idx[q[0]] + idx[q[1]])
    elif kind == "Last Edge Pair":
        best = max(pairs, key=lambda q: idx[q[0]] + idx[q[1]])
    elif kind == "Farthest Edge Pair":
        best = max(pairs, key=lambda q: abs(width(q) - ideal))
    elif kind == "Strongest & Nearest Edge Pair":
        top = max(strength(q) for q in pairs)
        best = min((q for q in pairs if strength(q) >= 0.9 * top), key=lambda q: abs(width(q) - ideal))
    else:                                                                           # Nearest Edge Pair
        best = min(pairs, key=lambda q: abs(width(q) - ideal))
    pa = np.asarray(p1, float) + d * min(max(_subpixel(sc0, best[0], idx), 0.0), ln)
    pb = np.asarray(p1, float) + d * min(max(_subpixel(sc1, best[1], idx), 0.0), ln)
    return pa, pb, strength(best) / 2.0


def pair_row(gray: np.ndarray, tr: Traj, length: float, height: int, pol0: str, pol1: str, kind: str, ideal: float, thr: float, filt: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each station the pair (edge 0, edge 1) found, edge 0 before edge 1 in the scan direction; NaN where there is none."""
    e0 = np.full((len(tr), 2), np.nan)
    e1 = np.full((len(tr), 2), np.nan)
    st = np.zeros(len(tr))
    for i in range(len(tr)):
        r = pair_in_strip(gray, tr.pts[i] - tr.left[i] * length / 2.0, tr.pts[i] + tr.left[i] * length / 2.0, height, pol0, pol1, kind, ideal, thr, filt)
        if r is not None:
            e0[i], e1[i], st[i] = r
    return e0, e1, st


# ---------------------------------------------------------------------------------------------------------------------------
# judging the profile
# ---------------------------------------------------------------------------------------------------------------------------
def _runs(flags: np.ndarray) -> List[Tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(flags) - 1))
    return out


def signed_deviation(tr: Traj, pts: np.ndarray, reject: int, dist: float, mode: str):
    """(deviation of every station's edge from the best-fit line / circle, positive on the left; the fit as a dict) or (None, None)."""
    valid = ~np.isnan(pts[:, 0])
    if valid.sum() < (2 if tr.kind == "line" else 3):
        return None, None
    if tr.kind == "line":
        f = g.fit_line(pts[valid], mode, reject, dist)
        if f is None:
            return None, None
        c, d = np.array(f["center"]), np.array(f["direction"])
        if d @ tr.tang.mean(axis=0) < 0:
            d = -d
        left = np.array([d[1], -d[0]])
        dev = np.full(len(tr), np.nan)
        dev[valid] = (pts[valid] - c) @ left
        return dev, {"line": g.line_to_dict(f["x1"], f["y1"], f["x2"], f["y2"]), "residual": f["residual"], "inliers": f["inliers"]}
    f = g.fit_circle(pts[valid], mode, reject, dist)
    if f is None:
        return None, None
    dev = np.full(len(tr), np.nan)
    rr = np.hypot(pts[valid, 0] - f["cx"], pts[valid, 1] - f["cy"])
    dev[valid] = f["r"] - rr                                                       # travelling counterclockwise on the picture, the left is the inside
    return dev, {"circle": {"cx": f["cx"], "cy": f["cy"], "r": f["r"]}, "residual": f["residual"], "inliers": f["inliers"]}


def _make_defect(kind: str, tr: Traj, a: int, b: int, dev: Optional[np.ndarray], pts: np.ndarray, half_len: float, spacing: float,
                 ref: Optional[np.ndarray] = None) -> Dict[str, Any]:
    idx = np.arange(a, b + 1)
    if kind == "fracture" or dev is None:
        xy = tr.pts[idx]
        pad = half_len
        x0, y0, x1, y1 = xy[:, 0].min() - pad, xy[:, 1].min() - pad, xy[:, 0].max() + pad, xy[:, 1].max() + pad
        depth, area, cen = 0.0, 0.0, tuple(xy.mean(axis=0))
    else:
        d = np.abs(dev[idx])
        worst = int(idx[np.nanargmax(d)])
        xy = pts[idx][~np.isnan(pts[idx][:, 0])]
        if ref is not None:                                                        # the box spans from where the edge should be to where it is
            xy = np.vstack([xy, ref[idx][~np.isnan(ref[idx][:, 0])]])
        x0, y0, x1, y1 = xy[:, 0].min(), xy[:, 1].min(), xy[:, 0].max(), xy[:, 1].max()
        depth, area, cen = float(np.nanmax(d)), float(np.nansum(d) * spacing), (float(pts[worst][0]), float(pts[worst][1]))
    return {"type": kind, "first": int(a), "last": int(b), "size": float((b - a + 1) * spacing), "depth": depth, "area": area, "center": [float(cen[0]), float(cen[1])],
            "box": [float(x0), float(y0), float(max(1.0, x1 - x0)), float(max(1.0, y1 - y0))]}


def judge_edge(tr: Traj, pts: np.ndarray, p: Dict[str, Any]):
    """Defects of one edge profile. Returns (defects, fit dict, deviations) or (None, None, None) when too little of an edge was found."""
    dev, fit = signed_deviation(tr, pts, int(p["reject_number"]), float(p["distance_to_remove"]), str(p["fit_mode"]))
    if dev is None:
        return None, None, None
    thr = float(p["rough_min_distance"])
    side = str(p["defect_polarity"])
    flag = (dev > thr) if side == "Left Defect" else (dev < -thr) if side == "Right Defect" else (np.abs(dev) > thr)
    flag = np.where(np.isnan(dev), False, flag)
    defects = []
    for a, b in _runs(flag):
        sgn = dev[a:b + 1][np.nanargmax(np.abs(dev[a:b + 1]))]
        d = _make_defect("bump left" if sgn > 0 else "bump right", tr, a, b, dev, pts, 0, tr.spacing, pts - dev[:, None] * tr.left)
        defects.append(d)
    if bool(p["fracture_enable"]):
        for a, b in _runs(np.isnan(dev)):
            defects.append(_make_defect("fracture", tr, a, b, None, pts, float(p["caliper_length"]) / 2.0, tr.spacing))
    return _filter_defects(defects, p), fit, dev


def _filter_defects(defects: List[Dict[str, Any]], p: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for d in defects:
        if bool(p["size_enable"]) and d["size"] < float(p["rough_min_size"]):
            continue
        if bool(p["area_enable"]) and d["type"] != "fracture" and d["area"] < float(p["rough_min_area"]):
            continue
        out.append(d)
    return out


def judge_pair(tr: Traj, e0: np.ndarray, e1: np.ndarray, p: Dict[str, Any]):
    """Defects of a pair profile: stations whose width is outside the eligible range, or where no pair was found."""
    valid = ~np.isnan(e0[:, 0]) & ~np.isnan(e1[:, 0])
    if valid.sum() < 2:
        return None, None
    width = np.full(len(tr), np.nan)
    width[valid] = np.hypot(*(e1[valid] - e0[valid]).T)
    lo, hi = float(p["width_min"]), float(p["width_max"])
    mid = (e0 + e1) / 2.0
    tol = float(p.get("track_tolerance", 0.0))
    if tol > 0 and valid.sum() >= 5:                                                # a pair that jumped away from the trail of the others is lost, not a defect
        off = np.where(valid, ((mid - tr.pts) * tr.left).sum(axis=1), np.nan)
        med = np.nanmedian(off)
        lost = valid & (np.abs(off - med) > tol)
        width[lost] = np.nan
        valid &= ~lost
    flag = valid & ((width < lo) | (width > hi))
    defects = []
    for a, b in _runs(flag):
        seg = width[a:b + 1]
        wide = bool(np.nanmean(seg) > hi)
        dev = np.where(np.isnan(width), np.nan, np.where(width > hi, width - hi, np.where(width < lo, lo - width, 0.0)))
        d = _make_defect("too wide" if wide else "too narrow", tr, a, b, dev, mid, 0, tr.spacing)
        defects.append(d)
    if bool(p["fracture_enable"]):
        for a, b in _runs(~valid):
            defects.append(_make_defect("fracture", tr, a, b, None, mid, float(p["caliper_length"]) / 2.0, tr.spacing))
    return _filter_defects(defects, p), width


def defect_overlays(defects: List[Dict[str, Any]], tr: Traj, pts_a: np.ndarray, pts_b: Optional[np.ndarray] = None) -> List[Dict[str, Any]]:
    over: List[Dict[str, Any]] = []
    for i in range(len(tr) - 1):
        over.append({"type": "line", "pt1": (int(tr.pts[i][0]), int(tr.pts[i][1])), "pt2": (int(tr.pts[i + 1][0]), int(tr.pts[i + 1][1])), "color": (120, 120, 120), "thickness": 1})
    for arr in (pts_a, pts_b):
        if arr is not None:
            over += [g.cross_overlay(x, y, (0, 255, 255), 2) for x, y in arr if not np.isnan(x)]
    for d in defects:
        over.append({"type": "rect", "box": [int(v) for v in d["box"]], "color": (0, 0, 255), "label": d["type"]})
    return over


def _summary(defects: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"Defect_Count": len(defects), "Defects": defects, "Defect_Boxes": [d["box"] for d in defects],
            "Max_Depth": max([d["depth"] for d in defects], default=0.0), "Max_Size": max([d["size"] for d in defects], default=0.0),
            "Max_Area": max([d["area"] for d in defects], default=0.0)}


DEFECT_PORTS = [val("Defect_Count"), port("Defects", "any", "[{type, size, depth, area, center, box}, ...]"), port("Defect_Boxes", "any", "[[x, y, w, h], ...]"),
                val("Max_Depth", "Deepest bump or notch, pixels"), val("Max_Size", "Longest defect along the edge, pixels"), val("Max_Area", "Largest defect area, square pixels")]
FOLLOW_PORTS = [port("Delta_X", "val"), port("Delta_Y", "val"), port("Delta_Angle", "val"), port("Affine_Matrix", "any", "2 x 3 matrix from Position Correction")]


def edge_common(**over) -> Dict[str, Any]:
    p = {"roi_mode": "Draw", "edge_type": "Strongest Edge", "edge_polarity": "Both", "filter_size": 3, "contrast_threshold": 20, "caliper_height": 5, "caliper_length": 30,
         "caliper_spacing": 5, "defect_polarity": "Both Defects", "rough_min_distance": 3.0, "size_enable": False, "rough_min_size": 5.0, "area_enable": False,
         "rough_min_area": 10.0, "fracture_enable": True, "reject_number": 0, "distance_to_remove": 5.0, "fit_mode": "Least Squares"}
    p.update(over)
    return p


def edge_common_schema() -> Dict[str, Any]:
    return {"roi_mode": enum("Draw", "Inherit"), "edge_type": enum(*TYPES1), "edge_polarity": enum(*POL3), "filter_size": num(1, 50), "contrast_threshold": num(0, 255),
            "caliper_height": num(1, 500, unit="px"), "caliper_length": num(4, 2000, unit="px"), "caliper_spacing": num(1, 1000, unit="px"), "defect_polarity": enum(*SIDES),
            "rough_min_distance": num(0, 1000, 0.5, "px", 2), "size_enable": {"kind": "bool"}, "rough_min_size": num(0, 100000, 1, "px", 1), "area_enable": {"kind": "bool"},
            "rough_min_area": num(0, 1e9, 1, "px2", 1), "fracture_enable": {"kind": "bool"}, "reject_number": num(0, 200), "distance_to_remove": num(0, 1000, 0.5, "px", 1),
            "fit_mode": enum(*g.FIT_MODES)}


def pair_common(**over) -> Dict[str, Any]:
    p = {"roi_mode": "Draw", "edge_search_type": "Widest Edge Pair", "edge0_polarity": "Dark to Light", "edge1_polarity": "Light to Dark", "filter_size": 3,
         "contrast_threshold": 20, "ideal_width": 20.0, "caliper_height": 5, "caliper_length": 60, "caliper_spacing": 5, "width_min": 15.0, "width_max": 25.0,
         "size_enable": False, "rough_min_size": 5.0, "area_enable": False, "rough_min_area": 10.0, "fracture_enable": True, "track_tolerance": 0.0}
    p.update(over)
    return p


def pair_common_schema() -> Dict[str, Any]:
    return {"roi_mode": enum("Draw", "Inherit"), "edge_search_type": enum(*PAIR_TYPES), "edge0_polarity": enum(*POL3), "edge1_polarity": enum(*POL3), "filter_size": num(1, 50),
            "contrast_threshold": num(0, 255), "ideal_width": num(0, 100000, 1, "px", 2), "caliper_height": num(1, 500, unit="px"), "caliper_length": num(4, 4000, unit="px"),
            "caliper_spacing": num(1, 1000, unit="px"), "width_min": num(0, 100000, 1, "px", 2), "width_max": num(0, 100000, 1, "px", 2), "size_enable": {"kind": "bool"},
            "rough_min_size": num(0, 100000, 1, "px", 1), "area_enable": {"kind": "bool"}, "rough_min_area": num(0, 1e9, 1, "px2", 1), "fracture_enable": {"kind": "bool"},
            "track_tolerance": num(0, 10000, 1, "px", 1)}


def _P(t, names) -> Dict[str, Any]:
    return {k: t.get_param(k) for k in names}


# ---------------------------------------------------------------------------------------------------------------------------
# the trajectory of a tool
# ---------------------------------------------------------------------------------------------------------------------------
LINE_IN = [img(), port("Line1", "line", "Line (Input Mode: By Line)"), port("Point1_Start", "pt", "Line start (By Point)"), port("Point1_End", "pt", "Line end (By Point)")] + FOLLOW_PORTS
LINE_MODES = ["By Line", "By Point", "By Coordinate"]
LINE_PARAMS = {"input_mode": "By Coordinate", "line1": [80, 200, 560, 200]}
LINE_SCHEMA = {"input_mode": enum(*LINE_MODES), "line1": {"kind": "line"}}
ARC_IN = [img(), port("Circle", "circle", "Circle {cx, cy, r} (By Circle)"), port("Angle_Start", "val", "Start angle, degrees"), port("Angle_Range", "val", "Sweep, degrees")] + FOLLOW_PORTS
ARC_PARAMS = {"input_mode": "By Parameter", "circle_x": 320.0, "circle_y": 240.0, "radius": 150.0, "angle_start": 0.0, "angle_range": 360.0}
ARC_SCHEMA = {"input_mode": enum("By Circle", "By Parameter"), "circle_x": num(-1e6, 1e6, 1, "px", 2), "circle_y": num(-1e6, 1e6, 1, "px", 2), "radius": num(2, 1e6, 1, "px", 2),
              "angle_start": num(-720, 720, 1, "deg", 2), "angle_range": num(-720, 720, 1, "deg", 2)}


def get_trajectory(t, ctx, spacing: float, arc: bool):
    """(Traj, error result): the trajectory in the tool's input mode, corrected to follow the part when ROI Area is Inherit."""
    if arc:
        if str(t.get_param("input_mode")) == "By Circle":
            from apex_vision.tools._spec import circle as as_circle
            c = as_circle(ctx.get("Circle"))
            try:
                a0, rg = float(ctx.get("Angle_Start")), float(ctx.get("Angle_Range"))
            except (TypeError, ValueError):
                return None, err("no angle start or sweep chosen: connect them, or switch to By Parameter")
            if c is None:
                return None, err("no circle chosen: connect one, or switch to By Parameter")
            cx, cy, r = c
        else:
            cx, cy, r = float(t.get_param("circle_x")), float(t.get_param("circle_y")), float(t.get_param("radius"))
            a0, rg = float(t.get_param("angle_start")), float(t.get_param("angle_range"))
        if not all(math.isfinite(v) for v in (cx, cy, r, a0, rg)):
            return None, err("the circle and the angles must be numbers")
        tr = arc_traj(cx, cy, r, a0, rg, spacing)
        if tr is None:
            return None, err("the arc is too small, or its sweep is 0")
        centre = (cx, cy)
    else:
        l = _line_from(t, ctx, 1)
        if l is None:
            return None, err("no line chosen, or it has no length: connect it, or type its coordinates")
        tr = line_traj((l["x1"], l["y1"]), (l["x2"], l["y2"]), spacing)
        if tr is None:
            return None, err("the line is too short (under 3 px)")
        centre = ((l["x1"] + l["x2"]) / 2.0, (l["y1"] + l["y2"]) / 2.0)
    if str(t.get_param("roi_mode")) == "Inherit":
        mm = follow_matrix(t, ctx, centre)
        if mm is not None:
            tr = tr.transform(mm)
    return tr, None


# ---------------------------------------------------------------------------------------------------------------------------
# the four tools
# ---------------------------------------------------------------------------------------------------------------------------
EDGE_KEYS = list(edge_common().keys())
PAIR_KEYS = list(pair_common().keys())


def _edge_tool(t, ctx, arc: bool):
    a = get_image(ctx)
    if a is None:
        return no_image()
    p = _P(t, EDGE_KEYS)
    tr, bad = get_trajectory(t, ctx, float(p["caliper_spacing"]), arc)
    if bad:
        return bad
    gray = as_gray(a)
    pts = edge_row(gray, tr, float(p["caliper_length"]), int(p["caliper_height"]), str(p["edge_polarity"]), str(p["edge_type"]), float(p["contrast_threshold"]), int(p["filter_size"]))
    defects, fit, dev = judge_edge(tr, pts, p)
    over0 = defect_overlays([], tr, pts)
    if defects is None:
        return ng("no edge found along the trajectory: check the position, the caliper length and the contrast threshold", over0, Image=a, Defect_Count=0, Defects=[],
                  Defect_Boxes=[], Max_Depth=0.0, Max_Size=0.0, Max_Area=0.0, Edge_Points=[], Edge_Count=0)
    over = defect_overlays(defects, tr, pts)
    found = int((~np.isnan(pts[:, 0])).sum())
    outs = {"Image": a, "Edge_Points": [[float(x), float(y)] for x, y in pts if not np.isnan(x)], "Edge_Count": found, **_summary(defects), "Fit_Residual": fit["residual"]}
    outs["Fit_Line" if "line" in fit else "Fit_Circle"] = fit.get("line") or fit.get("circle")
    fn = ng if defects else ok
    return fn(f"{len(defects)} defect(s)" + (f", deepest {outs['Max_Depth']:.2f} px, longest {outs['Max_Size']:.1f} px" if defects else "") + f"; edge found at {found} of {len(tr)} positions", over, **outs)


OUT_EDGE = DEFECT_PORTS + [port("Edge_Points", "any", "[[x, y], ...]"), val("Edge_Count"), val("Fit_Residual", "RMS distance of the edge points from the fit, pixels"),
                           port("Fit_Line", "line"), port("Fit_Circle", "circle")]


@define("Linear Edge Defect Detection", CAT,
        "Checks a straight edge for bumps, notches and breaks: a row of calipers finds the edge along the line, the best-fit line is drawn through "
        "it, and every stretch that strays further than the minimum distance (on the side you choose) or has no edge is a defect, with its size, "
        "depth and box.",
        inputs=LINE_IN, outputs=[img()] + OUT_EDGE, params={**LINE_PARAMS, **edge_common()}, schema={**LINE_SCHEMA, **edge_common_schema()})
def linear_edge_defect(t, ctx):
    return _edge_tool(t, ctx, False)


@define("Arc Edge Defect Detection", CAT,
        "Checks a circular edge for pits, bumps and breaks: calipers are laid round the arc, the best-fit circle is drawn through the edge, and "
        "every stretch that strays beyond the minimum distance or has no edge is a defect, with its size, depth and box.",
        inputs=ARC_IN, outputs=[img()] + OUT_EDGE, params={**ARC_PARAMS, **edge_common(caliper_length=40, caliper_spacing=6)}, schema={**ARC_SCHEMA, **edge_common_schema()})
def arc_edge_defect(t, ctx):
    return _edge_tool(t, ctx, True)


def _pair_tool(t, ctx, arc: bool):
    a = get_image(ctx)
    if a is None:
        return no_image()
    p = _P(t, PAIR_KEYS)
    if float(p["width_min"]) > float(p["width_max"]):
        return err("the smallest eligible width must not be above the largest")
    tr, bad = get_trajectory(t, ctx, float(p["caliper_spacing"]), arc)
    if bad:
        return bad
    gray = as_gray(a)
    e0, e1, _ = pair_row(gray, tr, float(p["caliper_length"]), int(p["caliper_height"]), _pol(str(p["edge0_polarity"])), _pol(str(p["edge1_polarity"])), str(p["edge_search_type"]),
                         float(p["ideal_width"]), float(p["contrast_threshold"]), int(p["filter_size"]))
    res = judge_pair(tr, e0, e1, p)
    if res[0] is None:
        return ng("no edge pairs found along the trajectory: check the polarities, the caliper length and the contrast threshold", defect_overlays([], tr, e0, e1), Image=a,
                  Defect_Count=0, Defects=[], Defect_Boxes=[], Max_Depth=0.0, Max_Size=0.0, Max_Area=0.0, Widths=[], Pair_Count=0)
    defects, width = res
    ok_w = width[~np.isnan(width)]
    outs = {"Image": a, **_summary(defects), "Widths": [None if np.isnan(w) else float(w) for w in width], "Pair_Count": int(len(ok_w)), "Min_Width": float(ok_w.min()),
            "Max_Width": float(ok_w.max()), "Mean_Width": float(ok_w.mean())}
    fn = ng if defects else ok
    return fn(f"{len(defects)} defect(s); width {outs['Min_Width']:.1f} to {outs['Max_Width']:.1f} px (mean {outs['Mean_Width']:.1f}); pair found at {len(ok_w)} of {len(tr)} positions",
              defect_overlays(defects, tr, e0, e1), **outs)


OUT_PAIR = DEFECT_PORTS + [port("Widths", "any", "Width at each position (None where no pair)"), val("Pair_Count"), val("Min_Width"), val("Max_Width"), val("Mean_Width")]


@define("Line-Pair Defect Detection", CAT,
        "Checks the strip between two straight edges (a rim, a gap, a bar): at each position a pair of edges is found and its width measured; "
        "where the width is outside the eligible range (too narrow or too wide) or no pair is found, that stretch is a defect.",
        inputs=LINE_IN, outputs=[img()] + OUT_PAIR, params={**LINE_PARAMS, **pair_common()}, schema={**LINE_SCHEMA, **pair_common_schema()})
def line_pair_defect(t, ctx):
    return _pair_tool(t, ctx, False)


@define("Arc-Pair Defect Detection", CAT,
        "Checks the ring between two circular edges: at each position round the arc a pair of edges is found and its width measured; where the "
        "width is outside the eligible range or no pair is found, that stretch is a defect.",
        inputs=ARC_IN, outputs=[img()] + OUT_PAIR, params={**ARC_PARAMS, **pair_common(caliper_length=60)}, schema={**ARC_SCHEMA, **pair_common_schema()})
def arc_pair_defect(t, ctx):
    return _pair_tool(t, ctx, True)


# ---------------------------------------------------------------------------------------------------------------------------
# Edge Group / Edge Pair Group
# ---------------------------------------------------------------------------------------------------------------------------
EDGE_TOOLS = ["Linear Edge Defect Detection", "Arc Edge Defect Detection"]
PAIR_TOOLS = ["Line-Pair Defect Detection", "Arc-Pair Defect Detection"]
GROUP_DEFAULT = [{"tool": "Linear Edge Defect Detection", "params": {"line1": [80, 150, 560, 150]}},
                 {"tool": "Linear Edge Defect Detection", "params": {"line1": [80, 330, 560, 330]}}]


def _group(t, ctx, allowed: List[str]):
    a = get_image(ctx)
    if a is None:
        return no_image()
    items = t.get_param("items")
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except ValueError:
            return err("the items must be a list like [{\"tool\": ..., \"params\": {...}}]")
    if not isinstance(items, list) or not items:
        return err("no detections chosen: list them in items")
    if len(items) > 64:
        return err("at most 64 detections can be combined")
    defects: List[Dict[str, Any]] = []
    over: List[Dict[str, Any]] = []
    msgs: List[str] = []
    bad = 0
    for k, item in enumerate(items):
        if not isinstance(item, dict) or str(item.get("tool")) not in allowed:
            return err(f"item {k + 1} must name one of: {', '.join(allowed)}")
        sub = create_tool_instance(str(item["tool"]), f"{t.instance_id}_{k}")
        for name, v in (item.get("params") or {}).items():
            if name in sub.parameters:
                sub.set_param(name, v)
        r = sub.execute({**ctx, "Image": a, "Line1": None, "Circle": None})
        if r.status.name == "ERROR":
            return err(f"item {k + 1} ({item['tool']}): {r.message}")
        for d in r.outputs.get("Defects", []):
            defects.append({**d, "source": k + 1})
        over += r.overlays
        msgs.append(f"{k + 1}: {r.outputs.get('Defect_Count', 0)}")
        bad += 0 if r.status.name == "OK" else 1
    outs = {"Image": a, **_summary(defects), "Items_Failed": bad}
    fn = ng if defects or bad else ok
    return fn(f"{len(defects)} defect(s) in {len(items)} detection(s) ({'; '.join(msgs)})", over, **outs)


@define("Edge Group Defect Detection", CAT,
        "Runs several edge defect detections (Linear Edge and Arc Edge Defect Detection) on one picture and combines their defects. List each "
        "detection with its settings in items; the group is NG if any of them finds a defect.",
        inputs=[img()] + FOLLOW_PORTS, outputs=[img()] + DEFECT_PORTS + [val("Items_Failed", "How many detections found nothing or found defects")],
        params={"items": GROUP_DEFAULT}, schema={"items": {"kind": "json"}})
def edge_group(t, ctx):
    return _group(t, ctx, EDGE_TOOLS)


@define("Edge Pair Group Defect Detection", CAT,
        "Runs several edge-pair defect detections (Line-Pair and Arc-Pair Defect Detection) on one picture and combines their defects. List each "
        "detection with its settings in items; the group is NG if any of them finds a defect.",
        inputs=[img()] + FOLLOW_PORTS, outputs=[img()] + DEFECT_PORTS + [val("Items_Failed", "How many detections found nothing or found defects")],
        params={"items": [{"tool": "Line-Pair Defect Detection", "params": {"line1": [80, 200, 560, 200]}}]}, schema={"items": {"kind": "json"}})
def edge_pair_group(t, ctx):
    return _group(t, ctx, PAIR_TOOLS)


# ---------------------------------------------------------------------------------------------------------------------------
# Edge Model / Edge Pair Model Defect Detection
# ---------------------------------------------------------------------------------------------------------------------------
def _model_path(t) -> Optional[np.ndarray]:
    from apex_vision.tools.vm_calib import as_points
    p = as_points(t.get_param("path_points"))
    if p is None or len(p) < 2:
        return None
    return p


def _model_traj(t, ctx, spacing: float) -> Tuple[Optional[Traj], Optional[Any]]:
    """Stations along the drawn path (a polyline), corrected to follow the part when ROI Area is Inherit."""
    path = _model_path(t)
    if path is None:
        return None, err("no path drawn: give at least two points that follow the edge (path_points)")
    seg = np.hypot(*np.diff(path, axis=0).T)
    total = float(seg.sum())
    if total < 3.0:
        return None, err("the path is too short")
    n = max(2, int(total / max(1.0, spacing)) + 1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    s = np.linspace(0.0, total, n)
    pts = np.column_stack([np.interp(s, cum, path[:, 0]), np.interp(s, cum, path[:, 1])])
    tang = np.gradient(pts, axis=0)
    tang = tang / np.maximum(np.hypot(*tang.T), 1e-9)[:, None]
    tr = Traj(pts, tang, "path", total / (n - 1))
    if str(t.get_param("roi_mode")) == "Inherit":
        ref = t.as_point(t.get_param("reference_point")) or tuple(path.mean(axis=0))
        mm = follow_matrix(t, ctx, ref)
        if mm is not None:
            tr = tr.transform(mm)
    return tr, None


def _get_model(t) -> Optional[Dict[str, Any]]:
    m = t.get_param("model")
    if isinstance(m, str):
        try:
            m = json.loads(m) if m.strip() else None
        except ValueError:
            m = None
    if not m:
        path = str(t.get_param("model_file") or "").strip()
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    m = json.load(f)
            except (OSError, ValueError):
                m = None
    return m if isinstance(m, dict) and "edge" in m else None


MODEL_COMMON = {"mode": "Detect", "path_points": [[80, 200], [560, 200]], "reference_point": [0, 0], "model": {}, "model_file": "", "roi_mode": "Draw", "filter_size": 3,
                "contrast_threshold": 20, "caliper_height": 5, "caliper_length": 40, "caliper_spacing": 5, "location_deviation": 3.0, "fracture_enable": True,
                "hierarchical_enable": True, "hierarchical_height": 2.0, "hierarchical_min_length": 3, "gray_assist": False}
MODEL_SCHEMA = {"mode": enum("Detect", "Train Model", "Clear Model"), "path_points": {"kind": "points"}, "reference_point": {"kind": "point"}, "model": {"kind": "json"},
                "model_file": {"kind": "path", "filters": "Edge models (*.json);;All files (*)"}, "roi_mode": enum("Draw", "Inherit"), "filter_size": num(1, 50),
                "contrast_threshold": num(0, 255), "caliper_height": num(1, 500, unit="px"), "caliper_length": num(4, 4000, unit="px"),
                "caliper_spacing": num(1, 1000, unit="px"), "location_deviation": num(0, 1000, 0.5, "px", 2), "fracture_enable": {"kind": "bool"},
                "hierarchical_enable": {"kind": "bool"}, "hierarchical_height": num(0, 1000, 0.5, "px", 2), "hierarchical_min_length": num(2, 1000),
                "gray_assist": {"kind": "bool"}}


def _save_model(t, model: Dict[str, Any]) -> Optional[str]:
    t.set_param("model", model)
    path = str(t.get_param("model_file") or "").strip()
    if path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(model, f)
        except OSError as e:
            return f"could not write the model file: {e}"
    return None


def _filt(t, tr: Traj) -> int:
    f = int(t.get_param("filter_size"))
    return max(f, int(round(tr.spacing / 2.0))) if bool(t.get_param("gray_assist")) else f


def _offsets(tr: Traj, pts: np.ndarray) -> np.ndarray:
    o = ((pts - tr.pts) * tr.left).sum(axis=1)
    o[np.isnan(pts[:, 0])] = np.nan
    return o


def _compare(t, tr: Traj, off: np.ndarray, model_off: np.ndarray, pts: np.ndarray) -> List[Dict[str, Any]]:
    """Location, fracture and hierarchical (sawtooth) defects of an offset profile against the model's."""
    dev = off - model_off
    thr = float(t.get_param("location_deviation"))
    flag = np.where(np.isnan(dev), False, np.abs(dev) > thr)
    flag &= ~np.isnan(model_off)
    defects = []
    for a, b in _runs(flag):
        defects.append(_make_defect("location deviation", tr, a, b, dev, pts, 0, tr.spacing))
    if bool(t.get_param("fracture_enable")):
        miss = np.isnan(off) & ~np.isnan(model_off)
        for a, b in _runs(miss):
            defects.append(_make_defect("fracture", tr, a, b, None, pts, float(t.get_param("caliper_length")) / 2.0, tr.spacing))
    if bool(t.get_param("hierarchical_enable")):
        jump = np.abs(np.diff(dev))
        step_flag = np.concatenate([[False], np.where(np.isnan(jump), False, jump > float(t.get_param("hierarchical_height")))])
        for a, b in _runs(step_flag):
            if b - a + 1 >= int(t.get_param("hierarchical_min_length")):
                defects.append(_make_defect("hierarchical", tr, max(0, a - 1), b, np.nan_to_num(dev), pts, 0, tr.spacing))
    return defects


MODEL_OUT = [img(), val("Status_Code", "1 trained or OK, 0 problem"), val("Trained", "1 when a model is held")] + DEFECT_PORTS


def _model_tool(t, ctx, pair: bool):
    a = get_image(ctx)
    mode = str(t.get_param("mode"))
    if mode == "Clear Model":
        t.set_param("model", {})
        t.set_param("model_file", "")
        return ok("model cleared", Image=a, Status_Code=1, Trained=0, **_summary([]))
    if a is None:
        return no_image()
    tr, bad = _model_traj(t, ctx, float(t.get_param("caliper_spacing")))
    if bad:
        return bad
    gray = as_gray(a)
    length, height, thr, filt = float(t.get_param("caliper_length")), int(t.get_param("caliper_height")), float(t.get_param("contrast_threshold")), _filt(t, tr)
    if pair:
        e0, e1, _ = pair_row(gray, tr, length, height, _pol(str(t.get_param("edge0_polarity"))), _pol(str(t.get_param("edge1_polarity"))), str(t.get_param("edge_search_type")),
                             float(t.get_param("ideal_width")), thr, filt)
        pts_list = [e0, e1]
    else:
        e = edge_row(gray, tr, length, height, _pol(str(t.get_param("edge_polarity"))), str(t.get_param("edge_type")), thr, filt)
        pts_list = [e]
    offs = [_offsets(tr, p) for p in pts_list]

    def mean_gray(i):
        return float(np.mean([gray[int(np.clip(tr.pts[i][1], 0, gray.shape[0] - 1)), int(np.clip(tr.pts[i][0], 0, gray.shape[1] - 1))]]))

    if mode == "Train Model":
        found = [int((~np.isnan(o)).sum()) for o in offs]
        if min(found) < max(2, len(tr) // 2):
            return ng(f"the edge was found at only {min(found)} of {len(tr)} positions, so a model cannot be trained: adjust the path or the contrast threshold", defect_overlays([], tr, *pts_list),
                      Image=a, Status_Code=0, Trained=0, **_summary([]))
        # the gray level between the edges (pair models) at each position, to compare bubbles against later
        grays = []
        for i in range(len(tr)):
            if pair and not np.isnan(pts_list[0][i][0]) and not np.isnan(pts_list[1][i][0]):
                mid = (pts_list[0][i] + pts_list[1][i]) / 2.0
                grays.append(float(gray[int(np.clip(mid[1], 0, gray.shape[0] - 1)), int(np.clip(mid[0], 0, gray.shape[1] - 1))]))
            else:
                grays.append(None)
        model = {"version": 1, "pair": pair, "spacing": float(tr.spacing), "edge": [[None if np.isnan(v) else float(v) for v in o] for o in offs], "gray": grays}
        problem = _save_model(t, model)
        if problem:
            return err(problem)
        return ok(f"model trained on {len(tr)} positions", defect_overlays([], tr, *pts_list), Image=a, Status_Code=1, Trained=1, **_summary([]))
    model = _get_model(t)
    if model is None:
        return err("no model chosen: train one (Mode: Train Model) or load a model file")
    if bool(model.get("pair")) != pair:
        return err("this model was trained for " + ("a single edge" if not pair else "an edge pair") + ": train or load the right kind")
    me = [np.array([np.nan if v is None else v for v in row], float) for row in model["edge"]]
    if len(me[0]) != len(tr):
        return err(f"the path has {len(tr)} positions but the model has {len(me[0])}: keep the path and the caliper spacing as they were when training")
    defects: List[Dict[str, Any]] = []
    for o, m_, pts in zip(offs, me, pts_list):
        defects += _compare(t, tr, o, m_, pts)
    if pair:
        w_now = offs[1] - offs[0]
        w_mod = me[1] - me[0]
        defects += _bubbles(t, tr, gray, pts_list, model, w_now, w_mod)
    outs = {"Image": a, "Status_Code": 1, "Trained": 1, **_summary(defects)}
    fn = ng if defects else ok
    return fn(f"{len(defects)} defect(s) against the model", defect_overlays(defects, tr, *pts_list), **outs)


def _bubbles(t, tr: Traj, gray: np.ndarray, pts_list, model: Dict[str, Any], w_now: np.ndarray, w_mod: np.ndarray) -> List[Dict[str, Any]]:
    """Bubble defects of a pair model: positions where the mean gray between the edges differs from the model's, or the gray changes abruptly."""
    if not bool(t.get_param("bubble_enable")):
        return []
    e0, e1 = pts_list
    mg = model.get("gray") or []
    flags = np.zeros(len(tr), bool)
    for i in range(len(tr)):
        if np.isnan(e0[i][0]) or np.isnan(e1[i][0]):
            continue
        p1, p2 = e0[i], e1[i]
        s = _steps(gray, p1, p2, int(t.get_param("caliper_height")), 1)
        n = int(max(3, np.hypot(*(p2 - p1))))
        xs = np.linspace(p1[0], p2[0], n).astype(np.float32).reshape(1, -1)
        ys = np.linspace(p1[1], p2[1], n).astype(np.float32).reshape(1, -1)
        prof = cv2.remap(gray.astype(np.float32), xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0]
        inner = prof[2:-2] if n > 8 else prof
        mean_now = float(inner.mean())
        accept = abs(mean_now - mg[i]) > float(t.get_param("grayscale_acceptance")) if i < len(mg) and mg[i] is not None else False
        muts = int((np.abs(np.diff(inner)) > float(t.get_param("grayscale_change"))).sum())
        flags[i] = accept or muts > int(t.get_param("max_mutations"))
    out = []
    for a, b in _runs(flags):
        if b - a + 1 >= int(t.get_param("bubble_length")):
            out.append(_make_defect("bubble", tr, a, b, None, (e0 + e1) / 2.0, float(t.get_param("caliper_length")) / 2.0, tr.spacing))
    return out


@define("Edge Model Defect Detection", CAT,
        "Compares an edge with a trained model of it. Train the model on a good part (the edge is found along the path you draw and remembered), "
        "then detect: an edge position that differs from the model by more than the location deviation, a missing stretch (fracture), and a "
        "sawtooth of steps (hierarchical) are defects.",
        inputs=[img()] + FOLLOW_PORTS, outputs=MODEL_OUT,
        params={**MODEL_COMMON, "edge_type": "Strongest Edge", "edge_polarity": "Both"},
        schema={**MODEL_SCHEMA, "edge_type": enum(*TYPES1), "edge_polarity": enum(*POL3)})
def edge_model_defect(t, ctx):
    return _model_tool(t, ctx, False)


@define("Edge Pair Model Defect Detection", CAT,
        "Compares an edge pair (a strip) with a trained model: both edges are checked as in Edge Model Defect Detection, and bubble defects are "
        "found where the gray level between the edges differs from the model's or changes abruptly.",
        inputs=[img()] + FOLLOW_PORTS, outputs=MODEL_OUT,
        params={**MODEL_COMMON, "edge_search_type": "Widest Edge Pair", "edge0_polarity": "Dark to Light", "edge1_polarity": "Light to Dark", "ideal_width": 20.0,
                "bubble_enable": True, "grayscale_acceptance": 30.0, "grayscale_change": 25.0, "bubble_length": 2, "max_mutations": 2},
        schema={**MODEL_SCHEMA, "edge_search_type": enum(*PAIR_TYPES), "edge0_polarity": enum(*POL3), "edge1_polarity": enum(*POL3), "ideal_width": num(0, 100000, 1, "px", 2),
                "bubble_enable": {"kind": "bool"}, "grayscale_acceptance": num(0, 255), "grayscale_change": num(0, 255), "bubble_length": num(1, 1000), "max_mutations": num(0, 1000)})
def edge_pair_model_defect(t, ctx):
    return _model_tool(t, ctx, True)


# ---------------------------------------------------------------------------------------------------------------------------
# Edge Position Trend Analysis / Edge Pair Trend Analysis
# ---------------------------------------------------------------------------------------------------------------------------
DIRS = ["Top to Bottom", "Left to Right"]
TREND_PORTS = [val("Count", "Points kept"), val("Max_Distance"), val("Min_Distance"), val("Mean_Distance"), port("Max_Point", "pt"), port("Min_Point", "pt"),
               port("Points", "any", "The points kept"), port("Distances", "any", "Distance of each point kept")]


def _distance_filter(d: np.ndarray, low: float, high: float, high_enable: bool) -> np.ndarray:
    """Which distances qualify: between low and high, or - when low is not below high - at most high or at least low."""
    if high_enable:
        high = float(d.mean() + 2.0 * d.std())
    if low < high:
        return (d >= low) & (d <= high)
    return (d <= high) | (d >= low)


def _trend_stations(roi, direction: str, n: int):
    x, y, w, h = [float(v) for v in roi]
    out = []
    for i in range(max(1, n)):
        f = (i + 0.5) / max(1, n)
        if direction == "Top to Bottom":
            xx = x + f * w
            out.append(((xx, y), (xx, y + h)))
        else:
            yy = y + f * h
            out.append(((x, yy), (x + w, yy)))
    return out


def _trend_summary(t, d: np.ndarray, pts: np.ndarray, label: str):
    keep = _distance_filter(d, float(t.get_param("distance_low")), float(t.get_param("distance_high")), bool(t.get_param("high_threshold_enable")))
    if not keep.any():
        return ng(f"{label}: no point qualifies for the distance thresholds", Count=0, Points=[], Distances=[])
    dk, pk = d[keep], pts[keep]
    imax, imin = int(np.argmax(dk)), int(np.argmin(dk))
    over = [g.cross_overlay(x, y, (0, 255, 255), 3) for x, y in pk] + [g.cross_overlay(*pk[imax], (0, 0, 255), 7), g.cross_overlay(*pk[imin], (0, 255, 0), 7)]
    return ok(f"{len(dk)} point(s): distance {dk.min():.2f} to {dk.max():.2f}, mean {dk.mean():.2f}", over, Count=int(len(dk)), Max_Distance=float(dk.max()),
              Min_Distance=float(dk.min()), Mean_Distance=float(dk.mean()), Max_Point=(float(pk[imax][0]), float(pk[imax][1])), Min_Point=(float(pk[imin][0]), float(pk[imin][1])),
              Points=pk.tolist(), Distances=dk.tolist())


TREND_PARAMS = {"roi": [100, 100, 300, 200], "search_direction": "Top to Bottom", "caliper_number": 20, "caliper_width": 5, "filter_size": 3, "edge_threshold": 20,
                "distance_low": 0.0, "distance_high": 1000.0, "high_threshold_enable": False}
TREND_SCHEMA = {"roi": {"kind": "rect"}, "search_direction": enum(*DIRS), "caliper_number": num(2, 500), "caliper_width": num(1, 500, unit="px"), "filter_size": num(1, 50),
                "edge_threshold": num(0, 255), "distance_low": num(0, 1e6, 1, "px", 2), "distance_high": num(0, 1e6, 1, "px", 2), "high_threshold_enable": {"kind": "bool"}}


@define("Edge Position Trend Analysis", CAT,
        "Studies how an edge sits across a region: a row of calipers finds one edge point each, and the distance of every point from the region's "
        "start side (top or left) is measured. Points whose distance fits the thresholds are kept, and the largest, smallest and mean distances "
        "and their points are reported.",
        inputs=[img()], outputs=[img()] + TREND_PORTS + [val("Found", "Calipers that found an edge")],
        params={**TREND_PARAMS, "edge_type": "Strongest Edge", "edge_polarity": "Both"}, schema={**TREND_SCHEMA, "edge_type": enum(*TYPES1), "edge_polarity": enum(*POL3)})
def edge_trend(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    roi = g.clamp_roi(t.get_param("roi"), a.shape)
    if roi[2] < 4 or roi[3] < 4:
        return err("the region is too small: choose a larger region")
    gray = as_gray(a)
    direction = str(t.get_param("search_direction"))
    pts, dist = [], []
    for p1, p2 in _trend_stations(roi, direction, int(t.get_param("caliper_number"))):
        r = g.caliper(gray, p1, p2, int(t.get_param("caliper_width")), _pol(str(t.get_param("edge_polarity"))), str(t.get_param("edge_type")), float(t.get_param("edge_threshold")),
                      int(t.get_param("filter_size")))
        if r is not None:
            pts.append((r[0], r[1]))
            dist.append(abs(r[1] - roi[1]) if direction == "Top to Bottom" else abs(r[0] - roi[0]))
    if not pts:
        return ng("no edge found in the region: check the contrast threshold and the direction", Image=a, Count=0, Found=0, Points=[], Distances=[])
    res = _trend_summary(t, np.array(dist), np.array(pts), "edge")
    res.outputs["Image"] = a
    res.outputs["Found"] = len(pts)
    res.overlays = [{"type": "rect", "box": [int(v) for v in roi], "color": (160, 160, 160)}] + res.overlays
    return res


@define("Edge Pair Trend Analysis", CAT,
        "Studies a strip across a region: a row of calipers finds one edge pair each and measures its width. Pairs whose width fits the "
        "thresholds are kept, and the widest, narrowest and mean widths and their pairs are reported.",
        inputs=[img()], outputs=[img()] + TREND_PORTS + [val("Found", "Calipers that found a pair"), port("Pairs", "any", "[[x0, y0, x1, y1], ...] for the points kept")],
        params={**TREND_PARAMS, "edge_type": "Widest Edge Pair", "edge0_polarity": "Dark to Light", "edge1_polarity": "Light to Dark", "ideal_width": 20.0},
        schema={**TREND_SCHEMA, "edge_type": enum(*PAIR_TYPES8), "edge0_polarity": enum(*POL3), "edge1_polarity": enum(*POL3), "ideal_width": num(0, 100000, 1, "px", 2)})
def edge_pair_trend(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    roi = g.clamp_roi(t.get_param("roi"), a.shape)
    if roi[2] < 4 or roi[3] < 4:
        return err("the region is too small: choose a larger region")
    gray = as_gray(a)
    direction = str(t.get_param("search_direction"))
    pairs, widths = [], []
    for p1, p2 in _trend_stations(roi, direction, int(t.get_param("caliper_number"))):
        r = pair_in_strip(gray, p1, p2, int(t.get_param("caliper_width")), _pol(str(t.get_param("edge0_polarity"))), _pol(str(t.get_param("edge1_polarity"))),
                          str(t.get_param("edge_type")), float(t.get_param("ideal_width")), float(t.get_param("edge_threshold")), int(t.get_param("filter_size")))
        if r is not None:
            pairs.append((r[0], r[1]))
            widths.append(float(np.hypot(*(r[1] - r[0]))))
    if not pairs:
        return ng("no edge pair found in the region: check the polarities and the contrast threshold", Image=a, Count=0, Found=0, Points=[], Distances=[], Pairs=[])
    mids = np.array([(p + q) / 2.0 for p, q in pairs])
    res = _trend_summary(t, np.array(widths), mids, "pair")
    keep = _distance_filter(np.array(widths), float(t.get_param("distance_low")), float(t.get_param("distance_high")), bool(t.get_param("high_threshold_enable")))
    res.outputs["Image"] = a
    res.outputs["Found"] = len(pairs)
    res.outputs["Pairs"] = [[float(p[0]), float(p[1]), float(q[0]), float(q[1])] for (p, q), k in zip(pairs, keep) if k]
    res.overlays = [{"type": "rect", "box": [int(v) for v in roi], "color": (160, 160, 160)}] + res.overlays
    return res
