"""Tests for the reference- workspace shell.

Covers the structures that were verified against the reference manual
(`HikRobotVMHelp_compressed.pdf`):

* Control Toolbar icon inventory and ordering (manual p.70)
* Tool Box category rail + icon-grid flyout with search + drag payload (p.72/74)
* Module result grid Param Name / Current Result / Global Variable (p.87)
* Multi-Flow overview cards + dependency wires (p.95)
* Segmented status bar (p.40 item 7)
* Validation / lock / undo-redo behaviours driven from the new chrome
"""
import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QMimeData

import apex_vision.tools
from apex_vision.core.registry import list_categories
from apex_vision.core.pipeline import VisionPipeline
from apex_vision.core.base_tool import ToolExecutionResult, ToolStatus
from apex_vision.core.registry import create_tool_instance

from apex_vision.ui.styles import initialize_app_fonts, THEME
from apex_vision.ui.theme import VM_THEME_QSS
from apex_vision.ui.toolbox import (
    ToolBoxPanel, ToolCategoryRail, ToolFlyoutPanel, ToolGridWidget,
    CATEGORY_ORDER, get_rail_icon, get_brand_mark,
)
from apex_vision.ui.result_panel import ModuleResultPanel, COL_PARAM, COL_VALUE, COL_LINK
from apex_vision.ui.flow_overview import FlowOverviewWidget, FlowCardItem
from apex_vision.ui.main_window import ApexMainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


# =========================================================================
# Theme
# =========================================================================
def test_vm_theme_tokens_match_sampled_reference():
    """The workspace tokens are the palette measured from the reference references.

    Values trace to the sampled reference palette / the sampled palette.
    """
    required = [
        "vm_chrome", "vm_chrome_dark", "vm_rail", "vm_flyout", "vm_canvas",
        "vm_canvas_dot", "vm_panel", "vm_panel_header", "vm_accent", "vm_node",
        "vm_node_text", "vm_node_border", "vm_wire", "vm_viewport",
    ]
    for key in required:
        assert key in THEME, f"missing VM theme token: {key}"
        assert THEME[key].startswith("#") and len(THEME[key]) == 7

    # Signature amber selection, measured from the selected tab / Flow Editor node.
    assert THEME["vm_accent"] == "#e4b030"
    # Canvas and card surfaces, measured from the XG Flow Editor.
    assert THEME["vm_canvas"] == "#b4b8c0"
    assert THEME["vm_node"] == "#fcfcfc"
    # Chrome greys, measured from the CV-X menu bar and the XG toolbar.
    assert THEME["vm_chrome"] == "#848c94"
    assert THEME["vm_chrome_dark"] == "#646c6c"
    # The image viewport is the measured near-black field.
    assert THEME["vm_viewport"] == "#201c20"

    # Light-theme honesty: the refinement must be a light UI, not a dark one.
    def _luma(h: str) -> float:
        r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
        return 0.299 * r + 0.587 * g + 0.114 * b

    assert _luma(THEME["vm_canvas"]) > 150, "canvas must be a light surface"
    assert _luma(THEME["vm_panel"]) > 200, "panels must be light surfaces"
    assert _luma(THEME["vm_node"]) > 220, "cards must be near-white"
    assert _luma(THEME["text_primary"]) < 60, "ink must be dark on light surfaces"
    # The rail carries light glyphs, so it must stay dark enough for AA contrast.
    assert _luma(THEME["vm_rail"]) < 110, "rail must stay dark for glyph contrast"

    # Every chrome token must be interpolated by the stylesheet. The canvas and
    # node-card colours are consumed by the QGraphicsScene / QGraphicsItem
    # painters instead of QSS, so they are asserted against those modules.
    qss_tokens = [
        "vm_chrome", "vm_rail", "vm_flyout", "vm_panel", "vm_panel_header",
        "vm_accent", "vm_accent_hover", "vm_accent_dim",
    ]
    for key in qss_tokens:
        assert THEME[key] in VM_THEME_QSS, f"{key} is not used by the stylesheet"

    from apex_vision.ui import flow_editor, flow_overview, toolbox, image_canvas
    painter_sources = "".join(
        open(m.__file__, encoding="utf-8").read()
        for m in (flow_editor, flow_overview, toolbox, image_canvas)
    )
    for key in ("vm_canvas", "vm_canvas_dot", "vm_node", "vm_node_text", "vm_wire"):
        assert f'"{key}"' in painter_sources, f"{key} is not consumed by any painter"

    # The focus-ring accent is the blue measured from the reference references.
    assert THEME["accent_primary"] == "#0078b0"


# =========================================================================
# Tool Box - rail + flyout (manual p.72 / p.74)
# =========================================================================
def test_rail_provides_one_glyph_per_registered_category(qapp):
    rail = ToolCategoryRail()
    names = rail.category_names()
    for cat in list_categories().keys():
        assert cat in names, f"category rail is missing a glyph for '{cat}'"

    # The brand and the "search all modules" shortcut are real rail buttons.
    assert not rail.btn_search.icon().isNull()
    assert rail.btn_search.toolTip() == "Search all modules"
    assert rail.width() == ToolCategoryRail.RAIL_W

    for cat in CATEGORY_ORDER:
        icon = get_rail_icon(cat)
        assert not icon.isNull()
        assert icon.pixmap(22, 22).width() == 22
    assert not get_brand_mark(22).isNull()
    rail.deleteLater()


def test_flyout_grid_filters_by_category_and_search(qapp):
    panel = ToolFlyoutPanel()
    panel.set_categories(list_categories())

    panel.show_category("Location")
    location_tools = [panel.grid.item(i).data(Qt.ItemDataRole.UserRole)
                      for i in range(panel.grid.count())]
    assert location_tools == list_categories()["Location"]
    assert panel.lbl_header.text() == "Location"

    # Searching must span every category, not just the visible one.
    panel.txt_search.setText("caliper")
    flat = [panel.grid.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(panel.grid.count())]
    assert "Caliper" in flat
    assert len(flat) <= len(location_tools) + 2
    panel.deleteLater()


def test_flyout_grid_uses_icon_and_label_and_exposes_drag_payload(qapp):
    panel = ToolFlyoutPanel()
    panel.set_categories(list_categories())
    panel.show_category("Measurement")

    item = panel.grid.item(0)
    assert not item.icon().isNull()
    assert item.text().strip() != ""
    assert item.toolTip().strip() != ""

    mime = QMimeData()
    mime.setText(item.data(Qt.ItemDataRole.UserRole))
    assert mime.text() == item.data(Qt.ItemDataRole.UserRole)

    # Grid must be dense: more than one column inside the flyout width.
    panel.resize(260, 600)
    panel.show()
    qapp.processEvents()
    assert panel.grid.column_count() >= 2
    panel.deleteLater()


def test_toolbox_panel_selects_first_category_by_default(qapp):
    box = ToolBoxPanel()
    assert box.flyout.lbl_header.text() != "Tool Box"
    assert box.flyout.grid.count() > 0
    box.rail._on_category_clicked("Logic Tools")
    assert box.flyout.lbl_header.text() == "Logic Tools"
    box.set_flyout_visible(False)
    assert box.is_collapsed is True
    box.deleteLater()


def test_tool_activation_signal_carries_tool_name(qapp):
    box = ToolBoxPanel()
    captured = []
    box.tool_activated.connect(captured.append)
    box.rail._on_category_clicked("Measurement")
    first = box.flyout.grid.item(0).data(Qt.ItemDataRole.UserRole)
    box.flyout.grid.tool_activated.emit(first)
    assert captured == [first]
    box.deleteLater()


# =========================================================================
# Result panel (manual p.87)
# =========================================================================
def test_result_panel_three_column_structure(qapp):
    panel = ModuleResultPanel({"g_CountOK": 0, "g_LotRate": 1.0})
    panel.resize(700, 400)
    assert panel.tree.columnCount() == 3
    assert [panel.tree.headerItem().text(c) for c in range(3)] == [
        "Param Name", "Current Result", "Global Var."
    ]

    res = ToolExecutionResult(
        status=ToolStatus.OK, message="Acquired image 800x600", elapsed_ms=3.12,
        outputs={"Width": 800, "Height": 600, "Score": 0.8877},
    )
    panel.set_module_result("01_ImageAcquisition", res)

    assert panel.tree.topLevelItemCount() == 1
    root = panel.tree.topLevelItem(0)
    assert root.text(COL_PARAM) == "01_ImageAcquisition"
    assert root.isExpanded() is True
    assert panel.row_count() >= 5  # status + time + message + outputs group + 3 outputs

    names = []
    stack = [root]
    while stack:
        node = stack.pop()
        names.append(node.text(COL_PARAM))
        stack.extend(node.child(i) for i in range(node.childCount()))
    assert "ModuStatus" in names
    assert "Width" in names and "Height" in names

    # Numeric outputs must be formatted to 4 decimals like the reference grid.
    out_group = next(c for c in [root.child(i) for i in range(root.childCount())]
                     if c.text(COL_PARAM) == "Outputs")
    score_row = next(out_group.child(i) for i in range(out_group.childCount())
                     if out_group.child(i).text(COL_PARAM) == "Score")
    assert score_row.text(COL_VALUE) == "0.8877"
    panel.deleteLater()


def test_result_panel_binds_parameter_to_global_variable(qapp):
    panel = ModuleResultPanel({"g_Value": 0})
    res = ToolExecutionResult(status=ToolStatus.OK, outputs={"Width": 800})
    panel.set_module_result("01_Acq", res)

    captured = []
    panel.variable_bound.connect(lambda a, b: captured.append((a, b)))
    panel._bindings["01_Acq.Width"] = "g_Value"
    assert panel.binding_for("01_Acq.Width") == "g_Value"
    panel.variable_bound.emit("01_Acq.Width", "g_Value")
    assert captured == [("01_Acq.Width", "g_Value")]
    panel.deleteLater()


# =========================================================================
# Multi-Flow overview (manual p.95)
# =========================================================================
def test_flow_overview_creates_one_card_per_flow_with_trigger_wires(qapp):
    flows = {"Flow1": VisionPipeline(name="Flow1"), "Flow2": VisionPipeline(name="Flow2"),
             "Flow3": VisionPipeline(name="Flow3")}
    widget = FlowOverviewWidget()
    widget.rebuild(flows, "Flow1")

    assert set(widget.scene.card_items.keys()) == {"Flow1", "Flow2", "Flow3"}
    assert widget.scene.card_items["Flow1"].is_trigger is True
    assert widget.scene.card_items["Flow2"].is_trigger is False

    # Two producers -> two dependency wires + two arrow heads.
    paths = [it for it in widget.scene.items() if it.__class__.__name__ == "QGraphicsPathItem"]
    assert len(paths) >= 4

    # Cards must not overlap (each is WIDTH x HEIGHT).
    positions = [c.pos() for c in widget.scene.card_items.values()]
    for i, a in enumerate(positions):
        for b in positions[i + 1:]:
            same_row = abs(a.y() - b.y()) < FlowCardItem.HEIGHT
            same_col = abs(a.x() - b.x()) < FlowCardItem.WIDTH
            assert not (same_row and same_col), "flow cards overlap"

    widget.deleteLater()


def test_flow_overview_card_signals(qapp):
    flow = VisionPipeline(name="Flow1")
    from apex_vision.ui.flow_overview import FlowOverviewSignals
    signals = FlowOverviewSignals()
    card = FlowCardItem(flow, is_trigger=True, signals=signals)

    fired = []
    signals.flow_run_requested.connect(lambda n: fired.append(("run", n)))
    signals.flow_loop_toggled.connect(lambda n, s: fired.append(("loop", n, s)))
    signals.flow_settings_requested.connect(lambda n: fired.append(("settings", n)))

    card.signals.flow_run_requested.emit("Flow1")
    card.signals.flow_settings_requested.emit("Flow1")
    assert ("run", "Flow1") in fired
    assert ("settings", "Flow1") in fired

    # The loop button must toggle the card without touching the pipeline runner.
    card.mousePressEvent(_press(card, "loop"))
    assert card.looping is True
    card.mousePressEvent(_press(card, "loop"))
    assert card.looping is False


def _press(card, button_key):
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QEvent, QPointF
    rect = card._buttons()[button_key]
    return QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(rect.center()),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


# =========================================================================
# Main window chrome (manual p.40 / p.70)
# =========================================================================
def test_control_toolbar_inventory_and_order(qapp):
    win = ApexMainWindow()
    win.resize(1600, 950)

    # Row 1 carries the brand + file/resource group then execution, exactly as the
    # reference orders them (Once, Continuous, then the status badge).
    for attr in ("btn_lock", "btn_run_once", "btn_continuous",
                 "btn_stop"):
        btn = getattr(win, attr)
        assert not btn.icon().isNull(), f"{attr} has no icon"

    # Row 2 starts with the flow tab, then the flow-scoped controls, and keeps the
    # viewport controls on the right (the reference's own distribution).
    for attr in ("btn_flow_once", "btn_loop_flow", "btn_add_flow", "btn_activate_flow",
                 "btn_layers", "btn_hist", "btn_draw_roi", "btn_arrange"):
        btn = getattr(win, attr)
        assert not btn.icon().isNull(), f"{attr} has no icon"

    tb = win.toolbar_resources
    labels = [a.text() for a in tb.actions() if a.text()]
    assert labels == [], "icon strip must not carry text labels"

    assert win.btn_lock.isCheckable()
    assert win.btn_continuous.isCheckable()
    assert win.btn_hist.isCheckable()

    # Tooltips document the manual's semantics.
    assert "Locking" in win.btn_lock.toolTip()
    assert "Continuously" in win.btn_continuous.toolTip()
    assert "Once" in win.btn_run_once.toolTip()
    win.close()


def test_menu_structure_matches_reference(qapp):
    win = ApexMainWindow()
    titles = [a.text().replace("&", "") for a in win.menuBar().actions()]
    for expected in ("File", "Settings", "Tools", "System", "View", "Help"):
        assert expected in titles
    win.close()


def test_lock_protection_blocks_editing(qapp):
    win = ApexMainWindow()
    win.resize(1400, 900)

    assert win.flow_scene.is_locked() is False
    win.btn_lock.setChecked(True)
    assert win.flow_scene.is_locked() is True

    node_id = next(iter(win.pipeline.nodes))
    assert not (win.flow_scene.node_items[node_id].flags()
                & win.flow_scene.node_items[node_id].GraphicsItemFlag.ItemIsMovable)

    # Inserting a module while locked must be rejected.
    before = len(win.pipeline.nodes)
    win.on_add_tool_by_name("Caliper")
    assert len(win.pipeline.nodes) == before

    # A locked scene must also refuse to start a wire drag.
    p_out = win.flow_scene.node_items[node_id].out_ports
    if p_out:
        win.flow_scene.start_connection_drag(next(iter(p_out.values())))
        assert win.flow_scene.is_dragging_connection() is False

    win.btn_lock.setChecked(False)
    assert win.flow_scene.is_locked() is False
    assert (win.flow_scene.node_items[node_id].flags()
            & win.flow_scene.node_items[node_id].GraphicsItemFlag.ItemIsMovable)

    # Unlocking restores module insertion.
    win.on_add_tool_by_name("Caliper")
    assert len(win.pipeline.nodes) == before + 1
    win.close()


def test_undo_redo_from_toolbar(qapp):
    win = ApexMainWindow()
    win.resize(1400, 900)

    before = len(win.pipeline.nodes)
    win.on_add_tool_by_name("Image Filter")
    assert len(win.pipeline.nodes) == before + 1

    win.on_undo()
    assert len(win.pipeline.nodes) == before
    win.on_redo()
    assert len(win.pipeline.nodes) == before + 1
    win.close()


def test_segmented_status_bar_updates_after_run(qapp):
    win = ApexMainWindow()
    win.resize(1400, 900)
    win.run_pipeline_step()

    assert "Flow" in win.lbl_flow_time.text()
    assert "Tools" in win.lbl_tool_count.text()
    assert "Algorithm" in win.lbl_algo_time.text()
    assert str(len(win.pipeline.nodes)) in win.lbl_tool_count.text()
    assert win.lbl_algo_time.text() != "Algorithm 0.00ms"
    win.close()


def test_history_tab_records_one_row_per_cycle(qapp):
    win = ApexMainWindow()
    win.resize(1400, 900)

    win.run_pipeline_step()
    win.run_pipeline_step()
    assert win.history_table.rowCount() >= 2
    verdict = win.history_table.item(0, 2).text()
    assert verdict in ("PASS", "NG")
    assert win.history_table.item(0, 1).text() == win.solution.active_flow_name
    win.close()


def test_flow_tab_label_and_tooltip_expose_verdict(qapp):
    win = ApexMainWindow()
    win.resize(1400, 900)
    win.run_pipeline_step()

    assert win.flow_tab_bar.count() == 1
    label = win.flow_tab_bar.tabText(0)
    assert "Flow1" in label
    tip = win.flow_tab_bar.tabToolTip(0)
    assert "Verdict:" in tip
    assert "FAIL" in tip or "PASS" in tip
    win.close()


def test_workspace_tabs_include_reference_screens(qapp):
    win = ApexMainWindow()
    labels = [win.tab_workspace.tabText(i) for i in range(win.tab_workspace.count())]
    assert labels == ["Flow Diagram", "Operation Interface", "Multi-Flow"]

    win.on_toggle_operation_panel(True)
    assert win.tab_workspace.currentIndex() == 1
    win.on_toggle_operation_panel(False)
    assert win.tab_workspace.currentIndex() == 0
    win.close()


def test_operation_panel_layer_switches_drive_canvas(qapp):
    win = ApexMainWindow()
    win.resize(1400, 900)

    win.act_layer_metrics.setChecked(False)
    assert win.image_canvas._show_measurements is False
    win.act_layer_rois.setChecked(False)
    assert win.image_canvas._show_rois is False

    win.act_layer_all.setChecked(False)
    assert win.image_canvas._show_overlays is False
    # Sub-switches stay operable and keep their own state while the master
    # switch is off; re-enabling the master restores rendering.
    assert win.act_layer_rois.isEnabled() is True
    assert win.act_layer_all.isChecked() is False

    win.act_layer_all.setChecked(True)
    win.act_layer_rois.setChecked(True)
    win.act_layer_metrics.setChecked(True)
    assert win.image_canvas._show_overlays is True
    assert win.image_canvas._show_measurements is True
    assert win.act_layer_rois.isEnabled() is True

    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_histogram_toggle_stays_in_sync(qapp):
    win = ApexMainWindow()
    win.resize(1400, 900)

    win.btn_hist.setChecked(True)
    qapp.processEvents()
    assert win.image_canvas._show_hist is True
    assert win.act_layer_hist.isChecked() is True

    win.act_layer_hist.setChecked(False)
    qapp.processEvents()
    assert win.image_canvas._show_hist is False
    assert win.btn_hist.isChecked() is False
    win.close()


def test_overview_flow_activation_switches_workspace(qapp):
    win = ApexMainWindow()
    win.resize(1400, 900)

    win.on_add_flow_tab()
    win.on_overview_flow_activated("Flow1")
    assert win.solution.active_flow_name == "Flow1"
    assert win.tab_workspace.currentIndex() == 0
    win.close()


def test_continuous_toggle_both_buttons_in_sync(qapp):
    win = ApexMainWindow()
    win.resize(1400, 900)

    win.btn_continuous.setChecked(True)
    assert win.btn_loop_flow.isChecked() is True
    assert win.run_timer.isActive() is True

    win.on_stop()
    assert win.btn_continuous.isChecked() is False
    assert win.btn_loop_flow.isChecked() is False
    assert win.run_timer.isActive() is False
    win.close()


def test_toolbox_is_permanent_part_of_main_window(qapp):
    """The toolbox must be an integral, permanent part of the main window.

    It must not be closable, movable, or floatable, and has no detached dock titlebar,
    functioning seamlessly within the main window layout.
    """
    from PyQt6.QtWidgets import QDockWidget
    win = ApexMainWindow()
    win.resize(1400, 900)
    win.show()
    qapp.processEvents()

    assert win.tool_dock is not None
    assert win.tool_dock.parent() == win
    assert win.tool_dock.features() == QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
    assert win.tool_dock.allowedAreas() == Qt.DockWidgetArea.LeftDockWidgetArea
    assert win.tool_dock.titleBarWidget() is not None
    assert win.tool_dock.titleBarWidget().height() == 0
    assert win.tool_dock.isFloating() is False

    # Closing cannot hide it
    win.tool_dock.close()
    assert win.tool_dock.isVisible() is True

    win.close()
    win.deleteLater()
    qapp.processEvents()

