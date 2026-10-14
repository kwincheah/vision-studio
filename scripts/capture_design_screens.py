"""Capture the standard design-system screen set.

Renders each primary surface offscreen at a fixed size so the captures are
reproducible and comparable, and so a validation run does not depend on driving the
live window with synthetic mouse events.

Run:  python scripts/capture_design_screens.py
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "screenshots", "design")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    from PyQt6.QtWidgets import QApplication, QDialog

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow
    from vm_clone.ui.start_page import StartPageDialog

    # --- Start Page -------------------------------------------------------
    page = StartPageDialog()
    page.resize(1200, 760)
    page.show()
    for _ in range(24):
        app.processEvents()
    page.grab().save(os.path.join(OUT, "H0_start_page.png"))
    print("saved H0_start_page.png", page.width(), page.height())
    page.close()

    # --- workspace --------------------------------------------------------
    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(28):
        app.processEvents()
    win.grab().save(os.path.join(OUT, "H1_workspace.png"))
    print("saved H1_workspace.png", win.width(), win.height())

    # --- each workspace tab ----------------------------------------------
    for i, label in enumerate(("flow", "operation", "overview")):
        try:
            win._show_workspace_tab(i)
            for _ in range(10):
                app.processEvents()
            win.grab().save(os.path.join(OUT, f"H2_workspace_{label}.png"))
            print(f"saved H2_workspace_{label}.png")
        except Exception as exc:
            print(f"  workspace tab {label}: {type(exc).__name__}: {exc}")

    win._show_workspace_tab(0)
    for _ in range(8):
        app.processEvents()

    # --- the tool flyout, open -------------------------------------------
    try:
        win.toolbox._on_category("Measurement")
        for _ in range(10):
            app.processEvents()
        win.toolbox.grab().save(os.path.join(OUT, "H3_flyout.png"))
        print("saved H3_flyout.png")
    except Exception as exc:
        print(f"  flyout: {type(exc).__name__}: {exc}")

    # --- each result tab --------------------------------------------------
    win.data_tabs.setCurrentIndex(1)
    for _ in range(8):
        app.processEvents()
    win.result_display.grab().save(os.path.join(OUT, "H4_result_panel.png"))
    print("saved H4_result_panel.png")

    # --- the module configuration dialog ---------------------------------
    from vm_clone.ui.module_config import ModuleConfigDialog
    nid = next(iter(win.pipeline.nodes))
    dlg = ModuleConfigDialog(win.pipeline.nodes[nid],
                             win.pipeline.last_results.get(nid), win)
    dlg.resize(720, 560)
    dlg.show()
    for _ in range(16):
        app.processEvents()
    dlg.grab().save(os.path.join(OUT, "H5_module_config.png"))
    print("saved H5_module_config.png", dlg.width(), dlg.height())
    dlg.close()

    # --- the camera management dialog ------------------------------------
    from vm_clone.ui.camera_dialog import CameraManagementDialog
    cam = CameraManagementDialog(win)
    cam.resize(880, 580)
    cam.show()
    for _ in range(18):
        app.processEvents()
    cam.grab().save(os.path.join(OUT, "H6_camera_dialog.png"))
    print("saved H6_camera_dialog.png")
    cam.close()

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
