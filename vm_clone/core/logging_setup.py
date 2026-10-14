"""Logging configuration and global exception hook for Apex Industrial Vision Studio."""
from __future__ import annotations

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from typing import Optional


def setup_logging(log_dir: Optional[str] = None) -> None:
    """Configures root logging with both rotating file and stderr handlers."""
    if log_dir is None:
        log_dir = os.path.join(os.path.expanduser("~"), ".apex_vision", "logs")

    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "vision_studio.log")
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] (%(name)s:%(lineno)d) %(message)s"
        )
        file_handler.setFormatter(file_formatter)
    except Exception as e:
        file_handler = None
        sys.stderr.write(f"Warning: Failed to initialize file logger: {e}\n")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.INFO)
    stream_formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    stream_handler.setFormatter(stream_formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Clear existing handlers to prevent duplicate lines
    root.handlers.clear()
    root.addHandler(stream_handler)
    if file_handler:
        root.addHandler(file_handler)


def install_global_excepthook() -> None:
    """Installs sys.excepthook to log uncaught exceptions and alert in GUI."""
    logger = logging.getLogger("vm_clone.crash")

    def _excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        logger.critical(f"Uncaught exception:\n{err_msg}")

        # If QApplication is running, show a crash dialog
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None,
                    "Application Error",
                    f"An unhandled error occurred:\n\n{exc_type.__name__}: {exc_value}\n\nSee application log for full traceback."
                )
        except Exception:
            pass

    sys.excepthook = _excepthook
