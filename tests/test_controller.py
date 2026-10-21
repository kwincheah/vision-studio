"""The shared controller (apex_vision/core/controller.py) is front-end independent: these tests drive it
with no widget and no QML, exactly as both user interfaces do."""
import os
import time

import cv2
import numpy as np
import pytest
from PyQt6.QtCore import QCoreApplication

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.controller import ImagePool, ProjectState, RunEngine, natural_key
from apex_vision.core.pipeline import SolutionManager
from apex_vision.core.project_manager import ProjectManager
from apex_vision.core.registry import create_tool_instance

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEMO = os.path.join(ROOT, "projects", "Precision_Measurement_Demo.vmp")


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def spin(app, predicate, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end and not predicate():
        app.processEvents()
        time.sleep(0.003)
    return predicate()


def make_images(folder, count=3):
    paths = []
    for i in range(count):
        p = folder / f"img{i + 1}.png"
        cv2.imwrite(str(p), np.full((30, 40, 3), 40 * i + 10, np.uint8))
        paths.append(str(p))
    return paths


def make_engine(app, n_images=3, tmp_path=None, async_=True, **kw):
    sol = SolutionManager.load_from_file(DEMO)
    pool = ImagePool()
    if n_images:
        for p in make_images(tmp_path, n_images):
            pool.add_path(p)
        pool.index = 0
    engine = RunEngine(lambda: sol.get_active_flow(), lambda: sol, pool, is_async=lambda: async_,
                       interval_ms=lambda: 1, **kw)
    return engine, sol, pool


# --------------------------------------------------------------------------- image pool
def test_pool_adds_decodes_and_orders_a_folder_naturally(tmp_path):
    for name in ("a10.png", "a2.png", "a1.png"):
        cv2.imwrite(str(tmp_path / name), np.zeros((8, 8, 3), np.uint8))
    (tmp_path / "x.txt").write_text("no")
    (tmp_path / "bad.png").write_bytes(b"junk")
    pool = ImagePool()
    added, skipped, failed = pool.add_folder(str(tmp_path))
    assert (added, skipped, failed) == (3, 0, 1)
    assert pool.names == ["a1.png", "a2.png", "a10.png"] and pool.index == 0
    assert sorted(["a10", "a2", "a1"], key=natural_key) == ["a1", "a2", "a10"]
    assert pool.add_path(str(tmp_path / "missing.png"))[0] is None
    again, _ = pool.add_path(str(tmp_path / "a2.png"))
    assert again == 1 and len(pool) == 3                       # same file does not duplicate
    with pytest.raises(OSError):
        pool.add_folder(str(tmp_path / "nope"))


def test_pool_feeds_the_image_source(tmp_path):
    pool = ImagePool()
    paths = make_images(tmp_path, 2)
    for p in paths:
        pool.add_path(p)
    sol = SolutionManager.load_from_file(DEMO)
    pipe = sol.get_active_flow()
    assert pool.apply_to(pipe, 1)
    src = next(n for n in pipe.nodes.values() if n.tool_name == "Image Source")
    assert src.parameters["file_path"] == os.path.abspath(paths[1]) and pool.index == 1
    assert src._override_name == "img2.png"
    assert not pool.apply_to(pipe, 9)


# --------------------------------------------------------------------------- run engine
def test_single_run_is_asynchronous_and_reports_once(app, tmp_path):
    engine, sol, pool = make_engine(app, 0)
    seen, started = [], []
    engine.cycle_finished.connect(seen.append)
    engine.cycle_started.connect(lambda: started.append(1))
    engine.request_run()
    assert engine.busy and started
    assert spin(app, lambda: not engine.busy)
    assert len(seen) == 1 and seen[0]["results"] and not seen[0]["failure"]


def test_requests_during_a_run_coalesce_into_one_follow_up(app, tmp_path, monkeypatch):
    engine, sol, pool = make_engine(app, 0)
    pipe = sol.get_active_flow()
    real, calls = pipe.execute_flow, []
    monkeypatch.setattr(pipe, "execute_flow", lambda *a, **k: (calls.append(1), time.sleep(0.2), real(*a, **k))[2])
    engine.request_run()
    engine.request_run()
    engine.request_run()
    assert spin(app, lambda: len(calls) >= 2 and not engine.busy)
    time.sleep(0.3)
    app.processEvents()
    assert len(calls) == 2


def test_wait_for_run_delivers_the_result_before_returning(app):
    engine, sol, pool = make_engine(app, 0)
    seen = []
    engine.cycle_finished.connect(seen.append)
    engine.request_run()
    engine.wait_for_run()
    assert not engine.busy and len(seen) == 1


def test_engine_failure_is_a_payload_not_a_crash(app, monkeypatch):
    engine, sol, pool = make_engine(app, 0)
    monkeypatch.setattr(sol.get_active_flow(), "execute_flow",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    seen = []
    engine.cycle_finished.connect(seen.append)
    engine.request_run()
    assert spin(app, lambda: seen)
    assert "boom" in seen[0]["failure"] and seen[0]["results"] == {}


def test_run_all_visits_every_image_once_and_summarises(app, tmp_path):
    engine, sol, pool = make_engine(app, 3, tmp_path)
    picks, done = [], []
    engine.image_selected.connect(picks.append)
    engine.run_finished.connect(done.append)
    assert engine.start_strip_run("Run all", loop=False) == "batch"
    assert engine.is_strip_busy()
    assert spin(app, lambda: done)
    assert picks == [0, 1, 2]
    assert "3 image(s)" in done[0] and not engine.is_strip_busy()


def test_loop_repeats_until_stop_and_stop_waits_for_the_cycle(app, tmp_path, monkeypatch):
    engine, sol, pool = make_engine(app, 2, tmp_path)
    picks = []
    engine.image_selected.connect(picks.append)
    engine.start_strip_run("Run all", loop=True)
    assert spin(app, lambda: len(picks) >= 5)
    assert picks[:5] == [0, 1, 0, 1, 0]                        # pass after pass, in order
    assert engine.show_as_running() == (True, False)
    pipe = sol.get_active_flow()
    real = pipe.execute_flow
    monkeypatch.setattr(pipe, "execute_flow", lambda *a, **k: (time.sleep(0.4), real(*a, **k))[1])
    assert spin(app, lambda: engine.busy)
    engine.stop()
    assert engine.show_as_running() == (True, True)            # 'Stopping...' while the cycle finishes
    assert spin(app, lambda: not engine.busy)
    assert spin(app, lambda: engine.show_as_running() == (False, False))
    n = len(picks)
    spin(app, lambda: False, timeout=0.15)
    assert len(picks) == n                                      # nothing further was scheduled


def test_loop_with_run_selected_repeats_the_current_image(app, tmp_path):
    engine, sol, pool = make_engine(app, 3, tmp_path)
    pool.index = 1
    picks = []
    engine.image_selected.connect(picks.append)
    engine.start_strip_run("Run selected", loop=True)
    assert spin(app, lambda: len(picks) >= 3)
    engine.stop()
    assert set(picks[:3]) == {1}


def test_single_scope_runs_once_and_clears_the_busy_flag(app, tmp_path):
    engine, sol, pool = make_engine(app, 3, tmp_path)
    assert engine.start_strip_run("Single step", loop=False) == "single"
    assert spin(app, lambda: not engine.busy and not engine.is_strip_busy())


def test_stop_on_ng_halts_a_batch(app, tmp_path, monkeypatch):
    engine, sol, pool = make_engine(app, 3, tmp_path)
    pipe = sol.get_active_flow()
    pipe.stop_on_ng = True
    monkeypatch.setattr(RunEngine, "payload_ok", staticmethod(lambda payload: False))
    done = []
    engine.run_finished.connect(done.append)
    engine.start_strip_run("Run all", loop=True)
    assert spin(app, lambda: done)
    assert "NG" in done[0] and engine.batch is None and not engine.is_strip_busy()


def test_continuous_ticks_cycle_images_only_with_loop_and_run_all(app, tmp_path):
    engine, sol, pool = make_engine(app, 3, tmp_path, async_=False)
    seen = []
    for _ in range(4):
        engine.tick("Run all", loop=True)
        seen.append(pool.index)
    assert seen == [0, 1, 2, 0]                                 # first tick uses the current image
    keep = pool.index
    engine.tick("Run all", loop=False)
    engine.tick("Run selected", loop=True)
    assert pool.index == keep
    engine.reset_ticks()
    engine.tick("Run all", loop=True)
    assert pool.index == keep                                   # restart: first tick re-uses it


def test_sync_mode_runs_inline(app):
    engine, sol, pool = make_engine(app, 0, async_=False)
    seen = []
    engine.cycle_finished.connect(seen.append)
    engine.request_run()
    assert len(seen) == 1 and not engine.busy


# --------------------------------------------------------------------------- project state
def test_project_state_tracks_changes_and_round_trips_xml(app, tmp_path):
    pm = ProjectManager(workspace_root=str(tmp_path))
    state = ProjectState(pm)
    sol = SolutionManager.load_from_file(DEMO)
    state.mark_saved(sol)
    assert not state.is_dirty(sol)
    sol.global_variables["g_new"] = 1
    assert state.is_dirty(sol)
    flushed = []
    path = str(tmp_path / "out.xml")
    state.save(sol, path, before=lambda: flushed.append(1))
    assert flushed and state.path == path and not state.is_dirty(sol)
    assert open(path, encoding="utf-8").read().lstrip().startswith("<?xml")
    again = state.open(path)
    assert again.global_variables["g_new"] == 1
    with pytest.raises(Exception):
        (tmp_path / "bad.vmp").write_text("{oops", encoding="utf-8")
        state.open(str(tmp_path / "bad.vmp"))


def test_snapshot_ignores_execution_counters_and_survives_bad_input():
    sol = SolutionManager.load_from_file(DEMO)
    before = ProjectState.snapshot(sol)
    sol.get_active_flow().execution_count += 5
    assert ProjectState.snapshot(sol) == before

    class Broken:
        def to_dict(self):
            raise RuntimeError("no")
    assert ProjectState.snapshot(Broken()) is None
