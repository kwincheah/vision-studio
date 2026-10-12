"""Frame-by-frame (分镜) geometry measurement of the VisionMaster references.

Every number used by the layout comes from here.  The tool locates the app window
inside each vendor figure, then measures the structural bands and column splits
with luminance profiling, and finally prints the derived layout ratios.

Run:  python scripts/measure_storyboard.py            # print + write JSON
"""
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXT = os.path.join(ROOT, "docs", "references", "external")
FIGS = os.path.join(ROOT, "docs", "references", "figs")
OUT_JSON = os.path.join(EXT, "storyboard_geometry.json")

RIGHT = os.path.join(EXT, "ui_crops", "right_column_zoom.png")
MAP = os.path.join(EXT, "ui_crops", "main_interface_map.png")
HOME = os.path.join(FIGS, "p040_01.png")


def luma(im: Image.Image) -> np.ndarray:
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    return 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]


def runs_of(profile: np.ndarray, offset: int, jump: float = 16.0,
            min_len: int = 8) -> List[Tuple[int, int, float]]:
    out: List[Tuple[int, int, float]] = []
    start = 0
    for i in range(1, len(profile)):
        if abs(float(profile[i]) - float(profile[i - 1])) >= jump:
            if i - start >= min_len:
                out.append((offset + start, offset + i, float(profile[start:i].mean())))
            start = i
    if len(profile) - start >= min_len:
        out.append((offset + start, offset + len(profile),
                    float(profile[start:].mean())))
    return out


def show(title: str, rows: List[Tuple[int, int, float]], total: int,
         unit: str) -> List[Dict]:
    print(f"\n  {title}   (extent {total} px)")
    out = []
    for a, b, m in rows:
        size = b - a
        rec = {"start": a, "end": b, "size": size,
               "ratio": round(size / total, 4), "luma": round(m, 1)}
        out.append(rec)
        print(f"     {unit} {a:5d}..{b:5d}   size {size:5d}   "
              f"ratio {size / total:6.4f}   luma {m:6.1f}")
    return out


def measure_right_column() -> Dict:
    """The 2x right-column crop: window 79..1388 vertically, 0..~1409 wide."""
    im = Image.open(RIGHT).convert("RGB")
    L = luma(im)
    w, h = im.size
    print(f"\n{'=' * 78}\nRIGHT COLUMN  {w}x{h}  (aspect {w / h:.4f})\n{'=' * 78}")

    # Window box: rows/cols that contain any dark pixel.
    dark = L < 120
    rows = np.where(dark.mean(axis=1) > 0.06)[0]
    cols = np.where(dark.mean(axis=0) > 0.06)[0]
    y0, y1 = int(rows[0]), int(rows[-1])
    x0, x1 = int(cols[0]), int(cols[-1])
    H = y1 - y0 + 1
    W = x1 - x0 + 1
    print(f"  window box: x {x0}..{x1} ({W})  y {y0}..{y1} ({H})  "
          f"aspect {W / H:.4f}")

    # Vertical bands down a column that crosses the whole stack (x = 25 %).
    px = x0 + int(W * 0.25)
    prof = L[y0:y1 + 1, px - 2:px + 3].mean(axis=1)
    rows_bands = runs_of(prof, y0, jump=14.0, min_len=8)

    # Horizontal split of the result table (a row inside it).
    ty = y0 + int(H * 0.90)
    hprof = L[ty, x0:x1 + 1]
    col_bands = runs_of(hprof, x0, jump=20.0, min_len=10)

    return {
        "image": [w, h],
        "window": [x0, y0, x1, y1],
        "window_size": [W, H],
        "aspect": round(W / H, 4),
        "vertical": show("vertical bands (full column)", rows_bands, H, "y"),
        "horizontal_table_row": show("horizontal bands (result table row)",
                                     col_bands, W, "x"),
    }


def measure_main_map() -> Dict:
    """The main-interface map: canvas vs right panel split."""
    im = Image.open(MAP).convert("RGB")
    L = luma(im)
    w, h = im.size
    print(f"\n{'=' * 78}\nMAIN INTERFACE MAP  {w}x{h}  (aspect {w / h:.4f})\n{'=' * 78}")

    dark = L < 110
    rows = np.where(dark.mean(axis=1) > 0.25)[0]
    cols = np.where(dark.mean(axis=0) > 0.25)[0]
    y0, y1 = int(rows[0]), int(rows[-1])
    x0, x1 = int(cols[0]), int(cols[-1])
    # The annotation lines sit right of the window; the window's own right edge is
    # the last column with a strong vertical dark run above 60 % dark.
    strong = np.where(dark.mean(axis=0) > 0.55)[0]
    if len(strong):
        x1 = int(strong[-1])
    W, H = x1 - x0 + 1, y1 - y0 + 1
    print(f"  window box: x {x0}..{x1} ({W})  y {y0}..{y1} ({H})  "
          f"aspect {W / H:.4f}")

    mid = L[y0:y1 + 1, x0 + W // 2]
    rows_bands = runs_of(mid, y0, jump=12.0, min_len=6)

    # Column split: average the luminance over a tall canvas band so text and
    # cards average out and only the panel boundaries remain.
    band = L[y0 + int(H * 0.50): y0 + int(H * 0.90), x0:x1 + 1].mean(axis=0)
    col_bands = runs_of(band, x0, jump=5.0, min_len=14)

    return {
        "image": [w, h],
        "window": [x0, y0, x1, y1],
        "window_size": [W, H],
        "aspect": round(W / H, 4),
        "vertical": show("vertical bands (window centre)", rows_bands, H, "y"),
        "horizontal_wide_band": show("horizontal bands (canvas region average)",
                                     col_bands, W, "x"),
    }


def main() -> int:
    results = {
        "right_column": measure_right_column(),
        "main_map": measure_main_map(),
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)
    print(f"\nwrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
