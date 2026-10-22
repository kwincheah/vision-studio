"""Pytest configuration and global fixtures for Vision Studio test suite."""
import os

# Default to offscreen platform for headless and CI test execution so that
# top-level Qt windows are not constrained by host/runner desktop resolutions (e.g. 1024x768).
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"


import pytest


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
    """A window built by a test must not write into the developer's real recent-projects list."""
    try:
        import apex_vision.ui.main_window as mw
        from apex_vision.core.project_manager import ProjectManager as _PM
    except Exception:  # pragma: no cover
        return
    workspace = str(tmp_path_factory.mktemp("vm_workspace"))
    monkeypatch.setattr(mw, "ProjectManager", lambda *a, **k: _PM(*a, **({"workspace_root": workspace} | k)
                                                                    if not a and "workspace_root" not in k else k))
