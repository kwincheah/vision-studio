"""Modular Theft Recognition & VLM Suite Plugin for Apex Vision Studio."""
from __future__ import annotations

import importlib.util
import os
import sys
from typing import List, Type

from apex_vision.sdk import IVisionPlugin, PluginMetadata, VisionToolBase


def _load_sibling(mod_suffix: str, filename: str):
    full_name = f"{__name__}.{mod_suffix}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    spec = importlib.util.spec_from_file_location(full_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load plugin submodule {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(full_name, None)
        raise
    return mod


# Preload helper submodules in the active plugin package namespace first
_load_sibling("batch_broker", "batch_broker.py")
_load_sibling("shelf_delta", "shelf_delta.py")
_load_sibling("behavior_core", "behavior_core.py")
_load_sibling("vlm_core", "vlm_core.py")

ROIZoneManagerTool = _load_sibling("roi_zone_tool", "roi_zone_tool.py").ROIZoneManagerTool
YOLOPoseTool = _load_sibling("pose_detector_tool", "pose_detector_tool.py").YOLOPoseTool
BoTSORTTrackerTool = _load_sibling("botsort_tool", "botsort_tool.py").BoTSORTTrackerTool
VLMTool = _load_sibling("vlm_module_tool", "vlm_module_tool.py").VLMTool
MotionGateTool = _load_sibling("motion_gate_tool", "motion_gate_tool.py").MotionGateTool
ContextObjectDetectorTool = _load_sibling("context_detector_tool", "context_detector_tool.py").ContextObjectDetectorTool
BehaviorGateTool = _load_sibling("behavior_gate_tool", "behavior_gate_tool.py").BehaviorGateTool
VlmAuditTool = _load_sibling("vlm_audit_tool", "vlm_audit_tool.py").VlmAuditTool


class TheftRecognitionPlugin(IVisionPlugin):
    """Exports ROI Zone Manager, Motion Gate, YOLO Pose, Context Detector, BoT-SORT Tracker, Behavior Gate, VLM, and VLM Audit tools."""

    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            plugin_id="theft_recognition_plugin",
            name="Modular Vision Tracking & VLM Suite",
            version="3.1.0",
            author="Apex Vision",
            description=(
                "ROI Zone Manager (dynamic pixel & normalized ROI ports), Motion Gate, YOLO Pose (ONNX/.pt), "
                "Context Object Detector, BoT-SORT Tracker, Behavior Gate, VLM caller, and 4-Fact VLM Audit."
            ),
            category="Theft Recognition",
            min_sdk_version="1.0.0",
            tags=["roi", "motion", "yolo", "pose", "botsort", "behavior", "vlm", "tracking"],
        )

    @classmethod
    def register_tools(cls) -> List[Type[VisionToolBase]]:
        return [
            ROIZoneManagerTool,
            MotionGateTool,
            YOLOPoseTool,
            ContextObjectDetectorTool,
            BoTSORTTrackerTool,
            BehaviorGateTool,
            VLMTool,
            VlmAuditTool,
        ]

    @classmethod
    def on_load(cls) -> bool:
        return True

    @classmethod
    def on_unload(cls):
        pass
