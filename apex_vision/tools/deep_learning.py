"""
Deep Learning modules: classify, segment and find anomalies with your own ONNX model.

    DL Classify   one label for the image (good / scratch / dent ...)         -> OK / NG by label and confidence
    DL Segment    which pixels are defective (a mask from a segmentation net) -> area, count, boxes
    DL Anomaly    how unlike a "good" part the image is (trained on good parts only) -> heat map, score, regions

Object Detection (boxes around defects or objects) also runs ONNX models; see object_detection.py. The "Defect Detection"
module can use these models too. All of them share ``apex_vision.core.dl_engine``. Train and export models with
``python main.py train`` (see docs/DEEP_LEARNING.md) or with any framework that can export ONNX.
"""
import cv2
import numpy as np
from typing import Any, Dict, List, Optional, Tuple

from apex_vision.core import dl_engine as dl
from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from apex_vision.core.registry import register_tool

CATEGORY = "Deep Learning"
OK_COLOUR, NG_COLOUR, INFO_COLOUR = (90, 200, 90), (60, 60, 235), (0, 220, 255)


# ---------------------------------------------------------------------------------------------------------------
# shared plumbing
# ---------------------------------------------------------------------------------------------------------------
def common_parameters() -> Dict[str, Any]:
    return {
        "model_path": "",             # an .onnx file; a bare name is looked up in ~/.apex_vision/models
        "backend": "Auto",            # Auto, ONNX Runtime, OpenCV DNN
        "device": "cpu",
        "labels": "",                 # 'good, scratch, dent' or a .txt file; blank = the model's own
        "input_width": 0,             # 0 = what the model says
        "input_height": 0,
        "resize": "Auto",             # Auto, Stretch, Letterbox
        "normalize": "Auto",          # Auto, 0 to 1, ImageNet (mean/std), -1 to 1, 0 to 255
        "rgb_input": True,
        "roi": [0, 0, 0, 0],          # x, y, w, h; all zero = the whole image
        "save_in_solution": False,    # keep a copy of the model inside the solution file, so it opens on another computer
        "model_data": {},             # (that copy; not shown for editing)
    }


def get_image(tool: VisionToolBase, context: Dict[str, Any]) -> Optional[np.ndarray]:
    img = tool.get_input_image(context, min_w=2, min_h=2)
    return None if img is None else dl._to_bgr(img)


def crop_roi(tool: VisionToolBase, img: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int]]:
    """The region to analyse and its offset. A region with no width or height means the whole picture."""
    raw = tool.get_param("roi", [0, 0, 0, 0])
    try:
        x, y, w, h = [int(v) for v in raw[:4]]
    except (TypeError, ValueError):
        return img, (0, 0)
    if w <= 0 or h <= 0:
        return img, (0, 0)
    x, y, w, h = tool.get_roi("roi", [0, 0, w, h], img_shape=img.shape)
    return img[y:y + h, x:x + w], (x, y)


def open_model(tool: VisionToolBase):
    return dl.load_model(dl.effective_path(tool, "model_path"), str(tool.get_param("backend", "Auto")), str(tool.get_param("device", "cpu")))


def prepare(tool: VisionToolBase, model: dl.DLModel, crop: np.ndarray):
    norm, resize, rgb = dl.settings_from_meta(model, str(tool.get_param("normalize", "Auto")), str(tool.get_param("resize", "Auto")),
                                              bool(tool.get_param("rgb_input", True)))
    size = (int(tool.as_float(tool.get_param("input_width", 0))), int(tool.as_float(tool.get_param("input_height", 0))))
    return dl.prepare_input(crop, model, size, resize, norm, rgb)


def _fail(message: str, img: Optional[np.ndarray], outputs: Optional[Dict[str, Any]] = None) -> ToolExecutionResult:
    out = {"Status": "NG"}
    if img is not None:
        out["Image"] = img
    out.update(outputs or {})
    return ToolExecutionResult(status=ToolStatus.ERROR, message=message, outputs=out)


def class_ids_from(text: Any, labels: List[str]) -> Optional[List[int]]:
    """'1, 2' or 'scratch, dent' -> class ids; blank -> None (every class except the background)."""
    s = str(text or "").strip()
    if not s or s.lower() in ("all", "*", "any"):
        return None
    ids = []
    low = [lab.lower() for lab in labels]
    for item in [p.strip() for p in s.split(",") if p.strip()]:
        if item.lstrip("-").isdigit():
            ids.append(int(item))
        elif item.lower() in low:
            ids.append(low.index(item.lower()))
    return ids or None


# ---------------------------------------------------------------------------------------------------------------
# analysis functions (also used by the Defect Detection module)
# ---------------------------------------------------------------------------------------------------------------
def analyse_segmentation(tool: VisionToolBase, model: dl.DLModel, img: np.ndarray, threshold: float, min_area: int,
                         defect_classes: Any = "", background: int = 0) -> Dict[str, Any]:
    crop, (ox, oy) = crop_roi(tool, img)
    blob, info = prepare(tool, model, crop)
    cls_map, prob = dl.decode_segmentation(model.run(blob), info, threshold, background)
    labels = dl.parse_labels(tool.get_param("labels", ""), model)
    wanted = class_ids_from(defect_classes, labels)
    mask = (np.isin(cls_map, wanted) if wanted else (cls_map != background)).astype(np.uint8)
    full = np.zeros(img.shape[:2], np.uint8)
    cls_full = np.zeros(img.shape[:2], np.uint8)
    prob_full = np.zeros(img.shape[:2], np.float32)
    sl = (slice(oy, oy + mask.shape[0]), slice(ox, ox + mask.shape[1]))
    full[sl], cls_full[sl], prob_full[sl] = mask, cls_map, prob
    regions, lab_img = dl.regions_from_mask(full, max(1, int(min_area)))
    kept = np.zeros_like(full)
    records = []
    for i, r in enumerate(regions):
        sel = lab_img == r["label_id"]
        kept[sel] = 1
        cid = int(np.bincount(cls_full[sel].ravel()).argmax())
        name = labels[cid] if cid < len(labels) else ("defect" if cid == 1 else f"class_{cid}")
        records.append({"Index": i, "Class": name, "Score": round(float(prob_full[sel].mean()), 4), "Area": r["area"],
                        "CentroidX": int(r["centroid"][0]), "CentroidY": int(r["centroid"][1]),
                        "Width": r["box"][2], "Height": r["box"][3], "Box": r["box"]})
    total = int(kept.sum())
    return {"mask": kept, "regions": records, "area": total, "ratio": 100.0 * total / max(1, kept.size), "roi": (ox, oy, crop.shape[1], crop.shape[0])}


def analyse_anomaly(tool: VisionToolBase, model: dl.DLModel, img: np.ndarray, threshold: float, min_area: int,
                    output_type: str = "Anomaly map", smooth: float = 2.0) -> Dict[str, Any]:
    crop, (ox, oy) = crop_roi(tool, img)
    blob, info = prepare(tool, model, crop)
    outs = model.run(blob)
    o = np.asarray(outs[0], np.float32)
    if output_type.startswith("Auto"):                                   # take it from the model's own .json
        output_type = str(model.meta.get("output_type", "Anomaly map"))
    if output_type.startswith("Reconstruction"):
        if o.ndim == 3:
            o = o[None]
        if o.shape[1:] != blob.shape[1:]:
            raise dl.DLModelError(f"The model's output {tuple(o.shape)} does not match its input {tuple(blob.shape)}, so it is not an "
                                  f"autoencoder. Set 'Output type' to 'Anomaly map' if it already produces a map.")
        amap = np.abs(blob[0] - o[0]).mean(axis=0)
    else:
        while o.ndim > 2:
            o = o[0]
        amap = o
    amap = dl.map_to_original(amap, info)
    if smooth > 0:
        k = int(max(3, round(smooth * 6)) | 1)
        amap = cv2.GaussianBlur(amap, (k, k), smooth)
    full_map = np.zeros(img.shape[:2], np.float32)
    full_map[oy:oy + amap.shape[0], ox:ox + amap.shape[1]] = amap
    if threshold <= 0:
        threshold = float(model.meta.get("threshold", 0.5))
    mask = (full_map >= threshold).astype(np.uint8)
    if (ox, oy) != (0, 0) or crop.shape[:2] != img.shape[:2]:
        roi_mask = np.zeros_like(mask)
        roi_mask[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = 1
        mask &= roi_mask
    regions, lab_img = dl.regions_from_mask(mask, max(1, int(min_area)))
    kept = np.zeros_like(mask)
    records = []
    for i, r in enumerate(regions):
        sel = lab_img == r["label_id"]
        kept[sel] = 1
        records.append({"Index": i, "Class": "anomaly", "Score": round(float(full_map[sel].max()), 4), "Area": r["area"],
                        "CentroidX": int(r["centroid"][0]), "CentroidY": int(r["centroid"][1]),
                        "Width": r["box"][2], "Height": r["box"][3], "Box": r["box"]})
    inside = full_map[oy:oy + crop.shape[0], ox:ox + crop.shape[1]]
    return {"map": full_map, "mask": kept, "regions": records, "score": float(inside.max()) if inside.size else 0.0,
            "threshold": threshold, "area": int(kept.sum())}


def detect_boxes(model: dl.DLModel, crop: np.ndarray, labels_text: Any, conf: float, iou: float, max_det: int = 100,
                 classes_param: Any = "") -> List[Tuple[int, int, int, int, float, str]]:
    """Run a YOLO-style .onnx model on ``crop``: [(x, y, w, h, score, class name), ...] in the crop's pixels."""
    labels = dl.parse_labels(labels_text, model)
    norm, resize, rgb = dl.settings_from_meta(model, "Auto", "Auto" if model.meta.get("resize") else "Letterbox", True)
    blob, info = dl.prepare_input(crop, model, (0, 0), resize, norm, rgb)
    dets = dl.decode_detections(model.run(blob), info, conf, iou, max_det, num_classes=len(labels) or None)
    wanted = None
    if isinstance(classes_param, str) and classes_param.strip().lower() not in ("", "all", "*", "any"):
        wanted, low = set(), [name.lower() for name in labels]
        for item in [c.strip() for c in classes_param.split(",") if c.strip()]:
            if item.isdigit():
                wanted.add(int(item))
            elif item.lower() in low:
                wanted.add(low.index(item.lower()))
    out = []
    for d in dets:
        if wanted is not None and d["class_id"] not in wanted:
            continue
        cid, (x, y, w, h) = d["class_id"], d["box"]
        out.append((int(x), int(y), int(w), int(h), float(d["score"]), labels[cid] if cid < len(labels) else f"class_{cid}"))
    return out


def analyse_detection(tool: VisionToolBase, model: dl.DLModel, img: np.ndarray, conf: float, iou: float = 0.45) -> Dict[str, Any]:
    crop, (ox, oy) = crop_roi(tool, img)
    raw = detect_boxes(model, crop, tool.get_param("labels", ""), conf, iou)
    records = [{"Index": i, "Class": name, "Score": round(score, 4), "Area": w * h, "CentroidX": x + ox + w // 2, "CentroidY": y + oy + h // 2,
                "Width": w, "Height": h, "Box": [x + ox, y + oy, w, h]} for i, (x, y, w, h, score, name) in enumerate(raw)]
    return {"regions": records, "area": int(sum(r["Area"] for r in records))}


def region_overlays(records: List[Dict[str, Any]], colour=NG_COLOUR) -> List[Dict[str, Any]]:
    out = []
    for r in records[:60]:
        out.append({"type": "rect", "box": r["Box"], "color": colour, "label": f"{r['Class']} {r['Score']:.2f}"})
    return out


def tint(img: np.ndarray, mask: np.ndarray, colour=NG_COLOUR, alpha: float = 0.45) -> np.ndarray:
    out = img.copy()
    if mask.any():
        layer = out.copy()
        layer[mask > 0] = colour
        out = cv2.addWeighted(layer, alpha, out, 1 - alpha, 0)
    return out


# ---------------------------------------------------------------------------------------------------------------
# DL Classify
# ---------------------------------------------------------------------------------------------------------------
@register_tool
class DLClassifyTool(VisionToolBase):
    category = CATEGORY
    tool_name = "DL Classify"
    description = ("Gives the image (or a region of it) one label with a deep-learning classification model (ONNX), for example "
                   "good / scratch / dent. Pass when the label is one of the 'OK labels' and the confidence is high enough.")

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image with the label written on it")
        self.outputs["Class"] = ToolPort("Class", DataType.STRING, "Predicted label")
        self.outputs["Class_Id"] = ToolPort("Class_Id", DataType.VALUE, "Predicted class number")
        self.outputs["Confidence"] = ToolPort("Confidence", DataType.VALUE, "Confidence of the predicted label (0-1)")
        self.outputs["Scores"] = ToolPort("Scores", DataType.ANY, "The best few labels with their scores")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG")

    def _init_parameters(self):
        self.parameters = {**common_parameters(), "top_k": 3, "ok_labels": "", "min_confidence": 0.5}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = get_image(self, context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided",
                                       outputs={"Class": "", "Class_Id": -1, "Confidence": 0.0, "Scores": [], "Status": "NG"})
        try:
            model = open_model(self)
            crop, (ox, oy) = crop_roi(self, img)
            blob, _ = prepare(self, model, crop)
            probs = dl.decode_classification(model.run(blob))
        except dl.DLModelError as exc:
            return _fail(f"DL Classify: {exc}", img, {"Class": "", "Class_Id": -1, "Confidence": 0.0, "Scores": []})
        labels = dl.parse_labels(self.get_param("labels", ""), model)
        name = lambda i: labels[i] if i < len(labels) else f"class_{i}"        # noqa: E731
        top = np.argsort(-probs)[:max(1, int(self.as_float(self.get_param("top_k", 3), 3)))]
        scores = [{"label": name(int(i)), "score": round(float(probs[i]), 4)} for i in top]
        best, conf = int(top[0]), float(probs[top[0]])
        ok_labels = {p.strip().lower() for p in str(self.get_param("ok_labels", "")).split(",") if p.strip()}
        min_conf = self.as_float(self.get_param("min_confidence", 0.5), 0.5)
        label_ok = not ok_labels or name(best).lower() in ok_labels
        passed = label_ok and conf >= min_conf
        reason = "" if passed else (f" (confidence {conf:.2f} is below {min_conf:g})" if label_ok else f" ('{name(best)}' is not an OK label)")
        colour = OK_COLOUR if passed else NG_COLOUR
        overlays = [{"type": "text", "text": f"{name(best)}  {conf:.0%}", "pt": (ox + 10, oy + 26), "color": colour}]
        if (ox, oy) != (0, 0) or crop.shape[:2] != img.shape[:2]:
            overlays.append({"type": "rect", "box": [ox, oy, crop.shape[1], crop.shape[0]], "color": colour})
        return ToolExecutionResult(
            status=ToolStatus.OK if passed else ToolStatus.NG,
            message=f"{name(best)} ({conf:.1%}){reason}  [{model.backend}]",
            outputs={"Image": img, "Class": name(best), "Class_Id": best, "Confidence": conf, "Scores": scores,
                     "Status": "OK" if passed else "NG"},
            overlays=overlays)


# ---------------------------------------------------------------------------------------------------------------
# DL Segment
# ---------------------------------------------------------------------------------------------------------------
@register_tool
class DLSegmentTool(VisionToolBase):
    category = CATEGORY
    tool_name = "DL Segment"
    description = ("Marks the defective pixels with a deep-learning segmentation model (ONNX, for example a U-Net). Reports the "
                   "defect area, how many separate defects there are, and a box for each. Fails when there are too many or too much.")

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image with the defects tinted")
        self.outputs["Mask"] = ToolPort("Mask", DataType.IMAGE, "Defect mask (white = defect)")
        self.outputs["Defect_Area"] = ToolPort("Defect_Area", DataType.VALUE, "Defect area in pixels")
        self.outputs["Defect_Ratio"] = ToolPort("Defect_Ratio", DataType.VALUE, "Defect area as a percentage of the image")
        self.outputs["Defect_Count"] = ToolPort("Defect_Count", DataType.VALUE, "Number of separate defects")
        self.outputs["Boxes"] = ToolPort("Boxes", DataType.ANY, "Boxes [[x, y, w, h], ...]")
        self.outputs["Classes"] = ToolPort("Classes", DataType.ANY, "Class name of each defect")
        self.outputs["Scores"] = ToolPort("Scores", DataType.ANY, "Average confidence of each defect")
        self.outputs["Detections"] = ToolPort("Detections", DataType.ANY, "Detailed records for the result table")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG")

    def _init_parameters(self):
        self.parameters = {**common_parameters(), "defect_classes": "", "background_class": 0, "threshold": 0.5,
                           "min_area": 20, "max_defect_count": 0, "max_defect_ratio": 100.0}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = get_image(self, context)
        empty = {"Defect_Area": 0, "Defect_Ratio": 0.0, "Defect_Count": 0, "Boxes": [], "Classes": [], "Scores": [], "Detections": []}
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided", outputs={**empty, "Status": "NG"})
        try:
            model = open_model(self)
            res = analyse_segmentation(self, model, img, self.as_float(self.get_param("threshold", 0.5), 0.5),
                                       int(self.as_float(self.get_param("min_area", 20), 20)), self.get_param("defect_classes", ""),
                                       int(self.as_float(self.get_param("background_class", 0))))
        except dl.DLModelError as exc:
            return _fail(f"DL Segment: {exc}", img, empty)
        n, ratio = len(res["regions"]), res["ratio"]
        max_n = int(self.as_float(self.get_param("max_defect_count", 0)))
        max_ratio = self.as_float(self.get_param("max_defect_ratio", 100.0), 100.0)
        passed = n <= max_n and ratio <= max_ratio
        why = "" if passed else (f"  (more than {max_n} allowed)" if n > max_n else f"  (over the {max_ratio:g}% limit)")
        shown = tint(img, res["mask"])
        mask_img = cv2.cvtColor(res["mask"] * 255, cv2.COLOR_GRAY2BGR)
        return ToolExecutionResult(
            status=ToolStatus.OK if passed else ToolStatus.NG,
            message=f"{n} defect(s), {res['area']} px ({ratio:.2f}% of the image){why}  [{model.backend}]",
            outputs={"Image": shown, "Mask": mask_img, "Defect_Area": res["area"], "Defect_Ratio": ratio, "Defect_Count": n,
                     "Boxes": [r["Box"] for r in res["regions"]], "Classes": [r["Class"] for r in res["regions"]],
                     "Scores": [r["Score"] for r in res["regions"]], "Detections": res["regions"], "Status": "OK" if passed else "NG"},
            overlays=region_overlays(res["regions"], NG_COLOUR if not passed else INFO_COLOUR))


# ---------------------------------------------------------------------------------------------------------------
# DL Anomaly
# ---------------------------------------------------------------------------------------------------------------
@register_tool
class DLAnomalyTool(VisionToolBase):
    category = CATEGORY
    tool_name = "DL Anomaly"
    description = ("Finds anything that does not look like a good part, using an anomaly model (ONNX) trained on good images only: "
                   "an autoencoder, or any model that outputs an anomaly map. Gives a heat map, a score, and a box around each anomaly.")

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image with the anomaly heat map on it")
        self.outputs["Heatmap"] = ToolPort("Heatmap", DataType.IMAGE, "The heat map alone")
        self.outputs["Mask"] = ToolPort("Mask", DataType.IMAGE, "Anomaly mask (white = anomalous)")
        self.outputs["Anomaly_Score"] = ToolPort("Anomaly_Score", DataType.VALUE, "Highest anomaly value in the image")
        self.outputs["Defect_Count"] = ToolPort("Defect_Count", DataType.VALUE, "Number of separate anomalies")
        self.outputs["Boxes"] = ToolPort("Boxes", DataType.ANY, "Boxes [[x, y, w, h], ...]")
        self.outputs["Detections"] = ToolPort("Detections", DataType.ANY, "Detailed records for the result table")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG")

    def _init_parameters(self):
        p = common_parameters()
        p.pop("labels")
        self.parameters = {**p, "output_type": "Auto (from the model)", "map_threshold": 0.0, "smoothing": 2.0, "min_area": 20,
                           "max_defect_count": 0}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = get_image(self, context)
        empty = {"Anomaly_Score": 0.0, "Defect_Count": 0, "Boxes": [], "Detections": []}
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided", outputs={**empty, "Status": "NG"})
        try:
            model = open_model(self)
            res = analyse_anomaly(self, model, img, self.as_float(self.get_param("map_threshold", 0.0)),
                                  int(self.as_float(self.get_param("min_area", 20), 20)), str(self.get_param("output_type", "Auto (from the model)")),
                                  self.as_float(self.get_param("smoothing", 2.0), 2.0))
        except dl.DLModelError as exc:
            return _fail(f"DL Anomaly: {exc}", img, empty)
        n = len(res["regions"])
        max_n = int(self.as_float(self.get_param("max_defect_count", 0)))
        passed = n <= max_n
        hi = max(res["threshold"] * 2.0, float(res["map"].max()), 1e-6)
        heat = dl.heatmap_overlay(np.zeros_like(img), res["map"], 0.0, hi, alpha=1.0)
        return ToolExecutionResult(
            status=ToolStatus.OK if passed else ToolStatus.NG,
            message=f"score {res['score']:.3f} (threshold {res['threshold']:.3f}): {n} anomalous region(s){'' if passed else f' (more than {max_n} allowed)'}  [{model.backend}]",
            outputs={"Image": dl.heatmap_overlay(img, res["map"], 0.0, hi), "Heatmap": heat,
                     "Mask": cv2.cvtColor(res["mask"] * 255, cv2.COLOR_GRAY2BGR), "Anomaly_Score": res["score"], "Defect_Count": n,
                     "Boxes": [r["Box"] for r in res["regions"]], "Detections": res["regions"], "Status": "OK" if passed else "NG"},
            overlays=region_overlays(res["regions"]) + [{"type": "text", "text": f"score {res['score']:.2f}", "pt": (10, 26),
                                                         "color": OK_COLOUR if passed else NG_COLOUR}])
