"""Find which dataset images produce the reference detector's false positives.

The blob inspector showed one clean board behaving correctly, so the false positives
must come from a specific image or a specific blob geometry.  This counts the false
positives by their measured features, which identifies the pattern instead of guessing.

Run:  python scripts/audit_detector_fps.py
"""
import os
import sys
import tempfile
from collections import Counter

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.evaluation import evaluate_records, iou  # noqa: E402
from vm_clone.samples.pcb_defect_dataset import (  # noqa: E402
    DETECTOR_VARIANTS, board_layout, build_dataset, detections_to_records,
    reference_pcb_detector, trace_boxes,
)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="vm_fp_audit_")
    ds = build_dataset(tmp, count=40)
    params = dict(DETECTOR_VARIANTS["reference"])

    feature_counts = Counter()
    per_image = Counter()
    worst = None

    for record in ds:
        image = cv2.imread(ds.resolve(record))
        if image is None:
            continue
        seed = int(record.meta.get("seed", 0))
        size = (record.size[0], record.size[1]) if record.size else (640, 480)
        pads, _ = board_layout(seed, size)
        traces = trace_boxes(seed, size)
        dets = reference_pcb_detector(image, pad_boxes=pads, trace_boxes=traces,
                                      **params)
        record.predictions = detections_to_records(dets)

    result = evaluate_records(list(ds), dataset_name=ds.name)
    for r in result.per_image:
        n = len(r.false_positives) + len(r.duplicates)
        if n:
            per_image[r.image] += n
        for item in r.false_positives + r.duplicates:
            x, y, w, h = (int(v) for v in item.prediction.box)
            gray = cv2.cvtColor(cv2.imread(ds.resolve(
                next(rec for rec in ds if rec.image_path == r.image))),
                cv2.COLOR_BGR2GRAY)
            blurred = cv2.medianBlur(gray, 5)
            background = cv2.medianBlur(blurred, 41)
            signed = background.astype(np.float32) - blurred.astype(np.float32)
            region = signed[y:y + h, x:x + w]
            depth = float(region.max()) if region.size else 0.0
            region_area = w * h
            fill = (region_area and
                    float((region > 30).sum()) / region_area) or 0.0
            feature_counts[
                (item.prediction.label,
                 f"aspect{round(w / max(1, h), 1)}",
                 f"size{'S' if region_area < 200 else 'M' if region_area < 800 else 'L'}",
                 f"depth{'shallow' if depth < 60 else 'mid' if depth < 100 else 'deep'}",
                 f"fill{round(fill, 1)}",
                 f"iou{round(item.best_iou, 1)}")
            ] += 1
            if worst is None or depth > worst[0]:
                worst = (depth, r.image, x, y, w, h, item.prediction.label,
                         item.reason_code)

    print(f"total FP: {result.fp}   TP: {result.tp}   FN: {result.fn}")
    print(f"images with FPs: {len(per_image)} of {len(ds)}")
    print("\ntop images:")
    for name, n in per_image.most_common(5):
        print(f"   {n:4d}  {name}")
    print("\nFP feature combinations:")
    for key, n in feature_counts.most_common(10):
        print(f"   {n:4d}  {key}")
    if worst:
        print(f"\ndeepest FP: depth={worst[0]:.0f} in {worst[1]} "
              f"box=({worst[2]},{worst[3]},{worst[4]},{worst[5]}) "
              f"label={worst[6]} reason={worst[7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
