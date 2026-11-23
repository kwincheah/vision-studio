"""Standalone BoT-SORT / ByteTrack multi-object tracker plugin tool (tracker only)."""
from __future__ import annotations

from collections import deque
import copy
import os
from typing import Any, Deque, Dict, List, Tuple

import cv2
import numpy as np

from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus
from apex_vision.core.dl_engine import resolve_torch_device
from apex_vision.sdk import ParamDef, ParamType, PluginToolBase


class _AppearanceReIDEncoder:
    """Lightweight device-aware appearance descriptor for BOTSORT ReID matching.

    Avoids external classifier weight downloads and runs crop normalization / tensor
    pooling on the selected PyTorch device ('cuda:0', 'mps', or 'cpu' / NumPy).
    """

    def __init__(self, device: str = "cpu"):
        self.device = resolve_torch_device(device)
        try:
            import torch
            self._torch = torch if self.device != "cpu" else None
        except Exception:
            self._torch = None

    def __call__(self, img: np.ndarray, dets: np.ndarray) -> List[np.ndarray]:
        if dets is None or len(dets) == 0:
            return []
        if img is None or not isinstance(img, np.ndarray) or img.size == 0:
            return [np.ones((48,), dtype=np.float32) / np.sqrt(48.0) for _ in range(len(dets))]

        h_img, w_img = img.shape[:2]
        crops: List[np.ndarray] = []
        for det in dets:
            cx, cy, bw, bh = float(det[0]), float(det[1]), float(det[2]), float(det[3])
            x1 = max(0, min(w_img - 1, int(round(cx - bw * 0.5))))
            y1 = max(0, min(h_img - 1, int(round(cy - bh * 0.5))))
            x2 = max(x1 + 1, min(w_img, int(round(cx + bw * 0.5))))
            y2 = max(y1 + 1, min(h_img, int(round(cy + bh * 0.5))))
            crop = cv2.resize(img[y1:y2, x1:x2], (16, 24), interpolation=cv2.INTER_AREA)
            crops.append(crop)

        batch = np.asarray(crops, dtype=np.float32) / 255.0  # (N, 24, 16, 3)
        if self._torch is not None:
            t = self._torch.from_numpy(batch).to(self.device)
            zones = t.reshape(len(crops), 3, 8, 2, 8, 3)
            means = zones.mean(dim=(2, 4)).reshape(len(crops), -1)
            stds = zones.std(dim=(2, 4), unbiased=False).reshape(len(crops), -1)
            feats = self._torch.cat([means, stds], dim=1).detach().cpu().numpy().astype(np.float32)
        else:
            zones = batch.reshape(len(crops), 3, 8, 2, 8, 3)
            means = zones.mean(axis=(2, 4)).reshape(len(crops), -1)
            stds = zones.std(axis=(2, 4)).reshape(len(crops), -1)
            feats = np.concatenate([means, stds], axis=1).astype(np.float32)

        norms = np.linalg.norm(feats, axis=1, keepdims=True)
        zero_rows = norms[:, 0] < 1e-6
        if np.any(zero_rows):
            feats[zero_rows, 0] = 1.0
            norms = np.linalg.norm(feats, axis=1, keepdims=True)
        feats = (feats / np.maximum(norms, 1e-6)).astype(np.float32)
        return [feats[i] for i in range(len(feats))]


class _DetSlice:
    """Minimal Ultralytics-compatible detection container for BOTSORT/BYTETracker.update."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray, cls_ids: np.ndarray):
        self.xyxy = np.asarray(xyxy, dtype=np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, dtype=np.float32).reshape(-1)
        self.cls = np.asarray(cls_ids, dtype=np.float32).reshape(-1)
        if len(self.xyxy) > 0:
            x1, y1, x2, y2 = self.xyxy[:, 0], self.xyxy[:, 1], self.xyxy[:, 2], self.xyxy[:, 3]
            self.xywh = np.stack([(x1 + x2) * 0.5, (y1 + y2) * 0.5, x2 - x1, y2 - y1], axis=1)
        else:
            self.xywh = np.zeros((0, 4), dtype=np.float32)

    def __len__(self) -> int:
        return int(len(self.conf))

    def __getitem__(self, mask) -> "_DetSlice":
        return _DetSlice(self.xyxy[mask], self.conf[mask], self.cls[mask])


def _normalize_detections(raw_dets: Any, raw_kps: Any) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str], List[Any]]:
    if not isinstance(raw_dets, (list, tuple)) or len(raw_dets) == 0:
        return np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32), np.zeros((0,), dtype=np.float32), [], []

    boxes_xyxy: List[List[float]] = []
    confs: List[float] = []
    clss: List[float] = []
    labels: List[str] = []
    kps_list: List[Any] = []
    ext_kps = raw_kps if isinstance(raw_kps, (list, tuple)) else []

    for idx, item in enumerate(raw_dets):
        if not isinstance(item, dict):
            continue
        box = item.get("Box") or item.get("bbox")
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            continue
        try:
            x, y, w, h = [float(v) for v in box[:4]]
            score = float(item.get("Score", item.get("confidence", 0.5)))
            cls_id = float(item.get("Class_Id", 0))
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        boxes_xyxy.append([x, y, x + w, y + h])
        confs.append(score)
        clss.append(cls_id)
        labels.append(str(item.get("Class", item.get("label", "object"))))
        kp = item.get("Keypoints")
        if kp is None and idx < len(ext_kps):
            kp = ext_kps[idx]
        kps_list.append(kp if isinstance(kp, list) else [])

    if not boxes_xyxy:
        return np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32), np.zeros((0,), dtype=np.float32), [], []
    return (
        np.asarray(boxes_xyxy, dtype=np.float32),
        np.asarray(confs, dtype=np.float32),
        np.asarray(clss, dtype=np.float32),
        labels,
        kps_list,
    )


class BoTSORTTrackerTool(PluginToolBase):
    """Pure BoT-SORT / ByteTrack multi-object tracker operating on upstream Detections."""

    plugin_id = "theft_recognition_plugin"
    category = "Theft Recognition"
    tool_name = "BoT-SORT Tracker"
    description = (
        "Pure BoT-SORT (or ByteTrack) multi-object tracker. Takes Detections (+ optional Keypoints) "
        "from YOLO Pose or Object Detection and outputs persistent Track IDs and motion trails."
    )

    param_definitions = {
        "tracker_type": ParamDef("tracker_type", ParamType.ENUM, "botsort.yaml", "Tracker algorithm", choices=["botsort.yaml", "bytetrack.yaml"]),
        "frame_rate": ParamDef("frame_rate", ParamType.INT, 24, "Expected stream FPS for Kalman/buffer timing", 1, 120, 1),
        "device": ParamDef("device", ParamType.ENUM, "auto", "ReID feature / tracker device", choices=["auto", "cpu", "cuda", "cuda:0", "mps"]),
        "enable_reid": ParamDef("enable_reid", ParamType.BOOLEAN, True, "Enable ReID appearance embeddings to resist ID switches"),
        "gmc_method": ParamDef(
            "gmc_method",
            ParamType.ENUM,
            "none",
            "Global motion compensation (use 'none' for fixed CCTV)",
            choices=["none", "sparseOptFlow", "orb", "sift", "ecc"],
        ),
        "draw_trails": ParamDef("draw_trails", ParamType.BOOLEAN, True, "Draw Track ID boxes and motion trails on canvas"),
    }

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input frame (used by BoT-SORT GMC)")
        self.inputs["Detections"] = ToolPort("Detections", DataType.ANY, "Detections from YOLO Pose or Object Detection")
        self.inputs["Keypoints"] = ToolPort("Keypoints", DataType.ANY, "Optional keypoints aligned with Detections")
        self.inputs["Reset"] = ToolPort("Reset", DataType.BOOLEAN, "Clear all active tracks when True")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Frame with Track ID & trail overlays")
        self.outputs["Tracks"] = ToolPort("Tracks", DataType.ANY, "Tracked objects [{track_id, bbox, score, label, keypoints, trail}]")
        self.outputs["Tracked_Count"] = ToolPort("Tracked_Count", DataType.VALUE, "Active tracked object count")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG")

    def _init_parameters(self):
        self.parameters = {k: copy.deepcopy(p.default_value) for k, p in self.param_definitions.items()}
        self._tracker = None
        self._tracker_key: Tuple[str, int, str, bool, str] = ("", 0, "", True, "none")
        self._trails: Dict[int, Deque[Tuple[int, int]]] = {}

    def reset_tracker(self):
        self._tracker = None
        self._tracker_key = ("", 0, "", True, "none")
        self._trails.clear()

    def _ensure_tracker(self, tracker_type: str, fps: int, device: str, enable_reid: bool, gmc_method: str = "none"):
        gmc_norm = str(gmc_method or "none").strip() or "none"
        key = (tracker_type, fps, device, enable_reid, gmc_norm)
        if self._tracker is None or self._tracker_key != key:
            import pathlib
            import yaml
            import ultralytics
            from ultralytics.trackers.bot_sort import BOTSORT
            from ultralytics.trackers.byte_tracker import BYTETracker
            from ultralytics.utils import IterableSimpleNamespace

            cfg_name = "bytetrack.yaml" if "bytetrack" in tracker_type.lower() else "botsort.yaml"
            cfg_path = pathlib.Path(ultralytics.__file__).parent / "cfg" / "trackers" / cfg_name
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg_dict = yaml.safe_load(fh) or {}
            if cfg_name == "bytetrack.yaml":
                cfg_obj = IterableSimpleNamespace(**cfg_dict)
                self._tracker = BYTETracker(cfg_obj, frame_rate=fps)
            else:
                cfg_dict["with_reid"] = bool(enable_reid)
                cfg_dict["gmc_method"] = None if gmc_norm.lower() == "none" else gmc_norm
                cfg_obj = IterableSimpleNamespace(**cfg_dict)
                self._tracker = BOTSORT(cfg_obj, frame_rate=fps)
                self._tracker.encoder = _AppearanceReIDEncoder(device=device) if enable_reid else None
            self._tracker_key = key
        return self._tracker

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=4, min_h=4)
        if img is None:
            return ToolExecutionResult(
                status=ToolStatus.NG,
                message="No valid input image for BoT-SORT Tracker",
                outputs={"Tracks": [], "Tracked_Count": 0, "Status": "NG"},
            )

        if bool(context.get("Reset")):
            self.reset_tracker()

        if img.ndim == 2:
            bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        else:
            bgr = img

        tracker_type = str(self.get_param("tracker_type", "botsort.yaml"))
        fps = max(1, int(self.as_float(self.get_param("frame_rate", 24), 24)))
        device = resolve_torch_device(str(self.get_param("device", "auto")))
        enable_reid = bool(self.get_param("enable_reid", True)) and "bytetrack" not in tracker_type.lower()
        gmc_method = str(self.get_param("gmc_method", "none") or "none")
        draw_trails = bool(self.get_param("draw_trails", True))

        xyxy, conf, clss, labels, kps_list = _normalize_detections(context.get("Detections"), context.get("Keypoints"))
        det_slice = _DetSlice(xyxy, conf, clss)

        try:
            tracker = self._ensure_tracker(tracker_type, fps, device, enable_reid, gmc_method)
            tracked = tracker.update(det_slice, bgr)
        except Exception as exc:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"BoT-SORT update failed: {exc}",
                outputs={"Image": img, "Tracks": [], "Tracked_Count": 0, "Status": "ERROR"},
            )

        tracks_out: List[Dict[str, Any]] = []
        overlays: List[Dict[str, Any]] = []
        h_img, w_img = bgr.shape[:2]
        active_ids = set()

        if isinstance(tracked, np.ndarray) and tracked.ndim == 2 and len(tracked) > 0:
            for row in tracked:
                x1 = max(0, min(w_img - 1, int(round(float(row[0])))))
                y1 = max(0, min(h_img - 1, int(round(float(row[1])))))
                x2 = max(x1 + 1, min(w_img, int(round(float(row[2])))))
                y2 = max(y1 + 1, min(h_img, int(round(float(row[3])))))
                tid = int(row[4])
                score = round(float(row[5]), 4) if len(row) > 5 else 1.0
                det_idx = int(row[7]) if len(row) > 7 else -1

                bw, bh = x2 - x1, y2 - y1
                cx, cy = x1 + bw // 2, y1 + bh // 2
                trail = self._trails.setdefault(tid, deque(maxlen=32))
                trail.append((cx, cy))
                active_ids.add(tid)

                label = labels[det_idx] if 0 <= det_idx < len(labels) else "object"
                kp = kps_list[det_idx] if 0 <= det_idx < len(kps_list) else []

                tracks_out.append({
                    "track_id": tid,
                    "label": label,
                    "confidence": score,
                    "bbox": [x1, y1, bw, bh],
                    "center": [cx, cy],
                    "keypoints": kp,
                    "trail": list(trail),
                })

                if draw_trails:
                    overlays.append({"type": "rect", "rect": [x1, y1, bw, bh], "color": (0, 200, 255), "thickness": 2})
                    overlays.append({"type": "text", "text": f"ID:{tid} ({label})", "pt": (x1, max(16, y1 - 6)), "color": (0, 200, 255)})
                    if len(trail) >= 2:
                        pts = list(trail)
                        for j in range(1, len(pts)):
                            overlays.append({"type": "line", "p1": pts[j - 1], "p2": pts[j], "color": (0, 200, 255), "thickness": 2})

        # Prune trails for tracks no longer maintained by BoT-SORT buffer
        if len(self._trails) > 128:
            for stale_id in [k for k in self._trails if k not in active_ids]:
                self._trails.pop(stale_id, None)

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"{tracker_type} ({device}{', ReID' if enable_reid else ''}): {len(tracks_out)} tracked object(s)",
            outputs={
                "Image": img,
                "Tracks": tracks_out,
                "Tracked_Count": len(tracks_out),
                "Status": "OK",
            },
            overlays=overlays,
        )
