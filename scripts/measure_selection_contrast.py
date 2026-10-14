"""Measure how the KEYENCE references distinguish selected from unselected states.

Contrast of a state fill against its own surround is the metric that matters for
"is this control visibly selected", and it is what the WCAG non-text rule (3:1) is
about.  Recording it lets the refinement be checked against the vendor's own
relationship instead of an arbitrary threshold.

Run:  python scripts/measure_selection_contrast.py
"""
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KEN = os.path.join(ROOT, "docs", "references", "keyence", "ui_crops")


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


def modal(im, box):
    x0, y0, x1, y1 = box
    a = np.asarray(im.convert("RGB").crop((x0, y0, x1, y1))).reshape(-1, 3)
    q = (a // 4) * 4
    cols, counts = np.unique(q, axis=0, return_counts=True)
    return cols[int(np.argmax(counts))]


def report(label, sel, unsel):
    c = contrast(sel, unsel)
    print(f"{label:34s} selected "
          f"#{int(sel[0]):02x}{int(sel[1]):02x}{int(sel[2]):02x}  vs unselected "
          f"#{int(unsel[0]):02x}{int(unsel[1]):02x}{int(unsel[2]):02x}"
          f"   contrast {c:5.2f}  {'3:1 ok' if c >= 3.0 else 'below 3:1'}")
    return c


def main() -> int:
    cv = Image.open(os.path.join(KEN, "cvx_window_a.png")).convert("RGB")
    xg = Image.open(os.path.join(KEN, "xg_floweditor.png")).convert("RGB")

    print("KEYENCE reference selection contrast:")
    # CV-X: the amber selected capture tab vs its neighbours.
    report("capture tab (selected vs not)",
           modal(cv, (222, 442, 285, 478)), modal(cv, (300, 442, 360, 478)))
    # XG: the amber selected unit node vs an unselected white node.
    report("unit node (selected vs not)",
           modal(xg, (50, 232, 280, 282)), modal(xg, (50, 145, 280, 195)))

    print("\nApplied application values:")
    sys.path.insert(0, ROOT)
    from vm_clone.ui.styles import THEME

    def hx(h):
        return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)

    for label, a, b in (
        ("flow tab selected vs unselected", THEME["accent_dim"], THEME["bg_surface"]),
        ("node selected vs unselected", THEME["accent_dim"], THEME["vm_node"]),
        ("amber accent vs canvas", THEME["vm_accent"], THEME["vm_canvas"]),
        ("amber border vs card", THEME["accent_border"], THEME["vm_node"]),
    ):
        c = contrast(hx(a), hx(b))
        print(f"{label:34s} #{a[1:]}  vs #{b[1:]}   contrast {c:5.2f}  "
              f"{'3:1 ok' if c >= 3.0 else 'below 3:1'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
