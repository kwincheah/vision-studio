"""Build the complete component inventory for the audit.

Discovers every registered vision tool and reports, per tool: category, declared
input ports, output ports, parameters with their default and type, and the module it
lives in.  Parameters and ports are created per instance (`_init_parameters` /
`_init_ports`), so each tool is instantiated rather than introspected.

Run:  python scripts/audit_inventory.py            # summary
      python scripts/audit_inventory.py --json     # machine-readable
      python scripts/audit_inventory.py --matrix   # test-matrix stub
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.core.registry import (  # noqa: E402
    list_all_tools, list_categories, get_tool_class, create_tool_instance,
)
import vm_clone.tools  # noqa: E402,F401  (importing registers the built-ins)


def describe(name: str) -> Dict[str, Any]:
    cls = get_tool_class(name)
    try:
        inst = create_tool_instance(name, instance_id="__inventory__")
    except Exception as exc:                      # a tool that cannot even be built
        return {"name": name, "error": f"{type(exc).__name__}: {exc}"}

    params = {}
    for key, value in inst.parameters.items():
        params[key] = {"default": value, "type": type(value).__name__}

    return {
        "name": name,
        "tool_name": inst.tool_name,
        "category": inst.category,
        "module": cls.__module__,
        "description": (inst.description or "")[:110],
        "inputs": [{"name": p.name, "type": p.data_type.value, "desc": p.description}
                   for p in inst.inputs.values()],
        "outputs": [{"name": p.name, "type": p.data_type.value, "desc": p.description}
                    for p in inst.outputs.values()],
        "parameters": params,
        "param_defs": sorted((inst.get_param_defs() or {}).keys()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--matrix", action="store_true")
    args = ap.parse_args()

    categories = list_categories()
    cat_of = {t: c for c, members in categories.items() for t in members}
    tools = [describe(n) for n in list_all_tools()]

    if args.json:
        print(json.dumps({"tools": tools, "categories": {k: list(v) for k, v in categories.items()}},
                         indent=1, default=str))
        return 0

    if args.matrix:
        print("| Tool | Category | In | Out | Params | Validation tested | "
              "Valid run | Invalid input | Missing input |")
        print("|---|---|---|---|---|---|---|---|---|")
        for t in tools:
            if "error" in t:
                print(f"| {t['name']} | - | - | - | - | **BUILD FAILS**: {t['error']} ||||")
                continue
            print(f"| {t['name']} | {t['category']} | {len(t['inputs'])} | "
                  f"{len(t['outputs'])} | {len(t['parameters'])} | | | | |")
        return 0

    print(f"{len(tools)} tools across {len(categories)} categories\n")
    built = 0
    for cat in categories:
        members = [t for t in tools if t.get("category") == cat]
        print(f"== {cat} ({len(members)})")
        for t in members:
            if "error" in t:
                print(f"   {t['name']:26s} ** BUILD FAILS: {t['error']}")
                continue
            built += 1
            ins = ",".join(p["type"][:4] for p in t["inputs"]) or "-"
            outs = ",".join(p["type"][:4] for p in t["outputs"]) or "-"
            print(f"   {t['name']:26s} in[{ins:16s}] out[{outs:18s}] "
                  f"p={len(t['parameters']):<2d}")
    print(f"\nbuilt cleanly: {built}/{len(tools)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
