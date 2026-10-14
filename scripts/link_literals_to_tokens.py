"""Replace stale palette literals in widget code with `THEME[...]` lookups.

The retint pass substituted *values* into widget strings, which left ~50 colour
literals that shadow the palette: when a token is later corrected for contrast, the
literal does not follow and the widget silently keeps the old, unreadable colour.
This rewrites those literals to token lookups (promoting the enclosing string to an
f-string where needed) so every surface tracks the palette.

Categorical diagram colours (module-category identity) and semantic status colours
are left alone: they encode meaning, not surface.

Run:  python scripts/link_literals_to_tokens.py --check
      python scripts/link_literals_to_tokens.py --apply
"""
import argparse
import os
import re
import sys
from typing import Dict, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.ui.styles import THEME  # noqa: E402

#: literal -> token, for values that duplicate a palette token
TOKEN_OF: Dict[str, str] = {}
for _k, _v in THEME.items():
    if isinstance(_v, str) and _v.startswith("#"):
        TOKEN_OF.setdefault(_v.lower(), _k)

#: Values left behind by the earlier retint pass.  Each was the *old* palette
#: value, so it is mapped to the token whose contrast was since corrected; leaving
#: them in place would silently shadow the fix.
STALE: Dict[str, str] = {
    "#4a5258": "text_secondary",
    "#5c6468": "vm_node_text_dim",
    "#6e767c": "text_muted",
    "#98a0a6": "border_control",
    "#b8bcc0": "border_subtle",
    "#8a9096": "vm_node_border",
    "#a2a8b2": "vm_canvas_dot",
    "#d89a28": "accent_border",
    "#00ac64": "status_ok_border",
    "#f49c34": "status_warn_border",
    "#ec282c": "status_error_border",
    "#9a6410": "status_warn_text",
}
TOKEN_OF.update({k: v for k, v in STALE.items() if v in THEME})

#: never rewrite these: they carry meaning (status, category identity)
PRESERVE = {
    "#22c55e", "#ef4444", "#f59e0b", "#a855f7", "#14b8a6", "#c084fc",
    "#a78bfa", "#10b981", "#f87171", "#00ac64", "#ec282c", "#f49c34",
    "#dc2626", "#b91c1c", "#166534", "#15803d", "#16a34a", "#4ade80",
}

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def in_string_spans(line: str) -> List[Tuple[int, int]]:
    spans, i, n = [], 0, len(line)
    while i < n:
        if line[i] in "'\"":
            q = line[i:i + 3] if line[i:i + 3] in ("'''", '"""') else line[i]
            end = line.find(q, i + len(q))
            end = n if end == -1 else end + len(q)
            spans.append((i, end))
            i = end
        else:
            i += 1
    return spans


def rewrite(line: str) -> Tuple[str, int, List[str]]:
    """Token-ise palette literals; report the count and anything unmapped."""
    spans = in_string_spans(line)
    out, last, n = [], 0, 0
    unmapped: List[str] = []

    for m in HEX.finditer(line):
        h = m.group(0).lower()
        if h in PRESERVE:
            continue
        token = TOKEN_OF.get(h)
        if token is None:
            unmapped.append(h)
            continue
        inside = any(s <= m.start() < e for s, e in spans)
        # QColor("...") / QPen(QColor(...)) want a string, not a bare lookup.
        needs_quotes = False
        if inside:
            head = line[max(0, m.start() - 40):m.start()]
            needs_quotes = bool(re.search(r"QColor\(\s*$", head))
            repl = f"THEME['{token}']" if needs_quotes else \
                   f"\"'\"+THEME['{token}']+\"'\""
        else:
            repl = f"THEME['{token}']"

        out.append(line[last:m.start()])
        if inside and not needs_quotes:
            # Build an f-string expression replacing the literal text.
            out.append("{THEME['%s']}" % token)
        else:
            out.append(repl)
        last = m.end()
        n += 1
    out.append(line[last:])
    new = "".join(out)

    # Promote the surrounding literal to an f-string when we injected {…}.
    if "{THEME[" in new and "f\"" not in new and "f'" not in new:
        new = re.sub(r'(?<![\w\]\)])(["\'])', r'f\1', new, count=1)
    return new, n, unmapped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total = 0
    unmapped_all: Dict[str, List[str]] = {}
    for root, _d, files in os.walk(os.path.join(ROOT, "vm_clone")):
        for f in sorted(files):
            if not f.endswith(".py") or f == "styles.py":
                continue
            path = os.path.join(root, f)
            lines = open(path, encoding="utf-8").read().split("\n")
            changed = 0
            for i, line in enumerate(lines):
                if "#" not in line:
                    continue
                if "setStyleSheet" not in line and "QColor" not in line \
                        and "QPen" not in line:
                    continue
                new, n, unmapped = rewrite(line)
                for u in unmapped:
                    unmapped_all.setdefault(u, []).append(f"{f}:{i + 1}")
                if n and new != line:
                    lines[i] = new
                    changed += n
            if changed and args.apply:
                open(path, "w", encoding="utf-8").write("\n".join(lines))
            if changed:
                total += changed
                print(f"  {f}: {changed} literal(s)")

    print(f"\n{total} literal(s) linked to tokens")
    if unmapped_all:
        print("not in the palette (left alone):")
        for h, where in sorted(unmapped_all.items(), key=lambda kv: -len(kv[1]))[:20]:
            print(f"  {h}  x{len(where)}  {where[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
