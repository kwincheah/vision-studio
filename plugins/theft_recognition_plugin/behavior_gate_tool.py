"""Behavior Gate plugin tool executing StoreGuard's dual-trigger state machine inside Apex Vision flows."""
from __future__ import annotations

import copy
import importlib.util
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus
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


_core = _load_local("behavior_core")
BehaviorGate = _core.BehaviorGate
RecentPickupsPool = _core.RecentPickupsPool
augment_sequence_with_ring_context = _core.augment_sequence_with_ring_context
_ensure_bgr_u8 = _core._ensure_bgr_u8


def finalize_candidate(
    cand: Dict[str, Any],
    ring_frames: List[Tuple[float, bytes]],
    recent_pickups: Optional[RecentPickupsPool],
    ts: float,
    *,
    max_seq: int = 14,
    provider: str = "",
) -> Dict[str, Any]:
    clean_scene_jpg = cand.pop("clean_scene_jpg", b"")
    pre_reach_jpg = cand.pop("pre_reach_jpg", b"")
    first_sample_ts = cand.pop("first_sample_ts", None)
    union_crop_rect = cand.pop("union_crop_rect", None)
    query_hist = cand.pop("upper_color_hist", None)

    cap = max(6, min(16, int(max_seq or 14)))
    cand["sequence_frames"] = augment_sequence_with_ring_context(
        list(cand.get("sequence_frames") or []),
        ring_frames,
        first_sample_ts=first_sample_ts,
        clean_scene_jpg=pre_reach_jpg or clean_scene_jpg,
        crop_rect=union_crop_rect,
        max_frames=cap,
    )

    if cand.get("trigger_mode") == "shelf_free_tuck" and recent_pickups is not None:
        sheet_jpeg, sheet_meta = recent_pickups.build_reference_sheet(
            ts,
            query_hist=query_hist,
            max_tiles=6,
        )
        if sheet_jpeg:
            seq = list(cand.get("sequence_frames") or [])
            is_gem = (provider or "").strip().lower() == "gemini"
            keep_n = 5 if is_gem else max(1, cap - 1)
            if len(seq) > keep_n:
                if keep_n == 1:
                    seq = [seq[-1]]
                else:
                    pick_idxs = sorted({int(i) for i in np.linspace(0, len(seq) - 1, keep_n, dtype=int).tolist()})
                    seq = [seq[i] for i in pick_idxs]
            cand["sequence_frames"] = [sheet_jpeg] + seq
            cand["has_reference_sheet"] = True
            cand["reference_pickups"] = sheet_meta
        else:
            cand["has_reference_sheet"] = False
            cand["reference_pickups"] = []
    else:
        cand["has_reference_sheet"] = False
        cand["reference_pickups"] = []

    return cand


class BehaviorGateTool(PluginToolBase):
    """Per-camera behavioral state machine, shelf-delta tracker, and candidate sequence packager."""

    plugin_id = "theft_recognition_plugin"
    category = "Theft Recognition"
    tool_name = "Behavior Gate"
    description = (
        "Stateful behavioral gate (Path A shelf reach + localized shelf delta; Path B shelf-free tuck + cross-cam pickups) "
        "packaging 2x3 overview grids and up to 14 chronological shopper crops for VLM Audit."
    )

    param_definitions = {
        "camera_id": ParamDef("camera_id", ParamType.STRING, "cam_01", "Camera identifier"),
        "camera_name": ParamDef("camera_name", ParamType.STRING, "Camera 1", "Human-readable camera label"),
        "dwell_sec": ParamDef("dwell_sec", ParamType.FLOAT, 3.0, "Minimum dwell inside aisle zone (sec)", 0.2, 30.0, 0.25),
        "release_wait_sec": ParamDef("release_wait_sec", ParamType.FLOAT, 3.5, "Post-arm natural release wait (sec)", 0.5, 30.0, 0.25),
        "cooldown_sec": ParamDef("cooldown_sec", ParamType.FLOAT, 12.0, "Per-track re-trigger cooldown (sec)", 1.0, 120.0, 1.0),
        "max_sequence_frames": ParamDef("max_sequence_frames", ParamType.INT, 14, "Max chronological VLM crops", 6, 16, 1),
        "preview_only": ParamDef("preview_only", ParamType.BOOLEAN, False, "Skip behavior triggering (overlay preview only)"),
    }

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input frame")
        self.inputs["Timestamp"] = ToolPort("Timestamp", DataType.VALUE, "Frame timestamp (sec)")
        self.inputs["Tracks"] = ToolPort("Tracks", DataType.ANY, "Tracked persons from BoT-SORT Tracker")
        self.inputs["Bag_Detections"] = ToolPort("Bag_Detections", DataType.ANY, "Context vessels from Context Object Detector")
        self.inputs["Zones"] = ToolPort("Zones", DataType.ANY, "Normalized ROI zones from ROI Zone Manager")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through image")
        self.outputs["Grid_Image"] = ToolPort("Grid_Image", DataType.IMAGE, "2x3 visual sequence grid on trigger")
        self.outputs["Candidate"] = ToolPort("Candidate", DataType.ANY, "Packaged VLM candidate dict when triggered")
        self.outputs["Triggered"] = ToolPort("Triggered", DataType.BOOLEAN, "True when a concealment candidate dispatched")
        self.outputs["Armed"] = ToolPort("Armed", DataType.BOOLEAN, "True while any track is armed")
        self.outputs["Track_States"] = ToolPort("Track_States", DataType.ANY, "Track ID -> {phase, armed, dwell, in_zone}")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "MONITORING | ARMED | DISPATCH | PREVIEW")

    def _init_parameters(self):
        self.parameters = {k: copy.deepcopy(p.default_value) for k, p in self.param_definitions.items()}
        self._gate: Optional[BehaviorGate] = None
        self._gate_sig: Tuple[str, str, float, float, float] = ("", "", 0.0, 0.0, 0.0)
        self._recent_pickups_fallback: Optional[RecentPickupsPool] = None

    def _ensure_gate(self, zones: Any) -> BehaviorGate:
        cam_id = str(self.get_param("camera_id", "cam_01") or "cam_01")
        cam_name = str(self.get_param("camera_name", cam_id) or cam_id)
        dwell = max(0.2, float(self.as_float(self.get_param("dwell_sec", 3.0), 3.0)))
        rel = max(0.5, float(self.as_float(self.get_param("release_wait_sec", 3.5), 3.5)))
        cd = max(1.0, float(self.as_float(self.get_param("cooldown_sec", 12.0), 12.0)))
        sig = (cam_id, cam_name, dwell, rel, cd)
        if self._gate is None or self._gate.camera_id != cam_id:
            self._gate = BehaviorGate(
                cam_id,
                cam_name,
                dwell_sec=dwell,
                release_wait_sec=rel,
                cooldown_sec=cd,
                zones=zones or (),
            )
            self._gate_sig = sig
        elif sig != self._gate_sig:
            self._gate.update_timing(
                camera_name=cam_name,
                dwell_sec=dwell,
                release_wait_sec=rel,
                cooldown_sec=cd,
                zones=zones or (),
            )
            self._gate_sig = sig
        elif zones is not None:
            self._gate.update_zones(zones)
        return self._gate

    def get_track_states(self) -> Dict[int, Dict[str, Any]]:
        return self._gate.get_track_states() if self._gate is not None else {}

    def has_armed_tracks(self) -> bool:
        return self._gate.has_armed_tracks() if self._gate is not None else False

    def mark_carried_openly(self, tid: int, ttl_sec: float = 60.0) -> None:
        if self._gate is not None:
            self._gate.mark_carried_openly(tid, ttl_sec=ttl_sec)

    def on_video_loop_restart(self) -> None:
        if self._gate is not None:
            self._gate.on_video_loop_restart()

    def reset_all(self) -> None:
        if self._gate is not None:
            self._gate.reset_all()

    def flush_armed_on_clip_end(
        self,
        frame_bgr: Optional[np.ndarray],
        ring_frames: List[Tuple[float, bytes]],
        ts: float,
        *,
        recent_pickups: Optional[RecentPickupsPool] = None,
        provider: str = "",
    ) -> List[Tuple[np.ndarray, Dict[str, Any], List[Tuple[float, bytes]]]]:
        if self._gate is None:
            return []
        raw_out = self._gate.flush_armed_on_clip_end(frame_bgr)
        max_seq = max(6, min(16, int(self.as_float(self.get_param("max_sequence_frames", 14), 14))))
        pool = recent_pickups or self._recent_pickups_fallback
        finalized: List[Tuple[np.ndarray, Dict[str, Any], List[Tuple[float, bytes]]]] = []
        for grid_bgr, cand in raw_out:
            eof_ts = float(ring_frames[-1][0]) if ring_frames else float(cand.get("first_sample_ts") or ts)
            c_fin = finalize_candidate(cand, ring_frames, pool, eof_ts, max_seq=max_seq, provider=provider)
            finalized.append((grid_bgr, c_fin, list(ring_frames)))
        return finalized

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=4, min_h=4)
        if img is None:
            return ToolExecutionResult(
                status=ToolStatus.NG,
                message="No valid input image for Behavior Gate",
                outputs={
                    "Grid_Image": None,
                    "Candidate": None,
                    "Triggered": False,
                    "Armed": False,
                    "Track_States": {},
                    "Status": "NG",
                },
            )
        img = _ensure_bgr_u8(img)

        gctx = context.get("global") or {}
        globals_dict = gctx.get("globals")
        if not isinstance(globals_dict, dict):
            globals_dict = {}
        flow_name = str(gctx.get("flow_name") or "")
        preview_only = bool(self.get_param("preview_only", False)) or bool(globals_dict.get(f"__preview_only_{flow_name}", False))

        if preview_only:
            if flow_name:
                globals_dict[f"__armed_{flow_name}"] = False
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message="Behavior Gate preview-only bypass",
                outputs={
                    "Image": img,
                    "Grid_Image": img,
                    "Candidate": None,
                    "Triggered": False,
                    "Armed": False,
                    "Track_States": {},
                    "Status": "PREVIEW",
                },
            )

        zones = context.get("Zones")
        bg = self._ensure_gate(zones)
        ts_raw = context.get("Timestamp")
        ts = float(ts_raw) if ts_raw is not None else time.monotonic()
        tracks = context.get("Tracks") or []
        bags = context.get("Bag_Detections") or []

        grid_bgr, cand, stats = bg.step(img, ts, tracks, bags)
        armed = bg.has_armed_tracks()
        if flow_name:
            globals_dict[f"__armed_{flow_name}"] = armed

        recent_pickups = globals_dict.get("__recent_pickups__")
        if recent_pickups is None:
            if self._recent_pickups_fallback is None:
                self._recent_pickups_fallback = RecentPickupsPool(ttl_sec=120.0, max_entries=24)
            recent_pickups = self._recent_pickups_fallback

        for ev in bg.pop_pickup_events():
            recent_pickups.record_pickup(**ev)

        triggered = grid_bgr is not None and cand is not None
        if triggered:
            ring_fn = globals_dict.get(f"__ring_fn_{flow_name}") if flow_name else None
            ring_frames = list(ring_fn()) if callable(ring_fn) else list(globals_dict.get(f"__ring_frames_{flow_name}") or ())
            max_seq = max(6, min(16, int(self.as_float(self.get_param("max_sequence_frames", 14), 14))))
            provider = str(globals_dict.get("__vlm_provider__", ""))
            cand = finalize_candidate(cand, ring_frames, recent_pickups, ts, max_seq=max_seq, provider=provider)
            cand["_ring_frames"] = ring_frames

        track_states = bg.get_track_states()
        gate_state = str(stats.get("gate_state") or ("DISPATCH" if triggered else ("ARMED" if armed else "MONITORING")))
        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Behavior Gate [{gate_state}] tracks={stats.get('tracks', 0)}",
            outputs={
                "Image": img,
                "Grid_Image": grid_bgr if grid_bgr is not None else img,
                "Candidate": cand,
                "Triggered": bool(triggered),
                "Armed": bool(armed),
                "Track_States": track_states,
                "Status": gate_state,
            },
        )
