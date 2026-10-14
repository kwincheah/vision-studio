"""Execute the built-in solution end to end and report every node's real result.

This is the check that "a click did not raise" cannot give you: it prints each
module's status, timing, message and the actual output values, so a module that
silently produced nothing (or a verdict that contradicts its inputs) is visible.

Run:  python scripts/audit_flow_execution.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vm_clone.core.base_tool import ToolStatus  # noqa: E402
from vm_clone.samples.pcb_solution import create_pcb_inspection_solution  # noqa: E402

SEV = {
    ToolStatus.OK: "OK  ",
    ToolStatus.NG: "NG  ",
    ToolStatus.ERROR: "ERR ",
    ToolStatus.BYPASS: "BYP ",
    ToolStatus.TIMEOUT: "TMO ",
    ToolStatus.READY: "RDY ",
}


def main() -> int:
    pipeline = create_pcb_inspection_solution()
    print(f"sample flow: {pipeline.name!r}  modules: {len(pipeline.nodes)}  "
          f"connections: {len(pipeline.connections)}")

    results = pipeline.execute_flow()

    print(f"\n{'module':30s} {'status':5s} {'ms':>9s}  message / key outputs")
    problems = []
    for nid in pipeline.execution_order:
        node = pipeline.nodes.get(nid)
        res = results.get(nid)
        if node is None:
            continue
        if res is None:
            print(f"{node.name:30s} {'--':5s} {'-':>9s}  NOT EXECUTED")
            problems.append(f"{node.name}: not executed")
            continue
        msg = (res.message or "").replace("\n", " ")[:70]
        print(f"{node.name:30s} {SEV.get(res.status, '?'):5s} "
              f"{res.elapsed_ms:9.3f}  {msg}")
        if res.status == ToolStatus.ERROR:
            problems.append(f"{node.name}: ERROR - {res.message}")
        if res.status == ToolStatus.OK and not res.outputs:
            problems.append(f"{node.name}: OK but produced no outputs")

    # An OK verdict whose own message says it did not actually inspect anything is a
    # false pass - the defect an operator would never notice.
    print("\nverdict detail:")
    for nid in pipeline.execution_order:
        node = pipeline.nodes.get(nid)
        res = results.get(nid)
        if res is None or res.status != ToolStatus.OK:
            continue
        interesting = {k: v for k, v in (res.outputs or {}).items()
                       if not isinstance(v, np.ndarray)}
        if interesting:
            print(f"  {node.name:28s} {str(interesting)[:120]}")

    print(f"\n{len(problems)} problem(s)")
    for p in problems:
        print(f"  ! {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
