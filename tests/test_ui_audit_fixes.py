"""Regression tests for the UI/UX audit fixes.

Each test pins a defect that was found by inspecting rendered screenshots:

* Control Toolbar overcrowding - controls were pushed into an overflow menu and
  the status badge was squeezed out of the strip at 1600 px and below.
* Flow tab labels - long flow names pushed the verdict and cycle time out of the
  tab, so no verdict was readable.
* Result grid - the "Global Variable" column and its header were clipped because
  the column model sized for a stale viewport width.
* Inspector - the duplicate "MODULE OUTPUTS" table ate the parameter surface's
  vertical space.
* Validation dialog - the diagnostic message column was truncated.
* Panel proportions - the central canvas was starved at 1600 px.
"""
import pytest

from PyQt6.QtWidgets import QApplication, QToolBar
from PyQt6.QtCore import Qt, QSize

import apex_vision.tools
from apex_vision.ui.styles import initialize_app_fonts
from apex_vision.ui.result_panel import ModuleResultPanel, ResultTreeWidget, COL_PARAM, COL_VALUE, COL_LINK
from apex_vision.ui.main_window import ApexMainWindow, FlowValidationDialog
from apex_vision.ui import layout_metrics as LM
from apex_vision.core.base_tool import ToolExecutionResult, ToolStatus

SIZES = [(1600, 950), (1440, 900), (1280, 800), (1100, 720)]


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def _win(qapp, size=(1600, 950)) -> ApexMainWindow:
    win = ApexMainWindow()
    win.resize(*size)
    win.show()
    for _ in range(6):
        qapp.processEvents()
    win._apply_responsive_chrome()
    for _ in range(4):
        qapp.processEvents()
    return win


def _toolbar_buttons(toolbar: QToolBar):
    """Every QToolButton the toolbar actually creates (not its overflow menu)."""
    from PyQt6.QtWidgets import QToolButton
    return [b for b in toolbar.findChildren(QToolButton)
            if b.objectName() != "qt_toolbar_ext_button"]


# =========================================================================
# Control Toolbar
# =========================================================================
@pytest.mark.parametrize("size", SIZES)
def test_toolbar_never_overflows(qapp, size):
    """No toolbar control may be pushed into the overflow popup.

    The chrome degrades explicitly (see ``_apply_responsive_chrome``) rather than
    letting Qt hide the tail of the strip, so the overflow extension button must
    stay invisible at every supported width.
    """
    win = _win(qapp, size)

    for toolbar in (win.toolbar_resources, win.toolbar_flows):
        ext = [b for b in toolbar.findChildren(type(win.btn_lock))
               if b.objectName() == "qt_toolbar_ext_button"]
        assert not [b for b in ext if b.isVisible()], (
            f"{toolbar.objectName()} overflowed at {size}"
        )

        for btn in _toolbar_buttons(toolbar):
            if not btn.isVisible():
                continue
            geo = btn.geometry()
            assert geo.right() <= toolbar.width() + 1, (
                f"{btn.toolTip()!r} is clipped by {toolbar.objectName()} at {size}"
            )

    # Primary execution controls must always remain visible.
    for btn in (win.btn_run_once, win.btn_continuous, win.btn_stop, win.btn_lock,
                win.btn_draw_roi, win.btn_hist):
        assert btn.isVisible(), f"{btn.toolTip()!r} hidden at {size}"

    win.close()
    win.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("size", SIZES)
def test_status_badge_and_hint_visible(qapp, size):
    win = _win(qapp, size)
    assert win.lbl_global_status.isVisible()
    assert win.lbl_global_status.text().strip() != ""
    assert win.lbl_view_status.isVisible()
    # The badge must have been given real width, not collapsed to zero.
    assert win.lbl_global_status.width() >= 44
    win.close()
    win.deleteLater()
    qapp.processEvents()


def _resize(win, qapp, w, h):
    win.resize(w, h)
    for _ in range(8):
        qapp.processEvents()
    win._apply_responsive_chrome()
    for _ in range(4):
        qapp.processEvents()


def test_responsive_chrome_degrades_in_order(qapp):
    """Wide -> everything; narrow -> the secondary viewport tools go first."""
    win = _win(qapp, (1600, 950))
    assert win.btn_arrange.isVisible()
    assert win.btn_fit.isVisible()
    assert win.lbl_view_status.isVisible()

    _resize(win, qapp, 1350, 900)
    assert win.btn_arrange.isVisible()
    assert win.lbl_view_status.isVisible()

    _resize(win, qapp, 1100, 720)
    assert not win.btn_arrange.isVisible()
    assert not win.btn_fit.isVisible()
    # Primary execution + status strip survive at every width.
    assert win.btn_run_once.isVisible()
    assert win.btn_stop.isVisible()
    assert win.lbl_view_status.isVisible()

    # Restoring the width restores the chrome.
    _resize(win, qapp, 1600, 950)
    assert win.btn_arrange.isVisible()
    assert win.btn_fit.isVisible()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_all_documented_toolbar_controls_present(qapp):
    """The 15 Control Toolbar entries from manual p.70 must all exist."""
    win = _win(qapp)
    tooltips = " | ".join(
        b.toolTip() for tb in (win.toolbar_resources, win.toolbar_flows)
        for b in _toolbar_buttons(tb)
    )
    for needed in ("Save Solution", "Open Solution", "Undo", "Redo", "Locking",
                   "Camera Set", "Controller Management", "Global Variable",
                   "Communication Management", "Global Trigger", "Global Script",
                   "Once", "Continuously", "Stop", "Operation Interface"):
        assert needed in tooltips, f"missing toolbar control: {needed}"
    win.close()
    win.deleteLater()
    qapp.processEvents()


# =========================================================================
# Flow tab labels
# =========================================================================
def test_flow_tab_keeps_verdict_and_time_for_long_names(qapp):
    win = _win(qapp)
    win.solution.flows["PCB_AOI_Solution_Line_A"] = win.solution.flows.pop("Flow1")
    win.solution.flows["PCB_AOI_Solution_Line_A"].name = "PCB_AOI_Solution_Line_A"
    win.solution.active_flow_name = "PCB_AOI_Solution_Line_A"
    win._refresh_flow_tabs()
    win.run_pipeline_step()
    qapp.processEvents()

    label = win.flow_tab_bar.tabText(0)
    assert "PASS" in label or "FAIL" in label, f"verdict missing from tab: {label!r}"
    assert "ms" in label, f"cycle time missing from tab: {label!r}"
    assert "…" in label, "long flow name was not elided"
    win.close()
    win.deleteLater()
    qapp.processEvents()


# =========================================================================
# Result grid column model
# =========================================================================
@pytest.mark.parametrize("width", [430, 360, 300, 260, 200])
def test_result_columns_always_fit(qapp, width):
    panel = ModuleResultPanel({"g_CountOK": 0})
    panel.resize(width, 300)
    panel.show()
    qapp.processEvents()
    panel.refresh_columns()
    qapp.processEvents()

    header = panel.tree.header()
    total = sum(header.sectionSize(c) for c in range(3))
    vp = panel.tree.viewport().width()
    assert total <= vp + 1, f"columns overflow the viewport at width {width}: {total} > {vp}"

    # Name and value must stay usable whenever they are shown.
    assert header.sectionSize(COL_PARAM) >= 70
    assert header.sectionSize(COL_VALUE) >= 56

    if not panel.tree.isColumnHidden(COL_LINK):
        # Column 3 must be wide enough for its own header text.
        from PyQt6.QtGui import QFontMetrics
        needed = QFontMetrics(header.font()).horizontalAdvance(
            panel.tree.headerItem().text(COL_LINK)) + 12
        assert header.sectionSize(COL_LINK) >= needed, (
            f"global-variable column clipped at width {width}"
        )
    panel.close()
    panel.deleteLater()
    qapp.processEvents()


def test_result_columns_refit_when_tab_is_shown(qapp):
    """A stacked widget only lays out the current page; columns must refit."""
    win = _win(qapp)
    win.resizeDocks([win.property_dock], [260], Qt.Orientation.Horizontal)
    qapp.processEvents()

    win.data_tabs.setCurrentWidget(win.result_panel)
    for _ in range(3):
        qapp.processEvents()

    header = win.result_panel.tree.header()
    total = sum(header.sectionSize(c) for c in range(3))
    assert total <= win.result_panel.tree.viewport().width() + 1
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_result_tree_does_not_force_dock_width(qapp):
    """The tree's own size hint must not stop the dock from shrinking."""
    tree = ResultTreeWidget()
    assert tree.sizeHint().width() <= 200
    assert tree.minimumSizeHint().width() <= 200
    tree.deleteLater()


# =========================================================================
# Right column: no parameter pane on the canvas (vendor layout)
# =========================================================================
def test_canvas_has_no_parameter_pane(qapp):
    """The reference keeps parameters in the module configuration window.

    The canvas therefore carries exactly two right-column blocks — the display
    block and the result block — and the result surfaces keep usable heights.
    """
    win = _win(qapp)
    assert not hasattr(win, "inspector"), "no parameter pane may sit on the canvas"
    assert win.split_right.count() == 2
    assert win.image_canvas.height() >= 70
    assert win.result_display.table.height() >= 50
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_module_config_window_edits_parameters(qapp):
    """Parameters are edited in the per-module dialog, as in the reference."""
    from apex_vision.ui.module_config import ModuleConfigDialog

    win = _win(qapp)
    win.run_pipeline_step()
    qapp.processEvents()

    node_id = win.selected_node_id
    tool = win.pipeline.nodes[node_id]
    res = win.pipeline.last_results.get(node_id)
    assert res is not None

    dlg = ModuleConfigDialog(tool, res, win)
    assert dlg.tabs.count() == 4
    # The dialog exposes the module's ports and its editable run parameters.
    assert dlg.output_tree.topLevelItem(0).childCount() == len(tool.outputs)
    assert dlg.run_editors, "the Run Params tab must carry editors"
    dlg.deleteLater()
    win.close()
    win.deleteLater()
    qapp.processEvents()


# =========================================================================
# Validation dialog
# =========================================================================
def test_validation_dialog_message_column_is_wide_enough(qapp):
    from PyQt6.QtWidgets import QTableWidget

    issues = [
        {"severity": "warning", "node_id": "node_tcp",
         "message": "Module '07_SendToPLC' input 'Trigger' has no incoming connection."},
        {"severity": "error", "node_id": "node_x",
         "message": "Cycle detected: 05_SurfaceScratchCheck -> 06_QualityJudge -> 05_SurfaceScratchCheck"},
    ]
    dlg = FlowValidationDialog(issues, None)
    dlg.show()
    qapp.processEvents()

    table = dlg.findChild(QTableWidget)
    assert table is not None and table.rowCount() == 2
    header = table.horizontalHeader()
    # The message column is the stretch column and must dominate the dialog.
    assert header.sectionSize(2) > header.sectionSize(0) + header.sectionSize(1)
    assert header.sectionSize(2) >= 260
    # Full message text must be recoverable even if visually elided.
    assert table.item(0, 2).toolTip() == issues[0]["message"]
    dlg.close()
    dlg.deleteLater()
    qapp.processEvents()


# =========================================================================
# Panel proportions
# =========================================================================
@pytest.mark.parametrize("size", SIZES)
def test_central_canvas_keeps_working_area(qapp, size):
    """The measured reference proportions must hold at every window size.

    Ratios come from `layout_metrics`, which is derived from pixel measurements of
    the vendor figures (see the measured reference storyboard): rail 0.0513,
    canvas 0.5452, right column 0.4034 of the window interior.
    """
    win = _win(qapp, size)
    total = (win.tool_dock.width() + win.centralWidget().width()
             + win.property_dock.width())

    # The canvas keeps the measured share (within 2.5 % at the smallest size,
    # where the dock minimums start to bind).
    canvas_share = win.centralWidget().width() / total
    assert abs(canvas_share - LM.CANVAS_RATIO) <= 0.03, (
        f"canvas share {canvas_share:.4f} off the measured {LM.CANVAS_RATIO} "
        f"at {size}"
    )
    right_share = win.property_dock.width() / total
    assert abs(right_share - LM.RIGHT_COL_RATIO) <= 0.02, (
        f"right column share {right_share:.4f} off the measured "
        f"{LM.RIGHT_COL_RATIO} at {size}"
    )
    # The rail is the measured fixed glyph strip, with the flyout collapsed.
    assert win.tool_dock.width() >= LM.RAIL_W
    assert win.toolbox.is_collapsed
    assert win.centralWidget().width() > win.property_dock.width()
    assert win.centralWidget().width() > win.tool_dock.width()
    # The vendor layout has no bottom result dock; it must start hidden.
    assert not win.result_dock.isVisible()
    win.close()
    win.deleteLater()
    qapp.processEvents()
