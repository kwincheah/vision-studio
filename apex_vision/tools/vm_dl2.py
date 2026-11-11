"""VisionMaster guide, chapter "Deep Learning" (the rest): Classification Registration, DL Image Retrieval, DL Instance Segment and DL Image Defect
Prediction.

Classification Registration and DL Image Retrieval look a picture up in a *gallery*: a set of example pictures grouped by category. Each picture
is turned into a feature vector (by the built-in shape-and-colour description, or by an ONNX feature model for retrieval) and the gallery
categories most like the new picture are returned. The gallery is kept in the module (and so in the solution) and can also be saved to a file.
"""
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core import dl_engine as dl
from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import as_bgr, as_gray, define, err, get_image, img, ng, no_image, ok, port, val
from apex_vision.tools.vm_recog import ml_features

CAT = "Deep Learning"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


# ---------------------------------------------------------------------------------------------------------------------------
# gallery search
# ---------------------------------------------------------------------------------------------------------------------------
def unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, np.float32).ravel()
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def embed(bgr: np.ndarray, model: Optional[dl.DLModel]) -> np.ndarray:
    if model is None:
        return unit(ml_features(bgr))
    norm, resize, rgb = dl.settings_from_meta(model, "Auto", "Auto" if model.meta.get("resize") else "Stretch", True)
    blob, _ = dl.prepare_input(bgr, model, (0, 0), resize, norm, rgb)
    return unit(np.asarray(model.run(blob)[0], np.float32))


def _gallery(t) -> Dict[str, Any]:
    gal = t.parameters.get("gallery")
    if not isinstance(gal, dict):
        gal = t.parameters["gallery"] = {}
    gal.setdefault("classes", {})
    return gal


def _load_file(t, gal: Dict[str, Any]) -> Optional[str]:
    path = str(t.get_param("gallery_file") or "").strip()
    if not path or gal["classes"] or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        classes = data.get("classes") if isinstance(data, dict) else None
        if not isinstance(classes, dict):
            return "the gallery file is not a gallery written by these modules"
        gal.update({"classes": {str(k): v for k, v in classes.items() if isinstance(v, list)}, "dim": data.get("dim")})
    except (OSError, ValueError):
        return "the gallery file could not be read"
    return None


def _save_file(t, gal: Dict[str, Any]) -> Optional[str]:
    path = str(t.get_param("gallery_file") or "").strip()
    if not path:
        return None
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(gal, f)
    except OSError as e:
        return f"could not write the gallery file: {e}"
    return None


def _read(path: str) -> Optional[np.ndarray]:
    try:
        im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        im = None
    return im


def folder_categories(folder: str) -> Dict[str, List[str]]:
    """Category -> picture files. Sub-folders are categories; with none, a picture's name (without trailing numbers) is its category."""
    out: Dict[str, List[str]] = {}
    subs = [d for d in sorted(os.listdir(folder)) if os.path.isdir(os.path.join(folder, d))]
    for d in subs:
        files = [os.path.join(folder, d, n) for n in sorted(os.listdir(os.path.join(folder, d))) if n.lower().endswith(IMAGE_EXT)]
        if files:
            out[d] = files
    if not out:
        import re
        for n in sorted(os.listdir(folder)):
            if n.lower().endswith(IMAGE_EXT):
                cat = re.sub(r"[\s_\-]*\d+$", "", os.path.splitext(n)[0]) or os.path.splitext(n)[0]
                out.setdefault(cat, []).append(os.path.join(folder, n))
    return out


GALLERY_PARAMS = {"mode": "Search", "roi": [0, 0, 0, 0], "category": "", "register_folder": "", "gallery_file": "", "top_k": 3, "min_similarity": 0.5, "gallery": {}}
GALLERY_SCHEMA = {"mode": enum("Search", "Register Image", "Register Folder", "Delete Category", "Clear Gallery"), "roi": {"kind": "rect"},
                  "category": {"kind": "text", "hint": "the category to register or delete"}, "register_folder": {"kind": "dir"},
                  "gallery_file": {"kind": "path", "filters": "Gallery files (*.json);;All files (*)"}, "top_k": num(1, 10), "min_similarity": num(0, 1, 0.05, decimals=2)}
GALLERY_OUT = [img(), port("Class", "str", "The most similar category"), val("Similarity"), port("Top", "any", "[{class, similarity}, ...]"), port("Categories", "any", "Pictures held for each category")]


def _gallery_tool(t, ctx, model_key: Optional[str]):
    a = get_image(ctx)
    mode = str(t.get_param("mode"))
    gal = _gallery(t)
    bad = _load_file(t, gal)
    if bad:
        return err(bad)
    counts = lambda: {k: len(v) for k, v in gal["classes"].items()}  # noqa: E731
    model = None
    if model_key is not None:
        raw = str(t.get_param(model_key) or "").strip()
        if raw or t.parameters.get("model_data"):
            try:
                model = dl.load_model(dl.effective_path(t, model_key), str(t.get_param("backend")), "cpu")
            except dl.DLModelError as e:
                return err(f"{t.tool_name}: {e}")
        else:
            return err("no model chosen: choose the feature model (.onnx) the gallery was made with")
    kind = "model" if model is not None else "builtin"
    if mode == "Clear Gallery":
        gal["classes"].clear()
        problem = _save_file(t, gal)
        return err(problem) if problem else ok("gallery cleared", Image=a, Class="", Similarity=0.0, Top=[], Categories={})
    if mode == "Delete Category":
        name = str(t.get_param("category") or "").strip()
        if name not in gal["classes"]:
            return ng(f"there is no category called '{name}'", Image=a, Class="", Similarity=0.0, Top=[], Categories=counts())
        del gal["classes"][name]
        problem = _save_file(t, gal)
        return err(problem) if problem else ok(f"category '{name}' deleted", Image=a, Class="", Similarity=0.0, Top=[], Categories=counts())

    def add(name: str, vec: np.ndarray) -> Optional[str]:
        if gal.get("dim") not in (None, len(vec)) and gal["classes"]:
            return f"this gallery holds {gal['dim']}-number descriptions but this one gives {len(vec)}: use the same feature model, or clear the gallery"
        gal["dim"] = int(len(vec))
        gal["kind"] = kind
        gal["classes"].setdefault(name, []).append([round(float(v), 5) for v in vec])
        return None

    try:
        if mode == "Register Folder":
            folder = str(t.get_param("register_folder") or "").strip()
            if not folder or not os.path.isdir(folder):
                return err("no folder chosen: choose a folder of pictures (sub-folders, or file names, give the categories)")
            cats = folder_categories(folder)
            if not cats:
                return ng("the folder has no pictures", Image=a, Class="", Similarity=0.0, Top=[], Categories=counts())
            added = 0
            for name, files in cats.items():
                for f in files:
                    im = _read(f)
                    if im is None:
                        continue
                    problem = add(name, embed(im, model))
                    if problem:
                        return err(problem)
                    added += 1
            problem = _save_file(t, gal)
            return err(problem) if problem else ok(f"{added} picture(s) registered in {len(cats)} category(ies)", Image=a, Class="", Similarity=0.0, Top=[], Categories=counts())
        if a is None:
            return no_image()
        x, y, w, h = [int(v) for v in t.get_param("roi")]
        x, y, w, h = [int(v) for v in g.clamp_roi((x, y, w, h), a.shape)] if w > 0 and h > 0 else (0, 0, a.shape[1], a.shape[0])
        bgr = as_bgr(a)[y:y + h, x:x + w]
        if bgr.shape[0] < 4 or bgr.shape[1] < 4:
            return err("the region is too small: choose a larger region")
        vec = embed(bgr, model)
        box = {"type": "rect", "box": [x, y, w, h], "color": (0, 255, 0)}
        if mode == "Register Image":
            name = str(t.get_param("category") or "").strip()
            if not name:
                return err("no category chosen: type the category name to register this picture under")
            problem = add(name, vec)
            if problem:
                return err(problem)
            problem = _save_file(t, gal)
            return err(problem) if problem else ok(f"registered under '{name}' ({len(gal['classes'][name])} now)", [box], Image=a, Class=name, Similarity=1.0, Top=[], Categories=counts())
    except dl.DLModelError as e:
        return err(f"{t.tool_name}: {e}")
    if not gal["classes"]:
        return err("no examples chosen: the gallery is empty, so register pictures first (Mode: Register Image or Register Folder), or choose a gallery file")
    if gal.get("dim") not in (None, len(vec)):
        return err("this picture is described differently from the gallery: use the same feature model the gallery was made with")
    sims: Dict[str, float] = {}
    for name, vs in gal["classes"].items():
        m = np.asarray(vs, np.float32)
        if m.ndim == 2 and m.shape[1] == len(vec) and len(m):
            sims[name] = float(np.max(m @ vec))
    if not sims:
        return err("the gallery does not fit this version: clear it and register again")
    top = sorted(sims.items(), key=lambda kv: -kv[1])
    kept = [{"class": c, "similarity": round(s, 4)} for c, s in top if s >= float(t.get_param("min_similarity"))][:int(t.get_param("top_k"))]
    if not kept:
        box["color"] = (0, 0, 255)
        return ng(f"nothing in the gallery is as similar as {float(t.get_param('min_similarity')):.2f} (closest: {top[0][0]} at {top[0][1]:.2f})", [box], Image=a, Class="", Similarity=top[0][1],
                  Top=[], Categories=counts())
    over = [box, {"type": "text", "text": f"{kept[0]['class']} {kept[0]['similarity']:.2f}", "pt": (x, max(12, y - 6)), "color": (0, 255, 0)}]
    return ok(f"{kept[0]['class']} ({kept[0]['similarity']:.2f}); " + ", ".join(f"{k['class']} {k['similarity']:.2f}" for k in kept[1:3]) if len(kept) > 1 else f"{kept[0]['class']} ({kept[0]['similarity']:.2f})",
              over, Image=a, Class=kept[0]["class"], Similarity=kept[0]["similarity"], Top=kept, Categories=counts())


@define("Classification Registration", CAT,
        "Finds which registered category a picture belongs to. Register example pictures under category names (whole pictures or a part of them, one "
        "at a time or a whole folder), then search: it returns the most similar categories and how similar. No training is needed - register more "
        "pictures to teach it more.",
        inputs=[img()], outputs=GALLERY_OUT, params=dict(GALLERY_PARAMS), schema=dict(GALLERY_SCHEMA))
def classification_registration(t, ctx):
    return _gallery_tool(t, ctx, None)


@define("DL Image Retrieval", CAT,
        "Searches a gallery of pictures for the categories most like a picture, using a deep-learning feature model (ONNX) to describe each picture. "
        "Register pictures into the gallery with the same model (one by one, or a whole folder), keep the gallery in a file, and search with the top-K "
        "and minimum similarity you want.",
        inputs=[img()], outputs=GALLERY_OUT,
        params={**GALLERY_PARAMS, "model_file": "", "backend": "Auto", "save_in_solution": False, "model_data": {}},
        schema={**GALLERY_SCHEMA, "model_file": {"kind": "path", "filters": "ONNX models (*.onnx);;All files (*)"}, "backend": enum("Auto", "ONNX Runtime", "OpenCV DNN"),
                "save_in_solution": {"kind": "bool"}})
def dl_image_retrieval(t, ctx):
    return _gallery_tool(t, ctx, "model_file")


# ---------------------------------------------------------------------------------------------------------------------------
# DL Instance Segment
# ---------------------------------------------------------------------------------------------------------------------------
def decode_instances(outputs, info: Dict[str, Any], conf: float, iou: float, max_det: int, mask_thr: float) -> List[Dict[str, Any]]:
    """Instances from a YOLO-seg style model: outputs[0] is (1, 4 + classes + n, N) (or transposed), outputs[1] the (1, n, mh, mw) prototypes."""
    if len(outputs) < 2:
        raise dl.DLModelError("this is not an instance segmentation model: it should give two outputs (detections and mask prototypes)")
    det = np.asarray(outputs[0], np.float32)
    proto = np.asarray(outputs[1], np.float32)
    det = det[0] if det.ndim == 3 else det
    if proto.ndim == 4:
        proto = proto[0]
    if det.ndim != 2 or proto.ndim != 3:
        raise dl.DLModelError("unexpected output shapes from the segmentation model")
    nm = proto.shape[0]
    if det.shape[0] < det.shape[1]:
        det = det.T                                                                    # (N, 4 + classes + nm)
    nc = det.shape[1] - 4 - nm
    if nc < 1:
        raise dl.DLModelError("the detections do not fit the mask prototypes (4 + classes + mask numbers)")
    scores_all = det[:, 4:4 + nc]
    cls = scores_all.argmax(axis=1)
    score = scores_all[np.arange(len(det)), cls]
    sel = np.nonzero(score >= conf)[0]
    if len(sel) == 0:
        return []
    sx, sy = info["scale"]
    px, py = info["pad"]
    w0, h0 = info["orig"]
    wi, hi = info["size"]
    cx, cy, bw, bh = det[sel, 0], det[sel, 1], det[sel, 2], det[sel, 3]
    x1, y1, x2, y2 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
    boxes_in = np.stack([x1, y1, x2, y2], axis=1)
    ox1, oy1 = np.clip((x1 - px) / sx, 0, w0 - 1), np.clip((y1 - py) / sy, 0, h0 - 1)
    ox2, oy2 = np.clip((x2 - px) / sx, 0, w0), np.clip((y2 - py) / sy, 0, h0)
    boxes = np.stack([ox1, oy1, np.maximum(ox2 - ox1, 1), np.maximum(oy2 - oy1, 1)], axis=1)
    keep = dl._nms(boxes, score[sel], cls[sel], iou, max_det)
    coef = det[sel][:, 4 + nc:]
    mh, mw = proto.shape[1:]
    flat = proto.reshape(nm, -1)
    out = []
    for i in keep:
        m = 1.0 / (1.0 + np.exp(-(coef[i] @ flat))).reshape(mh, mw)
        m = cv2.resize(m.astype(np.float32), (wi, hi), interpolation=cv2.INTER_LINEAR)
        clip = np.zeros_like(m)
        bx1, by1, bx2, by2 = [int(round(v)) for v in boxes_in[i]]
        clip[max(0, by1):max(0, by2), max(0, bx1):max(0, bx2)] = m[max(0, by1):max(0, by2), max(0, bx1):max(0, bx2)]
        full = dl.map_to_original(clip, info)
        out.append({"box": [float(v) for v in boxes[i]], "score": float(score[sel][i]), "class_id": int(cls[sel][i]), "mask": (full >= mask_thr)})
    return out


def _mask_overlap(a: np.ndarray, b: np.ndarray) -> float:
    inter = float(np.count_nonzero(a & b))
    small = float(min(np.count_nonzero(a), np.count_nonzero(b)))
    return inter / small if small > 0 else 0.0


@define("DL Instance Segment", CAT,
        "Finds each object in the picture and outlines it with its own mask, using an instance segmentation model (ONNX, YOLO-seg style). "
        "Gives every object's box, class, score and mask; masks that overlap too much are dropped (the weaker one), and the result can be drawn in colour.",
        inputs=[img()],
        outputs=[img("Image", "The picture, with the masks drawn when Render Mask Image is on"), val("Count"), port("Boxes", "any", "[[x, y, w, h], ...]"), port("Classes", "any"), port("Scores", "any"),
                 img("Mask_Image", "One grey level per object (1, 2, ...); 0 is the background"), port("Masks", "any", "One mask picture per object"), port("Detections", "any", "Detailed records")],
        params={"model_file": "", "backend": "Auto", "save_in_solution": False, "model_data": {}, "labels": "", "roi": [0, 0, 0, 0], "max_number": 20, "min_confidence": 0.3,
                "overlap_threshold": 0.5, "mask_threshold": 0.5, "max_mask_overlap": 0.8, "edge_filter_enable": False, "min_edge_score": 0.3, "render": True},
        schema={"model_file": {"kind": "path", "filters": "ONNX models (*.onnx);;All files (*)"}, "backend": enum("Auto", "ONNX Runtime", "OpenCV DNN"), "save_in_solution": {"kind": "bool"},
                "labels": {"kind": "text", "hint": "class names separated by commas, or a .txt file; blank = the model's own"}, "roi": {"kind": "rect"}, "max_number": num(1, 1000),
                "min_confidence": num(0, 1, 0.05, decimals=2), "overlap_threshold": num(0, 1, 0.05, decimals=2), "mask_threshold": num(0, 1, 0.05, decimals=2),
                "max_mask_overlap": num(0, 1, 0.05, decimals=2), "edge_filter_enable": {"kind": "bool"}, "min_edge_score": num(0, 1, 0.05, decimals=2), "render": {"kind": "bool"}})
def dl_instance_segment(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    raw = str(t.get_param("model_file") or "").strip()
    if not raw and not t.parameters.get("model_data"):
        return err("no model chosen: choose an instance segmentation model (.onnx)")
    try:
        model = dl.load_model(dl.effective_path(t, "model_file"), str(t.get_param("backend")), "cpu")
        x0, y0, rw, rh = [int(v) for v in t.get_param("roi")]
        x0, y0, rw, rh = [int(v) for v in g.clamp_roi((x0, y0, rw, rh), a.shape)] if rw > 0 and rh > 0 else (0, 0, a.shape[1], a.shape[0])
        crop = as_bgr(a)[y0:y0 + rh, x0:x0 + rw]
        norm, resize, rgb = dl.settings_from_meta(model, "Auto", "Auto" if model.meta.get("resize") else "Letterbox", True)
        blob, info = dl.prepare_input(crop, model, (0, 0), resize, norm, rgb)
        inst = decode_instances(model.run(blob), info, float(t.get_param("min_confidence")), float(t.get_param("overlap_threshold")), 500, float(t.get_param("mask_threshold")))
    except dl.DLModelError as e:
        return err(f"DL Instance Segment: {e}")
    labels = dl.parse_labels(t.get_param("labels"), model)
    kept: List[Dict[str, Any]] = []
    for d in sorted(inst, key=lambda d: -d["score"]):
        if not d["mask"].any():
            continue
        if bool(t.get_param("edge_filter_enable")):
            bx, by, bw, bh = d["box"]
            if float(np.count_nonzero(d["mask"])) / max(1.0, bw * bh) < float(t.get_param("min_edge_score")):
                continue
        if any(_mask_overlap(d["mask"], k["mask"]) > float(t.get_param("max_mask_overlap")) for k in kept):
            continue
        kept.append(d)
        if len(kept) >= int(t.get_param("max_number")):
            break
    full_h, full_w = a.shape[:2]
    labelled = np.zeros((full_h, full_w), np.uint8)
    masks, recs, over = [], [], []
    rendered = as_bgr(a).copy()
    palette = [(255, 120, 0), (0, 200, 0), (0, 0, 255), (0, 200, 255), (255, 0, 200), (200, 200, 0), (120, 0, 255), (0, 120, 255)]
    for i, d in enumerate(kept):
        m = np.zeros((full_h, full_w), np.uint8)
        m[y0:y0 + d["mask"].shape[0], x0:x0 + d["mask"].shape[1]] = d["mask"].astype(np.uint8)
        labelled[m > 0] = min(255, i + 1)
        masks.append(m * 255)
        name = labels[d["class_id"]] if d["class_id"] < len(labels) else f"class_{d['class_id']}"
        bx, by, bw, bh = d["box"]
        box = [int(bx) + x0, int(by) + y0, int(bw), int(bh)]
        recs.append({"Index": i, "Class": name, "Score": round(d["score"], 4), "Area": int(np.count_nonzero(m)), "Box": box})
        over.append({"type": "rect", "box": box, "color": palette[i % len(palette)], "label": f"{name} {d['score']:.2f}"})
        if bool(t.get_param("render")):
            layer = rendered.copy()
            layer[m > 0] = palette[i % len(palette)]
            rendered = cv2.addWeighted(layer, 0.45, rendered, 0.55, 0)
    if not recs:
        return ng("no object found: lower the minimum confidence, or check the model", Image=rendered if bool(t.get_param("render")) else a, Count=0, Boxes=[], Classes=[], Scores=[], Mask_Image=labelled,
                  Masks=[], Detections=[])
    return ok(f"{len(recs)} object(s): " + ", ".join(f"{r['Class']} {r['Score']:.2f}" for r in recs[:4]), over, Image=rendered if bool(t.get_param("render")) else a, Count=len(recs),
              Boxes=[r["Box"] for r in recs], Classes=[r["Class"] for r in recs], Scores=[r["Score"] for r in recs], Mask_Image=labelled, Masks=masks, Detections=recs)


# ---------------------------------------------------------------------------------------------------------------------------
# DL Image Defect Prediction
# ---------------------------------------------------------------------------------------------------------------------------
@define("DL Image Defect Prediction", CAT,
        "Predicts where the defects are on a picture from a model trained on normal pictures only (ONNX): the answer is a probability map - a grey "
        "picture where 0 means no defect and brighter means more likely a defect. Threshold it and use BLOB Analysis, or read the highest probability.",
        inputs=[img()],
        outputs=[img("Image", "The picture with the probability map tinted on it"), img("Probability_Map", "Grey picture: 0 = no defect, 255 = certain"), val("Max_Probability", "Highest probability, 0 to 1"),
                 val("Defect_Count"), port("Boxes", "any", "[[x, y, w, h], ...] of the regions over the threshold")],
        params={"model_file": "", "backend": "Auto", "save_in_solution": False, "model_data": {}, "roi": [0, 0, 0, 0], "output_type": "Probability map", "probability_threshold": 0.5,
                "smoothing": 1.0, "min_area": 20, "max_defects": 0},
        schema={"model_file": {"kind": "path", "filters": "ONNX models (*.onnx);;All files (*)"}, "backend": enum("Auto", "ONNX Runtime", "OpenCV DNN"), "save_in_solution": {"kind": "bool"},
                "roi": {"kind": "rect"}, "output_type": enum("Probability map", "Reconstruction (autoencoder)"), "probability_threshold": num(0, 1, 0.05, decimals=2),
                "smoothing": num(0, 20, 0.5, decimals=1), "min_area": num(1, 1_000_000, unit="px"), "max_defects": num(0, 10000)})
def dl_image_defect_prediction(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    raw = str(t.get_param("model_file") or "").strip()
    if not raw and not t.parameters.get("model_data"):
        return err("no model chosen: choose a defect prediction model (.onnx)")
    try:
        model = dl.load_model(dl.effective_path(t, "model_file"), str(t.get_param("backend")), "cpu")
        x0, y0, rw, rh = [int(v) for v in t.get_param("roi")]
        x0, y0, rw, rh = [int(v) for v in g.clamp_roi((x0, y0, rw, rh), a.shape)] if rw > 0 and rh > 0 else (0, 0, a.shape[1], a.shape[0])
        crop = as_bgr(a)[y0:y0 + rh, x0:x0 + rw]
        norm, resize, rgb = dl.settings_from_meta(model, "Auto", "Auto" if model.meta.get("resize") else "Stretch", True)
        blob, info = dl.prepare_input(crop, model, (0, 0), resize, norm, rgb)
        o = np.asarray(model.run(blob)[0], np.float32)
        if str(t.get_param("output_type")).startswith("Reconstruction"):
            if o.ndim == 3:
                o = o[None]
            if o.shape[1:] != blob.shape[1:]:
                raise dl.DLModelError(f"the model's output {tuple(o.shape)} does not match its input {tuple(blob.shape)}, so it is not an autoencoder")
            amap = np.abs(blob[0] - o[0]).mean(axis=0)
            scale = float(model.meta.get("threshold", 0.1)) * 2.0                     # the model's own threshold sits at a probability of 0.5
        else:
            while o.ndim > 2:
                o = o[0]
            amap = o
            scale = 1.0
        amap = dl.map_to_original(amap, info)
    except dl.DLModelError as e:
        return err(f"DL Image Defect Prediction: {e}")
    sm = float(t.get_param("smoothing"))
    if sm > 0:
        k = int(max(3, round(sm * 6)) | 1)
        amap = cv2.GaussianBlur(amap, (k, k), sm)
    prob = np.clip(amap / max(scale, 1e-6), 0.0, 1.0)
    full = np.zeros(a.shape[:2], np.float32)
    full[y0:y0 + prob.shape[0], x0:x0 + prob.shape[1]] = prob
    pmap = (full * 255).astype(np.uint8)
    mask = (full >= float(t.get_param("probability_threshold"))).astype(np.uint8)
    regions, _ = dl.regions_from_mask(mask, int(t.get_param("min_area")))
    boxes = [[int(v) for v in r["box"]] for r in regions]
    heat = cv2.applyColorMap(pmap, cv2.COLORMAP_JET)
    tinted = cv2.addWeighted(as_bgr(a), 0.6, heat, 0.4, 0)
    tinted[pmap == 0] = as_bgr(a)[pmap == 0]
    mx = float(full.max())
    limit = int(t.get_param("max_defects"))
    good = len(boxes) <= limit
    over = [{"type": "rect", "box": b, "color": (0, 0, 255), "label": "defect"} for b in boxes[:50]]
    return (ok if good else ng)(f"highest probability {mx:.2f}; {len(boxes)} region(s) over {float(t.get_param('probability_threshold')):.2f}", over, Image=tinted, Probability_Map=pmap,
                                Max_Probability=mx, Defect_Count=len(boxes), Boxes=boxes)
