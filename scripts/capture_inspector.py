"""Capture parameter-inspector close-ups with different module categories.

Produces the evidence for the inspector alignment / path-display work so the
label column, field axis and abbreviated path fields can be inspected directly.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "docs", "screenshots", "audit")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from vm_clone.ui.styles import initialize_app_fonts
    initialize_app_fonts(app)
    from vm_clone.ui.main_window import VisionMasterMainWindow

    os.makedirs(OUT, exist_ok=True)
    win = VisionMasterMainWindow()
    win.resize(1600, 950)
    win.show()
    for _ in range(8):
        app.processEvents()

    def shot(name, widget=None):
        app.processEvents()
        (widget or win).grab().save(os.path.join(OUT, name))
        print(f"saved {name}")

    shot("15_inspector_image_source.png", win.inspector)
    shot("16_image_result_column.png", win.property_dock.widget())

    # A tool with a long list parameter + ROI draw action.
    target = next((nid for nid in win.pipeline.nodes
                   if win.pipeline.nodes[nid].parameters.get("roi")), None)
    if target:
        win.on_node_selected(target)
        app.processEvents()
        shot("17_inspector_roi_module.png", win.inspector)

    # Image Output: folder-style parameter if present.
    from vm_clone.core.registry import create_tool_instance
    out_tool = create_tool_instance("Image Output", "out_demo", "09_ImageOutput")
    win.inspector.set_tool(out_tool)
    app.processEvents()
    shot("18_inspector_image_output.png", win.inspector)

    # Narrow dock to prove the path field stays aligned and readable.
    from PyQt6.QtCore import Qt
    win.resizeDocks([win.property_dock], [300], Qt.Orientation.Horizontal)
    for _ in range(4):
        app.processEvents()
    win.on_node_selected(next(iter(win.pipeline.execution_order)))
    app.processEvents()
    shot("19_inspector_narrow_dock.png", win.property_dock.widget())

    win.close()
    print("inspector capture complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
