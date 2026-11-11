"""VisionMaster guide, chapter "Location": Mark Location, BLOB Label Analysis, Path Extraction and Target Tracking."""
import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import as_gray, define, err, get_image, img, ng, no_image, ok, port, val
from apex_vision.tools.vm_boxes import to_box, to_boxes

CAT = "Location"


# ---------------------------------------------------------------------------------------------------------------------------
# Mark Location
# ---------------------------------------------------------------------------------------------------------------------------
MARKS = ["Hollow Cross", "Solid Cross", "Rectangle", "Hollow Rectangle"]


def mark_template(kind: str, w: int, h: int, arm: int, angle: float) -> np.ndarray:
    """The mark as a float picture (1 inside the mark, 0 outside), turned by ``angle`` degrees, cropped to its own outline."""
    n = int(math.hypot(w, h)) + 8
    c = np.zeros((n, n), np.uint8)
    cx, cy = n // 2, n // 2
    arm = max(1, arm)
    if kind in ("Solid Cross", "Hollow Cross"):
        cv2.rectangle(c, (cx - w // 2, cy - arm // 2), (cx + w // 2, cy + arm // 2), 255, -1)
        cv2.rectangle(c, (cx - arm // 2, cy - h // 2), (cx + arm // 2, cy + h // 2), 255, -1)
        if kind == "Hollow Cross":
            inner = cv2.erode(c, np.ones((3, 3), np.uint8), iterations=max(1, arm // 4))
            c = cv2.subtract(c, inner)
    elif kind == "Hollow Rectangle":
        cv2.rectangle(c, (cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2), 255, max(2, arm))
    else:
        cv2.rectangle(c, (cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2), 255, -1)
    m = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    c = cv2.warpAffine(c, m, (n, n), flags=cv2.INTER_LINEAR)
    ys, xs = np.nonzero(c > 20)
    c = c[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    pad = max(3, min(w, h) // 4)                                                      # some background around the mark, or a solid block has nothing to correlate against
    c = cv2.copyMakeBorder(c, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    return (c.astype(np.float32) / 255.0)


@define("Mark Location", CAT,
        "Finds crosses (solid or hollow) and rectangles, such as alignment marks: it builds the shape from the size you give and matches it "
        "over the picture at each angle in the range. Gives every match with its position, angle and score.",
        inputs=[img()], outputs=[img(), val("Count"), port("Matches", "any", "[{x, y, angle, score}, ...] best first"), val("Center_X"), val("Center_Y"),
                                 val("Angle_Deg"), val("Score")],
        params={"mark_type": "Hollow Cross", "mark_width": 40, "mark_height": 40, "arm_width": 8, "mark_polarity": "Dark on Light", "match_polarity": "Considered",
                "min_score": 0.5, "max_matches": 1, "angle_min": -10.0, "angle_max": 10.0, "angle_step": 1.0, "max_overlap": 50, "roi": [0, 0, 0, 0]},
        schema={"mark_type": enum(*MARKS), "mark_width": num(4, 2000, unit="px"), "mark_height": num(4, 2000, unit="px"), "arm_width": num(1, 500, unit="px"),
                "mark_polarity": enum("Dark on Light", "Light on Dark"), "match_polarity": enum("Considered", "Ignored"), "min_score": num(0, 1, 0.05, decimals=2),
                "max_matches": num(1, 200), "angle_min": num(-180, 180, 1, "deg", 1), "angle_max": num(-180, 180, 1, "deg", 1),
                "angle_step": num(0.1, 45, 0.1, "deg", 1), "max_overlap": num(0, 100, 5, "%", 0), "roi": {"kind": "rect"}})
def mark_location(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a).astype(np.float32)
    x0, y0, rw, rh = [int(v) for v in t.get_param("roi")]
    if rw > 0 and rh > 0:
        x0, y0, rw, rh = [int(v) for v in g.clamp_roi((x0, y0, rw, rh), a.shape)]
    else:
        x0, y0, rw, rh = 0, 0, a.shape[1], a.shape[0]
    sub = gray[y0:y0 + rh, x0:x0 + rw]
    lo, hi = float(t.get_param("angle_min")), float(t.get_param("angle_max"))
    if hi < lo:
        return err("the largest angle must not be below the smallest")
    step = max(0.1, float(t.get_param("angle_step")))
    angles = np.arange(lo, hi + 1e-9, step)
    if len(angles) > 400:
        return err("too many angles to try: raise the angle step or narrow the range")
    kind, w, h, arm = str(t.get_param("mark_type")), int(t.get_param("mark_width")), int(t.get_param("mark_height")), int(t.get_param("arm_width"))
    dark = str(t.get_param("mark_polarity")) == "Dark on Light"
    ignore_pol = str(t.get_param("match_polarity")) == "Ignored"
    cands: List[Tuple[float, float, float, float]] = []
    best_map = None
    for ang in angles:
        tpl = mark_template(kind, w, h, arm, float(ang))
        th, tw = tpl.shape
        if th >= sub.shape[0] or tw >= sub.shape[1]:
            return err("the mark is larger than the searched region")
        # the template is bright where the mark should be bright: invert it for a dark mark on a light background
        patt = (1.0 - tpl) if dark else tpl
        res = cv2.matchTemplate(sub, (patt * 255).astype(np.float32), cv2.TM_CCOEFF_NORMED)
        if ignore_pol:
            res = np.maximum(res, cv2.matchTemplate(sub, ((1.0 - patt) * 255).astype(np.float32), cv2.TM_CCOEFF_NORMED))
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        thr = float(t.get_param("min_score"))
        ys, xs = np.nonzero(res >= thr)
        for yy, xx in zip(ys, xs):
            cands.append((float(res[yy, xx]), xx + tw / 2.0 + x0, yy + th / 2.0 + y0, float(ang)))
    cands.sort(reverse=True)
    picked: List[Tuple[float, float, float, float]] = []
    box_w, box_h = max(w, 4), max(h, 4)
    overlap = float(t.get_param("max_overlap")) / 100.0
    for sc, cx, cy, ang in cands:
        clash = False
        for _s, px, py, _a in picked:
            ix = max(0.0, box_w - abs(cx - px))
            iy = max(0.0, box_h - abs(cy - py))
            if (ix * iy) / (box_w * box_h) > overlap:
                clash = True
                break
        if not clash:
            picked.append((sc, cx, cy, ang))
            if len(picked) >= int(t.get_param("max_matches")):
                break
    if not picked:
        return ng(f"no {kind.lower()} found with a score of {float(t.get_param('min_score')):g} or more", Image=a, Count=0, Matches=[])
    matches = [{"x": round(cx, 2), "y": round(cy, 2), "angle": round(ang, 2), "score": round(sc, 4)} for sc, cx, cy, ang in picked]
    over = [g.cross_overlay(m["x"], m["y"], (0, 255, 0), 8) for m in matches] + \
           [{"type": "text", "text": f"{m['score']:.2f}", "pt": (int(m["x"]) + 10, int(m["y"]) - 10), "color": (0, 255, 255)} for m in matches]
    b = matches[0]
    return ok(f"{len(matches)} {kind.lower()} found; best at ({b['x']:.1f}, {b['y']:.1f}), {b['angle']:.1f} deg, score {b['score']:.2f}", over, Image=a,
              Count=len(matches), Matches=matches, Center_X=b["x"], Center_Y=b["y"], Angle_Deg=b["angle"], Score=b["score"])


# ---------------------------------------------------------------------------------------------------------------------------
# BLOB Label Analysis
# ---------------------------------------------------------------------------------------------------------------------------
SORT_FEATURES = ["Area", "Perimeter", "Circularity", "Rectangularity", "Center X", "Center Y", "Box Angle", "Box Width", "Box Height",
                 "Box Left", "Box Top", "Second-order Center Distance", "Principal Axis Angle", "Axis Ratio"]


def blob_features(mask: np.ndarray, label_img: np.ndarray, i: int, stats, cents) -> Dict[str, Any]:
    x, y, w, h, area = [int(v) for v in stats[i]]
    comp = (label_img[y:y + h, x:x + w] == i).astype(np.uint8)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cnt = max(cnts, key=cv2.contourArea) if cnts else None
    per = float(cv2.arcLength(cnt, True)) if cnt is not None else 0.0
    circ = float(4 * math.pi * area / (per * per + 1e-9)) if per > 0 else 0.0
    cx, cy = float(cents[i][0]), float(cents[i][1])
    rect = cv2.minAreaRect(cnt + np.array([[x, y]])) if cnt is not None and len(cnt) >= 3 else ((cx, cy), (float(w), float(h)), 0.0)
    (rcx, rcy), (rw, rh), rang = rect
    major, minor = max(rw, rh), min(rw, rh)
    m = cv2.moments(comp, binaryImage=True)
    mu20, mu02, mu11 = m["mu20"] / max(1, area), m["mu02"] / max(1, area), m["mu11"] / max(1, area)
    pang = 0.5 * math.degrees(math.atan2(2 * mu11, mu20 - mu02))
    return {"area": area, "perimeter": per, "circularity": min(1.0, circ), "rectangularity": float(min(1.0, area / max(1.0, rw * rh))),
            "cx": cx, "cy": cy, "box": [x, y, w, h], "box_angle": float(rang), "box_width": float(rw), "box_height": float(rh),
            "box_left": x, "box_top": y, "major_axis": float(major), "minor_axis": float(minor), "axis_ratio": float(minor / major) if major > 0 else 0.0,
            "barycenter_offset": float(math.hypot(cx - (x + w / 2.0), cy - (y + h / 2.0))), "second_order_distance": float(math.sqrt(max(0.0, mu20 + mu02))),
            "principal_axis_angle": float(pang)}


SORT_KEY = {"Area": "area", "Perimeter": "perimeter", "Circularity": "circularity", "Rectangularity": "rectangularity", "Center X": "cx", "Center Y": "cy",
            "Box Angle": "box_angle", "Box Width": "box_width", "Box Height": "box_height", "Box Left": "box_left", "Box Top": "box_top",
            "Second-order Center Distance": "second_order_distance", "Principal Axis Angle": "principal_axis_angle", "Axis Ratio": "axis_ratio"}


@define("BLOB Label Analysis", CAT,
        "BLOB analysis for a picture whose pixel values are class numbers (for example the output of deep-learning segmentation): finds the "
        "connected regions of each class and reports each with its class name, size and shape. Filter by size per class or overall, and sort.",
        inputs=[img("Image", "Label picture: the grey value is the class"), port("Label_Names", "any", "Class names (optional)"), port("Gray_Values", "any", "Class numbers (optional)")],
        outputs=[img("Image", "Mask of the regions kept"), val("Count"), port("Blobs", "any", "One record per region"), port("Labels", "any", "Class name of each region"),
                 port("Label_Values", "any", "Class number of each region"), port("Areas", "any", "Area of each region"), port("Centers", "any", "[[x, y], ...]")],
        params={"roi": [0, 0, 0, 0], "label_names": "", "gray_values": "", "label_level_area": False, "label_min_area": 20, "label_max_area": 1000000,
                "global_area": True, "global_min_area": 20, "global_max_area": 10000000, "invert_area_filter": False, "max_blobs": 100,
                "connectivity": "8-connected", "min_axis_ratio": 0.0, "max_axis_ratio": 1.0, "sort_feature": "Area", "sort_type": "Descending",
                "min_overlap_rate": 0.0},
        schema={"roi": {"kind": "rect"}, "label_names": {"kind": "text", "hint": "class names separated by commas"},
                "gray_values": {"kind": "text", "hint": "class numbers separated by commas, same order"}, "label_min_area": num(0, 1_000_000_000, unit="px"),
                "label_max_area": num(0, 1_000_000_000, unit="px"), "global_min_area": num(0, 1_000_000_000, unit="px"), "global_max_area": num(0, 1_000_000_000, unit="px"),
                "max_blobs": num(1, 100000), "connectivity": enum("4-connected", "8-connected"), "min_axis_ratio": num(0, 1, 0.05, decimals=2),
                "max_axis_ratio": num(0, 1, 0.05, decimals=2), "sort_feature": enum(*SORT_FEATURES), "sort_type": enum("Ascending", "Descending", "No Sorting"),
                "min_overlap_rate": num(0, 100, 5, "%", 0)})
def blob_label_analysis(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    lab = as_gray(a)
    names = ctx.get("Label_Names") if ctx.get("Label_Names") is not None else [s.strip() for s in str(t.get_param("label_names")).split(",") if s.strip()]
    grays = ctx.get("Gray_Values")
    if grays is None:
        try:
            grays = [int(s) for s in str(t.get_param("gray_values")).replace(";", ",").split(",") if s.strip()]
        except ValueError:
            return err("the gray values must be whole numbers separated by commas")
    grays = [int(v) for v in grays]
    if not grays:                                                                            # every non-zero value in the picture is a class
        grays = [int(v) for v in np.unique(lab) if v != 0][:255]
    names = [str(n) for n in names] if names else []
    name_of = {gv: (names[i] if i < len(names) else f"class_{gv}") for i, gv in enumerate(grays)}
    x0, y0, rw, rh = [int(v) for v in t.get_param("roi")]
    roi_mask = None
    if rw > 0 and rh > 0:
        x0, y0, rw, rh = [int(v) for v in g.clamp_roi((x0, y0, rw, rh), a.shape)]
        roi_mask = np.zeros(lab.shape, bool)
        roi_mask[y0:y0 + rh, x0:x0 + rw] = True
    conn = 4 if str(t.get_param("connectivity")).startswith("4") else 8
    use_label_area, use_global = bool(t.get_param("label_level_area")), bool(t.get_param("global_area"))
    if use_label_area and use_global:
        use_global = False                                                                   # the guide: they cannot be used together
    blobs: List[Dict[str, Any]] = []
    for gv in grays:
        m = (lab == gv).astype(np.uint8)
        if not m.any():
            continue
        n, labels, stats, cents = cv2.connectedComponentsWithStats(m, connectivity=conn)
        for i in range(1, n):
            f = blob_features(m, labels, i, stats, cents)
            if roi_mask is not None:
                inside = int(np.count_nonzero((labels == i) & roi_mask))
                if inside == 0 or 100.0 * inside / f["area"] < float(t.get_param("min_overlap_rate")):
                    continue
            lo, hi = (float(t.get_param("label_min_area")), float(t.get_param("label_max_area"))) if use_label_area else \
                     (float(t.get_param("global_min_area")), float(t.get_param("global_max_area"))) if use_global else (0, float("inf"))
            inside_range = lo <= f["area"] <= hi
            if (use_label_area or use_global) and inside_range == bool(t.get_param("invert_area_filter")):
                continue
            if not (float(t.get_param("min_axis_ratio")) <= f["axis_ratio"] <= float(t.get_param("max_axis_ratio"))):
                continue
            f.update({"label": name_of[gv], "gray": gv, "_labels": labels, "_id": i})
            blobs.append(f)
    key = SORT_KEY.get(str(t.get_param("sort_feature")), "area")
    if str(t.get_param("sort_type")) != "No Sorting":
        blobs.sort(key=lambda b: b[key], reverse=str(t.get_param("sort_type")) == "Descending")
    blobs = blobs[:int(t.get_param("max_blobs"))]
    out_mask = np.zeros(lab.shape, np.uint8)
    over, records = [], []
    for b in blobs:
        out_mask[b.pop("_labels") == b.pop("_id")] = 255
        records.append(b)
        over.append({"type": "rect", "box": b["box"], "color": (0, 255, 0), "label": b["label"]})
    if not records:
        return ng("no region matches", Image=out_mask, Count=0, Blobs=[], Labels=[], Label_Values=[], Areas=[], Centers=[])
    return ok(f"{len(records)} region(s) in {len({r['gray'] for r in records})} class(es)", over, Image=out_mask, Count=len(records), Blobs=records,
              Labels=[r["label"] for r in records], Label_Values=[r["gray"] for r in records], Areas=[r["area"] for r in records],
              Centers=[[r["cx"], r["cy"]] for r in records])


# ---------------------------------------------------------------------------------------------------------------------------
# Path Extraction
# ---------------------------------------------------------------------------------------------------------------------------
def resample_polyline(pts: np.ndarray, n: int) -> Tuple[np.ndarray, np.ndarray, float]:
    """``n`` points spaced equally along a polyline, and the direction of the path at each."""
    seg = np.hypot(*np.diff(pts, axis=0).T)
    total = float(seg.sum())
    if total < 1e-9:
        raise ValueError("the path has no length")
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    s = np.linspace(0, total, n)
    xs, ys = np.interp(s, cum, pts[:, 0]), np.interp(s, cum, pts[:, 1])
    out = np.column_stack([xs, ys])
    tang = np.gradient(out, axis=0)
    norm = np.maximum(np.hypot(*tang.T), 1e-9)
    return out, tang / norm[:, None], total


@define("Path Extraction", CAT,
        "Takes points along a path you describe (a polyline or an arc): either spaced equally along it, or moved to the real edge nearby "
        "(for gluing, welding and dispensing paths). Follows the part when you connect a Position Correction.",
        inputs=[img(), val("Delta_X"), val("Delta_Y"), val("Delta_Angle", "Degrees"), port("Affine_Matrix", "any", "2x3 matrix from Position Correction (optional)")],
        outputs=[img(), port("Points", "any", "[[x, y], ...] along the path"), val("Count"), val("Path_Length"), port("Arc_Center", "pt", "Arc paths only"), val("Arc_Angle", "Arc paths only: the sweep in degrees")],
        params={"path_type": "Polyline", "path_points": [[80, 200], [200, 140], [320, 200], [440, 140]], "arc_center": [250, 200], "arc_radius": 100.0,
                "arc_start_angle": 0.0, "arc_end_angle": 180.0, "extraction_method": "Equal Interval Points", "point_count": 20, "position_offset": 0.0,
                "reference_point": [0, 0], "output_arc_params": True, "caliper_height": 24, **g.edge_params(caliper_number=20)},
        schema={"path_type": enum("Polyline", "Arc"), "path_points": {"kind": "points"}, "arc_center": {"kind": "point"}, "arc_radius": num(1, 100000, 1, "px", 1),
                "arc_start_angle": num(-720, 720, 1, "deg", 1), "arc_end_angle": num(-720, 720, 1, "deg", 1),
                "extraction_method": enum("Equal Interval Points", "Find Edge Points"), "point_count": num(2, 300), "position_offset": num(-1000, 1000, 0.5, "px", 1),
                "reference_point": {"kind": "point"}, "caliper_height": num(2, 1000, unit="px"), **g.edge_schema()})
def path_extraction(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    n = int(t.get_param("point_count"))
    arc = str(t.get_param("path_type")) == "Arc"
    try:
        if arc:
            cx, cy = [float(v) for v in t.get_param("arc_center")]
            r = float(t.get_param("arc_radius"))
            a0, a1 = float(t.get_param("arc_start_angle")), float(t.get_param("arc_end_angle"))
            th = np.radians(np.linspace(a0, a1, n))
            raw = np.column_stack([cx + r * np.cos(th), cy - r * np.sin(th)])                    # counterclockwise on screen
            tang = np.column_stack([-np.sin(th), -np.cos(th)])
            tang *= np.sign(a1 - a0) if a1 != a0 else 1.0
            path_len = abs(math.radians(a1 - a0)) * r
        else:
            raw, tang, path_len = resample_polyline(np.asarray(t.get_param("path_points"), np.float64).reshape(-1, 2), n)
    except (ValueError, TypeError) as exc:
        return err(f"Path Extraction: {exc}")
    pts = raw.copy()
    # follow the part: apply the correction (a 2x3 matrix, or dx, dy, angle about the reference point)
    m = ctx.get("Affine_Matrix")
    if m is not None:
        mm = np.asarray(m, np.float64).reshape(2, 3)
    elif any(ctx.get(k) is not None for k in ("Delta_X", "Delta_Y", "Delta_Angle")):
        rp = t.as_point(t.get_param("reference_point")) or (0.0, 0.0)
        mm = cv2.getRotationMatrix2D((float(rp[0]), float(rp[1])), t.as_float(ctx.get("Delta_Angle")), 1.0)
        mm[0, 2] += t.as_float(ctx.get("Delta_X"))
        mm[1, 2] += t.as_float(ctx.get("Delta_Y"))
    else:
        mm = None
    if mm is not None:
        pts = pts @ mm[:, :2].T + mm[:, 2]
        tang = tang @ mm[:, :2].T
        tang /= np.maximum(np.hypot(*tang.T), 1e-9)[:, None]
    off = float(t.get_param("position_offset"))
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
    if off:
        pts = pts + nrm * off
    method = str(t.get_param("extraction_method"))
    found_n = n
    if method == "Find Edge Points":
        gray = as_gray(a)
        half = float(t.get_param("caliper_height")) / 2.0
        e = dict(width=int(t.get_param("projection_width")), polarity=str(t.get_param("edge_polarity")), edge_type=str(t.get_param("edge_type")),
                 threshold=float(t.get_param("edge_threshold")), filter_size=int(t.get_param("filter_size")))
        res = []
        for p, nv in zip(pts, nrm):
            r_ = g.caliper(gray, tuple(p - nv * half), tuple(p + nv * half), **e)
            res.append([r_[0], r_[1]] if r_ else [float("nan"), float("nan")])
        res = np.array(res)
        good = ~np.isnan(res[:, 0])
        found_n = int(good.sum())
        if found_n == 0:
            return ng("no edge found near any path point", Image=a, Points=[], Count=0, Path_Length=path_len)
        pts = res
    over = [g.cross_overlay(p[0], p[1], (0, 255, 255), 3) for p in pts if not np.isnan(p[0])]
    for i in range(len(raw) - 1):
        over.append({"type": "line", "pt1": (int(raw[i][0]), int(raw[i][1])), "pt2": (int(raw[i + 1][0]), int(raw[i + 1][1])), "color": (120, 120, 120), "thickness": 1})
    outs: Dict[str, Any] = {"Image": a, "Points": [[None if np.isnan(v) else round(float(v), 3) for v in p] for p in pts], "Count": found_n, "Path_Length": float(path_len)}
    msg = f"{found_n} path point(s) ({method.lower()}), path {path_len:.1f} px long"
    if arc and t.get_param("output_arc_params") and method == "Equal Interval Points":
        ctr = np.array([cx, cy])
        if mm is not None:
            ctr = ctr @ mm[:, :2].T + mm[:, 2]
        outs["Arc_Center"] = (float(ctr[0]), float(ctr[1]))
        outs["Arc_Angle"] = float(a1 - a0)
        msg += f"; arc centre ({ctr[0]:.1f}, {ctr[1]:.1f}), sweep {a1 - a0:g} deg"
    return ok(msg, over, **outs)


# ---------------------------------------------------------------------------------------------------------------------------
# Target Tracking
# ---------------------------------------------------------------------------------------------------------------------------
@define("Target Tracking", CAT,
        "Counts targets that move through the picture (for example items on a belt): it follows each detected box from picture to picture, "
        "and counts it once when it crosses the counting line in the middle of the region.",
        inputs=[port("Boxes", "any", "Boxes found in this picture (e.g. from DL Object Detection)"), port("Clear", "bool", "Reset the count")],
        outputs=[val("Count", "Targets counted so far"), val("Active", "Targets being followed now"), port("Tracks", "any", "[{id, box, counted}, ...]"),
                 val("New_Counts", "Counted in this picture")],
        params={"roi": [0, 100, 640, 280], "direction": "Left to Right", "track_speed_x": 1.0, "track_speed_y": 1.0, "max_lost_frames": 2, "track_overlap": 30},
        schema={"roi": {"kind": "rect"}, "direction": enum("Left to Right", "Right to Left", "Top to Bottom", "Bottom to Top"),
                "track_speed_x": num(0.1, 10, 0.1, decimals=1), "track_speed_y": num(0.1, 10, 0.1, decimals=1), "max_lost_frames": num(0, 100),
                "track_overlap": num(1, 100, 1, "%", 0)})
def target_tracking(t, ctx):
    state = getattr(t, "_tracks", None)
    if state is None or ctx.get("Clear"):
        state = t._tracks = {"next": 1, "tracks": [], "count": 0}
    boxes = to_boxes(ctx.get("Boxes"))
    x, y, w, h = [float(v) for v in t.get_param("roi")]
    d = str(t.get_param("direction"))
    horizontal = d in ("Left to Right", "Right to Left")
    sign = 1 if d in ("Left to Right", "Top to Bottom") else -1
    line_pos = (x + w / 2.0) if horizontal else (y + h / 2.0)
    ov_thr, sx, sy = float(t.get_param("track_overlap")) / 100.0, float(t.get_param("track_speed_x")), float(t.get_param("track_speed_y"))
    boxes = [b for b in boxes if x <= b["cx"] <= x + w and y <= b["cy"] <= y + h]

    def iou(a_, b_):
        ax0, ay0, ax1, ay1 = a_["cx"] - a_["w"] / 2, a_["cy"] - a_["h"] / 2, a_["cx"] + a_["w"] / 2, a_["cy"] + a_["h"] / 2
        bx0, by0, bx1, by1 = b_["cx"] - b_["w"] / 2, b_["cy"] - b_["h"] / 2, b_["cx"] + b_["w"] / 2, b_["cy"] + b_["h"] / 2
        iw, ih = max(0.0, min(ax1, bx1) - max(ax0, bx0)), max(0.0, min(ay1, by1) - max(ay0, by0))
        inter = iw * ih
        return inter / max(1e-9, min(a_["w"] * a_["h"], b_["w"] * b_["h"]))                  # overlap relative to the smaller box, like the guide

    tracks = state["tracks"]
    for tr in tracks:                                                                        # predict where each followed target should be now
        tr["pred"] = {"cx": tr["box"]["cx"] + tr["vx"] * sx, "cy": tr["box"]["cy"] + tr["vy"] * sy, "w": tr["box"]["w"], "h": tr["box"]["h"]}
    used, new_counts = set(), 0
    pairs = sorted(((iou(tr["pred"], b), ti, bi) for ti, tr in enumerate(tracks) for bi, b in enumerate(boxes)), reverse=True)
    taken_t = set()
    for ov, ti, bi in pairs:
        if ov < ov_thr or ti in taken_t or bi in used:
            continue
        tr, b = tracks[ti], boxes[bi]
        tr["vx"], tr["vy"] = b["cx"] - tr["box"]["cx"], b["cy"] - tr["box"]["cy"]
        before = (tr["box"]["cx"] if horizontal else tr["box"]["cy"]) - line_pos
        after = (b["cx"] if horizontal else b["cy"]) - line_pos
        tr["box"], tr["lost"] = b, 0
        if not tr["counted"] and before * sign < 0 <= after * sign:                           # crossed the line in the counting direction
            tr["counted"] = True
            state["count"] += 1
            new_counts += 1
        taken_t.add(ti)
        used.add(bi)
    for ti, tr in enumerate(tracks):                                                        # followed targets that were not seen this time
        if ti not in taken_t:
            tr["lost"] = tr.get("lost", 0) + 1
    for bi, b in enumerate(boxes):                                                          # boxes nobody was following start new tracks
        if bi not in used:
            tracks.append({"id": state["next"], "box": b, "vx": 0.0, "vy": 0.0, "lost": 0, "counted": False})
            state["next"] += 1
    state["tracks"] = [tr for tr in tracks if tr["lost"] <= int(t.get_param("max_lost_frames"))]
    over = [{"type": "rect", "box": [int(x), int(y), int(w), int(h)], "color": (160, 160, 160)}]
    over.append({"type": "line", "pt1": (int(line_pos), int(y)) if horizontal else (int(x), int(line_pos)),
                 "pt2": (int(line_pos), int(y + h)) if horizontal else (int(x + w), int(line_pos)), "color": (0, 255, 255), "thickness": 2})
    for tr in state["tracks"]:
        b = tr["box"]
        over.append({"type": "rect", "box": [int(b["cx"] - b["w"] / 2), int(b["cy"] - b["h"] / 2), int(b["w"]), int(b["h"])],
                     "color": (0, 255, 0) if tr["counted"] else (0, 200, 255), "label": f"#{tr['id']}"})
    over.append({"type": "text", "text": f"Count {state['count']}", "pt": (int(x) + 6, int(y) + 22), "color": (0, 255, 255)})
    return ok(f"count {state['count']} ({new_counts} new), following {len(state['tracks'])}", over, Count=state["count"], Active=len(state["tracks"]),
              Tracks=[{"id": tr["id"], "box": [tr["box"]["cx"], tr["box"]["cy"], tr["box"]["w"], tr["box"]["h"]], "counted": tr["counted"]} for tr in state["tracks"]],
              New_Counts=new_counts)
