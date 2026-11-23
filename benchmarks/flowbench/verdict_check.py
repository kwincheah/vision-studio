"""Run a flow spec on labelled images and report the flow verdict for each (grader helper).

Runs with Vision Studio's Python. Every Image Source is switched to the given file; side-effect modules are off.
Usage: python verdict_check.py <spec.json> <image> [<image> ...]   ->  JSON {image: "OK" | "NG" | "Error" | ...}
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from apex_vision.core.base_tool import ToolStatus  # noqa: E402
from apex_vision.flowgen.api import SIDE_EFFECT_TOOLS  # noqa: E402
from apex_vision.flowgen.spec import build_flow  # noqa: E402


def verdict(spec, image):
    pipe, _ = build_flow(spec)
    if pipe is None:
        return "Invalid"
    for tool in pipe.nodes.values():
        if tool.tool_name in SIDE_EFFECT_TOOLS:
            tool.enabled = False
        if tool.tool_name == "Image Source":
            tool.parameters["source_type"] = "File"
            tool.parameters["file_path"] = image
    try:
        results = pipe.execute_flow({})
    except Exception as exc:  # noqa: BLE001 - a crash is a wrong verdict, not a grader error
        return f"Error: {type(exc).__name__}"
    statuses = [r.status for r in results.values() if r is not None]
    for worst in (ToolStatus.ERROR, ToolStatus.TIMEOUT, ToolStatus.NG):
        if worst in statuses:
            return worst.value
    return ToolStatus.OK.value


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps({os.path.basename(p): verdict(spec, os.path.abspath(p)) for p in sys.argv[2:]}))
