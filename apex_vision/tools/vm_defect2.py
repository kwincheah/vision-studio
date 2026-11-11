"""VisionMaster guide, chapter "Defect Detection" (surfaces and prints): Surface Defect Filter, OCV and Defect Contrast."""
import base64
import math
import zlib
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import as_gray, define, err, get_image, img, ng, no_image, ok, port, val

CAT = "Defect Detection"


# ---------------------------------------------------------------------------------------------------------------------------
# Surface Defect Filter
# ---------------------------------------------------------------------------------------------------------------------------
def ridge_kernel(angle_deg: float, length: int, across: int, sigma: float) -> np.ndarray:
    """A zero-mean line detector turned to ``angle_deg``: a Gaussian along the line, a (negative) second derivative of a Gaussian across it."""
    half = max(length, across) // 2 + 1
    ys, xs = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float64)
    a = math.radians(angle_deg)
    u = xs * math.cos(a) + ys * math.sin(a)                                             # along the line
    v = -xs * math.sin(a) + ys * math.cos(a)                                            # across it
    # `sigma` is the width of the across-line second derivative and divides the kernel
    # twice, so it must be positive and finite.  `s_along` was already floored, but the
    # raw value was used here: std_dev = 0 divided by zero, and std_dev = nan produced an
    # all-nan kernel that the module still reported as OK.  A width larger than the kernel
    # is equally broken - the support mask then zeroes every tap and the filter returns a
    # flat image while reporting OK - so the value is clamped to the kernel's own scale.
    sigma = float(sigma)
    if not math.isfinite(sigma):
        sigma = 1.0
    max_sigma = max(0.5, max(length, across) / 2.0)
    sigma = min(max(sigma, 0.5), max_sigma)
    s_along = max(sigma, length / 4.0)
    k = (1.0 - v * v / (sigma * sigma)) * np.exp(-v * v / (2 * sigma * sigma)) * np.exp(-u * u / (2 * s_along * s_along))
    k[np.abs(v) > max(across, 3 * sigma + 1) / 2.0 + 2 * sigma] = 0.0
    k[np.abs(u) > length / 2.0 + 1] = 0.0
    nz = k != 0
    k[nz] -= k[nz].mean()                                                              # zero mean, so a flat surface gives no response
    pos = k[k > 0].sum()
    return (k / pos if pos > 1e-12 else k).astype(np.float32)


def _angle_weight(angle: float, weights: List[float]) -> float:
    """Weight for a direction from the six given at 0, 30, ... 150 degrees (linear between them, wrapping at 180)."""
    pos = (angle % 180.0) / 30.0
    i = int(math.floor(pos)) % 6
    f = pos - math.floor(pos)
    return (1 - f) * weights[i] + f * weights[(i + 1) % 6]


@define("Surface Defect Filter", CAT,
        "Brings out scratches, dents, specks and foreign matter on a plain surface: the picture is filtered with line detectors turned to several "
        "directions, so a defect gives a strong response and a clean surface gives about 0. Threshold the result and use BLOB Analysis to count the "
        "defects. Weights make some directions count more or less.",
        inputs=[img()], outputs=[img("Image", "Filter response (defects bright, clean surface near 0)"), val("Max_Response"), val("Mean_Response")],
        params={"roi": [0, 0, 0, 0], "kernel_width": 21, "kernel_height": 9, "kernel_count": 6, "std_dev": 1.5, "offset": 4.0, "gain": 4.0,
                "weight_0": 0, "weight_30": 0, "weight_60": 0, "weight_90": 0, "weight_120": 0, "weight_150": 0},
        schema={"roi": {"kind": "rect"}, "kernel_width": num(3, 201, unit="px"), "kernel_height": num(3, 201, unit="px"), "kernel_count": num(1, 36),
                "std_dev": num(0.3, 30, 0.1, decimals=1), "offset": num(-255, 255, 1, decimals=1), "gain": num(0.1, 100, 0.5, decimals=1),
                **{f"weight_{a}": num(-10, 10) for a in (0, 30, 60, 90, 120, 150)}})
def surface_defect_filter(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a).astype(np.float32)
    x0, y0, rw, rh = [int(v) for v in t.get_param("roi")]
    full = not (rw > 0 and rh > 0)
    if not full:
        x0, y0, rw, rh = [int(v) for v in g.clamp_roi((x0, y0, rw, rh), a.shape)]
    sub = gray if full else gray[y0:y0 + rh, x0:x0 + rw]
    n = int(t.get_param("kernel_count"))
    weights = [float(t.get_param(f"weight_{a_}")) for a_ in (0, 30, 60, 90, 120, 150)]
    best = np.zeros(sub.shape, np.float32)
    pad = int(max(int(t.get_param("kernel_width")), int(t.get_param("kernel_height"))) // 2 + 2)
    padded = cv2.copyMakeBorder(sub, pad, pad, pad, pad, cv2.BORDER_REFLECT)
    for k in range(n):
        ang = 180.0 * k / n
        ker = ridge_kernel(ang, int(t.get_param("kernel_width")), int(t.get_param("kernel_height")), float(t.get_param("std_dev")))
        resp = np.abs(cv2.filter2D(padded, cv2.CV_32F, ker))[pad:-pad, pad:-pad]
        factor = max(0.0, 1.0 + _angle_weight(ang, weights) / 10.0)
        best = np.maximum(best, resp * factor)
    best = np.maximum(best - float(t.get_param("offset")), 0.0)
    out = np.zeros(gray.shape, np.float32)
    if full:
        out = best
    else:
        out[y0:y0 + rh, x0:x0 + rw] = best
    shown = np.clip(out * float(t.get_param("gain")), 0, 255).astype(np.uint8)
    over = [] if full else [{"type": "rect", "box": [x0, y0, rw, rh], "color": (160, 160, 160)}]
    return ok(f"response up to {float(out.max()):.1f} in {n} direction(s)", over, Image=shown, Max_Response=float(out.max()), Mean_Response=float(best.mean()))


# ---------------------------------------------------------------------------------------------------------------------------
# model storage
# ---------------------------------------------------------------------------------------------------------------------------
def pack(arr: np.ndarray) -> Dict[str, Any]:
    a = np.ascontiguousarray(arr, np.float32)
    return {"shape": list(a.shape), "data": base64.b64encode(zlib.compress(a.tobytes(), 6)).decode("ascii")}


def unpack(d: Any) -> Optional[np.ndarray]:
    try:
        shape = [int(v) for v in d["shape"]]
        a = np.frombuffer(zlib.decompress(base64.b64decode(d["data"])), np.float32)
        return a.reshape(shape).copy()
    except (KeyError, TypeError, ValueError, zlib.error):
        return None


def _roi(t, a: np.ndarray, name: str = "roi") -> Tuple[int, int, int, int]:
    x, y, w, h = [int(v) for v in t.get_param(name)]
    if w > 0 and h > 0:
        return tuple(int(v) for v in g.clamp_roi((x, y, w, h), a.shape))
    return 0, 0, a.shape[1], a.shape[0]


# ---------------------------------------------------------------------------------------------------------------------------
# OCV
# ---------------------------------------------------------------------------------------------------------------------------
MAX_TRAIN = 500


def _rotate_scale(gray: np.ndarray, angle: float, sx: float, sy: float) -> np.ndarray:
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    m[:, 0] *= sx
    m[:, 1] *= sy
    nw, nh = max(2, int(round(w * sx))), max(2, int(round(h * sy)))
    m[0, 2] += nw / 2.0 - w / 2.0
    m[1, 2] += nh / 2.0 - h / 2.0
    return cv2.warpAffine(gray, m, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def locate(gray: np.ndarray, tpl: np.ndarray, region: Tuple[int, int, int, int], angles: List[float], scales: List[Tuple[float, float]]):
    """Best match of ``tpl`` (grey, float32) inside ``region`` over the angles and scales: (score, centre x, centre y, angle, sx, sy) or None."""
    x0, y0, rw, rh = region
    sub = gray[y0:y0 + rh, x0:x0 + rw]
    best = None
    for ang in angles:
        for sx, sy in scales:
            tp = _rotate_scale(tpl, ang, sx, sy)
            if tp.shape[0] >= sub.shape[0] or tp.shape[1] >= sub.shape[1] or tp.std() < 1e-3:
                continue
            res = cv2.matchTemplate(sub, tp, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if best is None or mx > best[0]:
                best = (float(mx), x0 + loc[0] + tp.shape[1] / 2.0, y0 + loc[1] + tp.shape[0] / 2.0, float(ang), float(sx), float(sy))
    return best


def _frame_matrix(model_w: int, model_h: int, cx: float, cy: float, ang: float, sx: float, sy: float) -> np.ndarray:
    """2x3 matrix taking a point in the model's frame to the picture, for a match found at centre (cx, cy) turned by ang and scaled."""
    m = cv2.getRotationMatrix2D((model_w / 2.0, model_h / 2.0), ang, 1.0)
    m[:, 0] *= sx
    m[:, 1] *= sy
    m[:, 2] = np.array([cx, cy]) - m[:, :2] @ np.array([model_w / 2.0, model_h / 2.0])        # the model's centre lands on the match centre
    return m


def _angles(t) -> List[float]:
    lo, hi = float(t.get_param("angle_min")), float(t.get_param("angle_max"))
    if hi < lo:
        lo, hi = hi, lo
    step = max(0.25, float(t.get_param("angle_step")))
    return list(np.arange(lo, hi + 1e-9, step))[:361] or [0.0]


def _scales(t) -> List[Tuple[float, float]]:
    xs, ys = float(t.get_param("scale_x_range")), float(t.get_param("scale_y_range"))
    if xs <= 0 and ys <= 0:
        return [(1.0, 1.0)]
    return [(1.0 + fx * xs, 1.0 + fy * ys) for fx in (-1, 0, 1) for fy in (-1, 0, 1)]


@define("OCV", CAT,
        "Optical Character Verification: checks printed characters and marks against what good prints look like. Train it on good pictures "
        "(it learns the typical look and how much each pixel varies), then each print is found and compared: bright or dark spots beyond the "
        "limits, such as missing, extra or smeared strokes, are defects. Edge tolerance forgives small shifts of the strokes.",
        inputs=[img()],
        outputs=[img("Image", "Difference picture (defects bright)"), val("Defect_Count"), port("Defect_Boxes", "any", "[[x, y, w, h], ...] in the picture"), val("Score", "How well the print was found"),
                 port("Pose", "any", "[centre x, centre y, angle, x scale, y scale]"), val("Trained", "Training pictures used so far"), val("Max_Difference")],
        params={"mode": "Detect", "roi": [100, 100, 200, 60], "search_roi": [0, 0, 0, 0], "min_score": 0.5, "angle_min": -10.0, "angle_max": 10.0, "angle_step": 2.0,
                "scale_x_range": 0.0, "scale_y_range": 0.0, "correct_position": True, "defect_type": "Bright and Dark", "bright_threshold": 40, "dark_threshold": 40,
                "bright_scale": 3.0, "dark_scale": 3.0, "edge_tolerance": 1, "area_tolerance": 6, "model": {}},
        schema={"mode": enum("Detect", "Train", "Clear Model"), "roi": {"kind": "rect"}, "search_roi": {"kind": "rect"}, "min_score": num(0, 1, 0.05, decimals=2),
                "angle_min": num(-180, 180, 1, "deg", 1), "angle_max": num(-180, 180, 1, "deg", 1), "angle_step": num(0.25, 45, 0.25, "deg", 2),
                "scale_x_range": num(0, 0.5, 0.01, decimals=2), "scale_y_range": num(0, 0.5, 0.01, decimals=2), "correct_position": {"kind": "bool"},
                "defect_type": enum("Bright and Dark", "Bright", "Dark"), "bright_threshold": num(0, 255), "dark_threshold": num(0, 255), "bright_scale": num(0, 20, 0.5, decimals=1),
                "dark_scale": num(0, 20, 0.5, decimals=1), "edge_tolerance": num(0, 20), "area_tolerance": num(0, 100000, unit="px"), "model": {"kind": "json"}})
def ocv(t, ctx):
    a = get_image(ctx)
    mode = str(t.get_param("mode"))
    model = t.parameters.get("model")
    if mode == "Clear Model":
        t.parameters["model"] = {}
        return ok("model cleared", Image=a, Defect_Count=0, Defect_Boxes=[], Score=0.0, Pose=None, Trained=0, Max_Difference=0.0)
    if a is None:
        return no_image()
    gray = as_gray(a).astype(np.float32)
    if mode == "Train":
        if not isinstance(model, dict) or not model.get("sum"):
            x, y, w, h = _roi(t, a)
            if w < 8 or h < 8:
                return err("the print area is too small to train on: choose a larger area")
            patch = gray[y:y + h, x:x + w]
            t.parameters["model"] = model = {"n": 1, "w": w, "h": h, "origin": [x, y], "sum": pack(patch), "sumsq": pack(patch * patch)}
            return ok(f"model started from the area at ({x}, {y}), {w} x {h}", [{"type": "rect", "box": [x, y, w, h], "color": (0, 255, 0)}], Image=a, Defect_Count=0,
                      Defect_Boxes=[], Score=1.0, Pose=[x + w / 2.0, y + h / 2.0, 0.0, 1.0, 1.0], Trained=1, Max_Difference=0.0)
        if int(model["n"]) >= MAX_TRAIN:
            return err(f"the model already has {MAX_TRAIN} training pictures, the most it can take")
        s, sq = unpack(model["sum"]), unpack(model["sumsq"])
        if s is None or sq is None:
            return err("the stored model is damaged: clear it and train again")
        w, h = int(model["w"]), int(model["h"])
        tpl = s / model["n"]
        pose = locate(gray, tpl, _region(t, a), _angles(t), _scales(t))
        if pose is None or pose[0] < float(t.get_param("min_score")):
            return ng(f"the print was not found in this picture (best match {0.0 if pose is None else pose[0]:.2f}), so it was not added", Image=a, Defect_Count=0, Defect_Boxes=[],
                      Score=0.0 if pose is None else pose[0], Pose=None, Trained=int(model["n"]), Max_Difference=0.0)
        patch = _unwarp(gray, pose, w, h)
        model["sum"], model["sumsq"] = pack(s + patch), pack(sq + patch * patch)
        model["n"] = int(model["n"]) + 1
        return ok(f"picture {model['n']} added to the model (match {pose[0]:.2f})", Image=a, Defect_Count=0, Defect_Boxes=[], Score=pose[0], Pose=list(pose[1:]), Trained=int(model["n"]),
                  Max_Difference=0.0)
    if not isinstance(model, dict) or not model.get("sum"):
        return err("no model chosen: train one first (set Mode to Train and run on good pictures)")
    s, sq = unpack(model["sum"]), unpack(model["sumsq"])
    if s is None or sq is None:
        return err("the stored model is damaged: clear it and train again")
    n, w, h = int(model["n"]), int(model["w"]), int(model["h"])
    mean = s / n
    std = np.sqrt(np.maximum(sq / n - mean * mean, 0.0))
    pose = locate(gray, mean, _region(t, a), _angles(t), _scales(t))
    if pose is None or pose[0] < float(t.get_param("min_score")):
        return ng(f"the print was not found (best match {0.0 if pose is None else pose[0]:.2f}, needs {float(t.get_param('min_score')):.2f})", Image=a, Defect_Count=0, Defect_Boxes=[],
                  Score=0.0 if pose is None else pose[0], Pose=None, Trained=n, Max_Difference=0.0)
    patch = _unwarp(gray, pose, w, h)
    if bool(t.get_param("correct_position")):                                               # nudge by up to the edge tolerance for the best fit
        patch = _nudge(patch, mean, int(t.get_param("edge_tolerance")) + 1)
    tol = int(t.get_param("edge_tolerance"))
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * tol + 1, 2 * tol + 1))
    hi_margin = np.maximum(float(t.get_param("bright_threshold")), float(t.get_param("bright_scale")) * std)
    lo_margin = np.maximum(float(t.get_param("dark_threshold")), float(t.get_param("dark_scale")) * std)
    hi = cv2.dilate(mean + hi_margin, k) if tol else mean + hi_margin                          # the allowed range widens by the edge tolerance
    lo = cv2.erode(mean - lo_margin, k) if tol else mean - lo_margin
    kind = str(t.get_param("defect_type"))
    bright = np.maximum(patch - hi, 0.0) if kind in ("Bright and Dark", "Bright") else np.zeros_like(patch)
    dark = np.maximum(lo - patch, 0.0) if kind in ("Bright and Dark", "Dark") else np.zeros_like(patch)
    diff = np.maximum(bright, dark)
    mask = (diff > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    minarea = int(t.get_param("area_tolerance"))
    m = _frame_matrix(w, h, pose[1], pose[2], pose[3], pose[4], pose[5])
    boxes, over = [], []
    for i in range(1, count):
        bx, by, bw, bh, area = [int(v) for v in stats[i]]
        if area <= minarea:
            continue
        corners = np.array([[bx, by], [bx + bw, by], [bx + bw, by + bh], [bx, by + bh]], np.float64) @ m[:, :2].T + m[:, 2]
        x0, y0 = corners.min(axis=0)
        x1, y1 = corners.max(axis=0)
        boxes.append([float(x0), float(y0), float(x1 - x0), float(y1 - y0)])
        over.append({"type": "rect", "box": [int(x0), int(y0), int(max(1, x1 - x0)), int(max(1, y1 - y0))], "color": (0, 0, 255), "label": "defect"})
    outline = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float64) @ m[:, :2].T + m[:, 2]
    for i in range(4):
        over.append({"type": "line", "pt1": (int(outline[i][0]), int(outline[i][1])), "pt2": (int(outline[(i + 1) % 4][0]), int(outline[(i + 1) % 4][1])), "color": (0, 255, 0), "thickness": 1})
    shown = np.clip(diff * 4, 0, 255).astype(np.uint8)
    fn = ng if boxes else ok
    return fn(f"{len(boxes)} defect(s); print found with score {pose[0]:.2f}; trained on {n}", over, Image=shown, Defect_Count=len(boxes), Defect_Boxes=boxes, Score=pose[0],
              Pose=list(pose[1:]), Trained=n, Max_Difference=float(diff.max()))


def _region(t, a: np.ndarray) -> Tuple[int, int, int, int]:
    return _roi(t, a, "search_roi")


def _unwarp(gray: np.ndarray, pose, w: int, h: int) -> np.ndarray:
    m = _frame_matrix(w, h, pose[1], pose[2], pose[3], pose[4], pose[5])
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


def _nudge(patch: np.ndarray, ref: np.ndarray, radius: int) -> np.ndarray:
    """Shift ``patch`` by up to ``radius`` pixels each way to lie as close as it can to ``ref``."""
    best, best_err = patch, float(np.mean((patch - ref) ** 2))
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue
            sh = np.roll(np.roll(patch, dy, axis=0), dx, axis=1)
            e = float(np.mean((sh - ref) ** 2))
            if e < best_err:
                best, best_err = sh, e
    return best


# ---------------------------------------------------------------------------------------------------------------------------
# Defect Contrast
# ---------------------------------------------------------------------------------------------------------------------------
MAX_PER_CLASS = 20
FEATURE_SIZE = 24


def features(gray: np.ndarray) -> np.ndarray:
    """A description of a region that is steady against small brightness changes: its normalised look plus where its edges are."""
    small = cv2.resize(gray.astype(np.float32), (FEATURE_SIZE, FEATURE_SIZE), interpolation=cv2.INTER_AREA)
    small = (small - small.mean()) / (small.std() + 1e-6)
    gx = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.resize(np.hypot(gx, gy), (8, 8), interpolation=cv2.INTER_AREA)
    mag = (mag - mag.mean()) / (mag.std() + 1e-6)
    v = np.concatenate([small.ravel(), 1.5 * mag.ravel()])
    return v / (np.linalg.norm(v) + 1e-9)


@define("Defect Contrast", CAT,
        "Learns good and bad examples of a region and judges new ones: teach it up to 20 OK and 20 NG pictures of the region, then it scores how "
        "much a picture looks like the OK ones. A score under the threshold is NG. With OK examples only it scores the likeness to them.",
        inputs=[img()],
        outputs=[img(), val("Score", "0 to 1: how much it looks like the OK examples"), val("Result", "1 OK, 0 NG"), val("OK_Samples"), val("NG_Samples")],
        params={"mode": "Detect", "roi": [100, 100, 200, 100], "score_threshold": 0.6, "samples": {"ok": [], "ng": []}},
        schema={"mode": enum("Detect", "Learn OK", "Learn NG", "Clear Model"), "roi": {"kind": "rect"}, "score_threshold": num(0, 1, 0.05, decimals=2), "samples": {"kind": "json"}})
def defect_contrast(t, ctx):
    a = get_image(ctx)
    mode = str(t.get_param("mode"))
    samples = t.parameters.get("samples")
    if not isinstance(samples, dict):
        samples = t.parameters["samples"] = {"ok": [], "ng": []}
    ok_s, ng_s = samples.setdefault("ok", []), samples.setdefault("ng", [])
    counts = {"OK_Samples": len(ok_s), "NG_Samples": len(ng_s)}
    if mode == "Clear Model":
        ok_s.clear()
        ng_s.clear()
        return ok("model cleared", Image=a, Score=0.0, Result=0, OK_Samples=0, NG_Samples=0)
    if a is None:
        return no_image()
    x, y, w, h = _roi(t, a)
    if w < 8 or h < 8:
        return err("the region is too small: choose a larger region")
    box = [{"type": "rect", "box": [x, y, w, h], "color": (0, 255, 0)}]
    f = features(as_gray(a)[y:y + h, x:x + w])
    if mode in ("Learn OK", "Learn NG"):
        bucket = ok_s if mode == "Learn OK" else ng_s
        if len(bucket) >= MAX_PER_CLASS:
            return ng(f"already {MAX_PER_CLASS} {'OK' if bucket is ok_s else 'NG'} examples, the most it can take", box, Image=a, Score=0.0, Result=0, OK_Samples=len(ok_s),
                      NG_Samples=len(ng_s))
        bucket.append([round(float(v), 5) for v in f])
        return ok(f"{'OK' if bucket is ok_s else 'NG'} example {len(bucket)} added", box, Image=a, Score=0.0, Result=1, OK_Samples=len(ok_s), NG_Samples=len(ng_s))
    if not ok_s:
        return err("no OK examples chosen: set Mode to Learn OK and run on good pictures first")
    sim_ok = float(max(np.dot(f, np.asarray(s)) for s in ok_s))
    if ng_s:
        sim_ng = float(max(np.dot(f, np.asarray(s)) for s in ng_s))
        e_ok, e_ng = math.exp(8.0 * sim_ok), math.exp(8.0 * sim_ng)
        score = e_ok / (e_ok + e_ng)
    else:
        score = max(0.0, min(1.0, sim_ok))
    good = score >= float(t.get_param("score_threshold"))
    fn = ok if good else ng
    box[0]["color"] = (0, 255, 0) if good else (0, 0, 255)
    box.append({"type": "text", "text": f"{score:.2f}", "pt": (x, max(12, y - 6)), "color": box[0]["color"]})
    return fn(f"score {score:.2f} (needs {float(t.get_param('score_threshold')):.2f}): {'OK' if good else 'NG'}", box, Image=a, Score=score, Result=1 if good else 0, **counts)
