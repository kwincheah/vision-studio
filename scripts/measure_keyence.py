"""Find and measure KEYENCE UI screenshots inside the manuals.

Two jobs:

1. Rank rendered pages by how much of the page is a full-colour UI screenshot
   (dark viewport + coloured chrome), so the reference screens are found without
   reading 700-page manuals by hand.
2. Measure the palette from the actual screenshot pixels, and write the tokens to
   JSON so the theme is built from measurements rather than guesses.

Run:  python scripts/measure_keyence.py
"""
import json
import os
import sys
from collections import Counter
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "docs", "references", "keyence")
PAGES = os.path.join(SRC, "pages")
CROPS = os.path.join(SRC, "ui_crops")
OUT = os.path.join(SRC, "palette.json")


def ui_score(im: Image.Image) -> float:
    """How much of the page looks like a colour UI screenshot."""
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    L = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    sat = a.max(axis=2) - a.min(axis=2)
    # A UI screenshot contains a large near-black region (the image viewport) and
    # saturated blue chrome; a manual page is white with grey text.
    dark = (L < 90).mean()
    blue = ((a[:, :, 2] > a[:, :, 0] + 28) & (a[:, :, 2] > 90)).mean()
    return float(dark * 1.4 + blue * 2.2)


def tile_scores(im: Image.Image, grid: int = 6) -> List[Tuple[float, int, int]]:
    """Score each grid tile so a screenshot region can be located on a page."""
    w, h = im.size
    out = []
    for r in range(grid):
        for c in range(grid):
            box = (c * w // grid, r * h // grid, (c + 1) * w // grid, (r + 1) * h // grid)
            out.append((ui_score(im.crop(box)), r, c))
    return out


def dominant(im: Image.Image, k: int = 12, min_share: float = 0.004
             ) -> List[Tuple[str, float]]:
    """Most common quantised colours and their share of the region."""
    a = np.asarray(im.convert("RGB"))
    q = (a // 8) * 8
    flat = q.reshape(-1, 3)
    counts = Counter(map(tuple, flat))
    total = len(flat)
    out = []
    for rgb, n in counts.most_common(400):
        share = n / total
        if share < min_share:
            break
        out.append(("#%02x%02x%02x" % rgb, round(share, 4)))
        if len(out) >= k:
            break
    return out


def luma(hexcol: str) -> float:
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return round(0.299 * r + 0.587 * g + 0.114 * b, 1)


def main() -> int:
    os.makedirs(CROPS, exist_ok=True)
    files = sorted(f for f in os.listdir(PAGES) if f.lower().endswith(".png"))
    print(f"{len(files)} rendered pages")

    ranked = []
    for name in files:
        im = Image.open(os.path.join(PAGES, name)).convert("RGB")
        ranked.append((ui_score(im), name, im))
    ranked.sort(reverse=True, key=lambda t: t[0])

    print(f"\n{'page':50s} {'score':>7s}")
    for s, name, _im in ranked[:18]:
        print(f"{name:50s} {s:7.3f}")

    # Crop the densest UI region from the top pages.
    report: Dict = {"pages": [], "crops": []}
    for s, name, im in ranked[:6]:
        tiles = sorted(tile_scores(im), reverse=True)
        best = tiles[0]
        # Expand the best tile into a 2x2-tile window.
        r, c = best[1], best[2]
        w, h = im.size
        box = (max(0, (c - 1) * w // 6), max(0, (r - 1) * h // 6),
               min(w, (c + 2) * w // 6), min(h, (r + 2) * h // 6))
        crop = im.crop(box)
        out = os.path.join(CROPS, f"ui_{os.path.splitext(name)[0]}.png")
        crop.save(out)
        report["pages"].append({"page": name, "score": round(s, 3),
                                "box": box, "crop": out})
        report["crops"].append({
            "crop": os.path.basename(out),
            "size": list(crop.size),
            "colours": dominant(crop),
        })
        print(f"\n  crop {os.path.basename(out)}  {crop.size}  box={box}")
        for col, share in dominant(crop, k=10):
            print(f"    {col}  share {share:.3f}  luma {luma(col)}")

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
