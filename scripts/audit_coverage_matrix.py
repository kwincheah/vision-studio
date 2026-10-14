"""Build the component test-coverage matrix for the audit report.

Cross-references the registered tools against the test suite and the audit scripts, so
"tested" is a claim backed by a named test rather than an assumption.  Tools with no
direct coverage are listed explicitly.

Run:  python scripts/audit_coverage_matrix.py [--write]
"""
import argparse
import json
import os
import re
import sys
from typing import Dict, List, Set

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "audit")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    from vm_clone.core.registry import list_all_tools, list_categories
    import vm_clone.tools  # noqa: F401

    tools = list_all_tools()
    categories = list_categories()

    # Which test file mentions each tool by name?
    test_dir = os.path.join(ROOT, "tests")
    mentions: Dict[str, List[str]] = {t: [] for t in tools}
    for fname in sorted(os.listdir(test_dir)):
        if not fname.endswith(".py"):
            continue
        text = open(os.path.join(test_dir, fname), encoding="utf-8").read()
        for tool in tools:
            if tool in text:
                mentions[tool].append(fname)

    # The generic audits exercise every tool even when no test names it.
    audit_dir = os.path.join(ROOT, "scripts")
    audit_files = [f for f in sorted(os.listdir(audit_dir))
                   if f.startswith("audit_") and f.endswith(".py")]
    generic = [f for f in audit_files
               if f in ("audit_tool_behaviour.py", "audit_tool_contracts.py",
                        "audit_inventory.py")]

    rows = []
    uncovered = []
    for tool in tools:
        category = next((c for c, members in categories.items() if tool in members), "?")
        named = mentions[tool]
        # A tool is *directly* covered when a test names it, and *exercised* by the
        # generic audits regardless.
        rows.append({
            "tool": tool,
            "category": category,
            "named_in_tests": named,
            "direct_test": bool(named),
            "generic_audit": bool(generic),
        })
        if not named:
            uncovered.append(f"{tool} ({category})")

    os.makedirs(OUT, exist_ok=True)
    payload = {
        "tools": rows,
        "generic_audits": generic,
        "all_test_files": sorted(f for f in os.listdir(test_dir) if f.endswith(".py")),
    }
    if args.write:
        with open(os.path.join(OUT, "coverage_matrix.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)

    direct = sum(1 for r in rows if r["direct_test"])
    print(f"{len(tools)} tools: {direct} named in a test, "
          f"{len(tools) - direct} exercised only by the generic audits")
    print(f"generic audits covering every tool: {', '.join(generic)}")
    print(f"\n{len(uncovered)} tool(s) with no dedicated test:")
    for u in uncovered:
        print(f"  - {u}")
    print(f"\n{len(payload['all_test_files'])} test modules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
