"""Find `THEME[...]` written as literal *text* inside a plain stylesheet string.

The bug class behind the unthemed Start Page.  A stylesheet written as a plain
(non-f) string such as

    setStyleSheet(<plain string with> THEME['x'] <inside>)

puts the token *name* into the CSS, so Qt discards the declaration and the widget
falls back to the platform palette.  The same token inside an f-string is an
expression and must be left alone.

This uses Python's own `tokenize`, which is the only reliable way to tell a plain
string from an f-string whose expression happens to contain the same characters.

Run:  python scripts/find_literal_tokens.py
"""
import io
import os
import re
import sys
import tokenize

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOKEN = re.compile(r"""THEME\[\s*['"]([a-z_0-9]+)['"]\s*\]""")


def scan(path: str):
    """Yield (lineno, token_text) for literal tokens inside plain strings."""
    hits = []
    try:
        with open(path, "rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
    except (tokenize.TokenError, SyntaxError):
        return hits

    for tok in tokens:
        if tok.type != tokenize.STRING:
            continue
        text = tok.string
        stripped = text.lstrip("fFrRbBuU")
        # An f-string's body is code, not literal text.
        if text[0] in "fF" or stripped[:1] in ("f", "F"):
            continue
        if "THEME[" not in text:
            continue
        for m in TOKEN.finditer(text):
            hits.append((tok.start[0], m.group(0), text.split("\n")[0][:70]))
    return hits


def main() -> int:
    total = 0
    for root, _d, files in os.walk(os.path.join(ROOT, "vm_clone")):
        for f in sorted(files):
            if not f.endswith(".py") or f == "styles.py":
                continue
            hits = scan(os.path.join(root, f))
            if hits:
                total += len(hits)
                print(f"\n{f}  ({len(hits)} literal token(s))")
                lines = sorted({h[0] for h in hits})
                print(f"  lines: {lines[:20]}")
                for lineno, tok, text in hits[:4]:
                    print(f"    {lineno}: {text}")
    print(f"\n{total} literal token(s) inside plain strings")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
