"""Draw module result overlays (boxes, circles, lines, crosses, text) onto an image with OpenCV.

The widget canvas paints overlays itself with QPainter; this is the same drawing for front ends
that display a plain image (the QML viewer), including the layer switches of the Operation
Interface.
"""
from typing import Any, Dict, Iterable, Optional

import cv2
import numpy as np

#: layer switches (all default on except the histogram HUD)
DEFAULT_LAYERS: Dict[str, bool] = {
    "overlays": True,      # master switch
    "rois": True,          # rectangles / defect boxes
    "metrics": True,       # circles, lines and text labels
    "datums": True,        # crosses
    "crosshair": False,    # image-centre reticle
    "histogram": False,    # intensity histogram HUD
    "pixelgrid": False,    # measuring grid, one line every 50 px (100 px on big images)
}


def _bgr(colour: Any, fallback=(0, 200, 90)):
    try:
        b, g, r = (int(colour[0]), int(colour[1]), int(colour[2]))
        return (b, g, r)
    except (TypeError, ValueError, IndexError):
        return fallback


def _label(img: np.ndarray, text: str, x: int, y: int, colour) -> None:
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
    (w, h), base = cv2.getTextSize(text, font, scale, thick)
    y = max(h + 2, y)
    cv2.rectangle(img, (x - 2, y - h - 3), (x + w + 3, y + base), (32, 24, 20), -1)
    cv2.putText(img, text, (x, y), font, scale, colour, thick, cv2.LINE_AA)


def render_overlays(image: Optional[np.ndarray], overlays: Iterable[Dict[str, Any]],
                    layers: Optional[Dict[str, bool]] = None) -> Optional[np.ndarray]:
    """A copy of ``image`` (BGR) with the overlays that the layer switches allow."""
    if not isinstance(image, np.ndarray) or image.ndim not in (2, 3):      # e.g. a list wired into an Image input
        return None
    layers = {**DEFAULT_LAYERS, **(layers or {})}
    out = image.copy()
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    h, w = out.shape[:2]

    if layers["overlays"]:
        for item in overlays or []:
            kind = item.get("type")
            if kind == "rect" and not layers["rois"]:
                continue
            if kind in ("circle", "line", "text", "sector") and not layers["metrics"]:
                continue
            if kind == "cross" and not layers["datums"]:
                continue
            col = _bgr(item.get("color"))
            try:
                alpha = item.get("alpha")
                if alpha is not None and kind in ("rect", "circle") and 0.0 < float(alpha) < 1.0:     # a see-through filled shape
                    tint = out.copy()
                    if kind == "rect":
                        x, y, bw, bh = [int(v) for v in item.get("box", (0, 0, 0, 0))[:4]]
                        cv2.rectangle(tint, (x, y), (x + bw, y + bh), col, -1)
                    else:
                        cv2.circle(tint, tuple(int(v) for v in item.get("center", (0, 0))), int(item.get("radius", 10)), col, -1)
                    out = cv2.addWeighted(tint, float(alpha), out, 1.0 - float(alpha), 0)
                if kind == "sector":
                    cx, cy = [int(v) for v in item.get("center", (0, 0))]
                    r_in, r_out = int(item.get("r_in", 0)), int(item.get("r_out", 10))
                    a0, a1 = float(item.get("start", 0)), float(item.get("end", 360))
                    for rr in (r_in, r_out):
                        if rr > 0:
                            cv2.ellipse(out, (cx, cy), (rr, rr), 0, a0, a1, col, 2, cv2.LINE_AA)
                    for a in (a0, a1):
                        ca, sa = np.cos(np.radians(a)), np.sin(np.radians(a))
                        cv2.line(out, (int(cx + r_in * ca), int(cy + r_in * sa)), (int(cx + r_out * ca), int(cy + r_out * sa)), col, 2, cv2.LINE_AA)
                    if item.get("label"):
                        _label(out, str(item["label"]), cx + r_out + 4, cy, col)
                elif kind == "rect":
                    x, y, bw, bh = [int(v) for v in item.get("box", (0, 0, 0, 0))[:4]]
                    cv2.rectangle(out, (x, y), (x + bw, y + bh), col, 2)
                    if item.get("label"):
                        _label(out, str(item["label"]), x, y - 4, col)
                elif kind == "circle":
                    cx, cy = [int(v) for v in item.get("center", (0, 0))]
                    r = int(item.get("radius", 10))
                    cv2.circle(out, (cx, cy), r, col, 2, cv2.LINE_AA)
                    if item.get("label"):
                        _label(out, str(item["label"]), cx + r + 4, cy + 4, col)
                elif kind == "line":
                    p1 = tuple(int(v) for v in item.get("pt1", (0, 0)))
                    p2 = tuple(int(v) for v in item.get("pt2", (0, 0)))
                    cv2.line(out, p1, p2, col, int(item.get("thickness", 2)), cv2.LINE_AA)
                elif kind == "cross":
                    px, py = [int(v) for v in item.get("pt", (0, 0))]
                    s = int(item.get("size", 8))
                    cv2.line(out, (px - s, py), (px + s, py), col, 2, cv2.LINE_AA)
                    cv2.line(out, (px, py - s), (px, py + s), col, 2, cv2.LINE_AA)
                elif kind == "text":
                    px, py = [int(v) for v in item.get("pt", (10, 20))]
                    _label(out, str(item.get("text", "")), px, py, col)
            except (TypeError, ValueError):
                continue                    # a malformed overlay never stops the image from showing

    if layers["crosshair"]:
        cv2.line(out, (w // 2, 0), (w // 2, h), (140, 116, 100), 1, cv2.LINE_AA)
        cv2.line(out, (0, h // 2), (w, h // 2), (140, 116, 100), 1, cv2.LINE_AA)

    if layers["pixelgrid"]:
        step = 50 if max(w, h) <= 1000 else 100
        for gx in range(step, w, step):
            cv2.line(out, (gx, 0), (gx, h), (150, 150, 150), 1)
        for gy in range(step, h, step):
            cv2.line(out, (0, gy), (w, gy), (150, 150, 150), 1)

    if layers["histogram"]:
        gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [64], [0, 256]).flatten()
        hist = hist / max(1.0, float(hist.max()))
        hw, hh = min(190, w // 2), min(84, h // 2)
        x0, y0 = w - hw - 8, h - hh - 8
        cv2.rectangle(out, (x0, y0), (x0 + hw, y0 + hh), (34, 25, 22), -1)
        for i, v in enumerate(hist):
            bx = x0 + 4 + int(i * (hw - 8) / 64)
            cv2.line(out, (bx, y0 + hh - 4), (bx, y0 + hh - 4 - int(v * (hh - 12))), (226, 144, 74), 2)
        cv2.putText(out, "Histogram", (x0 + 6, y0 + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (188, 172, 160), 1, cv2.LINE_AA)
    return out
