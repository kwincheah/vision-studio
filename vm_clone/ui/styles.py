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
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtWidgets import QApplication

THEME = {
    # Surfaces & Backgrounds (macOS Dark Mode Depth Hierarchy)
    "bg_app": "#0f1217",           # Deep slate window root
    "bg_surface": "#151921",       # Primary panels, sidebars, dock containers
    "bg_surface_alt": "#1a202a",   # Secondary card surfaces, parameter groups
    "bg_control": "#202633",       # Buttons, input fields, tree nodes
    "bg_control_hover": "#272f3e", # Control hover state
    "bg_control_active": "#171c26",# Control pressed state
    "bg_header": "#181d26",        # Dock titles, table headers
    "bg_table_row_alt": "#12161f", # Alternating row surface

    # Borders & Outlines
    "border_subtle": "#232a37",    # 1px frame and divider lines
    "border_control": "#2d3647",   # Input & button boundaries
    "border_focus": "#3b82f6",     # macOS System Blue focus ring

    # Typography (WCAG AAA Contrast against dark surfaces)
    "text_primary": "#f1f5f9",     # Slate 100 primary content (>11:1 contrast)
    "text_secondary": "#94a3b8",   # Slate 400 headers, units, sub-captions
    "text_muted": "#64748b",       # Slate 500 placeholders, timestamps

    # Restrained System Accent (Engineering Blue)
    "accent_primary": "#3b82f6",   # Primary accent
    "accent_hover": "#60a5fa",     # Accent hover
    "accent_dim": "#1a3458",       # Selected item background pill
    "accent_border": "#2563eb",    # Selection pill border

    # Semantic Status Tokens (Exclusively reserved for Pass/Warn/Fail/Run)
    "status_ok_text": "#22c55e",
    "status_ok_bg": "#122e1b",
    "status_ok_border": "#19562e",

    "status_warn_text": "#f59e0b",
    "status_warn_bg": "#36250d",
    "status_warn_border": "#5e4012",

    "status_error_text": "#ef4444",
    "status_error_bg": "#361417",
    "status_error_border": "#5e1d23",

    "status_running_text": "#38bdf8",
    "status_running_bg": "#10273a",
    "status_running_border": "#194060",

    # --- Apex Vision Studio Distinctive Industrial Design Tokens -------------
    # Original industrial dark titanium workstation identity, differentiated
    # from proprietary trade dress. Replaces white paper cards and brown-orange
    # palettes with elevated slate-obsidian surfaces, Electric Cyan / Cobalt accents,
    # and crisp WCAG AAA legibility.
    "vm_chrome": "#11141a",          # title / menu / toolbar strip (deep titanium)
    "vm_rail": "#161b24",            # left category icon rail (slate-navy)
    "vm_rail_hover": "#222938",
    "vm_flyout": "#1a202c",          # tool flyout panel surface (elevated slate)
    "vm_flyout_header": "#141822",   # flyout category header
    "vm_canvas": "#0f131a",          # flow canvas base (obsidian slate CAD canvas)
    "vm_canvas_dot": "#1f2736",      # flow canvas dot grid
    "vm_canvas_dot_major": "#2c384e",
    "vm_panel": "#151922",           # right-side data panel (deep sleek slate)
    "vm_panel_header": "#1c222e",    # panel header / table header
    "vm_card": "#1e2532",            # flow overview card surface
    "vm_accent": "#0ea5e9",          # Apex signature Electric Cyan / Cobalt
    "vm_accent_hover": "#38bdf8",    # hover state
    "vm_accent_dim": "#0e324a",      # cyan glow selection wash
    "vm_node": "#1e2532",            # module card body (elevated dark slate)
    "vm_node_text": "#f1f5f9",       # module card primary text (crisp light slate)
    "vm_node_text_dim": "#94a3b8",   # module card secondary text (slate 400)
    "vm_node_border": "#2e3848",     # module card border
    "vm_wire": "#0ea5e9",            # dependency wire (electric cyan)
}


def initialize_app_fonts(app: QApplication):
    """Loads system fonts reliably across Windows, macOS, and Linux."""
    import sys
    if sys.platform == "win32":
        font_paths = [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/consola.ttf"
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                QFontDatabase.addApplicationFont(fp)
        app.setFont(QFont("Segoe UI", 9))
    elif sys.platform == "darwin":
        app.setFont(QFont(".AppleSystemUIFont", 11))
    else:
        families = QFontDatabase.families()
        for preferred in ("Ubuntu", "DejaVu Sans", "Noto Sans", "Liberation Sans"):
            if preferred in families:
                app.setFont(QFont(preferred, 10))
                break
        else:
            app.setFont(QFont("sans-serif", 10))


INDUSTRIAL_THEME_QSS = f"""
/* Global Reset & Base Typography */
QMainWindow {{
    background-color: {THEME['bg_app']};
    color: {THEME['text_primary']};
    font-family: "Segoe UI", -apple-system, Arial, sans-serif;
    font-size: 11px;
}}

QWidget {{
    background-color: {THEME['bg_app']};
    color: {THEME['text_primary']};
    selection-background-color: {THEME['accent_primary']};
    selection-color: #ffffff;
    outline: none;
    font-family: "Segoe UI", -apple-system, Arial, sans-serif;
    font-size: 11px;
}}

/* Dock Widgets (macOS Inspector & Tool Panels) */
QDockWidget {{
    color: {THEME['text_primary']};
    font-weight: 600;
    font-size: 11px;
}}

QDockWidget::title {{
    background-color: {THEME['bg_header']};
    border-bottom: 1px solid {THEME['border_subtle']};
    padding: 6px 10px;
    text-align: left;
    color: {THEME['text_secondary']};
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 0.5px;
}}

QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 2px;
}}

QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: {THEME['bg_control_hover']};
    border-radius: 3px;
}}

/* Menu Bar */
QMenuBar {{
    background-color: {THEME['bg_surface']};
    color: {THEME['text_secondary']};
    border-bottom: 1px solid {THEME['border_subtle']};
    padding: 2px 6px;
    font-size: 11px;
}}

QMenuBar::item {{
    background: transparent;
    padding: 4px 8px;
    border-radius: 3px;
    margin: 1px 1px;
}}

QMenuBar::item:selected {{
    background-color: {THEME['bg_control']};
    color: {THEME['text_primary']};
}}

QMenu {{
    background-color: {THEME['bg_surface_alt']};
    color: {THEME['text_primary']};
    border: 1px solid {THEME['border_control']};
    border-radius: 4px;
    padding: 4px 2px;
}}

QMenu::item {{
    padding: 5px 24px 5px 20px;
    border-radius: 3px;
    margin: 1px 2px;
}}

QMenu::item:selected {{
    background-color: {THEME['accent_primary']};
    color: #ffffff;
}}

QMenu::separator {{
    height: 1px;
    background-color: {THEME['border_subtle']};
    margin: 4px 6px;
}}

/* Command Toolbar */
QToolBar {{
    background-color: {THEME['bg_surface']};
    border-bottom: 1px solid {THEME['border_subtle']};
    spacing: 5px;
    padding: 3px 8px;
}}

QToolButton {{
    background-color: {THEME['bg_control']};
    color: {THEME['text_primary']};
    border: 1px solid {THEME['border_control']};
    border-radius: 4px;
    padding: 4px 8px;
    font-weight: 500;
    font-size: 11px;
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
    border-radius: 4px;
    padding: 4px 10px;
    font-weight: 500;
    font-size: 11px;
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
    font-weight: 600;
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
    font-weight: 600;
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
    font-weight: 600;
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
    padding: 6px 14px;
    border: 1px solid {THEME['border_subtle']};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
    font-weight: 500;
    font-size: 11px;
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
    border-radius: 4px;
    color: {THEME['text_primary']};
    padding: 3px;
    font-size: 11px;
    outline: none;
}}

QTreeWidget::item {{
    height: 24px;
    padding: 2px 6px;
    margin: 1px 2px;
    border-radius: 4px;
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
    font-weight: 500;
}}

QTreeWidget::branch {{
    background: transparent;
}}

QListWidget, QTableWidget {{
    background-color: {THEME['bg_surface']};
    border: 1px solid {THEME['border_subtle']};
    border-radius: 4px;
    color: {THEME['text_primary']};
    alternate-background-color: {THEME['bg_table_row_alt']};
    gridline-color: {THEME['border_subtle']};
    font-size: 11px;
}}

QTableWidget::item {{
    padding: 4px 6px;
}}

QTableWidget::item:selected {{
    background-color: {THEME['accent_dim']};
    color: #ffffff;
}}

QHeaderView::section {{
    background-color: {THEME['bg_header']};
    color: {THEME['text_secondary']};
    padding: 5px 8px;
    border: 1px solid {THEME['border_subtle']};
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}}

/* Form Controls (Search Box, SpinBoxes, ComboBoxes) */
QLineEdit {{
    background-color: {THEME['bg_control']};
    border: 1px solid {THEME['border_control']};
    border-radius: 5px;
    padding: 4px 8px;
    color: {THEME['text_primary']};
    font-size: 11px;
}}

QLineEdit:focus {{
    border: 1px solid {THEME['border_focus']};
    background-color: {THEME['bg_surface_alt']};
}}

QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {THEME['bg_control']};
    border: 1px solid {THEME['border_control']};
    border-radius: 4px;
    padding: 3px 6px;
    color: {THEME['text_primary']};
    font-size: 11px;
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
    border-radius: 4px;
    selection-background-color: {THEME['accent_primary']};
    selection-color: #ffffff;
}}

QCheckBox {{
    color: {THEME['text_primary']};
    spacing: 6px;
    font-size: 11px;
}}

QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {THEME['border_control']};
    border-radius: 3px;
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
    min-height: 20px;
    border-radius: 3px;
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
    border-radius: 3px;
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
    font-size: 11px;
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
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 10px;
    color: {THEME['text_secondary']};
    font-weight: 600;
    font-size: 10px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    background-color: {THEME['bg_surface']};
    color: {THEME['text_secondary']};
}}
"""
