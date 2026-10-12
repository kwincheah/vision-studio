"""Capture VisionMaster-alignment verification snapshots offscreen.

Renders the real main window (no mocks) at a fixed 1600x950 size and saves one
PNG per workspace screen so the result can be compared against the reference
figures extracted from the official Vision Master manual.
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "screenshots")
W, H = 1600, 950


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from vm_clone.ui.styles import initialize_app_fonts
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow
    win = VisionMasterMainWindow()
    win.resize(W, H)
    win.show()
    for _ in range(6):
        app.processEvents()
    time.sleep(0.15)
    app.processEvents()

    os.makedirs(OUT_DIR, exist_ok=True)

    def shot(name: str):
        app.processEvents()
        path = os.path.join(OUT_DIR, name)
        win.grab().save(path)
        print(f"saved {path}")

    # 1. Flow Diagram workspace with a module selected (reference p.74)
    if win.flow_scene.node_items:
        first = next(iter(win.flow_scene.node_items.values()))
        first.setSelected(True)
        main_win_node = win.pipeline.nodes.get(first.tool.instance_id)
        if main_win_node:
            win.on_node_selected(first.tool.instance_id)
    app.processEvents()
    shot("vm_flow_workspace.png")

    # 2. Tool Box flyout open on a different category (reference p.72/p.74)
    win.tool_rail._on_category_clicked("Location")
    app.processEvents()
    shot("vm_toolbox_flyout.png")

    # 3. Multi-flow overview (reference p.95)
    win.solution.add_flow("Flow2")
    win.solution.flows["Flow2"].add_node(
        __import__("vm_clone.core.registry", fromlist=["create_tool_instance"])
        .create_tool_instance("Image Source", "f2_src", "01_Acquisition")
    )
    win.solution.add_flow("Flow3")
    win.flow_overview.rebuild(win.solution.flows, win.solution.get_trigger_flow_name())
    win._refresh_flow_tabs()
    win.tab_workspace.setCurrentIndex(2)
    app.processEvents()
    shot("vm_multiflow_overview.png")

    # 4. Operation interface + Result tab (reference p.40 item 5/6, p.87)
    win.on_overview_flow_activated("Flow1")
    win.data_tabs.setCurrentWidget(win.result_panel)
    shot("vm_result_panel.png")

    win.data_tabs.setCurrentWidget(win.image_canvas)
    win.tab_workspace.setCurrentIndex(1)
    shot("vm_operation_interface.png")

    # 5. Close-up of the Tool Box only
    win.tool_dock.widget().grab().save(os.path.join(OUT_DIR, "vm_toolbox_closeup.png"))
    print("saved tool closeup")

    # 6. Module Configuration Dialog showing Input Params bound to connection wire
    from vm_clone.ui.module_config import ModuleConfigDialog
    tm = win.pipeline.nodes.get("node_template")
    if tm:
        dlg = ModuleConfigDialog(tm, win.pipeline.last_results.get("node_template"), win, pipeline=win.pipeline)
        dlg.show()
        for _ in range(3):
            app.processEvents()
        dlg_path = os.path.join(OUT_DIR, "vm_module_config_dialog.png")
        dlg.grab().save(dlg_path)
        print(f"saved {dlg_path}")
        dlg.close()
        dlg.deleteLater()

    win.close()
    print("snapshot pass complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
