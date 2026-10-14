"""Inspect one board's dark blobs: geometry and depth, against its ground truth.

The aggregate numbers say `missing_paste` collects ~12 false positives per board, so
something systematic is firing.  This prints every blob's measured features next to the
ground truth, which identifies the cause directly instead of by guesswork.

Run:  python scripts/audit_dark_blobs.py
"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.evaluation import iou  # noqa: E402
from vm_clone.samples.pcb_defect_dataset import (  # noqa: E402
    board_layout, synth_board,
)


def blobs(gray, cutoff):
    blurred = cv2.medianBlur(gray, 5)
    background = cv2.medianBlur(blurred, 41)
    signed = background.astype(np.float32) - blurred.astype(np.float32)
    darker = np.clip(signed, 0, 255)
    mask = (darker > cutoff).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, _labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    return signed, stats, n


def main() -> int:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    img, anns = synth_board(seed, allow_clean=False, force_clean=False)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    pads, traces = board_layout(seed)

    blurred = cv2.medianBlur(gray, 5)
    background = cv2.medianBlur(blurred, 41)
    signed = background.astype(np.float32) - blurred.astype(np.float32)
    positive = np.clip(signed, 0, 255)
    pos = positive[positive > 0]
    median = float(np.median(pos))
    mad = float(np.median(np.abs(pos - median)))
    sigma = max(1.0, 1.4826 * mad)
    cutoff = max(30.0, 4.0 * sigma)
    print(f"seed={seed}  sigma={sigma:.2f}  cutoff={cutoff:.1f}")
    print(f"ground truth: {[(a.label, tuple(int(v) for v in a.box)) for a in anns]}")
    print(f"pads: {pads[:3]} ... ({len(pads)} total)")

    _signed, stats, n = blobs(gray, cutoff)
    print(f"\n{n - 1} dark blob(s) at this cutoff:")
    print(f"  {'x,y,w,h':<22}{'area':>6}{'fill':>7}{'asp':>6}{'depth':>7}"
          f"  {'on_pad':<7}{'matches GT':<26}{'iou':>6}")
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        region = signed[y:y + h, x:x + w]
        depth = float(region.max()) if region.size else 0.0
        fill = area / float(max(1, w * h))
        aspect = w / float(max(1, h))
        cx, cy = x + w / 2.0, y + h / 2.0
        on_pad = any(px <= cx <= px + pw and py <= cy <= py + ph
                     for px, py, pw, ph in pads)
        label, best = "-", 0.0
        for a in anns:
            v = iou((x, y, w, h), a.box)
            if v > best:
                best, label = v, a.label
        print(f"  [{x:4d},{y:4d},{w:4d},{h:4d}]{area:>6}{fill:>7.2f}{aspect:>6.2f}"
              f"{depth:>7.1f}  {str(on_pad):<7}{label + (f' @{best:.2f}' if best else ''):<26}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
