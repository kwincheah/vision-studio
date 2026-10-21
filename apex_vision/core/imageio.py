"""Unicode-safe image file I/O.

``cv2.imread`` / ``cv2.imwrite`` go through the ANSI file API on Windows and silently
fail (``None`` / ``False``) for any path containing non-ASCII characters, such as a
user profile or project folder named in another language.  Reading and writing the raw
bytes ourselves works for every path.
"""
import os
from typing import Optional, Sequence

import cv2
import numpy as np


def imread(path: str, flags: int = cv2.IMREAD_COLOR) -> Optional[np.ndarray]:
    """Like ``cv2.imread`` but safe for any path; returns None when unreadable."""
    try:
        data = np.fromfile(os.fspath(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, flags)
    except (OSError, ValueError, TypeError, cv2.error):
        return None


def imwrite(path: str, image: np.ndarray, params: Optional[Sequence[int]] = None) -> bool:
    """Like ``cv2.imwrite`` but safe for any path; returns False on failure."""
    try:
        path = os.fspath(path)
        ext = os.path.splitext(path)[1] or ".png"
        ok, buf = cv2.imencode(ext, image, list(params) if params else [])
        if not ok:
            return False
        buf.tofile(path)
        return True
    except (OSError, ValueError, TypeError, cv2.error):
        return False
