"""Runtime global variables: a run must not look like an edit by the operator.

Globals are one shared, persisted namespace, so the same table holds settings the operator
tunes (g_SmallMax) and state a flow writes (g_Total, g_History).  Only the first kind is an
edit; a run writing the second is the machine working.  These tests pin both directions.
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from apex_vision.core.controller import ProjectState          # noqa: E402
from apex_vision.core.pipeline import SolutionManager        # noqa: E402

DEMO = os.path.join(ROOT, "projects", "Parts_Sorter_Demo.apex")


def _solution():
    from apex_vision.core.project_manager import ProjectManager
    return ProjectManager().load_project(DEMO)


# --------------------------------------------------------------------- the snapshot
def test_runtime_values_are_left_out_of_the_comparison():
    sol = _solution()
    sol.runtime_globals = {"g_Total"}
    sol.global_variables["g_Total"] = 1
    first = ProjectState.snapshot(sol)
    sol.global_variables["g_Total"] = 99
    assert ProjectState.snapshot(sol) == first, "a runtime value made the project look edited"


def test_settings_are_still_compared():
    sol = _solution()
    sol.runtime_globals = {"g_Total"}
    before = ProjectState.snapshot(sol)
    sol.global_variables["g_SmallMax"] = 4321
    assert ProjectState.snapshot(sol) != before


def test_marking_a_variable_is_itself_a_change():
    sol = _solution()
    sol.runtime_globals = set()
    before = ProjectState.snapshot(sol)
    sol.runtime_globals = {"g_Total"}
    assert ProjectState.snapshot(sol) != before, "the marks are part of the document"


def test_the_snapshot_does_not_mutate_the_solution():
    """`to_dict` hands back the live globals dict; filtering must copy, not delete."""
    sol = _solution()
    sol.runtime_globals = {"g_Total", "g_History"}
    names = set(sol.global_variables)
    ProjectState.snapshot(sol)
    assert set(sol.global_variables) == names


def test_dropping_a_mark_brings_the_value_back_into_the_comparison():
    sol = _solution()
    sol.runtime_globals = {"g_Total"}
    sol.global_variables["g_Total"] = 5
    ProjectState.snapshot(sol)
    base = ProjectState.snapshot(sol)
    sol.runtime_globals = set()
    assert ProjectState.snapshot(sol) != base


# --------------------------------------------------------------------- persistence
def test_the_runtime_mark_round_trips_through_the_file(tmp_path):
    from apex_vision.core.project_manager import ProjectManager
    sol = _solution()
    sol.runtime_globals = {"g_Total", "g_History"}
    out = tmp_path / "marks.apex"
    pm = ProjectManager()
    pm.save_project(sol, str(out))
    text = out.read_text(encoding="utf-8", errors="replace")
    assert 'runtime="true"' in text

    reloaded = pm.load_project(str(out))
    assert reloaded.runtime_globals == {"g_Total", "g_History"}
    assert "g_Total" in reloaded.global_variables, "the value must still be saved"


def test_a_project_without_marks_is_byte_identical(tmp_path):
    """Files that never used the feature must not gain an attribute."""
    from apex_vision.core.project_manager import ProjectManager
    pm = ProjectManager()
    sol = pm.load_project(DEMO)
    sol.runtime_globals = set()
    out = tmp_path / "plain.apex"
    pm.save_project(sol, str(out))
    assert 'runtime="true"' not in out.read_text(encoding="utf-8", errors="replace")


def test_a_mark_for_a_missing_variable_is_dropped_on_load(tmp_path):
    """A hand-edited file can name a variable that is not there."""
    from apex_vision.core.project_manager import ProjectManager
    pm = ProjectManager()
    sol = pm.load_project(DEMO)
    sol.runtime_globals = {"g_DoesNotExist"}
    out = tmp_path / "bad-mark.apex"
    pm.save_project(sol, str(out))
    assert "g_DoesNotExist" not in pm.load_project(str(out)).runtime_globals


def test_the_shipped_demo_marks_its_counters():
    sol = _solution()
    assert {"g_Total", "g_History", "g_CountOK", "g_CountNG"} <= sol.runtime_globals
    # ...and leaves the tuning values as settings
    assert not ({"g_SmallMax", "g_MinArea", "g_LotNumber"} & sol.runtime_globals)
