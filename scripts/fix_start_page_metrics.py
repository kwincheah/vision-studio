"""Move the remaining off-scale values in `start_page.py` onto the design tokens.

The token pass covers the two stylesheet modules; this screen carries its own inline
stylesheets, which were retinted earlier but not brought onto the spacing and type
scales.  Four values are affected:

  * `padding: 1px 5px`  -> the badge pills; 5 px is not a step, 4 px is
  * `padding: 5px 10px` -> a field; 5/10 -> 4/8 keeps the field on-scale
  * `font-size: 17px`   -> the brand title; the ramp's display size is `fs_title`
  * `font-weight: 800`  -> the ramp tops out at `fw_bold` (700)

Run:  python scripts/fix_start_page_metrics.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
TARGET = os.path.join(ROOT, "vm_clone", "ui", "start_page.py")

EDITS = [
    ("badge pill padding", "padding: 1px 5px;", "padding: 1px 4px;"),
    ("field padding", "padding: 5px 10px;", "padding: 4px 8px;"),
    ("brand title size", "font-size: 17px;", "font-size: 16px;"),
    ("brand title weight", "font-weight: 800;", "font-weight: 700;"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    src = open(TARGET, encoding="utf-8").read()
    for label, old, new in EDITS:
        n = src.count(old)
        if n:
            src = src.replace(old, new)
            print(f"  {label:22s} {old!r} -> {new!r}  x{n}")
        else:
            print(f"  {label:22s} (already applied)")

    # report anything still off the scales
    from vm_clone.ui.styles import RADIUS, SPACE, TYPE, WEIGHT

    allowed = set(SPACE.values()) | set(RADIUS.values()) | set(TYPE.values())
    leftover = []
    for m in re.finditer(r"(padding|border-radius|font-size)\s*:\s*([^;{}]+);", src):
        prop, raw = m.group(1), m.group(2)
        for value in re.findall(r"(\d+)px", raw):
            if prop == "font-weight":
                continue
            if int(value) not in allowed:
                leftover.append(f"{prop}: {raw.strip()}")
    if leftover:
        print(f"\n{len(leftover)} value(s) still off-scale: {sorted(set(leftover))}")
    else:
        print("\nall inline lengths are on-scale")

    if args.apply:
        open(TARGET, "w", encoding="utf-8").write(src)
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
