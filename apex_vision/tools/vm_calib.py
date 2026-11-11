"""VisionMaster guide, chapter "Calibration": the shared maths, the calibration file, and the calibration modules.

A calibration is a 3x3 matrix that carries an image point to a physical point (``image -> world``). It is kept in a small JSON
calibration file (and travels between modules as a dictionary on the ``Calibration`` port). The fit supports the guide's three degrees
of freedom (similarity, affine, perspective) and its weighting functions (least squares, Huber, Tukey, RANSAC).

Files written by VisionMaster itself (``.iWcal`` / its XML) are a proprietary layout and are not read here; calibrate again with these
modules, or use ``Load Calibration`` on a file written by them.
"""
import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import as_gray, define, err, get_image, img, ng, no_image, ok, port, val

CAT = "Calibration"
DOFS = ["Similarity (scale, rotation, translation)", "Affine (adds aspect ratio and skew)", "Perspective (adds projection)"]
WEIGHTS = ["Least Squares", "Huber", "Tukey", "RANSAC"]
FORMAT = "apex-calibration"
_MIN_POINTS = (2, 3, 4)


# ---------------------------------------------------------------------------------------------------------------------------
# the maths
# ---------------------------------------------------------------------------------------------------------------------------
def as_points(v: Any) -> Optional[np.ndarray]:
    """A list of (x, y) pairs as an (n, 2) float array, or None when it is not one."""
    try:
        a = np.asarray(v, dtype=float)
    except (TypeError, ValueError):
        return None
    if a.ndim != 2 or a.shape[1] < 2 or a.shape[0] == 0 or not np.all(np.isfinite(a[:, :2])):
        return None
    return a[:, :2].copy()


def apply_matrix(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.hstack([np.atleast_2d(pts), np.ones((np.atleast_2d(pts).shape[0], 1))]) @ np.asarray(m, float).T
    w = np.where(np.abs(p[:, 2]) < 1e-12, 1e-12, p[:, 2])
    return p[:, :2] / w[:, None]


def _weights(res: np.ndarray, mode: str, coeff: float) -> np.ndarray:
    if mode in ("Least Squares", "RANSAC") or res.size == 0:
        return np.ones(res.shape)
    med = np.median(res)
    sigma = max(1.4826 * float(np.median(np.abs(res - med))), 1e-9)
    u = res / sigma
    if mode == "Huber":
        k = coeff if coeff > 0 else 1.345
        return np.where(u <= k, 1.0, k / np.maximum(u, 1e-12))
    k = coeff if coeff > 0 else 4.685
    t = u / k
    return np.where(t < 1.0, (1.0 - t * t) ** 2, 0.0)


def _fit_once(src: np.ndarray, dst: np.ndarray, dof: int, w: np.ndarray) -> Optional[np.ndarray]:
    """Weighted fit of one transform family; None when the points cannot determine it."""
    w = np.maximum(w, 0.0)
    if w.sum() <= 1e-12 or int((w > 1e-9).sum()) < _MIN_POINTS[dof]:
        return None
    ws = w / w.sum()
    cs, cd = ws @ src, ws @ dst
    s0, d0 = src - cs, dst - cd
    if np.linalg.matrix_rank(s0[w > 1e-9], tol=1e-9 * max(1.0, np.abs(s0).max())) < (1 if dof == 0 else 2) and dof != 0:
        return None
    if dof == 0:
        best = None
        for flip in (1.0, -1.0):                                                           # a reflection happens when the physical Y points the other way
            d1 = d0 * np.array([1.0, flip])
            h = (s0 * ws[:, None]).T @ d1
            u, sv, vt = np.linalg.svd(h)
            dd = np.eye(2)
            if np.linalg.det(vt.T @ u.T) < 0:
                dd[1, 1] = -1
            r = vt.T @ dd @ u.T
            var = float((ws * (s0 ** 2).sum(1)).sum())
            if var < 1e-18:
                return None
            sc = float(np.trace(np.diag(sv) @ dd) / var)
            lin = sc * np.diag([1.0, flip]) @ r
            sse = float((ws * ((s0 @ lin.T - d0) ** 2).sum(1)).sum())
            if best is None or sse < best[0]:
                best = (sse, lin)
        lin = best[1]
        m = np.eye(3)
        m[:2, :2] = lin
        m[:2, 2] = cd - lin @ cs
        return m
    if dof == 1:
        a = np.hstack([src, np.ones((len(src), 1))])
        sw = np.sqrt(w)[:, None]
        sol, _, rank, _ = np.linalg.lstsq(a * sw, dst * sw, rcond=None)
        if rank < 3:
            return None
        m = np.eye(3)
        m[:2, :] = sol.T
        return m
    keep = w > 0.2 * w.max()
    if keep.sum() < 4:
        return None
    h, _ = cv2.findHomography(src[keep].astype(np.float64), dst[keep].astype(np.float64), 0)
    return None if h is None or not np.all(np.isfinite(h)) else h / h[2, 2] if abs(h[2, 2]) > 1e-12 else h


def fit_transform(src: np.ndarray, dst: np.ndarray, dof: int = 1, weight: str = "Least Squares", coeff: float = 0.0, threshold: float = 3.0,
                  rate: float = 0.8) -> Tuple[Optional[np.ndarray], np.ndarray]:
    """Fit ``dst ~ M(src)``. Returns (3x3 matrix or None, per-point residual in destination units)."""
    n = len(src)
    if n < _MIN_POINTS[dof] or len(dst) != n:
        return None, np.full(n, np.nan)
    if weight == "RANSAC":
        rng = np.random.default_rng(12345)
        k = _MIN_POINTS[dof]
        best, best_in = None, None
        for _ in range(200):
            idx = rng.choice(n, k, replace=False)
            m = _fit_once(src[idx], dst[idx], dof, np.ones(k))
            if m is None:
                continue
            inl = np.hypot(*(apply_matrix(m, src) - dst).T) <= threshold
            if best_in is None or inl.sum() > best_in.sum():
                best, best_in = m, inl
        if best_in is None or best_in.sum() < max(k, int(math.ceil(rate * 0.5 * n))):
            return None, np.full(n, np.nan)
        m = _fit_once(src[best_in], dst[best_in], dof, np.ones(int(best_in.sum())))
        if m is None:
            return None, np.full(n, np.nan)
        return m, np.hypot(*(apply_matrix(m, src) - dst).T)
    w = np.ones(n)
    m = None
    for _ in range(12 if weight != "Least Squares" else 1):
        m_new = _fit_once(src, dst, dof, w)
        if m_new is None:
            break
        m = m_new
        res = np.hypot(*(apply_matrix(m, src) - dst).T)
        w_new = _weights(res, weight, coeff)
        if np.allclose(w_new, w, atol=1e-6):
            break
        w = w_new
    if m is None:
        return None, np.full(n, np.nan)
    return m, np.hypot(*(apply_matrix(m, src) - dst).T)


def decompose(m_img_to_world: np.ndarray) -> Dict[str, float]:
    """The guide's output values, measured on the world -> image direction (the unit length in the world as pixels, and so on)."""
    inv = np.linalg.inv(m_img_to_world)
    inv = inv / inv[2, 2] if abs(inv[2, 2]) > 1e-12 else inv
    a = inv[:2, :2]
    sx, sy = float(np.hypot(a[0, 0], a[1, 0])), float(np.hypot(a[0, 1], a[1, 1]))
    ax, ay = math.atan2(a[1, 0], a[0, 0]), math.atan2(a[1, 1], a[0, 1])
    sign = 1.0 if np.linalg.det(a) >= 0 else -1.0
    skew = (ay - ax - sign * math.pi / 2 + math.pi) % (2 * math.pi) - math.pi
    scale = sx if sx > 1e-12 else 1.0
    return {"scale": scale, "scale_y": sy, "pixel_accuracy": 1.0 / scale, "translate_x": float(inv[0, 2]), "translate_y": float(inv[1, 2]),
            "rotation": float(ax), "skew": float(skew), "aspect": float(sy / sx) if sx > 1e-12 else 0.0}


def local_scale(m: np.ndarray, at: Tuple[float, float] = (0.0, 0.0)) -> float:
    """Physical length of one pixel near ``at`` (the average of the two directions)."""
    p = np.array([[at[0], at[1]], [at[0] + 1, at[1]], [at[0], at[1] + 1]], float)
    q = apply_matrix(m, p)
    return float((np.hypot(*(q[1] - q[0])) + np.hypot(*(q[2] - q[0]))) / 2)


def rotation_angle_deg(m: np.ndarray) -> float:
    """How far the matrix turns a direction (degrees), measured on the image X axis."""
    q = apply_matrix(m, np.array([[0.0, 0.0], [1.0, 0.0]]))
    return math.degrees(math.atan2(q[1][1] - q[0][1], q[1][0] - q[0][0]))


# ---------------------------------------------------------------------------------------------------------------------------
# the calibration file / dictionary
# ---------------------------------------------------------------------------------------------------------------------------
def make_calibration(m: np.ndarray, kind: str, **extra) -> Dict[str, Any]:
    d = decompose(m)
    cal = {"format": FORMAT, "version": 1, "kind": kind, "matrix": np.asarray(m, float).tolist(), **d}
    cal.update(extra)
    return cal


def calibration_matrix(cal: Any) -> Optional[np.ndarray]:
    if not isinstance(cal, dict):
        return None
    try:
        m = np.asarray(cal.get("matrix"), float)
    except (TypeError, ValueError):
        return None
    if m.shape != (3, 3) or not np.all(np.isfinite(m)) or abs(np.linalg.det(m)) < 1e-18:
        return None
    return m


def save_calibration(cal: Dict[str, Any], path: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cal, f, indent=2)


def load_calibration(path: str) -> Dict[str, Any]:
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"calibration file not found: {path!r}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cal = json.load(f)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("this is not a calibration file written by these modules (files from VisionMaster itself cannot be read)")
    if not isinstance(cal, dict) or cal.get("format") != FORMAT or calibration_matrix(cal) is None:
        raise ValueError("this is not a calibration file written by these modules (files from VisionMaster itself cannot be read)")
    return cal


class CalCache:
    """Remembers the last file read, and re-reads it only when the refresh signal is non-zero (or the file is new)."""

    def __init__(self) -> None:
        self.path, self.stamp, self.cal = "", None, None

    def get(self, path: str, refresh: Any) -> Dict[str, Any]:
        stamp = os.path.getmtime(path) if path and os.path.isfile(path) else None
        same = path == self.path and self.cal is not None
        reload_ = (not same) or (refresh not in (None, "", 0, "0", False) and stamp != self.stamp)
        if reload_:
            self.cal = load_calibration(path)
            self.path, self.stamp = path, stamp
        return self.cal


def calibration_for(tool, ctx: Dict[str, Any], port_name: str = "Calibration", path_param: str = "calibration_file") -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(calibration, error text): from the port first, then from the file path."""
    cal = ctx.get(port_name)
    if cal is not None:
        if calibration_matrix(cal) is None:
            return None, "the connected calibration is not valid"
        return cal, None
    path = str(tool.get_param(path_param) or "").strip()
    if not path:
        return None, "no calibration: connect a calibration module or choose a calibration file"
    cache = getattr(tool, "_cal_cache", None) or CalCache()
    tool._cal_cache = cache
    try:
        return cache.get(path, ctx.get("Refresh")), None
    except (OSError, ValueError) as e:
        return None, str(e)


# ---------------------------------------------------------------------------------------------------------------------------
# calibration boards
# ---------------------------------------------------------------------------------------------------------------------------
BOARDS = ["Checkerboard", "Circle Grid"]


def find_board(gray: np.ndarray, kind: str, cols: int, rows: int, dark_dots: bool = True, contrast: float = 0.0, median: bool = False,
               subpix: int = 0) -> Optional[np.ndarray]:
    """Inner corners (or dot centres) in row-major order as (cols*rows, 2), or None."""
    size = (cols, rows)
    if median:
        gray = cv2.medianBlur(gray, 3)
    if kind == "Circle Grid":
        p = cv2.SimpleBlobDetector_Params()
        p.filterByColor, p.blobColor = True, 0 if dark_dots else 255
        p.filterByArea, p.minArea, p.maxArea = True, 20, 200000
        p.filterByCircularity, p.minCircularity = True, 0.6
        det = cv2.SimpleBlobDetector_create(p)
        found, c = cv2.findCirclesGrid(gray, size, flags=cv2.CALIB_CB_SYMMETRIC_GRID, blobDetector=det)
        return c.reshape(-1, 2).astype(float) if found else None
    found, c = cv2.findChessboardCorners(gray, size, cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not found:
        try:
            found, c = cv2.findChessboardCornersSB(gray, size)
        except cv2.error:
            found = False
    if not found:
        return None
    c = c.reshape(-1, 1, 2).astype(np.float32)
    if contrast > 0:                                                                       # the dark and light squares must differ at least this much
        xs, ys = c.reshape(-1, 2)[:, 0], c.reshape(-1, 2)[:, 1]
        patch = gray[max(0, int(ys.min())):int(ys.max()) + 1, max(0, int(xs.min())):int(xs.max()) + 1]
        if patch.size and float(patch.max()) - float(patch.min()) < contrast:
            return None
    wsz = subpix if subpix >= 2 else max(3, int(round(np.median(np.hypot(*np.diff(c.reshape(rows, cols, 2)[0], axis=0).T)) / 10)) if cols > 1 else 5)
    wsz = min(wsz, 15)
    c = cv2.cornerSubPix(gray, c, (wsz, wsz), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001))
    return c.reshape(-1, 2).astype(float)


def board_lattice(cols: int, rows: int) -> np.ndarray:
    """Integer (i, j) of each point in the same row-major order as ``find_board``."""
    jj, ii = np.mgrid[0:rows, 0:cols]
    return np.stack([ii.ravel(), jj.ravel()], axis=1).astype(float)


def consistent_order(corners: np.ndarray, cols: int, rows: int) -> np.ndarray:
    """The detector can number a board from either end; make the first point the top-left one so lattice indices mean the same each time."""
    grid = corners.reshape(rows, cols, 2)
    if grid[0, 0].sum() > grid[-1, -1].sum():
        grid = grid[::-1, ::-1]
    return grid.reshape(-1, 2)


def physical_of(lattice: np.ndarray, size: float, origin: Tuple[float, float], angle_deg: float, left_hand: bool) -> np.ndarray:
    p = (lattice - np.array(origin)) * size
    if left_hand:
        p = p * np.array([1.0, -1.0])
    a = math.radians(angle_deg)
    r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return p @ r.T


# ---------------------------------------------------------------------------------------------------------------------------
# the robot's calibration walk
# ---------------------------------------------------------------------------------------------------------------------------
def motion_points(n: int, fx: float, fy: float, ox: float, oy: float, first: str, commutation: int) -> List[Tuple[float, float]]:
    """Where the robot stands at each of ``n`` calibration positions: it steps ``commutation`` positions along the first axis, takes one
    step along the other, comes back along the first, and so on (9 positions with a commutation of 3 make a 3 x 3 snake)."""
    pts: List[Tuple[float, float]] = []
    x, y = fx, fy
    run, direction = 0, 1.0
    x_first = not str(first).upper().startswith("Y")
    run_len = max(1, int(commutation)) if commutation and commutation > 0 else max(1, n)
    for i in range(n):
        pts.append((x, y))
        run += 1
        if i == n - 1:
            break
        if run >= run_len:
            if x_first:
                y += oy
            else:
                x += ox
            direction, run = -direction, 0
        elif x_first:
            x += direction * ox
        else:
            y += direction * oy
    return pts


def fit_circle_centre(pts: np.ndarray) -> Optional[Tuple[float, float, float, float]]:
    """(cx, cy, r, mean error) of the circle through 3+ points (algebraic fit, then a few Gauss-Newton steps)."""
    if len(pts) < 3:
        return None
    x, y = pts[:, 0], pts[:, 1]
    sv = np.linalg.svd(pts - pts.mean(axis=0), compute_uv=False)
    if sv[0] < 1e-9 or sv[1] / sv[0] < 1e-3:                                               # in a line: no circle
        return None
    a = np.column_stack([2 * x, 2 * y, np.ones(len(x))])
    sol, *_ = np.linalg.lstsq(a, x * x + y * y, rcond=None)
    cx, cy = float(sol[0]), float(sol[1])
    r2 = sol[2] + cx * cx + cy * cy
    if not np.isfinite(r2) or r2 <= 0:
        return None
    r = math.sqrt(r2)
    span = float(np.ptp(pts, axis=0).max())
    if span < 1e-9 or r > 200.0 * span:                                                    # points in a line are a circle of endless radius
        return None
    for _ in range(10):
        d = np.hypot(x - cx, y - cy)
        d = np.maximum(d, 1e-12)
        j = np.column_stack([(cx - x) / d, (cy - y) / d, -np.ones(len(x))])
        step, *_ = np.linalg.lstsq(j, -(d - r), rcond=None)
        cx, cy, r = cx + step[0], cy + step[1], r + step[2]
        if np.abs(step).max() < 1e-9:
            break
    err_ = float(np.mean(np.abs(np.hypot(x - cx, y - cy) - r)))
    return cx, cy, float(r), err_


MOTION_PARAMS = {"fiducial_x": 0.0, "fiducial_y": 0.0, "offset_x": 5.0, "offset_y": 5.0, "movement_first": "X First", "commutation_times": 3,
                 "fiducial_angle": -10.0, "angle_offset": 10.0}
MOTION_SCHEMA = {"fiducial_x": num(-1e6, 1e6, 1, "mm", 3), "fiducial_y": num(-1e6, 1e6, 1, "mm", 3), "offset_x": num(-1e6, 1e6, 1, "mm", 3),
                 "offset_y": num(-1e6, 1e6, 1, "mm", 3), "movement_first": enum("X First", "Y First"), "commutation_times": num(0, 100),
                 "fiducial_angle": num(-360, 360, 1, "deg", 2), "angle_offset": num(-360, 360, 1, "deg", 2)}
FIT_PARAMS = {"dof": DOFS[1], "weighting": "Least Squares", "weight_coeff": 0.0, "distance_threshold": 3.0, "sampling_rate": 0.8}
FIT_SCHEMA = {"dof": enum(*DOFS), "weighting": enum(*WEIGHTS), "weight_coeff": num(0, 100, 0.1, decimals=3),
              "distance_threshold": num(0.0001, 100000, 0.5, decimals=3), "sampling_rate": num(0.1, 1.0, 0.05, decimals=2)}


def _dof_index(t) -> int:
    d = str(t.get_param("dof"))
    return DOFS.index(d) if d in DOFS else 1


def _fit(t, src, dst):
    return fit_transform(src, dst, _dof_index(t), str(t.get_param("weighting")), float(t.get_param("weight_coeff")),
                         float(t.get_param("distance_threshold")), float(t.get_param("sampling_rate")))


def _result_outputs(cal: Dict[str, Any], m: np.ndarray, **more) -> Dict[str, Any]:
    return {"Calibration": cal, "Matrix": m.tolist(), "Scale": cal["scale"], "Pixel_Accuracy": cal["pixel_accuracy"], "Translation_X": cal["translate_x"],
            "Translation_Y": cal["translate_y"], "Rotation": cal["rotation"], "Skew": cal["skew"], "Aspect_Ratio": cal["aspect"], **more}


RESULT_PORTS = [port("Calibration", "dict", "The calibration, to connect to Calibration Transformation and the alignment modules"), port("Matrix", "any", "Image to physical 3 x 3 matrix"),
                val("Scale", "Pixels per physical unit"), val("Pixel_Accuracy", "Physical size of one pixel"), val("Translation_X"), val("Translation_Y"),
                val("Rotation", "Radians"), val("Skew", "Radians"), val("Aspect_Ratio")]


def _maybe_save(t, cal) -> Optional[str]:
    path = str(t.get_param("save_path") or "").strip()
    if not path or not bool(t.get_param("update_file")):
        return None
    try:
        save_calibration(cal, path)
    except OSError as e:
        return f"could not write the calibration file: {e}"
    return None


SAVE_PARAMS = {"save_path": "", "update_file": False}
SAVE_SCHEMA = {"save_path": {"kind": "path", "filters": "Calibration files (*.json);;All files (*)"}}


# ---------------------------------------------------------------------------------------------------------------------------
# CalibBoard Calibration
# ---------------------------------------------------------------------------------------------------------------------------
@define("CalibBoard Calibration", CAT,
        "Calibrates the camera from a picture of a calibration board (checkerboard or circle grid) of known size: finds the corners or dot "
        "centres, and builds the matrix that turns picture coordinates into millimetres. Gives the calibration error, scale and pixel size, "
        "and writes a calibration file for Calibration Transformation.",
        inputs=[img()], outputs=[img(), val("Status", "1 when calibrated"), val("Calibration_Error", "Mean distance in pixels between the found points and the model"),
                                 val("Point_Count")] + RESULT_PORTS,
        params={"board_type": "Checkerboard", "columns": 9, "rows": 6, "physical_size": 10.0, "origin_x": 0, "origin_y": 0, "rotation_angle": 0.0,
                "coordinate_system": "Right-handed", "dot_type": "Dark on Light", "gray_contrast": 0.0, "median_filter": False, "subpixel_window": 0,
                **FIT_PARAMS, **SAVE_PARAMS},
        schema={"board_type": enum(*BOARDS), "columns": num(2, 100), "rows": num(2, 100), "physical_size": num(0.0001, 100000, 1, "mm", 4), "origin_x": num(0, 99),
                "origin_y": num(0, 99), "rotation_angle": num(-360, 360, 1, "deg", 2), "coordinate_system": enum("Right-handed", "Left-handed"),
                "dot_type": enum("Dark on Light", "Light on Dark"), "gray_contrast": num(0, 255, 1), "median_filter": {"kind": "bool"},
                "subpixel_window": num(0, 15, 1), **FIT_SCHEMA, **SAVE_SCHEMA})
def calib_board(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    cols, rows = int(t.get_param("columns")), int(t.get_param("rows"))
    pts = find_board(gray, str(t.get_param("board_type")), cols, rows, str(t.get_param("dot_type")).startswith("Dark"), float(t.get_param("gray_contrast")),
                     bool(t.get_param("median_filter")), int(t.get_param("subpixel_window")))
    if pts is None:
        return ng(f"no {cols} x {rows} {str(t.get_param('board_type')).lower()} found: check the board type, its size and the lighting", Status=0, Image=a)
    pts = consistent_order(pts, cols, rows)
    world = physical_of(board_lattice(cols, rows), float(t.get_param("physical_size")), (float(t.get_param("origin_x")), float(t.get_param("origin_y"))),
                        float(t.get_param("rotation_angle")), str(t.get_param("coordinate_system")).startswith("Left"))
    m, _ = _fit(t, pts, world)
    if m is None:
        return ng("the board points do not fix a calibration", Status=0, Image=a)
    back = apply_matrix(np.linalg.inv(m), world)
    error = float(np.mean(np.hypot(*(back - pts).T)))
    cal = make_calibration(m, "board", error=error, points=len(pts))
    problem = _maybe_save(t, cal)
    if problem:
        return err(problem)
    over = [{"type": "circle", "center": (int(round(x)), int(round(y))), "radius": 3, "color": (0, 255, 0)} for x, y in pts]
    over.append({"type": "text", "text": f"error {error:.3f}px  {cal['pixel_accuracy']:.4f}/px", "pt": (10, 24), "color": (0, 255, 255)})
    return ok(f"calibrated from {len(pts)} points; error {error:.3f} px; one pixel is {cal['pixel_accuracy']:.4f}", over, Image=a, Status=1, Calibration_Error=error,
              Point_Count=len(pts), **_result_outputs(cal, m))


# ---------------------------------------------------------------------------------------------------------------------------
# Camera Mapping
# ---------------------------------------------------------------------------------------------------------------------------
@define("Camera Mapping", CAT,
        "Finds how two camera pictures relate: from the same features seen by both cameras (2 to 8 pairs of points) it builds the matrix that "
        "turns the running camera's coordinates into the demonstration camera's, and reports scale, shift, rotation, skew and aspect.",
        inputs=[port("Points_Demo", "any", "Points seen by the demonstration camera [[x, y], ...]"), port("Points_Run", "any", "The same points seen by the running camera")],
        outputs=[val("Status"), val("Calibration_Error", "Mean distance in the running camera's pixels")] + RESULT_PORTS,
        params={"input_mode": "By Coordinate", "demo_points": [[100, 100], [400, 100], [400, 300], [100, 300]], "run_points": [[110, 105], [412, 99], [405, 302], [103, 309]],
                **FIT_PARAMS, **SAVE_PARAMS},
        schema={"input_mode": enum("By Point", "By Coordinate"), "demo_points": {"kind": "points"}, "run_points": {"kind": "points"}, **FIT_SCHEMA, **SAVE_SCHEMA})
def camera_mapping(t, ctx):
    by_port = str(t.get_param("input_mode")) == "By Point"
    demo = as_points(ctx.get("Points_Demo") if by_port else t.get_param("demo_points"))
    run = as_points(ctx.get("Points_Run") if by_port else t.get_param("run_points"))
    if demo is None or run is None:
        return err("both point lists are needed: connect them, or type the points")
    if len(demo) != len(run):
        return err(f"the lists must pair up: {len(demo)} demonstration points but {len(run)} running points")
    if not 2 <= len(demo) <= 8:
        return err("use between 2 and 8 pairs of points")
    m, _ = _fit(t, run, demo)                                                             # run (the "image") -> demo (the "world")
    if m is None:
        return ng(f"these points cannot fix a {str(t.get_param('dof')).split(' (')[0].lower()} mapping: use more points or spread them out", Status=0)
    back = apply_matrix(np.linalg.inv(m), demo)
    error = float(np.mean(np.hypot(*(back - run).T)))
    cal = make_calibration(m, "mapping", error=error, points=len(demo))
    problem = _maybe_save(t, cal)
    if problem:
        return err(problem)
    return ok(f"mapped from {len(demo)} pairs; error {error:.3f} px", Status=1, Calibration_Error=error, **_result_outputs(cal, m))


# ---------------------------------------------------------------------------------------------------------------------------
# Rotation Calibration
# ---------------------------------------------------------------------------------------------------------------------------
@define("Rotation Calibration", CAT,
        "Finds the centre a mechanism turns about: the same feature is seen after each of 3 to 16 equal turns, and a circle is fitted through "
        "the positions. Gives the centre in the picture and, with a calibration, in physical units, with the fitting errors.",
        inputs=[port("Point", "pt", "Feature point in this picture"), port("Calibration", "dict", "Image to physical calibration (optional)"),
                port("Clear", "bool", "Start again"), port("Refresh", "val", "Reload the calibration file when not 0")],
        outputs=[val("Status", "1 when finished"), val("Remaining", "Turns still to capture"), port("Image_Center", "pt", "Centre of rotation in the picture"),
                 port("Physical_Center", "pt", "Centre of rotation in physical units"), val("Pixel_Error", "Mean distance of the points from the circle, pixels"),
                 val("Real_Error", "The same in physical units"), val("Angle_Error", "Mean difference from the stated turn angle, degrees"), val("Radius"),
                 port("Points", "any", "Points captured so far")],
        params={"input_mode": "By Coordinate", "point_x": 0.0, "point_y": 0.0, "accumulate": True, "rotation_times": 3, "rotation_angle": 10.0, "calibration_file": "",
                "image_points": [[400, 300], [380, 360], [330, 395]]},
        schema={"input_mode": enum("By Point", "By Coordinate"), "point_x": num(-1e6, 1e6, 1, "px", 3), "point_y": num(-1e6, 1e6, 1, "px", 3),
                "accumulate": {"kind": "bool"}, "rotation_times": num(3, 16), "rotation_angle": num(-360, 360, 1, "deg", 2),
                "calibration_file": {"kind": "path", "filters": "Calibration files (*.json);;All files (*)"}, "image_points": {"kind": "points"}})
def rotation_calibration(t, ctx):
    state = getattr(t, "_rot", None)
    if state is None or ctx.get("Clear"):
        state = t._rot = []
    n = int(t.get_param("rotation_times"))
    by_port = str(t.get_param("input_mode")) == "By Point"
    if bool(t.get_param("accumulate")):
        p = t.as_point(ctx.get("Point")) if by_port else (float(t.get_param("point_x")), float(t.get_param("point_y")))
        if p is None or not all(math.isfinite(v) for v in p):
            return err("no feature point: connect one, or type its coordinates")
        state.append(p)
        del state[:-n]
        pts = np.array(state, float)
    else:
        pts = as_points(t.get_param("image_points"))
        if pts is None:
            return err("type the points of the turns (at least 3)")
    if len(pts) < min(n, 3) or len(pts) < 3:
        return ng(f"{n - len(pts)} more turn(s) to capture", Status=0, Remaining=max(0, n - len(pts)), Points=pts.tolist())
    fit = fit_circle_centre(pts)
    if fit is None:
        return ng("the points do not lie on a circle: the feature must turn about one centre", Status=0, Remaining=max(0, n - len(pts)))
    cx, cy, r, e = fit
    ang = []
    for i in range(1, len(pts)):
        a0 = math.atan2(pts[i - 1][1] - cy, pts[i - 1][0] - cx)
        a1 = math.atan2(pts[i][1] - cy, pts[i][0] - cx)
        ang.append(abs((math.degrees(a1 - a0) + 180) % 360 - 180))
    step = abs(float(t.get_param("rotation_angle")))
    aerr = float(np.mean(np.abs(np.array(ang) - step))) if ang and step > 0 else 0.0
    cal, _ = calibration_for(t, ctx)
    phys, real = None, None
    if cal is not None:
        m = calibration_matrix(cal)
        phys = tuple(apply_matrix(m, np.array([[cx, cy]]))[0])
        real = e * local_scale(m, (cx, cy))
    over = [{"type": "circle", "center": (int(round(cx)), int(round(cy))), "radius": max(1, int(round(r))), "color": (0, 255, 255)}, g.cross_overlay(cx, cy, (0, 0, 255), 8)] + \
           [g.cross_overlay(x, y, (0, 255, 0), 4) for x, y in pts]
    done = len(pts) >= n
    return ok(f"rotation centre ({cx:.2f}, {cy:.2f}), radius {r:.1f}, error {e:.3f} px" + ("" if done else f"; {n - len(pts)} more turn(s) planned"), over, Status=1 if done else 0,
              Remaining=max(0, n - len(pts)), Image_Center=(cx, cy), Physical_Center=phys, Pixel_Error=e, Real_Error=real, Angle_Error=aerr, Radius=r, Points=pts.tolist())


# ---------------------------------------------------------------------------------------------------------------------------
# Translation and Rotation Calibration
# ---------------------------------------------------------------------------------------------------------------------------
def _tr_total(t) -> Tuple[int, int, bool]:
    nt = int(t.get_param("translation_times"))
    rot = str(t.get_param("calibration_type")).startswith("Translation and")
    return nt, (int(t.get_param("rotation_times")) if rot else 0), rot


def _solve_translation_rotation(t, img_t: np.ndarray, phys_t: np.ndarray, img_r: np.ndarray, rot: bool):
    m, res = _fit(t, img_t, phys_t)
    if m is None:
        return None, "the translation points do not fix a calibration: move in two different directions"
    cal_extra: Dict[str, Any] = {"camera_mode": str(t.get_param("camera_mode")), "points": int(len(img_t))}
    pix_err = float(np.mean(np.hypot(*(apply_matrix(np.linalg.inv(m), phys_t) - img_t).T)))
    cal_extra["translate_pixel_error"] = pix_err
    cal_extra["translate_real_error"] = float(np.mean(res))
    cal_extra["error"] = pix_err
    if rot and len(img_r) >= 3:
        c = fit_circle_centre(img_r)
        if c is None:
            return None, "the rotation points do not lie on a circle: check the image points and the angles"
        cx, cy, r, e = c
        cal_extra["rotation_center_image"] = [cx, cy]
        cal_extra["rotation_center_world"] = apply_matrix(m, np.array([[cx, cy]]))[0].tolist()
        cal_extra["rotate_pixel_error"] = e
        cal_extra["rotate_real_error"] = e * local_scale(m, (cx, cy))
    return make_calibration(m, "translation-rotation" if rot else "translation", **cal_extra), None


@define("Translation and Rotation Calibration", CAT,
        "Calibrates a camera against a robot or stage: the robot steps through a pattern of positions (a snake over a grid) and a picture is "
        "taken at each; for a mechanism that turns about an axis away from the tool, a few more pictures are taken while it turns. Builds the "
        "image-to-physical matrix and the centre of rotation, and writes a calibration file. With trigger acquisition each run adds one picture.",
        inputs=[port("Point", "pt", "Feature point in this picture"), port("Angle", "val", "Feature angle in this picture (deg)"),
                port("Physical_Point", "pt", "Robot position now (optional: otherwise worked out from the walk settings)"),
                port("Physical_Angle", "val", "Robot angle now (deg)"), port("Clear", "bool", "Start again")],
        outputs=[val("Status", "1 when calibrated"), val("Remaining", "Pictures still to capture"), val("Translate_Pixel_Error"), val("Translate_Real_Error"),
                 val("Rotate_Pixel_Error"), val("Rotate_Real_Error"), port("Image_Center", "pt", "Centre of rotation in the picture"),
                 port("Physical_Center", "pt", "Centre of rotation in physical units"), port("Image_Points", "any"), port("Physical_Points", "any")] + RESULT_PORTS,
        params={"calibration_type": "Translation and Rotation", "points_acquisition": "Trigger", "camera_mode": "Static Camera Above", "input_mode": "By Coordinate",
                "point_x": 0.0, "point_y": 0.0, "translation_times": 9, "rotation_times": 3, **MOTION_PARAMS,
                "image_points": [], "physical_points": [], **FIT_PARAMS, **SAVE_PARAMS},
        schema={"calibration_type": enum("Translation", "Translation and Rotation"), "points_acquisition": enum("Trigger", "Manual Input"),
                "camera_mode": enum("Static Camera Above", "Static Camera Below", "Dynamic Camera"), "input_mode": enum("By Point", "By Coordinate"),
                "point_x": num(-1e6, 1e6, 1, "px", 3), "point_y": num(-1e6, 1e6, 1, "px", 3), "translation_times": num(4, 16), "rotation_times": num(3, 16),
                **MOTION_SCHEMA, "image_points": {"kind": "points"}, "physical_points": {"kind": "points"}, **FIT_SCHEMA, **SAVE_SCHEMA})
def translation_rotation_calibration(t, ctx):
    nt, nr, rot = _tr_total(t)
    total = nt + nr
    walk = motion_points(nt, float(t.get_param("fiducial_x")), float(t.get_param("fiducial_y")), float(t.get_param("offset_x")), float(t.get_param("offset_y")),
                         str(t.get_param("movement_first")), int(t.get_param("commutation_times")))
    centre_idx = min(4, nt - 1)
    if str(t.get_param("points_acquisition")) == "Manual Input":
        pts = as_points(t.get_param("image_points"))
        if pts is None:
            return err("type the image points (translation ones first, then the turns)")
        phys = as_points(t.get_param("physical_points"))
        if phys is None:
            phys = np.array(walk + [walk[centre_idx]] * nr, float)
        if len(phys) < len(pts):
            return err("fewer physical points than image points")
        img_all, phys_all = pts, phys[:len(pts)]
    else:
        st = getattr(t, "_trc", None)
        if st is None or ctx.get("Clear"):
            st = t._trc = {"img": [], "phys": [], "ang": []}
        by_port = str(t.get_param("input_mode")) == "By Point"
        p = t.as_point(ctx.get("Point")) if by_port else (float(t.get_param("point_x")), float(t.get_param("point_y")))
        if p is None or not all(math.isfinite(v) for v in p):
            return err("no feature point: connect one, or type its coordinates")
        k = len(st["img"])
        if k >= total:                                                                      # a new round starts on the next picture
            st["img"], st["phys"], st["ang"], k = [], [], [], 0
        pp = t.as_point(ctx.get("Physical_Point"))
        if pp is None:
            pp = walk[k] if k < nt else walk[centre_idx]
        st["img"].append(p)
        st["phys"].append(pp)
        st["ang"].append(ctx.get("Physical_Angle"))
        img_all, phys_all = np.array(st["img"], float), np.array(st["phys"], float)
    have = len(img_all)
    if have < total and str(t.get_param("points_acquisition")) != "Manual Input":
        return ng(f"{total - have} more picture(s) to capture", Status=0, Remaining=total - have, Image_Points=img_all.tolist(), Physical_Points=phys_all.tolist())
    if have < nt:
        return err(f"need at least {nt} translation points, have {have}")
    cal, why = _solve_translation_rotation(t, img_all[:nt], phys_all[:nt], img_all[nt:nt + nr] if rot else np.zeros((0, 2)), rot)
    if cal is None:
        return ng(why, Status=0, Remaining=0)
    m = calibration_matrix(cal)
    problem = _maybe_save(t, cal)
    if problem:
        return err(problem)
    over = [g.cross_overlay(x, y, (0, 255, 0), 5) for x, y in img_all]
    if cal.get("rotation_center_image"):
        c = cal["rotation_center_image"]
        over.append(g.cross_overlay(c[0], c[1], (0, 0, 255), 9))
    return ok(f"calibrated: translation error {cal['translate_real_error']:.4f}, pixel {cal['pixel_accuracy']:.4f}/px"
              + (f"; rotation centre ({c[0]:.1f}, {c[1]:.1f})" if cal.get("rotation_center_image") else ""), over, Status=1, Remaining=0,
              Translate_Pixel_Error=cal["translate_pixel_error"], Translate_Real_Error=cal["translate_real_error"], Rotate_Pixel_Error=cal.get("rotate_pixel_error"),
              Rotate_Real_Error=cal.get("rotate_real_error"), Image_Center=tuple(cal["rotation_center_image"]) if cal.get("rotation_center_image") else None,
              Physical_Center=tuple(cal["rotation_center_world"]) if cal.get("rotation_center_world") else None, Image_Points=img_all.tolist(),
              Physical_Points=phys_all.tolist(), **_result_outputs(cal, m))


# ---------------------------------------------------------------------------------------------------------------------------
# N-Image Calibration
# ---------------------------------------------------------------------------------------------------------------------------
@define("N-Image Calibration", CAT,
        "Calibrates from several pictures of one calibration board as the robot moves it (or the camera) by known steps: every corner of every "
        "picture gives an image point and a physical point, so the matrix is well determined. The last pictures can be taken while it turns, "
        "which gives the centre of rotation. Each run adds one picture.",
        inputs=[img(), port("Physical_Point", "pt", "Robot position now (optional)"), port("Clear", "bool", "Start again")],
        outputs=[img(), val("Status"), val("Remaining"), val("Translate_Pixel_Error"), val("Translate_Real_Error"), val("Rotate_Pixel_Error"), val("Rotate_Real_Error"),
                 port("Rotation_Center", "pt", "Centre of rotation in the picture")] + RESULT_PORTS,
        params={"board_type": "Checkerboard", "columns": 9, "rows": 6, "physical_size": 10.0, "dot_type": "Dark on Light", "gray_contrast": 0.0, "median_filter": False,
                "subpixel_window": 0, "translation_times": 9, "rotation_times": 0, **MOTION_PARAMS, "camera_movement": False, "matrix_correction": False,
                "correct_image_x": 0.0, "correct_image_y": 0.0, "correct_physical_x": 0.0, "correct_physical_y": 0.0, **FIT_PARAMS, **SAVE_PARAMS},
        schema={"board_type": enum(*BOARDS), "columns": num(2, 100), "rows": num(2, 100), "physical_size": num(0.0001, 100000, 1, "mm", 4),
                "dot_type": enum("Dark on Light", "Light on Dark"), "gray_contrast": num(0, 255, 1), "median_filter": {"kind": "bool"}, "subpixel_window": num(0, 15, 1),
                "translation_times": num(3, 64), "rotation_times": num(0, 16), **MOTION_SCHEMA, "camera_movement": {"kind": "bool"}, "matrix_correction": {"kind": "bool"},
                "correct_image_x": num(-1e6, 1e6, 1, "px", 3), "correct_image_y": num(-1e6, 1e6, 1, "px", 3), "correct_physical_x": num(-1e6, 1e6, 1, "mm", 3),
                "correct_physical_y": num(-1e6, 1e6, 1, "mm", 3), **FIT_SCHEMA, **SAVE_SCHEMA})
def n_image_calibration(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    st = getattr(t, "_nimg", None)
    if st is None or ctx.get("Clear"):
        st = t._nimg = {"corners": [], "phys": []}
    nt, nr = int(t.get_param("translation_times")), int(t.get_param("rotation_times"))
    total = nt + nr
    cols, rows = int(t.get_param("columns")), int(t.get_param("rows"))
    pts = find_board(as_gray(a), str(t.get_param("board_type")), cols, rows, str(t.get_param("dot_type")).startswith("Dark"), float(t.get_param("gray_contrast")),
                     bool(t.get_param("median_filter")), int(t.get_param("subpixel_window")))
    if pts is None:
        return ng(f"no {cols} x {rows} board found in this picture", Status=0, Remaining=max(0, total - len(st["corners"])), Image=a)
    pts = consistent_order(pts, cols, rows)
    if len(st["corners"]) >= total:
        st["corners"], st["phys"] = [], []
    k = len(st["corners"])
    walk = motion_points(nt, float(t.get_param("fiducial_x")), float(t.get_param("fiducial_y")), float(t.get_param("offset_x")), float(t.get_param("offset_y")),
                         str(t.get_param("movement_first")), int(t.get_param("commutation_times")))
    pp = t.as_point(ctx.get("Physical_Point"))
    if pp is None:
        pp = walk[k] if k < nt else walk[min(4, nt - 1)]
    st["corners"].append(pts)
    st["phys"].append(pp)
    if len(st["corners"]) < total:
        return ng(f"{total - len(st['corners'])} more picture(s) to capture", Status=0, Remaining=total - len(st["corners"]), Image=a)
    size = float(t.get_param("physical_size"))
    lat = board_lattice(cols, rows) * size * np.array([1.0, 1.0])
    sign = -1.0 if bool(t.get_param("camera_movement")) else 1.0                         # a moving camera sees the board go the other way
    img_t = np.vstack(st["corners"][:nt])
    world_t = np.vstack([lat + sign * (np.array(p) - np.array(st["phys"][0])) for p in st["phys"][:nt]])
    m, res = _fit(t, img_t, world_t)
    if m is None:
        return ng("the pictures do not fix a calibration: the board must be moved in two different directions", Status=0, Remaining=0, Image=a)
    if bool(t.get_param("matrix_correction")):                                          # make the chosen picture point land on the chosen physical point
        ip = np.array([[float(t.get_param("correct_image_x")), float(t.get_param("correct_image_y"))]])
        want = np.array([float(t.get_param("correct_physical_x")), float(t.get_param("correct_physical_y"))])
        shift = want - apply_matrix(m, ip)[0]
        m = np.array([[1, 0, shift[0]], [0, 1, shift[1]], [0, 0, 1]], float) @ m
    extra: Dict[str, Any] = {"camera_mode": "Dynamic Camera" if bool(t.get_param("camera_movement")) else "Static Camera Above", "points": int(len(img_t))}
    pix = float(np.mean(np.hypot(*(apply_matrix(np.linalg.inv(m), world_t) - img_t).T)))
    extra.update(translate_pixel_error=pix, translate_real_error=float(np.mean(np.hypot(*(apply_matrix(m, img_t) - world_t).T))), error=pix)
    rot_c = None
    if nr >= 3:
        track = np.array([c[0] for c in st["corners"][nt:nt + nr]], float)                # one corner followed through the turns
        c = fit_circle_centre(track)
        if c is not None:
            rot_c = (c[0], c[1])
            extra.update(rotation_center_image=[c[0], c[1]], rotation_center_world=apply_matrix(m, np.array([[c[0], c[1]]]))[0].tolist(), rotate_pixel_error=c[3],
                         rotate_real_error=c[3] * local_scale(m, (c[0], c[1])))
    cal = make_calibration(m, "n-image", **extra)
    problem = _maybe_save(t, cal)
    if problem:
        return err(problem)
    return ok(f"calibrated from {total} pictures; pixel {cal['pixel_accuracy']:.4f}/px; error {pix:.3f} px", Image=a, Status=1, Remaining=0,
              Translate_Pixel_Error=pix, Translate_Real_Error=extra["translate_real_error"], Rotate_Pixel_Error=extra.get("rotate_pixel_error"),
              Rotate_Real_Error=extra.get("rotate_real_error"), Rotation_Center=rot_c, **_result_outputs(cal, m))


# ---------------------------------------------------------------------------------------------------------------------------
# Mapping Calibration
# ---------------------------------------------------------------------------------------------------------------------------
@define("Mapping Calibration", CAT,
        "Relates two cameras that both see the same calibration board: finds the board in each picture (or takes the two cameras' calibrations) "
        "and builds the matrix that turns the current camera's picture coordinates into the target camera's.",
        inputs=[img("Image", "Current camera's picture of the board"), img("Image2", "Target camera's picture of the board"),
                port("Calibration", "dict", "Current camera's calibration (instead of a picture)"), port("Calibration2", "dict", "Target camera's calibration")],
        outputs=[val("Status"), val("Current_Points"), val("Target_Points"), val("Mapped_Points"), val("Calibration_Error")] + RESULT_PORTS,
        params={"use": "Pictures", "board_type": "Checkerboard", "columns": 9, "rows": 6, "dot_type": "Dark on Light", "gray_contrast": 0.0, "median_filter": False,
                "subpixel_window": 0, **FIT_PARAMS, **SAVE_PARAMS},
        schema={"use": enum("Pictures", "Calibrations"), "board_type": enum(*BOARDS), "columns": num(2, 100), "rows": num(2, 100),
                "dot_type": enum("Dark on Light", "Light on Dark"), "gray_contrast": num(0, 255, 1), "median_filter": {"kind": "bool"}, "subpixel_window": num(0, 15, 1),
                **FIT_SCHEMA, **SAVE_SCHEMA})
def mapping_calibration(t, ctx):
    if str(t.get_param("use")) == "Calibrations":
        c1, c2 = ctx.get("Calibration"), ctx.get("Calibration2")
        m1, m2 = calibration_matrix(c1), calibration_matrix(c2)
        if m1 is None or m2 is None:
            return err("connect both calibrations")
        m = np.linalg.inv(m2) @ m1                                                         # picture 1 -> physical -> picture 2
        m = m / m[2, 2] if abs(m[2, 2]) > 1e-12 else m
        cal = make_calibration(m, "mapping", error=0.0, points=0)
        problem = _maybe_save(t, cal)
        if problem:
            return err(problem)
        return ok("mapping built from the two calibrations", Status=1, Current_Points=0, Target_Points=0, Mapped_Points=0, Calibration_Error=0.0, **_result_outputs(cal, m))
    a, b = get_image(ctx), get_image(ctx, "Image2")
    if a is None or b is None:
        return err("both pictures are needed (Image and Image2)")
    cols, rows = int(t.get_param("columns")), int(t.get_param("rows"))
    found = []
    for pic in (a, b):
        found.append(find_board(as_gray(pic), str(t.get_param("board_type")), cols, rows, str(t.get_param("dot_type")).startswith("Dark"),
                                float(t.get_param("gray_contrast")), bool(t.get_param("median_filter")), int(t.get_param("subpixel_window"))))
    n1, n2 = (0 if f is None else len(f) for f in found)
    if found[0] is None or found[1] is None:
        return ng(f"the board was not found in {'the first' if found[0] is None else 'the second'} picture", Status=0, Current_Points=n1, Target_Points=n2, Mapped_Points=0)
    p1, p2 = consistent_order(found[0], cols, rows), consistent_order(found[1], cols, rows)
    m, res = _fit(t, p1, p2)
    if m is None:
        return ng("the two sets of points do not fix a mapping", Status=0, Current_Points=n1, Target_Points=n2, Mapped_Points=0)
    err_px = float(np.mean(res))
    cal = make_calibration(m, "mapping", error=err_px, points=n1)
    problem = _maybe_save(t, cal)
    if problem:
        return err(problem)
    return ok(f"mapped {n1} corners; error {err_px:.3f} px", Status=1, Current_Points=n1, Target_Points=n2, Mapped_Points=n1, Calibration_Error=err_px, **_result_outputs(cal, m))


# ---------------------------------------------------------------------------------------------------------------------------
# Load Calibration
# ---------------------------------------------------------------------------------------------------------------------------
@define("Load Calibration", CAT,
        "Loads a calibration file written by the calibration modules and passes its calibration and numbers on. The file is read again when "
        "the refresh signal is not 0 and the file has changed; an empty or 0 signal keeps the first one read.",
        inputs=[port("Refresh", "val", "Reload the file when not 0")],
        outputs=[val("Status", "1 when a calibration is loaded"), val("Kind"), val("Calibration_Error"), val("Rotation_Center_Image"), val("Rotation_Center_Physical")] + RESULT_PORTS,
        params={"calibration_file": ""}, schema={"calibration_file": {"kind": "path", "filters": "Calibration files (*.json);;All files (*)"}})
def load_calibration_tool(t, ctx):
    cal, why = calibration_for(t, {"Refresh": ctx.get("Refresh")})
    if cal is None:
        return err(why)
    m = calibration_matrix(cal)
    return ok(f"{cal.get('kind', 'calibration')} calibration loaded; one pixel is {cal['pixel_accuracy']:.4f}", Status=1, Kind=cal.get("kind", ""),
              Calibration_Error=cal.get("error"), Rotation_Center_Image=tuple(cal["rotation_center_image"]) if cal.get("rotation_center_image") else None,
              Rotation_Center_Physical=tuple(cal["rotation_center_world"]) if cal.get("rotation_center_world") else None, **_result_outputs(cal, m))
