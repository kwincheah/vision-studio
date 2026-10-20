"""VisionMaster-aligned widget stylesheet.

Every token used here is grounded in the bundled HikRobot Vision Master manual
(`HikRobotVMHelp_compressed.pdf`).  Reference pages used as measurable design
evidence:

* p.40  Home Page        - menu bar / control toolbar / left category rail /
                          flow tab bar / Image|Result right panel / status bar
* p.70  Control Toolbar  - exact icon inventory and ordering
* p.72  Tool Box         - vertical category rail with popup tool grid
* p.74  Tool grid        - flyout with icon-above-label cells, white module cards
* p.87  Result Display   - "Param Name | Current Result | Global Variable" grid
* p.95  Multi-Flow       - white flow cards with playback controls and timings

The original Industrial Light/Dark identity of this project is preserved: the
same single restrained engineering blue remains the focus/selection hue for
inspector inputs, while the sampled VisionMaster orange is used strictly for
module numbering, flow mapping and dependency wires.
"""
from vm_clone.ui.styles import THEME

T = THEME


def check_icon_url(colour: str = "#1a2024") -> str:
    """A ``url(...)``-ready path to a tick mark PNG in ``colour`` (created on first use).

    QSS cannot draw a tick, so the checked-indicator image is rendered once with OpenCV
    into the temp folder; a failure just means checked boxes show a plain fill.
    """
    import os
    import tempfile
    try:
        import cv2
        import numpy as np
        path = os.path.join(tempfile.gettempdir(), f"apex_check_{colour.lstrip('#')}.png")
        if not os.path.exists(path):
            size = 60
            img = np.zeros((size, size, 4), np.uint8)
            rgb = tuple(int(colour.lstrip('#')[k:k + 2], 16) for k in (4, 2, 0))
            pts = np.array([[14, 31], [25, 42], [46, 18]], np.int32)
            cv2.polylines(img, [pts], False, rgb + (255,), 7, cv2.LINE_AA)
            ok, buf = cv2.imencode(".png", img)
            if not ok:
                return "none"
            buf.tofile(path)
        return path.replace("\\", "/")
    except Exception:
        return "none"


VM_THEME_QSS = f"""
/* =====================================================================
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

/* =====================================================================
   Menu bar
   ===================================================================== */
QMenuBar {{
    background-color: {T['vm_chrome']};
    color: {T['text_on_menu']};
    border: none;
    padding: 0 {T['sp_tight']}px 0 {T['sp_section']}px;   /* left inset leaves room for the brand mark */
    font-size: {T['fs_label']}px;
}}
QMenuBar::item {{
    background: transparent;
    padding: {T['sp_tight']}px {T['sp_base']}px;
    margin: {T['sp_hair']}px 0;
    border-radius: {T['r_control']}px;
}}
QMenuBar::item:selected {{
    background-color: {T['vm_canvas_dot']};
    color: {T['text_primary']};
}}
QMenuBar::item:pressed {{
    background-color: {T['vm_accent']};
    color: {T['text_primary']};
}}

QMenu {{
    background-color: {T['bg_surface_alt']};
    color: {T['text_primary']};
    border: 1px solid {T['border_control']};
    padding: {T['sp_tight']}px {T['sp_hair']}px;
}}
QMenu::item {{
    padding: {T['sp_tight']}px {T['sp_section']}px {T['sp_tight']}px {T['sp_section']}px;
    margin: {T['sp_hair']}px {T['sp_tight']}px;
    border-radius: {T['r_control']}px;
}}
QMenu::item:selected {{
    background-color: {T['bg_surface_alt']};
    color: {T['text_primary']};
}}
QMenu::item:disabled {{
    color: {T['text_muted']};
}}
QMenu::separator {{
    height: 1px;
    background-color: {T['bg_control_hover']};
    margin: {T['sp_tight']}px {T['sp_base']}px;
}}
QMenu::icon {{
    padding-left: 6px;
}}
QMenu::indicator {{
    width: 14px;
    height: 14px;
    margin-left: 6px;
}}

/* =====================================================================
   Control toolbar
   ===================================================================== */
QToolBar {{
    background-color: {T['vm_chrome_dark']};
    border: none;
    border-bottom: 1px solid {T['border_subtle']};
    spacing: 1px;
    padding: {T['sp_snug']}px {T['sp_snug']}px;
}}
QToolBar::separator {{
    background-color: {T['bg_control_hover']};
    width: 1px;
    margin: {T['sp_tight']}px {T['sp_snug']}px;
}}
QToolBar > QWidget {{
    background: transparent;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {T['r_control']}px;
    padding: {T['sp_tight']}px;
    color: {T['text_on_chrome']};
}}
QToolButton:hover {{
    background-color: {T['border_subtle']};
    border-color: {T['border_control']};
}}
QToolButton:pressed {{
    background-color: {T['bg_app']};
}}
QToolButton:checked {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};
}}
QToolButton:disabled {{
    color: {T['text_secondary']};
}}

/* =====================================================================
   Flow tab bar
   ===================================================================== */
QTabBar#flowTabBar {{
    background-color: {T['vm_chrome_dark']};
}}
QTabBar#flowTabBar::tab {{
    background-color: {T['vm_chrome_dark']};
    color: {T['text_on_chrome']};
    padding: {T['sp_tight']}px {T['sp_snug']}px;
    margin-right: 2px;
    border: 1px solid {T['bg_control_hover']};
    border-bottom: none;
    min-height: {T['h_icon_md']}px;
    /* One step below the body size.  The tab carries a state dot, the flow name, the
       verdict, the cycle time *and* a close button, and at the body size a normal flow
       name ("PCB_AOI_Solution FAIL 177ms") overran the width Qt allocates and lost the
       cycle time to elision.  At the caption size the longest realistic label fits with
       room for the close button.  It is a token, not a one-off size. */
    font-size: {T['fs_caption']}px;
}}
QTabBar#flowTabBar::scroller {{
    width: 18px;
}}
QTabBar#flowTabBar QToolButton {{
    background-color: {T['bg_control']};
    border: 1px solid {T['border_control']};
    color: {T['text_primary']};
    padding: 0;
}}
QTabBar#flowTabBar QToolButton:hover {{
    background-color: {T['bg_surface_alt']};
}}
QTabBar#flowTabBar::tab:selected {{
    background-color: {T['vm_accent']};
    color: {T['text_primary']};
    border-color: {T['accent_border']};
}}
QTabBar#flowTabBar::tab:hover:!selected {{
    background-color: {T['vm_rail_hover']};
}}

/* =====================================================================
   Central workspace tabs  (manual p.40 items 5/6 - Image | Result)
   ===================================================================== */
QTabWidget::pane {{
    border: none;
    background-color: {T['vm_panel']};
}}
QTabWidget#workspaceTabs::pane {{
    background-color: {T['vm_canvas']};
    border: none;
}}
QTabWidget#dataTabs::pane {{
    background-color: {T['vm_panel']};
    border: none;
    border-top: 1px solid {T['border_subtle']};
}}
QTabWidget#displayTabs::pane {{
    background-color: {T['vm_panel']};
    border: none;
    border-top: 1px solid {T['border_subtle']};
}}
QTabWidget#displayTabs > QTabBar::tab {{
    padding: {T['sp_tight']}px {T['sp_loose']}px;
    min-height: {T['h_icon_sm']}px;
}}
QTabWidget#resultTabs::pane {{
    background-color: {T['vm_panel']};
    border: none;
    border-top: 1px solid {T['border_subtle']};
}}
QTabWidget#resultTabs > QTabBar::tab {{
    padding: {T['sp_tight']}px {T['sp_loose']}px;
    min-height: {T['h_icon_sm']}px;
}}
QTabBar::tab {{
    background-color: {T['vm_flyout']};
    color: {T['vm_node_text_dim']};
    padding: {T['sp_tight']}px {T['sp_loose']}px;
    border: none;
    border-right: 1px solid {T['border_subtle']};
    min-height: {T['h_icon_sm']}px;
    font-size: {T['fs_label']}px;
}}
QTabBar::tab:selected {{
    background-color: {T['vm_panel']};
    color: {T['text_primary']};
    border-top: 2px solid {T['vm_accent']};
    padding-top: 1px;
}}
QTabBar::tab:hover:!selected {{
    background-color: {T['bg_surface_alt']};
    color: {T['text_primary']};
}}

/* =====================================================================
   Left category rail + tool flyout
   ===================================================================== */
#vmCategoryRail {{
    background-color: {T['vm_rail']};
    border-right: 1px solid {T['bg_app']};
}}
QToolButton#railCategory {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    padding: {T['sp_snug']}px 0;
}}
QToolButton#railCategory:hover {{
    background-color: {T['vm_rail_hover']};
}}
QToolButton#railCategory:checked {{
    /* The selected glyph is re-rendered in dark ink by the rail widget; swapping
       only the fill would leave a light glyph on a light square. */
    background-color: {T['vm_flyout']};
    border-left: 3px solid {T['accent_border']};
    border-top: 1px solid {T['accent_border']};
    border-bottom: 1px solid {T['accent_border']};
}}

#vmToolFlyout {{
    background-color: {T['vm_flyout']};
    border-right: 1px solid {T['bg_app']};
}}
QLabel#flyoutCategoryHeader {{
    color: {T['text_primary']};
    font-size: {T['fs_subtitle']}px;
    font-weight: {T['fw_demibold']};
    padding: {T['sp_base']}px {T['sp_loose']}px {T['sp_snug']}px {T['sp_loose']}px;
    background-color: {T['vm_flyout_header']};
    border-bottom: 1px solid {T['vm_flyout_header']};
}}
QLabel#flyoutHint {{
    color: {T['text_muted']};
    font-size: {T['fs_body']}px;
    padding: {T['sp_hair']}px {T['sp_base']}px {T['sp_snug']}px {T['sp_base']}px;
}}
QListWidget#toolGrid {{
    background-color: {T['vm_flyout']};
    border: none;
    outline: none;
    color: {T['text_primary']};
    /* The cell label size.  Without this the cells resolve the 13 px `QLabel` size from
       this sheet's generic rules, and a long tool name ("Linear Edge Defect") wraps onto
       three lines that run past the bottom of the 84 px cell - measured: 91 px needed.
       At 11 px the longest name needs 71 px.  A rule is used rather than `setFont`,
       because a widget font set in code is overridden by this stylesheet. */
    font-size: {T['fs_caption']}px;
}}
QListWidget#toolGrid::item {{
    border: 1px solid transparent;
    border-radius: {T['r_control']}px;
    margin: {T['sp_hair']}px;
    color: {T['text_secondary']};
}}
QListWidget#toolGrid::item:hover {{
    background-color: {T['border_subtle']};
    border-color: {T['border_control']};
}}
QListWidget#toolGrid::item:selected {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};
    color: {T['text_primary']};
}}
QLineEdit#toolSearch {{
    background-color: {T['vm_flyout_header']};
    border: 1px solid {T['bg_control_hover']};
    border-radius: {T['r_control']}px;
    padding: {T['sp_tight']}px {T['sp_snug']}px;
    color: {T['text_primary']};
    font-size: {T['fs_body']}px;
}}
QLineEdit#toolSearch:focus {{
    border-color: {T['vm_accent']};
}}

/* =====================================================================
   Legacy tool tree (kept for API/back-compat, restyled to flyout look)
   ===================================================================== */
QTreeWidget {{
    background-color: {T['vm_flyout']};
    border: none;
    color: {T['text_primary']};
    font-size: {T['fs_label']}px;
    outline: none;
}}
QTreeWidget::item {{
    height: 24px;
    padding: {T['sp_hair']}px {T['sp_snug']}px;
    border: 1px solid transparent;
}}
QTreeWidget::item:hover {{
    background-color: {T['border_control']};
}}
QTreeWidget::item:selected {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['accent_border']};
    color: {T['text_primary']};
}}

/* =====================================================================
   Tables  (manual p.87 Result grid / p.40 bottom result table)
   ===================================================================== */
QTableWidget, QTableView {{
    background-color: {T['vm_panel']};
    alternate-background-color: {T['bg_surface_alt']};
    border: none;
    gridline-color: {T['border_subtle']};
    color: {T['text_primary']};
    font-size: {T['fs_label']}px;
    selection-background-color: {T['vm_accent_dim']};
    selection-color: {T['text_primary']};
}}
QTableWidget::item, QTableView::item {{
    padding: {T['sp_hair']}px {T['sp_snug']}px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {T['vm_accent_dim']};
    color: {T['text_primary']};
}}
QHeaderView {{
    background-color: {T['vm_panel_header']};
}}
QHeaderView::section {{
    background-color: {T['vm_panel_header']};
    color: {T['text_secondary']};
    padding: {T['sp_tight']}px {T['sp_base']}px;
    border: none;
    border-right: 1px solid {T['bg_control_hover']};
    border-bottom: 1px solid {T['bg_control_hover']};
    font-weight: {T['fw_medium']};
    font-size: {T['fs_label']}px;
}}
QHeaderView::section:hover {{
    background-color: {T['bg_surface_alt']};
}}
QTableCornerButton::section {{
    background-color: {T['vm_panel_header']};
    border: none;
}}

/* =====================================================================
   Result tree
   ===================================================================== */
QTreeWidget#resultTree {{
    background-color: {T['vm_panel']};
    border: none;
    color: {T['text_primary']};
    font-size: {T['fs_label']}px;
    alternate-background-color: {T['bg_surface_alt']};
}}
QTreeWidget#resultTree::item {{
    height: 22px;
    padding: {T['sp_hair']}px {T['sp_snug']}px;
    border: none;
}}
QTreeWidget#resultTree::item:hover {{
    background-color: {T['bg_surface_alt']};
}}
QTreeWidget#resultTree::item:selected {{
    background-color: {T['vm_accent_dim']};
    color: {T['text_primary']};
}}

/* =====================================================================
   Flow-area zoom tool
   ===================================================================== */
#flowZoomTool {{
    background-color: {T['bg_surface_alt']};
    border: 1px solid #aab3b9;
    border-radius: {T['r_panel']}px;
}}
QLabel#flowZoomLabel {{
    color: {T['text_primary']};
    font-size: {T['fs_caption']}px;
    font-weight: {T['fw_demibold']};
}}
QToolButton#flowZoomButton {{
    background: transparent;
    border: none;
    color: {T['text_primary']};
    font-size: {T['fs_subtitle']}px;
    padding: 0;
}}
QToolButton#flowZoomButton:hover {{
    background-color: {T['bg_control_hover']};
    border-radius: {T['r_control']}px;
}}

/* Flow telemetry readouts: three matching chips (the flow time carries the amber edge). */
QWidget#flowTelemetryBar {{
    background: transparent;
}}
QLabel#telemetryFlow, QLabel#telemetryTools, QLabel#telemetryAlgo {{
    background-color: {T['bg_surface_alt']};
    border: 1px solid #aab3b9;
    border-radius: {T['r_panel']}px;
    padding: 0px {T['sp_base']}px;
    color: {T['text_secondary']};
    font-size: {T['fs_caption']}px;
}}
QLabel#telemetryFlow {{
    color: {T['text_primary']};
    font-weight: {T['fw_demibold']};
    border-color: {T['accent_border']};
}}

/* =====================================================================
   Image display area
   ===================================================================== */
#imageDisplayArea {{
    background-color: {T['vm_panel']};
}}
#imageHeader {{
    background-color: {T['vm_panel_header']};
    border-bottom: 1px solid {T['bg_control']};
}}
QLabel#imageSourceLabel {{
    color: {T['text_primary']};
    font-size: {T['fs_body']}px;
    font-weight: {T['fw_demibold']};
}}
QToolButton#viewToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {T['r_control']}px;
    padding: {T['sp_hair']}px;
}}
QToolButton#viewToolButton:hover {{
    background-color: {T['bg_surface_alt']};
    border-color: {T['border_control']};
}}
QToolButton#viewToolButton:checked {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};
}}
QToolButton#viewToolButton:disabled {{
    background: transparent;
    border-color: transparent;
}}
QFrame#viewToolSeparator {{
    color: {T['bg_control_hover']};
    max-width: 1px;
    margin: {T['sp_hair']}px {T['sp_hair']}px;
}}
#imageStatusBar {{
    background-color: {T['bg_app']};
    border-top: 1px solid {T['bg_control']};
    border-bottom: 1px solid {T['bg_control']};
}}
QLabel#imageStatusId {{
    color: {T['vm_node_text_dim']};
    font-size: {T['fs_body']}px;
    font-family: 'Segoe UI', sans-serif;
}}
QLabel#imageStatusCoords {{
    color: {T['text_secondary']};
    font-size: {T['fs_body']}px;
    font-family: 'Consolas', 'Segoe UI', monospace;
}}
#imageStripHeader {{
    background-color: {T['vm_panel_header']};
    border-top: 1px solid {T['bg_control']};
    border-bottom: 1px solid {T['bg_control']};
}}
QLabel#imageStripLabel {{
    color: {T['text_primary']};
    font-size: {T['fs_label']}px;
    font-weight: {T['fw_demibold']};
}}
QLabel#imageStripCaption {{
    color: {T['vm_node_text_dim']};
    font-size: {T['fs_body']}px;
}}
QComboBox#runScopeCombo {{
    background-color: #ffffff;
    color: {T['text_primary']};
    border: 1px solid #aab3b9;
    border-radius: {T['r_panel']}px;
    padding: {T['sp_hair']}px {T['sp_base']}px;
    font-size: {T['fs_body']}px;
    min-height: {T['h_input']}px;
}}
QComboBox#runScopeCombo:hover {{
    background-color: #ffffff;
    border-color: #7d8991;
}}
QComboBox#runScopeCombo::drop-down {{
    border: none;
    width: 16px;
}}
QComboBox#runScopeCombo QAbstractItemView {{
    background-color: {T['bg_header']};
    color: {T['text_primary']};
    border: 1px solid {T['border_control']};
    selection-background-color: {T['vm_accent']};
    selection-color: {T['text_primary']};
    font-size: {T['fs_body']}px;
}}
QPushButton#stripPlayButton, QToolButton#stripPlayButton {{
    background-color: #15803d;
    color: #ffffff;
    border: 1px solid #16a34a;
    border-radius: {T['r_panel']}px;
    font-size: {T['fs_body']}px;
    font-weight: {T['fw_demibold']};
    padding: {T['sp_hair']}px {T['sp_loose']}px;
    min-height: {T['h_input']}px;
}}
QPushButton#stripPlayButton:hover, QToolButton#stripPlayButton:hover {{
    background-color: #16a34a;
    border-color: #22c55e;
}}
QPushButton#stripPlayButton:pressed, QToolButton#stripPlayButton:pressed {{
    background-color: #14532d;
    border-color: #15803d;
}}
QPushButton#stripPlayButton[running="true"] {{
    background-color: #b91c1c;
    border-color: #dc2626;
}}
QPushButton#stripPlayButton[running="true"]:hover {{
    background-color: #dc2626;
    border-color: #ef4444;
}}
QPushButton#stripPlayButton[running="true"]:disabled {{
    background-color: #8f5a5a;
    border-color: #a97a7a;
    color: #ffffff;
}}
#imageStripRow {{
    background-color: {T['vm_flyout_header']};
    border-bottom: 1px solid {T['vm_panel_header']};
}}
QToolButton#stripNavPrev, QToolButton#stripNavNext {{
    background-color: {T['bg_surface']};
    border: 1px solid {T['bg_control_hover']};
    border-radius: {T['r_control']}px;
}}
QToolButton#stripNavPrev:hover, QToolButton#stripNavNext:hover {{
    background-color: {T['border_subtle']};
    border-color: {T['border_control']};
}}
QToolButton#stripNavPrev:disabled, QToolButton#stripNavNext:disabled {{
    background-color: {T['vm_flyout_header']};
    border-color: {T['vm_node']};
}}
QListWidget#imageStrip {{
    background-color: {T['vm_chrome_dark']};
    border: none;
    outline: none;
}}
QListWidget#imageStrip::item {{
    border: 1px solid {T['vm_rail_hover']};
    border-radius: {T['r_control']}px;
    margin: {T['sp_hair']}px {T['sp_hair']}px;
    background-color: {T['vm_rail']};
}}
QListWidget#imageStrip::item:hover {{
    border-color: {T['text_on_chrome']};
}}
QListWidget#imageStrip::item:selected {{
    border: 2px solid {T['vm_accent']};
    background-color: {T['vm_rail']};
}}

/* =====================================================================
   Result display area
   ===================================================================== */
QLabel#resultCaption {{
    background-color: {T['vm_panel_header']};
    color: {T['text_primary']};
    font-size: {T['fs_body']}px;
    border-bottom: 1px solid {T['bg_control']};
}}
QTableWidget#resultGrid, QTableWidget#historyGrid, QTableWidget#moduleLogGrid {{
    background-color: {T['vm_panel']};
    alternate-background-color: {T['bg_surface_alt']};
    border: none;
    gridline-color: {T['border_subtle']};
    color: {T['text_primary']};
    font-size: {T['fs_label']}px;
    selection-background-color: {T['vm_accent_dim']};
    selection-color: {T['text_primary']};
}}
QTableWidget#resultGrid::item, QTableWidget#historyGrid::item,
QTableWidget#moduleLogGrid::item {{
    padding: {T['sp_hair']}px {T['sp_snug']}px;
}}

/* =====================================================================
   Splitter / scrollbars / dock
   ===================================================================== */
QSplitter::handle {{
    background-color: {T['vm_viewport']};
}}
QSplitter::handle:horizontal {{
    width: 3px;
}}
QSplitter::handle:vertical {{
    height: 3px;
}}
QSplitter::handle:hover {{
    background-color: {T['vm_accent']};
}}

QScrollBar:vertical {{
    background: {T['vm_flyout_header']};
    width: 11px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {T['border_control']};
    min-height: {T['h_button']}px;
    border-radius: {T['r_control']}px;
}}
QScrollBar::handle:vertical:hover {{
    background: {T['border_control']};
}}
QScrollBar:horizontal {{
    background: {T['vm_flyout_header']};
    height: 11px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {T['border_control']};
    min-width: 26px;
    border-radius: {T['r_control']}px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {T['border_control']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QDockWidget {{
    color: {T['text_primary']};
    font-size: {T['fs_label']}px;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background-color: {T['vm_panel_header']};
    border-bottom: 1px solid {T['bg_control']};
    padding: {T['sp_tight']}px {T['sp_base']}px;
    text-align: left;
    color: {T['text_secondary']};
    font-weight: {T['fw_demibold']};
    font-size: {T['fs_body']}px;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: {T['sp_hair']}px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: {T['border_control']};
}}

/* =====================================================================
   Status bar
   ===================================================================== */
QStatusBar {{
    background-color: {T['vm_chrome_dark']};
    color: {T['text_on_chrome']};
    border-top: 1px solid {T['border_subtle']};
    font-size: {T['fs_body']}px;
}}
QStatusBar::item {{
    border: none;
}}
QLabel#statusSegment {{
    /* The status strip is dark chrome, so the ink is the chrome tone.  An explicit
       transparent background is required: a QLabel with a colour rule otherwise paints
       its own background, and that filled the whole strip with the window colour. */
    background: transparent;
    color: {T['text_on_chrome']};
    padding: {T['sp_hair']}px {T['sp_loose']}px;
    border-left: 1px solid {T['vm_rail_hover']};
    font-size: {T['fs_body']}px;
}}
QLabel#statusLeading {{
    background: transparent;
    color: {T['text_on_chrome']};
    padding: {T['sp_hair']}px {T['sp_loose']}px;
    font-size: {T['fs_body']}px;
}}
QLabel#statusMessage {{
    background: transparent;
    color: {T['text_on_chrome']};
    padding: {T['sp_hair']}px {T['sp_loose']}px;
    font-size: {T['fs_body']}px;
}}
QLabel#statusVersion {{
    background: transparent;
    color: {T['text_on_chrome']};
    font-size: {T['fs_micro']}px;
    padding-left: {T['sp_snug']}px;
}}

/* =====================================================================
   Buttons / inputs (inspector + dialogs)
   ===================================================================== */
QPushButton {{
    background-color: {T['vm_rail_hover']};
    color: {T['text_primary']};
    border: 1px solid {T['border_control']};
    border-radius: {T['r_control']}px;
    padding: {T['sp_tight']}px {T['sp_base']}px;
    font-size: {T['fs_label']}px;
}}
QPushButton:hover {{
    background-color: {T['border_control']};
    border-color: {T['text_secondary']};
}}
QPushButton:pressed {{
    background-color: {T['vm_rail']};
}}
QPushButton:disabled {{
    color: {T['text_secondary']};
    background-color: {T['vm_flyout']};
}}
QPushButton:checked {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};
    color: {T['text_primary']};
}}
QToolButton#btnRunOnce, QPushButton#btnRunOnce {{
    background-color: #12331f;
    border: 1px solid #1b5330;
    color: #86efac;
}}
QToolButton#btnRunOnce:hover, QPushButton#btnRunOnce:hover {{
    background-color: #184428;
    border-color: #22c55e;
}}
QToolButton#btnStop, QPushButton#btnStop {{
    background-color: #3b181c;
    border: 1px solid #5a242a;
    color: #fca5a5;
}}
QToolButton#btnStop:hover, QPushButton#btnStop:hover {{
    background-color: #4c1f24;
    border-color: #ef4444;
}}

/* Compact trailing action button in inspector parameter rows (Browse / Draw).
   Fixed width so the input fields of every row end on the same vertical line. */
QPushButton#fieldAction {{
    padding: {T['sp_hair']}px {T['sp_snug']}px;
    font-size: {T['fs_body']}px;
    min-width: 0px;
    min-height: 0;
}}

/* Parameter form labels: one shared column so fields align vertically. */
QWidget#paramContainer QLabel {{
    padding-right: 2px;
}}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {T['bg_header']};
    border: 1px solid {T['border_control']};
    border-radius: {T['r_control']}px;
    padding: {T['sp_tight']}px {T['sp_snug']}px;
    color: {T['text_primary']};
    font-size: {T['fs_label']}px;
    selection-background-color: {T['accent_primary']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {T['accent_primary']};
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: {T['text_secondary']};
}}

QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {T['bg_surface_alt']};
    border: 1px solid {T['border_control']};
    border-radius: {T['r_control']}px;
    padding: {T['sp_hair']}px {T['sp_snug']}px;
    color: {T['text_primary']};
    font-size: {T['fs_label']}px;
}}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {T['border_focus']};
    background-color: #ffffff;
}}
QComboBox::drop-down {{
    border: none;
    width: 16px;
}}
QComboBox QAbstractItemView {{
    background-color: #ffffff;
    border: 1px solid {T['border_control']};
    selection-background-color: {T['accent_primary']};
    selection-color: #ffffff;
    color: {T['text_primary']};
}}

QCheckBox {{
    color: {T['text_primary']};
    spacing: 6px;
    font-size: {T['fs_label']}px;
}}
QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {T['border_control']};
    border-radius: {T['r_control']}px;
    background-color: {T['bg_header']};
}}
QCheckBox::indicator:checked {{
    background-color: {T['vm_accent']};
    border-color: {T['vm_accent_hover']};
}}

QGroupBox {{
    border: none;
    border-top: 1px solid {T['bg_control_hover']};
    margin-top: 10px;
    padding-top: 8px;
    color: {T['text_secondary']};
    font-size: {T['fs_body']}px;
    font-weight: {T['fw_demibold']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 4px;
    padding: 0 {T['sp_tight']}px;
}}

QDialog {{
    background-color: {T['bg_surface']};
    color: {T['text_primary']};
}}
QToolTip {{
    background-color: {T['bg_surface_alt']};
    color: {T['text_primary']};
    border: 1px solid {T['border_control']};
    padding: {T['sp_tight']}px {T['sp_snug']}px;
    font-size: {T['fs_body']}px;
}}

QProgressBar {{
    background-color: {T['bg_surface_alt']};
    border: 1px solid {T['border_control']};
    border-radius: {T['r_control']}px;
    text-align: center;
    color: {T['text_primary']};
    font-size: {T['fs_body']}px;
}}
QProgressBar::chunk {{
    background-color: {T['vm_accent']};
}}

/* =====================================================================
   Inspection & evaluation panel
   ---------------------------------------------------------------------
   The evaluation surfaces read as part of the same application: the amber
   accent marks the primary action, the shared `panelHeader` strip titles
   the sections, and an undefined metric is drawn in muted ink so `n/a`
   cannot be mistaken for a figure.  Every rule is scoped by the panel's
   object names, so none of them can affect a widget outside the panel.
   ===================================================================== */
QWidget#inspectionPanel {{
    background-color: {T['bg_app']};
}}
QTabWidget#inspectionTabs::pane {{
    background-color: {T['bg_surface']};
    border: 1px solid {T['border_subtle']};
    border-top: none;
}}
QTabWidget#inspectionTabs > QTabBar::tab {{
    background-color: {T['bg_control']};
    color: {T['text_secondary']};
    border: 1px solid {T['border_subtle']};
    border-bottom: none;
    padding: {T['sp_tight']}px {T['sp_loose']}px;
    min-height: {T['h_tab']}px;
    font-size: {T['fs_body']}px;
}}
QTabWidget#inspectionTabs > QTabBar::tab:selected {{
    background-color: {T['vm_card']};
    color: {T['text_primary']};
    font-weight: {T['fw_demibold']};
}}
QTabWidget#inspectionTabs > QTabBar::tab:hover:!selected {{
    background-color: {T['bg_control_hover']};
}}
QLabel#metricName {{
    background: transparent;
    color: {T['text_muted']};
    font-size: {T['fs_caption']}px;
}}
QLabel#metricValue {{
    background: transparent;
    color: {T['text_primary']};
    font-size: {T['fs_title']}px;
    font-weight: {T['fw_demibold']};
}}
QLabel#metricNote, QLabel#headlineNote, QLabel#legend,
QLabel#datasetSummary, QLabel#failureSummary, QLabel#storePath {{
    background: transparent;
    color: {T['text_secondary']};
    font-size: {T['fs_caption']}px;
}}
QLabel#compareWarning {{
    background-color: {T['status_warn_bg']};
    color: {T['status_warn_text']};
    border: 1px solid {T['status_warn_border']};
    border-radius: {T['r_control']}px;
    padding: {T['sp_tight']}px {T['sp_base']}px;
    font-size: {T['fs_caption']}px;
}}
QLabel#failureImage {{
    background-color: {T['vm_viewport']};
    color: {T['vm_viewport_text']};
    border: 1px solid {T['border_subtle']};
    font-size: {T['fs_caption']}px;
}}
QTreeWidget#failureList {{
    background-color: {T['bg_surface_alt']};
    alternate-background-color: {T['bg_surface']};
    color: {T['text_primary']};
    border: 1px solid {T['border_subtle']};
    font-size: {T['fs_body']}px;
}}
QTreeWidget#failureList::item:selected {{
    background-color: {T['accent_dim']};
    color: {T['text_primary']};
}}
QWidget#inspectionPanel QPushButton#primaryAction {{
    background-color: {T['vm_accent']};
    color: {T['text_on_menu']};
    border: 1px solid {T['accent_border']};
    border-radius: {T['r_control']}px;
    padding: {T['sp_tight']}px {T['sp_loose']}px;
    min-height: {T['h_button']}px;
    font-weight: {T['fw_demibold']};
}}
QWidget#inspectionPanel QPushButton#primaryAction:hover {{
    background-color: {T['vm_accent_hover']};
}}
QWidget#inspectionPanel QPushButton#primaryAction:disabled {{
    background-color: {T['bg_control']};
    /* `text_secondary` (5.28:1 on the disabled fill) rather than `text_muted`
       (3.58:1): WCAG exempts inactive controls, but a design system that exempts
       itself from its own contrast rule has no rule.  This still reads as inactive. */
    color: {T['text_secondary']};
    border-color: {T['border_subtle']};
}}

/* =====================================================================
   Modern control layer
   ---------------------------------------------------------------------
   One consistent look for every input and button that sits on a light panel
   or in a dialog: white fields, hairline neutral borders, 5 px corners, a
   blue focus ring and a blue default action.  Chrome (toolbars, rail, status
   bar) and the amber selection language are untouched - those are styled by
   their own object names above, which out-rank these type selectors.
   ===================================================================== */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: #ffffff;
    border: 1px solid #aab3b9;
    border-radius: {T['r_panel']}px;
    padding: 3px 8px;
    min-height: 20px;
    color: {T['text_primary']};
    selection-background-color: {T['accent_primary']};
    selection-color: #ffffff;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: #7d8991;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {T['accent_primary']};
    background-color: #ffffff;
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QComboBox:disabled {{
    background-color: #e9edef;
    color: {T['text_muted']};
    border-color: #cdd4d8;
}}
QLineEdit:read-only, QPlainTextEdit[readOnly="true"], QTextEdit[readOnly="true"] {{
    background-color: #f3f5f6;
}}
QComboBox {{
    padding-right: 22px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 20px;
    border: none;
}}
QComboBox QAbstractItemView {{
    background-color: #ffffff;
    border: 1px solid #aab3b9;
    padding: 2px;
    outline: 0;
    selection-background-color: {T['accent_primary']};
    selection-color: #ffffff;
}}

QPushButton {{
    background-color: #f6f8f9;
    color: {T['text_primary']};
    border: 1px solid #aab3b9;
    border-radius: {T['r_panel']}px;
    padding: 4px 14px;
    min-height: 20px;
    min-width: 56px;
}}
QPushButton:hover {{
    background-color: #e8edf0;
    border-color: #7d8991;
}}
QPushButton:pressed {{
    background-color: #d8dfe3;
}}
QPushButton:focus {{
    border-color: {T['accent_primary']};
}}
QPushButton:disabled {{
    background-color: #eceff0;
    color: {T['text_muted']};
    border-color: #d0d6d9;
}}
QPushButton:default {{
    background-color: {T['accent_primary']};
    border-color: #00638f;
    color: #ffffff;
    font-weight: {T['fw_demibold']};
}}
QPushButton:default:hover {{
    background-color: #0a89c4;
}}
QPushButton:default:disabled {{
    background-color: {T['bg_control']};
    border-color: #aab3b9;
    color: {T['text_secondary']};
}}
QPushButton:checked {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};
}}
QMessageBox QLabel, QInputDialog QLabel {{
    background: transparent;
}}
QDialogButtonBox QPushButton, QMessageBox QPushButton {{
    min-width: 80px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid #8b959c;
    border-radius: {T['r_panel']}px;
    background-color: #ffffff;
}}
QCheckBox::indicator:hover {{
    border-color: {T['accent_primary']};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #b4bcc2;
    border-radius: {T['r_panel']}px;
    min-height: 30px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: #8b959c;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #b4bcc2;
    border-radius: {T['r_panel']}px;
    min-width: 30px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #8b959c;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0px;
    height: 0px;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* Menu-bar corner: the solution / role selectors sit inside the 30 px menu band, so they
   drop the generic field padding and centre their text in a fixed 22 px box. */
QComboBox#comboSolution, QComboBox#comboRole {{
    min-height: 0px;
    padding: 0px 22px 0px {T['sp_base']}px;
    font-size: {T['fs_body']}px;
}}
QToolButton#btnMenuSave {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {T['r_panel']}px;
}}
QToolButton#btnMenuSave:hover {{
    background-color: {T['bg_control_hover']};
    border-color: #aab3b9;
}}

/* Labels never paint their own box: a widget-level style on a QLabel otherwise fills it
   with the palette window colour, which showed as grey bands across dialogs. */
QLabel {{
    background: transparent;
}}

/* Tables and trees: light striping and hairline grid instead of the heavy palette default. */
QTableWidget, QTableView, QTreeWidget, QTreeView, QListWidget {{
    alternate-background-color: #f1f4f5;
    gridline-color: #dde2e5;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {T['vm_accent_dim']};
    color: {T['text_primary']};
}}
QCheckBox, QRadioButton {{
    background: transparent;
}}
QCheckBox::indicator:checked {{
    image: url({check_icon_url()});
}}

/* Menu-bar corner chips (project + role).  Flat controls that belong to the steel chrome:
   a hairline outline, a lighter fill on hover, and the platform arrow for the menu. */
QWidget#menuCornerWidget {{
    background: transparent;
}}
QToolButton#projectChip, QToolButton#roleChip {{
    background-color: transparent;
    color: {T['text_primary']};
    border: 1px solid #6a727a;
    border-radius: {T['r_panel']}px;
    padding: 0px 18px 0px {T['sp_base']}px;
    font-size: {T['fs_body']}px;
    font-weight: {T['fw_demibold']};
    text-align: left;
}}
QToolButton#projectChip:hover, QToolButton#roleChip:hover, QToolButton#projectChip:open,
QToolButton#roleChip:open {{
    background-color: #98a0a7;
    border-color: #4e565e;
}}
QToolButton#projectChip::menu-indicator, QToolButton#roleChip::menu-indicator {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: {T['sp_base']}px;
}}
QFrame#cornerSeparator {{
    color: #6a727a;
    background: #6a727a;
    max-width: 1px;
}}
"""
