"""Measure the intensity separation between board materials and defect classes.

Tuning a detector by guessing at thresholds produced a detector that fired on the board
texture.  This prints the actual grey levels and local-residual depths, so the operating
point can be chosen from the data.

Run:  python scripts/audit_board_separation.py
"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.samples.pcb_defect_dataset import (  # noqa: E402
    board_layout, synth_board,
)


def stats(name, values):
    values = np.asarray(values, dtype=np.float32)
    if values.size == 0:
        print(f"  {name:16s} (none)")
        return
    print(f"  {name:16s} n={values.size:5d}  mean={values.mean():7.2f}  "
          f"p5={np.percentile(values, 5):7.2f}  p95={np.percentile(values, 95):7.2f}  "
          f"min={values.min():6.1f}  max={values.max():6.1f}")


def main() -> int:
    materials = {"substrate": [], "plane": [], "pad": []}
    residual = {"substrate": [], "plane": [], "pad": []}
    by_class = {}
    depths = {}

    n_boards = 12
    for i in range(n_boards):
        seed = 1000 + i * 7919
        img, anns = synth_board(seed, force_clean=False, allow_clean=False)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)
        background = cv2.medianBlur(blurred, 41)
        signed = background.astype(np.float32) - blurred.astype(np.float32)

        pads, traces = board_layout(seed)

        # sample material patches away from any annotation
        def clear_of_ann(x, y, w, h):
            for a in anns:
                ax, ay, aw, ah = a.box
                if not (x + w < ax or ax + aw < x or y + h < ay or ay + ah < y):
                    return False
            return True

        h, w = gray.shape
        rng = np.random.default_rng(i)
        for _ in range(300):
            x, y = int(rng.integers(60, w - 60)), int(rng.integers(60, h - 60))
            on_pad = any(px <= x <= px + pw and py <= y <= py + ph
                         for px, py, pw, ph in pads)
            on_trace = any(
                min(p0[0], p1[0]) - 4 <= x <= max(p0[0], p1[0]) + 4 and
                min(p0[1], p1[1]) - 4 <= y <= max(p0[1], p1[1]) + 4
                for p0, p1 in traces)
            inside_plane = 40 <= x <= w - 40 and 40 <= y <= h - 40
            if not clear_of_ann(x - 6, y - 6, 12, 12):
                continue
            key = "pad" if on_pad else ("substrate" if not inside_plane else "plane")
            if on_trace and key == "plane":
                continue
            materials[key].append(gray[y, x])
            residual[key].append(max(0.0, signed[y, x]))

        # depth of each annotated defect relative to its own surroundings
        for a in anns:
            x, y, bw, bh = (int(v) for v in a.box)
            region = signed[max(0, y):y + bh, max(0, x):x + bw]
            if region.size == 0:
                continue
            # a bright defect (scratch) is a *negative* residual
            depths.setdefault(a.label, []).append(float(region.max()))
            by_class.setdefault(a.label, []).append(float(region.min()))

    print("grey level by material (luma):")
    for k, v in materials.items():
        stats(k, v)

    print("\npositive (dark) local residual by material:")
    for k, v in residual.items():
        stats(k, v)

    print("\ndark-defect residual depth (max over the annotated box):")
    for k, v in sorted(depths.items()):
        stats(k, v)
    print("\nbright-defect residual depth (min over the annotated box, negative=bright):")
    for k, v in sorted(by_class.items()):
        stats(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
