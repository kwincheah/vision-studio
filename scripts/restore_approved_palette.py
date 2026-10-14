"""Restore the approved KEYENCE-derived palette into `vm_clone/ui/styles.py`.

The palette is the one measured from the official KEYENCE manuals and approved in the
earlier work; it lives here as a script because a `git checkout` of the stylesheet
module reverted it once already, and re-deriving it by hand is error-prone.

Idempotent: re-running on an already-restored file reports "already restored".

Run:  python scripts/restore_approved_palette.py [--apply]
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "vm_clone", "ui", "styles.py")

PALETTE = '''THEME = {
    # --- Surfaces & backgrounds (KEYENCE light: K1 panel / K2 canvas) --------
    "bg_app": "#e4e7ea",           # window field
    "bg_surface": "#ecf0f0",       # panels, sidebars, dock containers   (K1 0.17)
    "bg_surface_alt": "#f8fafb",   # card surfaces, parameter groups
    "bg_control": "#c0c4c8",       # buttons, inputs, tree nodes         (K1 0.39)
    "bg_control_hover": "#d4d8db", # control hover
    "bg_control_active": "#a8adb2",# control pressed
    "bg_header": "#848c94",        # menus, dock titles, table headers   (K1 0.69)
    "bg_table_row_alt": "#f2f5f6", # alternating row surface

    # --- Borders & outlines -------------------------------------------------
    # Borders are *meaningful graphics* (they delimit every control), so they are
    # held to the WCAG non-text 3:1 rule rather than being decorative hairlines.
    # The reference draws them hard: a CV-X group box border measures 13.1:1 on its
    # panel, and an XG unit-node edge 5.5:1 on the canvas.
    "border_subtle": "#5f666d",    # 1 px frame and divider lines
    "border_control": "#5a6069",   # input & button boundaries
    "border_focus": "#0078b0",     # focus ring (K1 blue accent)

    # --- Typography (dark-on-light, WCAG AA+ on the light surfaces) ---------
    "text_primary": "#1a2024",     # body text                           (K1)
    "text_secondary": "#414850",   # headers, units, sub-captions
    "text_muted": "#5a6168",       # placeholders, timestamps, captions
    "text_on_chrome": "#f0f2f4",   # labels on the dark chrome           (K2)
    "text_on_menu": "#1a2120",     # dark ink on the lighter menu strip  (K1 4.99:1)

    # --- Accents (KEYENCE: blue primary, amber selection) -------------------
    "accent_primary": "#0078b0",   # active glyphs, links                (K1)
    "accent_hover": "#2f96ce",
    "accent_dim": "#f6dcae",       # amber selection wash                (K1 0.07)
    #: Selection edge.  The reference marks a selected node with a hard dark edge
    #: (measured 8.38:1 against the canvas), so the amber edge is deepened until it
    #: clears 3:1 against *both* the card fill and the canvas.  The amber fill itself
    #: is the approved brand colour and is unchanged.
    "accent_border": "#6f4a04",

    # --- Semantic status tokens (functional meaning, corrected contrast) ----
    "status_ok_text": "#076b3a",
    "status_ok_bg": "#d8f0e2",
    "status_ok_border": "#00754a",   # K2 Run button green

    "status_warn_text": "#8a5a0e",
    "status_warn_bg": "#fbeccf",
    "status_warn_border": "#8a5a0e", # K1 caution orange

    "status_error_text": "#b81c20",
    "status_error_bg": "#fadadd",
    "status_error_border": "#c8161a",# K2 error LED

    "status_running_text": "#0a6a96",
    "status_running_bg": "#d4e8f4",
    "status_running_border": "#0078b0",

    # --- Vision-workspace tokens (Apex identity on a KEYENCE-derived base) --
    "vm_chrome": "#848c94",          # menu strip            (measured K1 0.46)
    "vm_chrome_dark": "#646c6c",     # toolbar + status bar  (measured K2 0.39)
    #: The rail carries light glyphs, so it uses the darker end of the measured chrome
    #: range: at `#646c6c` the white glyphs only reach 3.6:1, short of the 4.5:1 needed
    #: for UI text.  The measured darkest chrome gives 6.9:1.
    "vm_rail": "#505854",
    "vm_rail_hover": "#6a7270",
    "vm_flyout": "#f8fafb",          # tool flyout panel surface (measured K1 #f4f4f4)
    "vm_flyout_header": "#dfe3e6",   # flyout category header
    "vm_canvas": "#b4b8c0",          # flow canvas base      (measured K2 0.54)
    #: The grid is a *subtle* texture on the light canvas and is decorative (nodes align
    #: by drag, not by grid), so it is deliberately below the non-text target and is
    #: exempt from the audit gate.
    "vm_canvas_dot": "#949aa4",
    "vm_canvas_dot_major": "#868d98",
    "vm_panel": "#ecf0f0",           # right-side data panel
    "vm_panel_header": "#d8dcdf",    # panel header / table header
    "vm_card": "#fcfcfc",            # flow overview card surface (K2 node)
    "vm_accent": "#e4b030",          # signature amber selection (measured K1)
    "vm_accent_hover": "#f0c050",
    "vm_accent_dim": "#f8e8c8",      # amber selection wash
    "vm_node": "#fcfcfc",            # module card body      (measured K2)
    "vm_node_text": "#1a2024",       # module card primary text
    "vm_node_text_dim": "#4f565c",   # module card secondary text
    #: Node edge, deepened to match the reference's hard graph-paper outline
    #: (XG unit node vs canvas measures 5.5:1).
    "vm_node_border": "#5c636a",
    #: Dependency wire.  On this lighter canvas the reference's exact accent blue only
    #: reaches 2.45:1, so the wire uses a deepened shade of the same hue.
    "vm_wire": "#005f8c",
    "vm_viewport": "#201c20",        # image viewport / result field (measured K2)
    "vm_viewport_text": "#e8eaec",
}'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    src = open(TARGET, encoding="utf-8").read()
    if '"vm_chrome_dark"' in src and '"text_on_menu"' in src:
        print("already restored")
        return 0

    # Replace the whole THEME literal.
    m = re.search(r"^THEME = \{.*?^\}", src, re.S | re.M)
    if m is None:
        print("could not find the THEME literal - aborting")
        return 1
    new = src[:m.start()] + PALETTE + src[m.end():]
    print(f"palette restored ({m.end() - m.start()} -> {len(PALETTE)} chars)")
    if args.apply:
        open(TARGET, "w", encoding="utf-8").write(new)
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
