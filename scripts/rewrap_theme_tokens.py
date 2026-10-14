"""Re-wrap bare `THEME['x']` lookups in the theme template as `{T['x']}`.

`vm_theme.py` holds its stylesheet in an f-string, so a token reference has to be an
*interpolation*.  When the retint pass writes a bare `THEME['x']` into the CSS body it
becomes inert text that Qt rejects (and the whole declaration is dropped), so the
lookups are re-wrapped to match the `{T['x']}` form the rest of the template uses.

Only occurrences sitting in the CSS template are re-wrapped; real Python code outside
it is left alone.

Run:  python scripts/rewrap_theme_tokens.py --check
      python scripts/rewrap_theme_tokens.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "vm_clone", "ui", "vm_theme.py")

#: bare lookup -> f-string interpolation
BARE = re.compile(r"(?<!\{)\bTHEME\['([a-z_0-9]+)'\]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    src = open(TARGET, encoding="utf-8").read()
    lines = src.split("\n")

    # The template starts at the f-string assignment and runs to its closing quotes.
    start = next((i for i, l in enumerate(lines) if "VM_THEME_QSS" in l), None)
    if start is None:
        print("could not find the VM_THEME_QSS template")
        return 1
    end = next((i for i in range(len(lines) - 1, start, -1)
                if lines[i].strip() == '"""' or lines[i].strip().endswith('"""')),
               len(lines))

    total = 0
    for i in range(start, end):
        new, n = BARE.subn(lambda m: "{T['%s']}" % m.group(1), lines[i])
        if n:
            lines[i] = new
            total += n

    print(f"{total} bare lookup(s) re-wrapped in the theme template "
          f"(lines {start + 1}-{end + 1})")
    if args.apply:
        open(TARGET, "w", encoding="utf-8").write("\n".join(lines))
        print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
