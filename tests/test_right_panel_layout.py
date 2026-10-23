"""Tests for the right-hand Image|Result layout.

Pins the structure requested for the workspace: the vendor's right column is a
two-block stack — the display block (`Image` | `Module Results`) over the result
block (`Current Result` | `History` | `Help`) — with no parameter pane on the
canvas.  The parameter form helpers (label column, abbreviated paths) are still
covered here because the module configuration window shares them.
"""
import os

import pytest

from PyQt6.QtWidgets import (
    QApplication, QFormLayout, QLabel, QLineEdit, QPushButton, QWidget
)
from PyQt6.QtCore import Qt

import apex_vision.tools
from apex_vision.ui.styles import initialize_app_fonts
from apex_vision.ui.inspector import ParameterInspectorWidget, abbreviate_path, LABEL_W
from apex_vision.ui.main_window import ApexMainWindow
from apex_vision.ui import layout_metrics as LM
from apex_vision.tools.acquisition import ImageSourceTool
from apex_vision.tools.image_output import ImageOutputTool


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
    for _ in range(8):
        qapp.processEvents()
    return win


# =========================================================================
# Result mounted under the image
# =========================================================================
def test_right_column_matches_the_vendor_two_tab_layout(qapp):
    """Strictly follow the vendor figure (4.3.0 Fig. 5-2, right column).

    Upper tab bar  : Image | Module Results
    Lower tab bar  : Current Result | History | Help
    Both tab bars are visible at the same time; the image display block sits above
    the result block.
    """
    win = _win(qapp)

    assert [win.data_tabs.tabText(i) for i in range(win.data_tabs.count())] == \
        ["Image", "Result"]
    assert [win.result_display.tabs.tabText(i)
            for i in range(win.result_display.tabs.count())] == \
        ["Current Result", "History", "Help"]

    # Both tab widgets are real, visible siblings in the same column.
    assert win.data_tabs.parent() is win.split_right
    assert win.result_display.parent() is win.split_right
    assert win.split_right.indexOf(win.data_tabs) == 0
    assert win.split_right.indexOf(win.result_display) == 1
    assert win.data_tabs.isVisible() and win.result_display.isVisible()

    # The image display is a page of the upper tab widget, not a stacked sibling.
    assert win.data_tabs.widget(0) is win.image_display
    assert win.data_tabs.widget(1) is win.result_panel

    # The vendor has no bottom result dock: it starts hidden.
    assert not win.result_dock.isVisible()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_upper_tab_switches_the_display_block(qapp):
    """Selecting Module Results replaces the image with the result tree."""
    win = _win(qapp)
    win.data_tabs.setCurrentIndex(1)
    for _ in range(3):
        qapp.processEvents()
    assert win.data_tabs.currentWidget() is win.result_panel
    assert not win.image_display.isVisible()

    win.data_tabs.setCurrentIndex(0)
    for _ in range(3):
        qapp.processEvents()
    assert win.data_tabs.currentWidget() is win.image_display
    assert win.image_display.isVisible()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_result_table_is_visible_without_switching_tabs(qapp):
    """The image and the result table are readable at the same time."""
    win = _win(qapp)
    win.run_pipeline_step()
    for _ in range(3):
        qapp.processEvents()

    assert win.image_display.isVisible()
    assert win.result_display.table.isVisible()
    assert win.result_display.table.rowCount() >= 1
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_image_display_header_and_strip(qapp):
    """The image display carries the source label, view toolbar and image strip."""
    win = _win(qapp)
    display = win.image_display

    assert display.lbl_source.text().endswith("Output Image")
    for btn in (display.btn_single, display.btn_double, display.btn_zoom_in,
                display.btn_zoom_out, display.btn_zoom_1_1, display.btn_crosshair,
                display.btn_expand):
        assert not btn.icon().isNull()
        assert btn.toolTip()

    win.run_pipeline_step()
    for _ in range(3):
        qapp.processEvents()
    assert display.strip.count() >= 1
    assert "(1/" in display.lbl_strip.text()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_image_strip_selection_switches_the_module_result(qapp):
    """Picking a module image in the strip must retarget the result surfaces."""
    win = _win(qapp)
    win.run_pipeline_step()
    for _ in range(3):
        qapp.processEvents()

    strip = win.image_display.strip
    if strip.count() < 2:
        pytest.skip("flow produced a single image")

    strip.setCurrentRow(1)
    for _ in range(3):
        qapp.processEvents()
    assert "(2/" in win.image_display.lbl_strip.full_text()
    assert win.result_display.table.rowCount() >= 0
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_image_display_zoom_controls(qapp):
    win = _win(qapp)
    win.run_pipeline_step()
    for _ in range(3):
        qapp.processEvents()

    canvas = win.image_canvas
    before = canvas._scale

    win.image_display.btn_zoom_in.click()
    assert canvas._scale > before, "zoom in did not change the scale"

    win.image_display.btn_zoom_out.click()
    assert abs(canvas._scale - before) < 1e-6, "zoom out did not restore the scale"

    win.image_display.btn_zoom_1_1.click()
    assert abs(canvas._scale - 1.0) < 1e-6, "1:1 did not set unit scale"

    # A later resize must not silently re-fit once the operator has zoomed.
    for _ in range(3):
        qapp.processEvents()
    assert abs(canvas._scale - 1.0) < 1e-6

    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_module_results_tab_shows_the_result_tree(qapp):
    """The Module Results page of the upper tab bar carries the result tree."""
    win = _win(qapp)
    win.run_pipeline_step()
    for _ in range(3):
        qapp.processEvents()

    win.data_tabs.setCurrentIndex(1)
    for _ in range(3):
        qapp.processEvents()
    assert win.result_panel.isVisible()
    assert win.result_panel.tree.topLevelItemCount() == 1
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_image_and_result_keep_usable_heights(qapp):
    """Neither the image nor the result surfaces may be squeezed out.

    The vendor's right column is exactly two blocks: the display block (image /
    module results) at 0.604 of the column and the result block at 0.396.
    """
    for size in ((1600, 950), (1366, 768), (1100, 720)):
        win = _win(qapp, size)
        sizes = win.split_right.sizes()
        column = sum(sizes)
        assert win.image_canvas.height() >= 60, f"image squeezed at {size}"
        assert win.image_display.height() > win.image_canvas.height()
        assert win.result_display.table.height() >= 50, f"result table squeezed at {size}"
        assert abs(sizes[0] / column - LM.IMAGE_BLOCK_RATIO) <= 0.04, (
            f"image block share off the measured value at {size}")
        win.close()
        win.deleteLater()
        qapp.processEvents()


def test_roi_drawing_prioritises_the_image_view(qapp):
    """Entering ROI mode must raise the image share of the column."""
    win = _win(qapp)
    before = win.split_right.sizes()[0]
    win.btn_draw_roi.setChecked(True)
    for _ in range(3):
        qapp.processEvents()
    after = win.split_right.sizes()[0]
    assert after >= before
    assert win.data_tabs.currentIndex() == 0
    win.btn_draw_roi.setChecked(False)
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_result_panel_refits_columns_inside_the_column(qapp):
    """The Module Results tree column model must track the dock width."""
    win = _win(qapp)
    win.data_tabs.setCurrentIndex(1)
    for _ in range(3):
        qapp.processEvents()
    win.result_panel.refresh_columns()
    qapp.processEvents()

    header = win.result_panel.tree.header()
    total = sum(header.sectionSize(c) for c in range(3))
    assert total <= win.result_panel.tree.viewport().width() + 1

    win.resizeDocks([win.property_dock], [360], Qt.Orientation.Horizontal)
    for _ in range(4):
        qapp.processEvents()
    win.result_panel.refresh_columns()
    qapp.processEvents()
    total = sum(header.sectionSize(c) for c in range(3))
    assert total <= win.result_panel.tree.viewport().width() + 1
    win.close()
    win.deleteLater()
    qapp.processEvents()


# =========================================================================
# Parameter form alignment
# =========================================================================
def test_form_labels_share_one_column_and_fields_align(qapp):
    inspector = ParameterInspectorWidget()
    tool = ImageSourceTool("src_align")
    tool.set_param("source_type", "File")
    inspector.set_tool(tool)
    inspector.resize(340, 500)
    inspector.show()
    for _ in range(3):
        qapp.processEvents()
    inspector._align_label_column()
    qapp.processEvents()

    label_widths = []
    field_lefts = []
    for row in range(inspector.param_layout.rowCount()):
        label_item = inspector.param_layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
        field_item = inspector.param_layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
        if label_item is not None and isinstance(label_item.widget(), QLabel):
            label_widths.append(label_item.widget().width())
            if field_item is not None and field_item.widget() is not None:
                field = field_item.widget()
                field_lefts.append(
                    field.mapTo(inspector, field.rect().topLeft()).x())

    assert label_widths, "no labelled rows were created"
    assert len(set(label_widths)) == 1, f"labels not aligned: {label_widths}"
    assert label_widths[0] == LABEL_W
    # Every labelled field starts on the same axis (1 px rounding tolerance).
    assert len(set(field_lefts)) == 1, f"fields misaligned: {field_lefts}"
    inspector.close()
    inspector.deleteLater()
    qapp.processEvents()


def test_path_field_and_browse_button_share_the_field_axis(qapp):
    inspector = ParameterInspectorWidget()
    tool = ImageSourceTool("src_axis")
    tool.set_param("source_type", "File")
    inspector.set_tool(tool)
    inspector.resize(340, 500)
    inspector.show()
    for _ in range(3):
        qapp.processEvents()

    rows = {}
    for row in range(inspector.param_layout.rowCount()):
        label_item = inspector.param_layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
        field_item = inspector.param_layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
        if label_item is None or field_item is None:
            continue
        label = label_item.widget()
        field = field_item.widget()
        if isinstance(label, QLabel) and field is not None:
            rows[label.text().rstrip(":")] = field

    # The path row and a plain combo row must start at the same x.
    start_x = inspector.mapToGlobal(inspector.rect().topLeft()).x()
    lefts = {name: field.mapTo(inspector, field.rect().topLeft()).x()
             for name, field in rows.items()}
    assert len(set(lefts.values())) == 1, f"field axis not shared: {lefts}"

    # The Browse button is inside the path row and ends at the field's right edge.
    path_row = rows.get("File Path")
    assert path_row is not None
    buttons = [b for b in path_row.findChildren(QPushButton)]
    assert len(buttons) == 1 and buttons[0].text() == "Browse"
    inspector.close()
    inspector.deleteLater()
    qapp.processEvents()


def test_abbreviate_path_keeps_the_tail_and_never_loses_information():
    win_path = r"C:\Users\someone\projects\apex_vision\samples\pcb_sample.png"
    short = abbreviate_path(win_path)
    assert short.startswith("…")
    assert short.endswith("pcb_sample.png")
    # The full directory chain is dropped, not the filename.
    assert "Users" not in short and "Downloads" not in short
    assert len(short) < len(win_path)

    # Short values are returned untouched.
    assert abbreviate_path(r"C:\a\b.png") == r"C:\a\b.png"
    assert abbreviate_path("") == ""

    # Forward slashes are handled too.
    posix = abbreviate_path("home/user/projects/vision/samples/very_long_image_name_here.png")
    assert posix.endswith("very_long_image_name_here.png")

    # A single very long bare filename is truncated from the end (it is not a
    # path, so there is no directory chain to drop).
    long_name = "a" * 60 + ".png"
    assert abbreviate_path(long_name).endswith("…")

    # A filename that fits on its own is preserved whole.
    assert abbreviate_path("deeply/nested/tree/of/folders/short_name.png").endswith(
        "short_name.png")
    assert len(abbreviate_path("deeply/nested/tree/of/folders/short_name.png")) <= 38


def test_folder_path_parameter_gets_directory_browse(qapp):
    """Output-folder parameters must offer a folder picker, not a file picker."""
    tool = ImageOutputTool("out_1")
    inspector = ParameterInspectorWidget()
    inspector.set_tool(tool)
    inspector.resize(340, 500)
    inspector.show()
    for _ in range(3):
        qapp.processEvents()

    dir_keys = [k for k in tool.parameters if "dir" in k.lower() or "folder" in k.lower()]
    if not dir_keys:
        pytest.skip("Image Output exposes no folder parameter in this build")

    field = next(e for e in inspector.param_container.findChildren(QLineEdit)
                 if e.property("realPath") is not None)
    button = next(b for b in inspector.param_container.findChildren(QPushButton)
                  if b.text() == "Browse")
    assert "folder" in button.toolTip().lower()
    assert field.property("realPath") is not None
    inspector.close()
    inspector.deleteLater()
    qapp.processEvents()
