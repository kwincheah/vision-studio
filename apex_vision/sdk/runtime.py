"""Hikrobot VisionMaster-style Solution / Procedure SDK runtime for Apex Vision."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import copy
from datetime import datetime, timezone
import importlib.util
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from apex_vision.core.base_tool import ToolExecutionResult, ToolStatus
from apex_vision.core.dl_engine import get_onnx_execution_capabilities, resolve_onnx_device
from apex_vision.core.pipeline import FlowConnection, SolutionManager, VisionPipeline
from apex_vision.core.registry import create_tool_instance
from apex_vision.sdk.manager import PluginManager
from apex_vision.sdk.media import RetentionManager, VlmAuditLogger, save_grid_jpeg, write_ring_clip_mp4
from apex_vision.sdk.stream_worker import CameraStreamWorker

logger = logging.getLogger("apex_vision.sdk.runtime")

_DEFAULT_TARGET_CLASSES = (
    "backpack,handbag,suitcase,tote bag,shopping basket,shopping cart,cell phone,smartphone,bottle"
)

_NODE_LAYOUT: Dict[str, Tuple[float, float]] = {
    "node_source": (60.0, 140.0),
    "node_roi": (300.0, 140.0),
    "node_motion": (540.0, 140.0),
    "node_pose": (780.0, 140.0),
    "node_bags": (1020.0, 40.0),
    "node_tracker": (1020.0, 240.0),
    "node_behavior": (1280.0, 140.0),
    "node_vlm": (1540.0, 140.0),
}


def ensure_theft_plugin_loaded() -> Any:
    """Ensure built-in tools and `theft_recognition_plugin` are discovered and loaded."""
    import apex_vision.tools  # noqa: F401 - ensures core tools (Image Source) are registered

    pm = PluginManager.get_instance()
    rec = pm.get_plugin("theft_recognition_plugin")
    if rec is None or not getattr(rec, "tools", None):
        pm.discover_and_load_all()
        rec = pm.get_plugin("theft_recognition_plugin")
    if rec is None or not getattr(rec, "tools", None):
        err = getattr(rec, "error_message", "theft_recognition_plugin not found")
        raise RuntimeError(f"Failed to load theft_recognition_plugin: {err}")
    return rec


def get_theft_submodule(mod_suffix: str) -> Any:
    """Return a preloaded helper submodule (e.g. `vlm_core`, `behavior_core`) from `theft_recognition_plugin`."""
    ensure_theft_plugin_loaded()
    candidates = (
        f"apex_plugin_theft_recognition_plugin.{mod_suffix}",
        f"plugins.theft_recognition_plugin.{mod_suffix}",
        mod_suffix,
    )
    for name in candidates:
        mod = sys.modules.get(name)
        if mod is not None:
            return mod

    pm = PluginManager.get_instance()
    rec = pm.get_plugin("theft_recognition_plugin")
    plugin_dir = Path(rec.plugin_dir) if rec and getattr(rec, "plugin_dir", None) else (
        Path(__file__).resolve().parent.parent.parent / "plugins" / "theft_recognition_plugin"
    )
    target = plugin_dir / f"{mod_suffix}.py"
    full_name = f"apex_plugin_theft_recognition_plugin.{mod_suffix}"
    spec = importlib.util.spec_from_file_location(full_name, str(target))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load plugin helper module {target}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(full_name, None)
        raise
    return mod


def get_device_capabilities() -> Dict[str, Any]:
    """Probe ONNX Runtime CUDA provider and PyTorch CUDA hardware availability."""
    providers: List[str] = []
    onnx_cuda = False
    try:
        import onnxruntime as ort

        providers = list(ort.get_available_providers())
        onnx_cuda = "CUDAExecutionProvider" in providers
    except Exception:
        providers = []

    torch_cuda = False
    gpu_name = ""
    try:
        import torch

        torch_cuda = bool(torch.cuda.is_available())
        if torch_cuda:
            gpu_name = str(torch.cuda.get_device_name(0) or "")
    except Exception:
        torch_cuda = False

    _, onnx_gpu_active = resolve_onnx_device("auto")
    using_gpu = bool(onnx_gpu_active or onnx_cuda or torch_cuda)
    cuda_available = bool(onnx_cuda or torch_cuda)

    resolved = "cuda" if using_gpu else "cpu"
    fallback_note = ""
    if not cuda_available:
        fallback_note = "CUDA GPU not detected; running ONNX/BoT-SORT on CPUExecutionProvider."
    elif torch_cuda and not onnx_cuda:
        fallback_note = "PyTorch CUDA detected, but onnxruntime-gpu CUDAExecutionProvider is unavailable."

    return {
        "requested_device": "auto",
        "resolved_device": resolved,
        "using_gpu": using_gpu,
        "cuda_available": cuda_available,
        "onnx_cuda_available": onnx_cuda,
        "torch_cuda_available": torch_cuda,
        "gpu_name": gpu_name,
        "available_providers": providers,
        "fallback_note": fallback_note,
    }


def normalize_device_request(requested: str) -> str:
    """Normalize user/UI device string into canonical 'auto' or 'cpu' (or explicit 'cuda:N')."""
    raw = str(requested or "auto").strip().lower()
    if raw in ("", "auto", "gpu", "cuda", "onnx", "onnx-gpu"):
        return "auto"
    if raw == "cpu":
        return "cpu"
    if raw.startswith("cuda:"):
        return raw
    return "auto"


def _zone_to_dict(z: Any, idx: int = 0) -> Dict[str, Any]:
    if isinstance(z, dict):
        name = str(z.get("name") or f"zone_{idx + 1}")
        role = str(z.get("role") or ("aisle" if "aisle" in name.lower() else "shelf")).strip().lower()
        rn = z.get("rect_norm")
        if isinstance(rn, (list, tuple)) and len(rn) == 4:
            x, y, w, h = [round(float(v), 6) for v in rn]
            rect = [
                int(round(x * 1920)),
                int(round(y * 1080)),
                max(1, int(round(w * 1920))),
                max(1, int(round(h * 1080))),
            ]
            return {"name": name, "role": role, "rect": rect, "rect_norm": [x, y, w, h]}
        rect = list(z.get("rect") or [0, 0, 0, 0])[:4]
        while len(rect) < 4:
            rect.append(0)
        return {"name": name, "role": role, "rect": [int(v) for v in rect]}

    name = str(getattr(z, "name", f"zone_{idx + 1}") or f"zone_{idx + 1}")
    role = str(getattr(z, "role", "shelf") or "shelf").strip().lower()
    rn = getattr(z, "rect_norm", None)
    if isinstance(rn, (list, tuple)) and len(rn) == 4:
        x, y, w, h = [round(float(v), 6) for v in rn]
    else:
        x = round(float(getattr(z, "x_norm", 0.0) or 0.0), 6)
        y = round(float(getattr(z, "y_norm", 0.0) or 0.0), 6)
        w = round(float(getattr(z, "w_norm", 0.0) or 0.0), 6)
        h = round(float(getattr(z, "h_norm", 0.0) or 0.0), 6)
    rect = [
        int(round(x * 1920)),
        int(round(y * 1080)),
        max(1, int(round(w * 1920))),
        max(1, int(round(h * 1080))),
    ]
    return {"name": name, "role": role, "rect": rect, "rect_norm": [x, y, w, h]}


def _zones_equal(a: Sequence[Any], b: Sequence[Any]) -> bool:
    da = [_zone_to_dict(z, i) for i, z in enumerate(a or ())]
    db = [_zone_to_dict(z, i) for i, z in enumerate(b or ())]
    return da == db


def _clean_media_path(url: str) -> str:
    clean = str(url or "").strip().strip('"').strip("'")
    if clean.lower().startswith("file:///"):
        from urllib.parse import unquote

        clean = unquote(clean[8:])
    return clean


def _set_node_params(node: Any, params: Dict[str, Any]) -> None:
    if hasattr(node, "load_dict"):
        node.load_dict({"parameters": params})
    else:
        for k, v in params.items():
            node.set_param(k, v)


def _wire_connection(pipe: VisionPipeline, fn: str, fp: str, tn: str, tp: str) -> None:
    if not pipe.connect(fn, fp, tn, tp, force=True):
        raise RuntimeError(f"Failed to connect {fn}.{fp} -> {tn}.{tp}")


class ApexProcedure:
    """Hikrobot VmProcedure equivalent wrapping one camera's `VisionPipeline`."""

    def __init__(
        self,
        name: str,
        pipeline: VisionPipeline,
        manager: Optional[SolutionManager] = None,
    ):
        self.name = str(name)
        self.pipeline = pipeline
        self.manager = manager
        self._exec_lock = threading.RLock()

    def node(self, node_id: str) -> Any:
        return self.pipeline.nodes.get(node_id)

    def get_param(self, node_id: str, param_name: str, default: Any = None) -> Any:
        nd = self.pipeline.nodes.get(node_id)
        if nd is None:
            raise KeyError(f"Unknown node '{node_id}' in procedure '{self.name}'")
        return nd.get_param(param_name, default)

    def set_param(self, node_id: str, param_name: str, value: Any) -> bool:
        nd = self.pipeline.nodes.get(node_id)
        if nd is None:
            return False
        with self._exec_lock:
            _set_node_params(nd, {param_name: value})
        return True

    def reset(self) -> None:
        with self._exec_lock:
            for nd in self.pipeline.nodes.values():
                for fn_name in ("reset_all", "reset", "on_video_loop_restart"):
                    fn = getattr(nd, fn_name, None)
                    if callable(fn):
                        try:
                            fn()
                            break
                        except Exception:
                            pass

    def run_once(
        self,
        frame_bgr: Optional[np.ndarray] = None,
        timestamp: Optional[float] = None,
        global_vars: Optional[Dict[str, Any]] = None,
        global_lock: Optional[threading.RLock] = None,
        *,
        force: bool = True,
    ) -> Dict[str, ToolExecutionResult]:
        """Execute one full DAG pass via `VisionPipeline.execute_flow()`."""
        with self._exec_lock:
            src_node = self.pipeline.nodes.get("node_source")
            if frame_bgr is not None and src_node is not None:
                setattr(src_node, "_override_image", frame_bgr)
                setattr(src_node, "_override_nocopy", True)
                if timestamp is not None:
                    setattr(src_node, "_override_timestamp", float(timestamp))

            gv = global_vars if global_vars is not None else (
                self.manager.global_variables if self.manager is not None else {}
            )
            lock = global_lock if global_lock is not None else (
                self.manager._globals_lock if self.manager is not None else None
            )
            prev_enabled = self.pipeline.enabled
            if force and not prev_enabled:
                self.pipeline.enabled = True
            try:
                return self.pipeline.execute_flow(global_vars=gv, global_lock=lock)
            finally:
                if force and not prev_enabled:
                    self.pipeline.enabled = prev_enabled
                if frame_bgr is not None and src_node is not None:
                    setattr(src_node, "_override_image", None)
                    setattr(src_node, "_override_nocopy", False)
                    setattr(src_node, "_override_timestamp", None)

    def to_summary(self) -> Dict[str, Any]:
        order = self.pipeline.execution_order or list(self.pipeline.nodes.keys())
        nodes_out: List[Dict[str, Any]] = []
        for nid in order:
            nd = self.pipeline.nodes.get(nid)
            if nd is None:
                continue
            params_safe: Dict[str, Any] = {}
            for pk, pv in (nd.parameters or {}).items():
                if str(pk) == "api_key" or str(pk).startswith("__"):
                    params_safe[pk] = ""
                else:
                    params_safe[pk] = pv
            nodes_out.append({
                "instance_id": nd.instance_id,
                "name": nd.name,
                "tool_name": nd.tool_name,
                "enabled": bool(nd.enabled),
                "parameters": params_safe,
            })

        return {
            "name": self.name,
            "enabled": bool(self.pipeline.enabled),
            "execution_count": int(self.pipeline.execution_count),
            "avg_time_ms": round(float(getattr(self.pipeline, "last_flow_time_ms", 0.0) or 0.0), 2),
            "nodes": nodes_out,
            "connections_count": len(self.pipeline.connections),
        }


class ApexSolution:
    """Hikrobot VmSolution equivalent managing multi-camera `<ApexFlow>` procedures."""

    REQUIRED_NODE_IDS = (
        "node_source",
        "node_roi",
        "node_motion",
        "node_pose",
        "node_bags",
        "node_tracker",
        "node_behavior",
        "node_vlm",
    )

    def __init__(
        self,
        manager: Optional[SolutionManager] = None,
        solution_path: Optional[str | Path] = None,
    ):
        ensure_theft_plugin_loaded()
        self.manager = manager or SolutionManager(name="StoreGuard")
        self.solution_path: Optional[Path] = Path(solution_path) if solution_path else None
        self._procedures: Dict[str, ApexProcedure] = {}
        self._rebuild_procedure_index()

    def _rebuild_procedure_index(self) -> None:
        existing = self._procedures
        rebuilt: Dict[str, ApexProcedure] = {}
        for fname, pipe in self.manager.flows.items():
            prev = existing.get(fname)
            if prev is not None and prev.pipeline is pipe:
                rebuilt[fname] = prev
            else:
                rebuilt[fname] = ApexProcedure(fname, pipe, self.manager)
        self._procedures = rebuilt

    def __getitem__(self, procedure_name: str) -> ApexProcedure:
        if procedure_name not in self._procedures:
            if procedure_name in self.manager.flows:
                self._rebuild_procedure_index()
            else:
                raise KeyError(f"Procedure '{procedure_name}' not found in solution")
        return self._procedures[procedure_name]

    def __contains__(self, procedure_name: str) -> bool:
        return procedure_name in self.manager.flows

    def list_procedures(self) -> List[str]:
        return list(self.manager.flows.keys())

    @staticmethod
    def build_camera_pipeline(
        cam: Any,
        *,
        pose_model: str = "yolo11n-pose.onnx",
        bag_model: str = "yolo11n.onnx",
        device: str = "auto",
        vlm_cfg: Any = None,
        pose_conf: float = 0.25,
        pose_iou: float = 0.50,
    ) -> VisionPipeline:
        """Build one standardized 8-node wired `<ApexFlow>` matching StoreGuard detection."""
        ensure_theft_plugin_loaded()
        cam_id = str(getattr(cam, "camera_id", None) or getattr(cam, "id", "cam_01"))
        cam_name = str(getattr(cam, "name", cam_id) or cam_id)
        raw_url = str(getattr(cam, "rtsp_url", "") or "")
        clean_url = _clean_media_path(raw_url)
        is_file = bool(clean_url and os.path.isfile(clean_url))

        pipe = VisionPipeline(name=cam_id)
        pipe.enabled = bool(getattr(cam, "enabled", True))

        n_src = create_tool_instance("Image Source", "node_source", "01_Camera_Source")
        _set_node_params(
            n_src,
            {
                "source_type": "File" if is_file else "IP Stream",
                "file_path": clean_url if is_file else "",
                "stream_url": "" if is_file else raw_url,
            },
        )

        zones_list = [_zone_to_dict(z, i) for i, z in enumerate(getattr(cam, "zones", ()) or ())]
        n_roi = create_tool_instance("ROI Zone Manager", "node_roi", "02_ROI_Zones")
        _set_node_params(n_roi, {"zones": zones_list, "draw_overlays": False})

        n_motion = create_tool_instance("Motion Gate", "node_motion", "03_Motion_Gate")
        _set_node_params(
            n_motion,
            {
                "diff_thresh": 16,
                "ratio_thresh": 0.005,
                "tail_sec": 3.0,
                "ref_interval_sec": 0.35,
                "min_zoom_side": 300,
                "bypass_nodes": "node_pose,node_bags,node_tracker,node_behavior,node_vlm",
            },
        )

        norm_dev = normalize_device_request(device)
        n_pose = create_tool_instance("YOLO Pose", "node_pose", "04_YOLO_Pose")
        _set_node_params(
            n_pose,
            {
                "model_path": pose_model,
                "confidence": float(pose_conf),
                "iou": float(pose_iou),
                "device": norm_dev,
                "draw_skeleton": False,
            },
        )

        n_bags = create_tool_instance("Context Object Detector", "node_bags", "05_Context_Bags")
        _set_node_params(
            n_bags,
            {
                "model_path": bag_model,
                "confidence": 0.25,
                "iou": 0.45,
                "device": norm_dev,
                "infer_stride": 3,
                "armed_stride": 2,
                "max_cache_age_sec": 0.55,
                "skip_when_no_persons": True,
                "target_classes": _DEFAULT_TARGET_CLASSES,
            },
        )

        n_track = create_tool_instance("BoT-SORT Tracker", "node_tracker", "06_BoTSORT_Tracker")
        _set_node_params(
            n_track,
            {
                "tracker_type": "botsort.yaml",
                "frame_rate": 8,
                "device": norm_dev,
                "enable_reid": True,
                "gmc_method": "none",
                "draw_trails": False,
            },
        )

        max_seq = max(6, min(16, int(getattr(vlm_cfg, "max_sequence_frames", 14) or 14)))
        n_beh = create_tool_instance("Behavior Gate", "node_behavior", "07_Behavior_Gate")
        _set_node_params(
            n_beh,
            {
                "camera_id": cam_id,
                "camera_name": cam_name,
                "dwell_sec": float(getattr(cam, "dwell_sec", 3.0) or 3.0),
                "release_wait_sec": float(getattr(cam, "release_wait_sec", 3.5) or 3.5),
                "cooldown_sec": float(getattr(cam, "cooldown_sec", 12.0) or 12.0),
                "max_sequence_frames": max_seq,
                "preview_only": False,
            },
        )

        n_vlm = create_tool_instance("VLM Audit", "node_vlm", "08_VLM_Audit")
        _set_node_params(
            n_vlm,
            {
                "provider": str(getattr(vlm_cfg, "provider", "gemini") or "gemini"),
                "base_url": str(getattr(vlm_cfg, "base_url", "") or ""),
                "model_name": str(getattr(vlm_cfg, "model_name", "gemini-2.5-flash") or "gemini-2.5-flash"),
                "api_key": "",
                "temperature": 0.1,
                "max_tokens": 2048,
                "timeout_sec": float(getattr(vlm_cfg, "timeout_sec", 25.0) or 25.0),
                "alert_threshold_pct": float(getattr(vlm_cfg, "alert_threshold_pct", 65.0) or 65.0),
                "use_native_video": bool(getattr(vlm_cfg, "use_native_video", True)),
                "video_fps": float(getattr(vlm_cfg, "video_fps", 2.0) or 2.0),
                "max_sequence_frames": max_seq,
                "disable_reasoning": bool(getattr(vlm_cfg, "disable_reasoning", False)),
                "dry_run_confidence": float(getattr(vlm_cfg, "dry_run_confidence", 0.85) or 0.85),
            },
        )

        for nid, node in (
            ("node_source", n_src),
            ("node_roi", n_roi),
            ("node_motion", n_motion),
            ("node_pose", n_pose),
            ("node_bags", n_bags),
            ("node_tracker", n_track),
            ("node_behavior", n_beh),
            ("node_vlm", n_vlm),
        ):
            pipe.add_node(node)
            if nid in _NODE_LAYOUT:
                pipe.node_positions[nid] = _NODE_LAYOUT[nid]

        _wire_connection(pipe, "node_source", "Image", "node_roi", "Image")
        _wire_connection(pipe, "node_source", "Image", "node_motion", "Image")
        _wire_connection(pipe, "node_source", "Timestamp", "node_motion", "Timestamp")
        _wire_connection(pipe, "node_roi", "Normalized_Zones", "node_motion", "Zones")

        _wire_connection(pipe, "node_source", "Image", "node_pose", "Image")
        _wire_connection(pipe, "node_roi", "Aisle_Crop", "node_pose", "ROI")
        _wire_connection(pipe, "node_motion", "Motion_ROI", "node_pose", "Fallback_ROI")

        _wire_connection(pipe, "node_source", "Image", "node_bags", "Image")
        _wire_connection(pipe, "node_roi", "Aisle_Crop", "node_bags", "ROI")
        _wire_connection(pipe, "node_pose", "Count", "node_bags", "Person_Count")
        _wire_connection(pipe, "node_source", "Timestamp", "node_bags", "Timestamp")

        _wire_connection(pipe, "node_source", "Image", "node_tracker", "Image")
        _wire_connection(pipe, "node_pose", "Detections", "node_tracker", "Detections")
        _wire_connection(pipe, "node_pose", "Keypoints", "node_tracker", "Keypoints")

        _wire_connection(pipe, "node_source", "Image", "node_behavior", "Image")
        _wire_connection(pipe, "node_source", "Timestamp", "node_behavior", "Timestamp")
        _wire_connection(pipe, "node_tracker", "Tracks", "node_behavior", "Tracks")
        _wire_connection(pipe, "node_bags", "Detections", "node_behavior", "Bag_Detections")
        _wire_connection(pipe, "node_roi", "Normalized_Zones", "node_behavior", "Zones")

        _wire_connection(pipe, "node_behavior", "Candidate", "node_vlm", "Candidate")
        _wire_connection(pipe, "node_behavior", "Grid_Image", "node_vlm", "Grid_Image")
        _wire_connection(pipe, "node_behavior", "Triggered", "node_vlm", "Triggered")
        return pipe

    def sync_camera_flow(
        self,
        cam: Any,
        *,
        pose_model: str = "yolo11n-pose.onnx",
        bag_model: str = "yolo11n.onnx",
        device: str = "auto",
        vlm_cfg: Any = None,
        pose_conf: float = 0.25,
        pose_iou: float = 0.50,
    ) -> ApexProcedure:
        """Create or update a camera's `<ApexFlow>` while preserving custom node tuning where intact."""
        cam_id = str(getattr(cam, "camera_id", None) or getattr(cam, "id", "cam_01"))
        existing = self.manager.flows.get(cam_id)
        has_all_nodes = existing is not None and all(nid in existing.nodes for nid in self.REQUIRED_NODE_IDS)
        if not has_all_nodes:
            pipe = self.build_camera_pipeline(
                cam,
                pose_model=pose_model,
                bag_model=bag_model,
                device=device,
                vlm_cfg=vlm_cfg,
                pose_conf=pose_conf,
                pose_iou=pose_iou,
            )
            self.manager.flows[cam_id] = pipe
            self._rebuild_procedure_index()
            return self._procedures[cam_id]

        pipe = existing
        assert pipe is not None
        pipe.enabled = bool(getattr(cam, "enabled", True))
        raw_url = str(getattr(cam, "rtsp_url", "") or "")
        clean_url = _clean_media_path(raw_url)
        is_file = bool(clean_url and os.path.isfile(clean_url))

        _set_node_params(
            pipe.nodes["node_source"],
            {
                "source_type": "File" if is_file else "IP Stream",
                "file_path": clean_url if is_file else "",
                "stream_url": "" if is_file else raw_url,
            },
        )
        zones_list = [_zone_to_dict(z, i) for i, z in enumerate(getattr(cam, "zones", ()) or ())]
        _set_node_params(pipe.nodes["node_roi"], {"zones": zones_list})

        norm_dev = normalize_device_request(device)
        for nid in ("node_pose", "node_bags", "node_tracker"):
            _set_node_params(pipe.nodes[nid], {"device": norm_dev})

        max_seq = max(6, min(16, int(getattr(vlm_cfg, "max_sequence_frames", 14) or 14)))
        _set_node_params(
            pipe.nodes["node_behavior"],
            {
                "camera_id": cam_id,
                "camera_name": str(getattr(cam, "name", cam_id) or cam_id),
                "dwell_sec": float(getattr(cam, "dwell_sec", 3.0) or 3.0),
                "release_wait_sec": float(getattr(cam, "release_wait_sec", 3.5) or 3.5),
                "cooldown_sec": float(getattr(cam, "cooldown_sec", 12.0) or 12.0),
                "max_sequence_frames": max_seq,
            },
        )
        _set_node_params(
            pipe.nodes["node_vlm"],
            {
                "provider": str(getattr(vlm_cfg, "provider", "gemini") or "gemini"),
                "base_url": str(getattr(vlm_cfg, "base_url", "") or ""),
                "model_name": str(getattr(vlm_cfg, "model_name", "gemini-2.5-flash") or "gemini-2.5-flash"),
                "api_key": "",
                "timeout_sec": float(getattr(vlm_cfg, "timeout_sec", 25.0) or 25.0),
                "alert_threshold_pct": float(getattr(vlm_cfg, "alert_threshold_pct", 65.0) or 65.0),
                "use_native_video": bool(getattr(vlm_cfg, "use_native_video", True)),
                "video_fps": float(getattr(vlm_cfg, "video_fps", 2.0) or 2.0),
                "max_sequence_frames": max_seq,
                "disable_reasoning": bool(getattr(vlm_cfg, "disable_reasoning", False)),
                "dry_run_confidence": float(getattr(vlm_cfg, "dry_run_confidence", 0.85) or 0.85),
            },
        )
        self._rebuild_procedure_index()
        return self._procedures[cam_id]

    @classmethod
    def build_from_cameras(
        cls,
        cameras: Sequence[Any],
        *,
        pose_model: str = "yolo11n-pose.onnx",
        bag_model: str = "yolo11n.onnx",
        device: str = "auto",
        vlm_cfg: Any = None,
        solution_name: str = "StoreGuard",
        solution_path: Optional[str | Path] = None,
    ) -> "ApexSolution":
        """Create a multi-flow `ApexSolution` with one `<ApexFlow>` per configured camera."""
        ensure_theft_plugin_loaded()
        mgr = SolutionManager(name=solution_name)
        mgr.flows.clear()
        sol = cls(mgr, solution_path=solution_path)
        for cam in cameras:
            sol.sync_camera_flow(
                cam,
                pose_model=pose_model,
                bag_model=bag_model,
                device=device,
                vlm_cfg=vlm_cfg,
            )
        return sol

    def sync_from_cameras(
        self,
        cameras: Sequence[Any],
        *,
        pose_model: str = "yolo11n-pose.onnx",
        bag_model: str = "yolo11n.onnx",
        device: str = "auto",
        vlm_cfg: Any = None,
        solution_name: str = "StoreGuard",
    ) -> None:
        self.manager.name = solution_name
        desired_ids = [str(getattr(c, "camera_id", None) or getattr(c, "id", "")) for c in cameras]
        for fname in list(self.manager.flows.keys()):
            if fname == "Flow1" or (desired_ids and fname not in desired_ids):
                self.manager.flows.pop(fname, None)
        for cam in cameras:
            self.sync_camera_flow(
                cam,
                pose_model=pose_model,
                bag_model=bag_model,
                device=device,
                vlm_cfg=vlm_cfg,
            )
        self._rebuild_procedure_index()

    def to_xml(self) -> str:
        """Serialize `<ApexSolution>` XML while stripping runtime `__*` globals and secrets."""
        with self.manager._globals_lock:
            saved_globals = dict(self.manager.global_variables)
            saved_rt = set(self.manager.runtime_globals)
            saved_keys: Dict[Tuple[str, str], Any] = {}
            try:
                self.manager.global_variables = {
                    k: v
                    for k, v in saved_globals.items()
                    if not str(k).startswith("__") and "api_key" not in str(k).lower()
                }
                self.manager.runtime_globals = {
                    k for k in saved_rt if k in self.manager.global_variables
                }
                for fname, pipe in self.manager.flows.items():
                    for nid, nd in pipe.nodes.items():
                        if "api_key" in (nd.parameters or {}):
                            saved_keys[(fname, nid)] = nd.parameters["api_key"]
                            nd.parameters["api_key"] = ""
                return self.manager.to_xml()
            finally:
                self.manager.global_variables = saved_globals
                self.manager.runtime_globals = saved_rt
                for (fname, nid), val in saved_keys.items():
                    pipe = self.manager.flows.get(fname)
                    if pipe and nid in pipe.nodes:
                        pipe.nodes[nid].parameters["api_key"] = val

    def save(self, path: Optional[str | Path] = None) -> Path:
        target = Path(path) if path is not None else self.solution_path
        if target is None:
            raise ValueError("No solution path specified for ApexSolution.save()")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        xml_text = self.to_xml()
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(xml_text, encoding="utf-8")
        os.replace(tmp, target)
        self.solution_path = target
        return target

    @classmethod
    def load(cls, path: str | Path) -> "ApexSolution":
        ensure_theft_plugin_loaded()
        p = Path(path)
        mgr = SolutionManager.load_from_file(str(p))
        return cls(mgr, solution_path=p)

    @classmethod
    def from_xml(cls, xml_text: str, solution_path: Optional[str | Path] = None) -> "ApexSolution":
        ensure_theft_plugin_loaded()
        mgr = SolutionManager.from_xml(xml_text)
        return cls(mgr, solution_path=solution_path)


class ApexRuntimeEngine:
    """Multi-camera real-time runtime orchestrating camera grabbers, Apex Vision flows, and async VLM audit."""

    def __init__(
        self,
        cfg: Any,
        base_dir: str | Path,
        broadcaster: Any,
        *,
        solution_path: Optional[str | Path] = None,
    ):
        self.base_dir = Path(base_dir)
        self.cfg = cfg
        self.broadcaster = broadcaster
        self._lock = threading.RLock()

        self.models_dir = self._resolve_dir(cfg.engine.models_dir)
        os.environ["APEX_MODELS_DIR"] = str(self.models_dir)

        evidence_dir = self._resolve_dir(getattr(cfg.engine, "evidence_dir", "runtime_data/evidence"))
        logs_dir = self._resolve_dir(getattr(cfg.engine, "logs_dir", "runtime_data/logs"))
        self.evidence_dir = evidence_dir
        self.logs_dir = logs_dir

        if solution_path is not None:
            self.solution_path = Path(solution_path)
        else:
            self.solution_path = self.base_dir / "runtime_data" / "storeguard.apex"

        self._vlm_core = get_theft_submodule("vlm_core")
        self._beh_core = get_theft_submodule("behavior_core")
        self._pose_mod = get_theft_submodule("pose_detector_tool")
        self._bag_mod = get_theft_submodule("context_detector_tool")

        self._apply_scaling_settings(cfg.engine)

        caps = get_device_capabilities()
        req_dev = normalize_device_request(cfg.engine.device)
        if req_dev == "cpu":
            resolved_dev = "cpu"
            using_gpu = False
        else:
            resolved_dev = caps["resolved_device"]
            using_gpu = caps["using_gpu"]
        self._requested_device = req_dev
        self._resolved_device = resolved_dev
        self._using_gpu = using_gpu
        self._cuda_available = caps["cuda_available"]
        self._tensorrt_available = bool(get_onnx_execution_capabilities().get("tensorrt_available", False))
        self._fallback_note = "" if req_dev == "cpu" else caps.get("fallback_note", "")

        self.recent_pickups = self._beh_core.RecentPickupsPool(ttl_sec=120.0, max_entries=24)
        self.vlm_worker = self._vlm_core.VlmWorker(
            self._vlm_cfg(cfg),
            on_verdict=self._handle_vlm_verdict,
            on_error=self._handle_vlm_error,
        )
        self.retention = RetentionManager(
            evidence_dir,
            retention_days=int(getattr(cfg.engine, "retention_days", 30) or 30),
            max_evidence_gb=float(getattr(cfg.engine, "max_evidence_gb", 20.0) or 20.0),
        )
        self.audit_logger = VlmAuditLogger(logs_dir)

        self.solution = self._init_or_load_solution(cfg)

        self._workers: Dict[str, CameraStreamWorker] = {}
        self._worker_locks: Dict[str, threading.Lock] = {}
        self._last_processed_seq: Dict[str, int] = {}
        self._next_due: Dict[str, float] = {}
        self._inflight: Dict[str, Future] = {}
        self._prev_armed: Dict[str, bool] = {}
        self._latest_overlays: Dict[str, Dict[str, Any]] = {}

        self._stop_evt = threading.Event()
        self._exec_pool: Optional[ThreadPoolExecutor] = None
        self._scheduler_thread: Optional[threading.Thread] = None
        self._last_retention_check = 0.0

    def _apply_scaling_settings(self, eng: Any) -> None:
        raw_threads = int(getattr(eng, "worker_threads", 0) or 0)
        self._worker_threads = raw_threads if raw_threads > 0 else max(2, min(8, int(os.cpu_count() or 4)))
        self._idle_fps = max(1.0, min(15.0, float(getattr(eng, "idle_fps", 3.0) or 3.0)))
        self._batch_max_size = max(1, min(32, int(getattr(eng, "batch_max_size", 8) or 8)))
        self._batch_max_wait_ms = max(0.0, min(50.0, float(getattr(eng, "batch_max_wait_ms", 8.0) or 8.0)))
        self._use_tensorrt = bool(getattr(eng, "use_tensorrt", True))
        self._decode_backend = str(getattr(eng, "decode_backend", "auto") or "auto")
        raw_ring_w = getattr(eng, "ring_max_width", None)
        self._ring_max_width = max(0, int(raw_ring_w if raw_ring_w is not None else 1280))
        os.environ["APEX_TRT_ENABLE"] = "1" if self._use_tensorrt else "0"
        os.environ["APEX_BATCH_MAX"] = str(self._batch_max_size)
        os.environ["APEX_BATCH_WAIT_MS"] = str(self._batch_max_wait_ms)

    @staticmethod
    def _vlm_cfg(cfg: Any) -> Any:
        v = getattr(cfg, "vlm", None)
        if v is not None:
            return v
        return getattr(getattr(cfg, "engine", None), "vlm", None)

    @staticmethod
    def _target_fps(cfg: Any) -> float:
        eng = getattr(cfg, "engine", None)
        val = getattr(eng, "target_fps", None) or getattr(eng, "scheduler_fps", None) or 8.0
        return float(val)

    def _model_path(self, raw_name: str, default_name: str) -> str:
        name = str(raw_name or default_name).strip() or default_name
        p = Path(name)
        return str(p if p.is_absolute() else (self.models_dir / p))

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        fn = getattr(self.broadcaster, "emit_sync", None) or getattr(self.broadcaster, "publish_sync", None)
        if callable(fn):
            fn(event_type, payload)

    def _resolve_dir(self, path_str: str) -> Path:
        p = Path(path_str)
        return p if p.is_absolute() else (self.base_dir / p)

    def _sync_runtime_globals(self) -> None:
        vlm = self._vlm_cfg(self.cfg)
        enabled_cnt = sum(1 for c in getattr(self.cfg, "cameras", ()) if getattr(c, "enabled", True))
        gv = self.solution.manager.global_variables
        with self.solution.manager._globals_lock:
            gv["__recent_pickups__"] = self.recent_pickups
            gv["__vlm_dispatcher__"] = self.vlm_worker
            gv["__vlm_api_key__"] = str(getattr(vlm, "api_key", "") or "")
            gv["__vlm_provider__"] = str(getattr(vlm, "provider", "gemini") or "gemini")
            gv["__batch_coalesce__"] = bool(enabled_cnt > 1 and self._batch_max_size > 1)

    def _init_or_load_solution(self, cfg: Any) -> ApexSolution:
        pose_path = self._model_path(getattr(cfg.engine, "pose_model", ""), "yolo11n-pose.onnx")
        bag_path = self._model_path(getattr(cfg.engine, "bag_model", ""), "yolo11n.onnx")
        vlm = self._vlm_cfg(cfg)
        if self.solution_path.is_file():
            try:
                sol = ApexSolution.load(self.solution_path)
                sol.sync_from_cameras(
                    cfg.cameras,
                    pose_model=pose_path,
                    bag_model=bag_path,
                    device=self._resolved_device,
                    vlm_cfg=vlm,
                )
                return sol
            except Exception as exc:
                logger.warning("Failed to load %s (%s); regenerating clean storeguard.apex", self.solution_path, exc)

        sol = ApexSolution.build_from_cameras(
            cfg.cameras,
            pose_model=pose_path,
            bag_model=bag_path,
            device=self._resolved_device,
            vlm_cfg=vlm,
            solution_name="StoreGuard",
            solution_path=self.solution_path,
        )
        try:
            sol.save(self.solution_path)
        except Exception as exc:
            logger.debug("Initial save of %s skipped: %s", self.solution_path, exc)
        return sol

    def _ensure_camera_slots(self, cfg: Any) -> None:
        pose_path = self._model_path(getattr(cfg.engine, "pose_model", ""), "yolo11n-pose.onnx")
        bag_path = self._model_path(getattr(cfg.engine, "bag_model", ""), "yolo11n.onnx")
        vlm = self._vlm_cfg(cfg)
        self.solution.sync_from_cameras(
            cfg.cameras,
            pose_model=pose_path,
            bag_model=bag_path,
            device=self._resolved_device,
            vlm_cfg=vlm,
        )
        pose_conf = float(getattr(cfg.engine, "pose_conf", 0.25) or 0.25)
        pose_iou = float(getattr(cfg.engine, "pose_iou", 0.50) or 0.50)
        bag_conf = float(getattr(cfg.engine, "bag_conf", 0.25) or 0.25)
        bag_iou = float(getattr(cfg.engine, "bag_iou", 0.45) or 0.45)
        bag_stride = int(getattr(cfg.engine, "bag_infer_stride", 3) or 3)
        ctx_classes = getattr(cfg.engine, "context_classes", None)
        for cam in cfg.cameras:
            proc = self.solution[cam.camera_id]
            proc.set_param("node_pose", "confidence", pose_conf)
            proc.set_param("node_pose", "iou", pose_iou)
            proc.set_param("node_bags", "confidence", bag_conf)
            proc.set_param("node_bags", "iou", bag_iou)
            proc.set_param("node_bags", "infer_stride", bag_stride)
            if isinstance(ctx_classes, (list, tuple)) and ctx_classes:
                proc.set_param("node_bags", "target_classes", ",".join(str(x) for x in ctx_classes))

        self._sync_runtime_globals()

        desired_ids = {c.camera_id for c in cfg.cameras}
        for cid in list(self._workers.keys()):
            if cid not in desired_ids:
                w = self._workers.pop(cid)
                w.stop()
                self._worker_locks.pop(cid, None)
                self._last_processed_seq.pop(cid, None)
                self._prev_armed.pop(cid, None)
                self._latest_overlays.pop(cid, None)

        fps_ring = self._target_fps(cfg)
        for cam in cfg.cameras:
            if cam.camera_id not in self._worker_locks:
                self._worker_locks[cam.camera_id] = threading.Lock()
            old = self._workers.get(cam.camera_id)
            need_new_worker = (
                old is None
                or old._cfg.rtsp_url != cam.rtsp_url
                or old._cfg.enabled != cam.enabled
            )
            if need_new_worker:
                if old is not None:
                    old.stop()
                worker = CameraStreamWorker(
                    cam,
                    ring_buffer_sec=10.0,
                    ring_fps=fps_ring,
                    on_health_change=lambda payload: self._emit("CAMERA_HEALTH", payload),
                    decode_backend=self._decode_backend,
                    target_fps=fps_ring,
                    idle_ring_fps=2.0,
                    ring_max_width=self._ring_max_width,
                    sub_stream_url=str(getattr(cam, "sub_stream_url", "") or ""),
                )
                self._workers[cam.camera_id] = worker
                self._last_processed_seq[cam.camera_id] = -1
                self._next_due[cam.camera_id] = 0.0
                if cam.enabled and not self._stop_evt.is_set() and self._scheduler_thread is not None:
                    worker.start()
            elif old is not None:
                old._cfg.zones = list(cam.zones)
                old._cfg.name = cam.name
                old._ring_max_width = self._ring_max_width

            proc = self.solution[cam.camera_id]
            worker_ref = self._workers.get(cam.camera_id)
            with self.solution.manager._globals_lock:
                if worker_ref is not None:
                    self.solution.manager.global_variables[f"__ring_fn_{cam.camera_id}"] = worker_ref.snapshot_ring_buffer
                self.solution.manager.global_variables.setdefault(f"__armed_{cam.camera_id}", False)
                self.solution.manager.global_variables.setdefault(f"__preview_only_{cam.camera_id}", False)
            if not cam.enabled:
                proc.reset()

    def start(self) -> None:
        with self._lock:
            self._stop_evt.clear()
            self._ensure_camera_slots(self.cfg)
            if self._exec_pool is None:
                self._exec_pool = ThreadPoolExecutor(
                    max_workers=self._worker_threads,
                    thread_name_prefix="apex-proc",
                )
            for cam in self.cfg.cameras:
                if cam.enabled and cam.camera_id in self._workers:
                    self._workers[cam.camera_id].start()
            if self._scheduler_thread is None or not self._scheduler_thread.is_alive():
                self._scheduler_thread = threading.Thread(
                    target=self._scheduler_loop,
                    name="apex-runtime-scheduler",
                    daemon=True,
                )
                self._scheduler_thread.start()
        self._emit("ENGINE_METRICS", self.get_health())

    def stop(self) -> None:
        self._stop_evt.set()
        with self._lock:
            workers = list(self._workers.values())
            pool = self._exec_pool
            self._exec_pool = None
        for w in workers:
            w.stop()
        if self._scheduler_thread is not None and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=3.0)
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        self.vlm_worker.stop()

    def reload_config(self, new_cfg: Any) -> int:
        with self._lock:
            old_dev = self.cfg.engine.device
            old_threads = self._worker_threads
            self.cfg = new_cfg
            self._apply_scaling_settings(new_cfg.engine)
            self.vlm_worker.update_config(self._vlm_cfg(new_cfg))
            if normalize_device_request(new_cfg.engine.device) != normalize_device_request(old_dev):
                self._apply_device_locked(new_cfg.engine.device)
            if self._exec_pool is not None and self._worker_threads != old_threads:
                self._exec_pool.shutdown(wait=False)
                self._exec_pool = ThreadPoolExecutor(
                    max_workers=self._worker_threads,
                    thread_name_prefix="apex-proc",
                )
            self._ensure_camera_slots(new_cfg)
            for cid, worker in self._workers.items():
                if worker._cfg.enabled and self._scheduler_thread is not None and self._scheduler_thread.is_alive():
                    worker.start()
            try:
                self.solution.save(self.solution_path)
            except Exception:
                pass
            active = sum(1 for c in new_cfg.cameras if c.enabled)
        self._emit("ENGINE_METRICS", self.get_health())
        return active

    def update_camera_zones(self, camera_id: str, zones: List[Any]) -> bool:
        with self._lock:
            cam = next((c for c in self.cfg.cameras if c.camera_id == camera_id), None)
            if cam is None:
                return False
            cam.zones = list(zones)
            if camera_id in self._workers:
                self._workers[camera_id]._cfg.zones = list(zones)
                self._workers[camera_id].invalidate_snapshot_cache()
            if camera_id in self.solution:
                proc = self.solution[camera_id]
                z_dicts = [_zone_to_dict(z, i) for i, z in enumerate(zones)]
                proc.set_param("node_roi", "zones", z_dicts)
                nd_beh = proc.node("node_behavior")
                if nd_beh is not None and getattr(nd_beh, "_gate", None) is not None:
                    nd_beh._gate.update_zones(zones)
                nd_beh_shelf = proc.node("node_motion")
                if nd_beh_shelf is not None and hasattr(nd_beh_shelf, "reset"):
                    nd_beh_shelf.reset()
            try:
                self.solution.save(self.solution_path)
            except Exception:
                pass
            return True

    def get_snapshot(
        self,
        camera_id: str,
        overlays: bool = True,
        max_width: Optional[int] = None,
        quality: int = 80,
        overlay_layers: Any = None,
    ) -> Tuple[Optional[bytes], bool]:
        with self._lock:
            worker = self._workers.get(camera_id)
            ov = self._latest_overlays.get(camera_id) if overlays else None
            cam = next((c for c in self.cfg.cameras if c.camera_id == camera_id), None)
            zones = cam.zones if (overlays and cam is not None) else None
        if worker is None:
            return None, False
        from apex_vision.sdk.stream_worker import _parse_overlay_layers

        layers_key = _parse_overlay_layers(bool(overlays), overlay_layers)
        cache_key = (
            (
                ov.get("ts") if ov else 0.0,
                bool(ov.get("preview_only")) if ov else False,
                len(zones or ()),
                layers_key,
            )
            if overlays and layers_key
            else "raw"
        )
        jpg = worker.get_snapshot_jpeg(
            zones=zones,
            overlays=overlays,
            overlay_layers=layers_key,
            overlay_tracks=ov.get("tracks") if ov else None,
            overlay_poses=ov.get("poses") if ov else None,
            overlay_bags=ov.get("bags") if ov else None,
            overlay_motion_roi=ov.get("motion_roi") if ov else None,
            preview_only=bool(ov.get("preview_only")) if ov else False,
            max_width=int(max_width or 0),
            quality=int(quality or 85),
            cache_key=cache_key,
        )
        return jpg, True

    def get_snapshot_jpeg(
        self,
        camera_id: str,
        overlays: bool = True,
        max_width: Optional[int] = None,
        quality: int = 80,
        overlay_layers: Any = None,
    ) -> Optional[bytes]:
        jpg, _ = self.get_snapshot(
            camera_id,
            overlays=overlays,
            max_width=max_width,
            quality=quality,
            overlay_layers=overlay_layers,
        )
        return jpg

    def pause_worker(self, camera_id: str) -> None:
        with self._lock:
            w = self._workers.get(camera_id)
        if w is not None:
            w.stop()

    def reset_camera_state(self, camera_id: str) -> None:
        with self._lock:
            if camera_id in self.solution:
                self.solution[camera_id].reset()
            self._prev_armed[camera_id] = False
            self._latest_overlays.pop(camera_id, None)
            with self.solution.manager._globals_lock:
                self.solution.manager.global_variables[f"__armed_{camera_id}"] = False
                self.solution.manager.global_variables[f"__preview_only_{camera_id}"] = False
            w = self._workers.get(camera_id)
            if w is not None:
                w.set_clip_detection_done(False)
                w.set_motion_active(False)

    def rerun_camera_detection(self, camera_id: str) -> bool:
        with self._lock:
            worker = self._workers.get(camera_id)
            if worker is None:
                return False
            self.reset_camera_state(camera_id)
            self._last_processed_seq[camera_id] = -1
            if worker.is_local_file:
                worker.restart_from_start()
        return True

    def _apply_device_locked(self, requested: str) -> None:
        norm_dev = normalize_device_request(requested)
        caps = get_device_capabilities()
        self._requested_device = norm_dev
        if norm_dev == "cpu":
            self._resolved_device = "cpu"
            self._using_gpu = False
            self._fallback_note = ""
        else:
            self._resolved_device = caps["resolved_device"]
            self._using_gpu = caps["using_gpu"]
            self._fallback_note = caps.get("fallback_note", "")
        self._cuda_available = caps["cuda_available"]
        self.cfg.engine.device = norm_dev
        for fname in self.solution.list_procedures():
            proc = self.solution[fname]
            for nid in ("node_pose", "node_bags", "node_tracker"):
                proc.set_param(nid, "device", self._resolved_device)

    def set_device(self, device: str) -> Dict[str, Any]:
        with self._lock:
            self._apply_device_locked(device)
            try:
                self.solution.save(self.solution_path)
            except Exception:
                pass
            info = self.get_device_info()
        self._emit("ENGINE_METRICS", self.get_health())
        return info

    def get_device_info(self) -> Dict[str, Any]:
        return {
            "requested_device": self._requested_device,
            "resolved_device": self._resolved_device,
            "using_gpu": self._using_gpu,
            "cuda_available": self._cuda_available,
            "fallback_note": self._fallback_note,
        }

    def get_health(self) -> Dict[str, Any]:
        with self._lock:
            cams = [self._workers[cid].get_health() for cid in self._workers]
            active = len(self._workers)
            procs = self.solution.list_procedures()
        pose_metrics = self._pose_mod.get_pose_batch_metrics() if hasattr(self._pose_mod, "get_pose_batch_metrics") else {}
        bag_metrics = self._bag_mod.get_bag_batch_metrics() if hasattr(self._bag_mod, "get_bag_batch_metrics") else {}
        return {
            "status": "ready",
            "runtime": "apex_vision",
            "solution_name": self.solution.manager.name,
            "solution_path": str(self.solution_path),
            "procedures": procs,
            "device": self._resolved_device,
            "requested_device": self._requested_device,
            "using_gpu": self._using_gpu,
            "cuda_available": self._cuda_available,
            "tensorrt_available": self._tensorrt_available,
            "fallback_note": self._fallback_note,
            "active_streams": active,
            "worker_threads": self._worker_threads,
            "idle_fps": self._idle_fps,
            "batch_metrics": {"pose": pose_metrics, "bags": bag_metrics},
            "vlm_queue_depth": self.vlm_worker.queue_depth,
            "cameras": cams,
        }

    # --- Hikrobot-style SDK inspection & live manipulation ---

    def get_solution_info(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self.solution.manager.name,
                "solution_path": str(self.solution_path),
                "runtime": "apex_vision",
                "procedures": [self.solution[p].to_summary() for p in self.solution.list_procedures()],
            }

    def get_solution_xml(self) -> str:
        with self._lock:
            return self.solution.to_xml()

    def save_solution(self, path: Optional[str | Path] = None) -> str:
        with self._lock:
            saved = self.solution.save(path or self.solution_path)
            self.solution_path = saved
            return str(saved)

    def load_solution(self, *, path: Optional[str | Path] = None, xml_text: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if xml_text is not None and xml_text.strip():
                sol = ApexSolution.from_xml(xml_text, solution_path=self.solution_path)
            else:
                target = Path(path) if path else self.solution_path
                sol = ApexSolution.load(target)
                self.solution_path = target
            self.solution = sol
            self._sync_runtime_globals()
            self._ensure_camera_slots(self.cfg)
            return self.get_solution_info()

    def list_procedures(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self.solution[p].to_summary() for p in self.solution.list_procedures()]

    def get_procedure_summary(self, name: str) -> Dict[str, Any]:
        with self._lock:
            if name not in self.solution:
                raise KeyError(name)
            return self.solution[name].to_summary()

    def get_procedure_param(self, name: str, node_id: str, param_name: str) -> Any:
        with self._lock:
            if name not in self.solution:
                raise KeyError(name)
            return self.solution[name].get_param(node_id, param_name)

    def set_procedure_param(self, name: str, node_id: str, param_name: str, value: Any) -> Dict[str, Any]:
        with self._lock:
            if name not in self.solution:
                raise KeyError(name)
            ok = self.solution[name].set_param(node_id, param_name, value)
            if not ok:
                raise KeyError(f"Unknown node '{node_id}' in procedure '{name}'")
            if node_id == "node_vlm" and param_name == "alert_threshold_pct":
                vlm = self._vlm_cfg(self.cfg)
                if vlm is not None:
                    vlm.alert_threshold_pct = float(value)
                    self.vlm_worker.update_config(vlm)
            try:
                self.solution.save(self.solution_path)
            except Exception:
                pass
            return self.solution[name].to_summary()

    def run_procedure_once(
        self,
        name: str,
        *,
        frame_bgr: Optional[np.ndarray] = None,
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if name not in self.solution:
                raise KeyError(name)
            proc = self.solution[name]
            worker = self._workers.get(name)
        if frame_bgr is None and worker is not None:
            frame_bgr, timestamp, _ = worker._get_latest_frame_ref()
        if frame_bgr is None:
            return {"procedure": name, "executed": False, "error": "No frame available"}

        t0 = time.perf_counter()
        self._sync_runtime_globals()
        results = proc.run_once(frame_bgr=frame_bgr, timestamp=timestamp)
        dt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        node_statuses = {nid: res.status.value for nid, res in results.items()}
        beh_res = results.get("node_behavior")
        beh_out = beh_res.outputs if beh_res else {}
        return {
            "procedure": name,
            "executed": True,
            "elapsed_ms": dt_ms,
            "node_statuses": node_statuses,
            "triggered": bool(beh_out.get("Triggered", False)),
            "armed": bool(beh_out.get("Armed", False)),
        }

    # --- Frame execution & overlay cache ---

    def _cache_track_overlays(
        self,
        camera_id: str,
        tracks: Sequence[Dict[str, Any]],
        track_states: Dict[int, Dict[str, Any]],
        *,
        poses: Optional[Sequence[Dict[str, Any]]] = None,
        bags: Optional[Sequence[Dict[str, Any]]] = None,
        motion_roi: Optional[Sequence[Any]] = None,
        preview_only: bool = False,
    ) -> None:
        packed: List[Dict[str, Any]] = []
        for tr in tracks:
            tid = int(tr.get("track_id", 0))
            st = track_states.get(tid) or {}
            packed.append({
                "track_id": tid,
                "bbox": list(tr.get("bbox") or [0, 0, 0, 0]),
                "confidence": round(float(tr.get("confidence") or 0.0), 3),
                "phase": str(st.get("phase") or ""),
                "armed": bool(st.get("armed")),
                "keypoints": list(tr.get("keypoints") or ()),
                "trail": list(tr.get("trail") or ()),
            })
        with self._lock:
            self._latest_overlays[camera_id] = {
                "ts": time.monotonic(),
                "tracks": packed,
                "poses": list(poses or ()),
                "bags": list(bags or ()),
                "motion_roi": list(motion_roi or (0, 0, 0, 0)),
                "preview_only": bool(preview_only),
            }

    def process_single_frame(
        self,
        camera_id: str,
        frame_bgr: np.ndarray,
        ts: float,
        ring_frames: Optional[List[Tuple[float, bytes]]] = None,
        *,
        preview_only: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Execute one frame through `<ApexFlow name="{camera_id}">` via `VisionPipeline.execute_flow()`."""
        with self._lock:
            if camera_id not in self.solution:
                cam = next((c for c in self.cfg.cameras if c.camera_id == camera_id), None)
                if cam is None:
                    return None
                self.solution.sync_camera_flow(
                    cam,
                    pose_model=self._model_path(getattr(self.cfg.engine, "pose_model", ""), "yolo11n-pose.onnx"),
                    bag_model=self._model_path(getattr(self.cfg.engine, "bag_model", ""), "yolo11n.onnx"),
                    device=self._resolved_device,
                    vlm_cfg=self._vlm_cfg(self.cfg),
                )
            proc = self.solution[camera_id]
            worker = self._workers.get(camera_id)

        preview_only = bool(
            preview_only
            or (worker is not None and worker.is_local_file and worker.clip_detection_done)
        )
        self._sync_runtime_globals()
        with self.solution.manager._globals_lock:
            gv = self.solution.manager.global_variables
            gv[f"__preview_only_{camera_id}"] = bool(preview_only)
            if ring_frames is not None:
                gv[f"__ring_frames_{camera_id}"] = list(ring_frames)
                gv.pop(f"__ring_fn_{camera_id}", None)
            elif worker is not None:
                gv[f"__ring_fn_{camera_id}"] = worker.snapshot_ring_buffer

        results = proc.run_once(frame_bgr=frame_bgr, timestamp=ts)

        mot_res = results.get("node_motion")
        mot_active = bool(mot_res.outputs.get("Active", False)) if mot_res else False
        if worker is not None:
            worker.set_motion_active(mot_active)

        pose_res = results.get("node_pose")
        bag_res = results.get("node_bags")
        trk_res = results.get("node_tracker")
        beh_res = results.get("node_behavior")

        motion_roi = list((mot_res.outputs.get("Motion_ROI") if mot_res else None) or (0, 0, 0, 0))
        poses = list((pose_res.outputs.get("Detections") if pose_res else None) or ())
        bags = list((bag_res.outputs.get("Detections") if bag_res else None) or ())
        tracks = list((trk_res.outputs.get("Tracks") if trk_res else None) or ())
        track_states = dict((beh_res.outputs.get("Track_States") if beh_res else None) or {})
        self._cache_track_overlays(
            camera_id,
            tracks,
            track_states,
            poses=poses,
            bags=bags,
            motion_roi=motion_roi,
            preview_only=preview_only,
        )

        armed_now = bool(beh_res.outputs.get("Armed", False)) if beh_res else False
        prev_arm = self._prev_armed.get(camera_id, False)
        if armed_now != prev_arm:
            self._prev_armed[camera_id] = armed_now
            self._emit("ENGINE_METRICS", self.get_health())

        cand = beh_res.outputs.get("Candidate") if beh_res else None
        if isinstance(cand, dict) and (beh_res and beh_res.outputs.get("Triggered")):
            return cand
        return None

    # --- VLM async callbacks ---

    def _handle_vlm_verdict(
        self,
        candidate: Dict[str, Any],
        verdict: Dict[str, Any],
        grid_bgr: np.ndarray,
        ring_frames: List[Tuple[float, bytes]],
    ) -> None:
        vlm = self._vlm_cfg(self.cfg)
        threshold_pct = float(getattr(vlm, "alert_threshold_pct", 65.0) or 65.0)
        provider = str(getattr(vlm, "provider", "") or "")
        model_name = str(getattr(vlm, "model_name", "") or "")
        latency_sec = candidate.get("_vlm_latency_sec")

        decision, conf_pct, vlm_reasons, fact_reasons, dest = self._vlm_core.evaluate_four_fact_verdict(
            verdict, threshold_pct
        )
        cam_id = str(candidate.get("camera_id") or "")
        tid = int(candidate.get("track_id", 0))
        if dest == "carried_openly":
            self.recent_pickups.mark_resolution(cam_id, tid, "carried_openly")
            if cam_id in self.solution:
                nd_beh = self.solution[cam_id].node("node_behavior")
                if nd_beh is not None and hasattr(nd_beh, "mark_carried_openly"):
                    nd_beh.mark_carried_openly(tid, ttl_sec=60.0)
        elif dest in ("returned_to_shelf", "store_basket_or_cart"):
            self.recent_pickups.mark_resolution(cam_id, tid, "returned")
        elif decision == "ALERT":
            self.recent_pickups.mark_resolution(cam_id, tid, "concealed")

        event_id = f"{cam_id}_t{tid}_{int(time.time() * 1000)}"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        grid_path = ""
        clip_path = ""

        if decision == "ALERT":
            grid_path = save_grid_jpeg(grid_bgr, self.evidence_dir / "grids" / f"{stamp}_{event_id}.jpg")
            clip_res = write_ring_clip_mp4(
                ring_frames,
                self.evidence_dir / "clips" / f"{stamp}_{event_id}.mp4",
                default_fps=self._target_fps(self.cfg),
            )
            clip_path = clip_res or ""
            self.audit_logger.log_verdict(
                candidate=candidate,
                provider=provider,
                model_name=model_name,
                decision=decision,
                conf_pct=conf_pct,
                threshold_pct=threshold_pct,
                suppression_reasons=vlm_reasons,
                verdict=verdict,
                event_id=event_id,
                latency_sec=latency_sec,
            )
            payload = {
                "event_id": event_id,
                "camera_id": cam_id,
                "camera_name": candidate.get("camera_name", ""),
                "track_id": tid,
                "behavior_category": str(verdict.get("behavior_category") or "high_risk_concealment_attempt"),
                "confidence_pct": conf_pct,
                "behaviors": candidate.get("behaviors", []),
                "nearby_bags": candidate.get("nearby_bags", []),
                "justification": str(verdict.get("justification") or ""),
                "grid_path": grid_path,
                "clip_path": clip_path,
            }
            self._emit("ALERT", payload)
            self.retention.prune_now()
        else:
            self.audit_logger.log_verdict(
                candidate=candidate,
                provider=provider,
                model_name=model_name,
                decision=decision,
                conf_pct=conf_pct,
                threshold_pct=threshold_pct,
                suppression_reasons=fact_reasons,
                verdict=verdict,
                event_id="",
                latency_sec=latency_sec,
            )

    def _handle_vlm_error(self, candidate: Dict[str, Any], error_msg: str, grid_bgr: np.ndarray) -> None:
        vlm = self._vlm_cfg(self.cfg)
        provider = str(getattr(vlm, "provider", "") or "")
        model_name = str(getattr(vlm, "model_name", "") or "")
        cam_id = str(candidate.get("camera_id") or "")
        tid = int(candidate.get("track_id", 0))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        grid_path = ""
        try:
            grid_path = save_grid_jpeg(
                grid_bgr,
                self.evidence_dir / "grids" / f"{stamp}_{cam_id}_t{tid}_err.jpg",
            )
        except Exception:
            pass
        self.audit_logger.log_error(
            candidate=candidate,
            provider=provider,
            model_name=model_name,
            error_msg=error_msg,
            grid_path=grid_path,
            latency_sec=candidate.get("_vlm_latency_sec"),
        )
        self._emit(
            "VLM_ERROR",
            {
                "camera_id": cam_id,
                "track_id": tid,
                "error": error_msg,
                "grid_path": grid_path,
            },
        )

    def _run_camera_tick(self, cam_id: str, worker: CameraStreamWorker) -> bool:
        """Run one camera's EOF/restart checks + `VisionPipeline.execute_flow()` inside the worker pool."""
        wlock = self._worker_locks.get(cam_id)
        if wlock is None or not wlock.acquire(blocking=False):
            return False
        try:
            if worker.is_local_file:
                if worker.restart_pending:
                    if cam_id in self.solution:
                        self.solution[cam_id].reset()
                    self._prev_armed[cam_id] = False
                    with self.solution.manager._globals_lock:
                        self.solution.manager.global_variables[f"__armed_{cam_id}"] = False
                        self.solution.manager.global_variables[f"__preview_only_{cam_id}"] = False
                    self._last_processed_seq[cam_id] = -1
                elif worker.loop_count >= 1 and not worker.clip_detection_done:
                    worker.set_clip_detection_done(True)
                    eof_frame, eof_ring = worker.pop_eof_context()
                    if cam_id in self.solution:
                        nd_beh = self.solution[cam_id].node("node_behavior")
                        if nd_beh is not None and hasattr(nd_beh, "flush_armed_on_clip_end"):
                            eof_ts = float(eof_ring[-1][0]) if eof_ring else time.monotonic()
                            for grid_bgr, cand, ring in nd_beh.flush_armed_on_clip_end(
                                eof_frame,
                                eof_ring,
                                eof_ts,
                                recent_pickups=self.recent_pickups,
                                provider=str(getattr(self._vlm_cfg(self.cfg), "provider", "") or ""),
                            ):
                                self.vlm_worker.submit(cand, grid_bgr, ring)
                        nd_beh_reset = self.solution[cam_id].node("node_behavior")
                        if nd_beh_reset is not None and hasattr(nd_beh_reset, "on_video_loop_restart"):
                            nd_beh_reset.on_video_loop_restart()
                    self._prev_armed[cam_id] = False
                    self._emit("CAMERA_HEALTH", worker.get_health())

            frame_bgr, ts, seq = worker._get_latest_frame_ref()
            if frame_bgr is None:
                return False
            if seq == self._last_processed_seq.get(cam_id, -1):
                return False
            self._last_processed_seq[cam_id] = seq

            preview_only = bool(worker.is_local_file and worker.clip_detection_done)
            self.process_single_frame(cam_id, frame_bgr, ts, preview_only=preview_only)
            return True
        except Exception as exc:
            logger.debug("ApexRuntimeEngine worker error (%s): %s", cam_id, exc)
            return False
        finally:
            wlock.release()

    # --- Parallel multi-camera scheduler dispatching to ThreadPoolExecutor + adaptive FPS ---

    def _scheduler_loop(self) -> None:
        while not self._stop_evt.is_set():
            now = time.monotonic()
            target_fps = max(2.0, min(15.0, self._target_fps(self.cfg)))
            active_period = 1.0 / target_fps
            idle_period = 1.0 / max(1.0, min(target_fps, self._idle_fps))

            with self._lock:
                items = [(c.camera_id, self._workers.get(c.camera_id)) for c in self.cfg.cameras if c.enabled]
                pool = self._exec_pool

            # Reap completed worker futures and schedule adaptive next due timestamps
            for cid in list(self._inflight.keys()):
                fut = self._inflight[cid]
                if not fut.done():
                    continue
                self._inflight.pop(cid, None)
                w = self._workers.get(cid)
                is_hot = bool(
                    self._prev_armed.get(cid, False)
                    or (w is not None and (w._motion_active or (w.is_local_file and not w.clip_detection_done)))
                )
                interval = active_period if is_hot else idle_period
                self._next_due[cid] = now + interval

            for cam_id, worker in items:
                if self._stop_evt.is_set() or worker is None or cam_id in self._inflight:
                    continue
                if now < self._next_due.get(cam_id, 0.0):
                    continue

                is_hot = bool(
                    self._prev_armed.get(cam_id, False)
                    or worker._motion_active
                    or (worker.is_local_file and not worker.clip_detection_done)
                )
                has_eof_work = bool(
                    worker.is_local_file
                    and (worker.restart_pending or (worker.loop_count >= 1 and not worker.clip_detection_done))
                )
                has_new_frame = worker._latest_frame is not None and worker._seq != self._last_processed_seq.get(cam_id, -1)
                if not has_new_frame and not has_eof_work:
                    self._next_due[cam_id] = now + (0.015 if is_hot else min(0.08, idle_period * 0.5))
                    continue

                if pool is not None:
                    self._inflight[cam_id] = pool.submit(self._run_camera_tick, cam_id, worker)
                else:
                    self._run_camera_tick(cam_id, worker)
                    self._next_due[cam_id] = time.monotonic() + (active_period if is_hot else idle_period)

            if (now - self._last_retention_check) > 3600.0:
                self._last_retention_check = now
                try:
                    self.retention.prune_now()
                except Exception:
                    pass

            self._stop_evt.wait(0.01)
