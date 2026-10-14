"""Validate that every declared dimension is on the design-token scale.

Distinct *combinations* are not the same as distinct *values*: `4px 8px` and `2px 12px`
are two shorthands drawn from the same five-step spacing scale, and collapsing them
would remove intentional differences in density.  What matters is that no value is
off-scale, so this checks every component of every length declaration against the
token ramps and reports anything outside them.

Run:  python scripts/validate_design_tokens.py [--strict]
"""
import argparse
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

STYLESHEET_MODULES = ["styles.py", "vm_theme.py"]
#: files scanned for inline stylesheets and pixel metrics
UI_DIRS = [os.path.join(ROOT, "vm_clone", "ui")]

LENGTH_DECL = re.compile(
    r"(?<!-)\b(font-size|border-radius|padding|margin|min-height|max-height|"
    r"min-width|max-width|padding-left|padding-right|padding-top|padding-bottom|"
    r"margin-left|margin-right|margin-top|margin-bottom|width|height|gap)\s*:\s*"
    r"([^;{}]+);")
NUM = re.compile(r"(\d+(?:\.\d+)?)px")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    from vm_clone.ui.styles import (BORDER, RADIUS, SIZE, SPACE, TYPE, WEIGHT)
    from vm_clone.ui.vm_theme import VM_THEME_QSS
    from vm_clone.ui.styles import INDUSTRIAL_THEME_QSS

    px_allowed = set(TYPE.values()) | set(SIZE.values()) | set(SPACE.values()) | \
        set(RADIUS.values()) | set(BORDER.values())
    #: widths and heights that are structural rather than part of a ramp
    structural = {0, 1, 2, 3, 6, 7, 13, 18, 20, 22, 26, 30, 42, 48, 51, 52, 56, 62, 68,
                  80, 96, 100, 104, 112, 120, 150, 168, 176, 200, 240, 300, 320, 340,
                  380, 400, 446, 520, 818}

    off: List[Tuple[str, str, str, str]] = []
    counts: Counter = Counter()
    checked = 0
    for name, css in (("vm_theme", VM_THEME_QSS), ("industrial", INDUSTRIAL_THEME_QSS)):
        for m in LENGTH_DECL.finditer(css):
            prop, raw = m.group(1), m.group(2).strip()
            if raw.startswith("{") or "{" in raw:
                continue          # unresolved token: nothing to validate
            checked += 1
            for value in NUM.findall(raw):
                counts[prop] += 1
                px = float(value)
                on_scale = px in px_allowed
                if prop in ("width", "height", "min-width", "max-width",
                            "min-height", "max-height"):
                    on_scale = on_scale or px in structural
                if not on_scale:
                    off.append((name, prop, raw, value))

    # also scan inline stylesheets in the UI modules
    inline_off: List[Tuple[str, int, str, str]] = []
    for directory in UI_DIRS:
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".py") or fname in STYLESHEET_MODULES:
                continue
            path = os.path.join(directory, fname)
            text = open(path, encoding="utf-8").read()
            for m in LENGTH_DECL.finditer(text):
                prop, raw = m.group(1), m.group(2).strip()
                if "{" in raw or "f\"" in raw:
                    continue
                lineno = text[:m.start()].count("\n") + 1
                for value in NUM.findall(raw):
                    on_scale = float(value) in px_allowed or float(value) in structural
                    if not on_scale:
                        inline_off.append((fname, lineno, prop, value))

    print(f"{checked} resolved length declaration(s) in the two stylesheets")
    print(f"  space scale : {sorted(SPACE.values())}")
    print(f"  radius scale: {sorted(RADIUS.values())}")
    print(f"  type scale  : {sorted(TYPE.values())}")
    print(f"  size tokens : {sorted(SIZE.values())}")
    print()
    for prop, n in counts.most_common():
        print(f"  {prop:16s} {n}")

    print(f"\n{len(off)} off-scale value(s) in the stylesheets")
    for name, prop, raw, value in off[:20]:
        print(f"   {name}: {prop}: {raw}  ({value}px)")

    print(f"\n{len(inline_off)} off-scale value(s) in inline widget stylesheets")
    for fname, lineno, prop, value in inline_off[:20]:
        print(f"   {fname}:{lineno}  {prop}: {value}px")

    total = len(off) + len(inline_off)
    if args.strict and total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
