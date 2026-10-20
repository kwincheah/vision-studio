"""Printable calibration target images (chessboard / circle grids)."""
from typing import Tuple

import cv2
import numpy as np

PATTERNS = ("Chessboard", "Circles Grid", "Asymmetric Circles")


def inner_pattern_size(pattern: str, cols: int, rows: int) -> Tuple[int, int]:
    """Size to pass to OpenCV's detectors: inner corners for a chessboard, else the grid."""
    return (cols - 1, rows - 1) if pattern == "Chessboard" else (cols, rows)


def make_calibration_target(pattern: str = "Chessboard", cols: int = 10, rows: int = 7,
                            cell_px: int = 80, margin_px: int = 80) -> np.ndarray:
    """Render a white-background BGR target.

    ``cols`` x ``rows`` is the number of squares (chessboard) or dots per row/column
    (circle grids). Raises ValueError for unusable dimensions.
    """
    if pattern not in PATTERNS:
        raise ValueError(f"Unknown pattern '{pattern}'")
    if not (3 <= cols <= 40 and 3 <= rows <= 40):
        raise ValueError("Columns and rows must be between 3 and 40")
    if not (10 <= cell_px <= 400):
        raise ValueError("Cell size must be between 10 and 400 px")

    asym = pattern == "Asymmetric Circles"
    width = cols * cell_px + (cell_px // 2 if asym else 0) + 2 * margin_px
    height = ((rows * cell_px) // 2 + cell_px if asym else rows * cell_px) + 2 * margin_px
    img = np.full((height, width, 3), 255, np.uint8)

    if pattern == "Chessboard":
        for r in range(rows):
            for c in range(cols):
                if (r + c) % 2 == 0:
                    x0, y0 = margin_px + c * cell_px, margin_px + r * cell_px
                    cv2.rectangle(img, (x0, y0), (x0 + cell_px - 1, y0 + cell_px - 1), (0, 0, 0), -1)
    else:
        radius = max(3, cell_px // 4)
        for r in range(rows):
            for c in range(cols):
                cx = margin_px + cell_px // 2 + c * cell_px
                cy = margin_px + cell_px // 2 + r * cell_px
                if asym:
                    cx = margin_px + cell_px // 2 + c * cell_px + (cell_px // 2 if r % 2 else 0)
                    cy = margin_px + cell_px // 2 + (r * cell_px) // 2
                cv2.circle(img, (cx, cy), radius, (0, 0, 0), -1, cv2.LINE_AA)
    return img
