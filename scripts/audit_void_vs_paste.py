"""Measure the blob features that distinguish `void` from `missing_paste`.

Both are dark blobs on a pad.  The classifier needs one threshold on a feature that
actually separates them, so this prints that feature's distribution per class rather
than leaving the choice to guesswork.

Run:  python scripts/audit_void_vs_paste.py
"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.evaluation import iou  # noqa: E402
from vm_clone.samples.pcb_defect_dataset import (  # noqa: E402
    DETECTOR_VARIANTS, board_layout, synth_board, trace_boxes,
)

FEATURES = ("fill", "aspect", "depth", "area", "min_dim")


def features_of(signed, x, y, w, h, cutoff):
    region = signed[y:y + h, x:x + w]
    area = int((region > cutoff).sum())
    depth = float(region.max()) if region.size else 0.0
    return {
        "fill": area / float(max(1, w * h)),
        "aspect": w / float(max(1, h)),
        "depth": depth,
        "area": float(area),
        "min_dim": float(min(w, h)),
    }


def main() -> int:
    params = dict(DETECTOR_VARIANTS["reference"])
    cutoff = float(params["dark_floor"])

    by_class = {}
    n_boards = 60
    for i in range(n_boards):
        seed = 5000 + i * 7919
        img, anns = synth_board(seed, allow_clean=False, force_clean=False)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)
        background = cv2.medianBlur(blurred, 41)
        signed = background.astype(np.float32) - blurred.astype(np.float32)

        for a in anns:
            if a.label not in ("void", "missing_paste"):
                continue
            x, y, w, h = (int(round(v)) for v in a.box)
            f = features_of(signed, x, y, w, h, cutoff)
            by_class.setdefault(a.label, []).append(f)

    for name, rows in sorted(by_class.items()):
        print(f"\n{name}  (n={len(rows)})")
        for feature in FEATURES:
            values = np.array([r[feature] for r in rows], dtype=np.float32)
            print(f"   {feature:9s} min={values.min():8.3f}  p25={np.percentile(values, 25):8.3f}"
                  f"  median={np.median(values):8.3f}  p75={np.percentile(values, 75):8.3f}"
                  f"  max={values.max():8.3f}")

    # Which single threshold on each feature separates them best?
    print("\nbest single-threshold separation:")
    for feature in FEATURES:
        v = np.array([r[feature] for r in by_class.get("void", [])], dtype=np.float32)
        p = np.array([r[feature] for r in by_class.get("missing_paste", [])],
                     dtype=np.float32)
        if v.size == 0 or p.size == 0:
            continue
        candidates = np.unique(np.concatenate([v, p]))
        best = (0.0, 0.0)
        for t in candidates:
            # void above t, paste at or below
            acc = ((v > t).sum() + (p <= t).sum()) / float(v.size + p.size)
            if acc > best[0]:
                best = (acc, float(t))
        print(f"   {feature:9s} best accuracy {best[0]:.3f} at threshold {best[1]:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
