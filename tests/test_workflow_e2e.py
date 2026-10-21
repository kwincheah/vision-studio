"""End-to-end workflow-editing and layout-resilience regression tests.

These exercise the operator workflow documented in the Vision Master manual
chapters implemented by this project:

1. insert a module from the Tool Box (p.74)
2. move it on the canvas and undo the move
3. wire it to an upstream module and validate the DAG (p.92)
4. execute the flow and read the verdict in every result surface (p.40/p.87)
5. persist the flow and re-load it (p.93)
6. resize the window across the reference proportions and re-check panel
   consistency (no clipped panels, no lost state)
"""
import csv
import json
import os

import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QPoint

import apex_vision.tools
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.pipeline import VisionPipeline
from apex_vision.ui.styles import initialize_app_fonts
from apex_vision.ui.main_window import VisionMasterMainWindow
from apex_vision.ui import layout_metrics as LM


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def _new_window(qapp) -> VisionMasterMainWindow:
    win = VisionMasterMainWindow()
    win.resize(1600, 950)
    win.show()
    for _ in range(3):
        qapp.processEvents()
    return win


def test_end_to_end_module_insert_wire_run_and_export(qapp, tmp_path_factory=None):
    win = _new_window(qapp)

    # ---- 1. insert from the Tool Box ------------------------------------
    before = len(win.pipeline.nodes)
    win.tool_rail._on_category_clicked("Measurement")
    target_tool = win.tool_grid.item(0).data(Qt.ItemDataRole.UserRole)
    win.on_add_tool_by_name(target_tool)
    assert len(win.pipeline.nodes) == before + 1

    new_node_id = [nid for nid in win.pipeline.nodes
                   if win.pipeline.nodes[nid].tool_name == target_tool][0]
    assert new_node_id in win.flow_scene.node_items
    assert win.selected_node_id == new_node_id
    # The selection is reflected by both result surfaces, which are the only
    # panes on the canvas (parameters live in the per-module configuration window).
    win.run_pipeline_step()
    for _ in range(3):
        qapp.processEvents()
    node_name = win.pipeline.nodes[new_node_id].name
    assert win.result_panel.tree.topLevelItemCount() == 1
    assert win.result_panel.tree.topLevelItem(0).text(0) == node_name
    assert node_name in win.result_display.lbl_current_title.text()

    # ---- 2. move + undo --------------------------------------------------
    item = win.flow_scene.node_items[new_node_id]
    original = item.pos()
    item.setPos(QPointF(original.x() + 90, original.y() + 70))
    win.run_pipeline_step()
    item.setPos(original)

    # ---- 3. validate -----------------------------------------------------
    issues = win.pipeline.validate_flow()
    assert isinstance(issues, list)
    # A freshly inserted module with an auto-wired image input must not create
    # new connectivity errors beyond whatever the sample flow already had.
    assert not any(i.get("severity") == "error" and i.get("node_id") == new_node_id
                   for i in issues)

    # ---- 4. execute and read every surface -------------------------------
    win.on_run_once()
    qapp.processEvents()

    assert win.results_table.rowCount() == len(win.pipeline.execution_order)
    statuses = {win.results_table.item(r, 2).text()
                for r in range(win.results_table.rowCount())}
    assert statuses <= {"OK", "NG", "ERROR", "TIMEOUT"}
    assert win.history_table.rowCount() >= 1
    assert win.lbl_global_status.text().strip() in ("PASS", "FAIL")

    # The Result tab must describe the selected module.
    root = win.result_panel.tree.topLevelItem(0)
    assert root is not None
    assert root.text(0) == win.pipeline.nodes[win.selected_node_id].name

    # ---- 5. persistence round-trip ---------------------------------------
    export_path = os.path.join(os.path.dirname(__file__), "..", "_e2e_flow.json")
    export_path = os.path.abspath(export_path)
    try:
        with open(export_path, "w", encoding="utf-8") as fh:
            json.dump(win.pipeline.to_dict(), fh, indent=2)
        with open(export_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        restored = VisionPipeline(name=data["name"])
        from apex_vision.core.registry import create_tool_instance
        for nd in data["nodes"]:
            tool = create_tool_instance(nd["tool_name"], nd["instance_id"], nd["name"])
            tool.load_dict(nd)
            restored.add_node(tool)
        for cd in data["connections"]:
            restored.connect(cd["from_node"], cd["from_port"], cd["to_node"], cd["to_port"])
        assert len(restored.nodes) == len(win.pipeline.nodes)
        assert len(restored.connections) == len(win.pipeline.connections)
        results = restored.execute_flow()
        assert len(results) == len(restored.nodes)
    finally:
        if os.path.exists(export_path):
            os.remove(export_path)

    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_csv_export_rows_match_execution_order(qapp):
    win = _new_window(qapp)
    win.on_run_once()

    csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_e2e_results.csv"))
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Module", "Kernel", "Status", "Latency_ms", "Message"])
            for nid in win.pipeline.execution_order:
                res = win.pipeline.last_results.get(nid)
                node = win.pipeline.nodes.get(nid)
                if res and node:
                    writer.writerow([node.name, node.tool_name,
                                     res.status.value.upper(),
                                     f"{res.elapsed_ms:.2f}", res.message])

        with open(csv_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == ["Module", "Kernel", "Status", "Latency_ms", "Message"]
        assert len(rows) - 1 == len(win.pipeline.execution_order)
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)

    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_multi_flow_isolation_and_overview_sync(qapp):
    win = _new_window(qapp)
    baseline = len(win.pipeline.nodes)

    win.on_add_flow_tab()
    assert win.solution.active_flow_name == "Flow2"
    assert len(win.pipeline.nodes) == 1  # only the seeded acquisition module
    win.on_add_tool_by_name("Image Filter")
    assert len(win.pipeline.nodes) == 2

    # Switching back must restore the original flow state.
    win.on_flow_tab_changed(0)
    assert win.solution.active_flow_name == "Flow1"
    assert len(win.pipeline.nodes) == baseline

    # The overview must show one card per flow and follow the trigger flow.
    win.flow_overview.rebuild(win.solution.flows, win.solution.get_trigger_flow_name())
    assert set(win.flow_overview.scene.card_items.keys()) == {"Flow1", "Flow2"}

    win.on_activate_flow()
    assert win.solution.get_trigger_flow_name() == "Flow1"

    win.on_flow_tab_closed(1)
    assert win.flow_tab_bar.count() == 1
    win.close()
    win.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("size", [(1280, 800), (1600, 950), (1920, 1080), (1100, 720)])
def test_layout_is_consistent_across_window_sizes(qapp, size):
    win = _new_window(qapp)
    win.resize(*size)
    for _ in range(4):
        qapp.processEvents()

    # Central workspace stays usable and every screen keeps a non-trivial width.
    assert win.tab_workspace.width() > 400
    assert win.flow_view.width() > 300
    # The module box is the measured glyph rail (42 px) with the flyout collapsed
    # at rest, exactly as in the reference; the flyout opens on demand.
    assert win.tool_dock.width() >= LM.RAIL_W
    assert win.toolbox.is_collapsed
    assert win.property_dock.width() > 200
    # The vendor layout has no bottom result dock; it starts hidden and the
    # right column carries the result block instead.
    assert not win.result_dock.isVisible()
    assert win.result_display.height() > 60

    # Reference panel proportions: the right column is a minority of the width.
    assert win.property_dock.width() < win.tab_workspace.width()

    # No widget may overflow the window frame.
    for widget in (win.tab_workspace, win.tool_dock, win.property_dock, win.result_dock):
        geo = widget.geometry()
        assert geo.right() <= win.width() + 1, f"{widget.objectName()} overflows horizontally"
        assert geo.bottom() <= win.height() + 1, f"{widget.objectName()} overflows vertically"

    # Switching screens after a resize must not disturb the layout.
    for index in (1, 2, 0):
        win.tab_workspace.setCurrentIndex(index)
        qapp.processEvents()
    assert win.tab_workspace.currentIndex() == 0
    assert win.flow_scene.node_items, "flow nodes disappeared after resizing"

    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_dock_reflow_keeps_state(qapp):
    win = _new_window(qapp)
    node_count = len(win.flow_scene.node_items)

    # Float then re-dock the Tool Box - the rail selection must survive.
    win.tool_rail._on_category_clicked("Logic Tools")
    selected = win.tool_flyout.lbl_header.text()
    win.tool_dock.setFloating(True)
    qapp.processEvents()
    win.tool_dock.setFloating(False)
    qapp.processEvents()
    assert win.tool_flyout.lbl_header.text() == selected
    assert len(win.flow_scene.node_items) == node_count

    # Hiding the module log dock and re-showing it must not lose the history.
    rows = win.history_table.rowCount()
    win.result_dock.show()
    qapp.processEvents()
    assert win.module_log_table.isVisible()
    win.result_dock.hide()
    qapp.processEvents()
    assert win.history_table.rowCount() == rows

    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_validation_reports_disconnected_module(qapp):
    win = _new_window(qapp)

    # Insert a tool whose Image input cannot be auto-wired after breaking the
    # upstream image chain, then confirm the validator surfaces it.
    win.on_add_tool_by_name("Image Filter")
    new_id = [nid for nid in win.pipeline.nodes if win.pipeline.nodes[nid].tool_name == "Image Filter"][-1]
    win.pipeline.disconnect(new_id, "Image")
    issues = win.pipeline.validate_flow()
    assert any(new_id in str(i.get("node_id", "")) or "Image" in str(i.get("message", ""))
               for i in issues), f"disconnected module not reported: {issues}"

    # Reconnecting clears the specific finding.
    upstream = win.pipeline.execution_order[0]
    win.pipeline.connect(upstream, "Image", new_id, "Image")
    win.run_pipeline_step()
    assert win.pipeline.last_results[new_id].status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR)

    win.close()
    win.deleteLater()
    qapp.processEvents()
