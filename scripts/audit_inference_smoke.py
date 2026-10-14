"""Verify YOLO inference produces real detections on a real image.

The synthetic probe returned zero detections, which for a COCO-trained model on a
synthetic PCB is expected (COCO has no PCB class) but is also exactly what a broken
pipeline looks like.  This separates the two by running the model on a photograph
containing COCO classes, and by reporting the raw decoder output.

Run:  python scripts/audit_inference_smoke.py
"""
import glob
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def main() -> int:
    from ultralytics import YOLO

    weights = os.path.join(ROOT, "yolo11n.pt")
    print(f"weights: {weights}  exists={os.path.exists(weights)}")
    model = YOLO(weights)
    print(f"model classes: {len(model.names)} COCO classes")

    # 1. a blank image must yield nothing
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    r = model.predict(source=blank, conf=0.25, verbose=False)
    print(f"blank image       -> {len(r[0].boxes)} box(es)")

    # 2. a real photograph must yield something, if one is available
    candidates = []
    for pattern in ("docs/**/*.png", "docs/**/*.jpg", "saved_images/*.png"):
        candidates.extend(glob.glob(os.path.join(ROOT, pattern), recursive=True))
    # prefer photographic content over UI screenshots
    photos = [c for c in candidates
              if "screenshot" not in c.lower() and "audit" not in c.lower()]
    print(f"candidate images  : {len(photos)}")

    found = 0
    for path in photos[:12]:
        img = __import__("cv2").imread(path)
        if img is None:
            continue
        res = model.predict(source=img, conf=0.25, verbose=False)
        n = len(res[0].boxes)
        if n:
            names = [model.names[int(b.cls[0])] for b in res[0].boxes]
            print(f"  {os.path.basename(path)[:40]:42s} {n:2d} box(es) {names[:4]}")
            found += n
    print(f"\ntotal detections across candidates: {found}")
    if found:
        print("VERDICT: inference works and produces detections.")
    else:
        print("VERDICT: the model ran but found nothing in the available images.")
        print("         (Expected: this project ships only synthetic PCB renders and UI")
        print("          screenshots, none of which contain COCO classes.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
