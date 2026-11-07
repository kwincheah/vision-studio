"""The operations the assistant (and the MCP server) can call.  Everything returns plain JSON-able data."""
import time
from typing import Any, Dict

from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import list_all_tools
from apex_vision.flowgen import catalog, docs
from apex_vision.flowgen.catalog import SIDE_EFFECT_TOOLS
from apex_vision.flowgen.spec import build_flow, has_errors, spec_to_xml, validate_spec


def search_tools(query: str = "", category: str = "") -> Dict[str, Any]:
    return {"tools": catalog.search_tools(query, category or None)}


def get_tool_spec(tool: str) -> Dict[str, Any]:
    if tool not in list_all_tools():
        return {"error": f"Unknown tool {tool!r}.", "hint": "Call search_tools to find the exact name."}
    return catalog.tool_spec(tool)


def search_docs(query: str) -> Dict[str, Any]:
    return {"sections": docs.search_docs(query)}


def read_doc(section: str) -> Dict[str, Any]:
    found = docs.read_section(section)
    return found or {"error": f"No section {section!r}.", "sections": [s["id"] for s in docs.list_sections()][:60]}


def validate_flow(spec: Any) -> Dict[str, Any]:
    issues = validate_spec(spec)
    return {"ok": not has_errors(issues), "issues": issues}


def build_xml(spec: Any, solution_name: str = "") -> Dict[str, Any]:
    xml, issues = spec_to_xml(spec, solution_name)
    return {"ok": bool(xml), "xml": xml, "issues": issues}


def dry_run(spec: Any) -> Dict[str, Any]:
    """Run the flow once on its own (synthetic) input and report each module's verdict.

    Modules with side effects (network, files, hardware, user code) are switched off for the run."""
    pipe, issues = build_flow(spec)
    if pipe is None:
        return {"ok": False, "issues": issues}
    skipped = []
    for tool in pipe.nodes.values():
        if tool.tool_name in SIDE_EFFECT_TOOLS:
            tool.enabled = False
            skipped.append(tool.name)
    t0 = time.perf_counter()
    try:
        results = pipe.execute_flow({})
    except Exception as exc:                       # a tool bug must not kill the assistant
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "issues": issues}
    modules = []
    for nid in pipe.execution_order:
        res, node = results.get(nid), pipe.nodes[nid]
        if res is not None:
            modules.append({"id": nid, "name": node.name, "status": res.status.value, "message": res.message,
                            "ms": round(res.elapsed_ms, 2)})
    errors = [m for m in modules if m["status"] == ToolStatus.ERROR.value]
    return {"ok": not errors, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1), "modules": modules,
            "skipped_side_effect_modules": skipped, "issues": issues}


def pipeline_to_spec(pipe) -> Dict[str, Any]:
    """An existing flow as a spec (so the assistant can read and modify what is on the canvas)."""
    modules = []
    for nid, tool in pipe.nodes.items():
        defaults = type(tool)(nid).parameters
        changed = {k: v for k, v in tool.parameters.items() if defaults.get(k) != v}
        m: Dict[str, Any] = {"id": nid, "tool": tool.tool_name, "name": tool.name}
        if changed:
            m["params"] = changed
        if not tool.enabled:
            m["enabled"] = False
        modules.append(m)
    links = [{"from": c.from_node, "from_port": c.from_port, "to": c.to_node, "to_port": c.to_port}
             for c in pipe.connections]
    return {"name": pipe.name, "modules": modules, "links": links}
