"""Test the hand-off contracts between tools.

A tool passing its own unit test proves nothing about a pipeline: the failures that
matter happen at the *boundary*, when an upstream tool returns a degraded value (a
detector finding nothing and emitting `None`) and the downstream tool assumes a
well-formed shape.

For every input port this feeds each of a set of adversarial-but-realistic values and
requires a graceful result.  Anything that raises, or that reports OK while producing
nothing, is a defect.

Run:  python scripts/audit_tool_contracts.py
"""
import json
import os
import sys
import traceback
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.core.base_tool import DataType, ToolStatus  # noqa: E402
from vm_clone.core.registry import (  # noqa: E402
    list_all_tools, get_tool_class, create_tool_instance,
)
import vm_clone.tools  # noqa: E402,F401

OUT_DIR = os.path.join(ROOT, "docs", "audit")

#: adversarial values per port type - "what a real upstream tool might emit"
ADVERSARIAL: Dict[DataType, List[Any]] = {
    DataType.IMAGE: [
        None,
        "path/to/none.png",
        np.zeros((0, 0, 3), dtype=np.uint8),
        np.zeros((1, 1), dtype=np.uint8),
        np.zeros((120, 160), dtype=np.uint8),
        np.zeros((120, 160, 5), dtype=np.float64),
        np.zeros((120, 160, 3), dtype=np.uint8),
    ],
    DataType.LINE: [
        None,
        {},
        {"x1": 1, "y1": 2},                       # partial dict
        {"x1": 1, "y1": 2, "x2": 3, "y2": 4},     # correct
        [(1.0, 2.0), (3.0, 4.0)],                 # pair-of-points form
        [1.0, 2.0, 3.0, 4.0],
        [1, 2, 3],                                # too short
        "garbage",
    ],
    DataType.CIRCLE: [
        None, {}, {"cx": 1.0, "cy": 2.0}, {"cx": 1.0, "cy": 2.0, "radius": 3.0},
        (1.0, 2.0, 3.0), [1.0, 2.0], "garbage",
    ],
    DataType.POINT: [
        None, (), (1.0,), (1.0, 2.0), [1.0, 2.0], {"x": 1, "y": 2}, "garbage",
    ],
    DataType.REGION: [
        None, [], [0, 0, 0, 0], [0, 0, 1, 1], [10, 10, 60, 60],
        [9999, 9999, 60, 60], [-50, -50, 60, 60], "garbage",
    ],
    DataType.VALUE: [
        None, 0, -1, 1e12, float("nan"), float("inf"), "42", "abc", [], {},
    ],
    DataType.STRING: [None, "", 0, "TEST", [], {}],
    DataType.BOOLEAN: [None, False, True, 0, 1, "true", []],
    DataType.DICT: [None, {}, {"width": 160}, {"width": 160, "height": 120}, [], 0],
    DataType.ANY: [None, [], {}, 0, "x", [[1, 2], [3, 4], [5, 6]]],
}


def base_context(tool) -> Dict[str, Any]:
    """A context in which the tool would otherwise succeed."""
    from scripts.audit_tool_behaviour import image, line_dict, point_list

    ctx: Dict[str, Any] = {"width": 160, "height": 120, "trigger": True}
    for port in tool.inputs.values():
        if port.data_type == DataType.IMAGE:
            ctx[port.name] = image()
        elif port.data_type == DataType.LINE:
            ctx[port.name] = line_dict()
        elif port.data_type == DataType.POINT:
            ctx[port.name] = (40.0, 40.0)
        elif port.data_type == DataType.REGION:
            ctx[port.name] = [10, 10, 60, 60]
        elif port.data_type == DataType.CIRCLE:
            ctx[port.name] = {"cx": 80.0, "cy": 60.0, "radius": 25.0}
        elif port.data_type == DataType.VALUE:
            ctx[port.name] = 42.0
        elif port.data_type == DataType.STRING:
            ctx[port.name] = "TEST"
        elif port.data_type == DataType.BOOLEAN:
            ctx[port.name] = True
        elif port.data_type == DataType.DICT:
            ctx[port.name] = {"width": 160, "height": 120}
        else:
            ctx[port.name] = point_list()
    return ctx


def main() -> int:
    names = list_all_tools()
    failures: List[Dict[str, Any]] = []
    tested = 0

    for name in names:
        try:
            tool = create_tool_instance(name, instance_id=f"__contract_{name}__")
        except Exception:
            continue
        base = base_context(tool)

        for port in tool.inputs.values():
            values = ADVERSARIAL.get(port.data_type, [None])
            for value in values:
                tested += 1
                ctx = dict(base)
                ctx[port.name] = value
                # also drop the port entirely: an unconnected upstream node
                dropped = dict(base)
                dropped.pop(port.name, None)

                for label, use in (("value", ctx), ("unconnected", dropped)):
                    try:
                        probe = create_tool_instance(
                            name, instance_id=f"__contract_{name}__")
                        result = probe.execute(use)
                    except Exception as exc:
                        failures.append({
                            "tool": name, "port": port.name, "type": port.data_type.value,
                            "case": label, "value": repr(value)[:60],
                            "outcome": "RAISED",
                            "detail": f"{type(exc).__name__}: {exc}",
                            "trace": traceback.format_exc()[-400:],
                        })
                        continue
                    if result is None:
                        failures.append({
                            "tool": name, "port": port.name, "type": port.data_type.value,
                            "case": label, "value": repr(value)[:60],
                            "outcome": "NO RESULT", "detail": "",
                        })
                        continue
                    if result.status == ToolStatus.OK and not (result.outputs or {}):
                        failures.append({
                            "tool": name, "port": port.name, "type": port.data_type.value,
                            "case": label, "value": repr(value)[:60],
                            "outcome": "OK WITH NO OUTPUTS",
                            "detail": (result.message or "")[:80],
                        })

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "contract_matrix.json"), "w", encoding="utf-8") as fh:
        json.dump(failures, fh, indent=1, default=str)

    print(f"{tested} adversarial port values x 40 tools = "
          f"{tested * 2} executions")
    if not failures:
        print("no contract violation: every tool handled every degraded input")
        return 0

    # group by tool+port so the report is readable
    grouped: Dict[str, List[Dict]] = {}
    for f in failures:
        grouped.setdefault(f"{f['tool']}  [{f['port']}:{f['type']}]", []).append(f)

    print(f"\n{len(failures)} violation(s) across {len(grouped)} port(s):\n")
    for key in sorted(grouped):
        items = grouped[key]
        kinds = sorted({i["outcome"] for i in items})
        print(f"  {key:52s} {len(items):3d} x {','.join(kinds)}")
        for i in items[:3]:
            print(f"        {i['case']:12s} {i['value'][:38]:40s} {i['detail'][:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
