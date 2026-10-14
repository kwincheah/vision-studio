"""Measure the KEYENCE reference's own text/background contrast.

Before changing a surface to fix contrast, check what the reference actually does:
splitting the menu strip's pixels into ink and fill (by luminance) and computing the
contrast between them shows whether the vendor's label is light-on-mid-grey or
dark-on-mid-grey.  That decides whether the fix is a darker fill or darker ink.

Run:  python scripts/measure_reference_contrast.py
"""
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KEN = os.path.join(ROOT, "docs", "references", "keyence", "ui_crops")

AA = 4.5


def _srgb(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(rgb):
    r, g, b = (float(v) for v in rgb[:3])
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def analyse(im, box, label):
    x0, y0, x1, y1 = box
    a = np.asarray(im.convert("RGB").crop((x0, y0, x1, y1)), dtype=np.float32)
    L = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    flat = L.reshape(-1)
    # Split into the fill (modal luminance band) and the ink (the rest).
    hist, edges = np.histogram(flat, bins=32)
    fill_bin = int(np.argmax(hist))
    fill_mask = (L >= edges[fill_bin]) & (L < edges[fill_bin + 1])
    fill = a[fill_mask].mean(axis=0) if fill_mask.any() else a.reshape(-1, 3).mean(axis=0)
    ink_mask = ~fill_mask
    if not ink_mask.any():
        print(f"{label:26s} no distinct ink found")
        return None
    ink_px = a[ink_mask]
    ink_l = L[ink_mask]
    # The most extreme luminance is the actual glyph colour.
    idx = int(np.argmin(ink_l)) if fill.mean() > 128 else int(np.argmax(ink_l))
    ink = ink_px[idx]
    c = contrast(ink, fill)
    print(f"{label:26s} fill #{int(fill[0]):02x}{int(fill[1]):02x}{int(fill[2]):02x}"
          f"  ink #{int(ink[0]):02x}{int(ink[1]):02x}{int(ink[2]):02x}"
          f"  contrast {c:5.2f}  {'AA ok' if c >= AA else 'below AA'}")
    return {"label": label, "fill": [int(v) for v in fill], "ink": [int(v) for v in ink],
            "contrast": c}


def analyse_edges(im, box, label):
    """Contrast between a component edge and its surround (non-text UI)."""
    a = np.asarray(im.convert("RGB").crop(box), dtype=np.float32)
    L = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    lo, hi = np.percentile(L, 2), np.percentile(L, 98)
    lo_px = a[L <= lo].mean(axis=0)
    hi_px = a[L >= hi].mean(axis=0)
    c = contrast(lo_px, hi_px)
    print(f"{label:26s} dark #{int(lo_px[0]):02x}{int(lo_px[1]):02x}{int(lo_px[2]):02x}"
          f"  light #{int(hi_px[0]):02x}{int(hi_px[1]):02x}{int(hi_px[2]):02x}"
          f"  contrast {c:5.2f}  {'3:1 ok' if c >= 3.0 else 'below 3:1'}")
    return c


def main() -> int:
    cv = Image.open(os.path.join(KEN, "cvx_window_a.png")).convert("RGB")
    print(f"CV-X window {cv.size}")
    analyse(cv, (400, 12, 930, 58), "menu strip labels")
    analyse(cv, (10, 20, 340, 55), "title / solution name")
    analyse(cv, (560, 95, 900, 130), "toolbar area")
    analyse(cv, (185, 315, 430, 430), "panel group box")

    print("\ncomponent edges:")
    analyse_edges(cv, (185, 315, 430, 425), "group box border")
    analyse_edges(cv, (300, 100, 520, 132), "tab strip edge")
    analyse_edges(cv, (95, 20, 140, 52), "button face vs chrome")

    xg = Image.open(os.path.join(KEN, "xg_floweditor.png")).convert("RGB")
    print(f"\nXG FlowEditor {xg.size}")
    analyse(xg, (560, 2, 1080, 40), "toolbar button labels")
    analyse(xg, (10, 0, 300, 36), "solution name on toolbar")
    analyse(xg, (0, 850, 760, 894), "status bar labels")

    print("\ncomponent edges:")
    analyse_edges(xg, (30, 130, 320, 210), "unit node vs canvas")
    analyse_edges(xg, (30, 220, 320, 295), "selected node vs canvas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
