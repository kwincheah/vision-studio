"""Clean up `QColor(f"{THEME['x']}")` style wrapping introduced by the linker.

A token lookup already yields a string, so wrapping it in an f-string is noise; and
where the linker nested a lookup inside an existing expression it produced the
invalid form `THEME[f"x"]` or a quoted literal.  This normalises all three to plain
`THEME['x']` lookups.

Run:  python scripts/normalise_token_lookups.py --check
      python scripts/normalise_token_lookups.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

#: `f"{THEME['x']}"` (with optional surrounding quotes inside QColor(...)) -> token
PATTERNS = [
    # QColor(f"{THEME['x']}")            -> QColor(THEME['x'])
    (re.compile(r"""QColor\(f"\{THEME\['([a-z_0-9]+)'\]\}"\)"""),
     r"""QColor(THEME['\1'])"""),
    # QColor(f'{THEME["x"]}')            -> QColor(THEME['x'])
    (re.compile(r"""QColor\(f'\{THEME\["([a-z_0-9]+)"\]\}'\)"""),
     r"""QColor(THEME['\1'])"""),
    # QColor("{THEME['x']}")             -> QColor(THEME['x'])
    (re.compile(r"""QColor\("\{THEME\['([a-z_0-9]+)'\]\}"\)"""),
     r"""QColor(THEME['\1'])"""),
    # THEME[f"x"]                        -> THEME['x']
    (re.compile(r"""THEME\[f"([a-z_0-9]+)"\]"""),
     r"""THEME['\1']"""),
    # f"{THEME['x']}" used as a bare value inside another f-string -> token
    (re.compile(r"""f"\{THEME\['([a-z_0-9]+)'\]\}"""),
     r"""THEME['\1']"""),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total = 0
    for root, _d, files in os.walk(os.path.join(ROOT, "vm_clone")):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            src = open(path, encoding="utf-8").read()
            out, n = src, 0
            for pat, repl in PATTERNS:
                out, k = pat.subn(repl, out)
                n += k
            if n:
                total += n
                print(f"  {f}: {n} cleanup(s)")
                if args.apply:
                    open(path, "w", encoding="utf-8").write(out)

    print(f"\n{total} nested lookup(s) normalised")
    return 0


if __name__ == "__main__":
    sys.exit(main())
