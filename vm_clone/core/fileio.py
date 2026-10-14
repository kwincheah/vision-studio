"""Safe file-writing helpers."""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any


def atomic_write_text(filepath: str, content: str, encoding: str = "utf-8") -> None:
    """Write ``content`` so that ``filepath`` is either fully replaced or untouched.

    The data is written to a temporary file in the same directory, flushed to
    disk, and then moved over the target with ``os.replace``.
    """
    directory = os.path.dirname(os.path.abspath(filepath))
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".part", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(filepath: str, data: Any, indent: int = 2) -> None:
    """Serialize ``data`` first (so errors cannot truncate the target), then write atomically."""
    atomic_write_text(filepath, json.dumps(data, indent=indent))
