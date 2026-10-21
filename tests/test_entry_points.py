"""``main.py`` starts the QML interface; the widget interface stays available with --widgets."""
import os
import subprocess
import sys

import pytest

pytest.importorskip("PyQt6.QtQml")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEMO = os.path.join(ROOT, "projects", "PCB_Inspection_Demo.vmp")


def launch(*args, timeout=90):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", APEX_AUTOQUIT_MS="2500")
    return subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout)


def test_main_py_starts_the_qml_interface_with_a_solution_file():
    result = launch(DEMO)
    assert result.returncode == 0, result.stderr[-800:]
    assert "QML" not in result.stderr.replace("QML_", "") or "Error" not in result.stderr
    assert "TypeError" not in result.stderr and "ReferenceError" not in result.stderr


def test_main_py_starts_the_qml_interface_without_arguments():
    result = launch()
    assert result.returncode == 0, result.stderr[-800:]
    assert "ReferenceError" not in result.stderr


def test_main_py_still_offers_the_widget_interface():
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "--widgets" in src and "def run_widgets" in src
    from importlib import util
    spec = util.spec_from_file_location("apex_main", os.path.join(ROOT, "main.py"))
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.run_widgets) and callable(module.main)


def test_backend_startup_and_close_behaviour(tmp_path):
    from PyQt6.QtGui import QGuiApplication
    from apex_vision.core.project_manager import ProjectManager
    from apex_vision.qml_backend import AppBackend, FrameProvider
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    pm = ProjectManager(workspace_root=str(tmp_path))
    b = AppBackend(FrameProvider(), pm)
    shown, closed, asked = [], [], []
    b.startPageRequested.connect(lambda: shown.append(1))
    b.closeApproved.connect(lambda: closed.append(1))
    b.confirmRequested.connect(asked.append)

    pm.set_show_on_startup(False)
    b.startup()
    assert not shown and len(b.nodes) == 7 and b.solutionName == "IndustrialSolution"
    pm.set_show_on_startup(True)
    b.startup()
    assert shown                                              # the start page comes first when enabled
    b.setShowStartPageOnStartup(False)
    assert pm.get_show_on_startup() is False and b.showStartPageOnStartup is False

    b.requestClose()                                          # clean: the window may close at once
    assert closed and not asked
    b.engine.wait_for_run()
    b.addTool("Histogram")
    b.engine.wait_for_run()
    b.requestClose()                                          # dirty: ask first
    assert asked and len(closed) == 1
    b.confirmCancel()
    assert len(closed) == 1
    b.requestClose()
    b.confirmDiscard()
    assert len(closed) == 2
    b.engine.wait_for_run()
