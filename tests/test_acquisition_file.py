"""
Unit tests for Image Source tool file path resolution, Windows paths with quotes,
relative paths, and Browse button interaction in ParameterInspectorWidget.
"""
import os
import pytest
import numpy as np
from PyQt6.QtWidgets import QApplication, QPushButton

from vm_clone.tools.acquisition import ImageSourceTool
from vm_clone.core.base_tool import ToolStatus
from vm_clone.ui.inspector import ParameterInspectorWidget
from vm_clone.ui.styles import initialize_app_fonts


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def test_image_source_file_resolution():
    tool = ImageSourceTool("src_test")
    tool.set_param("source_type", "File")

    # 1. Empty path fallback to bundled sample image
    tool.set_param("file_path", "")
    res1 = tool.execute({})
    assert res1.status == ToolStatus.OK
    assert "Image" in res1.outputs

    # 2. Path with surrounding quotes (standard Windows 'Copy as path')
    sample_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "vm_clone", "samples", "pcb_sample.png"))
    quoted = f'"{sample_path}"'
    tool.set_param("file_path", quoted)
    res2 = tool.execute({})
    assert res2.status == ToolStatus.OK

    # 3. Relative path resolution
    tool.set_param("file_path", "vm_clone/samples/pcb_sample.png")
    res3 = tool.execute({})
    assert res3.status == ToolStatus.OK

    # 4. Clear diagnostic message when path does not exist
    tool.set_param("file_path", "C:/invalid_nonexistent_dir/no_image.png")
    res4 = tool.execute({})
    assert res4.status == ToolStatus.NG
    assert "Browse..." in res4.message


def test_inspector_browse_button_generation(qapp):
    inspector = ParameterInspectorWidget()
    tool = ImageSourceTool("src_inspector")
    tool.set_param("source_type", "File")
    inspector.set_tool(tool)

    # The parameter surface is a QFormLayout, so the Browse action lives inside
    # the field widget of the "File Path" row.
    browse_btn_found = False
    for button in inspector.param_container.findChildren(QPushButton):
        if button.text().strip() in ("Browse", "Browse..."):
            browse_btn_found = True
            break

    assert browse_btn_found is True


def test_inspector_path_field_shows_abbreviated_path(qapp):
    """Long paths are abbreviated for display; the real value is preserved."""
    from PyQt6.QtWidgets import QLineEdit
    from vm_clone.ui.inspector import abbreviate_path

    inspector = ParameterInspectorWidget()
    tool = ImageSourceTool("src_path")
    tool.set_param("source_type", "File")
    long_path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "vm_clone", "samples", "pcb_sample.png"))
    tool.set_param("file_path", long_path)
    inspector.set_tool(tool)

    path_edits = [e for e in inspector.param_container.findChildren(QLineEdit)
                  if e.property("realPath")]
    assert path_edits, "no path field was created"
    field = path_edits[0]
    assert field.property("realPath") == long_path
    assert field.text() == abbreviate_path(long_path)
    # The full path stays recoverable even though the display is abbreviated.
    assert long_path in field.toolTip()
    assert "pcb_sample.png" in field.text()


def test_inspector_form_labels_share_one_column(qapp):
    """Every parameter label must sit on the same vertical axis."""
    from PyQt6.QtWidgets import QFormLayout, QLabel

    inspector = ParameterInspectorWidget()
    tool = ImageSourceTool("src_form")
    tool.set_param("source_type", "File")
    inspector.set_tool(tool)
    inspector.resize(330, 600)
    inspector.show()
    qapp.processEvents()
    inspector._align_label_column()
    qapp.processEvents()

    widths = set()
    for row in range(inspector.param_layout.rowCount()):
        item = inspector.param_layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
        if item is not None and isinstance(item.widget(), QLabel):
            widths.add(item.widget().width())
    assert len(widths) == 1, f"label column is not uniform: {widths}"


def test_inspector_path_value_commits_on_edit(qapp):
    """A hand-typed path must reach the tool parameter."""
    from PyQt6.QtWidgets import QLineEdit

    inspector = ParameterInspectorWidget()
    tool = ImageSourceTool("src_edit")
    tool.set_param("source_type", "File")
    tool.set_param("file_path", "old.png")
    inspector.set_tool(tool)

    field = next(e for e in inspector.param_container.findChildren(QLineEdit)
                 if e.property("realPath") is not None)
    assert field.property("realPath") == "old.png"

    sample = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "vm_clone", "samples", "pcb_sample.png"))
    field.setText(sample)
    inspector._on_path_edited("file_path", field)

    assert tool.get_param("file_path") == sample
    assert field.property("realPath") == sample
