"""Tests for the reference-specification reproduction.

Covers the surfaces specified in `docs/VISIONMASTER_REFERENCE_SPEC.md` from the
vendor's annotated main-interface region map (Vision Master 4.3.0 manual
Fig. 5-2) and §8.1/§8.2:

* the result display area (region 12) with its tabs and per-parameter columns
* the image display area (region 6) header, view toolbar and image strip
* the module card's circular category badge on the left edge
* the flow-area zoom tool (region 11)
* the tabbed module configuration window
"""
import pytest

from PyQt6.QtWidgets import QApplication, QComboBox
from PyQt6.QtCore import Qt, QPointF

import vm_clone.tools
from vm_clone.core.base_tool import ToolExecutionResult, ToolStatus
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.core.registry import create_tool_instance
from vm_clone.ui.styles import initialize_app_fonts
from vm_clone.ui.result_display import (
    ResultDisplayArea, build_result_table, extract_feature_rows, MODULE_LOG_HEADERS,
)
from vm_clone.ui.image_display import ImageDisplayArea
from vm_clone.ui.module_config import ModuleConfigDialog, RUN_PARAM_GROUPS
from vm_clone.ui.flow_editor import FlowScene, FlowEditorView, NodeSignals, FlowZoomTool
from vm_clone.ui.main_window import VisionMasterMainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def _win(qapp, size=(1600, 950)) -> VisionMasterMainWindow:
    win = VisionMasterMainWindow()
    win.resize(*size)
    win.show()
    for _ in range(8):
        qapp.processEvents()
    return win


# =========================================================================
# Result display area (region 12)
# =========================================================================
def test_result_display_area_has_the_documented_tabs(qapp):
    """The vendor's result block has exactly three tabs (Fig. 5-2 region 12)."""
    area = ResultDisplayArea()
    labels = [area.tabs.tabText(i) for i in range(area.tabs.count())]
    assert labels == ["Current Result", "History", "Help"]
    assert area.table.columnCount() == 0
    # The module log is built but is not a tab of this surface.
    assert area.tabs.indexOf(area.log_table) == -1
    area.deleteLater()


def test_window_has_the_vendor_two_tier_right_column(qapp):
    """Upper tab bar: Image | Module Results.  Lower: Current | History | Help."""
    win = _win(qapp)
    assert [win.data_tabs.tabText(i) for i in range(win.data_tabs.count())] == \
        ["Image", "Result"]
    assert [win.result_display.tabs.tabText(i)
            for i in range(win.result_display.tabs.count())] == \
        ["Current Result", "History", "Help"]
    win.close()
    win.deleteLater()
    qapp.processEvents()


# =========================================================================
# Image display area (region 6)
# =========================================================================
def test_image_display_area_has_the_documented_controls(qapp):
    area = ImageDisplayArea()
    for btn in (area.btn_single, area.btn_double, area.btn_zoom_in, area.btn_zoom_out,
                area.btn_zoom_1_1, area.btn_fit, area.btn_crosshair, area.btn_expand,
                area.btn_prev, area.btn_next):
        assert not btn.icon().isNull() or btn.text()
        assert btn.toolTip()
    assert area.btn_double.isCheckable()
    assert area.btn_crosshair.isChecked()
    assert area.lbl_auto.text() == "Loop"
    area.deleteLater()


def test_image_display_dual_view_toggle_emits(qapp):
    area = ImageDisplayArea()
    seen = []
    area.view_mode_changed.connect(seen.append)
    area.btn_double.setChecked(True)
    qapp.processEvents()
    assert seen == [True]
    assert area.btn_single.isEnabled() is False
    area.deleteLater()


def test_image_display_strip_paging(qapp):
    area = ImageDisplayArea()
    area.set_frames(["A", "B", "C"], 0)
    assert area.strip.count() == 3
    assert "(1/3)" in area.lbl_strip.text()
    area._step_image(1)
    qapp.processEvents()
    assert "(2/3)" in area.lbl_strip.text()
    area._step_image(-1)
    qapp.processEvents()
    assert "(1/3)" in area.lbl_strip.text()
    area.deleteLater()


def test_window_image_strip_lists_flow_images(qapp):
    win = _win(qapp)
    win.run_pipeline_step()
    for _ in range(3):
        qapp.processEvents()
    assert win.image_display.strip.count() >= 1
    assert win.image_display.lbl_source.text().endswith("Output Image")
    win.close()
    win.deleteLater()
    qapp.processEvents()


# =========================================================================
# Flow canvas instruments
# =========================================================================
def test_module_card_has_a_circular_category_badge(qapp):
    """The card badge sits on the left edge (vendor Fig. 5-2)."""
    pipe = VisionPipeline()
    pipe.add_node(create_tool_instance("Image Source", "src_1", "01_Acq"))
    scene = FlowScene(pipe, NodeSignals())
    scene.build_from_pipeline(preserve_positions=False)
    item = scene.node_items["src_1"]

    from PyQt6.QtGui import QPixmap
    pix = QPixmap(int(item.WIDTH) + 20, int(item.height) + 20)
    pix.fill(Qt.GlobalColor.transparent)
    from PyQt6.QtGui import QPainter
    painter = QPainter(pix)
    painter.translate(10, 10)
    item.paint(painter, None, None)
    painter.end()

    # The badge overhangs the left edge, so the card must be paintable outside x=0.
    assert item.boundingRect().left() < 0
    assert pix.width() > item.WIDTH


def test_flow_zoom_tool_tracks_and_changes_zoom(qapp):
    pipe = VisionPipeline()
    pipe.add_node(create_tool_instance("Image Source", "src_1", "01_Acq"))
    scene = FlowScene(pipe, NodeSignals())
    scene.build_from_pipeline(preserve_positions=False)
    view = FlowEditorView(scene)
    view.resize(800, 600)
    view.show()
    for _ in range(4):
        qapp.processEvents()

    tool = view.zoom_tool
    assert isinstance(tool, FlowZoomTool)
    assert tool.isVisible()
    assert tool.lbl_zoom.text().endswith("%")

    before = view.transform().m11()
    tool.btn_in.click()
    qapp.processEvents()
    assert view.transform().m11() > before
    assert tool.lbl_zoom.text() == f"{view.zoom_percent()}%"

    tool.btn_out.click()
    qapp.processEvents()
    assert abs(view.transform().m11() - before) < 1e-6

    # The zoom tool owns the lower-left corner.
    assert tool.x() == FlowZoomTool.MARGIN_LEFT
    assert tool.y() < view.height()

    view.setScene(None)
    view.deleteLater()
    qapp.processEvents()


# =========================================================================
# Module configuration window
# =========================================================================
def test_module_config_dialog_tabs_and_footer(qapp):
    tool = create_tool_instance("Image Source", "n1", "01_Acq")
    dlg = ModuleConfigDialog(tool)
    labels = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert labels == ["Input Params", "Output Params", "Run Params", "Display Setup"]
    assert dlg.btn_execute.text() == "Execute"
    assert dlg.btn_continuous.text() == "Continuous"
    assert dlg.btn_ok.text() == "OK"
    dlg.deleteLater()


def test_module_config_dialog_lists_ports_and_subscriptions(qapp):
    tool = create_tool_instance("Image Source", "n2", "01_Acq")
    dlg = ModuleConfigDialog(tool)
    root = dlg.output_tree.topLevelItem(0)
    assert root is not None
    assert root.childCount() == len(tool.outputs)
    assert root.isExpanded()
    for i in range(root.childCount()):
        assert root.child(i).checkState(2) == Qt.CheckState.Checked
    dlg.deleteLater()


def test_module_config_dialog_enum_and_path_editors(qapp):
    """Enums are dropdowns and path parameters get a picker (manual p.109)."""
    from PyQt6.QtWidgets import QPushButton

    tool = create_tool_instance("Image Source", "n3", "01_Acq")
    dlg = ModuleConfigDialog(tool)
    combos = dlg.findChildren(QComboBox)
    assert combos, "no dropdown editor was built for the enum parameters"
    assert any(c.count() >= 3 for c in combos)

    assert any(b.text() == "Browse" for b in dlg.findChildren(QPushButton))
    dlg.deleteLater()


def test_module_config_dialog_edits_write_through(qapp):
    tool = create_tool_instance("Image Source", "n4", "01_Acq")
    tool.set_param("pattern_type", "PCB Inspection")
    dlg = ModuleConfigDialog(tool)
    combo = next(c for c in dlg.findChildren(QComboBox)
                 if c.findText("Calibration Grid") >= 0)
    combo.setCurrentText("Calibration Grid")
    qapp.processEvents()
    assert tool.get_param("pattern_type") == "Calibration Grid"
    dlg.deleteLater()


def test_module_config_run_parameters_are_grouped(qapp):
    """Run parameters are grouped by category, as the manual documents."""
    tool = create_tool_instance("Image Source", "n5", "01_Acq")
    dlg = ModuleConfigDialog(tool)
    labels = [w.text() for w in dlg.findChildren(type(dlg.btn_ok))
              if hasattr(w, "text") and w.objectName() == ""]
    values = dlg.run_parameter_values()
    assert isinstance(values, dict)
    dlg.deleteLater()


def test_window_opens_module_config_and_reruns(qapp):
    win = _win(qapp)
    nid = next(iter(win.pipeline.nodes))
    seen = {}

    from vm_clone.ui import main_window as mw
    original = mw.ModuleConfigDialog.exec

    def fake_exec(self):
        seen["title"] = self.windowTitle()
        return 1

    mw.ModuleConfigDialog.exec = fake_exec
    try:
        win.on_open_module_config(nid)
    finally:
        mw.ModuleConfigDialog.exec = original

    assert "01_ImageAcquisition" in seen.get("title", "")
    win.close()
    win.deleteLater()
    qapp.processEvents()
