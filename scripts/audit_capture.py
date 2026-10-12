"""Audit capture pass: render every screen and interaction state of the app.

Produces the evidence set used for the UI/UX audit. Each capture is at a fixed
1600x950 window so screenshots are directly comparable between iterations.
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "docs", "screenshots", "audit")
W, H = 1600, 950


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from vm_clone.ui.styles import initialize_app_fonts
    initialize_app_fonts(app)
    from vm_clone.ui.main_window import VisionMasterMainWindow

    os.makedirs(OUT, exist_ok=True)
    win = VisionMasterMainWindow()
    win.resize(W, H)
    win.show()
    for _ in range(6):
        app.processEvents()
    time.sleep(0.2)
    app.processEvents()

    def shot(name, widget=None):
        app.processEvents()
        target = widget or win
        path = os.path.join(OUT, name)
        target.grab().save(path)
        print(f"saved {name}")

    # 1. Flow diagram, module selected
    first = next(iter(win.flow_scene.node_items.values()))
    first.setSelected(True)
    win.on_node_selected(first.tool.instance_id)
    app.processEvents()
    shot("01_flow_diagram.png")

    # 2. Tool flyout per category (check every category renders)
    for cat in ("Acquisition", "Location", "Measurement", "Image Processing",
                "Logic Tools"):
        win.tool_rail._on_category_clicked(cat)
        app.processEvents()
        shot(f"02_toolbox_{cat.replace(' ', '_').lower()}.png", win.tool_dock.widget())

    # 3. Tool search results
    win.tool_flyout.txt_search.setText("search")
    app.processEvents()
    shot("03_toolbox_search.png", win.tool_dock.widget())
    win.tool_flyout.txt_search.clear()
    win.tool_rail._on_category_clicked("Location")

    # 4. Result tab
    win.data_tabs.setCurrentWidget(win.result_panel)
    app.processEvents()
    shot("04_result_panel.png", win.property_dock.widget())

    # 5. Property inspector without a module
    win.data_tabs.setCurrentIndex(1)
    win.inspector.set_tool(None) if False else None
    app.processEvents()

    # 6. Bottom dock tabs
    for idx, name in ((0, "current_result"), (1, "history"), (2, "help")):
        win.bottom_tabs.setCurrentIndex(idx)
        app.processEvents()
        shot(f"05_bottom_{name}.png", win.result_dock.widget())

    # 7. Operation interface
    win.tab_workspace.setCurrentIndex(1)
    app.processEvents()
    shot("06_operation_interface.png")

    # 8. Multi-flow overview
    win.solution.add_flow("Flow2")
    win.solution.add_flow("Flow3")
    win.flow_overview.rebuild(win.solution.flows, win.solution.get_trigger_flow_name())
    win._refresh_flow_tabs()
    win.tab_workspace.setCurrentIndex(2)
    app.processEvents()
    shot("07_multi_flow.png")

    # 9. Menus open
    win.tab_workspace.setCurrentIndex(0)
    for menu_action, name in ((1, "file"), (2, "settings"), (3, "tools"),
                              (4, "system"), (5, "view"), (6, "help")):
        acts = win.menuBar().actions()
        if menu_action < len(acts):
            menu = acts[menu_action].menu()
            if menu is not None:
                menu.popup(win.mapToGlobal(win.menuBar().mapTo(win, win.menuBar().actionGeometry(acts[menu_action]).bottomLeft())) + __import__("PyQt6.QtCore", fromlist=["QPoint"]).QPoint(0, 4))
                app.processEvents()
                time.sleep(0.05)
                app.processEvents()
                screen = app.primaryScreen()
                pix = screen.grabWindow(0)
                pix.save(os.path.join(OUT, f"08_menu_{name}.png"))
                print(f"saved 08_menu_{name}.png")
                menu.close()
                app.processEvents()

    # 10. Validation dialog
    issues = win.pipeline.validate_flow()
    from vm_clone.ui.main_window import FlowValidationDialog
    dlg = FlowValidationDialog(issues, win)
    dlg.show()
    app.processEvents()
    dlg.grab().save(os.path.join(OUT, "09_validation_dialog.png"))
    print("saved 09_validation_dialog.png")
    dlg.close()

    # 11. Global variables dialog
    from vm_clone.ui.global_vars_dialog import GlobalVariablesDialog
    gv = GlobalVariablesDialog(win.solution.global_variables, win)
    gv.show()
    app.processEvents()
    gv.grab().save(os.path.join(OUT, "10_global_vars_dialog.png"))
    print("saved 10_global_vars_dialog.png")
    gv.close()

    # 12. Locked state + continuous running state
    win.btn_lock.setChecked(True)
    app.processEvents()
    shot("11_locked_state.png", win.toolbar_resources)
    win.btn_lock.setChecked(False)

    # 12b. Module configuration window (manual 4.3.0 §8.1/§8.2)
    from vm_clone.ui.module_config import ModuleConfigDialog
    nid = next(iter(win.pipeline.nodes))
    dlg = ModuleConfigDialog(win.pipeline.nodes[nid],
                            win.pipeline.last_results.get(nid), win)
    dlg.show()
    for _ in range(4):
        app.processEvents()
    for i in range(dlg.tabs.count()):
        dlg.tabs.setCurrentIndex(i)
        app.processEvents()
        dlg.grab().save(os.path.join(OUT, f"22_module_config_tab{i}.png"))
    print("saved 22_module_config_tab*.png")
    dlg.close()

    # 12c. Image display area close-up
    shot("23_image_display.png", win.property_dock.widget())
    # 12d. Result display area close-up
    shot("24_result_display.png", win.result_dock.widget())

    # 13. Empty flow (new solution)
    win.on_new_solution()
    app.processEvents()
    shot("12_empty_flow.png")

    # 14. Minimum supported size
    win.resize(1100, 720)
    for _ in range(6):
        app.processEvents()
    shot("13_small_window.png")

    # 15. Narrow right dock
    win.resize(1600, 950)
    app.processEvents()
    win.resizeDocks([win.property_dock], [240], Qt.Orientation.Horizontal)
    app.processEvents()
    shot("14_narrow_right_dock.png")

    win.close()
    print("audit capture complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
