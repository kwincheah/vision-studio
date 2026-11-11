"""Writes docs/MODULES.md from the module registry, so the page always matches the app.

    python scripts/gen_module_reference.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import apex_vision.tools  # noqa: E402,F401
from apex_vision.core import registry  # noqa: E402
from apex_vision.core.registry import create_tool_instance  # noqa: E402

ORDER = ["Acquisition", "Image Processing", "Color Processing", "Location", "Measurement", "Image Generation",
         "Recognition", "Defect Detection", "Calibration", "Logic Tools", "Communication"]
PIPE = "\\|"


def render() -> str:
    cats = {}
    for name in sorted(registry._TOOL_REGISTRY):
        tool = create_tool_instance(name, "x", "x")
        if getattr(tool, "toolbox_hidden", False) or getattr(tool, "plugin_id", "builtin") != "builtin":
            continue                    # hidden demo nodes and third-party plugin modules are not built-in modules
        cats.setdefault(tool.category, []).append(tool)
    total = sum(len(v) for v in cats.values())
    out = [f"# Module reference\n\nThe {total} built-in modules, by toolbox category. Inputs and outputs are the ports you "
           "wire together; select a module in the app and open the **Help** tab to see its settings and allowed values.\n\n"
           "This page is generated from the module registry (`python scripts/gen_module_reference.py`), so it always "
           "matches the app.\n"]
    for cat in ORDER + [c for c in cats if c not in ORDER]:
        if cat not in cats:
            continue
        out.append(f"\n## {cat} ({len(cats[cat])})\n\n| Module | What it does | Inputs | Outputs |\n|---|---|---|---|")
        for t in cats[cat]:
            desc = (t.description or "").replace("|", PIPE).replace("\n", " ")
            out.append(f"| **{t.tool_name}** | {desc} | {', '.join(t.inputs) or '-'} | {', '.join(t.outputs) or '-'} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    path = os.path.join(ROOT, "docs", "MODULES.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render())
    print("wrote", path)
