"""Report the dimensions and typography each stylesheet rule declares.

This is the design-system baseline: for every colour/background rule it extracts the
declared font size, weight, border radius, padding and min/max height, then groups them
by component family.  Running it before and after a token pass shows exactly how much
the scale collapsed, which is the evidence the standardisation is judged on.

Run:  python scripts/audit_declared_metrics.py [--json]
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
PROP = re.compile(r"([a-z-]+)\s*:\s*([^;]+);")

#: property -> the aspect of the design system it exercises
TRACKED = ["font-size", "font-weight", "border-radius", "padding", "margin",
           "min-height", "max-height", "min-width", "border", "spacing"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from vm_clone.ui.styles import INDUSTRIAL_THEME_QSS, TYPE_SCALE
    from vm_clone.ui.vm_theme import VM_THEME_QSS

    declared: Dict[str, Dict[str, List[str]]] = {}
    for sheet_name, css in (("industrial", INDUSTRIAL_THEME_QSS),
                            ("vm_theme", VM_THEME_QSS)):
        for m in RULE.finditer(css):
            sel = " ".join(m.group(1).split())
            if not sel or sel.startswith("/*"):
                continue
            # keep only the last simple selector as the family key
            family = sel.split(",")[0].strip()
            props = {k: v.strip() for k, v in PROP.findall(m.group(2))}
            entry = declared.setdefault(family, {"sheet": sheet_name})
            for key in TRACKED:
                if key in props:
                    entry.setdefault(key, set()).add(props[key])

    # --- report -----------------------------------------------------------
    def values_for(prop: str) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for entry in declared.values():
            for value in entry.get(prop, ()):  # type: ignore[arg-type]
                counts[value] += 1
        return dict(counts)

    if args.json:
        payload = {fam: {k: sorted(v) if isinstance(v, set) else v
                         for k, v in entry.items()}
                   for fam, entry in declared.items()}
        print(json.dumps(payload, indent=1))
        return 0

    print(f"{len(declared)} distinct rule families\n")
    fonts = values_for("font-size")
    print(f"font-size declarations: {len(fonts)} distinct")
    for value, count in sorted(fonts.items(), key=lambda kv: -kv[1]):
        px = re.match(r"(\d+)px", value)
        on_ramp = px and int(px.group(1)) in TYPE_SCALE
        flag = "on-ramp " if on_ramp else "OFF-RAMP"
        print(f"   {flag} {value:>10s}  x{count}")
    print(f"   ramp is {TYPE_SCALE}")

    for prop in ("font-weight", "border-radius", "min-height", "max-height",
                 "min-width", "spacing"):
        vals = values_for(prop)
        if not vals:
            continue
        print(f"\n{prop}: {len(vals)} distinct")
        for value, count in sorted(vals.items(), key=lambda kv: -kv[1])[:14]:
            print(f"        {value:>12s}  x{count}")

    paddings = values_for("padding")
    print(f"\npadding: {len(paddings)} distinct")
    for value, count in sorted(paddings.items(), key=lambda kv: -kv[1])[:18]:
        print(f"        {value:>18s}  x{count}")

    margins = values_for("margin")
    print(f"\nmargin: {len(margins)} distinct")
    for value, count in sorted(margins.items(), key=lambda kv: -kv[1])[:14]:
        print(f"        {value:>18s}  x{count}")

    # families whose typography disagrees with the rest of their family
    print("\ncomponent families and their declared sizes:")
    families = defaultdict(set)
    for fam, entry in declared.items():
        for token in fam.split():
            if token.startswith("Q"):
                families[token].add(tuple(sorted(entry.get("font-size", ()))))
    for fam in sorted(families):
        sizes = sorted({s for combo in families[fam] for s in combo})
        if sizes:
            print(f"   {fam:34s} {sizes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
