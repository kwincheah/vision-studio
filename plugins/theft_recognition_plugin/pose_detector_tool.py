"""Stateless YOLOv11-Pose estimator plugin tool with shared ONNX Runtime pool (decoupled from BoT-SORT tracking)."""
from __future__ import annotations

import copy
import importlib.util
import os
import sys
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus
from apex_vision.core.dl_engine import resolve_onnx_device, resolve_torch_device
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

_SKELETON_EDGES: Tuple[Tuple[int, int], ...] = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
)

_SHARED_POSE_LOCK = threading.Lock()
_SHARED_POSE_SESSIONS: Dict[Tuple[str, float, str], "_OnnxPoseSession"] = {}


def resolve_model_path(model_path: str, default_name: str = "yolo11n-pose.pt") -> str:
    """Resolve model file across absolute path, APEX_MODELS_DIR, CWD, plugin dir, and Apex Vision app root."""
    cleaned = (model_path or default_name).strip().strip('"').strip("'") or default_name
    if os.path.isabs(cleaned) or os.path.exists(cleaned):
        return cleaned
    env_models_dir = os.environ.get("APEX_MODELS_DIR", "").strip()
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    app_root = os.path.abspath(os.path.join(plugin_dir, "..", ".."))
    candidates = [
        d for d in (
            env_models_dir,
            plugin_dir,
            app_root,
            os.path.join(app_root, "models"),
        )
        if d
    ]
    for base in candidates:
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


def _normalize_predictions_2d(raw: np.ndarray, expected_cols: Optional[int] = None) -> np.ndarray:
    arr = np.asarray(raw)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2:
        return np.zeros((0, 0), dtype=np.float32)
    if expected_cols is not None:
        if arr.shape[0] == expected_cols and arr.shape[1] != expected_cols:
            arr = arr.T
    elif arr.shape[0] < arr.shape[1]:
        arr = arr.T
    return np.ascontiguousarray(arr, dtype=np.float32)


class _OnnxPoseSession:
    """Thread-safe shared ONNX Runtime YOLO11-Pose inference session with dynamic micro-batching."""

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
        max_b = max(1, int(os.environ.get("APEX_BATCH_MAX", "8") or 8))
        wait_ms = max(0.0, float(os.environ.get("APEX_BATCH_WAIT_MS", "6.0") or 6.0))
        self.broker = DynamicBatchBroker(
            self._run_raw,
            max_batch=max_b,
            max_wait_ms=wait_ms,
            supports_dynamic_batch=self.supports_dynamic_batch,
            name="apex-pose-batch",
        )

    def _run_raw(self, arr4: np.ndarray) -> np.ndarray:
        return self.session.run(None, {self.input_name: arr4})[0]

    def _preprocess_one(
        self,
        bgr: np.ndarray,
        crop_rect: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Tuple[np.ndarray, int, int, int, int, float, int, int, int, int]]:
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
        return blob, h_full, w_full, ww, wh, scale, pad_x, pad_y, ox, oy

    @staticmethod
    def _postprocess_one(
        raw: np.ndarray,
        meta: Tuple[np.ndarray, int, int, int, int, float, int, int, int, int],
        conf: float,
        iou: float,
    ) -> Tuple[List[Dict[str, Any]], List[List[List[float]]]]:
        _, h_full, w_full, ww, wh, scale, pad_x, pad_y, ox, oy = meta
        preds = _normalize_predictions_2d(raw, expected_cols=56)
        if preds.size == 0 or preds.shape[1] < 5:
            return [], []

        scores = preds[:, 4]
        mask = scores >= conf
        if not np.any(mask):
            return [], []

        filtered = preds[mask]
        boxes_xywh_nms: List[List[float]] = []
        boxes_xywh_full: List[List[int]] = []
        scores_list: List[float] = []
        kps_all: List[List[List[float]]] = []

        has_kps = filtered.shape[1] >= 56
        for row in filtered:
            cx, cy, bw, bh = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            x1 = max(0.0, min(float(ww - 1), (cx - bw * 0.5 - pad_x) / scale))
            y1 = max(0.0, min(float(wh - 1), (cy - bh * 0.5 - pad_y) / scale))
            x2 = max(x1 + 1.0, min(float(ww), (cx + bw * 0.5 - pad_x) / scale))
            y2 = max(y1 + 1.0, min(float(wh), (cy + bh * 0.5 - pad_y) / scale))
            rw, rh = x2 - x1, y2 - y1
            boxes_xywh_nms.append([x1, y1, rw, rh])
            boxes_xywh_full.append([int(round(x1)) + ox, int(round(y1)) + oy, max(1, int(round(rw))), max(1, int(round(rh)))])
            scores_list.append(float(row[4]))

            kp_list: List[List[float]] = []
            if has_kps:
                kp_vec = row[5:56].reshape(17, 3)
                for kx, ky, kc in kp_vec:
                    fx = max(0.0, min(float(w_full - 1), ((float(kx) - pad_x) / scale) + ox))
                    fy = max(0.0, min(float(h_full - 1), ((float(ky) - pad_y) / scale) + oy))
                    kp_list.append([round(fx, 1), round(fy, 1), round(float(kc), 3)])
            kps_all.append(kp_list)

        keep = cv2.dnn.NMSBoxes(boxes_xywh_nms, scores_list, float(conf), float(iou))
        indices = keep.flatten().tolist() if len(keep) > 0 else []

        detections: List[Dict[str, Any]] = []
        keypoints_out: List[List[List[float]]] = []
        for out_idx, idx in enumerate(indices):
            kp = kps_all[idx]
            keypoints_out.append(kp)
            detections.append(
                {
                    "Index": out_idx,
                    "Class": "person",
                    "Class_Id": 0,
                    "Score": round(scores_list[idx], 4),
                    "Box": boxes_xywh_full[idx],
                    "Keypoints": kp,
                }
            )
        return detections, keypoints_out

    def infer(
        self,
        bgr: np.ndarray,
        *,
        conf: float,
        iou: float,
        crop_rect: Optional[Tuple[int, int, int, int]] = None,
        coalesce: bool = True,
    ) -> Tuple[List[Dict[str, Any]], List[List[List[float]]]]:
        meta = self._preprocess_one(bgr, crop_rect)
        if meta is None:
            return [], []
        raw = self.broker.submit(meta[0], coalesce=coalesce)
        return self._postprocess_one(raw, meta, conf, iou)

    def infer_batch(
        self,
        items: Iterable[Tuple[np.ndarray, Optional[Tuple[int, int, int, int]]]],
        *,
        conf: float,
        iou: float,
    ) -> List[Tuple[List[Dict[str, Any]], List[List[List[float]]]]]:
        item_list = list(items)
        results: List[Tuple[List[Dict[str, Any]], List[List[List[float]]]]] = [([], []) for _ in item_list]
        metas: List[Tuple[int, Any]] = []
        for idx, (bgr, crop_rect) in enumerate(item_list):
            meta = self._preprocess_one(bgr, crop_rect)
            if meta is not None:
                metas.append((idx, meta))
        if not metas:
            return results
        raw_outs = self.broker.infer_batch([m[0] for _, m in metas])
        for (orig_idx, meta), raw in zip(metas, raw_outs):
            results[orig_idx] = self._postprocess_one(raw, meta, conf, iou)
        return results


def get_pose_batch_metrics() -> Dict[str, Any]:
    with _SHARED_POSE_LOCK:
        sessions = list(_SHARED_POSE_SESSIONS.values())
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


def get_shared_onnx_pose_session(model_path: str, device: str) -> _OnnxPoseSession:
    abs_path = os.path.abspath(model_path)
    use_trt = os.environ.get("APEX_TRT_ENABLE", "1") == "1"
    trt_cache = os.path.join(os.path.dirname(abs_path), "trt_cache")
    providers, using_gpu = resolve_onnx_device(device, use_tensorrt=use_trt, trt_cache_dir=trt_cache)
    prov_label = f"gpu:{device}:trt={use_trt}" if using_gpu else "cpu"
    mtime = os.path.getmtime(abs_path) if os.path.isfile(abs_path) else 0.0
    key = (abs_path, mtime, prov_label)
    max_b = max(1, int(os.environ.get("APEX_BATCH_MAX", "8") or 8))
    wait_ms = max(0.0, float(os.environ.get("APEX_BATCH_WAIT_MS", "6.0") or 6.0))
    with _SHARED_POSE_LOCK:
        sess = _SHARED_POSE_SESSIONS.get(key)
        if sess is None:
            if len(_SHARED_POSE_SESSIONS) > 8:
                _SHARED_POSE_SESSIONS.clear()
            sess = _OnnxPoseSession(abs_path, providers)
            _SHARED_POSE_SESSIONS[key] = sess
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


class YOLOPoseTool(PluginToolBase):
    """Per-frame YOLOv11-Pose detector outputting person boxes and 17 COCO keypoints."""

    plugin_id = "theft_recognition_plugin"
    category = "Theft Recognition"
    tool_name = "YOLO Pose"
    description = (
        "Stateless YOLOv11-Pose detector that outputs person bounding boxes and 17 COCO keypoints per frame. "
        "Supports shared ONNX Runtime sessions across camera flows and Ultralytics .pt weights."
    )

    param_definitions = {
        "model_path": ParamDef("model_path", ParamType.FILE_PATH, "yolo11n-pose.pt", "YOLOv11-Pose weights (.onnx or .pt)"),
        "confidence": ParamDef("confidence", ParamType.FLOAT, 0.35, "Detection confidence threshold", 0.05, 0.95, 0.05),
        "iou": ParamDef("iou", ParamType.FLOAT, 0.50, "NMS IoU threshold", 0.05, 0.95, 0.05),
        "device": ParamDef("device", ParamType.ENUM, "auto", "Inference device", choices=["auto", "cpu", "cuda", "cuda:0", "mps"]),
        "draw_skeleton": ParamDef("draw_skeleton", ParamType.BOOLEAN, True, "Draw pose boxes & keypoints on canvas"),
    }

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input frame")
        self.inputs["ROI"] = ToolPort("ROI", DataType.REGION, "Optional search ROI [x, y, w, h]")
        self.inputs["Fallback_ROI"] = ToolPort(
            "Fallback_ROI",
            DataType.REGION,
            "Optional motion zoom crop used when full-frame search finds 0 persons",
        )
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Frame with pose overlays")
        self.outputs["Detections"] = ToolPort("Detections", DataType.ANY, "Detected person boxes with keypoints")
        self.outputs["Keypoints"] = ToolPort("Keypoints", DataType.ANY, "List of 17 [x, y, conf] keypoints per person")
        self.outputs["Count"] = ToolPort("Count", DataType.VALUE, "Detected person count")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG")

    def _init_parameters(self):
        self.parameters = {k: copy.deepcopy(p.default_value) for k, p in self.param_definitions.items()}
        self._pose_model = None
        self._pose_path = ""

    def _ensure_model(self, model_path: str):
        resolved = resolve_model_path(model_path, "yolo11n-pose.pt")
        if self._pose_model is None or self._pose_path != resolved:
            from ultralytics import YOLO
            self._pose_model = YOLO(resolved)
            self._pose_path = resolved
        return self._pose_model

    @staticmethod
    def _build_overlays(detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        overlays: List[Dict[str, Any]] = []
        for det in detections:
            x1, y1, bw, bh = det["Box"]
            kp_list = det.get("Keypoints") or []
            overlays.append({"type": "rect", "rect": [x1, y1, bw, bh], "color": (80, 210, 255), "thickness": 2})
            if len(kp_list) >= 17:
                for a, b in _SKELETON_EDGES:
                    if kp_list[a][2] >= 0.3 and kp_list[b][2] >= 0.3 and kp_list[a][0] > 0 and kp_list[b][0] > 0:
                        overlays.append({
                            "type": "line",
                            "p1": (int(round(kp_list[a][0])), int(round(kp_list[a][1]))),
                            "p2": (int(round(kp_list[b][0])), int(round(kp_list[b][1]))),
                            "color": (120, 240, 180),
                            "thickness": 2,
                        })
        return overlays

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=4, min_h=4)
        if img is None:
            return ToolExecutionResult(
                status=ToolStatus.NG,
                message="No valid input image for YOLO Pose",
                outputs={"Detections": [], "Keypoints": [], "Count": 0, "Status": "NG"},
            )

        if img.ndim == 2:
            bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        else:
            bgr = img

        h_img, w_img = bgr.shape[:2]
        roi = _extract_roi(context.get("ROI"), w_img, h_img)
        fallback_roi = _extract_roi(context.get("Fallback_ROI"), w_img, h_img)

        conf = float(self.as_float(self.get_param("confidence", 0.35), 0.35))
        iou = float(self.as_float(self.get_param("iou", 0.50), 0.50))
        raw_device = str(self.get_param("device", "auto"))
        draw_skel = bool(self.get_param("draw_skeleton", True))
        model_path = str(self.get_param("model_path", "yolo11n-pose.pt"))
        resolved = resolve_model_path(model_path, "yolo11n-pose.pt")

        gctx = context.get("global") or {}
        globals_dict = gctx.get("globals") or {}
        coalesce = bool(globals_dict.get("__batch_coalesce__", False))

        if resolved.lower().endswith(".onnx") and os.path.isfile(resolved):
            try:
                sess = get_shared_onnx_pose_session(resolved, raw_device)
                detections, keypoints_out = sess.infer(bgr, conf=conf, iou=iou, crop_rect=roi, coalesce=coalesce)
                if not detections and roi is None and fallback_roi is not None:
                    detections, keypoints_out = sess.infer(bgr, conf=conf, iou=iou, crop_rect=fallback_roi, coalesce=coalesce)
            except Exception as exc:
                return ToolExecutionResult(
                    status=ToolStatus.ERROR,
                    message=f"YOLO Pose ONNX failed: {exc}",
                    outputs={"Image": img, "Detections": [], "Keypoints": [], "Count": 0, "Status": "ERROR"},
                )
        else:
            device = resolve_torch_device(raw_device)

            def _run_pt(crop_r: Optional[Tuple[int, int, int, int]]) -> Tuple[List[Dict[str, Any]], List[List[List[float]]]]:
                if crop_r is not None:
                    rx, ry, rw, rh = crop_r
                    infer_img = bgr[ry:ry + rh, rx:rx + rw]
                else:
                    rx, ry = 0, 0
                    infer_img = bgr
                model = self._ensure_model(model_path)
                results = model.predict(
                    infer_img,
                    conf=conf,
                    iou=iou,
                    classes=[0],
                    device=device,
                    verbose=False,
                )
                dets: List[Dict[str, Any]] = []
                kps_list: List[List[List[float]]] = []
                if results:
                    r0 = results[0]
                    boxes = getattr(r0, "boxes", None)
                    kps = getattr(r0, "keypoints", None)
                    kps_xy = kps.xy.cpu().numpy() if kps is not None and getattr(kps, "xy", None) is not None else None
                    kps_cf = kps.conf.cpu().numpy() if kps is not None and getattr(kps, "conf", None) is not None else None

                    if boxes is not None and len(boxes) > 0:
                        xyxy = boxes.xyxy.cpu().numpy()
                        confs = boxes.conf.cpu().numpy()
                        clss = boxes.cls.cpu().numpy() if getattr(boxes, "cls", None) is not None else np.zeros(len(xyxy))

                        for i in range(len(xyxy)):
                            x1 = max(0, int(round(float(xyxy[i][0]))) + rx)
                            y1 = max(0, int(round(float(xyxy[i][1]))) + ry)
                            x2 = min(w_img, int(round(float(xyxy[i][2]))) + rx)
                            y2 = min(h_img, int(round(float(xyxy[i][3]))) + ry)
                            bw, bh = max(1, x2 - x1), max(1, y2 - y1)
                            score = round(float(confs[i]), 4)

                            kp_list: List[List[float]] = []
                            if kps_xy is not None and i < len(kps_xy):
                                for k_idx in range(len(kps_xy[i])):
                                    kx = round(float(kps_xy[i][k_idx][0]) + rx, 1)
                                    ky = round(float(kps_xy[i][k_idx][1]) + ry, 1)
                                    kc = round(float(kps_cf[i][k_idx]), 3) if kps_cf is not None and i < len(kps_cf) else 0.9
                                    kp_list.append([kx, ky, kc])

                            kps_list.append(kp_list)
                            dets.append({
                                "Index": i,
                                "Class": "person",
                                "Class_Id": int(clss[i]),
                                "Score": score,
                                "Box": [x1, y1, bw, bh],
                                "Keypoints": kp_list,
                            })
                return dets, kps_list

            try:
                detections, keypoints_out = _run_pt(roi)
                if not detections and roi is None and fallback_roi is not None:
                    detections, keypoints_out = _run_pt(fallback_roi)
            except Exception as exc:
                return ToolExecutionResult(
                    status=ToolStatus.ERROR,
                    message=f"YOLO Pose failed: {exc}",
                    outputs={"Image": img, "Detections": [], "Keypoints": [], "Count": 0, "Status": "ERROR"},
                )

        overlays = self._build_overlays(detections) if (draw_skel and detections) else []
        count = len(detections)
        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"YOLO Pose: {count} person(s)",
            outputs={
                "Image": img,
                "Detections": detections,
                "Keypoints": keypoints_out,
                "Count": count,
                "Status": "OK" if count > 0 else "READY",
            },
            overlays=overlays,
        )
