"""Capture the interaction states that a static screen grab misses.

Tooltips, disabled controls, hover and pressed states are where contrast bugs hide,
because they are only visible on interaction.  This drives them programmatically and
captures each one so they can be inspected and probed.

Run:  python scripts/capture_states.py
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "screenshots", "audit")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    from PyQt6.QtWidgets import QApplication, QToolTip
    from PyQt6.QtCore import QPoint
    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow
    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(24):
        app.processEvents()

    # --- tooltip ----------------------------------------------------------
    QToolTip.showText(win.mapToGlobal(QPoint(300, 300)),
                      "Once - execute the active flow a single time", win)
    for _ in range(6):
        app.processEvents()
    for w in app.topLevelWidgets():
        if w.isVisible() and w.metaObject().className() == "QTipLabel":
            w.grab().save(os.path.join(OUT, "90_tooltip.png"))
            print("saved 90_tooltip.png", w.size())

    # --- disabled toolbar button -----------------------------------------
    win.btn_stop.setEnabled(False)
    for _ in range(4):
        app.processEvents()
    win.toolbar_resources.grab().save(os.path.join(OUT, "91_toolbar_disabled.png"))
    print("saved 91_toolbar_disabled.png")
    win.btn_stop.setEnabled(True)

    # --- a menu with a disabled entry ------------------------------------
    system_menu = None
    for action in win.menuBar().actions():
        if action.text().replace("&", "").lower().startswith("system"):
            system_menu = action.menu()
    if system_menu is not None:
        system_menu.popup(win.mapToGlobal(win.rect().topLeft()))
        for _ in range(5):
            app.processEvents()
        system_menu.grab().save(os.path.join(OUT, "92_menu_system.png"))
        print("saved 92_menu_system.png", system_menu.size())
        system_menu.hide()

    # --- tool flyout with a hovered and a selected cell ------------------
    win.toolbox._on_category("Measurement")
    for _ in range(6):
        app.processEvents()
    win.toolbox.grab().save(os.path.join(OUT, "93_flyout_states.png"))
    print("saved 93_flyout_states.png")

    # --- result tree selection -------------------------------------------
    win.data_tabs.setCurrentIndex(1)
    for _ in range(6):
        app.processEvents()
    win.result_panel.grab().save(os.path.join(OUT, "94_result_tree.png"))
    print("saved 94_result_tree.png")

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
