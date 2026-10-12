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

VM_THEME_QSS = f"""
/* =====================================================================
   Global base
   ===================================================================== */
QMainWindow, QWidget {{
    background-color: {T['vm_chrome']};
    color: {T['text_primary']};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", "Ubuntu", Arial, sans-serif;
    font-size: 13px;
    outline: none;
}}
QMainWindow::separator {{
    background-color: #10141b;
    width: 3px;
    height: 3px;
}}

/* =====================================================================
   Menu bar
   ===================================================================== */
QMenuBar {{
    background-color: {T['vm_chrome']};
    color: #d8dade;
    border: none;
    padding: 1px 4px 1px 96px;   /* left inset leaves room for the brand mark */
    font-size: 13px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 9px;
    margin: 1px 0;
    border-radius: 2px;
}}
QMenuBar::item:selected {{
    background-color: #1f2736;
    color: #ffffff;
}}
QMenuBar::item:pressed {{
    background-color: {T['vm_accent']};
    color: #ffffff;
}}

QMenu {{
    background-color: #181e28;
    color: #e2e4e8;
    border: 1px solid #283447;
    padding: 4px 2px;
}}
QMenu::item {{
    padding: 5px 26px 5px 24px;
    margin: 1px 3px;
    border-radius: 2px;
}}
QMenu::item:selected {{
    background-color: #242d3d;
    color: #ffffff;
}}
QMenu::item:disabled {{
    color: #64748b;
}}
QMenu::separator {{
    height: 1px;
    background-color: #283447;
    margin: 4px 8px;
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
    background-color: {T['vm_chrome']};
    border: none;
    border-bottom: 1px solid #10141b;
    spacing: 1px;
    padding: 6px 6px;
}}
QToolBar::separator {{
    background-color: #283447;
    width: 1px;
    margin: 4px 5px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 4px;
    color: #d8dade;
}}
QToolButton:hover {{
    background-color: #232c3d;
    border-color: #38465e;
}}
QToolButton:pressed {{
    background-color: #131720;
}}
QToolButton:checked {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};
}}
QToolButton:disabled {{
    color: #475569;
}}

/* =====================================================================
   Flow tab bar
   ===================================================================== */
QTabBar#flowTabBar {{
    background-color: {T['vm_chrome']};
}}
QTabBar#flowTabBar::tab {{
    background-color: #181e28;
    color: #c9cbd1;
    padding: 4px 7px;
    margin-right: 2px;
    border: 1px solid #283447;
    border-bottom: none;
    min-height: 20px;
    font-size: 12px;
}}
QTabBar#flowTabBar::scroller {{
    width: 18px;
}}
QTabBar#flowTabBar QToolButton {{
    background-color: #181e28;
    border: 1px solid #283447;
    color: #c9cbd1;
    padding: 0;
}}
QTabBar#flowTabBar QToolButton:hover {{
    background-color: #242d3d;
}}
QTabBar#flowTabBar::tab:selected {{
    background-color: #232c3d;
    color: #ffffff;
    border-color: #38465e;
}}
QTabBar#flowTabBar::tab:hover:!selected {{
    background-color: #1f2736;
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
    border-top: 1px solid #2a2d30;
}}
QTabWidget#displayTabs::pane {{
    background-color: {T['vm_panel']};
    border: none;
    border-top: 1px solid #2a2d30;
}}
QTabWidget#displayTabs > QTabBar::tab {{
    padding: 3px 13px;
    min-height: 16px;
}}
QTabWidget#resultTabs::pane {{
    background-color: {T['vm_panel']};
    border: none;
    border-top: 1px solid #2a2d30;
}}
QTabWidget#resultTabs > QTabBar::tab {{
    padding: 3px 13px;
    min-height: 16px;
}}
QTabBar::tab {{
    background-color: #1a202c;
    color: #94a3b8;
    padding: 3px 14px;
    border: none;
    border-right: 1px solid #232b3a;
    min-height: 16px;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    background-color: {T['vm_panel']};
    color: #ffffff;
    border-top: 2px solid {T['vm_accent']};
    padding-top: 1px;
}}
QTabBar::tab:hover:!selected {{
    background-color: #242c3b;
    color: #e2e8f0;
}}

/* =====================================================================
   Left category rail + tool flyout
   ===================================================================== */
#vmCategoryRail {{
    background-color: {T['vm_rail']};
    border-right: 1px solid #10141b;
}}
QToolButton#railCategory {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    padding: 6px 0;
}}
QToolButton#railCategory:hover {{
    background-color: {T['vm_rail_hover']};
}}
QToolButton#railCategory:checked {{
    background-color: {T['vm_flyout']};
    border-left: 3px solid {T['vm_accent']};
}}

#vmToolFlyout {{
    background-color: {T['vm_flyout']};
    border-right: 1px solid #10141b;
}}
QLabel#flyoutCategoryHeader {{
    color: #f1f5f9;
    font-size: 14px;
    font-weight: 600;
    padding: 7px 10px 6px 10px;
    background-color: {T['vm_flyout_header']};
    border-bottom: 1px solid #141822;
}}
QLabel#flyoutHint {{
    color: #64748b;
    font-size: 12px;
    padding: 3px 10px 6px 10px;
}}
QListWidget#toolGrid {{
    background-color: {T['vm_flyout']};
    border: none;
    outline: none;
    color: #f1f5f9;
}}
QListWidget#toolGrid::item {{
    border: 1px solid transparent;
    border-radius: 3px;
    margin: 2px;
    color: #cbd5e1;
}}
QListWidget#toolGrid::item:hover {{
    background-color: #263143;
    border-color: #38465e;
}}
QListWidget#toolGrid::item:selected {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};
    color: #ffffff;
}}
QLineEdit#toolSearch {{
    background-color: #141822;
    border: 1px solid #283344;
    border-radius: 2px;
    padding: 3px 6px;
    color: #e2e8f0;
    font-size: 12px;
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
    color: #dcdde1;
    font-size: 13px;
    outline: none;
}}
QTreeWidget::item {{
    height: 24px;
    padding: 2px 6px;
    border: 1px solid transparent;
}}
QTreeWidget::item:hover {{
    background-color: #3a3b3f;
}}
QTreeWidget::item:selected {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};
    color: #ffffff;
}}

/* =====================================================================
   Tables  (manual p.87 Result grid / p.40 bottom result table)
   ===================================================================== */
QTableWidget, QTableView {{
    background-color: {T['vm_panel']};
    alternate-background-color: #191f2a;
    border: none;
    gridline-color: #232c3b;
    color: #e2e8f0;
    font-size: 13px;
    selection-background-color: {T['vm_accent_dim']};
    selection-color: #ffffff;
}}
QTableWidget::item, QTableView::item {{
    padding: 3px 7px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {T['vm_accent_dim']};
    color: #ffffff;
}}
QHeaderView {{
    background-color: {T['vm_panel_header']};
}}
QHeaderView::section {{
    background-color: {T['vm_panel_header']};
    color: #cbd5e1;
    padding: 5px 8px;
    border: none;
    border-right: 1px solid #283344;
    border-bottom: 1px solid #283344;
    font-weight: 500;
    font-size: 13px;
}}
QHeaderView::section:hover {{
    background-color: #242d3d;
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
    color: #e2e8f0;
    font-size: 13px;
    alternate-background-color: #191f2a;
}}
QTreeWidget#resultTree::item {{
    height: 22px;
    padding: 1px 6px;
    border: none;
}}
QTreeWidget#resultTree::item:hover {{
    background-color: #242d3d;
}}
QTreeWidget#resultTree::item:selected {{
    background-color: {T['vm_accent_dim']};
    color: #ffffff;
}}

/* =====================================================================
   Flow-area zoom tool
   ===================================================================== */
#flowZoomTool {{
    background-color: rgba(18, 23, 31, 240);
    border: 1px solid {T['vm_accent']};
    border-radius: 3px;
}}
QLabel#flowZoomLabel {{
    color: #e2e8f0;
    font-size: 11px;
    font-weight: 600;
}}
QToolButton#flowZoomButton {{
    background: transparent;
    border: none;
    color: #cbd5e1;
    font-size: 14px;
    padding: 0;
}}
QToolButton#flowZoomButton:hover {{
    background-color: {T['vm_accent_dim']};
    border-radius: 2px;
}}

/* =====================================================================
   Image display area
   ===================================================================== */
#imageDisplayArea {{
    background-color: {T['vm_panel']};
}}
#imageHeader {{
    background-color: {T['vm_panel_header']};
    border-bottom: 1px solid #202735;
}}
QLabel#imageSourceLabel {{
    color: #e2e8f0;
    font-size: 12px;
    font-weight: 600;
}}
QToolButton#viewToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 1px;
}}
QToolButton#viewToolButton:hover {{
    background-color: #242d3d;
    border-color: #38465e;
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
    color: #283344;
    max-width: 1px;
    margin: 3px 3px;
}}
#imageStatusBar {{
    background-color: #12151c;
    border-top: 1px solid #202735;
    border-bottom: 1px solid #202735;
}}
QLabel#imageStatusId {{
    color: #94a3b8;
    font-size: 12px;
    font-family: 'Segoe UI', sans-serif;
}}
QLabel#imageStatusCoords {{
    color: #cbd5e1;
    font-size: 12px;
    font-family: 'Consolas', 'Segoe UI', monospace;
}}
#imageStripHeader {{
    background-color: {T['vm_panel_header']};
    border-bottom: 1px solid #202735;
}}
QLabel#imageStripLabel {{
    color: #e2e8f0;
    font-size: 12px;
    font-weight: 600;
}}
QLabel#imageStripCaption {{
    color: #94a3b8;
    font-size: 11px;
}}
QComboBox#runScopeCombo {{
    background-color: #1e2533;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 2px;
    padding: 0px 4px;
    font-size: 11px;
    min-height: 18px;
}}
QComboBox#runScopeCombo:hover {{
    background-color: #263143;
    border-color: #475569;
}}
QComboBox#runScopeCombo::drop-down {{
    border: none;
    width: 14px;
}}
QComboBox#runScopeCombo QAbstractItemView {{
    background-color: #181e28;
    color: #e2e8f0;
    border: 1px solid #334155;
    selection-background-color: {T['vm_accent']};
    selection-color: #ffffff;
}}
#imageStripRow {{
    background-color: #141822;
    border-bottom: 1px solid #1c222e;
}}
QToolButton#stripNavPrev, QToolButton#stripNavNext {{
    background-color: #1b212c;
    border: 1px solid #283344;
    border-radius: 2px;
}}
QToolButton#stripNavPrev:hover, QToolButton#stripNavNext:hover {{
    background-color: #263143;
    border-color: #3b4961;
}}
QToolButton#stripNavPrev:disabled, QToolButton#stripNavNext:disabled {{
    background-color: #141822;
    border-color: #1e2532;
}}
QListWidget#imageStrip {{
    background-color: #11141b;
    border: none;
    outline: none;
}}
QListWidget#imageStrip::item {{
    border: 1px solid #283344;
    border-radius: 2px;
    margin: 1px 2px;
    background-color: #161b24;
}}
QListWidget#imageStrip::item:hover {{
    border-color: #38465e;
}}
QListWidget#imageStrip::item:selected {{
    border: 2px solid {T['vm_accent']};
    background-color: #161b24;
}}

/* =====================================================================
   Result display area
   ===================================================================== */
QLabel#resultCaption {{
    background-color: {T['vm_panel_header']};
    color: #e2e8f0;
    font-size: 12px;
    border-bottom: 1px solid #202735;
}}
QTableWidget#resultGrid, QTableWidget#historyGrid, QTableWidget#moduleLogGrid {{
    background-color: {T['vm_panel']};
    alternate-background-color: #191f2a;
    border: none;
    gridline-color: #232c3b;
    color: #e2e8f0;
    font-size: 13px;
    selection-background-color: {T['vm_accent_dim']};
    selection-color: #ffffff;
}}
QTableWidget#resultGrid::item, QTableWidget#historyGrid::item,
QTableWidget#moduleLogGrid::item {{
    padding: 1px 6px;
}}

/* =====================================================================
   Splitter / scrollbars / dock
   ===================================================================== */
QSplitter::handle {{
    background-color: #1c1c20;
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
    background: #141822;
    width: 11px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #2d3748;
    min-height: 26px;
    border-radius: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: #3d4a60;
}}
QScrollBar:horizontal {{
    background: #141822;
    height: 11px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #2d3748;
    min-width: 26px;
    border-radius: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #3d4a60;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QDockWidget {{
    color: #e2e8f0;
    font-size: 13px;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background-color: {T['vm_panel_header']};
    border-bottom: 1px solid #202735;
    padding: 5px 9px;
    text-align: left;
    color: #cbd5e1;
    font-weight: 600;
    font-size: 12px;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 1px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: #2e3b4e;
}}

/* =====================================================================
   Status bar
   ===================================================================== */
QStatusBar {{
    background-color: {T['vm_chrome']};
    color: #94a3b8;
    border-top: 1px solid #10141b;
    font-size: 12px;
}}
QStatusBar::item {{
    border: none;
}}
QLabel#statusSegment {{
    color: #94a3b8;
    padding: 2px 10px;
    border-left: 1px solid #202735;
    font-size: 12px;
}}
QLabel#statusLeading {{
    color: #cbd5e1;
    padding: 2px 10px;
    font-size: 12px;
}}
QLabel#statusMessage {{
    color: #94a3b8;
    padding: 2px 12px;
    font-size: 12px;
}}

/* =====================================================================
   Buttons / inputs (inspector + dialogs)
   ===================================================================== */
QPushButton {{
    background-color: #222938;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 2px;
    padding: 3px 9px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: #2a3447;
    border-color: #475569;
}}
QPushButton:pressed {{
    background-color: #161b24;
}}
QPushButton:disabled {{
    color: #475569;
    background-color: #1a202c;
}}
QPushButton:checked {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};
    color: #ffffff;
}}
QPushButton#btnRunOnce {{
    background-color: #12331f;
    border: 1px solid #1b5330;
    color: #86efac;
}}
QPushButton#btnRunOnce:hover {{
    background-color: #184428;
}}
QPushButton#btnStop {{
    background-color: #3b181c;
    border: 1px solid #5a242a;
    color: #fca5a5;
}}
QPushButton#btnStop:hover {{
    background-color: #4c1f24;
}}

/* Compact trailing action button in inspector parameter rows (Browse / Draw).
   Fixed width so the input fields of every row end on the same vertical line. */
QPushButton#fieldAction {{
    padding: 1px 6px;
    font-size: 12px;
    min-width: 0px;
    min-height: 0px;
}}

/* Parameter form labels: one shared column so fields align vertically. */
QWidget#paramContainer QLabel {{
    padding-right: 2px;
}}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: #181e28;
    border: 1px solid #2d384a;
    border-radius: 2px;
    padding: 3px 6px;
    color: #f1f5f9;
    font-size: 13px;
    selection-background-color: {T['accent_primary']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {T['accent_primary']};
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: #475569;
}}

QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: #181e28;
    border: 1px solid #2d384a;
    border-radius: 2px;
    padding: 2px 5px;
    color: #f1f5f9;
    font-size: 13px;
}}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {T['accent_primary']};
}}
QComboBox::drop-down {{
    border: none;
    width: 16px;
}}
QComboBox QAbstractItemView {{
    background-color: #181e28;
    border: 1px solid #2d384a;
    selection-background-color: {T['accent_primary']};
    color: #f1f5f9;
}}

QCheckBox {{
    color: #e2e8f0;
    spacing: 6px;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid #334155;
    border-radius: 2px;
    background-color: #181e28;
}}
QCheckBox::indicator:checked {{
    background-color: {T['vm_accent']};
    border-color: {T['vm_accent_hover']};
}}

QGroupBox {{
    border: none;
    border-top: 1px solid #283344;
    margin-top: 10px;
    padding-top: 8px;
    color: #cbd5e1;
    font-size: 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 4px;
    padding: 0 4px;
}}

QDialog {{
    background-color: #181e28;
    color: #f1f5f9;
}}
QToolTip {{
    background-color: #121620;
    color: #f1f5f9;
    border: 1px solid #2d384a;
    padding: 4px 6px;
    font-size: 12px;
}}

QProgressBar {{
    background-color: #181e28;
    border: 1px solid #2d384a;
    border-radius: 2px;
    text-align: center;
    color: #f1f5f9;
    font-size: 12px;
}}
QProgressBar::chunk {{
    background-color: {T['vm_accent']};
}}
"""
