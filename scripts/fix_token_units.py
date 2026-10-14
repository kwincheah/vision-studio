"""Add the missing CSS unit to tokenised declarations in a stylesheet module.

A design-token substitution that emits `font-size: {THEME['fs_body']};` produces
`font-size: 12;`, which Qt rejects - the declaration is discarded and the widget keeps
its default, so the mistake is invisible in a screenshot.  This repairs declarations in
place by appending `px` where a length token is missing its unit.

Idempotent: declarations that already carry a unit are left alone.

Run:  python scripts/fix_token_units.py [--apply]
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGETS = [os.path.join(ROOT, "vm_clone", "ui", "styles.py"),
           os.path.join(ROOT, "vm_clone", "ui", "vm_theme.py")]

#: properties whose values are lengths and therefore need a unit
LENGTH_PROPS = ("font-size", "border-radius", "min-height", "max-height",
                "min-width", "max-width", "padding", "margin", "padding-left",
                "padding-right", "padding-top", "padding-bottom", "margin-left",
                "margin-right", "margin-top", "margin-bottom", "border-width")

#: a token expression that is not already followed by a unit
BARE_TOKEN = re.compile(r"(\{[A-Za-z_]+\[['\"][a-z_0-9]+['\"]\]\})(?!\s*(?:px|%|em|pt)\b)")


def fix_line(line: str) -> tuple:
    """Append `px` to bare token expressions in a length declaration."""
    m = re.match(r"\s*([a-z-]+)\s*:", line)
    if not m or m.group(1) not in LENGTH_PROPS:
        return line, 0
    new, n = BARE_TOKEN.subn(r"\1px", line)
    # `{tok}pxpx` cannot occur because the pattern refuses to match a unitted token
    return new, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    total = 0
    for path in TARGETS:
        lines = open(path, encoding="utf-8").read().split("\n")
        changed = 0
        for i, line in enumerate(lines):
            if "{" not in line:
                continue
            new, n = fix_line(line)
            if n:
                lines[i] = new
                changed += n
        if changed:
            total += changed
            print(f"  {os.path.basename(path)}: {changed} declaration(s) repaired")
            if args.apply:
                open(path, "w", encoding="utf-8").write("\n".join(lines))

    print(f"\n{total} declaration(s) given a unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
