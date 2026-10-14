"""Render a close-up of the flow tab bar and the tool flyout for visual inspection.

Measurement alone has been ambiguous here: Qt's reported `tabRect` does not tell us
whether the label is elided.  This crops the actual pixels.

Run:  python scripts/capture_alignment_crops.py
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "screenshots", "alignment")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    from PyQt6.QtWidgets import QApplication

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication([])
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(30):
        app.processEvents()

    # use the real solution's flow name, which is what exposed the elision
    win.solution.flows["PCB_AOI_Solution"] = win.solution.flows.pop("Flow1")
    win.solution.active_flow_name = "PCB_AOI_Solution"
    win._refresh_flow_tabs()
    win.run_pipeline_step()
    for _ in range(20):
        app.processEvents()

    bar = win.flow_tab_bar
    pix = bar.grab()
    pix.save(os.path.join(OUT, "flow_tab.png"))
    print(f"flow tab crop: {pix.width()}x{pix.height()}  "
          f"text={bar.tabText(0)!r}")

    # the tool flyout, with the category that has the longest label
    win.toolbox.set_flyout_visible(True)
    win.toolbox._on_category("Defect Detection")
    for _ in range(16):
        app.processEvents()
    flyout = win.toolbox.flyout
    fpix = flyout.grab()
    fpix.save(os.path.join(OUT, "tool_flyout.png"))
    print(f"tool flyout crop: {fpix.width()}x{fpix.height()}")

    win.close()
    print(f"saved to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
