"""Resolve `THEME['x']` lookups that sit inside **plain** stylesheet strings.

`link_literals_to_tokens.py` rewrote palette literals to token *lookups* so they
track the palette.  Inside a plain (non-f) string that lookup is inert text, and Qt
drops the whole declaration - which is how the Start Page's "Create Project" and
"Enter Workspace" buttons lost their label colour.

The safe repair is to substitute the token's **resolved value** there: the string
stays a plain string, no braces are introduced, and the widget paints the palette
colour.  f-strings are left alone because their lookups already interpolate.

A multi-line string is reported by `tokenize` at the line of its opening delimiter,
so the search runs forward from there to the closing delimiter.

Run:  python scripts/resolve_plain_string_tokens.py --check
      python scripts/resolve_plain_string_tokens.py --apply
"""
import argparse
import os
import re
import sys
import tokenize

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.ui.styles import THEME  # noqa: E402

TOKEN = re.compile(r"""THEME\[\s*['"]([a-z_0-9]+)['"]\s*\]""")
#: how far past the opening delimiter to look for the closing one
SCAN = 80


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total, unknown = 0, set()
    for root, _d, files in os.walk(os.path.join(ROOT, "vm_clone")):
        for f in sorted(files):
            if not f.endswith(".py") or f == "styles.py":
                continue
            path = os.path.join(root, f)
            lines = open(path, encoding="utf-8").read().split("\n")
            try:
                with open(path, "rb") as fh:
                    toks = list(tokenize.tokenize(fh.readline))
            except (tokenize.TokenError, SyntaxError):
                continue

            starts = []
            for tok in toks:
                if tok.type != tokenize.STRING or tok.string[0] in "fF":
                    continue
                if TOKEN.search(tok.string):
                    starts.append(tok.start[0])

            changed = 0
            for start in sorted(set(starts)):
                for i in range(start - 1, min(len(lines), start - 1 + SCAN)):
                    if "THEME[" not in lines[i]:
                        continue

                    def sub(m):
                        nonlocal changed
                        key = m.group(1)
                        if key not in THEME:
                            unknown.add(key)
                            return m.group(0)
                        changed += 1
                        return THEME[key]

                    new = TOKEN.sub(sub, lines[i])
                    if new != lines[i]:
                        lines[i] = new
            if changed:
                total += changed
                print(f"  {f}: {changed} lookup(s) resolved")
                if args.apply:
                    open(path, "w", encoding="utf-8").write("\n".join(lines))

    print(f"\n{total} lookup(s) resolved inside plain strings")
    if unknown:
        print("unknown tokens left alone:", sorted(unknown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
