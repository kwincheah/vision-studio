"""Capture the live (on-screen) application window to prove real rendering.

Unlike the offscreen `capture_vm_snapshots.py` pass, this grabs the actual
top-level window from the running application, which verifies fonts, DPI
scaling and the real window manager geometry.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "docs", "screenshots", "live_window.png")
TARGET_TITLE = "Apex Industrial Vision Studio"
WAIT_MS = 9000


def main() -> int:
    import time

    app = QApplication.instance() or QApplication(sys.argv)

    found = None
    waited = 0
    while waited < WAIT_MS and found is None:
        app.processEvents()
        for widget in app.topLevelWidgets():
            if widget.isVisible() and TARGET_TITLE in widget.windowTitle():
                found = widget
                break
        if found is None:
            time.sleep(0.25)
            waited += 250

    if found is None:
        print("target window not found")
        return 1

    pix = found.grab()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pix.save(OUT)
    print(f"saved {OUT} ({pix.width()}x{pix.height()}) from '{found.windowTitle()}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
