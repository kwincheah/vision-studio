"""Pytest configuration and global fixtures for Vision Studio test suite."""
import os

# Default to offscreen platform for headless and CI test execution so that
# top-level Qt windows are not constrained by host/runner desktop resolutions (e.g. 1024x768).
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _system_font_dir() -> str:
    """The host's font directory, or "" when none of the usual ones exist.

    The offscreen platform does not consult the platform font database, and PyQt6 no
    longer ships a `Qt6/lib/fonts` directory, so without this Qt reports
    "QFontDatabase: Cannot find font directory ..." and finds *zero* font families -
    which breaks any test that measures text.  Pointing `QT_QPA_FONTDIR` at the host
    fonts restores them (measured on this machine: 0 -> 185 families).
    """
    for path in (r"C:\Windows\Fonts", "/usr/share/fonts", "/usr/local/share/fonts",
                 "/System/Library/Fonts", os.path.expanduser("~/Library/Fonts")):
        if os.path.isdir(path):
            return path
    return ""


if "QT_QPA_FONTDIR" not in os.environ:
    _fonts = _system_font_dir()
    if _fonts:
        os.environ["QT_QPA_FONTDIR"] = _fonts


import pytest

# One QApplication for the whole run: a bare QGuiApplication created first by a QML test makes every later
# widget test abort the process, so the widgets-capable application always comes first.
try:
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
except ImportError:  # pragma: no cover - PyQt6 is a hard dependency; only guards odd environments
    _APP = None


@pytest.fixture(autouse=True)
def _never_block_on_unsaved_changes_prompt(monkeypatch):
    """Windows closed by a test often hold edits; answer the modal prompt instead of hanging.

    Tests that exercise the prompt itself monkeypatch ``_confirm_discard_changes`` again.
    """
    try:
        from apex_vision.ui.main_window import ApexMainWindow
    except Exception:  # pragma: no cover - UI stack unavailable
        return
    monkeypatch.setattr(ApexMainWindow, "run_async", False)
    monkeypatch.setattr(ApexMainWindow, "_confirm_discard_changes",
                        lambda self, when="before closing": "discard")


@pytest.fixture(autouse=True)
def _isolate_default_project_manager(monkeypatch, tmp_path_factory):
    """Nothing a test builds may write into the developer's real recent-projects list.

    Three modules construct a default `ProjectManager()` - the widget window, the QML
    backend and the start page - and patching only the first left the other two writing
    into `.apex_config/recent_projects.json`.  The visible symptom was a start screen whose
    "Recent projects" list was mostly `...Temp/pytest-of-<user>/pytest-665/Mine2.apex`
    entries: 28 of 30 records were test artefacts.  All three are patched here.
    """
    try:
        import apex_vision.qml_backend as qb
        import apex_vision.ui.main_window as mw
        import apex_vision.ui.start_page as sp
        from apex_vision.core.project_manager import ProjectManager as _PM
    except Exception:  # pragma: no cover - UI stack unavailable
        return

    workspace = str(tmp_path_factory.mktemp("apex_workspace"))

    def _scoped(*args, **kwargs):
        # Only redirect a *default* construction; a caller that passed its own workspace
        # root or arguments keeps them.
        if not args and "workspace_root" not in kwargs:
            kwargs = {**kwargs, "workspace_root": workspace}
        return _PM(*args, **kwargs)

    for module in (mw, qb, sp):
        monkeypatch.setattr(module, "ProjectManager", _scoped)

