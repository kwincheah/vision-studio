"""
Automated unit tests for Vision Master Project Manager and Start Page.
Verifies:
- ProjectManager recent projects tracking, filtering, persistence, and deletion
- Solution creation across templates (Blank, PCB, Measurement, YOLO, Calibration)
- Physical file deletion vs list removal
- StartPageDialog rendering, search filtering, and event signals
- NewProjectDialog project generation
- Integration with VisionMasterMainWindow
"""
import os
import shutil
import tempfile
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from apex_vision.core.project_manager import ProjectManager
from apex_vision.core.pipeline import SolutionManager, VisionPipeline
from apex_vision.ui.start_page import StartPageDialog, NewProjectDialog, ProjectRowWidget


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def temp_workspace():
    tmp_dir = tempfile.mkdtemp(prefix="vm_proj_test_")
    yield tmp_dir
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_project_manager_init_and_seed(temp_workspace):
    """Verify ProjectManager initializes and seeds sample projects if empty."""
    pm = ProjectManager(workspace_root=temp_workspace)
    assert os.path.exists(pm.default_projects_dir)
    assert os.path.exists(pm.cache_dir)

    pm.seed_default_samples_if_empty()
    recent = pm.get_recent_projects()
    assert len(recent) >= 3

    names = [p["name"] for p in recent]
    assert any("PCB" in n for n in names)
    assert any("Measurement" in n for n in names)
    assert any("YOLO" in n for n in names)

    # Check file exists flag
    for p in recent:
        assert p["file_exists"] is True
        assert os.path.exists(p["path"])


def test_project_creation_all_templates(temp_workspace):
    """Verify project creation across different templates."""
    pm = ProjectManager(workspace_root=temp_workspace)

    templates = ["blank", "pcb", "measurement", "yolo", "calibration"]
    for tpl in templates:
        name = f"Test_{tpl}"
        sol, fpath = pm.create_project(name, template=tpl)
        assert isinstance(sol, SolutionManager)
        assert os.path.exists(fpath)
        assert sol.name == name
        assert len(sol.flows) >= 1

        # Check top of recent
        recent = pm.get_recent_projects()
        assert recent[0]["name"] == name
        assert os.path.normpath(recent[0]["path"]) == os.path.normpath(fpath)


def test_project_load_and_save(temp_workspace):
    """Verify saving and reloading a multi-flow solution via ProjectManager."""
    pm = ProjectManager(workspace_root=temp_workspace)
    sol, fpath = pm.create_project("MultiFlowProj", template="pcb")

    # Add a second flow
    sol.add_flow("SecondaryFlow")
    sol.global_variables["g_TestVar"] = 999
    pm.save_project(sol, fpath)

    # Reload
    loaded_sol = pm.load_project(fpath)
    assert loaded_sol.name == "MultiFlowProj"
    assert "SecondaryFlow" in loaded_sol.flows
    assert loaded_sol.global_variables.get("g_TestVar") == 999


def test_project_deletion_modes(temp_workspace):
    """Verify both 'delete from disk' and 'remove from list only' modes."""
    pm = ProjectManager(workspace_root=temp_workspace)
    sol1, fpath1 = pm.create_project("DeleteDiskTest", template="blank")
    sol2, fpath2 = pm.create_project("RemoveListTest", template="blank")

    assert os.path.exists(fpath1)
    assert os.path.exists(fpath2)

    # 1. Delete physical file from disk
    ok1, msg1 = pm.delete_project_file(fpath1, delete_file_from_disk=True)
    assert ok1 is True
    assert not os.path.exists(fpath1)
    assert not any(p["path"] == fpath1 for p in pm.get_recent_projects())

    # 2. Remove from list only (keep file on disk)
    pm.remove_recent_project(fpath2)
    assert os.path.exists(fpath2)
    assert not any(p["path"] == fpath2 for p in pm.get_recent_projects())


def test_start_page_settings_toggle(temp_workspace):
    """Verify startup toggle preference."""
    pm = ProjectManager(workspace_root=temp_workspace)
    pm.set_show_on_startup(False)
    assert pm.get_show_on_startup() is False

    pm.set_show_on_startup(True)
    assert pm.get_show_on_startup() is True


def test_start_page_dialog_ui(qapp, temp_workspace):
    """Verify StartPageDialog renders, filters recent projects, and emits signals."""
    pm = ProjectManager(workspace_root=temp_workspace)
    pm.seed_default_samples_if_empty()

    dlg = StartPageDialog(project_manager=pm)
    assert "Start Page" in dlg.windowTitle()
    assert dlg.list_projects.count() >= 3

    # Test real-time search filter
    dlg.edit_search.setText("PCB")
    assert dlg.list_projects.count() >= 1

    dlg.edit_search.setText("NonExistentQuery_XYZ")
    assert dlg.list_projects.count() == 0
    assert not dlg.lbl_empty.isHidden()
    assert dlg.list_projects.isHidden()

    dlg.edit_search.setText("")
    assert dlg.list_projects.count() >= 3

    # Test template click signal
    received_signal = []
    dlg.solution_ready.connect(lambda sol, path: received_signal.append((sol, path)))
    dlg.on_template_clicked("yolo")
    assert len(received_signal) == 1
    assert "YOLO" in received_signal[0][0].name

    dlg.close()


def test_new_project_dialog(qapp, temp_workspace):
    """Verify NewProjectDialog form configuration and creation."""
    pm = ProjectManager(workspace_root=temp_workspace)
    dlg = NewProjectDialog(project_manager=pm)
    dlg.edit_name.setText("ModalCreatedProject")
    dlg.combo_template.setCurrentIndex(1)  # PCB template

    dlg._create_project()
    assert dlg.created_solution is not None
    assert dlg.created_filepath is not None
    assert os.path.exists(dlg.created_filepath)
    assert dlg.created_solution.name == "ModalCreatedProject"

    dlg.close()


def test_main_window_integration(qapp, temp_workspace):
    """Verify VisionMasterMainWindow integration with project_manager and start_page."""
    from apex_vision.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    assert hasattr(win, "project_manager")
    assert win.project_manager is not None

    # Verify menu action exists
    actions = [a.text() for a in win.menuBar().actions()]
    assert any("File" in a for a in actions)

    # Verify toolbar has start page button
    btn_tooltips = [b.toolTip() for b in win.toolbar_resources.findChildren(type(win.toolbar_resources.widgetForAction(win.toolbar_resources.actions()[0])))] if win.toolbar_resources.actions() else []
    
    # Test loading solution through load_solution_manager
    pm = ProjectManager(workspace_root=temp_workspace)
    sol, fpath = pm.create_project("WindowIntegrationSolution", template="measurement")
    win.load_solution_manager(sol, filepath=fpath)

    assert "WindowIntegrationSolution" in win.windowTitle()
    assert win.solution.name == "WindowIntegrationSolution"
    assert win.current_project_path == fpath

    win.close()


def test_main_window_not_shown_before_project_open_accepted(qapp, temp_workspace, monkeypatch):
    """Verify the main window is NOT visible before user finishes opening a project on the start page."""
    from apex_vision.ui.main_window import VisionMasterMainWindow
    from apex_vision.ui.start_page import StartPageDialog
    from PyQt6.QtWidgets import QDialog

    pm = ProjectManager(workspace_root=temp_workspace)
    sol, fpath = pm.create_project("AcceptedStartupSolution", template="pcb")

    win = VisionMasterMainWindow()
    win.project_manager = pm
    win.project_manager.set_show_on_startup(True)

    # Main window must not be visible yet
    assert win.isVisible() is False

    # Simulate user clicking/opening project inside StartPageDialog.exec()
    def mock_exec(dialog_self):
        # Dialog is executing, main window MUST STILL be invisible
        assert win.isVisible() is False
        dialog_self.solution_ready.emit(sol, fpath)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(StartPageDialog, "exec", mock_exec)

    res = win.run_startup_flow()
    assert res is True
    # Now that user finished opening project, main window is shown
    assert win.isVisible() is True
    assert win.solution.name == "AcceptedStartupSolution"

    win.close()


def test_main_window_never_shown_when_startup_cancelled(qapp, temp_workspace, monkeypatch):
    """Verify the main window is NEVER shown if user cancels/closes the start page without opening a project."""
    from apex_vision.ui.main_window import VisionMasterMainWindow
    from apex_vision.ui.start_page import StartPageDialog
    from PyQt6.QtWidgets import QDialog

    pm = ProjectManager(workspace_root=temp_workspace)
    win = VisionMasterMainWindow()
    win.project_manager = pm
    win.project_manager.set_show_on_startup(True)

    assert win.isVisible() is False

    # Simulate user closing/cancelling dialog
    def mock_exec(dialog_self):
        assert win.isVisible() is False
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(StartPageDialog, "exec", mock_exec)

    res = win.run_startup_flow()
    assert res is False
    # Main window MUST NOT be shown
    assert win.isVisible() is False

    win.close()


def test_main_window_shown_directly_when_startup_disabled(qapp, temp_workspace):
    """Verify main window opens directly when show_on_startup preference is disabled."""
    from apex_vision.ui.main_window import VisionMasterMainWindow

    pm = ProjectManager(workspace_root=temp_workspace)
    win = VisionMasterMainWindow()
    win.project_manager = pm
    win.project_manager.set_show_on_startup(False)

    assert win.isVisible() is False
    res = win.run_startup_flow()
    assert res is True
    assert win.isVisible() is True

    win.close()

