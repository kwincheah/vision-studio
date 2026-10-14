"""Rewrite `THEME[...]` text inside multi-line CSS strings into real values.

`vm_clone/ui/start_page.py` embeds stylesheets as plain triple-quoted strings, so the
token name was written into the CSS as literal text and Qt discarded every
declaration - which is why the Start Page and New Project dialog rendered with the
platform's dark default palette instead of the app theme.

The fix substitutes each token's measured value (a plain string edit, so the CSS
braces are untouched) and leaves already-interpolated f-strings alone.

Run:  python scripts/fix_css_token_text.py --check
      python scripts/fix_css_token_text.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.ui.styles import THEME  # noqa: E402

#: A token that is *already* an f-string interpolation is preceded by `{`; those must
#: be left alone, or the value would be substituted inside the expression itself.
TOKEN = re.compile(r"""(?<!\{)\bTHEME\[\s*['"]([a-z_0-9]+)['"]\s*\]""")
TRIPLE = '"""'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total = 0
    unknown = set()
    for root, _d, files in os.walk(os.path.join(ROOT, "vm_clone")):
        for f in sorted(files):
            if not f.endswith(".py") or f == "styles.py":
                continue
            path = os.path.join(root, f)
            lines = open(path, encoding="utf-8").read().split("\n")
            # Track multi-line plain (non-f) triple-quoted strings only.
            in_plain_block = False
            touched = 0
            for i, line in enumerate(lines):
                if TRIPLE in line:
                    head = line.split(TRIPLE)[0]
                    is_f = head.rstrip().endswith("f")
                    if line.count(TRIPLE) == 1:
                        in_plain_block = not is_f
                    continue
                if not in_plain_block or "THEME[" not in line:
                    continue

                def sub(m):
                    nonlocal touched
                    key = m.group(1)
                    if key not in THEME:
                        unknown.add(key)
                        return m.group(0)
                    touched += 1
                    return THEME[key]

                lines[i] = TOKEN.sub(sub, line)
            if touched:
                total += touched
                print(f"  {f}: {touched} token(s)")
                if args.apply:
                    open(path, "w", encoding="utf-8").write("\n".join(lines))

    print(f"\n{total} literal token(s) rewritten")
    if unknown:
        print("unknown tokens left alone:", sorted(unknown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
