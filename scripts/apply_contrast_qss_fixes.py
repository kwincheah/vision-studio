"""Re-apply the contrast fixes to the theme stylesheet after a retint.

The palette work and the contrast work are separate passes: `retint_ui.py` moves the
theme onto the measured palette, while this applies the *accessibility* corrections
that a palette move alone does not give you - dark ink on dark chrome, chrome-grey
input wells, decorative borders, invisible tooltips, and selection states.  Running
the retint alone leaves the UI on the right colours but with unreadable text, so this
must follow it.

Every substitution here is a measured fix; see `docs/UI_POLISH_AUDIT.md` §1.

Run:  python scripts/apply_contrast_qss_fixes.py --check
      python scripts/apply_contrast_qss_fixes.py --apply
"""
import argparse
import os
import sys
from typing import List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "vm_clone", "ui", "vm_theme.py")

#: (description, exact old text, exact new text)
EDITS: List[Tuple[str, str, str]] = [
    # ---- global base: the catch-all must not paint the chrome colour --------
    (
        "split the global base off the chrome",
        """QMainWindow, QWidget {{
    background-color: {T['vm_chrome']};""",
        """QMainWindow {{
    background-color: {T['bg_app']};""",
    ),
    # ---- menu bar carries the reference's dark ink -------------------------
    (
        "menu bar ink -> measured dark menu ink",
        """QMenuBar {{
    background-color: {T['vm_chrome']};
    color: {T['text_primary']};""",
        """QMenuBar {{
    background-color: {T['vm_chrome']};
    color: {T['text_on_menu']};""",
    ),
    # ---- QMenu is a light surface -----------------------------------------
    (
        "menu dropdown -> light surface with dark ink",
        """QMenu {{
    background-color: {T['bg_header']};
    color: {T['border_subtle']};
    border: 1px solid {T['bg_control_hover']};""",
        """QMenu {{
    background-color: {T['bg_surface_alt']};
    color: {T['text_primary']};
    border: 1px solid {T['border_control']};""",
    ),
    (
        "menu selection -> accent blue with white ink",
        """QMenu::item:selected {{
    background-color: {T['f8fafb']};""",
        """QMenu::item:selected {{
    background-color: {T['bg_surface_alt']};""",
    ),
    # ---- toolbars: darker chrome, light glyphs ----------------------------
    (
        "toolbar strip -> darker chrome",
        """QToolBar {{
    background-color: {T['vm_chrome']};
    border: none;
    border-bottom: 1px solid {T['bg_app']};""",
        """QToolBar {{
    background-color: {T['vm_chrome_dark']};
    border: none;
    border-bottom: 1px solid {T['border_subtle']};""",
    ),
    (
        "toolbar buttons -> dark ink (they are light control faces)",
        """QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 4px;
    color: {T['text_primary']};""",
        """QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 4px;
    color: {T['text_on_chrome']};""",
    ),
    (
        "toolbar spacer must not paint a surface",
        """QToolButton {{""",
        """QToolBar > QWidget {{
    background: transparent;
}}
QToolButton {{""",
    ),
    # ---- flow tab bar ------------------------------------------------------
    (
        "flow tab bar -> darker chrome",
        """QTabBar#flowTabBar {{
    background-color: {T['vm_chrome']};
}}""",
        """QTabBar#flowTabBar {{
    background-color: {T['vm_chrome_dark']};
}}""",
    ),
    (
        "flow tab ink -> chrome ink",
        """QTabBar#flowTabBar::tab {{
    background-color: {T['bg_header']};
    color: {T['text_secondary']};""",
        """QTabBar#flowTabBar::tab {{
    background-color: {T['vm_chrome_dark']};
    color: {T['text_on_chrome']};""",
    ),
    (
        "flow tab selected -> amber fill with dark ink",
        """QTabBar#flowTabBar::tab:selected {{
    background-color: {T['border_subtle']};
    color: {T['text_primary']};
    border-color: {T['border_control']};""",
        """QTabBar#flowTabBar::tab:selected {{
    background-color: {T['vm_accent']};
    color: {T['text_primary']};
    border-color: {T['accent_border']};""",
    ),
    (
        "flow tab hover -> rail hover tone",
        """QTabBar#flowTabBar::tab:hover:!selected {{
    background-color: {T['vm_canvas_dot']};""",
        """QTabBar#flowTabBar::tab:hover:!selected {{
    background-color: {T['vm_rail_hover']};""",
    ),
    (
        "flow tab scroller buttons -> light control face",
        """QTabBar#flowTabBar QToolButton {{
    background-color: {T['bg_header']};
    border: 1px solid {T['bg_control_hover']};
    color: {T['text_secondary']};""",
        """QTabBar#flowTabBar QToolButton {{
    background-color: {T['bg_control']};
    border: 1px solid {T['border_control']};
    color: {T['text_primary']};""",
    ),
    # ---- status bar: dark chrome, light ink --------------------------------
    (
        "status bar -> darker chrome with chrome ink",
        """QStatusBar {{
    background-color: {T['vm_chrome']};
    color: {T['vm_node_text_dim']};
    border-top: 1px solid {T['bg_app']};""",
        """QStatusBar {{
    background-color: {T['vm_chrome_dark']};
    color: {T['text_on_chrome']};
    border-top: 1px solid {T['border_subtle']};""",
    ),
    (
        "status segment ink",
        """QLabel#statusSegment {{
    color: {T['vm_node_text_dim']};
    padding: 2px 10px;
    border-left: 1px solid {T['bg_control']};""",
        """QLabel#statusSegment {{
    color: {T['text_on_chrome']};
    padding: 2px 10px;
    border-left: 1px solid {T['vm_rail_hover']};""",
    ),
    (
        "status leading ink",
        """QLabel#statusLeading {{
    color: {T['text_secondary']};""",
        """QLabel#statusLeading {{
    color: {T['text_on_chrome']};""",
    ),
    (
        "status message ink",
        """QLabel#statusMessage {{
    color: {T['vm_node_text_dim']};""",
        """QLabel#statusMessage {{
    color: {T['text_on_chrome']};""",
    ),
    # ---- image strip rides the same chrome ---------------------------------
    (
        "image strip -> darker chrome",
        """QListWidget#imageStrip {{
    background-color: {T['vm_chrome']};""",
        """QListWidget#imageStrip {{
    background-color: {T['vm_chrome_dark']};""",
    ),
    (
        "image strip item borders -> visible on chrome",
        """QListWidget#imageStrip::item {{
    border: 1px solid {T['bg_control_hover']};""",
        """QListWidget#imageStrip::item {{
    border: 1px solid {T['vm_rail_hover']};""",
    ),
    (
        "image strip item hover",
        """QListWidget#imageStrip::item:hover {{
    border-color: {T['border_control']};""",
        """QListWidget#imageStrip::item:hover {{
    border-color: {T['text_on_chrome']};""",
    ),
    # ---- rail selection ----------------------------------------------------
    (
        "rail checked edge -> deepened amber",
        """QToolButton#railCategory:checked {{
    background-color: {T['vm_flyout']};
    border-left: 3px solid {T['vm_accent']};""",
        """QToolButton#railCategory:checked {{
    /* The selected glyph is re-rendered in dark ink by the rail widget; swapping
       only the fill would leave a light glyph on a light square. */
    background-color: {T['vm_flyout']};
    border-left: 3px solid {T['accent_border']};
    border-top: 1px solid {T['accent_border']};
    border-bottom: 1px solid {T['accent_border']};""",
    ),
    # ---- form controls are light wells -------------------------------------
    (
        "spin/combo -> light well",
        """QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {T['bg_header']};""",
        """QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {T['bg_surface_alt']};""",
    ),
    (
        "spin/combo focus -> white well",
        """QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {T['accent_primary']};
}}""",
        """QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {T['border_focus']};
    background-color: #ffffff;
}}""",
    ),
    (
        "combo popup -> white list, white-on-accent selection",
        """QComboBox QAbstractItemView {{
    background-color: {T['bg_header']};
    border: 1px solid {T['border_control']};
    selection-background-color: {T['accent_primary']};
    color: {T['text_primary']};""",
        """QComboBox QAbstractItemView {{
    background-color: #ffffff;
    border: 1px solid {T['border_control']};
    selection-background-color: {T['accent_primary']};
    selection-color: #ffffff;
    color: {T['text_primary']};""",
    ),
    # ---- tooltips and dialogs are light surfaces ---------------------------
    (
        "dialog -> light surface",
        """QDialog {{
    background-color: {T['bg_header']};""",
        """QDialog {{
    background-color: {T['bg_surface']};""",
    ),
    (
        "tooltip -> light surface with dark ink",
        """QToolTip {{
    background-color: {T['bg_app']};""",
        """QToolTip {{
    background-color: {T['bg_surface_alt']};""",
    ),
    (
        "progress bar -> light well",
        """QProgressBar {{
    background-color: {T['bg_header']};""",
        """QProgressBar {{
    background-color: {T['bg_surface_alt']};""",
    ),
    # ---- selection edge for tree / node states -----------------------------
    (
        "tree selection edge -> deepened amber",
        """QTreeWidget::item:selected {{
    background-color: {T['accent_dim']};
    border: 1px solid {T['vm_accent']};""",
        """QTreeWidget::item:selected {{
    background-color: {T['accent_dim']};
    border: 1px solid {T['accent_border']};""",
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    src = open(TARGET, encoding="utf-8").read()
    applied, skipped = 0, []

    for label, old, new in EDITS:
        if old in src:
            src = src.replace(old, new, 1)
            applied += 1
        elif new in src:
            skipped.append(f"{label} (already applied)")
        else:
            skipped.append(f"{label} (PATTERN NOT FOUND)")

    print(f"{applied}/{len(EDITS)} contrast fix(es) applied")
    for s in skipped:
        print(f"  skipped: {s}")

    if args.apply:
        open(TARGET, "w", encoding="utf-8").write(src)
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
