"""Regression tests for the persistence, output and styling defects found by audit.

Pins the defects that were reproduced by `scripts/audit_persistence.py` and
`scripts/audit_qt_warnings.py`:

  * `Image Output` reported "Saved image to: ..." even when `cv2.imwrite` had failed
    (it returns False rather than raising), and its `save_mode` and `Trigger` port
    were inert.
  * `safe_fromstring` surfaced the parser's bare "no element found" for an empty or
    non-XML file instead of naming the problem.
  * `camera_dialog` embedded `THEME['vm_viewport']` as *literal text* in an f-string,
    so Qt discarded the whole inline stylesheet and the preview rendered unstyled;
    once repaired, the label's ink measured 1.8:1 on the dark preview surface.
"""
import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vm_clone.core.base_tool import ToolStatus  # noqa: E402
from vm_clone.core.registry import create_tool_instance  # noqa: E402
from vm_clone.core.xml_safe import safe_fromstring, DefusedXMLError  # noqa: E402
import vm_clone.tools  # noqa: E402,F401


@pytest.fixture(scope="module")
def qapp():
    """A single QApplication for the widget-level tests in this module."""
    from PyQt6.QtWidgets import QApplication

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    yield app


# ---------------------------------------------------------------------------
# Image Output
# ---------------------------------------------------------------------------
@pytest.fixture()
def output_tool(tmp_path):
    tool = create_tool_instance("Image Output", "out_test")
    tool.set_param("save_directory", str(tmp_path))
    return tool


def _files(directory) -> int:
    return len([f for f in os.listdir(directory) if f.lower().endswith((".png", ".jpg",
                                                                        ".jpeg", ".bmp"))])


def test_image_output_writes_a_file(output_tool, tmp_path):
    result = output_tool.execute({"Image": np.full((32, 40, 3), 128, dtype=np.uint8)})
    assert result.status == ToolStatus.OK, result.message
    assert _files(tmp_path) == 1
    assert os.path.exists(result.outputs["File_Path"])
    assert result.outputs["File_Size"] > 0


def test_image_output_reports_an_unwritable_directory(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    tool = create_tool_instance("Image Output", "out_bad")
    tool.set_param("save_directory", str(blocker / "sub"))
    result = tool.execute({"Image": np.full((32, 40, 3), 128, dtype=np.uint8)})
    assert result.status == ToolStatus.ERROR
    assert not (blocker / "sub").exists()


def test_image_output_reports_an_unsupported_format(output_tool):
    output_tool.set_param("file_format", "xyz")
    result = output_tool.execute({"Image": np.full((32, 40, 3), 128, dtype=np.uint8)})
    assert result.status == ToolStatus.ERROR


def test_image_output_reports_a_missing_image(output_tool):
    result = output_tool.execute({})
    assert result.status != ToolStatus.OK


def test_image_output_inactive_trigger_does_not_save(output_tool, tmp_path):
    """The `Trigger` port must actually gate the write."""
    result = output_tool.execute({"Image": np.full((32, 40, 3), 128, dtype=np.uint8),
                                  "Trigger": False})
    assert result.status == ToolStatus.OK
    assert _files(tmp_path) == 0
    assert "trigger" in result.message.lower()


def test_image_output_active_trigger_saves(output_tool, tmp_path):
    result = output_tool.execute({"Image": np.full((32, 40, 3), 128, dtype=np.uint8),
                                  "Trigger": True})
    assert result.status == ToolStatus.OK
    assert _files(tmp_path) == 1


def test_image_output_save_mode_only_on_ng(tmp_path):
    """`save_mode` must filter by the upstream verdict, not act as Always Save."""
    for i, (verdict, expect_save) in enumerate(((True, False), (False, True))):
        d = tmp_path / f"mode{i}"
        d.mkdir()
        tool = create_tool_instance("Image Output", f"out_mode{i}")
        tool.set_param("save_directory", str(d))
        tool.set_param("save_mode", "Only on NG")
        result = tool.execute({"Image": np.full((32, 40, 3), 128, dtype=np.uint8),
                               "Result": verdict})
        assert result.status == ToolStatus.OK
        assert bool(_files(d)) == expect_save, (
            f"verdict={verdict} expected save={expect_save}: {result.message}")


def test_image_output_save_mode_only_on_ok(tmp_path):
    for i, (verdict, expect_save) in enumerate(((True, True), (False, False))):
        d = tmp_path / f"ok{i}"
        d.mkdir()
        tool = create_tool_instance("Image Output", f"out_ok{i}")
        tool.set_param("save_directory", str(d))
        tool.set_param("save_mode", "Only on OK")
        result = tool.execute({"Image": np.full((32, 40, 3), 128, dtype=np.uint8),
                               "Result": verdict})
        assert result.status == ToolStatus.OK
        assert bool(_files(d)) == expect_save


@pytest.mark.parametrize("verdict,expect_save", [
    ("OK", False), ("NG", True), ("PASS", False), ("FAIL", True),
    (1, False), (0, True),
])
def test_image_output_save_mode_reads_the_verdict_forms(tmp_path, verdict, expect_save):
    """The verdict arrives as either a bool or the "OK"/"NG" status string."""
    d = tmp_path / "verdict"
    d.mkdir()
    tool = create_tool_instance("Image Output", "out_verdict")
    tool.set_param("save_directory", str(d))
    tool.set_param("save_mode", "Only on NG")
    tool.execute({"Image": np.full((32, 40, 3), 128, dtype=np.uint8), "Result": verdict})
    assert bool(_files(d)) == expect_save


# ---------------------------------------------------------------------------
# XML entry point
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("junk", ["", "   ", "\n\t ", None])
def test_empty_xml_is_named_not_a_parser_error(junk):
    with pytest.raises(ValueError) as exc:
        safe_fromstring(junk)
    assert "empty" in str(exc.value).lower()


@pytest.mark.parametrize("junk", ["not xml", '{"json": 1}', "\x00\x01binary"])
def test_non_xml_content_is_diagnosed(junk):
    with pytest.raises(ValueError) as exc:
        safe_fromstring(junk)
    message = str(exc.value).lower()
    assert "not xml" in message or "xml" in message


@pytest.mark.parametrize("bad", [123, [], {}, object()])
def test_non_text_input_is_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        safe_fromstring(bad)


def test_valid_xml_still_parses():
    element = safe_fromstring("<root name='x'><child/></root>")
    assert element.tag == "root"
    assert element.attrib["name"] == "x"


def test_bytes_xml_still_parses():
    element = safe_fromstring(b"<root><child/></root>")
    assert element.tag == "root"


def test_doctype_is_still_rejected():
    """The security guard must survive the added validation."""
    with pytest.raises(DefusedXMLError):
        safe_fromstring('<!DOCTYPE foo [<!ENTITY x "y">]><root/>')


def test_truncated_xml_still_raises_a_parse_error():
    """Damaged but non-empty XML keeps the parser's own error for the caller."""
    import xml.etree.ElementTree as ET
    with pytest.raises(ET.ParseError):
        safe_fromstring("<root><child></root>")


# ---------------------------------------------------------------------------
# The camera dialog's inline stylesheet must reach Qt intact
# ---------------------------------------------------------------------------
def test_camera_dialog_preview_stylesheet_is_valid(qapp):
    """The preview's inline stylesheet must contain no literal token text.

    A bare `THEME['vm_viewport']` inside the f-string made Qt reject the whole
    stylesheet, so the preview rendered unthemed.
    """
    from vm_clone.ui.camera_dialog import CameraManagementDialog

    dialog = CameraManagementDialog()
    try:
        css = dialog.lbl_preview.styleSheet()
        assert css.strip(), "the preview label has no stylesheet"
        assert "THEME[" not in css, f"literal token leaked into the CSS: {css!r}"
        assert "#201c20" in css.lower(), f"viewport colour missing: {css!r}"
    finally:
        dialog.deleteLater()


def test_camera_dialog_preview_ink_meets_contrast(qapp):
    """The preview label's ink must be readable on the dark viewport surface."""
    from vm_clone.ui.camera_dialog import CameraManagementDialog
    from vm_clone.ui.styles import THEME

    def srgb(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(hexcol):
        r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b)

    dialog = CameraManagementDialog()
    try:
        css = dialog.lbl_preview.styleSheet()
        colour = None
        for part in css.split(";"):
            if part.strip().startswith("color:"):
                colour = part.split(":")[1].strip()
        assert colour, f"no colour in the preview stylesheet: {css!r}"
        a, b = lum(colour), lum(THEME["vm_viewport"])
        ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
        assert ratio >= 4.5, f"preview ink {colour} on {THEME['vm_viewport']} = {ratio:.2f}:1"
    finally:
        dialog.deleteLater()


def test_camera_dialog_table_columns_fit_the_viewport(qapp):
    """No column may be clipped behind a horizontal scrollbar at the default size."""
    from vm_clone.ui.camera_dialog import CameraManagementDialog

    dialog = CameraManagementDialog()
    try:
        dialog.resize(880, 580)
        dialog.show()
        for _ in range(20):
            qapp.processEvents()
        table = dialog.table_devices
        header = table.horizontalHeader()
        for col in range(table.columnCount()):
            label = table.horizontalHeaderItem(col).text()
            needed = table.fontMetrics().horizontalAdvance(label) + 12
            assert header.sectionSize(col) >= min(needed, 64), (
                f"column {col} ({label!r}) is {header.sectionSize(col)}px, "
                f"needs about {needed}px")
        assert not table.horizontalScrollBar().isVisible(), (
            "the device table overflows horizontally at its default size")
    finally:
        dialog.close()
        dialog.deleteLater()


# ---------------------------------------------------------------------------
# The sample solution's verdict
# ---------------------------------------------------------------------------
def test_sample_flow_reports_a_defective_board_as_ng():
    """A board whose defect count exceeds the tolerance must not pass."""
    from vm_clone.samples.pcb_solution import create_pcb_inspection_solution

    pipeline = create_pcb_inspection_solution()
    results = pipeline.execute_flow()
    defects = results["node_defect"].outputs.get("Defect_Count")
    verdict = results["node_branch"]
    assert defects is not None
    if defects > 0:
        assert verdict.status == ToolStatus.NG
        assert "FAIL" in verdict.message
    else:
        assert verdict.status == ToolStatus.OK
