"""Audit text/background contrast across the theme and every widget stylesheet.

Computes WCAG 2.1 relative-luminance contrast ratios for the pairs the UI actually
renders, and greps the widget stylesheets for literal colours that bypass the
palette (which is where contrast bugs hide, because a hardcoded light literal on a
light surface is invisible while the token would have been correct).

Run:  python scripts/audit_contrast.py            # report
      python scripts/audit_contrast.py --strict   # non-zero exit if any AA failure
"""
import argparse
import os
import re
import sys
from typing import Dict, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.ui.styles import THEME  # noqa: E402

AA_NORMAL = 4.5
AA_LARGE = 3.0
AA_UI = 3.0          # non-text UI components and meaningful graphics


def _srgb(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexcol: str) -> float:
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def ratio(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


#: (label, foreground, background, kind) — kind: text | large | ui
PAIRS: List[Tuple[str, str, str, str]] = [
    # --- body text on the light surfaces ------------------------------------
    ("body ink on panel", "text_primary", "bg_surface", "text"),
    ("body ink on window field", "text_primary", "bg_app", "text"),
    ("body ink on card", "text_primary", "bg_surface_alt", "text"),
    ("body ink on module card", "vm_node_text", "vm_node", "text"),
    ("body ink on input field", "text_primary", "bg_surface_alt", "text"),
    ("secondary ink on panel", "text_secondary", "bg_surface", "text"),
    ("secondary ink on card", "text_secondary", "bg_surface_alt", "text"),
    ("muted ink on panel", "text_muted", "bg_surface", "text"),
    ("muted ink on card", "text_muted", "bg_surface_alt", "text"),
    ("muted ink on window field", "text_muted", "bg_app", "text"),
    ("module card dim ink on card", "vm_node_text_dim", "vm_node", "text"),
    ("table header ink on header", "text_primary", "vm_panel_header", "text"),
    ("secondary ink on table header", "text_secondary", "vm_panel_header", "text"),
    # --- text on the steel chrome -------------------------------------------
    ("body ink on menu strip", "text_on_menu", "vm_chrome", "text"),
    ("chrome label on toolbar", "text_on_chrome", "vm_chrome_dark", "text"),
    ("chrome label on status bar", "text_on_chrome", "vm_chrome_dark", "text"),
    ("body ink on control face", "text_primary", "bg_control", "text"),
    ("secondary ink on control face", "text_secondary", "bg_control", "text"),
    # --- text on the dark viewport ------------------------------------------
    ("viewport ink on viewport", "vm_viewport_text", "vm_viewport", "text"),
    # --- selection states ---------------------------------------------------
    ("ink on amber selection wash", "text_primary", "accent_dim", "text"),
    ("ink on amber hover", "text_primary", "vm_accent_hover", "text"),
    ("ink on tree selection", "text_primary", "accent_dim", "text"),
    ("white on accent (menu pick)", "#ffffff", "accent_primary", "text"),
    # --- semantic states ----------------------------------------------------
    ("OK text on OK wash", "status_ok_text", "status_ok_bg", "text"),
    ("warn text on warn wash", "status_warn_text", "status_warn_bg", "text"),
    ("error text on error wash", "status_error_text", "status_error_bg", "text"),
    ("running text on run wash", "status_running_text", "status_running_bg", "text"),
    # --- non-text: borders and the indicators that carry meaning -------------
    ("border vs panel", "border_subtle", "bg_surface", "ui"),
    ("control border vs control face", "border_control", "bg_control", "ui"),
    ("selection edge vs card", "accent_border", "vm_node", "ui"),
    ("selection edge vs canvas", "accent_border", "vm_canvas", "ui"),
    ("wire blue vs canvas", "vm_wire", "vm_canvas", "ui"),
    ("OK border vs panel", "status_ok_border", "bg_surface", "ui"),
    ("error border vs panel", "status_error_border", "bg_surface", "ui"),
    ("warn border vs panel", "status_warn_border", "bg_surface", "ui"),
    ("run border vs panel", "status_running_border", "bg_surface", "ui"),
    ("rail vs panel (edge)", "vm_rail", "bg_surface", "ui"),
    ("card border vs canvas", "vm_node_border", "vm_canvas", "ui"),
    ("focus ring vs panel", "border_focus", "bg_surface", "ui"),
]

#: Pairs that are intentionally below the non-text target, with the reason.  The
#: signature amber is part of the approved palette, so it is never used as a lone
#: indicator: selections pair it with a 3:1 edge (`accent_border`) and with the
#: `vm_accent_dim` wash that carries dark ink at >12:1.
APPROVED_EXCEPTIONS = {
    "amber accent vs canvas":
        "approved brand amber; never the sole indicator - the node edge uses "
        "accent_border (3:1) and the badge sits on a bordered capsule",
    "amber accent vs card":
        "approved brand amber; the selected card adds the accent_border edge",
    "canvas grid dot vs canvas":
        "decorative dot grid; nodes align by drag, it carries no information",
}


def check_pairs() -> Tuple[List[Dict], int]:
    rows, failures = [], 0
    for label, fg_key, bg_key, kind in PAIRS:
        fg = THEME.get(fg_key, fg_key)
        bg = THEME.get(bg_key, bg_key)
        r = ratio(fg, bg)
        need = AA_NORMAL if kind == "text" else (AA_LARGE if kind == "large" else AA_UI)
        exempt = label in APPROVED_EXCEPTIONS
        ok = r >= need or exempt
        if not ok:
            failures += 1
        rows.append({"label": label, "fg": fg, "bg": bg, "ratio": r,
                     "need": need, "kind": kind, "ok": ok, "exempt": exempt})
    return rows, failures


#: Literal colours in widget stylesheets that are not palette tokens.
LITERAL = re.compile(r"#[0-9a-fA-F]{6}\b")

#: Colours that deliberately live outside the palette because they encode meaning
#: rather than surface: module verdicts (PASS/FAIL/ERR/TIME), module-category
#: identity on the canvas, and the calibration overlay ink.  Their contrast is
#: checked where they are painted, not against a surface token here.
SEMANTIC_LITERALS = {
    "#22c55e",   # PASS
    "#ef4444",   # FAIL / ERR
    "#f59e0b",   # TIME / geometry-category
    "#a855f7",   # verdict-logic category
    "#14b8a6",   # text category
    "#c084fc",   # selected verdict-logic category
    "#a78bfa",   # algorithm-time readout
    "#10b981",   # calibration success overlay
    "#f87171",   # calibration failure overlay
    "#00ac64",   # run/OK semantic
    "#ec282c",   # error semantic
    "#f49c34",   # caution semantic
}


def stray_literals() -> List[Dict]:
    """Find colour literals in widget code that are not defined in the palette."""
    palette = {v.lower() for v in THEME.values() if isinstance(v, str)}
    out = []
    for root, _d, files in os.walk(os.path.join(ROOT, "vm_clone")):
        for f in sorted(files):
            if not f.endswith(".py") or f == "styles.py":
                continue
            path = os.path.join(root, f)
            for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
                if "setStyleSheet" not in line and "QColor(" not in line \
                        and "QPen(" not in line:
                    continue
                for m in LITERAL.finditer(line):
                    h = m.group(0).lower()
                    if h in palette or h in SEMANTIC_LITERALS:
                        continue
                    out.append({"file": f, "line": lineno, "colour": h,
                                "text": line.strip()[:100]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    rows, failures = check_pairs()
    print(f"{'pair':40s} {'ratio':>6s} {'need':>5s}  result")
    for r in rows:
        flag = "ok " if r["ok"] else "FAIL"
        note = "  (approved exception)" if r.get("exempt") and r["ratio"] < r["need"] else ""
        print(f"{r['label']:40s} {r['ratio']:6.2f} {r['need']:5.1f}  {flag}  "
              f"{r['fg']} on {r['bg']}{note}")
    print(f"\n{len(rows)} pairs checked, {failures} below target")
    exempt_hits = [r for r in rows if r.get("exempt") and r["ratio"] < r["need"]]
    if exempt_hits:
        print(f"{len(exempt_hits)} approved exception(s):")
        for r in exempt_hits:
            print(f"  {r['label']}: {APPROVED_EXCEPTIONS[r['label']]}")

    strays = stray_literals()
    if strays:
        print(f"\n{len(strays)} literal colour(s) outside the palette:")
        for s in strays[:40]:
            print(f"  {s['file']}:{s['line']}  {s['colour']}  {s['text']}")
    else:
        print("\nno colour literals outside the palette in widget code")

    if args.strict and (failures or strays):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
