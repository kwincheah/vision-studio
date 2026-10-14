"""Measure the reference detector variants against the synthetic dataset.

The honest feedback loop: it reports what the detector actually achieves, so the
demonstration is built on measured numbers.  It also runs a **threshold sweep**, which
is what an engineer does before trusting a detector, and prints the trade-off curve
rather than a single flattering operating point.

Run:  python scripts/audit_reference_detector.py [count]
"""
import os
import sys
import tempfile
from collections import Counter

import cv2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.evaluation import evaluate_records, render_text_report  # noqa: E402
from vm_clone.samples.pcb_defect_dataset import (  # noqa: E402
    DETECTOR_VARIANTS, board_layout, build_dataset, detections_to_records,
    reference_pcb_detector, trace_boxes,
)


def run_dataset(ds, variant: str, **overrides):
    """Predict and evaluate one variant over the whole dataset."""
    base = dict(DETECTOR_VARIANTS[variant])
    base.update(overrides)
    for record in ds:
        image = cv2.imread(ds.resolve(record))
        if image is None:
            record.predictions = []
            continue
        seed = int(record.meta.get("seed", 0))
        size = (record.size[0], record.size[1]) if record.size else (640, 480)
        pads, _ = board_layout(seed, size)
        traces = trace_boxes(seed, size)
        dets = reference_pcb_detector(image, pad_boxes=pads, trace_boxes=traces, **base)
        record.predictions = detections_to_records(
            dets, model_id=f"reference_pcb_detector[{variant}]")
    return evaluate_records(list(ds), dataset_name=ds.name, split="test")


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    tmp = tempfile.mkdtemp(prefix="vm_det_audit_")
    ds = build_dataset(tmp, count=count)
    print(f"dataset: {ds.name}  {ds.counts()}")
    print(f"classes: {ds.label_set()}\n")

    results = {}
    for variant in ("reference", "conservative"):
        result = run_dataset(ds, variant)
        results[variant] = result
        print(render_text_report(result))
        print()

    # Per-class confusion for the primary variant, so a systematic misclassification is
    # visible rather than buried in the aggregate.
    primary = results["reference"]
    print("per-class confusion for 'reference' (predicted -> annotated):")
    confusion = Counter()
    for r in primary.per_image:
        for item in r.false_positives:
            confusion[(item.prediction.label, item.nearest_label or "-")] += 1
        for item in r.false_negatives:
            confusion[("-", item.annotation.label)] += 1
    for (pred, truth), n in confusion.most_common(10):
        print(f"   predicted {pred:14s} vs truth {truth:14s} x{n}")

    print("\nthreshold sweep on 'reference' (dark_floor, min_area -> P / R / F1):")
    for floor in (30, 55, 80):
        for area in (60, 110):
            res = run_dataset(ds, "reference", dark_floor=floor, min_area=area)
            def f(v):
                return "  n/a" if v is None else f"{v:.3f}"
            print(f"   floor={floor:<4} area={area:<4} "
                  f"TP={res.tp:<4} FP={res.fp:<4} FN={res.fn:<4} "
                  f"P={f(res.precision)} R={f(res.recall)} F1={f(res.f1)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
