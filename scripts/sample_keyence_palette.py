"""Measure the KEYENCE palette from the reference screenshots.

Samples named control regions of
`docs/references/keyence/ui_crops/cvx_window_a.png` (a 6x render of the CV-X
VisionEditor screen from the official manual) and writes the tokens to
`docs/references/keyence/tokens.json`, so the stylesheet is built from measured
pixels rather than from memory.

Run:  python scripts/sample_keyence_palette.py
"""
import json
import os
import sys
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "docs", "references", "keyence", "ui_crops")
OUT = os.path.join(ROOT, "docs", "references", "keyence", "tokens.json")

#: (label, crop box, how to reduce the region)
#: Boxes are in the coordinates of `cvx_window_a.png` (1200x780).
REGIONS: List[Tuple[str, Tuple[int, int, int, int], str]] = [
    ("window_bg",        (700, 640, 1000, 660),  "mode"),
    ("titlebar",         (560, 10, 1000, 45),    "mode"),
    ("menubar",          (10, 20, 480, 45),      "mode"),
    ("toolbar_bg",       (560, 95, 900, 125),    "mode"),
    ("button_face",      (600, 20, 640, 50),     "mode"),
    ("button_border",    (0, 0, 1, 1),           "skip"),
    ("tab_strip",        (10, 95, 530, 135),     "mode"),
    ("tab_selected",     (30, 100, 95, 130),     "mode"),
    ("tab_unselected",   (130, 100, 200, 130),   "mode"),
    ("viewport_bg",      (500, 700, 900, 760),   "mode"),
    ("viewport_roi",     (283, 178, 460, 200),   "skip"),
    ("group_border",     (185, 315, 430, 425),   "mode"),
    ("warning_bg",       (690, 85, 860, 125),    "mode"),
    ("warning_icon",     (700, 88, 730, 118),    "mode"),
    ("selected_yellow",  (222, 442, 285, 478),   "mode"),
    ("panel_label",      (196, 287, 400, 312),   "mode"),
    ("tooltip_bg",       (455, 310, 660, 390),   "mode"),
]


def quantify(im: Image.Image, box: Tuple[int, int, int, int], how: str) -> Dict:
    x0, y0, x1, y1 = box
    a = np.asarray(im.crop((x0, y0, x1, y1)).convert("RGB")).reshape(-1, 3)
    if not len(a):
        return {"hex": None, "share": 0.0}
    q = (a // 4) * 4
    cols, counts = np.unique(q, axis=0, return_counts=True)
    if how == "mean":
        m = a.mean(axis=0).astype(int)
        return {"hex": "#%02x%02x%02x" % tuple(m),
                "share": 1.0,
                "rgb": [int(v) for v in m]}
    order = np.argsort(-counts)
    rgb = cols[order[0]]
    return {"hex": "#%02x%02x%02x" % tuple(int(v) for v in rgb),
            "share": round(float(counts[order[0]] / counts.sum()), 3),
            "rgb": [int(v) for v in rgb]}


def luma(hexcol: str) -> float:
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return round(0.299 * r + 0.587 * g + 0.114 * b, 1)


def main() -> int:
    src = os.path.join(SRC, "cvx_window_a.png")
    if not os.path.exists(src):
        print(f"missing {src}")
        return 1
    im = Image.open(src).convert("RGB")
    print(f"sampling {os.path.basename(src)}  {im.size}\n")

    out: Dict[str, Dict] = {}
    print(f"{'region':20s} {'hex':9s} {'share':>6s} {'luma':>7s}")
    for label, box, how in REGIONS:
        if how == "skip":
            continue
        rec = quantify(im, box, how)
        rec["box"] = list(box)
        rec["luma"] = luma(rec["hex"])
        out[label] = rec
        print(f"{label:20s} {rec['hex']:9s} {rec['share']:6.2f} {rec['luma']:7.1f}")

    # The saturated accent colours are the most important tokens: find them by
    # saturation across the whole screenshot rather than by box.
    a = np.asarray(im, dtype=np.float32)
    sat = a.max(axis=2) - a.min(axis=2)
    bright = sat > 60
    if bright.any():
        q = ((a[bright] // 8) * 8).astype(int)
        cols, counts = np.unique(q, axis=0, return_counts=True)
        order = np.argsort(-counts)
        acc: List[Dict] = []
        for i in order[:14]:
            rgb = [int(v) for v in cols[i]]
            acc.append({"hex": "#%02x%02x%02x" % tuple(rgb),
                        "share": round(float(counts[i] / counts.sum()), 3),
                        "luma": luma("#%02x%02x%02x" % tuple(rgb))})
        out["_accents"] = acc
        print("\nmost common saturated colours (accents):")
        for rec in acc:
            print(f"  {rec['hex']}  share {rec['share']:.3f}  luma {rec['luma']}")

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
