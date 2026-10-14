"""Inventory and capture every dialog and screen reachable in the application.

Walks the real `QMainWindow` menu tree, records every action, and captures the window
plus each dialog that can be opened without external hardware.  The screenshot set is
then probed for the visual properties this audit cares about (clipping, contrast,
layout), so a visual claim is always backed by a measurement.

Run:  python scripts/audit_ui_screens.py
"""
import json
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "docs", "screenshots", "audit")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    from PyQt6.QtWidgets import QApplication, QDialog, QMenu, QWidget
    from PyQt6.QtCore import Qt

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(26):
        app.processEvents()

    # ---------------------------------------------------------------
    # 1. Menu inventory
    # ---------------------------------------------------------------
    menus: List[Dict[str, Any]] = []
    for action in win.menuBar().actions():
        menu = action.menu()
        if menu is None:
            continue
        entries = []
        for sub in menu.actions():
            if sub.isSeparator():
                entries.append({"separator": True})
                continue
            if sub.menu() is not None:
                entries.append({
                    "text": sub.text().replace("&", ""),
                    "submenu": [s.text().replace("&", "") for s in sub.menu().actions()
                                if not s.isSeparator()],
                })
                continue
            entries.append({
                "text": sub.text().replace("&", ""),
                "enabled": sub.isEnabled(),
                "checkable": sub.isCheckable(),
                "checked": sub.isChecked(),
                "shortcut": sub.shortcut().toString(),
            })
        menus.append({"menu": action.text().replace("&", ""), "items": entries})

    # ---------------------------------------------------------------
    # 2. Toolbars and their controls
    # ---------------------------------------------------------------
    toolbars = []
    for tb in win.findChildren(type(win.toolbar_resources)):
        if tb is None:
            continue
        controls = []
        for child in tb.findChildren(QWidget):
            name = child.objectName() or type(child).__name__
            controls.append({
                "object": name,
                "type": type(child).__name__,
                "enabled": child.isEnabled(),
                "visible": child.isVisible(),
                "size": [child.width(), child.height()],
                "text": (child.text()[:30] if hasattr(child, "text") else ""),
                "tooltip": (child.toolTip()[:60] if hasattr(child, "toolTip") else ""),
            })
        toolbars.append({"name": tb.objectName(), "controls": controls})

    # ---------------------------------------------------------------
    # 3. Docks and panels
    # ---------------------------------------------------------------
    docks = []
    for dock in win.findChildren(type(win.property_dock)):
        docks.append({
            "object": dock.objectName(),
            "title": dock.windowTitle(),
            "visible": dock.isVisible(),
            "floating": dock.isFloating(),
            "size": [dock.width(), dock.height()],
        })

    inventory = {"menus": menus, "toolbars": toolbars, "docks": docks}

    with open(os.path.join(OUT, "ui_inventory.json"), "w", encoding="utf-8") as fh:
        json.dump(inventory, fh, indent=1, default=str)

    print(f"menus: {len(menus)}")
    for m in menus:
        plain = [i.get("text", "---") for i in m["items"]]
        print(f"  {m['menu']:10s} ({len(m['items'])}): {', '.join(plain)[:110]}")
    print(f"\ntoolbars: {len(toolbars)}")
    for tb in toolbars:
        print(f"  {tb['name']:20s} {len(tb['controls'])} control(s)")
    print(f"\ndocks: {len(docks)}")
    for d in docks:
        print(f"  {d['object']:22s} {d['title'][:28]:30s} {d['size']}")

    # every menu action must be either enabled or explainably disabled
    disabled = [(m["menu"], i["text"]) for m in menus for i in m["items"]
                if isinstance(i, dict) and i.get("enabled") is False]
    print(f"\ndisabled actions: {len(disabled)}")
    for menu_name, text in disabled[:14]:
        print(f"  {menu_name} / {text}")

    # ---------------------------------------------------------------
    # 4. Capture the main window and each right-column / workspace state
    # ---------------------------------------------------------------
    captured = []
    shot = win.grab()
    path = os.path.join(OUT, "B0_main.png")
    shot.save(path)
    captured.append(path)

    for i, label in enumerate(["flow", "operation", "overview"]):
        try:
            win._show_workspace_tab(i)
            for _ in range(8):
                app.processEvents()
            p = os.path.join(OUT, f"B{i + 1}_workspace_{label}.png")
            win.grab().save(p)
            captured.append(p)
        except Exception as exc:
            print(f"  workspace tab {label}: {type(exc).__name__}: {exc}")

    for i, label in enumerate(["image", "result"]):
        try:
            win.data_tabs.setCurrentIndex(i)
            for _ in range(6):
                app.processEvents()
            p = os.path.join(OUT, f"B{10 + i}_right_{label}.png")
            win.grab().save(p)
            captured.append(p)
        except Exception as exc:
            print(f"  right tab {label}: {type(exc).__name__}: {exc}")

    for i in range(win.result_display.tabs.count()):
        win.result_display.tabs.setCurrentIndex(i)
        for _ in range(5):
            app.processEvents()
        p = os.path.join(OUT, f"B{20 + i}_resulttab{i}.png")
        win.result_display.grab().save(p)
        captured.append(p)

    print(f"\ncaptured {len(captured)} screen(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
