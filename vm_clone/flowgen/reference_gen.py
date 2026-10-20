"""Generate the catalogue and recipe sections of the flow-generation reference from the live engine."""
import json
import os
import re
from typing import Dict, List

from vm_clone.flowgen.catalog import full_catalog

PKG = os.path.dirname(os.path.abspath(__file__))
REFERENCE = os.path.join(PKG, "reference", "flow_generation_reference.md")
RECIPES_DIR = os.path.join(PKG, "recipes")


def load_recipes() -> Dict[str, dict]:
    out = {}
    for fn in sorted(os.listdir(RECIPES_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(RECIPES_DIR, fn), encoding="utf-8") as f:
                out[fn[:-5]] = json.load(f)
    return out


def catalog_markdown() -> str:
    parts: List[str] = []
    for s in full_catalog(builtin_only=True):
        parts.append(f"### {s['tool']}")
        parts.append(f"*Category:* {s['category']}. {s['description']}" + ("  \n**Has side effects** (network, files, hardware or user code): mention it to the user." if s["side_effects"] else ""))
        ins = ", ".join(f"`{k}` ({t})" for k, t in s["inputs"].items()) or "none"
        outs = ", ".join(f"`{k}` ({t})" for k, t in s["outputs"].items()) or "none"
        parts.append(f"- Inputs: {ins}\n- Outputs: {outs}")
        if s["parameters"]:
            parts.append("- Parameters:")
            for k, v in s["parameters"].items():
                default = json.dumps(v["default"]) if not isinstance(v["default"], str) or len(v["default"]) < 60 else '"(multi-line text)"'
                choices = f"; choices: {' | '.join(v['choices'])}" if "choices" in v else ""
                if "min" in v and v["min"] > -1e11:
                    choices += f"; range {v['min']:g} to {v['max']:g}" + (f" {v['unit']}" if v.get("unit") else "")
                elif v.get("unit"):
                    choices += f"; unit {v['unit']}"
                parts.append(f"  - `{k}` ({v['editor']}), default {default}{choices}")
        parts.append("")
    return "\n".join(parts)


def recipes_markdown() -> str:
    parts: List[str] = []
    for key, r in load_recipes().items():
        parts.append(f"### Recipe: {r['title']}")
        parts.append(f"Use when: {r['when']}")
        parts.append("```json\n" + json.dumps(r["spec"], indent=1) + "\n```")
        parts.append("")
    return "\n".join(parts)


def render() -> str:
    with open(REFERENCE, encoding="utf-8") as f:
        text = f.read()
    for tag, body in (("RECIPES", recipes_markdown()), ("CATALOG", catalog_markdown())):
        text = re.sub(rf"(<!-- BEGIN {tag} -->).*?(<!-- END {tag} -->)",
                      lambda m: f"{m.group(1)}\n{body}\n{m.group(2)}", text, flags=re.S)
    return text


def write() -> str:
    text = render()
    with open(REFERENCE, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return REFERENCE
