"""
Core UI Theme & Design Tokens for Apex Industrial Vision Studio.
Grounded in Apple Human Interface Guidelines adapted for Desktop Industrial Engineering:
- Strict depth hierarchy: Root window -> Surfaces/Docks -> Controls/Cards (color.md, dark-mode.md)
- WCAG AAA contrast typography with primary, secondary, and muted hierarchy (typography.md, accessibility.md)
- Single restrained accent (Engineering Blue) for focus rings and selection states (color.md)
- Rounded selection pills with subtle accent borders for tree and list items (sidebars.md, focus-and-selection.md)
- Semantic status strictness: Green, Amber, Red exclusively for verified functional states (color.md)
"""
import os
from typing import Dict

from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtWidgets import QApplication

THEME = {
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
}

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
    """Snap an arbitrary pixel gap onto the spacing scale.

    Ties round *up*, because a control that is slightly too roomy reads better than one
    whose content touches its border.
    """
    return min(SPACE.values(), key=lambda step: (abs(step - value), -step))


def _preferred_family(app: QApplication) -> str:
    """The first installed family from the token font stack."""
    families = set(QFontDatabase.families())
    for candidate in FONT_STACK.split(","):
        candidate = candidate.strip().strip("'\"")
        if candidate in families:
            return candidate
    return FONT_FAMILY


def _point_size_for(px: int) -> float:
    """Convert a CSS pixel size to points for the application-font channel.

    Qt reports a font set with `setPixelSize` as `pointSize() == -1`, and widgets that
    read the point size then warn and fall back - the tab bar does this when it applies
    the stylesheet's font (`QFont::setPointSize: Point size <= 0 (-1)`).  Expressing the
    application font in points keeps both channels readable; they agree because the
    conversion uses the same logical DPI Qt lays out with.
    """
    from PyQt6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    dpi = screen.logicalDotsPerInch() if screen is not None else 96.0
    if not dpi or dpi <= 0:
        dpi = 96.0
    return px * 72.0 / dpi


def initialize_app_fonts(app: QApplication):
    """Load the UI font and set the application default.

    Qt has two font channels: the application font set here, which unstyled widgets
    inherit, and the `font-size` a stylesheet declares, which overrides it for styled
    widgets.  When the two disagreed, text in a styled panel and text in an unstyled
    one rendered at different sizes - the "inconsistent typography" the audit reported.
    Both are driven from `TYPE['body']` here.
    """
    import sys
    if sys.platform == "win32":
        for fp in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                   "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/consola.ttf"):
            if os.path.exists(fp):
                QFontDatabase.addApplicationFont(fp)

    base = QFont(_preferred_family(app))
    base.setPointSizeF(_point_size_for(TYPE["body"]))
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
    f.setPointSizeF(_point_size_for(font_px(size_key)))
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



INDUSTRIAL_THEME_QSS = f"""
/* Global Reset & Base Typography */
QMainWindow {{
    background-color: {THEME['bg_app']};
    color: {THEME['text_primary']};
    font-family: "Segoe UI", -apple-system, Arial, sans-serif;
    font-size: {THEME['fs_body']}px;
}}

QWidget {{
    background-color: {THEME['bg_app']};
    color: {THEME['text_primary']};
    selection-background-color: {THEME['accent_primary']};
    selection-color: #ffffff;
    outline: none;
    font-family: "Segoe UI", -apple-system, Arial, sans-serif;
    font-size: {THEME['fs_body']}px;
}}

/* Dock Widgets (macOS Inspector & Tool Panels) */
QDockWidget {{
    color: {THEME['text_primary']};
    font-weight: {THEME['fw_demibold']};
    font-size: {THEME['fs_body']}px;
}}

QDockWidget::title {{
    background-color: {THEME['bg_header']};
    border-bottom: 1px solid {THEME['border_subtle']};
    padding: {THEME['sp_snug']}px {THEME['sp_loose']}px;
    text-align: left;
    color: {THEME['text_secondary']};
    font-weight: {THEME['fw_demibold']};
    font-size: {THEME['fs_caption']}px;
    letter-spacing: 0.5px;
}}

QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: {THEME['sp_hair']}px;
}}

QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: {THEME['bg_control_hover']};
    border-radius: {THEME['r_control']}px;
}}

/* Menu Bar */
QMenuBar {{
    background-color: {THEME['bg_surface']};
    color: {THEME['text_secondary']};
    border-bottom: 1px solid {THEME['border_subtle']};
    padding: {THEME['sp_hair']}px {THEME['sp_snug']}px;
    font-size: {THEME['fs_body']}px;
}}

QMenuBar::item {{
    background: transparent;
    padding: {THEME['sp_tight']}px {THEME['sp_base']}px;
    border-radius: {THEME['r_control']}px;
    margin: {THEME['sp_hair']}px {THEME['sp_hair']}px;
}}

QMenuBar::item:selected {{
    background-color: {THEME['bg_control']};
    color: {THEME['text_primary']};
}}

QMenu {{
    background-color: {THEME['bg_surface_alt']};
    color: {THEME['text_primary']};
    border: 1px solid {THEME['border_control']};
    border-radius: {THEME['r_panel']}px;
    padding: {THEME['sp_tight']}px {THEME['sp_hair']}px;
}}

QMenu::item {{
    padding: {THEME['sp_tight']}px {THEME['sp_section']}px {THEME['sp_tight']}px {THEME['sp_loose']}px;
    border-radius: {THEME['r_control']}px;
    margin: {THEME['sp_hair']}px {THEME['sp_hair']}px;
}}

QMenu::item:selected {{
    background-color: {THEME['accent_primary']};
    color: #ffffff;
}}

QMenu::separator {{
    height: 1px;
    background-color: {THEME['border_subtle']};
    margin: {THEME['sp_tight']}px {THEME['sp_snug']}px;
}}

/* Command Toolbar */
QToolBar {{
    background-color: {THEME['bg_surface']};
    border-bottom: 1px solid {THEME['border_subtle']};
    spacing: 5px;
    padding: {THEME['sp_tight']}px {THEME['sp_base']}px;
}}

QToolButton {{
    background-color: {THEME['bg_control']};
    color: {THEME['text_primary']};
    border: 1px solid {THEME['border_control']};
    border-radius: {THEME['r_panel']}px;
    padding: {THEME['sp_tight']}px {THEME['sp_base']}px;
    font-weight: {THEME['fw_medium']};
    font-size: {THEME['fs_body']}px;
}}

QToolButton:hover {{
    background-color: {THEME['bg_control_hover']};
    border-color: {THEME['border_focus']};
    color: #ffffff;
}}

QToolButton:pressed {{
    background-color: {THEME['bg_control_active']};
}}

/* Standard Push Buttons */
QPushButton {{
    background-color: {THEME['bg_control']};
    color: {THEME['text_primary']};
    border: 1px solid {THEME['border_control']};
    border-radius: {THEME['r_panel']}px;
    padding: {THEME['sp_tight']}px {THEME['sp_loose']}px;
    font-weight: {THEME['fw_medium']};
    font-size: {THEME['fs_body']}px;
}}

QPushButton:hover {{
    background-color: {THEME['bg_control_hover']};
    border-color: {THEME['border_focus']};
    color: #ffffff;
}}

QPushButton:pressed {{
    background-color: {THEME['bg_control_active']};
}}

/* Primary Execution Controls (Prominent Semantic Styling) */
QPushButton#btnRunOnce {{
    background-color: {THEME['status_ok_bg']};
    border: 1px solid {THEME['status_ok_border']};
    color: {THEME['status_ok_text']};
    font-weight: {THEME['fw_demibold']};
}}

QPushButton#btnRunOnce:hover {{
    background-color: #163d24;
    border-color: {THEME['status_ok_text']};
    color: #ffffff;
}}

QPushButton#btnContinuous {{
    background-color: {THEME['bg_control']};
    border: 1px solid {THEME['border_control']};
    color: {THEME['text_primary']};
    font-weight: {THEME['fw_demibold']};
}}

QPushButton#btnContinuous:hover {{
    background-color: {THEME['bg_control_hover']};
    border-color: {THEME['status_warn_text']};
    color: #ffffff;
}}

QPushButton#btnContinuous:checked {{
    background-color: {THEME['status_warn_bg']};
    border: 1px solid {THEME['status_warn_border']};
    color: {THEME['status_warn_text']};
}}

QPushButton#btnStop {{
    background-color: {THEME['status_error_bg']};
    border: 1px solid {THEME['status_error_border']};
    color: {THEME['status_error_text']};
    font-weight: {THEME['fw_demibold']};
}}

QPushButton#btnStop:hover {{
    background-color: #4a1c20;
    border-color: {THEME['status_error_text']};
    color: #ffffff;
}}

/* Central Workspace Tab Widgets */
QTabWidget::pane {{
    border: 1px solid {THEME['border_subtle']};
    background-color: {THEME['bg_app']};
}}

QTabBar::tab {{
    background-color: {THEME['bg_surface']};
    color: {THEME['text_secondary']};
    padding: {THEME['sp_snug']}px {THEME['sp_section']}px;
    border: 1px solid {THEME['border_subtle']};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
    font-weight: {THEME['fw_medium']};
    font-size: {THEME['fs_body']}px;
}}

QTabBar::tab:selected {{
    background-color: {THEME['bg_surface_alt']};
    color: #ffffff;
    border-bottom: 2px solid {THEME['accent_primary']};
}}

QTabBar::tab:hover:!selected {{
    background-color: {THEME['bg_control']};
    color: {THEME['text_primary']};
}}

/* Sidebar Tool Tree with Apple HIG Rounded Selection Pills */
QTreeWidget {{
    background-color: {THEME['bg_surface']};
    border: 1px solid {THEME['border_subtle']};
    border-radius: {THEME['r_panel']}px;
    color: {THEME['text_primary']};
    padding: {THEME['sp_hair']}px;
    font-size: {THEME['fs_body']}px;
    outline: none;
}}

QTreeWidget::item {{
    height: 24px;
    padding: {THEME['sp_hair']}px {THEME['sp_snug']}px;
    margin: {THEME['sp_hair']}px {THEME['sp_hair']}px;
    border-radius: {THEME['r_panel']}px;
    border: 1px solid transparent;
}}

QTreeWidget::item:hover {{
    background-color: rgba(255, 255, 255, 0.05);
    color: #ffffff;
}}

QTreeWidget::item:selected {{
    background-color: {THEME['accent_dim']};
    border: 1px solid {THEME['accent_border']};
    color: #ffffff;
    font-weight: {THEME['fw_medium']};
}}

QTreeWidget::branch {{
    background: transparent;
}}

QListWidget, QTableWidget {{
    background-color: {THEME['bg_surface']};
    border: 1px solid {THEME['border_subtle']};
    border-radius: {THEME['r_panel']}px;
    color: {THEME['text_primary']};
    alternate-background-color: {THEME['bg_table_row_alt']};
    gridline-color: {THEME['border_subtle']};
    font-size: {THEME['fs_body']}px;
}}

QTableWidget::item {{
    padding: {THEME['sp_tight']}px {THEME['sp_snug']}px;
}}

QTableWidget::item:selected {{
    background-color: {THEME['accent_dim']};
    color: #ffffff;
}}

QHeaderView::section {{
    background-color: {THEME['bg_header']};
    color: {THEME['text_secondary']};
    padding: {THEME['sp_tight']}px {THEME['sp_base']}px;
    border: 1px solid {THEME['border_subtle']};
    font-weight: {THEME['fw_demibold']};
    font-size: {THEME['fs_caption']}px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}}

/* Form Controls (Search Box, SpinBoxes, ComboBoxes) */
QLineEdit {{
    background-color: {THEME['bg_control']};
    border: 1px solid {THEME['border_control']};
    border-radius: {THEME['r_panel']}px;
    padding: {THEME['sp_tight']}px {THEME['sp_base']}px;
    color: {THEME['text_primary']};
    font-size: {THEME['fs_body']}px;
}}

QLineEdit:focus {{
    border: 1px solid {THEME['border_focus']};
    background-color: {THEME['bg_surface_alt']};
}}

QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {THEME['bg_control']};
    border: 1px solid {THEME['border_control']};
    border-radius: {THEME['r_panel']}px;
    padding: {THEME['sp_tight']}px {THEME['sp_snug']}px;
    color: {THEME['text_primary']};
    font-size: {THEME['fs_body']}px;
}}

QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {THEME['border_focus']};
    background-color: {THEME['bg_surface_alt']};
}}

QComboBox::drop-down {{
    border: none;
    width: 18px;
}}

QComboBox QAbstractItemView {{
    background-color: {THEME['bg_surface_alt']};
    border: 1px solid {THEME['border_control']};
    border-radius: {THEME['r_panel']}px;
    selection-background-color: {THEME['accent_primary']};
    selection-color: #ffffff;
}}

QCheckBox {{
    color: {THEME['text_primary']};
    spacing: 6px;
    font-size: {THEME['fs_body']}px;
}}

QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {THEME['border_control']};
    border-radius: {THEME['r_control']}px;
    background-color: {THEME['bg_control']};
}}

QCheckBox::indicator:checked {{
    background-color: {THEME['accent_primary']};
    border-color: {THEME['accent_hover']};
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: {THEME['bg_app']};
    width: 7px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {THEME['border_control']};
    min-height: {THEME['h_icon_md']}px;
    border-radius: {THEME['r_control']}px;
}}

QScrollBar::handle:vertical:hover {{
    background: {THEME['text_muted']};
}}

QScrollBar:horizontal {{
    background: {THEME['bg_app']};
    height: 7px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {THEME['border_control']};
    min-width: 20px;
    border-radius: {THEME['r_control']}px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {THEME['text_muted']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    height: 0px;
    width: 0px;
}}

/* Status Bar & Splitters */
QStatusBar {{
    background-color: {THEME['bg_app']};
    color: {THEME['text_muted']};
    border-top: 1px solid {THEME['border_subtle']};
    font-size: {THEME['fs_body']}px;
}}

QSplitter::handle {{
    background-color: {THEME['border_subtle']};
}}

QSplitter::handle:hover {{
    background-color: {THEME['accent_primary']};
}}

/* Dialogs */
QDialog {{
    background-color: {THEME['bg_surface']};
    color: {THEME['text_primary']};
}}

/* Group Boxes */
QGroupBox {{
    border: 1px solid {THEME['border_subtle']};
    border-radius: {THEME['r_panel']}px;
    margin-top: 8px;
    padding-top: 10px;
    color: {THEME['text_secondary']};
    font-weight: {THEME['fw_demibold']};
    font-size: {THEME['fs_caption']}px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 {THEME['sp_tight']}px;
    background-color: {THEME['bg_surface']};
    color: {THEME['text_secondary']};
}}
"""
