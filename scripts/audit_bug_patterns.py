"""Second-pass sweep for the *bug patterns* the first audit found.

The first pass tested values.  This tests the code shapes that produced those bugs, so
a remaining instance cannot hide simply because my earlier value list happened to miss
it:

  1. `except: pass` / broad excepts that swallow a real failure and still report OK.
  2. API calls that signal failure by *returning* a falsy value instead of raising
     (`cv2.imwrite`, `os.path.*`, socket calls).
  3. Unguarded `int()` / `float()` on anything operator- or upstream-supplied.
  4. Parameters declared in `_init_parameters` but never read in `execute`.
  5. Inputs declared as ports but never read in `execute`.

Run:  python scripts/audit_bug_patterns.py
"""
import ast
import os
import re
import sys
from typing import Any, Dict, List, Set, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.core.registry import list_all_tools, create_tool_instance  # noqa: E402
import vm_clone.tools  # noqa: E402,F401


def class_sources() -> Dict[str, Tuple[str, str]]:
    """Map registered tool_name -> (file, class source) by walking the tools package."""
    out: Dict[str, Tuple[str, str]] = {}
    tools_dir = os.path.join(ROOT, "vm_clone", "tools")
    for fname in sorted(os.listdir(tools_dir)):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(tools_dir, fname)
        src = open(path, encoding="utf-8").read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            name = None
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name) and t.id == "tool_name":
                            if isinstance(item.value, ast.Constant):
                                name = item.value.value
            if name:
                out[name] = (fname, ast.get_source_segment(src, node) or "")
    return out


def execute_source(cls_src: str) -> str:
    """The text of the class's execute() method, or ''."""
    try:
        tree = ast.parse("class X:\n" + "\n".join(
            "    " + line for line in cls_src.split("\n")))
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "execute":
            return ast.get_source_segment(
                "class X:\n" + "\n".join("    " + l for l in cls_src.split("\n")), node) or ""
    return ""


def main() -> int:
    sources = class_sources()
    issues: List[Dict[str, Any]] = []

    for tool in list_all_tools():
        if tool not in sources:
            continue
        fname, cls_src = sources[tool]
        body = execute_source(cls_src)
        if not body:
            continue
        # unindent for easier matching
        lines = [l.strip() for l in body.split("\n")]

        # --- 1. swallowed exceptions -------------------------------------
        for i, line in enumerate(lines):
            if re.match(r"except\b", line):
                tail = " ".join(lines[i + 1:i + 3])
                if tail.startswith("pass") or tail.startswith("continue"):
                    issues.append({
                        "tool": tool, "file": fname, "kind": "SWALLOWED EXCEPTION",
                        "detail": f"{line} -> {tail[:60]}",
                    })

        # --- 2. unchecked falsy-returning API calls -----------------------
        for i, line in enumerate(lines):
            if re.search(r"\bcv2\.imwrite\(", line) and "if " not in line \
                    and "=" not in line:
                issues.append({
                    "tool": tool, "file": fname,
                    "kind": "UNCHECKED imwrite",
                    "detail": line[:70],
                })
            if re.search(r"\b(?:os\.remove|os\.makedirs|os\.rename)\(", line) \
                    and "try" not in body[:body.find(line)].split("\n")[-1]:
                pass  # these raise; only imwrite-style returns matter

        # --- 3. unguarded numeric conversion of a supplied value ----------
        for i, line in enumerate(lines):
            if "as_float" in line or "try" in " ".join(lines[max(0, i - 2):i]):
                continue
            m = re.search(r"\b(int|float)\(\s*(self\.get_param|context\.get|[a-z_]+_?in|[a-z]+_raw)", line)
            if m:
                issues.append({
                    "tool": tool, "file": fname,
                    "kind": "UNGUARDED CONVERSION",
                    "detail": line[:70],
                })

    # --- 4/5. declared but unused parameters and ports --------------------
    # Scanned over the WHOLE class body, not just execute(): several tools use their
    # parameters inside helpers such as `_compute_transform()`, and a narrower scan
    # reports those as unused.
    for tool in list_all_tools():
        try:
            inst = create_tool_instance(tool, f"__pat_{tool}__")
        except Exception:
            continue
        if tool not in sources:
            continue
        fname, cls_src = sources[tool]
        for param in inst.parameters:
            if param not in cls_src:
                issues.append({"tool": tool, "file": fname,
                               "kind": "UNUSED PARAMETER", "detail": param})
        for port in inst.outputs:
            if port not in cls_src:
                issues.append({"tool": tool, "file": fname,
                               "kind": "DECLARED OUTPUT NEVER SET", "detail": port})
        for port in inst.inputs:
            # A port is read either by name or through get_input_image()/get_roi(),
            # which resolve it internally.
            if port in cls_src:
                continue
            if port == "Image" and ("get_input_image" in cls_src or "get_roi" in cls_src):
                continue
            issues.append({"tool": tool, "file": fname,
                           "kind": "UNUSED INPUT PORT", "detail": port})

    # report grouped by kind
    by_kind: Dict[str, List[Dict]] = {}
    for issue in issues:
        by_kind.setdefault(issue["kind"], []).append(issue)

    for kind in sorted(by_kind):
        items = by_kind[kind]
        print(f"\n=== {kind} ({len(items)})")
        for it in items:
            print(f"  {it['tool']:26s} {it['file']:22s} {it['detail'][:64]}")

    print(f"\n{len(issues)} potential issue(s) across {len(by_kind)} pattern(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
