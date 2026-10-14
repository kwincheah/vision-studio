"""Measure the KEYENCE chrome bands precisely and record the token delta.

The earlier sampling mixed a control face into the "toolbar" region.  This walks
each reference screenshot's row luminance to find the chrome band, then reports the
modal colour of that band alone - so the recorded delta between the applied chrome
and the measured chrome is meaningful.

Run:  python scripts/measure_chrome_bands.py
"""
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KEN = os.path.join(ROOT, "docs", "references", "keyence")
OUT = os.path.join(KEN, "chrome_bands.json")


def modal(im: Image.Image, box: Tuple[int, int, int, int]) -> Tuple[str, float]:
    x0, y0, x1, y1 = box
    a = np.asarray(im.convert("RGB").crop((x0, y0, x1, y1))).reshape(-1, 3)
    q = (a // 4) * 4
    cols, counts = np.unique(q, axis=0, return_counts=True)
    i = int(np.argmax(counts))
    c = cols[i]
    return "#%02x%02x%02x" % tuple(int(v) for v in c), float(counts[i] / counts.sum())


def bands(im: Image.Image, x: int, y0: int, y1: int, jump: float = 8.0
          ) -> List[Tuple[int, int, float]]:
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    L = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    prof = L[y0:y1, :].mean(axis=1)
    out, start = [], 0
    for i in range(1, len(prof)):
        if abs(float(prof[i]) - float(prof[i - 1])) >= jump:
            if i - start >= 6:
                out.append((y0 + start, y0 + i, float(prof[start:i].mean())))
            start = i
    if len(prof) - start >= 6:
        out.append((y0 + start, y0 + len(prof), float(prof[start:].mean())))
    return out


def main() -> int:
    report: Dict = {}

    xg = Image.open(os.path.join(KEN, "ui_crops", "xg_floweditor.png")).convert("RGB")
    print("XG FlowEditor chrome bands (rows 0..60):")
    for a, b, m in bands(xg, 0, 0, 60):
        col, share = modal(xg, (10, a, 1280, b))
        print(f"  y {a:4d}..{b:4d}  h {b - a:3d}  luma {m:6.1f}  {col}  share {share:.2f}")
        report.setdefault("xg_bands", []).append(
            {"y0": a, "y1": b, "luma": round(m, 1), "colour": col,
             "share": round(share, 3)})

    cv = Image.open(os.path.join(KEN, "ui_crops", "cvx_window_a.png")).convert("RGB")
    print("\nCV-X window chrome bands (rows 0..140):")
    for a, b, m in bands(cv, 0, 0, 140):
        col, share = modal(cv, (300, a, 900, b))
        print(f"  y {a:4d}..{b:4d}  h {b - a:3d}  luma {m:6.1f}  {col}  share {share:.2f}")
        report.setdefault("cvx_bands", []).append(
            {"y0": a, "y1": b, "luma": round(m, 1), "colour": col,
             "share": round(share, 3)})

    # Compare with what the application applies.
    sys.path.insert(0, ROOT)
    from vm_clone.ui.styles import THEME

    def dist(p: str, q: str) -> float:
        r1, g1, b1 = (int(p[i:i + 2], 16) for i in (1, 3, 5))
        r2, g2, b2 = (int(q[i:i + 2], 16) for i in (1, 3, 5))
        return round(((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5, 1)

    xg_toolbar = next((b["colour"] for b in report.get("xg_bands", [])
                       if b["y0"] < 30), None)
    cvx_menu = next((b["colour"] for b in report.get("cvx_bands", [])
                     if 10 <= b["y0"] < 40), None)

    print(f"\n{'applied token':16s} {'value':9s} {'measured':9s} {'dE':>7s}")
    rows = []
    for token, measured, label in (
        ("vm_chrome_dark", xg_toolbar, "XG toolbar strip"),
        ("vm_chrome", cvx_menu, "CV-X menu strip"),
    ):
        d = dist(THEME[token], measured) if measured else None
        rows.append({"token": token, "applied": THEME[token], "measured": measured,
                     "region": label, "distance": d})
        print(f"{token:16s} {THEME[token]:9s} {(measured or '-'):9s} "
              f"{(f'{d:.1f}' if d is not None else '-'):>7s}")
    report["delta"] = rows

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
