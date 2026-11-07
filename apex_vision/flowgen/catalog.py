"""Machine-readable catalogue of the installed vision tools (what the AI assistant may use).

Read from the live registry, so tools added by plugins appear automatically and the reference
cannot drift from the engine.
"""
import os
from typing import Any, Dict, List, Optional

import apex_vision.tools  # noqa: F401  (registers the built-in tools)
from apex_vision.core.registry import create_tool_instance, list_all_tools

from apex_vision.core import param_schema


def choices_for(tool: str, key: str) -> Optional[List[str]]:
    """Allowed values of a drop-down parameter of ``tool`` (None for free-form parameters)."""
    return param_schema.choices_for(tool, key)


# Tools that talk to the outside world or run user code: never executed by a dry run, and flagged
# for the user to review.
SIDE_EFFECT_TOOLS = {"TCP Send", "Script", "Image Output", "Camera IO"}


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (list, tuple)):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "any"


_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _portable(value: Any) -> Any:
    """Defaults that point into the install folder are shown relative to it (the catalogue must not depend on
    where the app is installed)."""
    if isinstance(value, str) and value.startswith(_APP_ROOT):
        return "<app>/" + os.path.relpath(value, _APP_ROOT).replace(os.sep, "/")
    return value


def tool_spec(name: str) -> Dict[str, Any]:
    """Ports, parameters (with default, type and allowed values) and description of one tool."""
    tool = create_tool_instance(name, "spec")
    params = {}
    for key, default in tool.parameters.items():
        entry: Dict[str, Any] = {"default": _portable(default), "type": _type_name(default)}
        ps = param_schema.spec_for(name, key, default)
        entry["editor"] = ps["kind"]
        for extra in ("choices", "min", "max", "unit"):
            if extra in ps:
                entry[extra] = ps[extra]
        params[key] = entry
    return {
        "tool": name,
        "category": tool.category,
        "description": tool.description,
        "inputs": {k: p.data_type.name for k, p in tool.inputs.items()},
        "outputs": {k: p.data_type.name for k, p in tool.outputs.items()},
        "parameters": params,
        "side_effects": name in SIDE_EFFECT_TOOLS,
        "builtin": getattr(tool, "plugin_id", "builtin") == "builtin",
    }


def full_catalog(builtin_only: bool = False) -> List[Dict[str, Any]]:
    """Every registered tool (``builtin_only``: just the ones shipped with the app - what the checked-in
    reference documents; plugin tools are always available live through ``get_tool_spec``)."""
    specs = [tool_spec(n) for n in sorted(list_all_tools())]
    return [s for s in specs if s["builtin"]] if builtin_only else specs


def search_tools(query: str = "", category: Optional[str] = None, limit: int = 15) -> List[Dict[str, Any]]:
    """Keyword search over name, category, description, port and parameter names (no embeddings)."""
    words = [w for w in query.lower().replace(",", " ").split() if w]
    hits = []
    for spec in full_catalog():
        if category and spec["category"].lower() != category.lower():
            continue
        text = " ".join([spec["tool"], spec["category"], spec["description"], *spec["inputs"], *spec["outputs"],
                         *spec["parameters"]]).lower()
        score = sum(text.count(w) + (3 if w in spec["tool"].lower() else 0) for w in words) if words else 1
        if score:
            hits.append((score, spec))
    hits.sort(key=lambda h: -h[0])
    return [{"tool": s["tool"], "category": s["category"], "description": s["description"],
             "inputs": s["inputs"], "outputs": s["outputs"]} for _score, s in hits[:limit]]


def compact_catalog_text() -> str:
    """One line per tool, small enough to put in a system prompt (~4k tokens for all built-ins)."""
    lines = []
    for s in full_catalog():
        params = ", ".join(f"{k}={v['default']!r}" + (f" {{{'|'.join(v['choices'])}}}" if "choices" in v else "")
                           for k, v in s["parameters"].items())
        ins = ", ".join(f"{k}:{t}" for k, t in s["inputs"].items()) or "-"
        outs = ", ".join(f"{k}:{t}" for k, t in s["outputs"].items()) or "-"
        flag = " [side effects]" if s["side_effects"] else ""
        lines.append(f"{s['tool']} ({s['category']}){flag}: {s['description']}\n  in: {ins} | out: {outs}\n  params: {params}")
    return "\n".join(lines)
