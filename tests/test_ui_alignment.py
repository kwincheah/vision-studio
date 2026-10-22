"""Regression tests for the flow-tab and tool-cell alignment fixes.

Both defects were cramped text: the flow tab elided its cycle time ("PCB_AOI_Solution
PASS …") and a long tool name wrapped onto a third line that ran past the bottom of its
cell ("Linear Edge Defect").  Each is asserted by *measurement*, because in both cases the
code looked correct and only the rendered geometry showed the problem.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    from apex_vision.ui.styles import initialize_app_fonts

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)
    yield app


@pytest.fixture()
def win(qapp):
    from apex_vision.ui.main_window import ApexMainWindow

    window = ApexMainWindow()
    window.resize(1400, 760)
    window.show()
    for _ in range(24):
        qapp.processEvents()
    yield window
    window.close()
    window.deleteLater()
    qapp.processEvents()


# ---------------------------------------------------------------------------
# Flow tab
# ---------------------------------------------------------------------------
def test_flow_tab_is_expanding(qapp):
    """The tab must fill the bar, not be sized from Qt's pre-stylesheet hint.

    Qt computes `tabSizeHint` before the stylesheet applies the font, so it asked for
    203 px for content needing 222 px - which elided the cycle time.  With an expanding
    bar the tab takes the width the bar has instead.
    """
    from apex_vision.ui.main_window import ApexMainWindow

    window = ApexMainWindow()
    assert window.flow_tab_bar.expanding() is True
    window.close()
    window.deleteLater()


def test_flow_tab_shows_name_verdict_and_time(win, qapp):
    from PyQt6.QtGui import QFontMetrics

    win.solution.flows["PCB_AOI_Solution"] = win.solution.flows.pop("Flow1")
    win.solution.active_flow_name = "PCB_AOI_Solution"
    win._refresh_flow_tabs()
    win.run_pipeline_step()
    for _ in range(12):
        qapp.processEvents()

    bar = win.flow_tab_bar
    label = bar.tabText(0)
    assert "PCB_AOI_Solution" in label, f"name lost: {label!r}"
    assert "PASS" in label or "FAIL" in label, f"verdict lost: {label!r}"
    assert "ms" in label, f"cycle time lost: {label!r}"

    # and it must actually fit the tab that will draw it
    metrics = QFontMetrics(bar.font())
    button = bar.tabButton(0, bar.ButtonPosition.RightSide)
    close = button.sizeHint().width() if button is not None else 0
    needed = metrics.horizontalAdvance(label) + 2 * 6 + close + 2 + 2
    assert needed <= bar.tabRect(0).width(), (
        f"tab content needs {needed}px but the tab is {bar.tabRect(0).width()}px")


def test_flow_tab_elides_an_extremely_long_name(win, qapp):
    """Verdict and timing survive even when the name cannot."""
    name = "PCB_AOI_Solution_Line_A_Extended_Revision_2026_" * 2
    win.solution.flows[name] = win.solution.flows.pop("Flow1")
    win.solution.active_flow_name = name
    win._refresh_flow_tabs()
    for _ in range(10):
        qapp.processEvents()

    label = win.flow_tab_bar.tabText(0)
    assert "…" in label, f"an enormous name was not elided: {label!r}"
    assert "ms" in label, f"cycle time lost with a long name: {label!r}"
    assert ("PASS" in label or "FAIL" in label or "NOT RUN" in label)


def test_flow_tab_tooltip_has_the_whole_name(win, qapp):
    """Eliding the tab must not lose the name - the tooltip carries it."""
    name = "PCB_Defect_Flow_Very_Long_Name_Here"
    win.solution.flows[name] = win.solution.flows.pop("Flow1")
    win.solution.active_flow_name = name
    win._refresh_flow_tabs()
    for _ in range(8):
        qapp.processEvents()
    assert name in win.flow_tab_bar.tabToolTip(0)


# ---------------------------------------------------------------------------
# Tool cells
# ---------------------------------------------------------------------------
def test_tool_cell_font_is_explicit(qapp):
    """The cell font must be set, not inherited.

    The cells resolved the 13 px label size from the stylesheet cascade, which made
    'Linear Edge Defect' wrap onto three lines needing 91 px in an 84 px cell.
    """
    from apex_vision.ui.toolbox import ToolGridWidget

    grid = ToolGridWidget()
    assert grid.font().pixelSize() == ToolGridWidget.LABEL_PX
    grid.deleteLater()


@pytest.mark.parametrize("category", ["Recognition", "Defect Detection", "Location",
                                      "Measurement", "Logic Tools", "Acquisition",
                                      "Image Processing", "Calibration",
                                      "Communication", "Color Processing",
                                      "Image Generation"])
def test_every_tool_label_fits_its_cell(win, qapp, category):
    """No tool label may need more height than its cell provides."""
    from PyQt6.QtGui import QFontMetrics

    win.toolbox.set_flyout_visible(True)
    win.toolbox._on_category(category)
    for _ in range(10):
        qapp.processEvents()

    grid = win.toolbox.flyout.grid
    metrics = QFontMetrics(grid.font())
    inner = grid.gridSize().width() - 8
    cell_h = grid.gridSize().height()
    overflowing = []
    for i in range(grid.count()):
        item = grid.item(i)
        text = item.text()
        lines, current = 1, ""
        for word in text.split():
            candidate = (current + " " + word).strip()
            if metrics.horizontalAdvance(candidate) <= inner or not current:
                current = candidate
            else:
                lines += 1
                current = word
        needed = grid.iconSize().height() + 4 + lines * metrics.lineSpacing() + 6
        if needed > cell_h:
            overflowing.append(f"{text!r} needs {needed}px in {cell_h}px ({lines} lines)")
    assert not overflowing, (
        f"{category}: {len(overflowing)} label(s) overrun the cell: {overflowing}")


def test_the_specific_label_from_the_report_fits(win, qapp):
    """'Linear Edge Defect' is the case that was reported as touching the cell edge."""
    from PyQt6.QtGui import QFontMetrics

    win.toolbox.set_flyout_visible(True)
    win.toolbox._on_category("Defect Detection")
    for _ in range(10):
        qapp.processEvents()

    grid = win.toolbox.flyout.grid
    target = next((grid.item(i) for i in range(grid.count())
                   if grid.item(i).text() == "Linear Edge Defect"), None)
    assert target is not None, "the reported tool is missing from its category"

    metrics = QFontMetrics(grid.font())
    inner = grid.gridSize().width() - 8
    lines, current = 1, ""
    for word in target.text().split():
        candidate = (current + " " + word).strip()
        if metrics.horizontalAdvance(candidate) <= inner or not current:
            current = candidate
        else:
            lines += 1
            current = word
    assert lines == 2, f"expected 2 lines, got {lines}"
    needed = grid.iconSize().height() + 4 + lines * metrics.lineSpacing() + 6
    assert needed < grid.gridSize().height(), (
        f"needs {needed}px of an {grid.gridSize().height()}px cell")
