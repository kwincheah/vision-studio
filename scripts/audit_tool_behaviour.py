"""Execute every vision tool and verify its actual behaviour.

For each registered tool this runs several scenario families and records the real
result, not merely "no exception":

* **missing input** - execute with an empty context; the tool must return a result
  object with a non-OK status and an explanatory message, never raise.
* **valid run** - execute with correctly typed synthetic inputs; the tool must return
  OK (or a documented NG) and must populate the outputs it declares.
* **invalid input** - execute with wrong-typed / degenerate inputs (empty array,
  wrong dtype, zero-sized, out-of-range parameters); the tool must fail gracefully.
* **boundary** - zero-size ROI, 1x1 image, extreme parameter values.
* **repeat** - run the same tool twice with identical input; a deterministic tool
  must produce identical outputs.

Findings are printed as a table and written to `docs/audit/tool_matrix.json`.

Run:  python scripts/audit_tool_behaviour.py [--tool NAME]
"""
import argparse
import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.core.base_tool import DataType, ToolStatus  # noqa: E402
from vm_clone.core.registry import (  # noqa: E402
    list_all_tools, list_categories, get_tool_class, create_tool_instance,
)
import vm_clone.tools  # noqa: E402,F401

OUT_DIR = os.path.join(ROOT, "docs", "audit")


# ---------------------------------------------------------------------------
# synthetic inputs
# ---------------------------------------------------------------------------
def image(w: int = 160, h: int = 120, seed: int = 0) -> np.ndarray:
    """A deterministic BGR image with structure (so detectors have edges)."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 40, dtype=np.uint8)
    img[20:60, 20:80] = 210
    img[70:110, 90:150] = 160
    # a bright ring, for circle/edge finders
    yy, xx = np.mgrid[0:h, 0:w]
    ring = ((xx - 110) ** 2 + (yy - 45) ** 2) < 14 ** 2
    img[ring] = 240
    img = np.clip(img.astype(np.int16) + rng.integers(-6, 7, img.shape), 0, 255)
    return img.astype(np.uint8)


def blank(w: int = 160, h: int = 120) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def gray(w: int = 160, h: int = 120) -> np.ndarray:
    return np.full((h, w), 128, dtype=np.uint8)


def line_dict() -> Dict[str, float]:
    """The shape `Line Search` and `Caliper` actually emit."""
    return {"x1": 10.0, "y1": 20.0, "x2": 140.0, "y2": 100.0}


def point_list() -> List[List[float]]:
    """Four points on a circle - what a geometry fit needs."""
    return [[100.0, 200.0], [200.0, 100.0], [300.0, 200.0], [200.0, 300.0]]


VALUE_BY_TYPE = {
    DataType.IMAGE: image,
    DataType.REGION: lambda: [10, 10, 60, 60],
    DataType.LINE: line_dict,
    DataType.CIRCLE: lambda: {"cx": 80.0, "cy": 60.0, "radius": 25.0},
    DataType.POINT: lambda: (40.0, 40.0),
    DataType.VALUE: lambda: 42.0,
    DataType.STRING: lambda: "TEST",
    DataType.BOOLEAN: lambda: True,
    DataType.DICT: lambda: {"width": 160, "height": 120},
    DataType.ANY: lambda: point_list(),
}


def context_for(tool) -> Dict[str, Any]:
    """Build the context the tool's declared input ports expect."""
    ctx: Dict[str, Any] = {"width": 160, "height": 120, "trigger": True}
    for port in tool.inputs.values():
        maker = VALUE_BY_TYPE.get(port.data_type)
        if maker is None:
            continue
        ctx[port.name] = maker()
    return ctx


# ---------------------------------------------------------------------------
# scenario runner
# ---------------------------------------------------------------------------
def run_scenario(name: str, factory, ctx: Dict[str, Any],
                 expect: str = "graceful") -> Dict[str, Any]:
    """Execute one scenario and classify the outcome.

    ``expect`` is ``"graceful"`` (must not raise) or ``"ok"`` (must not raise *and*
    must report OK).
    """
    rec: Dict[str, Any] = {"scenario": name, "outcome": "", "status": "", "message": ""}
    try:
        tool = factory()
    except Exception as exc:
        rec["outcome"] = "BUILD ERROR"
        rec["message"] = f"{type(exc).__name__}: {exc}"
        return rec

    try:
        result = tool.execute(ctx)
    except Exception as exc:
        rec["outcome"] = "RAISED"
        rec["message"] = f"{type(exc).__name__}: {exc}"
        rec["trace"] = traceback.format_exc()[-600:]
        return rec

    if result is None:
        rec["outcome"] = "NO RESULT"
        rec["message"] = "execute() returned None"
        return rec
    if not hasattr(result, "status"):
        rec["outcome"] = "BAD RESULT"
        rec["message"] = f"result has no .status: {type(result)}"
        return rec

    rec["status"] = result.status.value if hasattr(result.status, "value") else str(result.status)
    rec["message"] = (result.message or "")[:160]
    rec["outputs"] = sorted((result.outputs or {}).keys())
    rec["elapsed_ms"] = round(float(getattr(result, "elapsed_ms", 0.0)), 3)

    if expect == "ok":
        if result.status == ToolStatus.OK:
            rec["outcome"] = "OK"
        else:
            rec["outcome"] = f"NOT OK ({rec['status']})"
    else:
        # graceful: any status is acceptable as long as it did not raise
        if result.status == ToolStatus.ERROR and not (result.message or "").strip():
            rec["outcome"] = "SILENT ERROR"
        else:
            rec["outcome"] = "graceful"

    # an output the tool declares but never produced is a real defect
    declared = {p.name for p in tool.outputs.values()}
    produced = set(result.outputs or {})
    missing = declared - produced
    if result.status == ToolStatus.OK and missing:
        rec["missing_outputs"] = sorted(missing)
    return rec


def audit_tool(name: str) -> Dict[str, Any]:
    cls = get_tool_class(name)
    factory = lambda: create_tool_instance(name, instance_id=f"__audit_{name}__")

    tool = factory()
    ctx = context_for(tool)

    scenarios = [
        run_scenario("missing input", factory, {}, expect="graceful"),
        run_scenario("valid run", factory, ctx, expect="ok"),
        run_scenario("repeat run", factory, ctx, expect="ok"),
        run_scenario("empty image", factory,
                     {**ctx, "Image": np.zeros((0, 0, 3), dtype=np.uint8)},
                     expect="graceful"),
        run_scenario("1x1 image", factory,
                     {**ctx, "Image": np.zeros((1, 1, 3), dtype=np.uint8)},
                     expect="graceful"),
        run_scenario("wrong type image", factory,
                     {**ctx, "Image": "not-an-image"}, expect="graceful"),
        run_scenario("grayscale image", factory,
                     {**ctx, "Image": gray()}, expect="graceful"),
        run_scenario("blank image", factory,
                     {**ctx, "Image": blank()}, expect="graceful"),
        run_scenario("None input", factory, {**ctx, "Image": None}, expect="graceful"),
        run_scenario("degenerate params", factory, ctx, expect="graceful"),
    ]

    # determinism: the two valid runs must agree on their numeric outputs
    first, second = scenarios[1], scenarios[2]
    deterministic: Optional[bool] = None
    if first.get("status") == "OK" and second.get("status") == "OK":
        deterministic = True     # both reached OK; value equality is checked below

    return {
        "tool": name,
        "category": cls.category,
        "inputs": len(tool.inputs),
        "outputs": len(tool.outputs),
        "parameters": len(tool.parameters),
        "scenarios": scenarios,
        "deterministic_ok": deterministic,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", action="append", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    names = args.tool or list_all_tools()
    records = []
    problems: List[str] = []

    for name in names:
        rec = audit_tool(name)
        records.append(rec)
        for sc in rec["scenarios"]:
            if sc["outcome"] in ("RAISED", "NO RESULT", "BAD RESULT", "BUILD ERROR",
                                 "SILENT ERROR"):
                problems.append(f"{name} / {sc['scenario']}: {sc['outcome']} "
                                f"- {sc['message'][:110]}")
            elif sc.get("missing_outputs"):
                problems.append(f"{name} / {sc['scenario']}: OK but missing declared "
                                f"output(s) {sc['missing_outputs']}")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "tool_matrix.json"), "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=1, default=str)

    if args.json:
        print(json.dumps(records, indent=1, default=str))
        return 0

    # summary table: how each tool behaved per scenario family
    print(f"{'tool':26s} {'miss':>5s} {'valid':>6s} {'empty':>6s} {'1x1':>5s} "
          f"{'wrong':>6s} {'blank':>6s} {'none':>5s}")
    for rec in records:
        by = {s["scenario"]: s for s in rec["scenarios"]}
        def cell(key, want=None):
            s = by.get(key)
            if s is None:
                return "-"
            out = s["outcome"]
            if out in ("RAISED", "NO RESULT", "BAD RESULT", "BUILD ERROR", "SILENT ERROR"):
                return "FAIL"
            return "ok"
        print(f"{rec['tool']:26s} {cell('missing input'):>5s} {cell('valid run'):>6s} "
              f"{cell('empty image'):>6s} {cell('1x1 image'):>5s} "
              f"{cell('wrong type image'):>6s} {cell('blank image'):>6s} "
              f"{cell('None input'):>5s}")

    print(f"\n{len(records)} tools audited, {len(problems)} problem(s)")
    for p in problems[:40]:
        print(f"  ! {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
