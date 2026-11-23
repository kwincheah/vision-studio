"""Lightweight CPU Motion Gate plugin tool emitting Inactive_Branches when aisles are idle."""
from __future__ import annotations

import copy
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus
from apex_vision.sdk import ParamDef, ParamType, PluginToolBase


def _norm_zone_rect(z: Any, sw: int, sh: int) -> Optional[Tuple[int, int, int, int]]:
    if isinstance(z, dict):
        role = str(z.get("role") or "").strip().lower()
        if role != "aisle":
            return None
        rn = z.get("rect_norm")
        if isinstance(rn, (list, tuple)) and len(rn) >= 4:
            nx, ny, nw, nh = float(rn[0]), float(rn[1]), float(rn[2]), float(rn[3])
            if nw > 0.0 and nh > 0.0 and sw > 0 and sh > 0:
                x1 = max(0, min(sw - 1, int(round(nx * sw))))
                y1 = max(0, min(sh - 1, int(round(ny * sh))))
                rw = max(1, min(sw - x1, int(round(nw * sw))))
                rh = max(1, min(sh - y1, int(round(nh * sh))))
                return (x1, y1, rw, rh)
    elif hasattr(z, "role") and hasattr(z, "to_pixel_rect"):
        if getattr(z, "role", "") == "aisle":
            return z.to_pixel_rect(sw, sh)
    return None


class MotionGateTool(PluginToolBase):
    """Downscaled 160x90 gray-diff motion pre-gate to skip empty aisles with zero downstream overhead."""

    plugin_id = "theft_recognition_plugin"
    category = "Theft Recognition"
    tool_name = "Motion Gate"
    description = (
        "Lightweight 160x90 grayscale motion pre-gate with hysteresis tail. "
        "Emits Inactive_Branches for downstream nodes when aisles are idle and unarmed."
    )

    param_definitions = {
        "diff_thresh": ParamDef("diff_thresh", ParamType.INT, 16, "Pixel intensity delta threshold", 1, 100, 1),
        "ratio_thresh": ParamDef("ratio_thresh", ParamType.FLOAT, 0.005, "Changed pixel area ratio threshold", 0.0001, 0.5, 0.001),
        "tail_sec": ParamDef("tail_sec", ParamType.FLOAT, 3.0, "Post-motion hysteresis window (sec)", 0.0, 30.0, 0.25),
        "ref_interval_sec": ParamDef("ref_interval_sec", ParamType.FLOAT, 0.35, "Background reference refresh period (sec)", 0.05, 5.0, 0.05),
        "min_zoom_side": ParamDef("min_zoom_side", ParamType.INT, 300, "Minimum zoom crop size around motion", 64, 1080, 16),
        "bypass_nodes": ParamDef("bypass_nodes", ParamType.STRING, "", "Comma-separated node IDs to bypass when idle & unarmed"),
    }

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input video frame")
        self.inputs["Timestamp"] = ToolPort("Timestamp", DataType.VALUE, "Frame timestamp in seconds")
        self.inputs["Zones"] = ToolPort("Zones", DataType.ANY, "Optional normalized zone descriptors [{name, role, rect_norm}]")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through image")
        self.outputs["Active"] = ToolPort("Active", DataType.BOOLEAN, "True when motion or hysteresis window is active")
        self.outputs["Motion_ROI"] = ToolPort("Motion_ROI", DataType.REGION, "Square crop around latest motion [x, y, w, h]")
        self.outputs["Inactive_Branches"] = ToolPort("Inactive_Branches", DataType.ANY, "Node IDs bypassed when idle and unarmed")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "ACTIVE or IDLE")

    def _init_parameters(self):
        self.parameters = {k: copy.deepcopy(p.default_value) for k, p in self.param_definitions.items()}
        self._sample_size: Tuple[int, int] = (160, 90)
        self._ref_gray: Optional[np.ndarray] = None
        self._ref_ts: float = 0.0
        self._motion_until: float = 0.0
        self._last_motion_norm_box: Optional[Tuple[float, float, float, float]] = None

    def reset(self) -> None:
        self._ref_gray = None
        self._ref_ts = 0.0
        self._motion_until = 0.0
        self._last_motion_norm_box = None

    def _get_motion_crop(self, w_img: int, h_img: int, min_side: int) -> List[int]:
        if self._last_motion_norm_box is None or w_img <= 0 or h_img <= 0:
            return [0, 0, 0, 0]
        nx, ny, nw, nh = self._last_motion_norm_box
        x1 = int(round(nx * w_img))
        y1 = int(round(ny * h_img))
        x2 = int(round((nx + nw) * w_img))
        y2 = int(round((ny + nh) * h_img))
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        side = max(int(min_side), (x2 - x1) + 140, (y2 - y1) + 140)
        rx1 = max(0, min(max(0, w_img - side), cx - side // 2))
        ry1 = max(0, min(max(0, h_img - side), cy - side // 2))
        rw = min(w_img - rx1, side)
        rh = min(h_img - ry1, side)
        if rw <= 0 or rh <= 0 or (rw * rh) >= 0.65 * float(w_img * h_img):
            return [0, 0, 0, 0]
        return [rx1, ry1, rw, rh]

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=4, min_h=4)
        if img is None:
            return ToolExecutionResult(
                status=ToolStatus.NG,
                message="No valid input image for Motion Gate",
                outputs={"Active": False, "Motion_ROI": [0, 0, 0, 0], "Inactive_Branches": [], "Status": "NG"},
            )

        diff_thresh = max(1, int(self.as_float(self.get_param("diff_thresh", 16), 16)))
        ratio_thresh = max(1e-5, float(self.as_float(self.get_param("ratio_thresh", 0.005), 0.005)))
        tail_sec = max(0.0, float(self.as_float(self.get_param("tail_sec", 3.0), 3.0)))
        ref_interval = max(0.02, float(self.as_float(self.get_param("ref_interval_sec", 0.35), 0.35)))
        min_zoom_side = max(64, int(self.as_float(self.get_param("min_zoom_side", 300), 300)))
        bypass_raw = str(self.get_param("bypass_nodes", "") or "")

        raw_ts = context.get("Timestamp")
        now_ts = float(raw_ts) if raw_ts is not None else time.monotonic()
        zones = context.get("Zones") or []

        sw, sh = self._sample_size
        small = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        gray = self.to_grayscale(small)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        active = False
        if self._ref_gray is None or self._ref_gray.shape != gray.shape:
            self._ref_gray = gray
            self._ref_ts = now_ts
            self._motion_until = max(self._motion_until, now_ts + tail_sec)
            active = True
        else:
            diff = cv2.absdiff(gray, self._ref_gray)
            if now_ts < self._ref_ts or (now_ts - self._ref_ts) >= ref_interval:
                self._ref_gray = gray
                self._ref_ts = now_ts

            aisle_rects = [r for r in (_norm_zone_rect(z, sw, sh) for z in zones) if r is not None]
            if aisle_rects:
                mask = np.zeros((sh, sw), dtype=np.uint8)
                for ax, ay, aw, ah in aisle_rects:
                    mask[ay:ay + ah, ax:ax + aw] = 1
                area = int(mask.sum())
                if area > 0:
                    motion_mask = (diff > diff_thresh) & (mask > 0)
                    ratio = float(np.count_nonzero(motion_mask)) / float(area)
                else:
                    motion_mask = diff > diff_thresh
                    ratio = float(np.count_nonzero(motion_mask)) / float(sw * sh)
            else:
                motion_mask = diff > diff_thresh
                ratio = float(np.count_nonzero(motion_mask)) / float(sw * sh)

            if ratio >= ratio_thresh:
                self._motion_until = max(self._motion_until, now_ts + tail_sec)
                ys, xs = np.where(motion_mask)
                if len(xs) >= 12:
                    self._last_motion_norm_box = (
                        float(xs.min()) / float(sw),
                        float(ys.min()) / float(sh),
                        float(xs.max() - xs.min() + 1) / float(sw),
                        float(ys.max() - ys.min() + 1) / float(sh),
                    )
            active = now_ts <= self._motion_until

        gctx = context.get("global") or {}
        globals_dict = gctx.get("globals") or {}
        flow_name = str(gctx.get("flow_name") or "")
        armed = bool(globals_dict.get(f"__armed_{flow_name}", False))
        preview_only = bool(globals_dict.get(f"__preview_only_{flow_name}", False))

        inactive_branches: List[str] = []
        if not active and (preview_only or not armed):
            inactive_branches = [n.strip() for n in bypass_raw.split(",") if n.strip()]

        h_img, w_img = img.shape[:2]
        motion_roi = self._get_motion_crop(w_img, h_img, min_zoom_side)
        return ToolExecutionResult(
            status=ToolStatus.OK,
            message="Motion active" if active else ("Armed idle" if armed else "Idle"),
            outputs={
                "Image": img,
                "Active": bool(active),
                "Motion_ROI": motion_roi,
                "Inactive_Branches": inactive_branches,
                "Status": "ACTIVE" if active else ("ARMED_IDLE" if armed and not preview_only else "IDLE"),
            },
        )
