"""Determine whether YOLO inference is genuinely available in this environment.

The evaluation platform is only meaningful if the inference node really produces
detections.  A node that raises and returns an empty result "without crashing" would
make every metric vacuously zero, so this checks the dependency, the weights, and a real
prediction, and reports which of those is missing.

Run:  python scripts/audit_inference_availability.py
"""
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.core.base_tool import ToolStatus  # noqa: E402
from vm_clone.core.registry import create_tool_instance  # noqa: E402
import vm_clone.tools  # noqa: E402,F401


def main() -> int:
    print("=== dependency ===")
    try:
        import ultralytics
        print(f"  ultralytics {ultralytics.__version__}")
    except ImportError as exc:
        print(f"  ultralytics NOT INSTALLED ({exc})")
        print("\n  -> YOLO inference is unavailable; the node returns ERROR for every image.")
        print("     Any detection metric computed through it would be vacuously zero.")

    print("\n=== weights on disk ===")
    for name in ("yolo11n.pt", "yolov8n.pt", "yolo11s.pt"):
        found = []
        for base in (ROOT, os.getcwd(), os.path.join(os.path.expanduser("~"), ".cache")):
            candidate = os.path.join(base, name)
            if os.path.exists(candidate):
                found.append(candidate)
        print(f"  {name:14s} {'found: ' + found[0] if found else 'not found'}")

    print("\n=== node behaviour on a synthetic PCB-like image ===")
    img = np.full((480, 640, 3), 40, dtype=np.uint8)
    img[180:260, 220:380] = 210
    img[300:340, 120:200] = 190
    tool = create_tool_instance("Object Detection", "__probe__")
    result = tool.execute({"Image": img})
    print(f"  status : {result.status.value}")
    print(f"  message: {result.message[:110]}")
    outputs = result.outputs or {}
    for key in ("Count", "Detections", "Classes", "Scores", "Boxes"):
        value = outputs.get(key)
        if isinstance(value, list):
            print(f"  {key:12s} list[{len(value)}]")
        else:
            print(f"  {key:12s} {value!r}")

    print("\n=== verdict ===")
    if result.status == ToolStatus.ERROR:
        print("  Inference is NOT available here. The platform must be built so that a")
        print("  *deterministic* detector can stand in for a trained model, and any metric")
        print("  must record which detector produced it.")
    elif result.status == ToolStatus.OK and outputs.get("Count", 0) > 0:
        print("  Inference works and returned detections.")
    else:
        print("  Inference returned no detections for this input (may be legitimate).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
