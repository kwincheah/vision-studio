"""VLM Audit plugin tool dispatching triggered theft candidates through Cloud VLM + 4-Fact Gate."""
from __future__ import annotations

import copy
import importlib.util
import os
import sys
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


_vcore = _load_local("vlm_core")
VlmRuntimeConfig = _vcore.VlmRuntimeConfig
VlmWorker = _vcore.VlmWorker
evaluate_four_fact_verdict = _vcore.evaluate_four_fact_verdict


class VlmAuditTool(PluginToolBase):
    """Non-blocking Cloud VLM verification + 4-Fact Visual Audit consistency gate."""

    plugin_id = "theft_recognition_plugin"
    category = "Theft Recognition"
    tool_name = "VLM Audit"
    description = (
        "Dispatches Behavior Gate candidates asynchronously to Gemini / OpenAI / OpenRouter / DeepSeek / Ollama / dry_run "
        "and enforces the 4-Fact Visual Audit consistency gate before raising confirmed theft alerts."
    )

    param_definitions = {
        "provider": ParamDef(
            "provider",
            ParamType.ENUM,
            "gemini",
            "VLM provider endpoint",
            choices=["gemini", "openai", "openrouter", "deepseek", "anthropic", "ollama", "lmstudio", "custom", "dry_run"],
        ),
        "base_url": ParamDef("base_url", ParamType.STRING, "", "Optional OpenAI-compatible base URL override"),
        "model_name": ParamDef("model_name", ParamType.STRING, "gemini-2.5-flash", "Model identifier"),
        "api_key": ParamDef("api_key", ParamType.STRING, "", "Optional API key (leave empty to use runtime/env secret)"),
        "temperature": ParamDef("temperature", ParamType.FLOAT, 0.1, "Sampling temperature", 0.0, 1.5, 0.05),
        "max_tokens": ParamDef("max_tokens", ParamType.INT, 2048, "Maximum output tokens", 128, 8192, 64),
        "timeout_sec": ParamDef("timeout_sec", ParamType.FLOAT, 25.0, "HTTP request timeout (sec)", 5.0, 120.0, 1.0),
        "alert_threshold_pct": ParamDef("alert_threshold_pct", ParamType.FLOAT, 65.0, "Minimum concealment confidence %", 10.0, 100.0, 1.0),
        "use_native_video": ParamDef("use_native_video", ParamType.BOOLEAN, True, "Send ring MP4 directly to native Gemini endpoints"),
        "video_fps": ParamDef("video_fps", ParamType.FLOAT, 2.0, "Native Gemini video sample rate", 0.5, 8.0, 0.5),
        "max_sequence_frames": ParamDef("max_sequence_frames", ParamType.INT, 14, "Max JPEG frames attached to non-video VLM", 6, 16, 1),
        "disable_reasoning": ParamDef("disable_reasoning", ParamType.BOOLEAN, False, "Pass reasoning.enabled=false for OpenRouter flash models"),
        "dry_run_confidence": ParamDef("dry_run_confidence", ParamType.FLOAT, 0.85, "Dry-run confidence score", 0.0, 1.0, 0.05),
    }

    def _init_ports(self):
        self.inputs["Candidate"] = ToolPort("Candidate", DataType.ANY, "Candidate metadata from Behavior Gate")
        self.inputs["Grid_Image"] = ToolPort("Grid_Image", DataType.IMAGE, "2x3 visual sequence grid")
        self.inputs["Triggered"] = ToolPort("Triggered", DataType.BOOLEAN, "Only queue VLM call when True")
        self.outputs["Queued"] = ToolPort("Queued", DataType.BOOLEAN, "True when candidate was queued for async audit")
        self.outputs["Queue_Depth"] = ToolPort("Queue_Depth", DataType.VALUE, "Active async VLM queue depth")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "QUEUED or IDLE")

    def _init_parameters(self):
        self.parameters = {k: copy.deepcopy(p.default_value) for k, p in self.param_definitions.items()}
        self._standalone_worker: Optional[VlmWorker] = None
        self.last_verdicts: List[Dict[str, Any]] = []

    def build_runtime_config(self, api_key_override: str = "") -> VlmRuntimeConfig:
        param_key = str(self.get_param("api_key", "") or "").strip()
        return VlmRuntimeConfig(
            provider=str(self.get_param("provider", "gemini") or "gemini"),
            base_url=str(self.get_param("base_url", "") or ""),
            model_name=str(self.get_param("model_name", "gemini-2.5-flash") or "gemini-2.5-flash"),
            api_key=param_key or str(api_key_override or ""),
            temperature=float(self.as_float(self.get_param("temperature", 0.1), 0.1)),
            max_tokens=int(self.as_float(self.get_param("max_tokens", 2048), 2048)),
            timeout_sec=float(self.as_float(self.get_param("timeout_sec", 25.0), 25.0)),
            alert_threshold_pct=float(self.as_float(self.get_param("alert_threshold_pct", 65.0), 65.0)),
            use_native_video=bool(self.get_param("use_native_video", True)),
            video_fps=float(self.as_float(self.get_param("video_fps", 2.0), 2.0)),
            max_sequence_frames=max(6, min(16, int(self.as_float(self.get_param("max_sequence_frames", 14), 14)))),
            disable_reasoning=bool(self.get_param("disable_reasoning", False)),
            dry_run_confidence=float(self.as_float(self.get_param("dry_run_confidence", 0.85), 0.85)),
        )

    def _ensure_standalone_worker(self, cfg: VlmRuntimeConfig) -> VlmWorker:
        if self._standalone_worker is None:
            def _on_ok(cand: Dict[str, Any], verdict: Dict[str, Any], _grid: np.ndarray, _ring: List[Tuple[float, bytes]]):
                decision, conf_pct, vlm_r, fact_r, dest = evaluate_four_fact_verdict(verdict, cfg.alert_threshold_pct)
                self.last_verdicts.append({
                    "camera_id": cand.get("camera_id"),
                    "track_id": cand.get("track_id"),
                    "decision": decision,
                    "confidence_pct": conf_pct,
                    "destination": dest,
                    "reasons": vlm_r or fact_r,
                    "verdict": verdict,
                })

            def _on_err(cand: Dict[str, Any], err: str, _grid: np.ndarray):
                self.last_verdicts.append({
                    "camera_id": cand.get("camera_id"),
                    "track_id": cand.get("track_id"),
                    "decision": "VLM_ERROR",
                    "error": err,
                })

            self._standalone_worker = VlmWorker(cfg, on_verdict=_on_ok, on_error=_on_err)
        else:
            self._standalone_worker.update_config(cfg)
        return self._standalone_worker

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        triggered = bool(context.get("Triggered"))
        cand = context.get("Candidate")
        grid = context.get("Grid_Image")

        gctx = context.get("global") or {}
        globals_dict = gctx.get("globals") or {}
        dispatcher = globals_dict.get("__vlm_dispatcher__")

        if not triggered or not isinstance(cand, dict):
            depth = getattr(dispatcher, "queue_depth", 0) if dispatcher is not None else (
                self._standalone_worker.queue_depth if self._standalone_worker is not None else 0
            )
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message="VLM Audit idle",
                outputs={"Queued": False, "Queue_Depth": depth, "Status": "IDLE"},
            )

        cand_copy = dict(cand)
        ring_frames = list(cand_copy.pop("_ring_frames", None) or ())
        grid_arr = grid if (isinstance(grid, np.ndarray) and grid.size > 0) else np.zeros((32, 32, 3), dtype=np.uint8)
        api_key_override = str(globals_dict.get("__vlm_api_key__", "") or "")
        cfg = self.build_runtime_config(api_key_override=api_key_override)

        if dispatcher is not None and hasattr(dispatcher, "submit"):
            try:
                dispatcher.submit(cand_copy, grid_arr, ring_frames, cfg_override=cfg)
            except TypeError:
                dispatcher.submit(cand_copy, grid_arr, ring_frames)
            depth = getattr(dispatcher, "queue_depth", 1)
        else:
            worker = self._ensure_standalone_worker(cfg)
            worker.submit(cand_copy, grid_arr, ring_frames, cfg_override=cfg)
            depth = worker.queue_depth

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"VLM Audit queued track #{cand_copy.get('track_id')}",
            outputs={"Queued": True, "Queue_Depth": depth, "Status": "QUEUED"},
        )
