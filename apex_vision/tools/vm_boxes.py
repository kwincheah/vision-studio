"""VisionMaster guide, chapter "Division and Combination": Image Division, 2D Array Correction, Pixel Transformation, Box Merge,
Box Overlap and Box Filtering.

A *box* is a rectangle that can be turned. These modules take and give boxes as ``{"cx", "cy", "w", "h", "angle", "label"}`` and also
accept the plain ``[x, y, w, h]`` (top-left corner) that the detection modules produce.
"""
import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools._spec import as_gray, define, err, get_image, img, ng, no_image, ok, port, val

CAT = "Division and Combination"


# ---------------------------------------------------------------------------------------------------------------------------
# box helpers
# ---------------------------------------------------------------------------------------------------------------------------
def to_box(v: Any, label: Any = None) -> Optional[Dict[str, Any]]:
    """Normalise one box. [x, y, w, h] is a top-left box; a dict may give cx/cy or x/y."""
    try:
        if isinstance(v, dict):
            if "cx" in v and "cy" in v:
                cx, cy = float(v["cx"]), float(v["cy"])
            elif "x" in v and "y" in v:
                cx, cy = float(v["x"]) + float(v["w"]) / 2.0, float(v["y"]) + float(v["h"]) / 2.0
            elif "Box" in v:
                return to_box(v["Box"], v.get("Class", label))
            else:
                return None
            return {"cx": cx, "cy": cy, "w": float(v["w"]), "h": float(v["h"]), "angle": float(v.get("angle", 0.0)),
                    "label": v.get("label", label)}
        if isinstance(v, (list, tuple, np.ndarray)) and len(v) >= 4:
            x, y, w, h = [float(a) for a in v[:4]]
            return {"cx": x + w / 2.0, "cy": y + h / 2.0, "w": w, "h": h, "angle": float(v[4]) if len(v) > 4 else 0.0, "label": label}
    except (TypeError, ValueError, KeyError):
        return None
    return None


def to_boxes(values: Any, labels: Any = None) -> List[Dict[str, Any]]:
    if values is None:
        return []
    if isinstance(values, dict) or (isinstance(values, (list, tuple)) and values and not isinstance(values[0], (list, tuple, dict, np.ndarray))
                                    and len(values) >= 4):
        values = [values]
    labs = list(labels) if isinstance(labels, (list, tuple)) else []
    out = []
    for i, v in enumerate(values):
        b = to_box(v, labs[i] if i < len(labs) else None)
        if b is not None:
            out.append(b)
    return out


def box_rect(b: Dict[str, Any]) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
    return (b["cx"], b["cy"]), (max(1e-6, b["w"]), max(1e-6, b["h"])), -b["angle"]          # angle: counterclockwise on screen


def box_points(b: Dict[str, Any]) -> np.ndarray:
    return cv2.boxPoints(box_rect(b)).astype(np.float32)


def box_out(b: Dict[str, Any]) -> Dict[str, Any]:
    return {"cx": round(b["cx"], 3), "cy": round(b["cy"], 3), "w": round(b["w"], 3), "h": round(b["h"], 3),
            "angle": round(b["angle"], 3), "label": b.get("label")}


def aabb(b: Dict[str, Any]) -> List[int]:
    p = box_points(b)
    x0, y0, x1, y1 = p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()
    return [int(round(x0)), int(round(y0)), int(round(x1 - x0)), int(round(y1 - y0))]


def intersection_area(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    kind, pts = cv2.rotatedRectangleIntersection(box_rect(a), box_rect(b))
    if kind == cv2.INTERSECT_NONE or pts is None or len(pts) < 3:
        return 0.0
    return float(cv2.contourArea(cv2.convexHull(pts.astype(np.float32))))


def overlap_rate(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Overlapped area divided by the area of the smaller box (0 = apart, 1 = one lies inside the other)."""
    smaller = min(a["w"] * a["h"], b["w"] * b["h"])
    return 0.0 if smaller <= 0 else min(1.0, intersection_area(a, b) / smaller)


def draw_boxes(boxes: List[Dict[str, Any]], colour=(0, 200, 255)) -> List[Dict[str, Any]]:
    out = []
    for b in boxes[:80]:
        p = box_points(b)
        for i in range(4):
            out.append({"type": "line", "pt1": (int(p[i][0]), int(p[i][1])), "pt2": (int(p[(i + 1) % 4][0]), int(p[(i + 1) % 4][1])),
                        "color": colour, "thickness": 2})
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# Image Division
# ---------------------------------------------------------------------------------------------------------------------------
def divide_span(length: float, parts: int, overlap: float) -> List[Tuple[float, float]]:
    """(start, size) of ``parts`` equal pieces covering ``length`` with the given overlap fraction: S*M - (M-1)*F*L = L."""
    if parts <= 1:
        return [(0.0, float(length))]
    size = length * (1.0 + (parts - 1) * overlap) / parts
    step = size - overlap * length
    return [(i * step, size) for i in range(parts)]


@define("Image Division Tool", CAT,
        "Cuts the region of interest into a grid of equal pieces (with an overlap if you like) so each piece can be processed on its own, "
        "for example by Copy Fill or Group. Gives the pieces' boxes and their pictures.",
        inputs=[img()], outputs=[port("Boxes", "any", "[x, y, w, h] of each piece"), val("Count"), port("Images", "any", "The picture of each piece")],
        params={"roi": [0, 0, 0, 0], "divisions_x": 2, "divisions_y": 2, "overlap_x": 10.0, "overlap_y": 10.0},
        schema={"roi": {"kind": "rect"}, "divisions_x": num(1, 50), "divisions_y": num(1, 50),
                "overlap_x": num(0, 90, 1, "%", 1), "overlap_y": num(0, 90, 1, "%", 1)})
def image_division(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    x, y, w, h = [int(v) for v in t.get_param("roi")]
    if w <= 0 or h <= 0:
        x, y, w, h = 0, 0, a.shape[1], a.shape[0]
    else:
        x, y, w, h = t.get_roi("roi", [0, 0, 1, 1], img_shape=a.shape)
    xs = divide_span(w, int(t.get_param("divisions_x")), float(t.get_param("overlap_x")) / 100.0)
    ys = divide_span(h, int(t.get_param("divisions_y")), float(t.get_param("overlap_y")) / 100.0)
    boxes, pics = [], []
    for sy, hh in ys:
        for sx, ww in xs:
            bx, by = int(round(x + sx)), int(round(y + sy))
            bw, bh = int(round(ww)), int(round(hh))
            bx, by = max(0, min(bx, a.shape[1] - 1)), max(0, min(by, a.shape[0] - 1))
            bw, bh = max(1, min(bw, a.shape[1] - bx)), max(1, min(bh, a.shape[0] - by))
            boxes.append([bx, by, bw, bh])
            pics.append(a[by:by + bh, bx:bx + bw].copy())
    over = [{"type": "rect", "box": b, "color": (0, 200, 255)} for b in boxes[:100]]
    return ok(f"{len(boxes)} pieces ({int(t.get_param('divisions_x'))} x {int(t.get_param('divisions_y'))})", over, Boxes=boxes, Count=len(boxes), Images=pics)


# ---------------------------------------------------------------------------------------------------------------------------
# 2D Array Correction
# ---------------------------------------------------------------------------------------------------------------------------
def _cluster_1d(values: np.ndarray, k: int) -> np.ndarray:
    """Group sorted 1-D values into k clusters by splitting at the k-1 largest gaps."""
    order = np.argsort(values)
    labels = np.zeros(len(values), int)
    if k <= 1 or len(values) <= 1:
        return labels
    gaps = np.diff(values[order])
    cuts = np.sort(np.argsort(gaps)[-(k - 1):]) if len(gaps) >= k - 1 else np.arange(len(gaps))
    cluster = 0
    for i, idx in enumerate(order):
        labels[idx] = cluster
        if i in cuts:
            cluster += 1
    return labels


@define("2D Array Correction", CAT,
        "When parts sit in a regular grid but the locator missed some or put some in the wrong place, this rebuilds the full grid: it fits a "
        "line through each row and each column of the found centres and places every box where the lines cross.",
        inputs=[port("Boxes", "any", "Found boxes")], outputs=[port("Boxes", "any", "The complete grid of boxes"), val("Count"),
                                                                 port("Centers", "any", "Corrected centres [[x, y], ...]")],
        params={"array_rows": 2, "array_columns": 3},
        schema={"array_rows": num(2, 100), "array_columns": num(2, 100)})
def array_correction(t, ctx):
    rows, cols = int(t.get_param("array_rows")), int(t.get_param("array_columns"))
    found = to_boxes(ctx.get("Boxes"))
    if len(found) < 4:
        return ng(f"needs at least 4 boxes to fit a grid, got {len(found)}")
    c = np.array([[b["cx"], b["cy"]] for b in found], np.float64)
    row_id, col_id = _cluster_1d(c[:, 1], rows), _cluster_1d(c[:, 0], cols)
    # 1) a whole-grid fit, centre(r, c) = origin + c * step_c + r * step_r, down-weighting points that sit off the grid, tells which
    #    found boxes are trustworthy
    design = np.column_stack([np.ones(len(c)), col_id, row_id]).astype(np.float64)
    weights = np.ones(len(c))
    for _ in range(8):
        sw = np.sqrt(weights)[:, None]
        coef, *_r = np.linalg.lstsq(design * sw, c * sw, rcond=None)
        res = np.linalg.norm(design @ coef - c, axis=1)
        scale = max(1.0, 1.4826 * float(np.median(res)))
        weights = 1.0 / (1.0 + (res / (2.0 * scale)) ** 2)
    trusted = res <= max(3.0 * scale, 0.1 * min(float(np.median([b["w"] for b in found])), float(np.median([b["h"] for b in found]))))
    # 2) lines through the trusted centres of each row and each column (they follow a mildly bent grid better than one straight model)
    row_lines, col_lines = [], []
    for r in range(rows):
        p = c[(row_id == r) & trusted]
        if len(p) >= max(2, int(math.ceil(0.5 * cols))):
            a_, b_ = np.polyfit(p[:, 0], p[:, 1], 1) if np.ptp(p[:, 0]) > 1e-6 else (0.0, p[:, 1].mean())
            row_lines.append((r, a_, b_))
    for k in range(cols):
        p = c[(col_id == k) & trusted]
        if len(p) >= max(2, int(math.ceil(0.5 * rows))):
            a_, b_ = np.polyfit(p[:, 1], p[:, 0], 1) if np.ptp(p[:, 1]) > 1e-6 else (0.0, p[:, 0].mean())
            col_lines.append((k, a_, b_))
    if len(row_lines) < 2 or len(col_lines) < 2:
        return ng("not enough boxes in line to fit the rows and columns (need at least 2 of each)")
    w = float(np.median([b["w"] for b in found]))
    h = float(np.median([b["h"] for b in found]))

    def complete(lines, n):                                  # a row or column that was not found at all is placed by the spacing of the others
        have = {l[0]: l for l in lines}
        if len(have) == n:
            return [have[i] for i in range(n)]
        idx = np.array(list(have), float)
        a_fit = np.polyfit(idx, [have[i][1] for i in have], 1)
        b_fit = np.polyfit(idx, [have[i][2] for i in have], 1)
        return [have[i] if i in have else (i, np.polyval(a_fit, i), np.polyval(b_fit, i)) for i in range(n)]
    row_lines, col_lines = complete(row_lines, rows), complete(col_lines, cols)
    centers, boxes = [], []
    for _, ra, rb in row_lines:
        for _, ca, cb in col_lines:
            den = 1.0 - ca * ra                               # y = ra*x + rb  and  x = ca*y + cb
            x = (ca * rb + cb) / den if abs(den) > 1e-9 else cb
            y = ra * x + rb
            centers.append([round(float(x), 3), round(float(y), 3)])
            boxes.append({"cx": float(x), "cy": float(y), "w": w, "h": h, "angle": 0.0, "label": None})
    missed = rows * cols - len(found)
    return ok(f"rebuilt a {rows} x {cols} grid from {len(found)} found boxes", draw_boxes(boxes),
              Boxes=[box_out(b) for b in boxes], Count=len(boxes), Centers=centers)


# ---------------------------------------------------------------------------------------------------------------------------
# Pixel Transformation
# ---------------------------------------------------------------------------------------------------------------------------
@define("Pixel Transformation", CAT,
        "Turns a label picture (each pixel holds a class number) into a black-and-white mask: pixels whose value is in the class list become 255, "
        "everything else 0. Used after instance segmentation to pick the classes you want.",
        inputs=[img(), port("Class_Index", "any", "List of class numbers"), val("Class_Count", "Number of entries to use")],
        outputs=[img(), val("Pixel_Count", "How many pixels are white")],
        params={"class_list": "1"}, schema={"class_list": {"kind": "text", "hint": "class numbers separated by commas, e.g. 1,5,8"}})
def pixel_transformation(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    wanted = ctx.get("Class_Index")
    if wanted is None:
        try:
            wanted = [int(p) for p in str(t.get_param("class_list", "")).replace(";", ",").split(",") if p.strip()]
        except ValueError:
            return err("the class list must be whole numbers separated by commas")
    elif isinstance(wanted, (int, float)):
        wanted = [int(wanted)]
    wanted = [int(v) for v in wanted]
    n = ctx.get("Class_Count")
    if n is not None:
        wanted = wanted[:max(0, int(t.as_float(n, len(wanted))))]
    g = as_gray(a)
    out = (np.isin(g, wanted) * 255).astype(np.uint8)
    return ok(f"{int(np.count_nonzero(out))} pixels in classes {wanted}", Image=out, Pixel_Count=int(np.count_nonzero(out)))


# ---------------------------------------------------------------------------------------------------------------------------
# Box Merge
# ---------------------------------------------------------------------------------------------------------------------------
@define("Box Merge", CAT,
        "Joins boxes that overlap into one box. 'Flaw Priority' keeps the most important label of the group, 'Box Label' only joins boxes "
        "with the same label, 'No Box Label' joins any boxes that overlap.",
        inputs=[port("Boxes", "any", "Boxes to merge"), port("Labels", "any", "A label for each box")],
        outputs=[port("Boxes", "any", "The merged boxes"), port("Labels", "any", "Their labels"), val("Count")],
        params={"overlap_rate": 0.3, "merge_type": "Merge Type Flaw Priority", "flaw_priority": "scratch,dent,stain", "split_char": ",",
                "priority_sort": "Grade Down"},
        schema={"overlap_rate": num(0, 1, 0.05, decimals=2),
                "merge_type": enum("Merge Type Flaw Priority", "Merge Type Box Label", "Merge Type No Box Label"),
                "flaw_priority": {"kind": "text", "hint": "labels from most to least important, separated by the split character"},
                "split_char": {"kind": "text", "hint": "the character between labels"}, "priority_sort": enum("Grade Up", "Grade Down")})
def box_merge(t, ctx):
    boxes = to_boxes(ctx.get("Boxes"), ctx.get("Labels"))
    if not boxes:
        return ok("no boxes", Boxes=[], Labels=[], Count=0)
    rate = float(t.get_param("overlap_rate"))
    kind = str(t.get_param("merge_type"))
    sep = str(t.get_param("split_char") or ",")
    order = [s.strip() for s in str(t.get_param("flaw_priority")).split(sep) if s.strip()]
    rank = {lab: i for i, lab in enumerate(order)}
    rank_best_first = str(t.get_param("priority_sort")) == "Grade Down"                 # Grade Down: the first label listed wins

    def priority(label):
        r = rank.get(str(label), None)
        if r is None:
            return -1e9
        return -r if rank_best_first else r

    n = len(boxes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if kind == "Merge Type Box Label" and boxes[i]["label"] != boxes[j]["label"]:
                continue
            if overlap_rate(boxes[i], boxes[j]) > rate:
                parent[find(i)] = find(j)
    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    merged = []
    for members in groups.values():
        pts = np.vstack([box_points(boxes[i]) for i in members])
        (cx, cy), (w, h), ang = cv2.minAreaRect(pts)
        if ang >= 45.0:                                           # describe it as a box that is at most 45 degrees off axis
            w, h, ang = h, w, ang - 90.0
        elif ang <= -45.0:
            w, h, ang = h, w, ang + 90.0
        if kind == "Merge Type Flaw Priority":
            label = max((boxes[i]["label"] for i in members), key=priority)
        else:
            label = boxes[members[0]]["label"]
        merged.append({"cx": cx, "cy": cy, "w": w, "h": h, "angle": -ang, "label": label})
    return ok(f"{n} boxes -> {len(merged)}", draw_boxes(merged, (0, 255, 0)), Boxes=[box_out(b) for b in merged],
              Labels=[b["label"] for b in merged], Count=len(merged))


# ---------------------------------------------------------------------------------------------------------------------------
# Box Overlap Calculation
# ---------------------------------------------------------------------------------------------------------------------------
@define("Box Overlap", CAT,
        "How much two boxes overlap: the overlapped area divided by the area of the smaller box. 0 = apart, 1 = one is inside the other.",
        inputs=[port("Box1", "any", "First box"), port("Box2", "any", "Second box")],
        outputs=[val("Overlap_Rate", "0 to 1"), port("Overlap_Box", "any", "The overlapped area's bounding box")],
        params={"box1": [100, 100, 120, 80], "box2": [160, 120, 120, 80]},
        schema={"box1": {"kind": "rect"}, "box2": {"kind": "rect"}})
def box_overlap(t, ctx):
    a = to_box(ctx.get("Box1") if ctx.get("Box1") is not None else t.get_param("box1"))
    b = to_box(ctx.get("Box2") if ctx.get("Box2") is not None else t.get_param("box2"))
    if a is None or b is None:
        return err("Box Overlap: a box is not valid (need x, y, w, h)")
    rate = overlap_rate(a, b)
    kind, pts = cv2.rotatedRectangleIntersection(box_rect(a), box_rect(b))
    region = None
    if kind != cv2.INTERSECT_NONE and pts is not None and len(pts) >= 3:
        q = pts.reshape(-1, 2)
        x0, y0, x1, y1 = q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()
        region = [int(round(x0)), int(round(y0)), int(round(x1 - x0)), int(round(y1 - y0))]
    return ok(f"overlap {rate:.3f}", draw_boxes([a, b]) + [{"type": "text", "text": f"overlap {rate:.2f}", "pt": (10, 24), "color": (0, 255, 255)}],
              Overlap_Rate=rate, Overlap_Box=region)


# ---------------------------------------------------------------------------------------------------------------------------
# Box Filtering
# ---------------------------------------------------------------------------------------------------------------------------
@define("Box Filtering", CAT,
        "Keeps only the boxes that are at least partly white in a mask picture: it counts the 255-valued pixels inside each box and drops boxes "
        "where that share is below the minimum.",
        inputs=[img("Image", "Binary mask picture"), port("Boxes", "any", "Boxes to check")],
        outputs=[port("Boxes", "any", "Boxes that were kept"), port("Removed", "any", "Boxes that were dropped"), val("Count", "Kept")],
        params={"min_overlap": 0.1}, schema={"min_overlap": num(0, 1, 0.05, decimals=2)})
def box_filtering(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    mask = as_gray(a) == 255
    boxes = to_boxes(ctx.get("Boxes"))
    min_ov = float(t.get_param("min_overlap"))
    kept, removed = [], []
    for b in boxes:
        poly = np.zeros(mask.shape, np.uint8)
        cv2.fillConvexPoly(poly, np.round(box_points(b)).astype(np.int32), 1)
        area = int(poly.sum())
        share = int(np.count_nonzero(mask & (poly > 0))) / area if area else 0.0
        (kept if share >= min_ov else removed).append(dict(b, share=round(share, 4)))
    return ok(f"kept {len(kept)} of {len(boxes)}", draw_boxes(kept, (0, 255, 0)) + draw_boxes(removed, (0, 0, 255)),
              Boxes=[box_out(b) for b in kept], Removed=[box_out(b) for b in removed], Count=len(kept))
