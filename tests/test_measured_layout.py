"""Pin the measured VisionMaster layout geometry.

Every expected value here comes from a pixel measurement of the vendor figures,
recorded in `docs/VISIONMASTER_STORYBOARD.md` §2 with the raw data in
`docs/references/external/storyboard_geometry.json`.  The tests serve two
purposes: they keep the constants honest, and they assert that the *applied*
layout actually lands on the measured ratios rather than on a guess.
"""
import pytest

from PyQt6.QtWidgets import QApplication

from vm_clone.ui.styles import initialize_app_fonts
from vm_clone.ui.main_window import VisionMasterMainWindow
from vm_clone.ui import layout_metrics as LM


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def _win(qapp, size):
    win = VisionMasterMainWindow()
    win.resize(*size)
    win.show()
    # The measured split is applied in two passes (the first before Qt finalises
    # the dock frames, the second from the settled geometry).
    for _ in range(26):
        qapp.processEvents()
    return win


# =========================================================================
# The constants must equal the measured reference values
# =========================================================================
def test_reference_measurements_are_recorded():
    """The measured reference split, in pixels and ratios."""
    assert LM.REF_WINDOW == (925, 765)
    px = LM.REF_COLUMNS_PX
    assert px["rail"] == 42
    assert px["canvas"] == 446
    assert px["right"] == 330
    assert px["interior"] == 818

    # The ratios are derived from those pixel measurements, not chosen.
    assert LM.REF_COLUMN_RATIOS["rail"] == round(42 / 818, 4)
    assert LM.REF_COLUMN_RATIOS["canvas"] == round(446 / 818, 4)
    assert LM.REF_COLUMN_RATIOS["right"] == round(330 / 818, 4)
    assert LM.CANVAS_RATIO == LM.REF_COLUMN_RATIOS["canvas"]
    assert LM.RIGHT_COL_RATIO == LM.REF_COLUMN_RATIOS["right"]


def test_vertical_ratios_match_the_reference_bands():
    """Chrome and block heights measured in R1 (a 1310 px window)."""
    assert LM.TITLEBAR_RATIO == pytest.approx(80 / 1310, abs=1e-4)
    assert LM.TOOLBAR_RATIO == pytest.approx(66 / 1310, abs=1e-4)
    assert LM.CHROME_RATIO == pytest.approx(196 / 1310, abs=1e-3)
    # The image display block measured 791 px of 1310.
    assert LM.IMAGE_BLOCK_RATIO_REFERENCE == pytest.approx(791 / 1310, abs=1e-3)


def test_split_helpers_respect_the_minimums():
    """No part may fall below its usable minimum at the smallest window."""
    left, canvas, right = LM.split_horizontal(LM.MIN_WINDOW[0])
    assert left >= LM.RAIL_W
    assert canvas >= LM.MIN_CANVAS_W
    assert right >= LM.MIN_RIGHT_COL_W

    image_h, result_h = LM.split_right_column(LM.MIN_WINDOW[1])
    assert image_h >= LM.MIN_IMAGE_H
    assert result_h >= LM.MIN_RESULT_TABLE_H
    assert image_h + result_h <= LM.MIN_WINDOW[1]


def test_split_is_proportional_at_the_reference_size():
    """At the reference size the solver returns the measured pixel split."""
    interior = LM.REF_COLUMNS_PX["interior"]
    left, canvas, right = LM.split_horizontal(interior)
    # The rail is the measured fixed strip; canvas and right column are the
    # measured ratios of the interior.
    assert left == LM.RAIL_W
    assert right == pytest.approx(interior * LM.RIGHT_COL_RATIO, abs=2)
    assert canvas == pytest.approx(interior * LM.CANVAS_RATIO, abs=3)


# =========================================================================
# The applied layout must land on the measured ratios
# =========================================================================
@pytest.mark.parametrize("size", [(925, 765), (1400, 760), (1600, 950),
                                  (1100, 720), (1920, 1080)])
def test_applied_split_matches_the_measured_ratios(qapp, size):
    win = _win(qapp, size)
    total = (win.tool_dock.width() + win.centralWidget().width()
             + win.property_dock.width())
    assert total > 400

    canvas_share = win.centralWidget().width() / total
    right_share = win.property_dock.width() / total

    # The canvas is Qt's leftover space, so at narrow widths the dock minimums
    # take a little of it; 3.5 % covers that and nothing more.
    assert abs(canvas_share - LM.CANVAS_RATIO) <= 0.035, (
        f"canvas {canvas_share:.4f} vs measured {LM.CANVAS_RATIO} at {size}")
    assert abs(right_share - LM.RIGHT_COL_RATIO) <= 0.005, (
        f"right column {right_share:.4f} vs measured {LM.RIGHT_COL_RATIO} at {size}")
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_applied_chrome_matches_the_measured_ratio(qapp):
    """Chrome (menu + two control rows) measured 196/1310 = 0.1496.

    The ratio is measured against the *content* height: the window's minimum
    height is set by the tallest tab page, so `win.height()` can exceed the
    requested size and would otherwise dilute the ratio.
    """
    win = _win(qapp, (1400, 760))
    chrome = (win.menuBar().height() + win.toolbar_resources.height()
              + win.toolbar_flows.height())
    content_h = chrome + win.centralWidget().height()
    ratio = chrome / content_h
    assert abs(ratio - LM.CHROME_RATIO) <= 0.015, (
        f"chrome ratio {ratio:.4f} vs measured {LM.CHROME_RATIO:.4f}")
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_right_column_bands_are_applied_in_order(qapp):
    """Exactly two blocks, as in the vendor figure: image over result."""
    win = _win(qapp, (1400, 760))
    sizes = win.split_right.sizes()
    assert len(sizes) == 2, "the vendor right column is a two-block stack"
    assert sizes[0] > sizes[1], "the image block must be the taller band"
    assert sizes[0] >= LM.MIN_IMAGE_H
    assert sizes[1] >= LM.MIN_RESULT_TABLE_H
    assert win.split_right.indexOf(win.data_tabs) == 0
    assert win.split_right.indexOf(win.result_display) == 1
    # No parameter pane on the canvas: the reference keeps parameters in the
    # per-module configuration window.
    assert not hasattr(win, "inspector")
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_module_box_is_the_measured_rail_at_rest(qapp):
    """The reference rail is a bare glyph strip; the flyout opens on demand."""
    win = _win(qapp, (1400, 760))
    assert win.toolbox.is_collapsed
    assert win.tool_dock.width() <= LM.RAIL_W + 12
    assert win.tool_dock.width() >= LM.RAIL_W

    # Opening the flyout widens the dock and the canvas gives up the width.
    before_canvas = win.centralWidget().width()
    win.toolbox._on_category("Acquisition")
    for _ in range(10):
        qapp.processEvents()
    assert not win.toolbox.is_collapsed
    assert win.tool_dock.width() > LM.RAIL_W
    assert win.centralWidget().width() < before_canvas

    # Clicking the active glyph collapses it again and the canvas gets it back.
    win.toolbox._on_category("Acquisition")
    for _ in range(10):
        qapp.processEvents()
    assert win.toolbox.is_collapsed
    assert win.tool_dock.width() <= LM.RAIL_W + 12
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_deviation_report_is_complete():
    """The report the comparison pass uses must cover every measured ratio."""
    rows = LM.deviation_report()
    parts = {row["part"] for row in rows}
    assert parts == {"module_box_w", "canvas_w", "right_column_w",
                     "image_block_h", "result_block_h"}
    for row in rows:
        assert set(row) == {"part", "measured", "applied", "delta"}
        assert abs(row["delta"]) < 0.2
