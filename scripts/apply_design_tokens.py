"""Replace literal visual constants in the stylesheets with design tokens.

Operates only on the two stylesheet modules (`styles.py`, `vm_theme.py`) and only on
the properties the design system owns: font size, weight, border radius, padding and
margin.  Colours, layout properties and structure are untouched.

The mappings are explicit rather than derived so the intent of each collapse is
reviewable, and every replacement keeps the value it had where the value was already a
deliberate tier (for example a 2 px hairline padding stays a hairline).

Run:  python scripts/apply_design_tokens.py --check
      python scripts/apply_design_tokens.py --apply
"""
import argparse
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

TARGETS = [
    os.path.join(ROOT, "vm_clone", "ui", "styles.py"),
    os.path.join(ROOT, "vm_clone", "ui", "vm_theme.py"),
]

#: literal font size -> type-ramp token.  Only sizes already in use are listed, so no
#: text changes size; the change is that the value now has one name.
FONT = {
    "10px": "fs_micro",
    "11px": "fs_caption",
    "12px": "fs_body",
    "13px": "fs_label",
    "14px": "fs_subtitle",
    "16px": "fs_title",
}

#: literal weight -> weight token
WEIGHT = {
    "500": "fw_medium",
    "600": "fw_demibold",
    "700": "fw_bold",
    "400": "fw_regular",
}

#: literal radius -> radius token.  2 px and 3 px both read as "control" (the 1 px
#: difference is below the visual threshold at these sizes); 4 px is a container and
#: 5 px is the same container with a rounding difference not worth a tier of its own.
RADIUS = {"0": "none", "0px": "none", "2px": "r_control", "3px": "r_control",
          "4px": "r_panel", "5px": "r_panel", "6px": "r_panel", "9px": "r_pill"}

#: padding shorthand -> token-based shorthand.  Grouped by the role the padding plays
#: so a dense control stays dense; the audit's 29 distinct values collapse to 9.
PADDING = {
    "1px": "sp_hair",
    "2px": "sp_hair",
    "1px 2px": "sp_hair sp_hair",
    "1px 4px": "sp_hair sp_tight",
    "1px 6px": "sp_hair sp_snug",
    "1px 8px": "sp_hair sp_base",
    "2px 4px": "sp_hair sp_tight",
    "2px 5px": "sp_hair sp_snug",
    "2px 6px": "sp_hair sp_snug",
    "2px 8px": "sp_hair sp_base",
    "2px 10px": "sp_hair sp_loose",
    "2px 12px": "sp_hair sp_loose",
    "3px 6px": "sp_tight sp_snug",
    "3px 8px": "sp_tight sp_base",
    "3px 9px": "sp_tight sp_base",
    "3px 10px": "sp_tight sp_loose",
    "3px 13px": "sp_tight sp_loose",
    "3px 14px": "sp_tight sp_loose",
    "4px": "sp_tight",
    "4px 2px": "sp_tight sp_hair",
    "4px 6px": "sp_tight sp_snug",
    "4px 8px": "sp_tight sp_base",
    "4px 9px": "sp_tight sp_base",
    "4px 10px": "sp_tight sp_loose",
    "4px 12px": "sp_tight sp_loose",
    "5px 9px": "sp_tight sp_base",
    "5px 24px 5px 20px": "sp_tight sp_section sp_tight sp_loose",
    "5px 26px 5px 24px": "sp_tight sp_section sp_tight sp_section",
    "6px": "sp_snug",
    "6px 10px": "sp_snug sp_loose",
    "6px 14px": "sp_snug sp_section",
    "7px 10px 6px 10px": "sp_base sp_loose sp_snug sp_loose",
    "8px": "sp_base",
    "10px": "sp_loose",
    "12px": "sp_loose",
}

#: margin shorthand -> token-based.  Spacings inside a control are small by design.
MARGIN = {
    "0": "0",
    "0px": "0",
    "1px 0": "sp_hair 0",
    "1px 1px": "sp_hair sp_hair",
    "1px 2px": "sp_hair sp_hair",
    "1px 3px": "sp_hair sp_tight",
    "1px 4px": "sp_hair sp_tight",
    "0 8px": "0 sp_base",
    "1px 6px": "sp_hair sp_snug",
    "2px 0": "sp_hair 0",
    "2px 4px": "sp_hair sp_tight",
    "3px 0": "sp_tight 0",
    "4px 0": "sp_tight 0",
    "4px 5px": "sp_tight sp_snug",
    "4px 6px": "sp_tight sp_snug",
    "4px 8px": "sp_tight sp_base",
    "6px 0": "sp_snug 0",
    "8px 0": "sp_base 0",
}

#: min-height literal -> size token
MIN_H = {
    "0": "none",
    "0px": "none",
    "16px": "h_icon_sm",
    "18px": "h_icon_sm",
    "20px": "h_icon_md",
    "22px": "h_input",
    "24px": "h_input",
    "26px": "h_button",
    "28px": "h_button",
    "30px": "h_toolbar",
    "32px": "h_toolbar",
    "34px": "h_header",
    "36px": "h_header",
}


#: tokens whose value is zero; emitted as a literal `0`, which needs no unit
ZERO_TOKENS = {"none", "sp_none", "r_none", "h_none"}


def _token_expr(name: str, alias: str, unit: str) -> str:
    """`{THEME['token']}` with a CSS unit appended when the token is a length.

    The unit matters: `padding: {T['sp_hair']} {T['sp_loose']};` renders as
    `padding: 2 12;`, which Qt rejects and silently discards, so the widget keeps its
    default and the mistake is invisible in a screenshot.  Every token in the
    dimension ramp is a bare number, so the unit is supplied here.  A zero token is
    emitted as a literal `0`, which needs no unit.
    """
    if name in ZERO_TOKENS:
        return "0"
    expr = "{" + f"{alias}['{name}']" + "}"
    return expr + unit if unit else expr


def _snap_component(value: str, alias: str) -> str:
    """Snap one `Npx` / `0` component onto the spacing scale, as a token reference."""
    from vm_clone.ui.styles import SPACE

    raw = value.strip()
    if raw in ("0", "0px"):
        return "0"
    m = re.fullmatch(r"(\d+)px", raw)
    if not m:
        return value
    px = int(m.group(1))
    name = min(SPACE, key=lambda k: (abs(SPACE[k] - px), SPACE[k]))
    return _token_expr(f"sp_{name}", alias, "px")


def _sub_prop(text: str, prop: str, mapping: Dict[str, str],
              alias: str = "THEME") -> Tuple[str, int]:
    """Replace `prop: <literal>;` with the token form.  Returns (text, count).

    `alias` is the token-map name in that module: `styles.py` refers to `THEME`,
    while `vm_theme.py` binds the same dict to `T`.
    """
    from vm_clone.ui.styles import BORDER

    count = 0
    # The unit a tokenised value needs, per property.
    unit = {"font-size": "px", "border-radius": "px", "min-height": "px",
            "padding": "px", "margin": "px"}.get(prop, "")
    # Longest literals first so "4px 8px" is matched before "4px".
    literals = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(rf"(\b{re.escape(prop)}\s*:\s*)([^;{{}}]+)(;)")

    def repl(m):
        nonlocal count
        raw = " ".join(m.group(2).split())
        for lit in literals:
            if raw == lit:
                token = mapping[lit]
                count += 1
                rendered = " ".join(
                    "0" if t == "0" else _token_expr(f"sp_{t}", alias, "px")
                    if t.startswith(("hair", "tight", "snug", "base", "loose", "section"))
                    else _token_expr(t, alias, unit)
                    for t in token.split())
                return f"{m.group(1)}{rendered}{m.group(3)}"
        # Fallback: snap a spacing shorthand component by component.  This covers the
        # long tail of literal values and the mixed form that arises when a shorthand
        # combines a zero with an already-tokenised value and so is missed by the
        # whole-string table (`0 {T['sp_tight']}` needs a unit on the second part).
        if prop in ("padding", "margin"):
            parts = raw.split()
            if all(re.fullmatch(r"0|[\d.]+px|\{.*\}", p) for p in parts):
                snapped = []
                for part in parts:
                    if part.startswith("{"):
                        if not re.search(r"\}(px|%)$", part):
                            part = part + "px"      # add the missing unit
                        snapped.append(part)
                    else:
                        snapped.append(_snap_component(part, alias))
                if snapped != parts:
                    count += 1
                    return f"{m.group(1)}{' '.join(snapped)}{m.group(3)}"
        return m.group(0)

    return pattern.sub(repl, text), count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    totals: Counter = Counter()
    for path in TARGETS:
        src = open(path, encoding="utf-8").read()
        before = len(src)
        # `vm_theme.py` binds the token dict to the short name `T`.
        alias = "T" if os.path.basename(path) == "vm_theme.py" else "THEME"
        text = src
        for prop, mapping in (("font-size", FONT), ("font-weight", WEIGHT),
                              ("border-radius", RADIUS), ("padding", PADDING),
                              ("margin", MARGIN), ("min-height", MIN_H)):
            text, n = _sub_prop(text, prop, mapping, alias)
            if n:
                totals[prop] += n
        if text != src:
            print(f"  {os.path.basename(path)}: "
                  f"{sum(1 for a, b in zip(src, text) if a != b)} chars differ, "
                  f"len {before} -> {len(text)}")
            if args.apply:
                open(path, "w", encoding="utf-8").write(text)

    print(f"\n{sum(totals.values())} literal(s) tokenised")
    for prop, n in totals.most_common():
        print(f"   {prop:16s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
