"""Flow specification: the compact JSON the assistant writes, its validation and its conversion to a flow.

The model never writes XML.  It writes this spec; ``validate_spec`` returns precise, fixable problems
and ``build_flow`` turns a valid spec into a real :class:`VisionPipeline` that is serialised with the
application's own XML writer, so the result always opens in the app.

Spec shape::

    {"name": "Flow1",
     "modules": [{"id": "src", "tool": "Image Source", "name": "01_Source",
                  "params": {"source_type": "Synthetic"}}],
     "links":   [{"from": "src", "from_port": "Image", "to": "blur", "to_port": "Image"}]}
"""
import difflib
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from vm_clone.core.base_tool import is_compatible_type
from vm_clone.core.pipeline import SolutionManager, VisionPipeline
from vm_clone.core.registry import create_tool_instance, list_all_tools
from vm_clone.core import param_schema
from vm_clone.flowgen.catalog import SIDE_EFFECT_TOOLS

SPEC_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["modules"],
    "properties": {
        "name": {"type": "string", "description": "Flow name"},
        "modules": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object", "required": ["id", "tool"],
                "properties": {
                    "id": {"type": "string", "description": "Short unique id used by links (letters, digits, underscore)"},
                    "tool": {"type": "string", "description": "Exact tool name from the catalogue"},
                    "name": {"type": "string", "description": "Display name, e.g. 02_FindHole (optional)"},
                    "params": {"type": "object", "description": "Parameter name -> value (only those that differ from the default)"},
                    "enabled": {"type": "boolean"},
                },
            },
        },
        "links": {
            "type": "array",
            "items": {
                "type": "object", "required": ["from", "from_port", "to", "to_port"],
                "properties": {"from": {"type": "string"}, "from_port": {"type": "string"},
                               "to": {"type": "string"}, "to_port": {"type": "string"}},
            },
        },
    },
}

_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")


def _issue(severity: str, code: str, message: str, hint: str = "", where: str = "") -> Dict[str, str]:
    return {"severity": severity, "code": code, "where": where, "message": message, "hint": hint}


def _close(word: str, options) -> str:
    near = difflib.get_close_matches(str(word), list(options), n=3, cutoff=0.5)
    return f"Did you mean: {', '.join(near)}?" if near else f"Available: {', '.join(list(options)[:12])}"


def _suggest_tools(name: Any, tools) -> str:
    """Close spellings first, then tools whose description matches the words used."""
    near = difflib.get_close_matches(str(name), list(tools), n=3, cutoff=0.6)
    if not near:
        from vm_clone.flowgen.catalog import search_tools
        near = [h["tool"] for h in search_tools(str(name), limit=3)]
    return f"Did you mean: {', '.join(near)}? (search_tools finds tools by keyword)" if near else "Call search_tools to find the exact name."


def _param_problem(tool_name: str, key: str, default: Any, value: Any) -> Optional[str]:
    """Why ``value`` does not fit the parameter (None when it fits) - the same rules the property editors enforce."""
    if value is None:
        return None
    return param_schema.problem(tool_name, key, default, value)


def validate_spec(spec: Any) -> List[Dict[str, str]]:
    """All problems of a spec.  Errors must be fixed; warnings are advice."""
    issues: List[Dict[str, str]] = []
    if not isinstance(spec, dict):
        return [_issue("error", "spec", "The spec must be a JSON object with a 'modules' list.")]
    modules = spec.get("modules")
    if not isinstance(modules, list) or not modules:
        return [_issue("error", "modules", "'modules' must be a non-empty list.",
                       'Example: {"modules":[{"id":"src","tool":"Image Source"}],"links":[]}')]
    links = spec.get("links", [])
    if not isinstance(links, list):
        return [_issue("error", "links", "'links' must be a list.")]

    tools = set(list_all_tools())
    instances: Dict[str, Any] = {}
    names = set()
    for i, m in enumerate(modules):
        where = f"modules[{i}]"
        if not isinstance(m, dict):
            issues.append(_issue("error", "module", "A module must be an object.", where=where))
            continue
        mid, tname = m.get("id"), m.get("tool")
        if not isinstance(mid, str) or not _ID.match(mid):
            issues.append(_issue("error", "id", f"Invalid module id {mid!r}.",
                                 "Use letters, digits and underscores, starting with a letter.", where))
            continue
        if mid in instances:
            issues.append(_issue("error", "duplicate_id", f"Module id '{mid}' is used twice.", where=where))
            continue
        if tname not in tools:
            issues.append(_issue("error", "unknown_tool", f"Unknown tool {tname!r}.", _suggest_tools(tname, tools), where))
            continue
        tool = create_tool_instance(tname, mid, m.get("name") or None)
        instances[mid] = tool
        if tool.name in names:
            issues.append(_issue("error", "duplicate_name", f"Two modules are named '{tool.name}'.",
                                 "Give each module a different 'name' (or omit it).", where))
        names.add(tool.name)
        params = m.get("params", {})
        if not isinstance(params, dict):
            issues.append(_issue("error", "params", "'params' must be an object.", where=where))
            continue
        for key, value in params.items():
            if key not in tool.parameters:
                issues.append(_issue("error", "unknown_param", f"{tname} has no parameter '{key}'.",
                                     _close(key, tool.parameters), f"{where}.params.{key}"))
                continue
            problem = _param_problem(tname, key, tool.parameters[key], value)
            if problem:
                issues.append(_issue("error", "bad_param", f"{tname}.{key} {problem}.",
                                     f"Default is {tool.parameters[key]!r}.", f"{where}.params.{key}"))
        if tname in SIDE_EFFECT_TOOLS:
            issues.append(_issue("warning", "side_effects", f"{tname} talks to the outside world or runs code.",
                                 "Tell the user to review its settings before running the flow.", where))

    fed: Dict[Tuple[str, str], str] = {}
    edges: List[Tuple[str, str]] = []
    for i, ln in enumerate(links):
        where = f"links[{i}]"
        if not isinstance(ln, dict) or not all(k in ln for k in ("from", "from_port", "to", "to_port")):
            issues.append(_issue("error", "link", "A link needs from, from_port, to and to_port.", where=where))
            continue
        a, ap, b, bp = ln["from"], ln["from_port"], ln["to"], ln["to_port"]
        if a not in instances or b not in instances:
            missing = a if a not in instances else b
            issues.append(_issue("error", "link_node", f"Link refers to unknown module '{missing}'.",
                                 _close(missing, instances), where))
            continue
        if a == b:
            issues.append(_issue("error", "self_link", f"Module '{a}' cannot feed itself.", where=where))
            continue
        src, dst = instances[a], instances[b]
        if ap not in src.outputs:
            issues.append(_issue("error", "link_port", f"{src.tool_name} has no output '{ap}'.",
                                 _close(ap, src.outputs), where))
            continue
        if bp not in dst.inputs:
            issues.append(_issue("error", "link_port", f"{dst.tool_name} has no input '{bp}'.",
                                 _close(bp, dst.inputs), where))
            continue
        if not is_compatible_type(src.outputs[ap].data_type, dst.inputs[bp].data_type):
            issues.append(_issue("error", "type_mismatch",
                                 f"{a}.{ap} ({src.outputs[ap].data_type.name}) cannot feed {b}.{bp} "
                                 f"({dst.inputs[bp].data_type.name}).",
                                 "Only matching types connect (VALUE and BOOLEAN are interchangeable, ANY fits anything).",
                                 where))
            continue
        if (b, bp) in fed:
            issues.append(_issue("error", "input_taken", f"Input {b}.{bp} already has a source ({fed[(b, bp)]}).",
                                 "An input accepts exactly one link.", where))
            continue
        fed[(b, bp)] = f"{a}.{ap}"
        edges.append((a, b))

    cycle = _find_cycle(list(instances), edges)
    if cycle:
        issues.append(_issue("error", "cycle", "The links form a loop: " + " -> ".join(cycle) + ".",
                             "Flows must be acyclic; remove one of these links."))

    linked = {x for e in edges for x in e}
    for mid, tool in instances.items():
        for port in tool.inputs:
            if (mid, port) not in fed:
                issues.append(_issue("warning", "unconnected_input",
                                     f"{mid}.{port} ({tool.tool_name}) has no incoming link.",
                                     "Connect it, or the module will have no data to work on.", mid))
        if mid not in linked and len(instances) > 1:
            issues.append(_issue("warning", "isolated", f"Module '{mid}' is not linked to anything.", where=mid))
    if instances and not any(t.tool_name == "Image Source" for t in instances.values()):
        issues.append(_issue("warning", "no_source", "The flow has no Image Source module.",
                             "Most flows start with Image Source (or Image Buffer fed by one)."))
    return issues


def _find_cycle(nodes: List[str], edges: List[Tuple[str, str]]) -> List[str]:
    adj: Dict[str, List[str]] = {n: [] for n in nodes}
    for a, b in edges:
        adj[a].append(b)
    state = {n: 0 for n in nodes}
    for start in nodes:
        if state[start]:
            continue
        stack, path = [(start, iter(adj[start]))], [start]
        state[start] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
                path.pop()
            elif state[nxt] == 1:
                return path[path.index(nxt):] + [nxt]
            elif state[nxt] == 0:
                state[nxt] = 1
                stack.append((nxt, iter(adj[nxt])))
                path.append(nxt)
    return []


def has_errors(issues: List[Dict[str, str]]) -> bool:
    return any(i["severity"] == "error" for i in issues)


def build_flow(spec: Dict[str, Any]) -> Tuple[Optional[VisionPipeline], List[Dict[str, str]]]:
    """Spec -> VisionPipeline (None when the spec has errors)."""
    issues = validate_spec(spec)
    if has_errors(issues):
        return None, issues
    pipe = VisionPipeline(name=str(spec.get("name") or "GeneratedFlow"))
    for n, m in enumerate(spec["modules"], 1):
        default_name = f"{n:02d}_{re.sub(r'[^A-Za-z0-9]+', '', m['tool'])}"
        tool = create_tool_instance(m["tool"], m["id"], m.get("name") or default_name)
        for key, value in (m.get("params") or {}).items():
            tool.set_param(key, value)
        if m.get("enabled") is False:
            tool.enabled = False
        pipe.add_node(tool)
    for ln in spec.get("links", []):
        pipe.connect(ln["from"], ln["from_port"], ln["to"], ln["to_port"])
    pipe.node_positions = _layout(pipe)
    return pipe, issues


def _layout(pipe: VisionPipeline) -> Dict[str, List[float]]:
    """Layered left-to-right layout (depth = longest path from a source)."""
    depth = {n: 0 for n in pipe.nodes}
    for _ in range(len(pipe.nodes)):
        for c in pipe.connections:
            depth[c.to_node] = max(depth[c.to_node], depth[c.from_node] + 1)
    rows: Dict[int, int] = {}
    pos = {}
    for nid in pipe.nodes:
        d = depth[nid]
        r = rows.get(d, 0)
        rows[d] = r + 1
        pos[nid] = [50.0 + d * 260.0, 50.0 + r * 170.0]
    return pos


def build_solution(spec: Dict[str, Any], solution_name: str = "") -> Tuple[Optional[SolutionManager], List[Dict[str, str]]]:
    pipe, issues = build_flow(spec)
    if pipe is None:
        return None, issues
    sol = SolutionManager(name=solution_name or pipe.name)
    sol.flows[pipe.name] = pipe
    sol.active_flow_name = pipe.name
    return sol, issues


def spec_to_xml(spec: Dict[str, Any], solution_name: str = "") -> Tuple[str, List[Dict[str, str]]]:
    """(xml, issues).  ``xml`` is empty when the spec has errors."""
    sol, issues = build_solution(spec, solution_name)
    if sol is None:
        return "", issues
    return sol.to_xml(), issues
