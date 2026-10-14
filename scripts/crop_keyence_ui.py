"""Render KEYENCE manual pages at high resolution and crop the UI screens.

The manuals embed the screenshots as vector/CMYK composites, so a page render is
the only way to see them - but at scale 6 the chrome, buttons and status bar are
sharp enough to sample exact colours and measure control sizes.

Run:  python scripts/crop_keyence_ui.py
"""
import os
import sys
from typing import Dict, List, Tuple

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "docs", "references", "keyence")
OUT = os.path.join(SRC, "ui_crops")

SCALE = 6.0

#: (manual, page, crop box in *page points*) for the screens worth studying.
#: Page-point boxes were located from the 2.4x renders (divide those pixels by 2.4).
TARGETS: List[Tuple[str, int, str, Tuple[float, float, float, float]]] = [
    # CV-X: full application window with toolbar, viewport, parameter panel.
    ("CV-X100_200_User_Manual.pdf", 43, "cvx_full_window",
     (0, 0, 0, 0)),          # box resolved automatically below
    ("CV-X100_200_User_Manual.pdf", 21, "cvx_main_screen",
     (0, 0, 0, 0)),
    ("CV-X100_200_User_Manual.pdf", 50, "cvx_tool_catalog",
     (0, 0, 0, 0)),
    ("CV-X100_200_User_Manual.pdf", 506, "cvx_result_screen",
     (0, 0, 0, 0)),
]


def find_window_box(page, scale: float = 2.4) -> Tuple[int, int, int, int]:
    """Bounding box, in rendered pixels at `scale`, of the darkest wide region."""
    img = page.render(scale=scale).to_pil().convert("RGB")
    a = np.asarray(img, dtype=np.float32)
    L = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    dark = L < 70
    rows = np.where(dark.mean(axis=1) > 0.20)[0]
    cols = np.where(dark.mean(axis=0) > 0.20)[0]
    if not len(rows) or not len(cols):
        return (0, 0, img.width, img.height)
    # Grow the box generously: the chrome around the dark viewport is light.
    x0, x1 = int(cols[0]), int(cols[-1])
    y0, y1 = int(rows[0]), int(rows[-1])
    pad_x, pad_y = 60, 90
    return (max(0, x0 - pad_x), max(0, y0 - pad_y),
            min(img.width, x1 + pad_x), min(img.height, y1 + pad_y))


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    made: List[str] = []

    for name, page_no, label, box in TARGETS:
        path = os.path.join(SRC, name)
        if not os.path.exists(path):
            print(f"missing {name}")
            continue
        pdf = pdfium.PdfDocument(path)
        page = pdf[page_no - 1]

        if box == (0, 0, 0, 0):
            px = find_window_box(page, scale=2.4)
        else:
            px = tuple(int(v * 2.4) for v in box)

        # Render at SCALE and convert the 2.4x box into 6x coordinates.
        k = SCALE / 2.4
        img = page.render(scale=SCALE).to_pil().convert("RGB")
        big_box = (int(px[0] * k), int(px[1] * k), int(px[2] * k), int(px[3] * k))
        big_box = (max(0, big_box[0]), max(0, big_box[1]),
                   min(img.width, big_box[2]), min(img.height, big_box[3]))
        crop = img.crop(big_box)
        out = os.path.join(OUT, f"{label}.png")
        crop.save(out)
        made.append(out)
        print(f"{label:20s} {name} p{page_no}  -> {crop.size}  box={big_box}")
        pdf.close()

    print(f"\n{len(made)} crops in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
