"""ROI Zone Manager plugin tool: create, name, draw, and delete dynamic ROI output ports."""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus
from apex_vision.sdk import ParamDef, ParamType, PluginToolBase

_RESERVED_PORTS = {"Image", "Named_ROIs", "Zone_Count", "Union_ROI", "Normalized_Zones", "Aisle_Crop"}
_PALETTE: List[Tuple[int, int, int]] = [
    (0, 215, 255),
    (0, 220, 120),
    (255, 165, 0),
    (255, 105, 180),
    (120, 180, 255),
]


def _clean_zone_name(raw: Any, fallback: str, used: set) -> str:
    txt = re.sub(r"\s+", "_", str(raw or "").strip())
    txt = re.sub(r"[^a-zA-Z0-9_\-]", "", txt) or fallback
    if txt in _RESERVED_PORTS:
        txt = f"roi_{txt}"
    candidate = txt
    suffix = 2
    while candidate in used:
        candidate = f"{txt}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _coerce_rect(val: Any) -> List[int]:
    if isinstance(val, (list, tuple)) and len(val) >= 4:
        try:
            x, y, w, h = [int(round(float(v))) for v in val[:4]]
            return [max(0, x), max(0, y), max(0, w), max(0, h)]
        except (TypeError, ValueError):
            pass
    return [0, 0, 0, 0]


def _coerce_rect_norm(val: Any) -> Optional[List[float]]:
    if isinstance(val, (list, tuple)) and len(val) >= 4:
        try:
            nx, ny, nw, nh = [max(0.0, min(1.0, float(v))) for v in val[:4]]
            if nx + nw > 1.0:
                nw = max(0.0, 1.0 - nx)
            if ny + nh > 1.0:
                nh = max(0.0, 1.0 - ny)
            return [round(nx, 6), round(ny, 6), round(nw, 6), round(nh, 6)]
        except (TypeError, ValueError):
            pass
    return None


def _compute_aisle_crop(rects_with_role: List[Tuple[str, List[int]]], w_img: int, h_img: int) -> List[int]:
    """Compute union crop across aisle/shelf zones when occupying <75% of full frame."""
    rects_all = [r for _, r in rects_with_role]
    if not rects_all or w_img <= 0 or h_img <= 0:
        return [0, 0, 0, 0]

    has_aisle = any(role == "aisle" for role, _ in rects_with_role)
    if has_aisle:
        x1 = min(r[0] for r in rects_all)
        y1 = min(r[1] for r in rects_all)
        x2 = max(r[0] + r[2] for r in rects_all)
        y2 = max(r[1] + r[3] for r in rects_all)
        mw = max(12, int((x2 - x1) * 0.10))
        mh = max(12, int((y2 - y1) * 0.10))
        cx1, cy1 = max(0, x1 - mw), max(0, y1 - mh)
        cx2, cy2 = min(w_img, x2 + mw), min(h_img, y2 + mh)
    else:
        exp_x1: List[int] = []
        exp_y1: List[int] = []
        exp_x2: List[int] = []
        exp_y2: List[int] = []
        for rx, ry, rw, rh in rects_all:
            pad_x = max(120, int(rw * 0.90))
            pad_up = max(160, int(rh * 1.15))
            pad_down = max(80, int(rh * 0.45))
            exp_x1.append(max(0, rx - pad_x))
            exp_y1.append(max(0, ry - pad_up))
            exp_x2.append(min(w_img, rx + rw + pad_x))
            exp_y2.append(min(h_img, ry + rh + pad_down))
        cx1, cy1 = min(exp_x1), min(exp_y1)
        cx2, cy2 = max(exp_x2), max(exp_y2)

    cw, ch = max(1, cx2 - cx1), max(1, cy2 - cy1)
    if (cw * ch) >= 0.75 * float(max(1, w_img * h_img)):
        return [0, 0, 0, 0]
    return [cx1, cy1, cw, ch]


class ROIZoneManagerTool(PluginToolBase):
    """Defines multiple named ROIs (pixel or normalized) and exposes each ROI name as an output port."""

    plugin_id = "theft_recognition_plugin"
    category = "ROI & Zones"
    tool_name = "ROI Zone Manager"
    description = (
        "Add, rename, draw, and delete multiple named ROIs on the image (supporting both pixel rect and normalized rect_norm). "
        "Each ROI name automatically becomes an output port [x, y, w, h] for downstream modules."
    )

    param_definitions = {
        "zones": ParamDef(
            "zones",
            ParamType.LIST,
            [
                {"name": "shelf", "rect": [0, 0, 0, 0]},
                {"name": "aisle", "rect": [0, 0, 0, 0]},
            ],
            "Named ROI zones (each name becomes an accessible output port)",
            unit="roi_list",
        ),
        "draw_overlays": ParamDef("draw_overlays", ParamType.BOOLEAN, True, "Draw labeled ROI boxes on output image"),
    }

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self._rebuild_outputs(self.parameters.get("zones") if hasattr(self, "parameters") else None)

    def _init_parameters(self):
        self.parameters = {k: copy.deepcopy(p.default_value) for k, p in self.param_definitions.items()}
        self._rebuild_outputs(self.parameters.get("zones"))

    def _normalize_zones(self, raw_zones: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_zones, (list, tuple)):
            return []
        used: set = set()
        cleaned: List[Dict[str, Any]] = []
        for idx, item in enumerate(raw_zones):
            if not isinstance(item, dict):
                continue
            name = _clean_zone_name(item.get("name"), f"roi_{idx + 1}", used)
            rect = _coerce_rect(item.get("rect"))
            rect_norm = _coerce_rect_norm(item.get("rect_norm"))
            role_raw = str(item.get("role") or "").strip().lower()
            if role_raw in ("shelf", "aisle"):
                role = role_raw
            else:
                role = "aisle" if ("aisle" in name.lower() or "corridor" in name.lower()) else "shelf"

            entry: Dict[str, Any] = {"name": name, "rect": rect}
            if rect_norm is not None:
                entry["rect_norm"] = rect_norm
                if rect[2] <= 0 or rect[3] <= 0:
                    entry["rect"] = [
                        int(round(rect_norm[0] * 1280)),
                        int(round(rect_norm[1] * 720)),
                        int(round(rect_norm[2] * 1280)),
                        int(round(rect_norm[3] * 720)),
                    ]
            if "role" in item or rect_norm is not None:
                entry["role"] = role
            cleaned.append(entry)
        return cleaned

    def _rebuild_outputs(self, raw_zones: Any) -> List[Dict[str, Any]]:
        zones = self._normalize_zones(raw_zones)
        new_outputs: Dict[str, ToolPort] = {
            "Image": ToolPort("Image", DataType.IMAGE, "Pass-through image with ROI overlays"),
            "Named_ROIs": ToolPort("Named_ROIs", DataType.ANY, "Mapping of all ROI names to [x, y, w, h]"),
            "Union_ROI": ToolPort("Union_ROI", DataType.REGION, "Padded union bounding box of all active ROIs [x, y, w, h]"),
            "Aisle_Crop": ToolPort("Aisle_Crop", DataType.REGION, "Smart expanded aisle crop ROI (<75% frame) for pose/bag zoom"),
            "Normalized_Zones": ToolPort("Normalized_Zones", DataType.ANY, "List of {name, role, rect_norm} descriptors"),
            "Zone_Count": ToolPort("Zone_Count", DataType.VALUE, "Number of active (w>0, h>0) ROIs"),
        }
        for z in zones:
            name = z["name"]
            new_outputs[name] = ToolPort(name, DataType.REGION, f"ROI '{name}' [x, y, w, h]")
        self.outputs = new_outputs
        return zones

    def set_param(self, key: str, value: Any):
        if key == "zones":
            zones = self._rebuild_outputs(value)
            self.parameters["zones"] = zones
            return
        super().set_param(key, value)

    def load_dict(self, data: Dict[str, Any]):
        super().load_dict(data)
        self.parameters["zones"] = self._rebuild_outputs(self.parameters.get("zones"))

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=1, min_h=1)
        if img is None:
            return ToolExecutionResult(
                status=ToolStatus.NG,
                message="No input image for ROI Zone Manager",
                outputs={
                    "Named_ROIs": {},
                    "Union_ROI": [0, 0, 0, 0],
                    "Aisle_Crop": [0, 0, 0, 0],
                    "Normalized_Zones": [],
                    "Zone_Count": 0,
                },
            )

        h_img, w_img = img.shape[:2]
        zones = self._normalize_zones(self.get_param("zones", []))
        draw = bool(self.get_param("draw_overlays", True))

        named_map: Dict[str, List[int]] = {}
        norm_zones_out: List[Dict[str, Any]] = []
        overlays: List[Dict[str, Any]] = []
        outputs: Dict[str, Any] = {"Image": img}
        active_count = 0

        active_rects: List[List[int]] = []
        rects_with_role: List[Tuple[str, List[int]]] = []
        for idx, z in enumerate(zones):
            name = z["name"]
            role = str(z.get("role") or ("aisle" if ("aisle" in name.lower() or "corridor" in name.lower()) else "shelf"))
            rn = z.get("rect_norm")
            if isinstance(rn, (list, tuple)) and len(rn) >= 4 and rn[2] > 0.0 and rn[3] > 0.0:
                nx, ny, nw, nh = float(rn[0]), float(rn[1]), float(rn[2]), float(rn[3])
                x1 = max(0, min(w_img - 1, int(round(nx * w_img))))
                y1 = max(0, min(h_img - 1, int(round(ny * h_img))))
                rw = max(1, min(w_img - x1, int(round(nw * w_img))))
                rh = max(1, min(h_img - y1, int(round(nh * h_img))))
                rect = [x1, y1, rw, rh]
                norm_rect = [round(nx, 6), round(ny, 6), round(nw, 6), round(nh, 6)]
                active_rects.append(rect)
                rects_with_role.append((role, rect))
                active_count += 1
                if draw:
                    color = _PALETTE[idx % len(_PALETTE)]
                    overlays.append({"type": "rect", "rect": rect, "color": color, "thickness": 2})
                    overlays.append({"type": "text", "text": f"ROI:{name}", "pt": (x1, max(16, y1 - 6)), "color": color})
            else:
                x, y, w, h = z["rect"]
                if w > 0 and h > 0:
                    x1 = max(0, min(w_img - 1, x))
                    y1 = max(0, min(h_img - 1, y))
                    rw = max(1, min(w_img - x1, w))
                    rh = max(1, min(h_img - y1, h))
                    rect = [x1, y1, rw, rh]
                    norm_rect = [
                        round(x1 / float(max(1, w_img)), 6),
                        round(y1 / float(max(1, h_img)), 6),
                        round(rw / float(max(1, w_img)), 6),
                        round(rh / float(max(1, h_img)), 6),
                    ]
                    active_rects.append(rect)
                    rects_with_role.append((role, rect))
                    active_count += 1
                    if draw:
                        color = _PALETTE[idx % len(_PALETTE)]
                        overlays.append({"type": "rect", "rect": rect, "color": color, "thickness": 2})
                        overlays.append({"type": "text", "text": f"ROI:{name}", "pt": (x1, max(16, y1 - 6)), "color": color})
                else:
                    rect = [0, 0, 0, 0]
                    norm_rect = [0.0, 0.0, 0.0, 0.0]

            named_map[name] = rect
            outputs[name] = rect
            if rect[2] > 0 and rect[3] > 0:
                norm_zones_out.append({"name": name, "role": role, "rect_norm": norm_rect})

        if active_rects:
            ux1 = min(r[0] for r in active_rects)
            uy1 = min(r[1] for r in active_rects)
            ux2 = max(r[0] + r[2] for r in active_rects)
            uy2 = max(r[1] + r[3] for r in active_rects)
            mx = max(8, int(round((ux2 - ux1) * 0.10)))
            my = max(8, int(round((uy2 - uy1) * 0.10)))
            px1 = max(0, ux1 - mx)
            py1 = max(0, uy1 - my)
            px2 = min(w_img, ux2 + mx)
            py2 = min(h_img, uy2 + my)
            outputs["Union_ROI"] = [px1, py1, max(1, px2 - px1), max(1, py2 - py1)]
        else:
            outputs["Union_ROI"] = [0, 0, 0, 0]

        outputs["Aisle_Crop"] = _compute_aisle_crop(rects_with_role, w_img, h_img)
        outputs["Normalized_Zones"] = norm_zones_out
        outputs["Named_ROIs"] = named_map
        outputs["Zone_Count"] = active_count
        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"ROIs ready ({active_count}/{len(zones)} active)",
            outputs=outputs,
            overlays=overlays,
        )
