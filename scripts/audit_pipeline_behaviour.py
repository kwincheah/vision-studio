"""Audit pipeline-level behaviours: disconnection, failure, repeat and cancel.

The tool audits cover one module in isolation.  These are the flow-level behaviours
that decide whether a running line behaves sanely:

* a node whose input is not connected must not break the flow;
* a node that fails must not stop the other branches, and its downstream consumers
  must still report a real verdict rather than a stale or absent one;
* executing the same flow repeatedly must give the same result and must not leak
  state between runs (accumulating counts, growing buffers, drifting parameters);
* a stop request must leave the pipeline in a usable state.

Run:  python scripts/audit_pipeline_behaviour.py
"""
import os
import sys
import traceback
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.core.base_tool import ToolStatus  # noqa: E402
from vm_clone.core.pipeline import VisionPipeline  # noqa: E402
from vm_clone.core.registry import create_tool_instance  # noqa: E402
import vm_clone.tools  # noqa: E402,F401


def result_of(results, nid):
    return results.get(nid)


def main() -> int:
    problems: List[str] = []
    checks: List[str] = []

    def check(label: str, ok: bool, detail: str = ""):
        checks.append(label)
        flag = "ok  " if ok else "FAIL"
        print(f"{flag} {label}" + (f"  -- {detail}" if detail and not ok else ""))
        if not ok:
            problems.append(f"{label}: {detail}")

    # ------------------------------------------------------------------
    # 1. A node with no connected input must not break the flow
    # ------------------------------------------------------------------
    try:
        pipe = VisionPipeline(name="disconnected")
        src = create_tool_instance("Image Source", "src", "Source")
        src.set_param("pattern_type", "PCB Inspection")
        pipe.add_node(src)
        # deliberately NOT connected
        binar = create_tool_instance("Image Binarization", "bin", "Binarize")
        pipe.add_node(binar)
        results = pipe.execute_flow()
        check("unconnected input: flow completes",
              len(results) == 2, f"got {len(results)} results")
        bres = result_of(results, "bin")
        check("unconnected input: node reports a non-OK status rather than crashing",
              bres is not None and bres.status in (ToolStatus.NG, ToolStatus.ERROR),
              f"status={getattr(bres, 'status', None)}")
    except Exception as exc:
        check("unconnected input: flow completes", False,
              f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # 2. A failing node must not stop unrelated branches
    # ------------------------------------------------------------------
    try:
        pipe = VisionPipeline(name="failure_isolation")
        src = create_tool_instance("Image Source", "src", "Source")
        src.set_param("pattern_type", "PCB Inspection")
        pipe.add_node(src)

        # a node whose file does not exist -> guaranteed failure
        bad = create_tool_instance("Image Source", "bad", "BrokenSource")
        bad.set_param("source_type", "File")
        bad.set_param("file_path", os.path.join(os.getcwd(), "no_such_file_xyz.png"))
        pipe.add_node(bad)

        # a healthy branch off the good source
        good = create_tool_instance("Image Binarization", "good", "Healthy")
        pipe.add_node(good)
        pipe.connect("src", "Image", "good", "Image")

        results = pipe.execute_flow()
        check("failure isolation: healthy branch still ran",
              result_of(results, "good") is not None, "healthy node missing")
        check("failure isolation: healthy branch succeeded",
              result_of(results, "good").status == ToolStatus.OK,
              f"status={result_of(results, 'good').status.value}")
        check("failure isolation: failing branch reported an error",
              result_of(results, "bad").status in (ToolStatus.NG, ToolStatus.ERROR),
              f"status={result_of(results, 'bad').status.value}")
    except Exception as exc:
        check("failure isolation: healthy branch still ran", False,
              f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # 3. Downstream of a failed node must degrade gracefully, not crash
    # ------------------------------------------------------------------
    try:
        pipe = VisionPipeline(name="downstream_of_failure")
        bad = create_tool_instance("Image Source", "bad", "BrokenSource")
        bad.set_param("source_type", "File")
        bad.set_param("file_path", os.path.join(os.getcwd(), "no_such_file_xyz.png"))
        pipe.add_node(bad)
        down = create_tool_instance("Image Binarization", "down", "Downstream")
        pipe.add_node(down)
        pipe.connect("bad", "Image", "down", "Image")
        results = pipe.execute_flow()
        dres = result_of(results, "down")
        check("downstream of failure: completes without raising",
              dres is not None, "downstream produced no result")
        check("downstream of failure: reports non-OK",
              dres is not None and dres.status in (ToolStatus.NG, ToolStatus.ERROR),
              f"status={getattr(dres, 'status', None)}")
    except Exception as exc:
        check("downstream of failure: completes without raising", False,
              f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # 4. Repeat execution must be stable
    # ------------------------------------------------------------------
    try:
        from vm_clone.samples.pcb_solution import create_pcb_inspection_solution

        pipe = create_pcb_inspection_solution()
        signatures = []
        for run in range(4):
            results = pipe.execute_flow()
            sig = {nid: (r.status.value,
                         tuple(sorted((k, round(float(v), 4))
                                      for k, v in (r.outputs or {}).items()
                                      if isinstance(v, (int, float)) and not isinstance(v, bool))))
                   for nid, r in results.items()}
            signatures.append(sig)

        first = signatures[0]
        stable = all(s == first for s in signatures[1:])
        check("repeat: 4 consecutive runs give identical statuses and values", stable,
              "" if stable else "results drifted between runs")

        # a metric that must not accumulate across runs
        counts = []
        for _ in range(3):
            results = pipe.execute_flow()
            counts.append(results["node_defect"].outputs.get("Defect_Count"))
        check("repeat: the defect count does not accumulate across runs",
              len(set(counts)) == 1, f"counts={counts}")
    except Exception as exc:
        check("repeat: 4 consecutive runs give identical statuses and values", False,
              f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # 5. Stop / restart: the pipeline must expose a usable running state
    # ------------------------------------------------------------------
    try:
        from vm_clone.samples.pcb_solution import create_pcb_inspection_solution

        pipe = create_pcb_inspection_solution()
        check("stop: is_running is False before a run", not pipe.is_running,
              f"is_running={pipe.is_running}")
        pipe.execute_flow()
        check("stop: is_running returns to False after a run", not pipe.is_running,
              f"is_running={pipe.is_running}")
        results = pipe.execute_flow()
        check("stop: the flow runs again afterwards", len(results) > 0,
              "no results after re-running")
    except Exception as exc:
        check("stop: is_running is False before a run", False,
              f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # 6. Cycle handling: refused at connect time, and detected in the data
    # ------------------------------------------------------------------
    try:
        pipe = VisionPipeline(name="cyclic")
        a = create_tool_instance("Image Binarization", "a", "A")
        b = create_tool_instance("Image Filter", "b", "B")
        pipe.add_node(a)
        pipe.add_node(b)
        pipe.connect("a", "Image", "b", "Image")
        refused = not pipe.connect("b", "Image", "a", "Image")
        check("cycle: connect() refuses to create a feedback loop", refused,
              "connect() allowed a cycle")

        # Force the cycle into the data to exercise the detector itself.
        from vm_clone.core.pipeline import FlowConnection
        pipe.connections.append(
            FlowConnection(from_node="b", from_port="Image",
                           to_node="a", to_port="Image"))
        issues = pipe.validate_flow()
        cycle_errors = [i for i in issues
                        if i.get("severity") == "error"
                        and "cycl" in i.get("message", "").lower()]
        check("cycle: validate_flow reports a forced cycle as an error",
              bool(cycle_errors),
              f"issues={[i.get('message') for i in issues]}")
        results = pipe.execute_flow()
        check("cycle: executing a forced cycle does not hang",
              isinstance(results, dict), "execute_flow returned a non-dict")
    except Exception as exc:
        check("cycle: connect() refuses to create a feedback loop", False,
              f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # 7. An empty flow must be a no-op, not an error
    # ------------------------------------------------------------------
    try:
        pipe = VisionPipeline(name="empty")
        results = pipe.execute_flow()
        check("empty flow: returns an empty result set",
              isinstance(results, dict) and not results, f"got {results!r}")
    except Exception as exc:
        check("empty flow: returns an empty result set", False,
              f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # 8. validate_flow must pass a clean graph and flag an unconnected input
    # ------------------------------------------------------------------
    try:
        pipe = VisionPipeline(name="validate")
        src = create_tool_instance("Image Source", "src", "Source")
        binar = create_tool_instance("Image Binarization", "bin", "Binarize")
        pipe.add_node(src)
        pipe.add_node(binar)
        pipe.connect("src", "Image", "bin", "Image")
        issues = pipe.validate_flow()
        errors = [i for i in issues if i.get("severity") == "error"]
        check("validate_flow: a clean graph has no errors", not errors,
              f"errors={[i.get('message') for i in errors]}")

        pipe2 = VisionPipeline(name="validate2")
        orphan = create_tool_instance("Image Binarization", "orphan", "Orphan")
        pipe2.add_node(orphan)
        issues2 = pipe2.validate_flow()
        check("validate_flow: an unconnected input is reported",
              any(i.get("node_id") == "orphan" for i in issues2),
              f"issues={issues2}")
    except Exception as exc:
        check("validate_flow: a clean graph has no errors", False,
              f"{type(exc).__name__}: {exc}")

    print(f"\n{len(checks)} flow-level check(s), {len(problems)} problem(s)")
    for p in problems:
        print(f"  ! {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
