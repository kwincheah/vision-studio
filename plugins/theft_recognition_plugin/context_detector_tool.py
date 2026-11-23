"""Shared ONNX Runtime context object (bags/baskets/phones/bottles) detector with strided cache."""
from __future__ import annotations

import ast
import copy
import importlib.util
import os
import sys
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus
from apex_vision.core.dl_engine import resolve_onnx_device
from apex_vision.sdk import ParamDef, ParamType, PluginToolBase


def _load_local(name: str):
    pkg = __package__ or ""
    full = f"{pkg}.{name}" if pkg else name
    if full in sys.modules:
        return sys.modules[full]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py")
    spec = importlib.util.spec_from_file_location(full, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(full, None)
        raise
    return mod


DynamicBatchBroker = _load_local("batch_broker").DynamicBatchBroker

_COCO_BAG_DEFAULTS: Dict[int, str] = {
    24: "backpack",
    26: "handbag",
    28: "suitcase",
    39: "bottle",
    67: "cell phone",
}

_SHARED_BAG_LOCK = threading.Lock()
_SHARED_BAG_SESSIONS: Dict[Tuple[str, float, str], "_OnnxBagSession"] = {}


def _resolve_model_path(model_path: str, default_name: str = "yolo11n.onnx") -> str:
    cleaned = (model_path or default_name).strip().strip('"').strip("'") or default_name
    if os.path.isabs(cleaned) or os.path.exists(cleaned):
        return cleaned
    env_models_dir = os.environ.get("APEX_MODELS_DIR", "").strip()
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    app_root = os.path.abspath(os.path.join(plugin_dir, "..", ".."))
    for base in (env_models_dir, plugin_dir, app_root, os.path.join(app_root, "models")):
        if not base:
            continue
        cand = os.path.join(base, cleaned)
        if os.path.exists(cand):
            return cand
    return cleaned


def _letterbox_image(bgr: np.ndarray, size: int = 640) -> Tuple[np.ndarray, float, float, float]:
    h, w = bgr.shape[:2]
    scale = min(size / float(max(1, w)), size / float(max(1, h)))
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    pad_w = (size - nw) / 2.0
    pad_h = (size - nh) / 2.0
    top, bottom = int(round(pad_h - 0.1)), int(round(pad_h + 0.1))
    left, right = int(round(pad_w - 0.1)), int(round(pad_w + 0.1))
    canvas = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
    if canvas.shape[0] != size or canvas.shape[1] != size:
        canvas = cv2.resize(canvas, (size, size), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    blob = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
    return blob[None, ...], scale, float(left), float(top)


def _normalize_predictions_2d(raw: np.ndarray) -> np.ndarray:
    arr = np.asarray(raw)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2:
        return np.zeros((0, 0), dtype=np.float32)
    if arr.shape[0] < arr.shape[1]:
        arr = arr.T
    return np.ascontiguousarray(arr, dtype=np.float32)


def _read_names_metadata(sess) -> Dict[int, str]:
    try:
        meta = sess.get_modelmeta().custom_metadata_map or {}
        if "names" in meta:
            parsed = ast.literal_eval(meta["names"])
            if isinstance(parsed, dict):
                return {int(k): str(v) for k, v in parsed.items()}
            if isinstance(parsed, (list, tuple)):
                return {i: str(v) for i, v in enumerate(parsed)}
    except Exception:
        pass
    return {}


class _OnnxBagSession:
    """Thread-safe shared ONNX Runtime detector for context vessels/items with dynamic micro-batching."""

    def __init__(self, model_path: str, providers: List[Any]):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        intra = int(os.environ.get("APEX_ORT_INTRA_THREADS", "0") or 0)
        inter = int(os.environ.get("APEX_ORT_INTER_THREADS", "0") or 0)
        if intra > 0:
            opts.intra_op_num_threads = intra
        if inter > 0:
            opts.inter_op_num_threads = inter

        self._lock = threading.Lock()
        self.session = ort.InferenceSession(model_path, sess_options=opts, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = 640
        in_shape = self.session.get_inputs()[0].shape
        try:
            if len(in_shape) == 4 and isinstance(in_shape[2], int) and in_shape[2] > 0:
                self.input_size = int(in_shape[2])
        except Exception:
            pass
        self.supports_dynamic_batch = bool(len(in_shape) == 4 and not (isinstance(in_shape[0], int) and in_shape[0] == 1))
        self.names = _read_names_metadata(self.session)
        max_b = max(1, int(os.environ.get("APEX_BATCH_MAX", "8") or 8))
        wait_ms = max(0.0, float(os.environ.get("APEX_BATCH_WAIT_MS", "6.0") or 6.0))
        self.broker = DynamicBatchBroker(
            self._run_raw,
            max_batch=max_b,
            max_wait_ms=wait_ms,
            supports_dynamic_batch=self.supports_dynamic_batch,
            name="apex-bag-batch",
        )

    def _run_raw(self, arr4: np.ndarray) -> np.ndarray:
        return self.session.run(None, {self.input_name: arr4})[0]

    def _preprocess_one(
        self,
        bgr: np.ndarray,
        crop_rect: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Tuple[np.ndarray, int, int, float, int, int, int, int]]:
        if bgr is None or bgr.size == 0:
            return None
        ox, oy = 0, 0
        work = bgr
        h_full, w_full = bgr.shape[:2]
        if crop_rect is not None:
            cx, cy, cw, ch = crop_rect
            ox = max(0, min(w_full - 1, cx))
            oy = max(0, min(h_full - 1, cy))
            work = bgr[oy:min(h_full, oy + ch), ox:min(w_full, ox + cw)]
            if work.size == 0:
                return None
        wh, ww = work.shape[:2]
        blob, scale, pad_x, pad_y = _letterbox_image(work, self.input_size)
        return blob, ww, wh, scale, pad_x, pad_y, ox, oy

    def _postprocess_one(
        self,
        raw: np.ndarray,
        meta: Tuple[np.ndarray, int, int, float, int, int, int, int],
        *,
        conf: float,
        iou: float,
        target_classes: Iterable[str],
    ) -> List[Dict[str, Any]]:
        _, ww, wh, scale, pad_x, pad_y, ox, oy = meta
        preds = _normalize_predictions_2d(raw)
        if preds.size == 0 or preds.shape[1] < 5:
            return []

        names = self.names or _COCO_BAG_DEFAULTS
        wanted = {c.strip().lower() for c in target_classes if c.strip()}
        wanted_ids = [cid for cid, cname in names.items() if cname.lower() in wanted] if wanted else list(names.keys())
        if not wanted_ids:
            wanted_ids = [cid for cid in _COCO_BAG_DEFAULTS if _COCO_BAG_DEFAULTS[cid] in wanted]

        cls_scores_all = preds[:, 4:]
        valid_ids = [cid for cid in wanted_ids if cid < cls_scores_all.shape[1]]
        if not valid_ids:
            return []

        sub_scores = cls_scores_all[:, valid_ids]
        best_rel = np.argmax(sub_scores, axis=1)
        best_score = sub_scores[np.arange(len(sub_scores)), best_rel]
        mask = best_score >= conf
        if not np.any(mask):
            return []

        filtered_boxes = preds[mask, :4]
        filtered_scores = best_score[mask]
        filtered_cids = np.asarray(valid_ids)[best_rel[mask]]

        boxes_nms: List[List[float]] = []
        boxes_full: List[List[int]] = []
        scores_list: List[float] = []
        cids_list: List[int] = []

        for (cx, cy, bw, bh), sc, cid in zip(filtered_boxes, filtered_scores, filtered_cids):
            x1 = max(0.0, min(float(ww - 1), (float(cx) - float(bw) * 0.5 - pad_x) / scale))
            y1 = max(0.0, min(float(wh - 1), (float(cy) - float(bh) * 0.5 - pad_y) / scale))
            x2 = max(x1 + 1.0, min(float(ww), (float(cx) + float(bw) * 0.5 - pad_x) / scale))
            y2 = max(y1 + 1.0, min(float(wh), (float(cy) + float(bh) * 0.5 - pad_y) / scale))
            rw, rh = x2 - x1, y2 - y1
            boxes_nms.append([x1, y1, rw, rh])
            boxes_full.append([int(round(x1)) + ox, int(round(y1)) + oy, max(1, int(round(rw))), max(1, int(round(rh)))])
            scores_list.append(float(sc))
            cids_list.append(int(cid))

        keep = cv2.dnn.NMSBoxes(boxes_nms, scores_list, float(conf), float(iou))
        indices = keep.flatten().tolist() if len(keep) > 0 else []

        detections: List[Dict[str, Any]] = []
        for out_idx, idx in enumerate(indices):
            cid = cids_list[idx]
            detections.append(
                {
                    "Index": out_idx,
                    "Class": names.get(cid, str(cid)),
                    "Class_Id": cid,
                    "Score": round(scores_list[idx], 4),
                    "Box": boxes_full[idx],
                }
            )
        return detections

    def infer(
        self,
        bgr: np.ndarray,
        *,
        conf: float,
        iou: float,
        target_classes: Iterable[str],
        crop_rect: Optional[Tuple[int, int, int, int]] = None,
        coalesce: bool = True,
    ) -> List[Dict[str, Any]]:
        meta = self._preprocess_one(bgr, crop_rect)
        if meta is None:
            return []
        raw = self.broker.submit(meta[0], coalesce=coalesce)
        return self._postprocess_one(raw, meta, conf=conf, iou=iou, target_classes=target_classes)

    def infer_batch(
        self,
        items: Iterable[Tuple[np.ndarray, Optional[Tuple[int, int, int, int]]]],
        *,
        conf: float,
        iou: float,
        target_classes: Iterable[str],
    ) -> List[List[Dict[str, Any]]]:
        item_list = list(items)
        results: List[List[Dict[str, Any]]] = [[] for _ in item_list]
        metas: List[Tuple[int, Any]] = []
        for idx, (bgr, crop_rect) in enumerate(item_list):
            meta = self._preprocess_one(bgr, crop_rect)
            if meta is not None:
                metas.append((idx, meta))
        if not metas:
            return results
        raw_outs = self.broker.infer_batch([m[0] for _, m in metas])
        for (orig_idx, meta), raw in zip(metas, raw_outs):
            results[orig_idx] = self._postprocess_one(raw, meta, conf=conf, iou=iou, target_classes=target_classes)
        return results


def get_bag_batch_metrics() -> Dict[str, Any]:
    with _SHARED_BAG_LOCK:
        sessions = list(_SHARED_BAG_SESSIONS.values())
    if not sessions:
        return {"sessions": 0, "total_requests": 0, "total_batches": 0, "max_batch_seen": 0, "avg_batch_size": 0.0}
    reqs = sum(int(s.broker.get_metrics()["total_requests"]) for s in sessions)
    bats = sum(int(s.broker.get_metrics()["total_batches"]) for s in sessions)
    mx = max(int(s.broker.get_metrics()["max_batch_seen"]) for s in sessions)
    return {
        "sessions": len(sessions),
        "supports_dynamic_batch": all(s.supports_dynamic_batch for s in sessions),
        "total_requests": reqs,
        "total_batches": bats,
        "max_batch_seen": mx,
        "avg_batch_size": round(float(reqs) / float(bats), 2) if bats > 0 else 0.0,
    }


def get_shared_onnx_bag_session(model_path: str, device: str) -> _OnnxBagSession:
    abs_path = os.path.abspath(model_path)
    use_trt = os.environ.get("APEX_TRT_ENABLE", "1") == "1"
    trt_cache = os.path.join(os.path.dirname(abs_path), "trt_cache")
    providers, using_gpu = resolve_onnx_device(device, use_tensorrt=use_trt, trt_cache_dir=trt_cache)
    prov_label = f"gpu:{device}:trt={use_trt}" if using_gpu else "cpu"
    mtime = os.path.getmtime(abs_path) if os.path.isfile(abs_path) else 0.0
    key = (abs_path, mtime, prov_label)
    max_b = max(1, int(os.environ.get("APEX_BATCH_MAX", "8") or 8))
    wait_ms = max(0.0, float(os.environ.get("APEX_BATCH_WAIT_MS", "6.0") or 6.0))
    with _SHARED_BAG_LOCK:
        sess = _SHARED_BAG_SESSIONS.get(key)
        if sess is None:
            if len(_SHARED_BAG_SESSIONS) > 8:
                _SHARED_BAG_SESSIONS.clear()
            sess = _OnnxBagSession(abs_path, providers)
            _SHARED_BAG_SESSIONS[key] = sess
        sess.broker.configure(max_batch=max_b, max_wait_ms=wait_ms)
        return sess


def _extract_roi(roi_val: Any, w_img: int, h_img: int) -> Optional[Tuple[int, int, int, int]]:
    if isinstance(roi_val, dict):
        roi_val = roi_val.get("rect") or roi_val.get("box")
    if not isinstance(roi_val, (list, tuple)) or len(roi_val) < 4:
        return None
    try:
        x, y, w, h = [int(round(float(v))) for v in roi_val[:4]]
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    x1 = max(0, min(w_img - 1, x))
    y1 = max(0, min(h_img - 1, y))
    rw = max(1, min(w_img - x1, w))
    rh = max(1, min(h_img - y1, h))
    return (x1, y1, rw, rh)


class ContextObjectDetectorTool(PluginToolBase):
    """Strided, shared-ONNX detector for bags, shopping baskets, carts, phones, and bottles."""

    plugin_id = "theft_recognition_plugin"
    category = "Theft Recognition"
    tool_name = "Context Object Detector"
    description = (
        "Detects retail context vessels/objects (backpack, handbag, shopping basket, cart, cell phone, bottle) "
        "using a shared ONNX Runtime session pool with person-gated strided caching."
    )

    param_definitions = {
        "model_path": ParamDef("model_path", ParamType.FILE_PATH, "yolo11n.onnx", "COCO ONNX object detection model"),
        "confidence": ParamDef("confidence", ParamType.FLOAT, 0.25, "Detection confidence threshold", 0.05, 0.95, 0.05),
        "iou": ParamDef("iou", ParamType.FLOAT, 0.45, "NMS IoU threshold", 0.05, 0.95, 0.05),
        "device": ParamDef("device", ParamType.ENUM, "auto", "Inference device", choices=["auto", "cpu", "cuda", "cuda:0"]),
        "infer_stride": ParamDef("infer_stride", ParamType.INT, 3, "Frame stride between bag inferences when idle/browsing", 1, 10, 1),
        "armed_stride": ParamDef("armed_stride", ParamType.INT, 2, "Tighter stride when a shopper track is armed", 1, 10, 1),
        "max_cache_age_sec": ParamDef("max_cache_age_sec", ParamType.FLOAT, 0.55, "Max cache age before forced refresh (sec)", 0.05, 5.0, 0.05),
        "skip_when_no_persons": ParamDef("skip_when_no_persons", ParamType.BOOLEAN, True, "Skip ONNX when Person_Count == 0"),
        "target_classes": ParamDef(
            "target_classes",
            ParamType.STRING,
            "backpack,handbag,suitcase,tote bag,shopping basket,shopping cart,cell phone,smartphone,bottle",
            "Comma-separated context class names",
        ),
    }

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input frame")
        self.inputs["ROI"] = ToolPort("ROI", DataType.REGION, "Optional search ROI [x, y, w, h]")
        self.inputs["Person_Count"] = ToolPort("Person_Count", DataType.VALUE, "Upstream detected person count")
        self.inputs["Timestamp"] = ToolPort("Timestamp", DataType.VALUE, "Frame timestamp in seconds")
        self.outputs["Detections"] = ToolPort("Detections", DataType.ANY, "Detected context objects")
        self.outputs["Count"] = ToolPort("Count", DataType.VALUE, "Context detection count")
        self.outputs["Cache_Hit"] = ToolPort("Cache_Hit", DataType.BOOLEAN, "True if strided cache was reused")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or SKIP")

    def _init_parameters(self):
        self.parameters = {k: copy.deepcopy(p.default_value) for k, p in self.param_definitions.items()}
        self._cache: Optional[Dict[str, Any]] = None

    def reset(self) -> None:
        self._cache = None

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=4, min_h=4)
        if img is None:
            return ToolExecutionResult(
                status=ToolStatus.NG,
                message="No valid input image for Context Object Detector",
                outputs={"Detections": [], "Count": 0, "Cache_Hit": False, "Status": "NG"},
            )

        gctx = context.get("global") or {}
        globals_dict = gctx.get("globals") or {}
        flow_name = str(gctx.get("flow_name") or "")
        preview_only = bool(globals_dict.get(f"__preview_only_{flow_name}", False))
        armed = bool(globals_dict.get(f"__armed_{flow_name}", False))

        skip_empty = bool(self.get_param("skip_when_no_persons", True))
        raw_pc = context.get("Person_Count")
        person_count = int(raw_pc) if raw_pc is not None else 1

        if preview_only or (skip_empty and person_count <= 0):
            self._cache = None
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message="Context detection skipped (preview or 0 persons)",
                outputs={"Detections": [], "Count": 0, "Cache_Hit": False, "Status": "SKIP"},
            )

        ts_raw = context.get("Timestamp")
        ts = float(ts_raw) if ts_raw is not None else time.monotonic()
        base_stride = max(1, int(self.as_float(self.get_param("infer_stride", 3), 3)))
        armed_stride = max(1, int(self.as_float(self.get_param("armed_stride", 2), 2)))
        eff_stride = min(armed_stride, base_stride) if armed else base_stride
        max_age = max(0.05, float(self.as_float(self.get_param("max_cache_age_sec", 0.55), 0.55)))

        run_infer = (
            self._cache is None
            or person_count != int(self._cache.get("person_count", -1))
            or (int(self._cache.get("skipped", 0)) + 1) >= eff_stride
            or (ts - float(self._cache.get("ts", 0.0))) >= max_age
            or ts < float(self._cache.get("ts", 0.0))
        )

        if not run_infer and self._cache is not None:
            self._cache["skipped"] = int(self._cache.get("skipped", 0)) + 1
            dets = list(self._cache.get("dets") or ())
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Context cache hit ({len(dets)} object(s))",
                outputs={"Detections": dets, "Count": len(dets), "Cache_Hit": True, "Status": "OK"},
            )

        if img.ndim == 2:
            bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        else:
            bgr = img

        h_img, w_img = bgr.shape[:2]
        roi = _extract_roi(context.get("ROI"), w_img, h_img)
        conf = float(self.as_float(self.get_param("confidence", 0.25), 0.25))
        iou = float(self.as_float(self.get_param("iou", 0.45), 0.45))
        raw_device = str(self.get_param("device", "auto"))
        classes_raw = str(self.get_param("target_classes", "") or "")
        target_classes = [c.strip() for c in classes_raw.split(",") if c.strip()]
        model_path = _resolve_model_path(str(self.get_param("model_path", "yolo11n.onnx")), "yolo11n.onnx")

        if not os.path.isfile(model_path):
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Context ONNX model not found: {model_path}",
                outputs={"Detections": [], "Count": 0, "Cache_Hit": False, "Status": "ERROR"},
            )

        coalesce = bool(globals_dict.get("__batch_coalesce__", False))
        try:
            sess = get_shared_onnx_bag_session(model_path, raw_device)
            try:
                dets = sess.infer(bgr, conf=conf, iou=iou, target_classes=target_classes, crop_rect=roi, coalesce=coalesce)
            except TypeError:
                dets = sess.infer(bgr, conf=conf, iou=iou, target_classes=target_classes, crop_rect=roi)
        except Exception as exc:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Context ONNX inference failed: {exc}",
                outputs={"Detections": [], "Count": 0, "Cache_Hit": False, "Status": "ERROR"},
            )

        self._cache = {
            "skipped": 0,
            "ts": float(ts),
            "person_count": person_count,
            "dets": list(dets),
        }
        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Context inferred ({len(dets)} object(s))",
            outputs={"Detections": dets, "Count": len(dets), "Cache_Hit": False, "Status": "OK"},
        )
