"""Deep-learning inference for Apex Vision Studio: load an ONNX model, feed it an image, decode what comes out.

Why ONNX: it is the one format every training framework exports (PyTorch, Ultralytics YOLO, anomalib, TensorFlow, ...), and it
runs in the packaged application, which does not contain PyTorch. Two backends are supported and chosen automatically:

* **onnxruntime**  (preferred: fastest, supports nearly every operator, can use a GPU), and
* **OpenCV DNN**   (always present, so a model still runs when onnxruntime is missing).

A model can come with a small ``<model>.json`` next to it (written by ``python main.py train``) that holds its labels, input size
and normalisation, so a module needs no setup beyond the file path. Everything in the JSON can be overridden by module settings.
"""
import ast
import json
import os
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

BACKENDS = ["Auto", "ONNX Runtime", "OpenCV DNN"]
NORMALIZE_MODES = ["0 to 1", "ImageNet (mean/std)", "-1 to 1", "0 to 255"]
RESIZE_MODES = ["Stretch", "Letterbox"]
DEFAULT_SIZE = 224


class DLModelError(Exception):
    """Anything that stops a model from loading or running. The message is shown to the user as written."""


# ---------------------------------------------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------------------------------------------
_CACHE: Dict[Tuple, "DLModel"] = {}
_CACHE_LOCK = threading.Lock()


def available_backends() -> List[str]:
    out = []
    try:
        import onnxruntime  # noqa: F401
        out.append("ONNX Runtime")
    except Exception:                                   # noqa: BLE001
        pass
    if hasattr(cv2, "dnn") and hasattr(cv2.dnn, "readNetFromONNX"):
        out.append("OpenCV DNN")
    return out


def sidecar_path(model_path: str) -> str:
    return os.path.splitext(model_path)[0] + ".json"


def resolve_path(model_path: str) -> str:
    """A model file next to the application or in the user's models folder is found by name alone."""
    p = os.path.expandvars(os.path.expanduser(str(model_path or "").strip().strip('"')))
    if p and os.path.isfile(p):
        return os.path.abspath(p)
    for base in (os.path.join(os.path.expanduser("~"), ".apex_vision", "models"),
                 os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "samples", "models")),      # the demo models shipped with the app
                 os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "models"))):
        cand = os.path.join(base, p)
        if p and os.path.isfile(cand):
            return cand
    return p


def load_model(model_path: str, backend: str = "Auto", device: str = "cpu") -> "DLModel":
    """Load (and cache) a model. Raises DLModelError with a plain-language reason."""
    path = resolve_path(model_path)
    if not path:
        raise DLModelError("No model file chosen. Pick an .onnx file in the module settings.")
    if not os.path.isfile(path):
        raise DLModelError(f"Model file not found: {path}")
    if os.path.splitext(path)[1].lower() != ".onnx":
        raise DLModelError(f"'{os.path.basename(path)}' is not an .onnx file. Export your model to ONNX first "
                           f"(see docs/DEEP_LEARNING.md); PyTorch .pt files cannot run in the packaged app.")
    key = (path, os.path.getmtime(path), backend, device)
    with _CACHE_LOCK:
        model = _CACHE.get(key)
        if model is None:
            model = DLModel(path, backend, device)
            if len(_CACHE) > 8:
                _CACHE.clear()
            _CACHE[key] = model
    return model


MAX_EMBED_BYTES = 500 * 1024 * 1024        # the guide: a model larger than 500 MB cannot be saved into the solution


def embed_file(path: str) -> Optional[Dict[str, Any]]:
    """The model file (and its .json next to it) packed for saving inside a solution, or None when it cannot be."""
    import base64
    import hashlib
    import zlib
    p = resolve_path(path)
    if not p or not os.path.isfile(p) or os.path.getsize(p) > MAX_EMBED_BYTES:
        return None
    with open(p, "rb") as f:
        raw = f.read()
    meta = ""
    sc = sidecar_path(p)
    if os.path.isfile(sc):
        with open(sc, "r", encoding="utf-8") as f:
            meta = f.read()
    return {"name": os.path.basename(p), "sha1": hashlib.sha1(raw).hexdigest(), "onnx": base64.b64encode(zlib.compress(raw, 3)).decode("ascii"), "meta": meta}


def materialize(data: Dict[str, Any]) -> Optional[str]:
    """Write an embedded model back to a file in the cache folder (once) and return its path."""
    import base64
    import zlib
    try:
        raw = zlib.decompress(base64.b64decode(data["onnx"]))
        sha = str(data.get("sha1") or "model")[:16]
        folder = os.path.join(os.path.expanduser("~"), ".apex_vision", "embedded")
        os.makedirs(folder, exist_ok=True)
        stem = os.path.splitext(os.path.basename(str(data.get("name") or "model.onnx")))[0]
        path = os.path.join(folder, f"{stem}_{sha}.onnx")
        if not os.path.isfile(path) or os.path.getsize(path) != len(raw):
            with open(path, "wb") as f:
                f.write(raw)
        if data.get("meta"):
            with open(sidecar_path(path), "w", encoding="utf-8") as f:
                f.write(str(data["meta"]))
        return path
    except (KeyError, ValueError, OSError, zlib.error, TypeError):
        return None


def effective_path(tool, path_key: str = "model_path", flag_key: str = "save_in_solution") -> str:
    """The model path a module should load. With 'save model in solution' on, the file is packed into the module's settings when it is there
    (and re-packed if it changed); when the file is missing but a packed copy exists, that copy is unpacked and used."""
    path = str(tool.get_param(path_key, "") or "")
    data = tool.parameters.get("model_data")
    if bool(tool.get_param(flag_key, False)):
        real = resolve_path(path)
        if real and os.path.isfile(real):
            import hashlib
            with open(real, "rb") as f:
                sha = hashlib.sha1(f.read()).hexdigest()
            if not isinstance(data, dict) or data.get("sha1") != sha:
                packed = embed_file(real)
                if packed is None:
                    raise DLModelError("This model is larger than 500 MB, so it cannot be saved into the solution. Turn off 'Save model in solution'.")
                tool.parameters["model_data"] = packed
            return path
        if isinstance(data, dict) and data.get("onnx"):
            made = materialize(data)
            if made:
                return made
    elif isinstance(data, dict) and data.get("onnx") and not os.path.isfile(resolve_path(path)):
        made = materialize(data)
        if made:
            return made
    return path


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


class DLModel:
    def __init__(self, path: str, backend: str = "Auto", device: str = "cpu"):
        self.path = path
        self.meta: Dict[str, Any] = {}
        self._session = None
        self._net = None
        self.backend = ""
        self.input_name = "input"
        self.input_shape: List[Any] = []
        self.output_shapes: List[Any] = []
        self._load_sidecar()
        have = available_backends()
        order = {"ONNX Runtime": ["ONNX Runtime", "OpenCV DNN"], "OpenCV DNN": ["OpenCV DNN"]}.get(backend, ["ONNX Runtime", "OpenCV DNN"])
        errors = []
        for name in [b for b in order if b in have] or order:
            try:
                self._open(name, device)
                break
            except Exception as exc:                        # noqa: BLE001
                errors.append(f"{name}: {str(exc).strip().splitlines()[0][:160] if str(exc).strip() else exc.__class__.__name__}")
                self._session = self._net = None
        else:
            hint = "" if have else " Neither onnxruntime nor OpenCV DNN is available."
            raise DLModelError(f"Could not load '{os.path.basename(path)}'. " + " | ".join(errors) + hint)

    # -- metadata -----------------------------------------------------------------------------------------------
    def _load_sidecar(self) -> None:
        sc = sidecar_path(self.path)
        if os.path.isfile(sc):
            try:
                with open(sc, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    self.meta.update(data)
            except (OSError, ValueError):
                pass

    def _read_embedded_meta(self) -> None:
        """Ultralytics and some exporters store class names inside the model file."""
        try:
            custom = self._session.get_modelmeta().custom_metadata_map or {}
        except Exception:                                   # noqa: BLE001
            return
        if "names" in custom and "labels" not in self.meta:
            try:
                names = ast.literal_eval(custom["names"])
                if isinstance(names, dict):
                    self.meta["labels"] = [str(names[k]) for k in sorted(names, key=lambda x: int(x))]
                elif isinstance(names, (list, tuple)):
                    self.meta["labels"] = [str(n) for n in names]
            except (ValueError, SyntaxError):
                pass
        if "imgsz" in custom and "input_size" not in self.meta:
            try:
                h, w = ast.literal_eval(custom["imgsz"])[:2]
                self.meta["input_size"] = [int(w), int(h)]
            except (ValueError, SyntaxError, TypeError):
                pass
        if "task" in custom and "task" not in self.meta:
            self.meta["task"] = str(custom["task"])

    def _open(self, name: str, device: str) -> None:
        if name == "ONNX Runtime":
            import onnxruntime as ort
            providers = ["CPUExecutionProvider"]
            if device == "cuda" and "CUDAExecutionProvider" in ort.get_available_providers():
                providers.insert(0, "CUDAExecutionProvider")
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            self._session = ort.InferenceSession(self.path, sess_options=opts, providers=providers)
            inp = self._session.get_inputs()[0]
            self.input_name, self.input_shape = inp.name, list(inp.shape)
            self.output_shapes = [list(o.shape) for o in self._session.get_outputs()]
            self._read_embedded_meta()
            self.backend = "ONNX Runtime" + (" (GPU)" if providers[0].startswith("CUDA") else "")
        else:
            self._net = cv2.dnn.readNetFromONNX(self.path)
            self._out_names = list(self._net.getUnconnectedOutLayersNames())
            self.backend = "OpenCV DNN"

    # -- shape helpers --------------------------------------------------------------------------------------------
    @property
    def labels(self) -> List[str]:
        return [str(x) for x in self.meta.get("labels", [])]

    def fixed_input_size(self) -> Optional[Tuple[int, int]]:
        """(width, height) when the model has a fixed spatial input size, else None."""
        if len(self.input_shape) == 4 and all(isinstance(v, int) and v > 0 for v in self.input_shape[2:]):
            return int(self.input_shape[3]), int(self.input_shape[2])
        return None

    def input_channels(self) -> int:
        if len(self.input_shape) == 4 and isinstance(self.input_shape[1], int) and self.input_shape[1] in (1, 3):
            return int(self.input_shape[1])
        return int(self.meta.get("channels", 3))

    def run(self, blob: np.ndarray) -> List[np.ndarray]:
        blob = np.ascontiguousarray(blob, dtype=np.float32)
        try:
            if self._session is not None:
                return [np.asarray(o) for o in self._session.run(None, {self.input_name: blob})]
            self._net.setInput(blob)
            out = self._net.forward(self._out_names)
            return [np.asarray(o) for o in (out if isinstance(out, (list, tuple)) else [out])]
        except Exception as exc:                            # noqa: BLE001
            want = "x".join(str(d) if isinstance(d, int) and d > 0 else "N" for d in self.input_shape) if self.input_shape else "?"
            raise DLModelError(f"The model could not run on this image (it expects {want}, got "
                               f"{'x'.join(str(d) for d in blob.shape)}): {str(exc).strip().splitlines()[0][:200]}") from exc

    def describe(self) -> str:
        dims = lambda shape: "x".join(str(d) if isinstance(d, int) and d > 0 else "N" for d in shape)      # noqa: E731
        shape = dims(self.input_shape) if self.input_shape else "unknown"
        outs = ", ".join(dims(s) for s in self.output_shapes) or "unknown"
        return f"{os.path.basename(self.path)}  [{self.backend}]  input {shape}  output {outs}  labels {len(self.labels)}"


# ---------------------------------------------------------------------------------------------------------------
# pre-processing
# ---------------------------------------------------------------------------------------------------------------
def parse_labels(text: Any, model: Optional[DLModel] = None) -> List[str]:
    """Labels from a module setting ('good, scratch, dent' or a .txt file with one per line), else the model's own."""
    s = str(text or "").strip()
    if s:
        if os.path.isfile(s):
            with open(s, "r", encoding="utf-8") as fh:
                return [ln.strip() for ln in fh if ln.strip()]
        return [p.strip() for p in s.split(",") if p.strip()]
    return model.labels if model else []


def _to_bgr(img: np.ndarray) -> np.ndarray:
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    if img.shape[2] == 1:
        return cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 2:
        return cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
    if img.shape[2] > 3:                                  # any other channel count (multi-spectral, stacked maps): the first three
        return np.ascontiguousarray(img[:, :, :3])
    return img


def prepare_input(img: np.ndarray, model: DLModel, size: Tuple[int, int] = (0, 0), resize: str = "Stretch",
                  normalize: str = "0 to 1", rgb: bool = True) -> Tuple[np.ndarray, Dict[str, Any]]:
    """The image as an NCHW float blob, plus what is needed to map results back onto the original image."""
    bgr = _to_bgr(img)
    h0, w0 = bgr.shape[:2]
    fixed = model.fixed_input_size()
    w, h = (int(size[0]), int(size[1])) if size and size[0] > 0 and size[1] > 0 else (fixed or model.meta.get("input_size") or (DEFAULT_SIZE, DEFAULT_SIZE))
    w, h = int(w), int(h)
    if fixed and (w, h) != fixed:
        w, h = fixed                                       # a fixed-size model cannot take any other size
    info = {"orig": (w0, h0), "size": (w, h), "scale": (w / w0, h / h0), "pad": (0, 0)}
    if resize == "Letterbox":
        r = min(w / w0, h / h0)
        nw, nh = max(1, int(round(w0 * r))), max(1, int(round(h0 * r)))
        canvas = np.full((h, w, 3), 114, np.uint8)
        px, py = (w - nw) // 2, (h - nh) // 2
        canvas[py:py + nh, px:px + nw] = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        bgr = canvas
        info.update(scale=(r, r), pad=(px, py))
    else:
        bgr = cv2.resize(bgr, (w, h), interpolation=cv2.INTER_LINEAR if w * h >= w0 * h0 else cv2.INTER_AREA)
    chans = model.input_channels()
    if chans == 1:
        arr = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)[None, :, :]
    else:
        arr = (cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB) if rgb else bgr).astype(np.float32).transpose(2, 0, 1)
    if normalize == "0 to 255":
        pass
    elif normalize == "-1 to 1":
        arr = arr / 127.5 - 1.0
    elif normalize == "ImageNet (mean/std)":
        arr = arr / 255.0
        mean = np.array(model.meta.get("mean", [0.485, 0.456, 0.406]), np.float32)[: arr.shape[0], None, None]
        std = np.array(model.meta.get("std", [0.229, 0.224, 0.225]), np.float32)[: arr.shape[0], None, None]
        arr = (arr - mean) / std
    else:
        arr = arr / 255.0
    return arr[None, ...].astype(np.float32), info


def settings_from_meta(model: DLModel, normalize: str, resize: str, rgb: Optional[bool] = None) -> Tuple[str, str, bool]:
    """Module settings left on 'Auto' take what the model's .json says."""
    n = model.meta.get("normalize", "0 to 1") if normalize == "Auto" else normalize
    r = model.meta.get("resize", "Stretch") if resize == "Auto" else resize
    c = model.meta.get("rgb", True) if rgb is None else rgb
    return n if n in NORMALIZE_MODES else "0 to 1", r if r in RESIZE_MODES else "Stretch", bool(c)


# ---------------------------------------------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------------------------------------------
def softmax(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float64)
    e = np.exp(x - x.max())
    return (e / e.sum()).astype(np.float32)


def decode_classification(outputs: Sequence[np.ndarray]) -> np.ndarray:
    """Class probabilities from a (1, C) output that holds logits or probabilities."""
    v = np.asarray(outputs[0], np.float32).reshape(-1)
    if v.size == 0:
        raise DLModelError("The model returned no scores")
    if v.size == 1:                                         # a single sigmoid output: [P(class 1)]
        p = 1.0 / (1.0 + np.exp(-float(v[0]))) if not 0.0 <= v[0] <= 1.0 else float(v[0])
        return np.array([1.0 - p, p], np.float32)
    if (v >= 0).all() and abs(float(v.sum()) - 1.0) < 1e-3:
        return v
    return softmax(v)


def _nms(boxes_xywh: np.ndarray, scores: np.ndarray, classes: np.ndarray, iou: float, max_det: int) -> List[int]:
    if len(boxes_xywh) == 0:
        return []
    keep = cv2.dnn.NMSBoxesBatched([[float(a) for a in b] for b in boxes_xywh], [float(s) for s in scores],
                                   [int(c) for c in classes], 0.0, float(iou))
    keep = np.asarray(keep).reshape(-1).tolist()
    keep.sort(key=lambda i: -scores[i])
    return keep[:max_det]


def decode_detections(outputs: Sequence[np.ndarray], info: Dict[str, Any], conf: float, iou: float, max_det: int = 100,
                      num_classes: Optional[int] = None) -> List[Dict[str, Any]]:
    """Boxes from YOLO-style outputs: v8 / v11 / v12 ``(1, 4+C, N)``, v5 / v7 ``(1, N, 5+C)`` and end-to-end ``(1, N, 6)``
    (x1, y1, x2, y2, score, class; used by YOLOv10 and later). Returns ``{box: [x, y, w, h], score, class_id}`` in the
    original image's pixels."""
    out = np.asarray(outputs[0], np.float32)
    if out.ndim == 3:
        out = out[0]
    if out.ndim != 2:
        raise DLModelError(f"Unrecognised detection output shape {tuple(np.asarray(outputs[0]).shape)}")
    scale_x, scale_y = info["scale"]
    pad_x, pad_y = info["pad"]
    w0, h0 = info["orig"]

    def to_original(x1, y1, x2, y2):
        x1, x2 = (x1 - pad_x) / scale_x, (x2 - pad_x) / scale_x
        y1, y2 = (y1 - pad_y) / scale_y, (y2 - pad_y) / scale_y
        x1, y1 = np.clip(x1, 0, w0 - 1), np.clip(y1, 0, h0 - 1)
        x2, y2 = np.clip(x2, 0, w0), np.clip(y2, 0, h0)
        return x1, y1, np.maximum(x2 - x1, 1), np.maximum(y2 - y1, 1)

    rows, cols = out.shape
    if cols == 6 and rows <= 1000:                                                 # end-to-end: already one box per object
        sel = out[:, 4] >= conf
        d = out[sel]
        x, y, w, h = to_original(d[:, 0], d[:, 1], d[:, 2], d[:, 3])
        order = np.argsort(-d[:, 4])[:max_det]
        return [{"box": [float(x[i]), float(y[i]), float(w[i]), float(h[i])], "score": float(d[i, 4]), "class_id": int(d[i, 5])} for i in order]
    # decide the layout: the channel axis (4 + classes, or 5 + classes) is the short one
    if rows < cols:
        out = out.T                                                                # (N, 4+C)
    n, c = out.shape
    if num_classes is not None and c == 5 + num_classes:                           # v5 style: objectness then class scores
        obj, cls_scores = out[:, 4:5], out[:, 5:]
        scores_all = cls_scores * obj
    else:
        scores_all = out[:, 4:]
    cls_id = scores_all.argmax(axis=1)
    score = scores_all[np.arange(n), cls_id]
    sel = score >= conf
    if not sel.any():
        return []
    cx, cy, bw, bh = out[sel, 0], out[sel, 1], out[sel, 2], out[sel, 3]
    x, y, w, h = to_original(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
    boxes = np.stack([x, y, w, h], axis=1)
    keep = _nms(boxes, score[sel], cls_id[sel], iou, max_det)
    return [{"box": [float(v) for v in boxes[i]], "score": float(score[sel][i]), "class_id": int(cls_id[sel][i])} for i in keep]


def map_to_original(m: np.ndarray, info: Dict[str, Any], interp=cv2.INTER_LINEAR) -> np.ndarray:
    """A model-resolution map (H x W) resized back onto the original image, undoing any letterbox padding."""
    w0, h0 = info["orig"]
    px, py = info["pad"]
    if (px, py) != (0, 0):
        h, w = m.shape[:2]
        m = m[py:h - py if py else h, px:w - px if px else w]
    return cv2.resize(np.ascontiguousarray(m, dtype=np.float32), (w0, h0), interpolation=interp)


def decode_segmentation(outputs: Sequence[np.ndarray], info: Dict[str, Any], threshold: float = 0.5,
                        background: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """(class_map uint8 at the original size, probability_map float32 of the predicted class).

    Accepts ``(1, C, H, W)`` with C > 1 (softmax / logits: argmax), or ``(1, 1, H, W)`` / ``(1, H, W)`` (a sigmoid mask,
    thresholded; class 1 = defect)."""
    o = np.asarray(outputs[0], np.float32)
    while o.ndim > 3 and o.shape[0] == 1:
        o = o[0]
    back = lambda m: map_to_original(m, info)

    if o.ndim == 2:
        o = o[None]
    if o.ndim != 3:
        raise DLModelError(f"Unrecognised segmentation output shape {tuple(np.asarray(outputs[0]).shape)}")
    if o.shape[0] == 1:
        m = o[0]
        if m.min() < 0 or m.max() > 1:
            m = 1.0 / (1.0 + np.exp(-m))
        prob = back(m)
        cls = (prob >= threshold).astype(np.uint8)
        return cls, np.where(cls > 0, prob, 1.0 - prob).astype(np.float32)
    if (o.min() < 0 or o.max() > 1.0001) or abs(float(o.sum(axis=0).mean()) - 1.0) > 1e-2:
        e = np.exp(o - o.max(axis=0, keepdims=True))
        o = e / e.sum(axis=0, keepdims=True)
    full = np.stack([back(o[i]) for i in range(o.shape[0])])
    cls = full.argmax(axis=0).astype(np.uint8)
    prob = full.max(axis=0).astype(np.float32)
    if background != 0 and background < full.shape[0]:                              # keep 'class id 0 = background' downstream
        cls = np.where(cls == background, 0, np.where(cls == 0, background, cls)).astype(np.uint8)
    return cls, prob


def regions_from_mask(mask: np.ndarray, min_area: int = 1, max_regions: int = 200):
    """(regions, label_image): connected regions of a binary mask with their box, area and centre, largest first."""
    n, labels, stats, cent = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), connectivity=8)
    out = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        out.append({"label_id": i, "box": [int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3])],
                    "area": area, "centroid": [float(cent[i][0]), float(cent[i][1])]})
    out.sort(key=lambda r: -r["area"])
    return out[:max_regions], labels


def heatmap_overlay(img_bgr: np.ndarray, amap: np.ndarray, lo: float, hi: float, alpha: float = 0.45) -> np.ndarray:
    """The image with the anomaly map blended on top (blue = normal, red = anomalous)."""
    span = max(1e-9, hi - lo)
    norm = np.clip((amap - lo) / span, 0, 1)
    heat = cv2.applyColorMap((norm * 255).astype(np.uint8), cv2.COLORMAP_JET)
    return cv2.addWeighted(_to_bgr(img_bgr), 1 - alpha, heat, alpha, 0)


# ---------------------------------------------------------------- PyTorch (.pt) models
CONVERTER_EXE = "ApexModelConverter.exe"


def pytorch_available() -> bool:
    """Whether PyTorch and Ultralytics are installed here (the packaged application leaves them out to stay small)."""
    import importlib.util
    return importlib.util.find_spec("torch") is not None and importlib.util.find_spec("ultralytics") is not None


def find_converter() -> Optional[str]:
    """The optional ApexModelConverter program: named by APEX_MODEL_CONVERTER, next to the application, or in the user's data folder."""
    import sys
    env = os.environ.get("APEX_MODEL_CONVERTER", "")
    app_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    local = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Apex Industrial Vision Studio", "converter")
    for cand in (env, os.path.join(app_dir, "converter", CONVERTER_EXE), os.path.join(app_dir, CONVERTER_EXE),
                 os.path.join(local, CONVERTER_EXE), os.path.join(local, "ApexModelConverter", CONVERTER_EXE)):
        if cand and os.path.isfile(cand):
            return cand
    return None


def _onnx_target(pt_path: str) -> str:
    """Where the converted model goes: beside the .pt, or in the user's cache when that folder is read-only."""
    beside = os.path.splitext(pt_path)[0] + ".onnx"
    if os.access(os.path.dirname(pt_path) or ".", os.W_OK) or os.path.exists(beside):
        return beside
    import hashlib
    cache = os.path.join(os.path.expanduser("~"), ".apex_vision", "converted")
    os.makedirs(cache, exist_ok=True)
    return os.path.join(cache, hashlib.sha1(pt_path.encode("utf-8")).hexdigest()[:10] + "_" + os.path.basename(beside))


def convert_pt_to_onnx(pt_path: str, imgsz: int = 640) -> str:
    """The ONNX version of a PyTorch YOLO model, converting it the first time (and again when the .pt is newer).

    Runs in-process where PyTorch is installed, otherwise through the optional ApexModelConverter program.
    Raises DLModelError with what to do when neither is available."""
    import subprocess
    pt = resolve_path(pt_path)
    target = _onnx_target(pt) if os.path.isfile(pt) else os.path.splitext(pt)[0] + ".onnx"
    have = os.path.isfile(target)
    stale = have and os.path.isfile(pt) and os.path.getmtime(target) + 5 < os.path.getmtime(pt)
    if have and not stale:
        return target
    if not os.path.isfile(pt):
        if have:
            return target
        raise DLModelError(f"Model file not found: {pt_path}")
    converter = None if pytorch_available() else find_converter()
    if not pytorch_available() and converter is None:
        if have:
            return target                     # cannot refresh it, but a converted copy exists: better than none
        raise DLModelError(
            f"'{os.path.basename(pt)}' is a PyTorch model and this build has no PyTorch. Install the Apex Model Converter add-on "
            f"({CONVERTER_EXE}, next to the application) to run .pt models, or export the model to .onnx yourself.")
    try:
        if converter is None:
            from apex_vision.model_converter import convert
            convert(pt, target, imgsz)
        else:
            done = subprocess.run([converter, pt, target, str(int(imgsz))], capture_output=True, text=True, timeout=900,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if done.returncode != 0:
                raise RuntimeError((done.stderr or done.stdout or f"exit code {done.returncode}").strip().splitlines()[-1])
    except DLModelError:
        raise
    except Exception as exc:
        raise DLModelError(f"Could not convert '{os.path.basename(pt)}' to ONNX: {exc}") from exc
    os.utime(target, None)                    # stamp it now, so it counts as newer than the .pt it came from
    clear_cache()
    return target
