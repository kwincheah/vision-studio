"""Trains the three small demo models shipped in apex_vision/samples/models (classifier, segmenter, anomaly) from synthetic parts.

    python scripts/make_demo_models.py

They only understand the synthetic 'Metal Surface (demo)' parts and exist so the Deep Learning modules can be tried without training
anything. For real parts train your own: python main.py train --help. Needs torch and onnx.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from apex_vision import dl_train  # noqa: E402
from apex_vision.samples import demo_parts as dp  # noqa: E402

OUT = os.path.join(ROOT, "apex_vision", "samples", "models")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    work = tempfile.mkdtemp(prefix="apex_demo_models_")
    rng = np.random.default_rng(2026)
    try:
        # classification: good / scratch / blotch
        for cls in ("good", "scratch", "blotch"):
            os.makedirs(os.path.join(work, "cls", cls))
        for i in range(240):
            img = dp.surface(rng)
            kind = ("good", "scratch", "blotch")[i % 3]
            img = dp.add_scratch(img, rng) if kind == "scratch" else dp.add_blotch(img, rng) if kind == "blotch" else img
            cv2.imwrite(os.path.join(work, "cls", kind, f"{i}.png"), img)
        dl_train.train_classifier(os.path.join(work, "cls"), os.path.join(OUT, "demo_defect_classifier.onnx"), epochs=25, size=64)

        # segmentation: scratches and blotches are the defect class
        os.makedirs(os.path.join(work, "seg", "images"))
        os.makedirs(os.path.join(work, "seg", "masks"))
        for i in range(220):
            img, mask = dp.surface(rng), np.zeros((dp.SIZE, dp.SIZE), np.uint8)
            if i % 6:
                img = dp.add_scratch(img, rng, mask) if i % 2 else dp.add_blotch(img, rng, mask)
            cv2.imwrite(os.path.join(work, "seg", "images", f"{i}.png"), img)
            cv2.imwrite(os.path.join(work, "seg", "masks", f"{i}.png"), mask)
        dl_train.train_segmenter(os.path.join(work, "seg"), os.path.join(OUT, "demo_defect_segmenter.onnx"), epochs=60, size=96,
                                 labels=["background", "defect"])

        # anomaly: good parts only
        os.makedirs(os.path.join(work, "good"))
        for i in range(80):
            cv2.imwrite(os.path.join(work, "good", f"{i}.png"), dp.surface(rng))
        dl_train.train_anomaly(os.path.join(work, "good"), os.path.join(OUT, "demo_anomaly.onnx"), epochs=120, size=128)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for f in sorted(os.listdir(OUT)):
        print(f"{os.path.getsize(os.path.join(OUT, f)) / 1024:7.0f} KB  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
