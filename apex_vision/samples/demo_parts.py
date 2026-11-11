"""Synthetic metal-surface parts for trying the deep-learning modules (and for training the bundled demo models).

``make_part(i)`` is deterministic: an even ``i`` is a good part, an odd one carries a scratch or a blotch at a position that depends on
``i``. The Image Source pattern "Metal Surface (demo)" walks through them, so a Run loop alternates PASS and FAIL.
"""
from typing import Optional, Tuple

import cv2
import numpy as np

SIZE = 256
DEFECT_COLOUR_SCRATCH = (25, 25, 25)
DEFECT_COLOUR_BLOTCH = (20, 30, 230)


def surface(rng: np.random.Generator, size: int = SIZE) -> np.ndarray:
    """A smooth, slightly noisy brushed-metal surface (BGR)."""
    base = rng.uniform(90, 150)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / size
    img = base + 25 * np.sin(2 * np.pi * (xx * rng.uniform(0.5, 1.5) + rng.uniform(0, 1))) + 15 * yy
    img = img + rng.normal(0, 2.0, (size, size))
    img = cv2.GaussianBlur(img.astype(np.float32), (0, 0), size / 64.0)
    return np.clip(cv2.merge([img * 0.95, img, img * 1.05]), 0, 255).astype(np.uint8)


def add_scratch(img: np.ndarray, rng: np.random.Generator, mask: Optional[np.ndarray] = None) -> np.ndarray:
    out = img.copy()
    s = img.shape[0]
    p1 = (int(rng.integers(s // 12, s // 3)), int(rng.integers(s // 12, s - s // 12)))
    p2 = (int(rng.integers(2 * s // 3, s - s // 12)), int(rng.integers(s // 12, s - s // 12)))
    width = max(2, s // 32)
    cv2.line(out, p1, p2, DEFECT_COLOUR_SCRATCH, width)
    if mask is not None:
        cv2.line(mask, p1, p2, 1, width)
    return out


def add_blotch(img: np.ndarray, rng: np.random.Generator, mask: Optional[np.ndarray] = None) -> np.ndarray:
    out = img.copy()
    s = img.shape[0]
    c = (int(rng.integers(s // 5, 4 * s // 5)), int(rng.integers(s // 5, 4 * s // 5)))
    ax = (int(rng.integers(s // 14, s // 7)), int(rng.integers(s // 14, s // 7)))
    angle = int(rng.integers(0, 180))
    cv2.ellipse(out, c, ax, angle, 0, 360, DEFECT_COLOUR_BLOTCH, -1)
    if mask is not None:
        cv2.ellipse(mask, c, ax, angle, 0, 360, 1, -1)
    return out


def make_part(index: int, size: int = SIZE) -> Tuple[np.ndarray, str]:
    """(image, kind) where kind is 'good', 'scratch' or 'blotch'. Deterministic in ``index``."""
    rng = np.random.default_rng(1000 + int(index))
    img = surface(rng, size)
    if index % 2 == 0:
        return img, "good"
    if (index // 2) % 2 == 0:
        return add_scratch(img, rng), "scratch"
    return add_blotch(img, rng), "blotch"
