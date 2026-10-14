"""Build the KEYENCE refinement comparison sheet and measure the palette delta.

Places, at identical sizes:
  * the KEYENCE reference UI crop (the measured source), and
  * the application before and after the refinement,
then reports per-region colour deltas between the applied chrome and the measured
reference values, so the refinement is auditable rather than asserted.

Run:  python scripts/build_keyence_comparison.py
"""
import json
import os
import sys
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

SHOTS = os.path.join(ROOT, "docs", "screenshots")
AUDIT = os.path.join(SHOTS, "audit")
KEN = os.path.join(ROOT, "docs", "references", "keyence")
OUT_JSON = os.path.join(KEN, "palette_delta.json")


def modal(im: Image.Image, box: Tuple[int, int, int, int]) -> str:
    x0, y0, x1, y1 = box
    a = np.asarray(im.convert("RGB").crop((x0, y0, x1, y1))).reshape(-1, 3)
    q = (a // 4) * 4
    cols, counts = np.unique(q, axis=0, return_counts=True)
    c = cols[int(np.argmax(counts))]
    return "#%02x%02x%02x" % tuple(int(v) for v in c)


def dist(a: str, b: str) -> float:
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (1, 3, 5))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return round(((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5, 1)


def sheet(pairs: List[Tuple[str, str]], out_name: str, cell_h: int = 420) -> str:
    imgs = []
    for label, path in pairs:
        if not os.path.exists(path):
            print(f"  missing {path}")
            continue
        im = Image.open(path).convert("RGB")
        scale = cell_h / im.height
        imgs.append((label, im.resize((max(1, int(im.width * scale)), cell_h),
                                      Image.LANCZOS)))
    if not imgs:
        return ""
    cols = 2
    rows = (len(imgs) + cols - 1) // cols
    pad, label_h = 10, 20
    cell_w = max(im.width for _, im in imgs)
    width = cols * cell_w + (cols + 1) * pad
    height = rows * (cell_h + label_h) + (rows + 1) * pad
    canvas = Image.new("RGB", (width, height), (30, 30, 34))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("segoeui.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
    for idx, (label, im) in enumerate(imgs):
        r, c = divmod(idx, cols)
        x = pad + c * (cell_w + pad)
        y = pad + r * (cell_h + label_h + pad)
        draw.text((x, y), label, fill=(235, 235, 240), font=font)
        canvas.paste(im, (x, y + label_h))
    path = os.path.join(SHOTS, out_name)
    canvas.save(path)
    print(f"saved {path}  ({canvas.width}x{canvas.height})")
    return path


def main() -> int:
    # The KEYENCE reference screens (measured source)
    ref_window = os.path.join(KEN, "ui_crops", "cvx_window_a.png")
    ref_flow = os.path.join(KEN, "ui_crops", "xg_floweditor.png")

    pairs = [
        ("REFERENCE K2 — XG Flow Editor (KEYENCE manual): canvas / nodes / selection",
         ref_flow),
        ("AFTER — same workspace, KEYENCE-derived palette",
         os.path.join(AUDIT, "61_after_925x765.png")),
        ("REFERENCE K1 — CV-X window (KEYENCE manual): chrome / toolbars / panels",
         ref_window),
        ("BEFORE — previous dark-titanium palette",
         os.path.join(AUDIT, "60_before_925x765.png")),
        ("AFTER — KEYENCE-derived light palette, 925x765",
         os.path.join(AUDIT, "61_after_925x765.png")),
        ("AFTER — 1400x760 (resize check)",
         os.path.join(AUDIT, "61_after_1400x760.png")),
    ]
    sheet(pairs, "keyence_comparison.png")

    # Measured delta: application chrome vs the sampled reference values.
    from vm_clone.ui.styles import THEME
    ref = json.load(open(os.path.join(KEN, "tokens.json"), encoding="utf-8"))
    rows = []
    for token, region in (
        ("vm_chrome", "titlebar"),
        ("vm_chrome_dark", "toolbar_bg"),
        ("vm_canvas", None),
        ("vm_node", None),
        ("vm_accent", "selected_yellow"),
        ("vm_viewport", "viewport_bg"),
        ("vm_panel", "group_border"),
    ):
        measured = None
        if region and region in ref and isinstance(ref[region], dict):
            measured = ref[region].get("hex")
        rows.append({"token": token, "applied": THEME[token],
                     "reference_region": region, "reference": measured,
                     "distance": dist(THEME[token], measured) if measured else None})

    print(f"\n{'token':16s} {'applied':9s} {'reference':9s} {'dE':>7s}  region")
    for r in rows:
        d = f"{r['distance']:.1f}" if r["distance"] is not None else "-"
        print(f"{r['token']:16s} {r['applied']:9s} "
              f"{(r['reference'] or '-'):9s} {d:>7s}  {r['reference_region'] or ''}")

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump({"rows": rows}, fh, indent=1)
    print(f"\nwrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
