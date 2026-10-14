"""Bring the Start Page onto the approved palette.

`vm_clone/ui/start_page.py` predates the palette work: it hardcodes its own light
palette with a *different* accent blue (`#2563EB`), a *different* ink slate
(`#1E293B`), and a near-black page header (`#201F24`).  That is why the Start Page
reads as a separate application from the workspace.

Values are substituted directly (never a token *name* into the CSS, which Qt would
discard).  `#FFFFFF` is context-sensitive - it is both the card/field fill and the
label ink on the blue action buttons - so it is only remapped when it appears as a
`background`, and left alone when it is a `color`.

Run:  python scripts/retint_start_page.py --check
      python scripts/retint_start_page.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "vm_clone", "ui", "start_page.py")

#: start-page literal -> approved palette value
MAP = {
    "#f8fafc": "#ecf0f0",   # page -> panel surface
    "#f1f5f9": "#e4e7ea",   # alt section -> window field
    "#e2e8f0": "#d8dcdf",   # chips / dividers -> panel header
    "#eff6ff": "#f6dcae",   # info tint -> amber selection wash
    "#201f24": "#d8dcdf",   # page header -> panel header (was near-black)
    "#dcfce7": "#d8f0e2",   # success tint
    "#fee2e2": "#fadadd",   # error tint
    "#cbd5e1": "#5a6069",   # border -> input/control border (3.5:1)
    "#fecaca": "#c8161a",   # error border
    "#1e293b": "#1a2024",   # ink
    "#334155": "#1a2024",
    "#475569": "#414850",
    "#64748b": "#5a6168",   # muted ink (was 4.0:1, now 6.0:1)
    "#94a3b8": "#5a6168",
    "#991b1b": "#b81c20",   # error ink
    "#166534": "#076b3a",   # success ink
    "#2563eb": "#0078b0",   # accent blue -> approved accent
    "#1d4ed8": "#0078b0",
    "#1e40af": "#0078b0",
    "#0284c7": "#2f96ce",   # accent hover
    "#e8792b": "#e4b030",   # amber
    "#dc2626": "#b81c20",   # error
    "#fca5a5": "#c8161a",
}

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    lines = open(TARGET, encoding="utf-8").read().split("\n")
    changed = 0
    kept_white = 0

    for i, line in enumerate(lines):
        if "#" not in line:
            continue
        is_color_prop = bool(re.search(r"(?<!-)\bcolor\s*:", line))

        def sub(m):
            nonlocal kept_white
            key = m.group(0).lower()
            if key == "#ffffff":
                if is_color_prop:
                    kept_white += 1
                    return m.group(0)     # white ink on the blue action button
                return "#f8fafb"          # card / field fill
            return MAP.get(key, m.group(0))

        new = HEX.sub(sub, line)
        if new != line:
            lines[i] = new
            changed += 1

    print(f"{changed} line(s) retinted; {kept_white} white ink value(s) preserved")
    if args.apply:
        open(TARGET, "w", encoding="utf-8").write("\n".join(lines))
        print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
