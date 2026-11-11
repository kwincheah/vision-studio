"""Shared geometry and edge-finding for the VisionMaster-style location and measurement modules.

* ``caliper``      one strip scan across an edge: where along the strip does the brightness step, how strong, which way
* ``scan_edges``   many calipers laid across a region -> a set of edge points
* ``fit_line`` / ``fit_circle`` / ``fit_ellipse``   robust fits with the guide's options: fit mode (least squares, Huber, Tukey),
  reject number and distance to remove
* small line and point helpers (intersection, angle, perpendicular foot, ...)

Angles are in degrees, measured the way the picture is stored (y points down): ``atan2(dy, dx)``.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from apex_vision.core.param_schema import enum, num

DIRECTIONS = ["Left to Right", "Right to Left", "Top to Bottom", "Bottom to Top"]
EDGE_TYPES = ["Strongest Edge", "First Edge", "Last Edge"]
POLARITIES = ["Any", "Dark to Light", "Light to Dark"]
FIT_MODES = ["Least Squares", "Huber", "Tukey"]


def edge_params(**over) -> Dict[str, Any]:
    """The settings every edge-based module shares (the guide's 'running parameters'), with optional different defaults."""
    p = {"edge_type": "Strongest Edge", "edge_polarity": "Any", "edge_threshold": 20, "filter_size": 3, "caliper_number": 16,
         "projection_width": 5, "reject_number": 0, "distance_to_remove": 5.0, "fit_mode": "Least Squares"}
    p.update(over)
    return p


def edge_schema() -> Dict[str, Dict[str, Any]]:
    return {"edge_type": enum(*EDGE_TYPES), "edge_polarity": enum(*POLARITIES), "edge_threshold": num(0, 255), "filter_size": num(1, 50),
            "caliper_number": num(2, 500), "projection_width": num(1, 500, unit="px"), "reject_number": num(0, 200),
            "distance_to_remove": num(0, 1000, 0.5, "px", 1), "fit_mode": enum(*FIT_MODES)}


# ---------------------------------------------------------------------------------------------------------------------------
# calipers
# ---------------------------------------------------------------------------------------------------------------------------
def caliper(gray: np.ndarray, p1: Tuple[float, float], p2: Tuple[float, float], width: int = 5, polarity: str = "Any",
            edge_type: str = "Strongest Edge", threshold: float = 20.0, filter_size: int = 3) -> Optional[Tuple[float, float, float, int]]:
    """Scan the strip from p1 to p2 (``width`` pixels wide, averaged) for a brightness step.

    Returns (x, y, strength, sign) for the chosen edge, or None. ``strength`` is the grey-level step across the edge; ``sign`` is +1 for
    dark-to-light and -1 for light-to-dark as seen travelling from p1 to p2.
    """
    p1, p2 = np.asarray(p1, np.float64), np.asarray(p2, np.float64)
    length = float(np.hypot(*(p2 - p1)))
    if length < 3:
        return None
    n = int(math.ceil(length)) + 1
    d = (p2 - p1) / length
    nrm = np.array([-d[1], d[0]])
    t = np.linspace(0.0, length, n)
    w = max(1, int(width))
    off = np.linspace(-(w - 1) / 2.0, (w - 1) / 2.0, w)
    xs = p1[0] + t[None, :] * d[0] + off[:, None] * nrm[0]
    ys = p1[1] + t[None, :] * d[1] + off[:, None] * nrm[1]
    prof = cv2.remap(gray.astype(np.float32), xs.astype(np.float32), ys.astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE).mean(axis=0)
    k = max(1, int(filter_size))
    if n < 2 * k + 2:
        return None
    c = np.cumsum(np.concatenate([[0.0], prof]))
    idx = np.arange(k, n - k + 1)                                              # step between the k samples before and after position i
    after = (c[np.minimum(idx + k, n)] - c[idx]) / k
    before = (c[idx] - c[idx - k]) / k
    step = after - before
    if polarity == "Dark to Light":
        score = step
    elif polarity == "Light to Dark":
        score = -step
    else:
        score = np.abs(step)
    peaks = [j for j in range(len(score)) if score[j] >= threshold and (j == 0 or score[j] >= score[j - 1]) and (j == len(score) - 1 or score[j] > score[j + 1])]
    if not peaks:
        return None
    if edge_type == "First Edge":
        j = peaks[0]
    elif edge_type == "Last Edge":
        j = peaks[-1]
    else:
        j = max(peaks, key=lambda q: score[q])
    pos = float(idx[j]) - 0.5                                                # the step sits between sample i-1 and sample i
    if 0 < j < len(score) - 1:                                                # sub-pixel: parabola through the peak and its neighbours
        a, b, cc = score[j - 1], score[j], score[j + 1]
        den = a - 2 * b + cc
        if abs(den) > 1e-9:
            pos += float(np.clip(0.5 * (a - cc) / den, -0.5, 0.5))
    pos = min(max(pos, 0.0), length)
    return float(p1[0] + pos * d[0]), float(p1[1] + pos * d[1]), float(abs(step[j])), 1 if step[j] >= 0 else -1


def direction_vector(direction: str) -> Tuple[int, int]:
    return {"Left to Right": (1, 0), "Right to Left": (-1, 0), "Top to Bottom": (0, 1), "Bottom to Top": (0, -1)}.get(direction, (1, 0))


def scan_edges(gray: np.ndarray, roi: Sequence[float], direction: str, n_calipers: int, width: int, polarity: str, edge_type: str,
               threshold: float, filter_size: int) -> List[Tuple[float, float, float, int]]:
    """Lay ``n_calipers`` calipers across the rectangle ``roi`` = [x, y, w, h]; each scans along ``direction``. Returns the edge points found."""
    x, y, w, h = [float(v) for v in roi[:4]]
    dx, dy = direction_vector(direction)
    pts = []
    for i in range(max(1, int(n_calipers))):
        f = (i + 0.5) / max(1, int(n_calipers))
        if dx != 0:                                                           # calipers run horizontally, spread down the region
            yy = y + f * h
            a, b = ((x, yy), (x + w, yy)) if dx > 0 else ((x + w, yy), (x, yy))
        else:
            xx = x + f * w
            a, b = ((xx, y), (xx, y + h)) if dy > 0 else ((xx, y + h), (xx, y))
        r = caliper(gray, a, b, width, polarity, edge_type, threshold, filter_size)
        if r is not None:
            pts.append(r)
    return pts


# ---------------------------------------------------------------------------------------------------------------------------
# robust fitting
# ---------------------------------------------------------------------------------------------------------------------------
def _weights(res: np.ndarray, mode: str) -> np.ndarray:
    if mode == "Least Squares" or len(res) == 0:
        return np.ones(len(res))
    sigma = max(0.3, 1.4826 * float(np.median(np.abs(res - np.median(res)))))
    r = np.abs(res)
    if mode == "Huber":
        k = 1.345 * sigma
        return np.where(r <= k, 1.0, k / np.maximum(r, 1e-12))
    c = 4.685 * sigma
    return np.where(r < c, (1.0 - (r / c) ** 2) ** 2, 0.0)                  # Tukey: far points get no say at all


def _prune(res: np.ndarray, reject: int, dist: float) -> np.ndarray:
    """Boolean keep-mask: drop points farther than ``dist`` (if > 0), then the ``reject`` worst of what is left."""
    keep = np.ones(len(res), bool)
    if dist and dist > 0:
        keep &= np.abs(res) <= dist
    if reject and reject > 0 and keep.sum() > reject + 2:
        worst = np.argsort(-np.where(keep, np.abs(res), -1))[:reject]
        keep[worst] = False
    return keep


def fit_line(points: np.ndarray, mode: str = "Least Squares", reject: int = 0, dist: float = 0.0) -> Optional[Dict[str, Any]]:
    """Orthogonal line fit. Returns {x1,y1,x2,y2,length,angle,inliers,residual} with end points at the extreme inliers, or None."""
    p = np.asarray(points, np.float64).reshape(-1, 2)
    if len(p) < 2:
        return None
    w = np.ones(len(p))
    keep = np.ones(len(p), bool)
    if (reject and reject > 0) or (dist and dist > 0):
        pre = fit_line(p, "Huber", 0, 0.0)                                       # judge outliers against a fit they have not pulled around
        if pre is not None:
            cc, dd = np.array(pre["center"]), np.array(pre["direction"])
            keep = _prune((p - cc) @ np.array([-dd[1], dd[0]]), reject, dist)
    c = d = None
    for rnd in range(8):
        sel = keep & (w > 1e-6)
        if sel.sum() < 2:
            break
        q, ww = p[sel], w[sel]
        c = (q * ww[:, None]).sum(axis=0) / ww.sum()
        cov = ((q - c).T * ww) @ (q - c)
        vals, vecs = np.linalg.eigh(cov)
        d = vecs[:, 1]
        res = (p - c) @ np.array([-d[1], d[0]])
        w = _weights(res, mode)
    if c is None or d is None:
        return None
    res = (p - c) @ np.array([-d[1], d[0]])
    inl = keep & (w > 1e-6)
    t = (p[inl] - c) @ d
    a, b = c + t.min() * d, c + t.max() * d
    ang = math.degrees(math.atan2(d[1], d[0]))
    ang = ((ang + 90.0) % 180.0) - 90.0
    return {"x1": float(a[0]), "y1": float(a[1]), "x2": float(b[0]), "y2": float(b[1]), "length": float(np.hypot(*(b - a))),
            "angle": ang, "inliers": int(inl.sum()), "residual": float(np.sqrt(np.mean(res[inl] ** 2))) if inl.any() else 0.0,
            "center": (float(c[0]), float(c[1])), "direction": (float(d[0]), float(d[1]))}


def fit_circle(points: np.ndarray, mode: str = "Least Squares", reject: int = 0, dist: float = 0.0) -> Optional[Dict[str, Any]]:
    p = np.asarray(points, np.float64).reshape(-1, 2)
    if len(p) < 3:
        return None
    w = np.ones(len(p))
    keep = np.ones(len(p), bool)
    if (reject and reject > 0) or (dist and dist > 0):
        pre = fit_circle(p, "Huber", 0, 0.0)
        if pre is not None:
            keep = _prune(np.hypot(p[:, 0] - pre["cx"], p[:, 1] - pre["cy"]) - pre["r"], reject, dist)
    cx = cy = r = None
    for rnd in range(10):
        sel = keep & (w > 1e-6)
        if sel.sum() < 3:
            break
        q, ww = p[sel], w[sel]
        a = np.column_stack([2 * q[:, 0], 2 * q[:, 1], np.ones(len(q))]) * np.sqrt(ww)[:, None]
        b = (q[:, 0] ** 2 + q[:, 1] ** 2) * np.sqrt(ww)
        try:
            sol, *_ = np.linalg.lstsq(a, b, rcond=None)
        except np.linalg.LinAlgError:
            return None
        cx, cy = float(sol[0]), float(sol[1])
        r2 = sol[2] + cx * cx + cy * cy
        if r2 <= 0:
            return None
        r = math.sqrt(r2)
        res = np.hypot(p[:, 0] - cx, p[:, 1] - cy) - r
        w = _weights(res, mode)
    if r is None:
        return None
    res = np.hypot(p[:, 0] - cx, p[:, 1] - cy) - r
    inl = keep & (w > 1e-6)
    return {"cx": cx, "cy": cy, "r": r, "inliers": int(inl.sum()), "residual": float(np.sqrt(np.mean(res[inl] ** 2))) if inl.any() else 0.0}


def fit_ellipse(points: np.ndarray, reject: int = 0, dist: float = 0.0, mode: str = "Least Squares") -> Optional[Dict[str, Any]]:
    """Ellipse fit (cv2.fitEllipse) with outlier removal: points far from the first fit are dropped and it is fitted again."""
    p = np.asarray(points, np.float32).reshape(-1, 2)
    if len(p) < 5:
        return None
    use = np.ones(len(p), bool)
    best = None
    for rnd in range(4):
        if use.sum() < 5:
            break
        (cx, cy), (da, db), ang = cv2.fitEllipse(p[use])
        a, b = max(da, db) / 2.0, min(da, db) / 2.0
        if b < 1e-6:
            return None
        th = math.radians(ang + (0 if da >= db else 90))
        ct, st = math.cos(th), math.sin(th)
        u = (p[:, 0] - cx) * ct + (p[:, 1] - cy) * st
        v = -(p[:, 0] - cx) * st + (p[:, 1] - cy) * ct
        rad = np.sqrt((u / a) ** 2 + (v / b) ** 2)
        res = (rad - 1.0) * min(a, b)                                          # roughly the distance to the curve, in pixels
        best = {"cx": float(cx), "cy": float(cy), "a": 2 * a, "b": 2 * b, "angle": float(((math.degrees(th) + 90.0) % 180.0) - 90.0),
                "inliers": int(use.sum()), "residual": float(np.sqrt(np.mean(res[use] ** 2)))}
        keep = _prune(res, reject, dist) if rnd == 0 else (np.abs(res) <= max(dist, 1.0) if dist else use)
        if np.array_equal(keep, use):
            break
        use = keep
    return best


# ---------------------------------------------------------------------------------------------------------------------------
# lines and points
# ---------------------------------------------------------------------------------------------------------------------------
def line_to_dict(x1, y1, x2, y2) -> Dict[str, float]:
    return {"x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2), "length": float(math.hypot(x2 - x1, y2 - y1))}


def fit_to_line_dict(f: Dict[str, Any]) -> Dict[str, float]:
    return line_to_dict(f["x1"], f["y1"], f["x2"], f["y2"])


def line_angle(l: Dict[str, float]) -> float:
    a = math.degrees(math.atan2(l["y2"] - l["y1"], l["x2"] - l["x1"]))
    return ((a + 90.0) % 180.0) - 90.0


def intersect(l1: Dict[str, float], l2: Dict[str, float]) -> Optional[Tuple[float, float]]:
    """Where two lines cross (extended to infinity); None if parallel."""
    d1x, d1y = l1["x2"] - l1["x1"], l1["y2"] - l1["y1"]
    d2x, d2y = l2["x2"] - l2["x1"], l2["y2"] - l2["y1"]
    den = d1x * d2y - d1y * d2x
    if abs(den) < 1e-9 * max(1.0, math.hypot(d1x, d1y) * math.hypot(d2x, d2y)):
        return None
    s = ((l2["x1"] - l1["x1"]) * d2y - (l2["y1"] - l1["y1"]) * d2x) / den
    return l1["x1"] + s * d1x, l1["y1"] + s * d1y


def angle_between(l1: Dict[str, float], l2: Dict[str, float]) -> float:
    """Smallest angle between two lines, 0..90 degrees."""
    d = abs(line_angle(l1) - line_angle(l2)) % 180.0
    return min(d, 180.0 - d)


def point_line_foot(pt: Tuple[float, float], l: Dict[str, float]) -> Tuple[float, float]:
    dx, dy = l["x2"] - l["x1"], l["y2"] - l["y1"]
    n2 = dx * dx + dy * dy
    if n2 < 1e-12:
        return l["x1"], l["y1"]
    s = ((pt[0] - l["x1"]) * dx + (pt[1] - l["y1"]) * dy) / n2
    return l["x1"] + s * dx, l["y1"] + s * dy


def line_overlay(l: Dict[str, float], colour=(0, 255, 0), thickness=2) -> Dict[str, Any]:
    return {"type": "line", "pt1": (int(round(l["x1"])), int(round(l["y1"]))), "pt2": (int(round(l["x2"])), int(round(l["y2"]))),
            "color": colour, "thickness": thickness}


def cross_overlay(x: float, y: float, colour=(0, 255, 255), size=5) -> Dict[str, Any]:
    return {"type": "cross", "pt": (int(round(x)), int(round(y))), "size": size, "color": colour}


def clamp_roi(roi: Sequence[float], shape) -> Tuple[float, float, float, float]:
    h, w = shape[:2]
    x, y, rw, rh = [float(v) for v in roi[:4]]
    if rw <= 0 or rh <= 0:                        # no region drawn: the whole picture
        return 0.0, 0.0, float(w), float(h)
    x, y = max(0.0, min(x, w - 2)), max(0.0, min(y, h - 2))
    return x, y, max(2.0, min(rw, w - x)), max(2.0, min(rh, h - y))
