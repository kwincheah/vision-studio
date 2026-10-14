"""Install the design-token layer into `vm_clone/ui/styles.py`.

Idempotent: re-running on an already-tokenised file reports "already applied".  Kept as
a script rather than hand-edits because a `git checkout` of the stylesheet modules
previously reverted the tokens along with an unrelated experiment, and this makes the
layer reproducible.

Run:  python scripts/install_design_tokens.py [--apply]
"""
import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "vm_clone", "ui", "styles.py")

IMPORT_OLD = """import os
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtWidgets import QApplication
"""

IMPORT_NEW = """import os
from typing import Dict

from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtWidgets import QApplication
"""

TOKEN_BLOCK = '''

# ===========================================================================
# Design-system tokens
# ---------------------------------------------------------------------------
# The palette above is *colour*.  These are the dimensions and the type ramp that make
# components of the same kind look like the same component.  They live here rather than
# inline in each widget because a measured audit found 383 hardcoded visual constants
# across `vm_clone/ui` - 24 distinct margin tuples, 29 padding shorthands, 12 spacings,
# 5 radii and 6 font sizes - which is what made equivalent controls differ between
# panels.  See `docs/DESIGN_SYSTEM.md`.
#
# Sizes are CSS pixels because Qt's stylesheet channel (`font-size: Npx`) is what
# resolves for styled widgets; `initialize_app_fonts` drives the application-font
# channel from the same value so the two cannot disagree.
# ===========================================================================

#: Type ramp.  `body` is the default; every other size has a distinct role.
TYPE = {
    "micro": 10,      # build stamps, axis ticks, calibration readouts
    "caption": 11,    # secondary labels, units, table sub-captions
    "body": 12,       # default UI text: buttons, fields, tables, panels
    "label": 13,      # form labels, dialog body, module card text
    "subtitle": 14,   # section headings
    "title": 16,      # dialog and page titles
}

#: Font weights, named for the role rather than the number.
WEIGHT = {
    "regular": 400,
    "medium": 500,
    "demibold": 600,
    "bold": 700,
}

#: Every text size the ramp permits.
TYPE_SCALE = tuple(sorted(set(TYPE.values())))

#: Control heights, in pixels, each named for a *purpose* so a widget picks the tier
#: matching its role instead of inventing a height.
SIZE = {
    "input": 24,          # single-line text, numeric and combo fields
    "button": 26,         # standard push buttons
    "compact": 24,        # icon-only buttons in dense rows
    "toolbar": 30,        # the measured command-strip button
    "tab": 26,            # tab-bar and panel-header rows
    "row": 24,            # table and tree row pitch
    "header": 30,         # table header
    "toolbar_strip": 30,
    "status_strip": 24,
    "indicator": 13,      # check-box / radio glyph
    "icon_sm": 16,
    "icon_md": 20,
    "icon_lg": 24,
}

#: Spacing scale.  Off-scale gaps are snapped with `nearest_space`.
SPACE = {
    "none": 0,
    "hair": 2,      # between a label and its own indicator
    "tight": 4,     # inside a dense row
    "snug": 6,      # between related controls
    "base": 8,      # default gap and panel padding
    "loose": 12,    # between groups
    "section": 16,  # between sections
}

#: Corner radii: controls, containers, and pills.
RADIUS = {"none": 0, "control": 3, "panel": 4, "pill": 9}

#: Border widths.
BORDER = {"none": 0, "hair": 1, "focus": 2, "selected": 2}

#: The font stack, so a stylesheet rule and a `QFont` fall back identically.
FONT_STACK = "Segoe UI, Noto Sans, Ubuntu, DejaVu Sans, Arial, sans-serif"
#: Family used when constructing a `QFont` in code.
FONT_FAMILY = "Segoe UI"

#: Flat names for the stylesheet vocabulary.  The dicts above are the source of truth;
#: generating the keys keeps a rule (`font-size: {T['fs_body']}px`) and the ramp from
#: ever disagreeing.
THEME.update({f"fs_{k}": v for k, v in TYPE.items()})
THEME.update({f"fw_{k}": v for k, v in WEIGHT.items()})
THEME.update({f"h_{k}": v for k, v in SIZE.items()})
THEME.update({f"r_{k}": v for k, v in RADIUS.items()})
THEME.update({f"sp_{k}": v for k, v in SPACE.items()})
THEME.update({f"bw_{k}": v for k, v in BORDER.items()})
THEME["font_stack"] = FONT_STACK


def font_px(size_key: str = "body") -> int:
    """Pixel size for a type-ramp role."""
    return TYPE.get(size_key, TYPE["body"])


def font_weight(weight_key: str = "regular") -> int:
    """Numeric weight for a named weight role."""
    return WEIGHT.get(weight_key, WEIGHT["regular"])


def control_h(size_key: str = "button") -> int:
    """Pixel height for a control role."""
    return SIZE.get(size_key, SIZE["button"])


def space(space_key: str = "base") -> int:
    """Pixel gap for a spacing role."""
    return SPACE.get(space_key, SPACE["base"])


def corner_radius(radius_key: str = "control") -> int:
    """Pixel corner radius for a role."""
    return RADIUS.get(radius_key, RADIUS["control"])


def nearest_space(value: int) -> int:
    """Snap an arbitrary pixel gap onto the spacing scale."""
    return min(SPACE.values(), key=lambda step: (abs(step - value), step))


def _preferred_family(app: QApplication) -> str:
    """The first installed family from the token font stack."""
    families = set(QFontDatabase.families())
    for candidate in FONT_STACK.split(","):
        candidate = candidate.strip().strip("'\\"")
        if candidate in families:
            return candidate
    return FONT_FAMILY


def initialize_app_fonts(app: QApplication):
    """Load the UI font and set the application default.

    Qt has two font channels: the application font set here, which unstyled widgets
    inherit, and the `font-size` a stylesheet declares, which overrides it for styled
    widgets.  When the two disagreed, text in a styled panel and text in an unstyled
    one rendered at different sizes - the "inconsistent typography" of the audit.  Both
    channels are driven from `TYPE['body']` here, and rendered at an explicit pixel size
    so the result does not drift with the screen's logical DPI.
    """
    import sys
    if sys.platform == "win32":
        for fp in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                   "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/consola.ttf"):
            if os.path.exists(fp):
                QFontDatabase.addApplicationFont(fp)

    base = QFont(_preferred_family(app))
    base.setPixelSize(TYPE["body"])
    base.setWeight(QFont.Weight.Normal)
    app.setFont(base)


def apply_type(widget, size_key: str = "body", weight_key: str = "regular"):
    """Set a widget's font from the type ramp.

    Prefer this to constructing `QFont(family, size)` inline: the audit found 33 such
    constructions using six different sizes, which is why labels in the flow editor,
    the canvas and the dialogs disagreed with each other.
    """
    f = widget.font()
    f.setFamily(FONT_FAMILY)
    f.setPixelSize(font_px(size_key))
    f.setWeight(QFont.Weight(font_weight(weight_key)))
    widget.setFont(f)
    return f


def ramp_report() -> Dict[str, object]:
    """The design tokens, for documentation and the validation tests."""
    return {
        "type": dict(TYPE),
        "weights": dict(WEIGHT),
        "sizes": dict(SIZE),
        "spacing": dict(SPACE),
        "radius": dict(RADIUS),
        "border": dict(BORDER),
        "font_stack": FONT_STACK,
    }
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    src = open(TARGET, encoding="utf-8").read()
    if "Design-system tokens" in src:
        print("already applied")
        return 0

    if IMPORT_OLD not in src:
        print("could not find the import block - aborting")
        return 1
    src = src.replace(IMPORT_OLD, IMPORT_NEW, 1)

    # Insert the token block right after the THEME dict literal.
    marker = "\n\n\ndef initialize_app_fonts(app: QApplication):"
    if marker not in src:
        print("could not find initialize_app_fonts - aborting")
        return 1
    head, tail = src.split(marker, 1)
    # drop the old implementation and keep whatever follows it
    end = tail.find("\n\n\nINDUSTRIAL_THEME_QSS")
    if end == -1:
        print("could not find the QSS template - aborting")
        return 1
    rest = tail[end:]
    src = head + TOKEN_BLOCK + rest

    print(f"token layer installed ({len(src)} chars)")
    if args.apply:
        open(TARGET, "w", encoding="utf-8").write(src)
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
