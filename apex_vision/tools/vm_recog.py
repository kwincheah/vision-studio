"""VisionMaster guide, chapter "Recognition": DL Character Location, DL Character Recognition, DL Single Character Recognition, DL Code Reading and
ML Classification.

The "default model" of VisionMaster's character modules is a trained neural network that is not available here. These modules work two ways:
 * with a model: an ONNX text-line model (CTC) for recognition, or an ONNX detector (for example YOLO) for locating / single characters;
 * without one: a built-in reader that finds characters by thresholding and connected regions and names them by comparing each with
   rendered letters, digits and symbols in several fonts. That suits clean printed characters in a known size range; for dot-matrix, embossed,
   curved or heavily degraded print, use a trained model.
"""
import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from apex_vision.core import dl_engine as dl
from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import as_gray, define, err, get_image, img, ng, no_image, ok, port, val

CAT = "Recognition"
DIGITS = "0123456789"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LOWER = "abcdefghijklmnopqrstuvwxyz"
SPECIAL = "-_./:+*#@%&()[]=<>?!,;"
CHAR_SETS = {"All": DIGITS + UPPER + LOWER + SPECIAL, "Numbers": DIGITS, "Uppercase Letters": UPPER, "Lowercase Letters": LOWER, "Letters": UPPER + LOWER,
             "Numbers and Uppercase Letters": DIGITS + UPPER, "Numbers and Letters": DIGITS + UPPER + LOWER, "Special Characters": SPECIAL}
FILTERS = list(CHAR_SETS) + ["Custom"]
GLYPH_W, GLYPH_H = 20, 28


# ---------------------------------------------------------------------------------------------------------------------------
# the built-in reader
# ---------------------------------------------------------------------------------------------------------------------------
def _glyph_vector(binary: np.ndarray) -> Optional[Tuple[np.ndarray, float]]:
    """A 20 x 28 description of the ink in a tight crop (ink = 255), and the crop's width / height."""
    ys, xs = np.nonzero(binary)
    if len(xs) == 0:
        return None
    crop = binary[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    aspect = w / float(h)
    s = min(GLYPH_W / float(w), GLYPH_H / float(h))
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    small = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA).astype(np.float32)
    canvas = np.zeros((GLYPH_H, GLYPH_W), np.float32)
    ox, oy = (GLYPH_W - nw) // 2, (GLYPH_H - nh) // 2
    canvas[oy:oy + nh, ox:ox + nw] = small
    canvas = cv2.GaussianBlur(canvas, (3, 3), 0.8)
    v = canvas.ravel() - canvas.mean()
    n = np.linalg.norm(v)
    return (v / n, aspect) if n > 1e-6 else None


_BANK: Optional[Tuple[List[str], np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = None


def glyph_bank():
    """(characters, vectors, aspect ratios, heights relative to a capital) of every character in several fonts."""
    global _BANK
    if _BANK is not None:
        return _BANK
    chars, vecs, aspects, rel, ycen = [], [], [], [], []
    fonts = [cv2.FONT_HERSHEY_SIMPLEX, cv2.FONT_HERSHEY_DUPLEX, cv2.FONT_HERSHEY_COMPLEX, cv2.FONT_HERSHEY_TRIPLEX, cv2.FONT_HERSHEY_PLAIN]
    cap_h = {}
    for fi, font in enumerate(fonts):
        (_, th), _base = cv2.getTextSize("H", font, 2.0, 3)
        cap_h[fi] = float(th)
    for ch in CHAR_SETS["All"]:
        for fi, font in enumerate(fonts):
            for thick in (2, 4):
                canvas = np.zeros((120, 120), np.uint8)
                cv2.putText(canvas, ch, (20, 90), font, 2.0, 255, thick, cv2.LINE_AA)
                b = (canvas > 100).astype(np.uint8) * 255
                r = _glyph_vector(b)
                if r is None:
                    continue
                ys, xs = np.nonzero(b)
                chars.append(ch)
                vecs.append(r[0])
                aspects.append(r[1])
                rel.append((ys.max() - ys.min() + 1) / cap_h[fi])
                ycen.append((90.0 - (ys.min() + ys.max()) / 2.0) / cap_h[fi])               # height of the middle above the baseline, in capital heights
    _BANK = (chars, np.array(vecs, np.float32), np.array(aspects, np.float32), np.array(rel, np.float32), np.array(ycen, np.float32))
    return _BANK


def classify_glyph(binary: np.ndarray, allowed: str, rel_height: float, ycen: Optional[float] = None) -> Tuple[str, float]:
    """The allowed character most like this ink picture, and a 0..1 confidence."""
    r = _glyph_vector(binary)
    if r is None:
        return "", 0.0
    vec, aspect = r
    chars, bank, asp, rel, yc = glyph_bank()
    allow = np.array([c in allowed for c in chars])
    if not allow.any():
        return "", 0.0
    corr = bank @ vec
    pen = 0.15 * np.abs(np.log((asp + 1e-3) / (aspect + 1e-3))) + 0.8 * np.abs(np.log((rel + 1e-3) / (rel_height + 1e-3)))
    if ycen is not None and rel_height < 0.6:                                      # a small mark: where it sits on the line tells - from _ . ,
        pen = pen + 0.9 * np.abs(yc - ycen)
    score = np.where(allow, corr - pen, -9.0)
    j = int(np.argmax(score))
    return chars[j], float(np.clip(score[j], 0.0, 1.0))


def binarize_ink(gray: np.ndarray, polarity: str) -> np.ndarray:
    """Ink as 255. Polarity 'Auto' takes the smaller of the two classes of Otsu's split as the ink."""
    g8 = gray if gray.dtype == np.uint8 else np.clip(gray, 0, 255).astype(np.uint8)
    if g8.std() < 2.0:
        return np.zeros_like(g8)
    _, b = cv2.threshold(g8, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)           # bright = 255
    if polarity.startswith("Dark"):
        return cv2.bitwise_not(b)
    if polarity.startswith("Light"):
        return b
    return cv2.bitwise_not(b) if (b > 0).mean() > 0.5 else b


def segment_characters(ink: np.ndarray, min_area: int = 8) -> List[Tuple[int, int, int, int]]:
    """Character boxes (x, y, w, h) in reading order from an ink picture."""
    h_roi, w_roi = ink.shape
    n, labels, stats, _ = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8), connectivity=8)
    boxes = [list(map(int, stats[i][:4])) for i in range(1, n) if stats[i][4] >= min_area and stats[i][3] >= 3 and not (stats[i][2] >= w_roi - 1 and stats[i][3] >= h_roi - 1)]
    if not boxes:
        return []
    tall = np.median([b[3] for b in boxes if b[3] >= 0.5 * max(x[3] for x in boxes)] or [boxes[0][3]])
    # join the dots and bars that belong to a character (i, j, :, ;, !, ?, =, %)
    changed = True
    while changed and len(boxes) > 1:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
                gap = max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3])
                small = min(a[3], b[3]) < 0.45 * tall or min(a[2], b[2]) < 0.2 * tall
                if ox > 0.5 * min(a[2], b[2]) and gap < 0.4 * tall and small:
                    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
                    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
                    boxes[i] = [x0, y0, x1 - x0, y1 - y0]
                    del boxes[j]
                    changed = True
                    break
            if changed:
                break
    # lines: boxes whose centres differ in height by over half a character are on different lines
    boxes.sort(key=lambda b: b[1] + b[3] / 2.0)
    lines: List[List[List[int]]] = []
    for b in boxes:
        cy = b[1] + b[3] / 2.0
        for ln in lines:
            if abs(np.mean([q[1] + q[3] / 2.0 for q in ln]) - cy) < 0.6 * tall:
                ln.append(b)
                break
        else:
            lines.append([b])
    lines.sort(key=lambda ln: np.mean([q[1] + q[3] / 2.0 for q in ln]))
    out = []
    for ln in lines:
        out += [tuple(b) for b in sorted(ln, key=lambda q: q[0])]
    return out


def contrast_score(gray: np.ndarray, ink: np.ndarray, box) -> float:
    x, y, w, h = box
    g_ = gray[y:y + h, x:x + w].astype(np.float32)
    k = ink[y:y + h, x:x + w] > 0
    if not k.any() or k.all():
        return 0.0
    return float(abs(g_[k].mean() - g_[~k].mean()))


def allowed_chars(t) -> str:
    if not bool(t.get_param("filter_enable")):
        return CHAR_SETS["All"]
    name = str(t.get_param("character_filter"))
    if name == "Custom":
        return str(t.get_param("custom_characters"))
    return CHAR_SETS.get(name, CHAR_SETS["All"])


# ---------------------------------------------------------------------------------------------------------------------------
# model helpers
# ---------------------------------------------------------------------------------------------------------------------------
def ctc_decode(logits: np.ndarray, charset: str, blank: int = 0) -> Tuple[str, List[float]]:
    """Greedy CTC decoding of [T, C] scores: repeats and blanks are dropped; characters are charset[index - 1] after a leading blank."""
    logits = np.asarray(logits, np.float64)
    if logits.min() < 0 or logits.max() > 1.0 or not np.allclose(logits.sum(axis=-1), 1.0, atol=1e-3):             # scores, not yet probabilities: softmax each frame
        e = np.exp(logits - logits.max(axis=-1, keepdims=True))
        probs = e / e.sum(axis=-1, keepdims=True)
    else:
        probs = logits
    idx = probs.argmax(axis=-1)
    text, conf, prev = [], [], -1
    for t, i in enumerate(idx):
        if i != prev and i != blank:
            k = int(i) - 1 if blank == 0 else int(i)
            if 0 <= k < len(charset):
                text.append(charset[k])
                conf.append(float(probs[t, i]))
        prev = int(i)
    return "".join(text), conf


def run_text_model(path: str, backend: str, gray: np.ndarray, allowed: Optional[str]) -> Tuple[str, List[float]]:
    model = dl.load_model(path, backend, "cpu")
    charset = str(model.meta.get("charset", ""))
    if not charset:
        raise dl.DLModelError("this text model has no 'charset' in its .json file next to it, so its outputs cannot be turned into characters")
    norm, resize, rgb = dl.settings_from_meta(model, "Auto", "Stretch", False)
    blob, _ = dl.prepare_input(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), model, (0, 0), resize, norm, rgb)
    out = np.asarray(model.run(blob)[0], np.float32)
    out = np.squeeze(out, axis=0) if out.shape[0] == 1 and out.ndim == 3 else out
    if out.ndim == 3:
        out = out[:, 0, :]
    if out.ndim != 2:
        raise dl.DLModelError(f"unexpected output shape {tuple(out.shape)} from the text model")
    blank = int(model.meta.get("blank", 0))
    if out.shape[0] == len(charset) + 1 and out.shape[1] != len(charset) + 1:
        out = out.T
    if allowed is not None and allowed != CHAR_SETS["All"]:                       # character filtering: characters outside the set cannot win
        keep = np.array([c in allowed for c in charset])
        offset = 1 if blank == 0 else 0
        mask = np.full(out.shape[1], -1e4, np.float32)
        mask[blank] = 0.0
        for k, kk in enumerate(keep):
            if kk:
                mask[k + offset] = 0.0
        out = out + mask
    return ctc_decode(out, charset, blank)


def boxes_from_model(path: str, backend: str, crop: np.ndarray, conf: float, iou: float, max_det: int):
    model = dl.load_model(path, backend, "cpu")
    norm, resize, rgb = dl.settings_from_meta(model, "Auto", "Auto" if model.meta.get("resize") else "Letterbox", True)
    blob, info = dl.prepare_input(crop, model, (0, 0), resize, norm, rgb)
    dets = dl.decode_detections(model.run(blob), info, conf, iou, max_det, num_classes=len(model.labels) or None)
    labels = model.labels
    return [{"box": [int(d["box"][0]), int(d["box"][1]), int(d["box"][2]), int(d["box"][3])], "score": float(d["score"]),
             "label": labels[d["class_id"]] if d["class_id"] < len(labels) else str(d["class_id"])} for d in dets]


def _nms(items: List[Dict[str, Any]], overlap: float) -> List[Dict[str, Any]]:
    items = sorted(items, key=lambda d: -d["score"])
    kept: List[Dict[str, Any]] = []
    for d in items:
        x, y, w, h = d["box"]
        bad = False
        for k in kept:
            kx, ky, kw, kh = k["box"]
            iw, ih = min(x + w, kx + kw) - max(x, kx), min(y + h, ky + kh) - max(y, ky)
            if iw > 0 and ih > 0 and iw * ih / float(min(w * h, kw * kh) + 1e-9) > overlap:
                bad = True
                break
        if not bad:
            kept.append(d)
    return kept


def sort_items(items: List[Dict[str, Any]], how: str) -> List[Dict[str, Any]]:
    if how.startswith("Center Y"):
        return sorted(items, key=lambda d: d["box"][1] + d["box"][3] / 2.0)
    if how.startswith("Confidence"):
        return sorted(items, key=lambda d: -d["score"])
    return sorted(items, key=lambda d: d["box"][0] + d["box"][2] / 2.0)


def model_path(t) -> str:
    """The model file to load: the typed path, or the copy saved inside the solution when the file is not here. '' when there is none."""
    raw = str(t.get_param("model_file") or "").strip()
    if not raw and not t.parameters.get("model_data"):
        return ""
    return dl.effective_path(t, "model_file")


def _roi(t, a: np.ndarray) -> Tuple[int, int, int, int]:
    x, y, w, h = [int(v) for v in t.get_param("roi")]
    if w > 0 and h > 0:
        return tuple(int(v) for v in g.clamp_roi((x, y, w, h), a.shape))
    return 0, 0, a.shape[1], a.shape[0]


def locate_builtin(gray_roi: np.ndarray, polarity: str, min_area: int):
    """Character candidates found by the built-in method: [{box, score}], plus the ink picture."""
    ink = binarize_ink(gray_roi, polarity)
    out = []
    for b in segment_characters(ink, min_area):
        x, y, w, h = b
        fill = float((ink[y:y + h, x:x + w] > 0).mean())
        c = contrast_score(gray_roi, ink, b)
        out.append({"box": [int(x), int(y), int(w), int(h)], "score": float(np.clip(0.6 * min(1.0, c / 80.0) + 0.4 * min(1.0, fill / 0.25), 0.0, 1.0))})
    return out, ink


LOC_PARAMS = {"roi": [0, 0, 0, 0], "model_file": "", "save_in_solution": False, "model_data": {}, "backend": "Auto", "polarity": "Auto", "max_number": 1, "min_confidence": 0.3, "overlap_threshold": 0.3,
              "sort_object": "Center X", "edge_filter_enable": False, "min_edge_score": 0.5, "width_enable": False, "min_width": 5, "max_width": 200,
              "height_enable": False, "min_height": 5, "max_height": 200, "min_area": 8}
LOC_SCHEMA = {"roi": {"kind": "rect"}, "save_in_solution": {"kind": "bool"}, "model_file": {"kind": "path", "filters": "ONNX models (*.onnx);;All files (*)"}, "backend": enum("Auto", "ONNX Runtime", "OpenCV DNN"),
              "polarity": enum("Auto", "Dark on Light", "Light on Dark"), "max_number": num(1, 100), "min_confidence": num(0, 1, 0.05, decimals=2),
              "overlap_threshold": num(0, 1, 0.05, decimals=2), "sort_object": enum("Center X", "Center Y", "Confidence"), "edge_filter_enable": {"kind": "bool"},
              "min_edge_score": num(0, 1, 0.05, decimals=2), "width_enable": {"kind": "bool"}, "min_width": num(1, 10000, unit="px"), "max_width": num(1, 10000, unit="px"),
              "height_enable": {"kind": "bool"}, "min_height": num(1, 10000, unit="px"), "max_height": num(1, 10000, unit="px"), "min_area": num(1, 100000, unit="px")}


def find_characters(t, gray: np.ndarray, full: np.ndarray):
    """(items, ink or None, (x0, y0)): located characters in full-picture coordinates, after the size and confidence rules. Raises DLModelError."""
    x0, y0, rw, rh = _roi(t, full)
    roi = gray[y0:y0 + rh, x0:x0 + rw]
    path = model_path(t)
    if path:
        crop = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
        items = boxes_from_model(path, str(t.get_param("backend")), crop, float(t.get_param("min_confidence")), float(t.get_param("overlap_threshold")), 100)
        ink = None
    else:
        items, ink = locate_builtin(roi, str(t.get_param("polarity")), int(t.get_param("min_area")))
    keep = []
    for d in items:
        x, y, w, h = d["box"]
        if d["score"] < float(t.get_param("min_confidence")):
            continue
        if bool(t.get_param("width_enable")) and not float(t.get_param("min_width")) <= w <= float(t.get_param("max_width")):
            continue
        if bool(t.get_param("height_enable")) and not float(t.get_param("min_height")) <= h <= float(t.get_param("max_height")):
            continue
        if bool(t.get_param("edge_filter_enable")):                                         # share of the box's border that is on an edge
            patch = cv2.Canny(roi[max(0, y):y + h, max(0, x):x + w], 50, 150) if w > 2 and h > 2 else None
            if patch is None or float((patch > 0).mean()) < float(t.get_param("min_edge_score")) * 0.2:
                continue
        keep.append(d)
    keep = _nms(keep, float(t.get_param("overlap_threshold")))
    keep = sort_items(keep, str(t.get_param("sort_object")))[:int(t.get_param("max_number"))]
    for d in keep:
        d["box_roi"] = list(d["box"])
        d["box"] = [d["box"][0] + x0, d["box"][1] + y0, d["box"][2], d["box"][3]]
    return keep, ink, (x0, y0)


LOC_OUT = [img(), val("Count"), port("Boxes", "any", "[[x, y, w, h], ...] in reading order"), port("Centers", "any", "[[x, y], ...]"), port("Scores", "any", "Confidence of each")]


@define("DL Character Location", CAT,
        "Finds where each character is, as boxes, even on a busy background and where the print moves about. With a detection model (ONNX) it "
        "finds what the model was trained on; without one it finds dark or light characters by thresholding the region.",
        inputs=[img()], outputs=LOC_OUT, params=dict(LOC_PARAMS), schema=dict(LOC_SCHEMA))
def dl_character_location(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    try:
        items, _, _ = find_characters(t, as_gray(a), a)
    except dl.DLModelError as e:
        return err(f"DL Character Location: {e}")
    over = [{"type": "rect", "box": d["box"], "color": (0, 255, 0), "label": f"{d['score']:.2f}"} for d in items]
    if not items:
        return ng("no character found: check the region, the polarity and the minimum confidence", Image=a, Count=0, Boxes=[], Centers=[], Scores=[])
    return ok(f"{len(items)} character(s) located", over, Image=a, Count=len(items), Boxes=[d["box"] for d in items],
              Centers=[[d["box"][0] + d["box"][2] / 2.0, d["box"][1] + d["box"][3] / 2.0] for d in items], Scores=[round(d["score"], 4) for d in items])


# ---------------------------------------------------------------------------------------------------------------------------
# DL Character Recognition / Single Character Recognition
# ---------------------------------------------------------------------------------------------------------------------------
REC_PARAMS = {"filter_enable": False, "character_filter": "All", "custom_characters": "", "include_spaces": True}
REC_SCHEMA = {"filter_enable": {"kind": "bool"}, "character_filter": enum(*FILTERS), "custom_characters": {"kind": "text", "hint": "the characters allowed when the filter is Custom"},
              "include_spaces": {"kind": "bool"}}
REC_OUT = [img(), port("Text", "str", "What was read"), port("Characters", "any", "[{char, score, box}, ...]"), val("Min_Score"), val("Count")]


def line_metrics(boxes: Sequence[Sequence[int]]) -> Tuple[float, float]:
    """(typical tall-character height, baseline y) of a set of character boxes."""
    hs = [b[3] for b in boxes]
    ref = float(np.percentile(hs, 80)) if hs else 1.0
    tall = [b for b in boxes if b[3] >= 0.7 * ref] or list(boxes)
    base = float(np.median([b[1] + b[3] for b in tall])) if tall else 0.0
    return max(1.0, ref), base


def read_builtin(gray_roi: np.ndarray, ink: np.ndarray, boxes: List[Tuple[int, int, int, int]], allowed: str) -> List[Dict[str, Any]]:
    out = []
    ref, base = line_metrics(boxes)                                                    # capitals and digits are the tallest: compare each with those
    for (x, y, w, h) in boxes:
        ch, sc = classify_glyph(ink[y:y + h, x:x + w], allowed, h / ref, (base - (y + h / 2.0)) / ref)
        out.append({"char": ch, "score": sc, "box": [int(x), int(y), int(w), int(h)]})
    return out


def _with_spaces(chars: List[Dict[str, Any]], include: bool) -> str:
    if not chars:
        return ""
    widths = [c["box"][2] for c in chars]
    typical = float(np.median(widths)) if widths else 1.0
    text = ""
    for i, c in enumerate(chars):
        if include and i:
            p = chars[i - 1]["box"]
            same_line = abs((p[1] + p[3] / 2.0) - (c["box"][1] + c["box"][3] / 2.0)) < 0.6 * max(p[3], c["box"][3])
            if same_line and c["box"][0] - (p[0] + p[2]) > 0.9 * typical:
                text += " "
            elif not same_line:
                text += " "
        text += c["char"] if c["char"] else "?"
    return text


@define("DL Character Recognition", CAT,
        "Reads the text in a region. With a text model (ONNX, CTC) it reads the line directly; without one it finds each character and names it "
        "by comparing with letters, digits and symbols in several fonts (good for clean printed characters). The character filter limits what each "
        "character may be, which settles O / 0 and I / 1 doubts.",
        inputs=[img()], outputs=REC_OUT, params={**LOC_PARAMS, **REC_PARAMS, "min_confidence": 0.5, "max_number": 100, "model_file": ""},
        schema={**LOC_SCHEMA, **REC_SCHEMA})
def dl_character_recognition(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    allowed = allowed_chars(t)
    if bool(t.get_param("filter_enable")) and not allowed:
        return err("no characters chosen for the filter: type some in Custom Characters, or choose another filter")
    x0, y0, rw, rh = _roi(t, a)
    roi = gray[y0:y0 + rh, x0:x0 + rw]
    try:
        path = model_path(t)
    except dl.DLModelError as e:
        return err(f"DL Character Recognition: {e}")
    thr = float(t.get_param("min_confidence"))
    if path:
        try:
            text, confs = run_text_model(path, str(t.get_param("backend")), roi, allowed if bool(t.get_param("filter_enable")) else None)
        except dl.DLModelError as e:
            return err(f"DL Character Recognition: {e}")
        chars = [{"char": c, "score": s, "box": [x0, y0, rw, rh]} for c, s in zip(text, confs)]
        low = min(confs) if confs else 0.0
        verdict = bool(text) and low >= thr
        return (ok if verdict else ng)(f"read '{text}' (lowest confidence {low:.2f})  [text model]", [{"type": "rect", "box": [x0, y0, rw, rh], "color": (0, 255, 0) if verdict else (0, 0, 255),
                                                                                                     "label": text}], Image=a, Text=text, Characters=chars, Min_Score=low, Count=len(text))
    ink = binarize_ink(roi, str(t.get_param("polarity")))
    boxes = segment_characters(ink, int(t.get_param("min_area")))[:int(t.get_param("max_number"))]
    if not boxes:
        return ng("no characters found in the region: check the region and the polarity", Image=a, Text="", Characters=[], Min_Score=0.0, Count=0)
    chars = read_builtin(roi, ink, boxes, allowed)
    low = min(c["score"] for c in chars)
    for c in chars:
        c["box"] = [c["box"][0] + x0, c["box"][1] + y0, c["box"][2], c["box"][3]]
        if c["score"] < thr:
            c["char"] = c["char"] or "?"
    text = _with_spaces(chars, bool(t.get_param("include_spaces")))
    verdict = low >= thr
    over = [{"type": "rect", "box": c["box"], "color": (0, 255, 0) if c["score"] >= thr else (0, 0, 255), "label": c["char"]} for c in chars]
    return (ok if verdict else ng)(f"read '{text}' (lowest confidence {low:.2f})", over, Image=a, Text=text, Characters=chars, Min_Score=low, Count=len(chars))


@define("DL Single Character Recognition", CAT,
        "Finds each character and names it in one step - best for several lines of text or characters spread over a part. With a detection model "
        "(ONNX) each detection's class is the character; without one, the built-in reader is used. Characters come out in the order you choose.",
        inputs=[img(), port("Boxes", "any", "Character boxes from DL Character Location (optional)")],
        outputs=REC_OUT, params={**LOC_PARAMS, **REC_PARAMS, "max_number": 100, "min_confidence": 0.5, "overlap_threshold": 0.5}, schema={**LOC_SCHEMA, **REC_SCHEMA})
def dl_single_character_recognition(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    allowed = allowed_chars(t)
    if bool(t.get_param("filter_enable")) and not allowed:
        return err("no characters chosen for the filter: type some in Custom Characters, or choose another filter")
    try:
        path = model_path(t)
    except dl.DLModelError as e:
        return err(f"DL Single Character Recognition: {e}")
    thr = float(t.get_param("min_confidence"))
    items: List[Dict[str, Any]] = []
    given = ctx.get("Boxes")
    if given is not None:
        from apex_vision.tools.vm_boxes import to_boxes
        bx = to_boxes(given)
        if not bx:
            return err("the boxes are not [x, y, w, h] boxes")
        ink_full = binarize_ink(gray, str(t.get_param("polarity")))
        rects = []
        for b in bx:
            x, y, w, h = int(b["cx"] - b["w"] / 2), int(b["cy"] - b["h"] / 2), int(b["w"]), int(b["h"])
            rects.append((max(0, x), max(0, y), w, h))
        ref, base = line_metrics(rects)
        for (x, y, w, h) in rects:
            ch, sc = classify_glyph(ink_full[y:y + h, x:x + w], allowed, h / ref, (base - (y + h / 2.0)) / ref)
            items.append({"char": ch or "?", "score": sc, "box": [x, y, w, h]})
    else:
        try:
            found, ink, (ox, oy) = find_characters(t, gray, a)
        except dl.DLModelError as e:
            return err(f"DL Single Character Recognition: {e}")
        if path:
            for d in found:
                lab = d.get("label", "")
                if bool(t.get_param("filter_enable")) and lab and lab not in allowed:
                    continue
                items.append({"char": lab or "?", "score": d["score"], "box": d["box"]})
        else:
            ref, base = line_metrics([d["box_roi"] for d in found]) if found else (1.0, 0.0)
            for d in found:
                x, y, w, h = d["box_roi"]
                ch, sc = classify_glyph(ink[y:y + h, x:x + w], allowed, h / ref, (base - (y + h / 2.0)) / ref)
                items.append({"char": ch or "?", "score": sc, "box": d["box"]})
    items = sort_items(items, str(t.get_param("sort_object")))[:int(t.get_param("max_number"))] if given is None else items
    if not items:
        return ng("no characters found", Image=a, Text="", Characters=[], Min_Score=0.0, Count=0)
    low = min(i["score"] for i in items)
    text = _with_spaces(items, bool(t.get_param("include_spaces"))) if str(t.get_param("sort_object")).startswith("Center X") else "".join(i["char"] for i in items)
    over = [{"type": "rect", "box": i["box"], "color": (0, 255, 0) if i["score"] >= thr else (0, 0, 255), "label": i["char"]} for i in items]
    return (ok if low >= thr else ng)(f"read '{text}' ({len(items)} character(s), lowest confidence {low:.2f})", over, Image=a, Text=text, Characters=items, Min_Score=low, Count=len(items))


# ---------------------------------------------------------------------------------------------------------------------------
# DL Code Reading
# ---------------------------------------------------------------------------------------------------------------------------
def _grade(pct: float) -> str:
    return "A" if pct >= 70 else "B" if pct >= 55 else "C" if pct >= 40 else "D" if pct >= 20 else "F"


def _decode_all(gray: np.ndarray, kinds: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if "2D" in kinds:
        det = cv2.QRCodeDetector()
        try:
            good, texts, pts, _ = det.detectAndDecodeMulti(gray)
        except cv2.error:
            good, texts, pts = False, [], None
        if good and pts is not None:
            for tx, p in zip(texts, pts):
                if tx:
                    out.append({"text": tx, "type": "QR", "points": p.astype(float).tolist()})
        if not out:
            tx, p, _ = det.detectAndDecode(gray)
            if tx and p is not None:
                out.append({"text": tx, "type": "QR", "points": p.reshape(-1, 2).astype(float).tolist()})
    if "1D" in kinds:
        try:
            bd = cv2.barcode_BarcodeDetector()
            r = bd.detectAndDecodeWithType(gray)
            if len(r) == 4:
                good, texts, types, pts = r
                if good and pts is not None:
                    for tx, ty, p in zip(texts, types, pts):
                        if tx:
                            out.append({"text": str(tx), "type": str(ty) or "1D", "points": p.astype(float).tolist()})
        except (AttributeError, cv2.error, ValueError):
            pass
    return out


@define("DL Code Reading", CAT,
        "Reads the bar codes and 2D codes (QR) in a region, as many as it can find: gives each code's text, type and outline. Tries both polarities and "
        "mirrored pictures when asked, stops after the time limit, and can grade each code's print contrast A to F.",
        inputs=[img()],
        outputs=[img(), port("Text", "str", "Text of the first code"), port("Codes", "any", "[{text, type, points, grade}, ...]"), val("Count"), port("Texts", "any", "All the texts")],
        params={"roi": [0, 0, 0, 0], "code_kind": "1D and 2D", "polarity": "Any", "mirror": "Any", "time_limit_ms": 0, "max_codes": 20, "grade_enable": False,
                "expected_text": ""},
        schema={"roi": {"kind": "rect"}, "code_kind": enum("1D and 2D", "1D only", "2D only"), "polarity": enum("Any", "Dark on White", "White on Dark"),
                "mirror": enum("Any", "Not Mirrored", "Mirrored"), "time_limit_ms": num(0, 600000, unit="ms"), "max_codes": num(1, 200), "grade_enable": {"kind": "bool"},
                "expected_text": {"kind": "text", "hint": "when set, the first code must read exactly this"}})
def dl_code_reading(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    gray = as_gray(a)
    x0, y0, rw, rh = _roi(t, a)
    roi = gray[y0:y0 + rh, x0:x0 + rw]
    kinds = {"1D and 2D": ["1D", "2D"], "1D only": ["1D"], "2D only": ["2D"]}[str(t.get_param("code_kind"))]
    limit = float(t.get_param("time_limit_ms")) / 1000.0
    t0 = time.perf_counter()
    variants: List[Tuple[str, np.ndarray]] = []
    pol = str(t.get_param("polarity"))
    mir = str(t.get_param("mirror"))
    bases = [("", roi)] if mir != "Mirrored" else []
    if mir in ("Any", "Mirrored"):
        bases.append(("mirror", cv2.flip(roi, 1)))
    for tag, im in bases:
        if pol in ("Any", "Dark on White"):
            variants.append((tag, im))
        if pol in ("Any", "White on Dark"):
            variants.append((tag + "inv", cv2.bitwise_not(im)))
    found: List[Dict[str, Any]] = []
    seen = set()
    for tag, im in variants:
        if limit > 0 and time.perf_counter() - t0 > limit:
            break
        for c in _decode_all(im, kinds):
            if c["text"] in seen:
                continue
            pts = np.array(c["points"], float)
            if tag.startswith("mirror"):
                pts[:, 0] = roi.shape[1] - 1 - pts[:, 0]
            pts += [x0, y0]
            c["points"] = pts.tolist()
            c["mirrored"] = tag.startswith("mirror")
            seen.add(c["text"])
            found.append(c)
    found = found[:int(t.get_param("max_codes"))]
    over = []
    for c in found:
        p = np.array(c["points"])
        if bool(t.get_param("grade_enable")):
            xs, ys = p[:, 0], p[:, 1]
            patch = gray[int(max(0, ys.min())):int(ys.max()) + 1, int(max(0, xs.min())):int(xs.max()) + 1]
            sc = 0.0 if patch.size == 0 else 100.0 * (float(np.percentile(patch, 95)) - float(np.percentile(patch, 5))) / 255.0
            c["contrast"] = round(sc, 1)
            c["grade"] = _grade(sc)
        over.append({"type": "text", "text": c["text"][:40] + (f" [{c['grade']}]" if "grade" in c else ""), "pt": (int(p[0][0]), max(10, int(p[0][1]) - 8)), "color": (0, 255, 0)})
        over += [{"type": "line", "pt1": (int(p[i][0]), int(p[i][1])), "pt2": (int(p[(i + 1) % len(p)][0]), int(p[(i + 1) % len(p)][1])), "color": (0, 255, 0), "thickness": 2} for i in range(len(p))]
    if not found:
        return ng("no code found: check the region and the code kind", Image=a, Text="", Codes=[], Count=0, Texts=[])
    exp = str(t.get_param("expected_text") or "")
    good = (not exp) or found[0]["text"] == exp
    return (ok if good else ng)(f"{len(found)} code(s): " + "; ".join(c["text"][:30] for c in found[:3]) + ("" if good else f" - the first does not read '{exp}'"), over, Image=a,
                                Text=found[0]["text"], Codes=found, Count=len(found), Texts=[c["text"] for c in found])


# ---------------------------------------------------------------------------------------------------------------------------
# ML Classification
# ---------------------------------------------------------------------------------------------------------------------------
HOG_SIZE = 64
_HOG = None


def ml_features(bgr: np.ndarray) -> np.ndarray:
    """Shape (gradient orientations on a grid) and colour (hue / saturation / value histograms) of a region."""
    global _HOG
    if _HOG is None:
        _HOG = cv2.HOGDescriptor((HOG_SIZE, HOG_SIZE), (32, 32), (16, 16), (16, 16), 9)
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    small = cv2.resize(bgr, (HOG_SIZE, HOG_SIZE), interpolation=cv2.INTER_AREA)
    hog = _HOG.compute(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)).ravel()
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = np.concatenate([cv2.calcHist([hsv], [c], None, [8], r).ravel() for c, r in ((0, [0, 180]), (1, [0, 256]), (2, [0, 256]))])
    hist = hist / max(1.0, hist.sum() / 3.0)
    return np.concatenate([hog / (np.linalg.norm(hog) + 1e-9), 0.7 * hist / (np.linalg.norm(hist) + 1e-9)]).astype(np.float32)


@define("ML Classification", CAT,
        "Sorts pictures into classes you teach it, by classical machine learning (not a neural network): teach it samples of each class, then it "
        "names the class of a new picture from its nearest samples (shape and colour features). Best when you have few pictures; with many, use DL Classify.",
        inputs=[img()],
        outputs=[img(), port("Class", "str"), val("Score", "Share of the nearest samples that agree, weighted by closeness"), port("Scores", "any", "Score of every class"),
                 port("Top", "any", "The best few classes [{class, score}]"), port("Samples", "any", "Samples held for each class")],
        params={"mode": "Classify", "roi": [0, 0, 0, 0], "learn_label": "", "neighbours": 3, "min_score": 0.0, "top_k": 3, "model_file": "", "samples": {}},
        schema={"mode": enum("Classify", "Learn", "Clear Samples"), "roi": {"kind": "rect"}, "learn_label": {"kind": "text", "hint": "the class to teach (in Learn mode)"},
                "neighbours": num(1, 25), "min_score": num(0, 1, 0.05, decimals=2), "top_k": num(1, 10), "model_file": {"kind": "path", "filters": "Model files (*.json);;All files (*)"},
                "samples": {"kind": "json"}})
def ml_classification(t, ctx):
    a = get_image(ctx)
    mode = str(t.get_param("mode"))
    samples = t.parameters.get("samples")
    if not isinstance(samples, dict):
        samples = t.parameters["samples"] = {}
    counts = lambda: {k: len(v) for k, v in samples.items()}  # noqa: E731
    if mode == "Clear Samples":
        samples.clear()
        return ok("all samples removed", Image=a, Class="", Score=0.0, Scores={}, Top=[], Samples={})
    if not samples:
        path = str(t.get_param("model_file") or "").strip()
        if path:
            import json
            import os
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        samples.update({str(k): v for k, v in loaded.items() if isinstance(v, list)})
                except (OSError, ValueError):
                    return err("the model file could not be read")
    if a is None:
        return no_image()
    x, y, w, h = _roi(t, a)
    f = ml_features(a[y:y + h, x:x + w])
    if mode == "Learn":
        label = str(t.get_param("learn_label") or "").strip()
        if not label:
            return err("no class name chosen: type the class to teach in Learn Label")
        samples.setdefault(label, []).append([round(float(v), 5) for v in f])
        path = str(t.get_param("model_file") or "").strip()
        if path:
            import json
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(samples, fh)
            except OSError as e:
                return err(f"could not write the model file: {e}")
        return ok(f"sample added to '{label}' ({len(samples[label])} now)", Image=a, Class=label, Score=1.0, Scores={}, Top=[], Samples=counts())
    if not samples:
        return err("no samples chosen: set Mode to Learn and run on pictures of each class first (or choose a model file)")
    pool, names = [], []
    for k, vs in samples.items():
        for v in vs:
            try:
                arr = np.asarray(v, np.float32)
            except (TypeError, ValueError):
                continue
            if arr.shape == f.shape:
                pool.append(arr)
                names.append(k)
    if not pool:
        return err("the taught samples do not fit this version: clear them and teach again")
    d = np.linalg.norm(np.array(pool) - f, axis=1)
    k = min(int(t.get_param("neighbours")), len(pool))
    nn = np.argsort(d)[:k]
    wts = 1.0 / (d[nn] + 1e-3)
    votes: Dict[str, float] = {}
    for i, wt in zip(nn, wts):
        votes[names[i]] = votes.get(names[i], 0.0) + float(wt)
    total = sum(votes.values())
    scores = {c: round(v / total, 4) for c, v in sorted(votes.items(), key=lambda kv: -kv[1])}
    for c in samples:
        scores.setdefault(c, 0.0)
    best = max(scores, key=lambda c: scores[c])
    top = [{"class": c, "score": s} for c, s in sorted(scores.items(), key=lambda kv: -kv[1])[:int(t.get_param("top_k"))]]
    good = scores[best] >= float(t.get_param("min_score"))
    over = [{"type": "rect", "box": [x, y, w, h], "color": (0, 255, 0) if good else (0, 0, 255), "label": f"{best} {scores[best]:.2f}"}]
    return (ok if good else ng)(f"{best} (score {scores[best]:.2f}) from {len(pool)} sample(s)", over, Image=a, Class=best if good else "", Score=scores[best], Scores=scores, Top=top,
                                Samples=counts())
