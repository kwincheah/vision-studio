"""A region of interest for modules that work on the whole picture.

``add_roi(ToolClass)`` gives a module an ``roi`` setting ``[x, y, w, h]`` (all zero = the whole image, so existing flows are unchanged).
With a region set the module sees only that part of the picture; an image it produces is put back into a copy of the full picture
(outside the region stays as it was), masks are padded with zeros, and drawn results are moved to where the region lies.
The region is drawn by dragging on the image view, like every other ROI.
"""
from typing import Any, Dict, Tuple

import cv2
import numpy as np

_POINT_KEYS = ("pt", "pt1", "pt2", "center")


def region(value: Any, shape: Tuple[int, ...]) -> Tuple[int, int, int, int]:
    """The ``(x, y, w, h)`` of an ROI setting inside an image of ``shape``; w and h are 0 when no region is set (or it misses the image)."""
    try:
        x, y, w, h = [int(round(float(v))) for v in value[:4]]
    except (TypeError, ValueError, IndexError):
        return 0, 0, 0, 0
    if w <= 0 or h <= 0:
        return 0, 0, 0, 0
    ih, iw = shape[:2]
    x0, y0 = max(0, min(x, iw)), max(0, min(y, ih))
    x1, y1 = max(x0, min(x + w, iw)), max(y0, min(y + h, ih))
    return x0, y0, x1 - x0, y1 - y0


def _shift(item: Dict[str, Any], dx: int, dy: int) -> Dict[str, Any]:
    out = dict(item)
    for key in _POINT_KEYS:
        if key in out and isinstance(out[key], (list, tuple)) and len(out[key]) >= 2:
            out[key] = (out[key][0] + dx, out[key][1] + dy)
    if "box" in out and isinstance(out["box"], (list, tuple)) and len(out["box"]) >= 4:
        out["box"] = (out["box"][0] + dx, out["box"][1] + dy, *out["box"][2:])
    return out


def _put_back(full: np.ndarray, part: np.ndarray, x: int, y: int) -> np.ndarray:
    """``full`` with ``part`` placed at (x, y); the two may differ in colour channels."""
    if part.ndim != full.ndim:
        full = cv2.cvtColor(full, cv2.COLOR_GRAY2BGR) if part.ndim == 3 else cv2.cvtColor(full, cv2.COLOR_BGR2GRAY)
    elif part.ndim == 3 and part.shape[2] != full.shape[2]:
        full = full[:, :, :1].repeat(part.shape[2], axis=2) if part.shape[2] > full.shape[2] else full[:, :, :part.shape[2]]
    out = full.copy()
    out[y:y + part.shape[0], x:x + part.shape[1]] = part.astype(out.dtype, copy=False)
    return out


def add_roi(cls):
    """Give ``cls`` an ``roi`` setting and make its ``execute`` honour it. Safe to apply once per class."""
    if getattr(cls, "_has_roi_support", False):
        return cls
    init, run = cls._init_parameters, cls.execute

    def _init_parameters(self):
        init(self)
        self.parameters.setdefault("roi", [0, 0, 0, 0])            # all zero: the whole image

    def execute(self, context: Dict[str, Any]):
        img = context.get("Image")
        if not isinstance(img, np.ndarray) or img.ndim < 2:
            return run(self, context)
        x, y, w, h = region(self.get_param("roi"), img.shape)
        if w == 0 or h == 0:
            return run(self, context)
        sub = dict(context)
        sub["Image"] = img[y:y + h, x:x + w].copy()
        res = run(self, sub)
        for key, val in list(res.outputs.items()):
            if isinstance(val, np.ndarray) and val.ndim >= 2 and val.shape[:2] == (h, w):
                if key == "Image":
                    res.outputs[key] = _put_back(img, val, x, y)
                else:                                              # a mask or map: zero outside the region
                    res.outputs[key] = _put_back(np.zeros(img.shape[:2] + val.shape[2:], val.dtype), val, x, y)
        res.overlays = [_shift(o, x, y) if isinstance(o, dict) else o for o in (res.overlays or [])]
        return res

    cls._init_parameters, cls.execute, cls._has_roi_support = _init_parameters, execute, True
    return cls


#: modules whose region setting used to start as a box that only suited the built-in test picture. They now start empty
#: (all zero = the whole image) so a new module works on any picture until a region is drawn.
WHOLE_IMAGE_DEFAULTS = {
    "Affine Transformation": ("roi",), "Box Overlap": ("box1", "box2"), "Color Measurement": ("roi",), "Copy Fill": ("roi",),
    "Defect Contrast": ("roi",), "Defect Detection": ("roi",), "Edge Intersection": ("roi1", "roi2"),
    "Edge Pair Trend Analysis": ("roi",), "Edge Position Trend Analysis": ("roi",), "Ellipse Search": ("roi",),
    "Focus Measure": ("roi",), "Histogram": ("roi",), "Hough Detect": ("roi",), "Image Crop": ("roi",),
    "Intensity Measure": ("roi",), "Inverse Affine Transformation": ("roi",), "Matrix Circle Search": ("roi",),
    "OCR Recognition": ("roi",), "OCV": ("roi",), "Parallel Lines Search": ("roi",), "Peak Search": ("roi",),
    "Pixel Count": ("roi",), "Rect Search": ("roi",), "Target Tracking": ("roi",), "Template Match": ("template_roi",),
}


def start_with_whole_image(cls, keys):
    """Make ``cls`` start with an empty region for each of ``keys``. Safe to apply once per class."""
    if getattr(cls, "_starts_whole_image", False):
        return cls
    init = cls._init_parameters

    def _init_parameters(self):
        init(self)
        for key in keys:
            if key in self.parameters:
                self.parameters[key] = [0, 0, 0, 0]

    cls._init_parameters, cls._starts_whole_image = _init_parameters, True
    return cls
