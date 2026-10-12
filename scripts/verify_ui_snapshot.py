"""Offscreen UI verification snapshots for icon navigation and industrial palette.

Retained as the project's historical verification entry point; the
VisionMaster-alignment capture pass lives in ``capture_vm_snapshots.py``.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication
from vm_clone.ui.main_window import VisionMasterMainWindow


def capture_snapshots():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    win = VisionMasterMainWindow()
    win.resize(1500, 920)
    win.show()
    app.processEvents()

    os.makedirs("docs/screenshots", exist_ok=True)

    # 1. Full Main Window Snapshot (Flow Diagram active)
    pix_main = win.grab()
    pix_main.save("docs/screenshots/workspace_flow_polished.png")
    print("Saved docs/screenshots/workspace_flow_polished.png")

    # 2. Tool Box close-up (select a category that exercises the flyout grid)
    win.tool_rail._on_category_clicked("Measurement")
    app.processEvents()
    win.tool_dock.widget().grab().save("docs/screenshots/tool_library_tree.png")
    print("Saved docs/screenshots/tool_library_tree.png")

    # 3. Multi-Flow overview (was the Vision Canvas tab before the redesign)
    win.tab_workspace.setCurrentIndex(2)
    app.processEvents()
    win.grab().save("docs/screenshots/workspace_canvas_polished.png")
    print("Saved docs/screenshots/workspace_canvas_polished.png")

    win.close()
    print("UI snapshots completed successfully.")


if __name__ == "__main__":
    capture_snapshots()
