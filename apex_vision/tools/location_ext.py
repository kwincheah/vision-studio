"""
Hough Detect: finds circles or straight lines anywhere in a region, without having to say where to look first.
"""
import cv2
import numpy as np
from typing import Any, Dict

from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from apex_vision.core.registry import register_tool


@register_tool
class HoughDetectTool(VisionToolBase):
    category = "Location"
    tool_name = "Hough Detect"
    description = ("Finds circles or straight line segments in a region of the image. Use it when you do not know "
                   "where the feature is. The strongest circle / longest line is passed on as 'Circle' / 'Line'.")

    MODES = ["Circles", "Lines"]

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image (results are drawn on top)")
        self.outputs["Count"] = ToolPort("Count", DataType.VALUE, "How many were found")
        self.outputs["Circle"] = ToolPort("Circle", DataType.CIRCLE, "Strongest circle {cx, cy, r}")
        self.outputs["Line"] = ToolPort("Line", DataType.LINE, "Longest line {x1, y1, x2, y2}")
        self.outputs["Items"] = ToolPort("Items", DataType.ANY, "Every circle or line found")

    def _init_parameters(self):
        self.parameters = {
            "mode": "Circles",
            "roi": [0, 0, 640, 480],
            "min_radius": 10,           # Circles
            "max_radius": 200,
            "min_distance": 20,         # Circles: smallest gap between two centres
            "sensitivity": 30,          # Circles: lower finds more (and false) circles
            "line_threshold": 50,       # Lines: votes a line needs
            "min_line_length": 40,
            "max_line_gap": 10,
            "min_count": 1,             # fewer than this fails
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=8, min_h=8)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")
        x, y, w, h = self.get_roi("roi", [0, 0, 640, 480], img_shape=img.shape)
        gray = self.to_grayscale(img)[y:y + h, x:x + w]
        show = img if img.ndim == 3 and img.shape[2] == 3 else cv2.cvtColor(self.to_grayscale(img), cv2.COLOR_GRAY2BGR)
        mode = self.get_param("mode", "Circles")
        items, overlays = [], [{"type": "rect", "box": (x, y, w, h), "color": (120, 120, 120)}]
        try:
            if mode == "Lines":
                edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
                found = cv2.HoughLinesP(
                    edges, 1, np.pi / 180,
                    threshold=max(1, int(self.as_float(self.get_param("line_threshold", 50), 50))),
                    minLineLength=max(1, int(self.as_float(self.get_param("min_line_length", 40), 40))),
                    maxLineGap=max(0, int(self.as_float(self.get_param("max_line_gap", 10), 10))))
                for seg in (found.reshape(-1, 4) if found is not None else []):
                    x1, y1, x2, y2 = (float(seg[0]) + x, float(seg[1]) + y, float(seg[2]) + x, float(seg[3]) + y)
                    items.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "length": float(np.hypot(x2 - x1, y2 - y1))})
                items.sort(key=lambda d: d["length"], reverse=True)
                items = items[:200]
                for d in items:
                    overlays.append({"type": "line", "pt1": (int(d["x1"]), int(d["y1"])), "pt2": (int(d["x2"]), int(d["y2"])),
                                     "color": (0, 255, 0), "thickness": 2})
            else:
                min_r = max(0, int(self.as_float(self.get_param("min_radius", 10), 10)))
                max_r = max(min_r + 1, int(self.as_float(self.get_param("max_radius", 200), 200)))
                found = cv2.HoughCircles(
                    cv2.medianBlur(gray, 5), cv2.HOUGH_GRADIENT, dp=1.2,
                    minDist=max(1, self.as_float(self.get_param("min_distance", 20), 20)),
                    param1=100, param2=max(1, self.as_float(self.get_param("sensitivity", 30), 30)),
                    minRadius=min_r, maxRadius=max_r)
                for c in (found.reshape(-1, 3) if found is not None else [])[:200]:
                    items.append({"cx": float(c[0]) + x, "cy": float(c[1]) + y, "r": float(c[2])})
                for d in items:
                    overlays.append({"type": "circle", "center": (int(d["cx"]), int(d["cy"])), "radius": int(d["r"]),
                                     "color": (0, 255, 0)})
                    overlays.append({"type": "cross", "pt": (int(d["cx"]), int(d["cy"])), "size": 5, "color": (0, 255, 0)})
        except cv2.error as exc:
            return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Hough {mode.lower()} failed: {exc}")
        minimum = max(0, int(self.as_float(self.get_param("min_count", 1), 1)))
        ok = len(items) >= minimum
        outputs = {"Image": show, "Count": len(items), "Items": items}
        if items:
            if mode == "Lines":
                outputs["Line"] = {k: items[0][k] for k in ("x1", "y1", "x2", "y2", "length")}
            else:
                outputs["Circle"] = dict(items[0])
        return ToolExecutionResult(
            status=ToolStatus.OK if ok else ToolStatus.NG,
            message=f"Found {len(items)} {mode.lower()}" + ("" if ok else f" (need at least {minimum})"),
            outputs=outputs, overlays=overlays)
