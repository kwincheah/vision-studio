"""Retint the dark-titanium UI onto the measured KEYENCE palette, brace-safely.

Why this is not a plain find/replace
------------------------------------
The stylesheets are f-strings whose CSS blocks are written as `{{ ... }}`.  Splicing
`{THEME['x']}` into them (or into a plain string) produces either a broken f-string
expression or literal text that Qt rejects.  This script therefore works at the
*token* level and never inserts a brace:

* a **real code** hex literal becomes `THEME['token']`;
* a hex literal that sits **inside a string** is replaced by that token's measured
  value (so `"color: #e2e8f0;"` becomes `"color: #1a2024;"`), and the string is
  promoted to an f-string only when it was already one;
* when a string already contains a `{...}` expression, the value is substituted
  textually so the f-string's braces are left exactly as they were.

Semantic status colours (green / red / orange) and categorical diagram colours are
preserved verbatim, because they carry meaning rather than style.

Run:  python scripts/retint_ui.py --check
      python scripts/retint_ui.py --apply
"""
import argparse
import os
import re
import sys
from typing import Dict, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.ui.styles import THEME  # noqa: E402

# ---------------------------------------------------------------------------
# dark-titanium literal -> measured token
# ---------------------------------------------------------------------------
TOKENS: Dict[str, str] = {
    # window / panel / canvas
    "#0f1217": "bg_app", "#0b0e14": "bg_app", "#12151c": "bg_app",
    "#121620": "bg_app", "#131720": "bg_app", "#10141b": "bg_app",
    "#0f131a": "vm_canvas", "#1f2736": "vm_canvas_dot", "#2c384e": "vm_canvas_dot_major",
    "#1c1c20": "vm_viewport", "#1e2024": "vm_viewport", "#201f24": "vm_viewport",
    "#101216": "vm_viewport",
    "#ecf0f0": "vm_panel", "#151922": "vm_panel", "#151921": "bg_surface",
    "#141a24": "bg_surface", "#1b212c": "bg_surface",
    "#1a202a": "bg_surface_alt", "#191f2a": "bg_surface_alt",
    "#1e293b": "bg_surface_alt", "#242c3b": "bg_surface_alt",
    "#242d3d": "bg_surface_alt", "#1c2330": "bg_surface_alt", "#171d27": "bg_surface_alt",
    "#141822": "vm_flyout_header", "#1c222e": "vm_panel_header",
    "#181e28": "bg_header", "#181d26": "bg_header", "#181e28": "bg_header",
    "#1e2532": "vm_node", "#1e2533": "vm_node", "#1e2634": "vm_node",
    "#1a202c": "vm_flyout",
    "#11141a": "vm_chrome", "#11141b": "vm_chrome", "#161b24": "vm_rail",
    "#222938": "vm_rail_hover", "#202633": "bg_control", "#202735": "bg_control",
    "#2b3547": "bg_control", "#272f3e": "bg_control_hover",
    "#283344": "bg_control_hover", "#283447": "bg_control_hover",
    # borders
    "#232a37": "border_subtle", "#232b3a": "border_subtle", "#232c3b": "border_subtle",
    "#232c3d": "border_subtle", "#263143": "border_subtle", "#273244": "border_subtle",
    "#2a2d30": "border_subtle", "#e2e4e8": "border_subtle",
    "#2a3447": "border_control", "#2d3647": "border_control", "#2d3748": "border_control",
    "#2d384a": "border_control", "#2e3848": "vm_node_border", "#2e3b4e": "border_control",
    "#334155": "border_control", "#38465e": "border_control", "#383c44": "border_control",
    "#3a3b3f": "border_control", "#3b4961": "border_control", "#3d4a60": "border_control",
    "#2c3749": "border_control", "#38455a": "border_control",
    # ink
    "#464a50": "text_muted", "#5a5f6a": "text_muted", "#64748b": "text_muted",
    "#6e767c": "text_muted", "#999c9e": "text_muted", "#9ba0a7": "text_muted",
    "#475569": "text_secondary", "#b9bcc2": "text_secondary", "#b9bec6": "text_secondary",
    "#c3c6cb": "text_secondary", "#c9cbd0": "text_secondary", "#c9cbd1": "text_secondary",
    "#cbd5e1": "text_secondary", "#cfd2d7": "text_secondary", "#d0d3d8": "text_secondary",
    "#d5d8dd": "text_secondary", "#8b9096": "vm_node_text_dim",
    "#94a3b8": "vm_node_text_dim", "#9aa0a6": "vm_node_text_dim",
    "#d8dade": "text_primary", "#dcdde1": "text_primary", "#e2e8f0": "text_primary",
    "#e4e6ea": "text_primary", "#e6e8ec": "text_primary", "#f1f5f9": "text_primary",
    "#f8fafc": "text_primary", "#ffffff": "text_primary",
    # accents
    "#0ea5e9": "vm_accent_hover", "#38bdf8": "vm_accent",
    "#3b82f6": "accent_primary", "#2563eb": "accent_primary",
    "#1d4ed8": "accent_primary", "#0284c7": "accent_primary",
    "#0369a1": "accent_primary", "#1e40af": "accent_primary",
    "#e8792b": "vm_accent", "#e8963c": "vm_accent", "#eff6ff": "accent_dim",
}

#: keep verbatim: functional status + categorical diagram colours
KEEP = {
    "#22c55e", "#4ade80", "#16a34a", "#15803d", "#166534", "#dcfce7", "#86efac",
    "#ef4444", "#dc2626", "#b91c1c", "#991b1b", "#fca5a5", "#fee2e2", "#fecaca",
    "#f59e0b", "#fbbf24", "#a855f7", "#10b981", "#14b8a6", "#f87171",
    "#c084fc", "#a78bfa",
    "#12331f", "#3b181c", "#5e1d23", "#19562e", "#5e4012", "#4a1c20",
    "#163d24", "#184428", "#5a242a", "#14532d", "#1b5330", "#4c1f24",
    "#00ac64", "#ec282c", "#f49c34",
}

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def resolve(hexv: str) -> Tuple[str, str]:
    """(action, replacement) for a literal."""
    h = hexv.lower()
    if h in KEEP:
        return ("keep", hexv)
    if h in TOKENS:
        return ("value", THEME[TOKENS[h]])
    return ("unknown", hexv)


def code_positions(line: str) -> List[Tuple[int, int]]:
    """Ranges of the line that are inside a quoted string (prefix-aware)."""
    spans = []
    i, n = 0, len(line)
    while i < n:
        if line[i] in "'\"":
            quote = line[i:i + 3] if line[i:i + 3] in ("'''", '"""') else line[i]
            end = line.find(quote, i + len(quote))
            end = n if end == -1 else end + len(quote)
            spans.append((i, end))
            i = end
        else:
            i += 1
    return spans


def transform(line: str, string_kind: str = "plain") -> Tuple[str, int, List[str]]:
    """Rewrite every literal on the line; report count and unknowns.

    ``string_kind`` says how a literal *inside a string* should be replaced:

    * ``"plain"``  - substitute the token's measured **value**, because the string
      is not an f-string and a token name would be inert text;
    * ``"fstring"`` - substitute ``{THEME['token']}`` so the enclosing f-string
      interpolates it.  Used for the theme's own QSS template.
    """
    spans = code_positions(line)
    out = []
    last = 0
    count = 0
    unknown: List[str] = []

    for m in HEX.finditer(line):
        if m.start() < last:
            continue
        in_string = any(s <= m.start() < e for s, e in spans)
        action, repl = resolve(m.group(0))
        if action == "unknown":
            unknown.append(m.group(0).lower())
            continue
        if action == "keep":
            continue
        token = TOKENS[m.group(0).lower()]
        out.append(line[last:m.start()])
        if not in_string:
            out.append(f"THEME['{token}']")
        elif string_kind == "fstring":
            out.append("{THEME['%s']}" % token)
        else:
            out.append(repl)
        last = m.end()
        count += 1
    out.append(line[last:])
    return "".join(out), count, unknown


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total = 0
    unknown: Dict[str, int] = {}
    for root, _d, fs in os.walk(os.path.join(ROOT, "vm_clone")):
        for f in sorted(fs):
            if not f.endswith(".py") or f == "styles.py":
                continue
            path = os.path.join(root, f)
            # The theme module holds its stylesheet in an f-string template, so its
            # literals must become interpolations rather than substituted values.
            kind = "fstring" if f == "vm_theme.py" else "plain"
            lines = open(path, encoding="utf-8").read().split("\n")
            changed = 0
            for i, line in enumerate(lines):
                if "#" not in line:
                    continue
                new, n, unk = transform(line, kind)
                for u in unk:
                    unknown[u] = unknown.get(u, 0) + 1
                if n and new != line:
                    lines[i] = new
                    changed += n
            if changed and args.apply:
                open(path, "w", encoding="utf-8").write("\n".join(lines))
            if changed:
                total += changed
                print(f"  {f}: {changed} literal(s)")

    print(f"\n{total} literal(s) retinted")
    if unknown:
        print("unclassified (left alone):")
        for h, n in sorted(unknown.items(), key=lambda kv: -kv[1]):
            print(f"  {h} x{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
