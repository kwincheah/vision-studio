"""Repair malformed `{#rrggbb}` placeholders left by a token-linking pass.

`link_literals_to_tokens.py` promotes a string to an f-string when it inserts a
token lookup, but where the literal was written as `{#ecf0f0` (a `#` outside the
quotes) the promotion produced `f"... {#ecf0f0} ..."`, which is a syntax error: the
`#` starts a comment inside the placeholder expression.

The intended meaning is plainly the colour itself, so the placeholder collapses back
to the literal value.

Run:  python scripts/fix_malformed_placeholders.py --check
      python scripts/fix_malformed_placeholders.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
#: `{#rrggbb}` -> `#rrggbb`
BROKEN = re.compile(r"\{(#[0-9a-fA-F]{6})\}")


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
            new, n = BROKEN.subn(r"\1", src)
            if n:
                total += n
                print(f"  {f}: {n} placeholder(s) repaired")
                if args.apply:
                    open(path, "w", encoding="utf-8").write(new)

    print(f"\n{total} malformed placeholder(s) repaired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
