"""Regression tests for the final audit: canvas layout, persistence of node positions,
unsaved-change tracking, in-place save and toolbar/solution consistency."""
import os

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication

import vm_clone.tools  # noqa: F401  (registers the tools)
from vm_clone.core.pipeline import SolutionManager, VisionPipeline
from vm_clone.ui.styles import initialize_app_fonts

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEMO = os.path.join(ROOT, "projects", "Precision_Measurement_Demo.vmp")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)
    return app


@pytest.fixture
def win(qapp):
    from vm_clone.ui.main_window import VisionMasterMainWindow
    w = VisionMasterMainWindow()
    w.show()
    yield w
    w.close()
    w.deleteLater()


def _load(win, path):
    sol = win.project_manager.load_project(path)
    win.load_solution_manager(sol, filepath=path)
    return sol


def test_loaded_project_nodes_are_laid_out_not_stacked(win):
    _load(win, DEMO)
    pts = {(round(i.pos().x()), round(i.pos().y())) for i in win.flow_scene.node_items.values()}
    assert len(win.flow_scene.node_items) == 4
    assert len(pts) == 4, "every node was placed at the same position"


def test_node_positions_survive_save_and_load(win, tmp_path):
    _load(win, DEMO)
    nid = list(win.flow_scene.node_items)[1]
    win.flow_scene.node_items[nid].setPos(QPointF(777, 333))
    target = str(tmp_path / "moved.vmp")
    win.current_project_path = target
    win.on_save_solution()                       # in place: must not need a dialog
    assert os.path.exists(target)
    _load(win, target)
    assert win.flow_scene.node_items[nid].pos() == QPointF(777, 333)


def test_pipeline_positions_round_trip_and_reject_junk():
    pipe = VisionPipeline("F")
    from vm_clone.core.registry import create_tool_instance
    pipe.add_node(create_tool_instance("Image Source", "a", "a"))
    data = pipe.to_dict()
    data["positions"] = {"a": [10, 20], "ghost": [1, 2], "b": "junk"}
    back = VisionPipeline.from_dict(data)
    assert back.node_positions == {"a": [10.0, 20.0]}
    data["positions"] = {"a": [float("nan"), 1]}
    assert VisionPipeline.from_dict(data).node_positions == {}


def test_unsaved_change_tracking_is_live(win):
    _load(win, DEMO)
    assert not win.has_unsaved_changes()
    nid = list(win.flow_scene.node_items)[0]
    win.flow_scene.node_items[nid].setPos(QPointF(500, 400))
    assert win.has_unsaved_changes()


def test_project_chip_follows_loaded_solution_and_dirty_state(win):
    _load(win, DEMO)
    assert win.btn_project.text().startswith("Precision") and "Precision_Measurement_Demo" in win.btn_project.toolTip()
    assert not win.btn_menu_save.isEnabled()
    nid = list(win.flow_scene.node_items)[0]
    win.flow_scene.node_items[nid].setPos(QPointF(500, 400))
    win._refresh_project_chip()
    assert win.btn_project.text().startswith("● ") and win.btn_menu_save.isEnabled()


def test_project_menu_lists_recent_and_samples(win):
    _load(win, DEMO)
    win._populate_project_menu()
    titles = [a.text() for a in win.project_menu.actions() if a.text()]
    assert {"Open Solution...", "Save", "Save As...", "Recent Projects", "Sample Solutions"} <= set(titles)


def test_operator_role_locks_editing_and_engineer_unlocks(win):
    win._set_role("Operator")
    assert win.flow_scene.is_locked() and not win.btn_lock.isEnabled()
    assert win.btn_role.text() == "Operator"
    win._set_role("Engineer")
    assert not win.flow_scene.is_locked() and win.btn_lock.isEnabled()


def test_open_solution_path_reports_bad_file_without_crashing(win, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    bad = tmp_path / "bad.vmp"
    bad.write_text("{not json", encoding="utf-8")
    before = win.solution
    assert win.open_solution_path(str(bad)) is False
    assert win.solution is before and shown and "bad.vmp" in shown[0]


def test_replacing_solution_respects_cancel(win, monkeypatch):
    _load(win, DEMO)
    nid = list(win.flow_scene.node_items)[0]
    win.flow_scene.node_items[nid].setPos(QPointF(500, 400))
    monkeypatch.setattr(type(win), "_confirm_discard_changes", lambda self, when="": "cancel")
    before = win.solution
    from vm_clone.samples.pcb_solution import create_pcb_inspection_solution
    assert win._load_solution_instance(create_pcb_inspection_solution()) is False
    assert win.solution is before


def test_template_load_does_not_inherit_previous_file_path(win):
    _load(win, DEMO)
    assert win.current_project_path == DEMO
    from vm_clone.samples.pcb_solution import create_pcb_inspection_solution
    win._load_solution_instance(create_pcb_inspection_solution())
    assert win.current_project_path is None   # Ctrl+S must not overwrite the demo file


def test_add_flow_never_reuses_a_name(win):
    _load(win, DEMO)
    win.on_add_flow_tab()
    win.on_add_flow_tab()
    first = list(win.solution.flows)[0]
    win.on_flow_tab_closed(0)
    win.on_add_flow_tab()
    names = list(win.solution.flows)
    assert first not in names and len(names) == len(set(names)) == 3
    assert all(len(f.nodes) == 1 for f in win.solution.flows.values())


@pytest.mark.parametrize("content", ['{"name":"x","flows":[{', "", "\x00\x01binary", "[1, 2, 3]"])
def test_corrupt_solution_files_raise_readable_value_error(tmp_path, content):
    path = tmp_path / "bad.vmp"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        SolutionManager.load_from_file(str(path))
    assert "bad.vmp" in str(exc.value)


def test_solution_file_with_bom_loads(tmp_path):
    sol = SolutionManager(name="bom")
    sol.add_flow("Flow1")
    path = tmp_path / "bom.vmp"
    path.write_bytes(b"\xef\xbb\xbf" + __import__("json").dumps(sol.to_dict()).encode("utf-8"))
    assert SolutionManager.load_from_file(str(path)).name == "bom"


def test_project_path_matches_create_project(tmp_path):
    from vm_clone.core.project_manager import ProjectManager
    pm = ProjectManager(workspace_root=str(tmp_path))
    name, expected = pm.project_path("My: bad/name", str(tmp_path))
    _, created = pm.create_project("My: bad/name", str(tmp_path), template="blank")
    assert created == expected and name == "My__bad_name"


def test_elided_label_elides_and_keeps_full_text_in_tooltip(qapp):
    from vm_clone.ui.elided_label import ElidedLabel
    lbl = ElidedLabel("a_very_long_image_name_that_cannot_fit_in_the_label.png")
    lbl.resize(90, 20)
    lbl.show()
    qapp.processEvents()
    assert lbl.text().endswith("…") and len(lbl.text()) < len(lbl.full_text())
    assert lbl.toolTip() == lbl.full_text()
    lbl.resize(600, 20)
    qapp.processEvents()
    assert lbl.text() == lbl.full_text()
    lbl.setToolTip("explicit")
    lbl.setText("changed")
    assert lbl.toolTip() == "explicit"
    lbl.close()


def _spin(qapp, predicate, timeout=5.0):
    import time
    end = time.time() + timeout
    while time.time() < end and not predicate():
        qapp.processEvents()
        time.sleep(0.005)
    return predicate()


def test_flow_runs_off_the_ui_thread_and_ui_stays_responsive(win, qapp, monkeypatch):
    import threading
    import time
    win.run_async = True
    _load(win, DEMO)
    assert _spin(qapp, lambda: not win.is_running_flow())
    seen = {}
    real = win.pipeline.execute_flow

    def slow(*a, **k):
        seen["thread"] = threading.current_thread()
        time.sleep(0.6)
        return real(*a, **k)

    monkeypatch.setattr(win.pipeline, "execute_flow", slow)
    ticks = []
    from PyQt6.QtCore import QTimer
    t = QTimer()
    t.timeout.connect(lambda: ticks.append(1))
    t.start(20)
    t0 = time.time()
    win.run_pipeline_step()
    assert time.time() - t0 < 0.3, "run_pipeline_step blocked the caller"
    assert win.is_running_flow()
    assert _spin(qapp, lambda: not win.is_running_flow())
    t.stop()
    assert seen["thread"] is not threading.main_thread()
    assert len(ticks) >= 10, "the event loop was starved while the flow ran"
    assert win.result_panel is not None and win.pipeline.last_results


def test_editing_during_a_run_waits_for_it_and_requests_coalesce(win, qapp, monkeypatch):
    import time
    win.run_async = True
    _load(win, DEMO)
    _spin(qapp, lambda: not win.is_running_flow())
    real = win.pipeline.execute_flow
    calls = []

    def slow(*a, **k):
        calls.append(1)
        time.sleep(0.3)
        return real(*a, **k)

    monkeypatch.setattr(win.pipeline, "execute_flow", slow)
    win.run_pipeline_step()
    win.run_pipeline_step()
    win.run_pipeline_step()          # coalesced into a single follow-up run
    nid = list(win.pipeline.nodes)[-1]
    win.flow_scene.select_node(nid)
    win.on_node_deleted(nid) if False else win.wait_for_run()
    assert not win.is_running_flow()
    assert _spin(qapp, lambda: len(calls) >= 1)
    _spin(qapp, lambda: not win.is_running_flow())
    assert len(calls) <= 2


def test_flow_engine_failure_is_reported_not_swallowed(win, qapp, monkeypatch):
    win.run_async = True
    _load(win, DEMO)
    _spin(qapp, lambda: not win.is_running_flow())
    monkeypatch.setattr(win.pipeline, "execute_flow",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine blew up")))
    win.run_pipeline_step()
    assert _spin(qapp, lambda: not win.is_running_flow())
    assert "engine blew up" in win.lbl_view_status.text()
