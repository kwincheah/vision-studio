"""Capture Qt warnings (especially stylesheet parse failures) while opening dialogs.

Qt reports "Could not parse stylesheet of object QLabel(0x...)" on stderr with no
object name, so this installs a message handler and reports the warning together with
the dialog being opened, and then locates the offending widget by checking each
label's own stylesheet against a scratch widget.

Run:  python scripts/audit_qt_warnings.py
"""
import os
import sys
from typing import List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

WARNINGS: List[str] = []


def main() -> int:
    from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QWidget
    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

    def handler(mode, context, message):
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg):
            WARNINGS.append(message)

    qInstallMessageHandler(handler)

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication([])
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(20):
        app.processEvents()

    print("--- warnings while the main window runs ---")
    for w in WARNINGS:
        print(f"  {w}")
    WARNINGS.clear()

    # Open each dialog in turn and see which one provokes a parse failure.  A modal
    # dialog blocks inside its own `exec()`, so a timer must close it: Qt runs timers
    # in the nested event loop.
    from PyQt6.QtCore import QTimer
    from scripts.audit_ui_dialogs import DIALOGS, find_action

    for menu_title, action_text, name in DIALOGS:
        action = find_action(win, menu_title, action_text)
        if action is None:
            continue
        WARNINGS.clear()
        opened: List[QDialog] = []

        def collect():
            for w in app.topLevelWidgets():
                if isinstance(w, QDialog) and w.isVisible() and w not in opened:
                    opened.append(w)

        poll = QTimer()
        poll.setInterval(200)
        poll.timeout.connect(collect)
        poll.start()
        closer = QTimer()
        closer.setInterval(900)
        closer.timeout.connect(lambda: [w.close() for w in opened])
        closer.start()
        try:
            action.trigger()
        except Exception as exc:
            print(f"{name}: trigger raised {type(exc).__name__}: {exc}")
            poll.stop()
            closer.stop()
            continue
        finally:
            poll.stop()
            closer.stop()

        # inspect any dialog that was captured before it closed
        for top in opened:
            try:
                labels = top.findChildren(QLabel)
            except RuntimeError:
                continue          # already destroyed by the application
            for lab in labels:
                try:
                    css = lab.styleSheet()
                except RuntimeError:
                    continue
                if not css.strip():
                    continue
                scratch = QLabel()
                probe: List[str] = []
                qInstallMessageHandler(lambda m, c, msg: probe.append(msg))
                scratch.setStyleSheet(css)
                qInstallMessageHandler(handler)
                scratch.deleteLater()
                if probe:
                    print(f"\n{menu_title} / {action_text}")
                    print(f"    OFFENDER {type(top).__name__} -> "
                          f"QLabel({lab.objectName()!r}) text={lab.text()[:30]!r}")
                    print(f"      css={css[:160]!r}")
                    for p in probe:
                        print(f"      {p}")
            try:
                top.reject()
                top.deleteLater()
            except Exception:
                pass

        if WARNINGS:
            print(f"\n{menu_title} / {action_text}:")
            for w in WARNINGS:
                print(f"    {w}")
        for _ in range(6):
            app.processEvents()

    return 0


if __name__ == "__main__":
    sys.exit(main())
