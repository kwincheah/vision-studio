"""Open and capture every dialog reachable from the application menus.

Dialog contrast, clipping and layout cannot be judged from the source, and several of
these dialogs (calibration wizards, camera configuration) are the least-exercised code
in the project.  Each is opened, given time to lay out, captured, and probed.

Run:  python scripts/audit_ui_dialogs.py
"""
import os
import sys
import traceback
from typing import Any, Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "screenshots", "audit")

#: menu path (menu title, action text) -> a stable capture name
DIALOGS = [
    ("File", "New Solution...", "new_solution"),
    ("File", "Load Image File...", "load_image"),
    ("Settings", "Global Variables...", "global_variables"),
    ("Settings", "Communication Configuration", "communication_config"),
    ("Tools", "Camera Lens Distortion Calibration Wizard...", "lens_calibration"),
    ("Tools", "N-Point Spatial Calibration Wizard", "npoint_calibration"),
    ("Tools", "Calibration Target Generator", "calibration_target"),
    ("System", "Camera Set", "camera_set"),
    ("System", "Controller Management", "controller_management"),
    ("System", "Log Viewer", "log_viewer"),
    ("System", "Performance Options", "performance_options"),
    ("Help", "User Manual", "user_manual"),
    ("Help", "Keyboard Shortcuts", "keyboard_shortcuts"),
    ("Help", "Version Information", "version_information"),
    ("Help", "About Apex Industrial Vision Studio", "about"),
]


def find_action(win, menu_title: str, action_text: str):
    for action in win.menuBar().actions():
        if action.text().replace("&", "").strip().lower() != menu_title.lower():
            continue
        menu = action.menu()
        if menu is None:
            continue
        for sub in menu.actions():
            label = sub.text().replace("&", "").strip()
            if label.lower() == action_text.lower():
                return sub
    return None


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
    from PyQt6.QtCore import QTimer

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(24):
        app.processEvents()

    records: List[Dict[str, Any]] = []
    captured = 0

    for menu_title, action_text, name in DIALOGS:
        action = find_action(win, menu_title, action_text)
        rec: Dict[str, Any] = {"menu": menu_title, "action": action_text, "name": name}
        if action is None:
            rec["outcome"] = "ACTION NOT FOUND"
            records.append(rec)
            print(f"MISSING  {menu_title} / {action_text}")
            continue

        captured_dialogs: List[Dict[str, Any]] = []

        # Modal dialogs block inside their own `exec()`, so a timer must both capture
        # and dismiss them.  Grabbing inside the same callback that first sees the
        # dialog avoids a second timer racing in and destroying it (which is what
        # "wrapped C/C++ object ... has been deleted" meant).
        def on_poll(menu=menu_title, text=action_text, tag=name, sink=captured_dialogs):
            for w in app.topLevelWidgets():
                if not isinstance(w, QDialog) or not w.isVisible():
                    continue
                if any(d["widget"] is w for d in sink):
                    continue
                cls = type(w).__name__
                entry: Dict[str, Any] = {"widget": w, "class": cls}
                if cls in ("QFileDialog", "QColorDialog", "QFontDialog"):
                    entry["outcome"] = "native dialog (not capturable offscreen)"
                else:
                    try:
                        fname = f"C_{tag}_{cls}.png"
                        w.grab().save(os.path.join(OUT, fname))
                        entry.update({
                            "outcome": "ok",
                            "title": (w.windowTitle() or cls)[:60],
                            "size": [w.width(), w.height()],
                            "shot": fname,
                        })
                    except Exception as exc:
                        entry["outcome"] = "CAPTURE FAILED"
                        entry["detail"] = f"{type(exc).__name__}: {exc}"
                sink.append(entry)
                try:
                    w.close()
                except Exception:
                    pass

        poll = QTimer()
        poll.setInterval(150)
        poll.timeout.connect(on_poll)
        poll.start()
        try:
            action.trigger()
        except Exception as exc:
            rec["outcome"] = "TRIGGER RAISED"
            rec["detail"] = f"{type(exc).__name__}: {exc}"
            records.append(rec)
            print(f"RAISED   {menu_title} / {action_text}: {rec['detail']}")
            poll.stop()
            continue
        # let the poll timer observe the dialog through the nested event loop
        for _ in range(12):
            app.processEvents()
        poll.stop()

        for entry in captured_dialogs:
            record = dict(entry)
            record.pop("widget", None)
            records.append({"menu": menu_title, "action": action_text, "name": name,
                            **record})
            status = record.get("outcome")
            if status == "ok":
                captured += 1
                print(f"ok       {menu_title:9s} / {action_text[:38]:40s} "
                      f"{record['class']:28s} {record['size'][0]}x{record['size'][1]}")
            else:
                print(f"{status[:8]:8s} {menu_title} / {action_text[:38]}: "
                      f"{record.get('detail', '')}")
        if not captured_dialogs:
            records.append({"menu": menu_title, "action": action_text, "name": name,
                            "outcome": "NO DIALOG"})
            print(f"NODLG    {menu_title} / {action_text}")
        for _ in range(6):
            app.processEvents()
        records.append(rec)
        for _ in range(6):
            app.processEvents()

    import json
    with open(os.path.join(OUT, "dialog_inventory.json"), "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=1, default=str)

    ok = [r for r in records if r.get("outcome") == "ok"]
    bad = [r for r in records if r.get("outcome") != "ok"]
    print(f"\n{len(ok)}/{len(records)} dialogs captured, {captured} screenshot(s)")
    for r in bad:
        print(f"  ! {r.get('menu', '?')} / {r.get('action', '?')}: "
              f"{r.get('outcome', 'unknown')} {r.get('detail', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
