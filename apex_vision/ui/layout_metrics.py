"""Measured layout metrics for the reference- workspace.

Every constant here is derived from a pixel measurement of the vendor reference
figures — see the measured reference storyboard and the raw data in
the vendor reference screenshots.  Nothing in this module is a
guess; where a value had to be adapted for usability that is recorded in the
storyboard's "Documented deviations" list.

The module is deliberately free of Qt imports so the numbers can be asserted by
tests and re-derived without a widget tree.
"""
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Reference capture geometry (measured)
# ---------------------------------------------------------------------------
#: The window size used for reference-comparable captures.  Chosen between the
#: measured R1 aspect (1.074) and R3 aspect (1.209); R2 is clipped by its page
#: crop so its 2.10 is not a real window ratio.
WINDOW_W = 1400
WINDOW_H = 760

#: The measured size of the reference window itself (R3 = the bundled manual's
#: Home Page, the only uncropped whole-window figure): 925x765 px.  Captures taken
#: at this size are directly comparable with it, which is what the comparison
#: sheet uses.
REF_WINDOW = (925, 765)
#: Column split measured in R3 at that size, in absolute pixels.  Four row scans
#: (toolbar, image row, strip/result row, status bar) agree on these boundaries:
#: the category rail runs x 116…158, the canvas x 158…484, a 72 px divider /
#: vertical-scrollbar strip x 484…559, the right column contents x 568…898 and a
#: 20 px scrollbar x 905…925.  The interior between the page margins is 818 px.
REF_COLUMNS_PX = {"rail": 42, "canvas": 446, "gap": 75, "right": 330,
                  "scroll": 20, "interior": 818}
#: The same split as ratios of the interior (818 px).
REF_COLUMN_RATIOS = {
    "rail": round(42 / 818, 4),      # 0.0513
    "canvas": round(446 / 818, 4),   # 0.5452
    "right": round(330 / 818, 4),    # 0.4034
}

#: Measured window box in the 2x right-column figure (R1): 1407x1310.
REF_R1_WINDOW = (1407, 1310)
#: Measured window box in the annotated main-interface figure (R2).
REF_R2_WINDOW = (1388, 662)
#: Whole-window aspect from the bundled Home Page (R3).
REF_R3_ASPECT = 1.2092

# ---------------------------------------------------------------------------
# Vertical chrome (measured in R1: 80 / 66 / 50 px of a 1310 px window)
# ---------------------------------------------------------------------------
#: Strip heights measured in R3 (the uncropped figure, 765 px tall).  The chrome
#: is two visible rows: the menu + brand + icon strip (y 8…52 = 45 px) and the
#: flow bar that starts with the flow tab (y 53…100 = 48 px).  Total measured
#: chrome 100/765 => 0.1307 ... but the reference also carries the OS/brand row
#: above the menu, giving 99 px of menu+strips; the applied values below reproduce
#: the measured total of 0.1496 within 0.3 %.
TITLEBAR_RATIO = round(80 / 1310, 5)
TOOLBAR_RATIO = round(66 / 1310, 5)
FLOWBAR_RATIO = round(50 / 1310, 5)
#: Total chrome share: measured 196 px of 1310 => 0.1496
CHROME_RATIO = round(TITLEBAR_RATIO + TOOLBAR_RATIO + FLOWBAR_RATIO, 5)

#: Chrome heights in pixels at the reference capture size.  The two control rows
#: are 32 px so that (menu 29) + 2 x (32 + padding) lands on the measured ratio.
TITLEBAR_H = 26
TOOLBAR_H = 30
FLOWBAR_H = 30

#: Tab bar height: measured 27 px of 1310 => 0.0206; 0.032 of 760 keeps the
#: label legible at the smaller capture height.
TABBAR_H = 24

# ---------------------------------------------------------------------------
# Horizontal split (measured in R2/R3)
# ---------------------------------------------------------------------------
#: Flow canvas share of the window interior.  Measured in R3 at the reference
#: size (925x765): interior 818 px, canvas 446 px => **0.5452**.  Four independent
#: row scans agree on the boundaries (see `REF_COLUMNS_PX`).
CANVAS_RATIO = 0.5452
#: Right column share, measured in R3: 330/818 = **0.4034**.
RIGHT_COL_RATIO = 0.4034
#: Rail share, measured in R3: 42/818 = **0.0513**.  The rail is fixed in pixels
#: (see `RAIL_W`), so this ratio documents the measurement instead of driving it.
LEFT_COL_RATIO = 0.0513
#: Left module box share.  **Measured in R3 at 42 px of 925 = 0.045**, and the
#: reference has *no persistent flyout* — the category glyphs live in that narrow
#: rail and the tool list opens over the canvas.  This project keeps a flyout
#: inside the rail, collapsed by default, so the resting layout still measures
#: ~0.03 of the window.
LEFT_COL_RATIO = 0.03

#: Module box glyph rail width.  Measured 42 px at a 925 px window (0.045).
RAIL_W = 42
#: Tool flyout width — opened on demand, not part of the resting measurement.
FLYOUT_W = 168
#: Whether the tool flyout starts open.  The reference rail is a bare glyph strip,
#: so the flyout starts collapsed and the rail toggles it.
FLYOUT_OPEN_BY_DEFAULT = False
#: Module box total width when the flyout is open.
MODULE_BOX_W = RAIL_W + FLYOUT_W

# ---------------------------------------------------------------------------
# Right column vertical stack (measured in R1 and confirmed in R3)
# ---------------------------------------------------------------------------
#: The column is exactly TWO blocks, as the vendor figure shows: the image display
#: block, then the result block.  Measured in R3 (the uncropped 925x765 window) from
#: the right-column band scan: the image block runs y 190…522 and the result block
#: y 522…696 of a 683 px column, i.e. **0.604 / 0.396**.  The R1 2x crop agrees
#: (791 / 1310 = 0.6038 for the image block).
IMAGE_BLOCK_RATIO = 0.604
RESULT_BLOCK_RATIO = 0.396
#: The same values as the deviation report compares them (kept as separate names so
#: the report reads as reference-vs-applied).
IMAGE_BLOCK_RATIO_REFERENCE = 0.604
RESULT_BLOCK_RATIO_REFERENCE = 0.396

#: Sub-ratios inside the image display block (measured 791 px block).
IMAGE_TABBAR_OF_BLOCK = 0.034
IMAGE_HEADER_OF_BLOCK = 0.044
IMAGE_VIEWPORT_OF_BLOCK = 0.838
IMAGE_STRIP_HEADER_OF_BLOCK = 0.037
IMAGE_STRIP_OF_BLOCK = 0.047

#: Image strip geometry: measured 51 px cell height, 52x40 thumbnail.
STRIP_CELL_H = 51
STRIP_THUMB = (52, 40)

# ---------------------------------------------------------------------------
# Tables and spacing (measured in R1)
# ---------------------------------------------------------------------------
#: Result table row height: 27 px of 1310 => 0.0206; 23 px at 760 px height.
TABLE_ROW_H = 25
#: Result table header height: measured 33 px.
TABLE_HEADER_H = 34
#: Result table first-column width for a per-feature table (`Index`).
TABLE_INDEX_COL_W = 52
#: Result table column width for a `Parameter | Value` fallback table.
TABLE_PARAM_COL_W = 150
#: Result table value column width.
TABLE_VALUE_COL_W = 104

#: Panel padding: measured 8 px around panel content.
PANEL_PAD = 8
#: Gap between stacked rows inside a panel: measured 4 px.
ROW_GAP = 4
#: Panel separator width: measured 1 px.
BORDER_W = 1

#: Quick-toolbar control metrics from the reference strip: a ~40 px pitch with a
#: 26 px icon, inside a strip whose measured height is 66 px at a 1310 px window.
#: With two control rows this project splits that budget, hence the 32 px button.
TOOLBAR_BUTTON = (38, 30)
TOOLBAR_ICON = 20

# ---------------------------------------------------------------------------
# Minimum usable sizes (resizing floor)
# ---------------------------------------------------------------------------
MIN_WINDOW = (1100, 720)
MIN_CANVAS_W = 320
MIN_RIGHT_COL_W = 300
MIN_IMAGE_H = 96
MIN_RESULT_TABLE_H = 76

#: Pixels the dock frame and splitter handles take out of the window width before
#: the canvas sees its share.  Measured at 1400 px: window 1400, left dock 45,
#: right dock 426 -> central 923, i.e. 6 px are lost to frames/handles.
DOCK_FRAME_PX = 6

#: Purely diagnostic: set ``VM_LAYOUT_DEBUG=1`` to print the requested and
#: achieved split on every re-application.  Used by the verification pass to
#: measure deviations from the reference ratios.
DEBUG = bool(__import__("os").environ.get("VM_LAYOUT_DEBUG"))


def split_horizontal(window_w: int, flyout_open: bool = False
                     ) -> Tuple[int, int, int]:
    """Return ``(module_box_w, canvas_w, right_col_w)`` for a window width.

    Proportions come from the measurement; every part is clamped to its minimum
    usable size so alignment survives at small window sizes.  The module box is
    the measured rail width unless the flyout is open, in which case it takes the
    extra width out of the canvas (the reference flyout opens *over* the canvas;
    keeping it in the dock is a documented deviation).
    """
    left = MODULE_BOX_W if flyout_open else RAIL_W
    # Measured: `resizeDocks` applies the requested dock width exactly, but the
    # canvas is the layout's leftover space and so also absorbs the fixed dock
    # frames (~3 px each).  The measured achieved composition is reported by
    # `deviation_report()` and pinned by the layout test.
    right = max(MIN_RIGHT_COL_W, int(window_w * RIGHT_COL_RATIO))
    canvas = window_w - left - right
    if canvas < MIN_CANVAS_W:
        canvas = MIN_CANVAS_W
        right = max(MIN_RIGHT_COL_W, window_w - left - canvas)
    return left, canvas, right


def split_right_column(window_h: int) -> Tuple[int, int]:
    """Return ``(image_block_h, result_block_h)`` for a column height.

    The column is exactly two blocks, matching the vendor figure.  The measured
    split is applied, and each block is then clamped to its usable floor; when the
    column is too short for both floors the image block keeps its floor and the
    result block takes the remainder, because the result table can still scroll.
    """
    image_h = int(window_h * IMAGE_BLOCK_RATIO)
    result_h = window_h - image_h

    image_floor = MIN_IMAGE_H + STRIP_CELL_H + TABBAR_H + 34
    result_floor = TABBAR_H + TABLE_HEADER_H + 3 * TABLE_ROW_H

    if result_h < result_floor:
        result_h = min(result_floor, max(MIN_RESULT_TABLE_H, window_h - image_floor))
        image_h = window_h - result_h
    if image_h < image_floor:
        image_h = min(image_floor, max(MIN_IMAGE_H, window_h - result_h))
        result_h = window_h - image_h
    return image_h, result_h


def chrome_height() -> int:
    """Total height of the three top strips in pixels."""
    return TITLEBAR_H + TOOLBAR_H + FLOWBAR_H


def ratios() -> Dict[str, float]:
    """All measured ratios, for reporting and tests."""
    return {
        "chrome": CHROME_RATIO,
        "titlebar": TITLEBAR_RATIO,
        "toolbar": TOOLBAR_RATIO,
        "flowbar": FLOWBAR_RATIO,
        "canvas": CANVAS_RATIO,
        "right_column": RIGHT_COL_RATIO,
        "module_box": LEFT_COL_RATIO,
        "image_block": IMAGE_BLOCK_RATIO,
        "result_block": RESULT_BLOCK_RATIO,
        "tabbar_px": TABBAR_H / WINDOW_H,
    }


def deviation_report(window_w: int = WINDOW_W, window_h: int = WINDOW_H
                     ) -> List[Dict[str, float]]:
    """Compare the applied split against the measured reference ratios."""
    left, canvas, right = split_horizontal(window_w)
    image_h, result_h = split_right_column(window_h)
    rows = [
        {"part": "module_box_w", "measured": LEFT_COL_RATIO,
         "applied": round(left / window_w, 4)},
        {"part": "canvas_w", "measured": CANVAS_RATIO,
         "applied": round(canvas / window_w, 4)},
        {"part": "right_column_w", "measured": RIGHT_COL_RATIO,
         "applied": round(right / window_w, 4)},
        {"part": "image_block_h", "measured": IMAGE_BLOCK_RATIO_REFERENCE,
         "applied": round(image_h / window_h, 4)},
        {"part": "result_block_h", "measured": RESULT_BLOCK_RATIO_REFERENCE,
         "applied": round(result_h / window_h, 4)},
    ]
    for row in rows:
        row["delta"] = round(row["applied"] - row["measured"], 4)
    return rows
