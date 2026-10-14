"""Normalise the theme's global base rules.

Three concerns meet in the base rules and each was lost by a different pass:

* `QWidget` must carry the *window field* colour, not the chrome.  A rule that paints
  every QWidget with the chrome made all unstyled containers - tooltips included - dark.
* `QWidget` must exist at all.  Removing it while splitting the old combined selector
  left unstyled widgets with no font, so their text fell back to the platform default.
* The font family must come from the token stack, so a stylesheet rule and a `QFont`
  fall back identically.

Idempotent: re-running rewrites the same block.

Run:  python scripts/fix_global_base_rules.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "vm_clone", "ui", "vm_theme.py")

BLOCK = """/* =====================================================================
   Global base
   ---------------------------------------------------------------------
   The window field is the LIGHT surface, not the chrome.  A generic rule that
   painted every QWidget with the chrome colour made all unstyled containers
   (tooltips included) dark, which put dark text on a dark field.  Chrome is
   applied per strip - menu bar, toolbars, status bar, rails - instead.
   See docs/UI_POLISH_AUDIT.md.
   ===================================================================== */
QMainWindow {{
    background-color: {T['bg_app']};
    color: {T['text_primary']};
    font-family: {T['font_stack']};
    font-size: {T['fs_label']}px;
    outline: none;
}}
QWidget {{
    /* Unstyled widgets must still inherit the design system's font and ink, or text
       falls back to the platform default and disagrees with every styled panel. */
    background-color: {T['bg_app']};
    color: {T['text_primary']};
    font-family: {T['font_stack']};
    font-size: {T['fs_label']}px;
    outline: none;
}}
QMainWindow::separator {{
    background-color: {T['border_subtle']};
    width: {T['sp_hair']}px;
    height: {T['sp_hair']}px;
}}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    src = open(TARGET, encoding="utf-8").read()

    start = src.find("/* =====================================================================\n   Global base")
    if start == -1:
        print("could not find the global base block - aborting")
        return 1
    # the block ends at the start of the next commented section
    nxt = src.find("/* =================", start + 10)
    if nxt == -1:
        print("could not find the end of the global base block - aborting")
        return 1

    src = src[:start] + BLOCK + "\n" + src[nxt:]
    print("global base rules normalised")
    if args.apply:
        open(TARGET, "w", encoding="utf-8").write(src)
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
