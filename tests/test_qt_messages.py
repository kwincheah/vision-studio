"""Qt itself reports QML mistakes on stderr (deprecated handler injection, focus misuse, ...) instead of
raising them.  These tests fail on any such message so they cannot reach the console again."""
import os
import subprocess
import sys

import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

from test_qml_interaction import fresh, ui  # noqa: F401

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IGNORED = ("libpng", "QFont::", "propagateSizeHints", "QWindowsWindow::setGeometry")


def significant(lines):
    return [l for l in lines if l.strip() and not any(i in l for i in IGNORED)]


def test_application_startup_prints_no_qt_warnings():
    env = dict(os.environ, APEX_AUTOQUIT_MS="2500", QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "main.py")], cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
    bad = significant((out.stderr + out.stdout).splitlines())
    bad = [l for l in bad if not l.startswith("[INFO]")]
    assert not bad, "\n".join(bad)


def test_opening_dialogs_and_the_ai_panel_and_disabling_focused_buttons_prints_nothing(ui):
    seen = []

    def handler(kind, ctx, msg):
        if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            seen.append(msg)

    qInstallMessageHandler(handler)
    try:
        for name in ("globalVars", "flowSettings", "validation", "cameraSet", "lensCal", "plugins", "newProject", "confirm"):
            ui.host.setProperty("current", name)
            ui.spin(25)
            ui.close_dialog()
        ui.main.setProperty("aiVisible", True)
        ui.spin(30)
        # a focused button becoming disabled must not warn
        for btn in ui.of_type("AppButton"):
            if btn.isVisible():
                btn.forceActiveFocus()
                btn.setProperty("enabledState", False)
                btn.setProperty("enabledState", True)
        ui.main.setProperty("aiVisible", False)
        ui.spin(20)
        # every switch in the main window: toggling runs its handler (where parameter-injection warnings arise)
        for sw in [c for c in ui.of_type("ToggleSwitch") if c.isVisible()]:
            ui.click(ui.center(sw))
            ui.click(ui.center(sw))
    finally:
        qInstallMessageHandler(None)
    assert not significant(seen), seen
