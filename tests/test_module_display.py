"""The Display Setup of a module: persists, defaults safely, and never appears uninvited."""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from apex_vision.core.registry import create_tool_instance   # noqa: E402


def _new_tool():
    return create_tool_instance("BLOB Analysis", "disp1", "QA")


def test_a_module_starts_with_the_default_display():
    tool = _new_tool()
    assert tool.display == {"roi": True, "labels": True, "boxes": True,
                            "colour": "#e4b030"}


def test_the_default_is_not_written_into_the_project():
    """An untouched module must serialise exactly as before, or every project would
    suddenly report unsaved changes and every file would grow a display block."""
    tool = _new_tool()
    assert "display" not in tool.to_dict()


def test_a_changed_display_is_written():
    tool = _new_tool()
    tool.display = {**tool.display, "colour": "#2b7bb9"}
    assert tool.to_dict()["display"]["colour"] == "#2b7bb9"


def test_a_display_round_trips_through_load_dict():
    tool = _new_tool()
    tool.load_dict({"display": {"roi": False, "labels": True, "boxes": False,
                                "colour": "#e0585c"}})
    assert tool.display == {"roi": False, "labels": True, "boxes": False,
                            "colour": "#e0585c"}


@pytest.mark.parametrize("stored,expected", [
    (None, {"roi": True, "labels": True, "boxes": True, "colour": "#e4b030"}),
    ("nonsense", {"roi": True, "labels": True, "boxes": True, "colour": "#e4b030"}),
    ({"roi": "yes"}, {"roi": True, "labels": True, "boxes": True, "colour": "#e4b030"}),
    ({"colour": "#GGGGGG"}, {"roi": True, "labels": True, "boxes": True,
                             "colour": "#e4b030"}),
    ({"labels": False}, {"roi": True, "labels": False, "boxes": True,
                         "colour": "#e4b030"}),
])
def test_a_bad_display_block_falls_back_to_the_default(stored, expected):
    """A hand-edited file must not be able to put rubbish into the renderer."""
    from apex_vision.core.base_tool import VisionToolBase
    assert VisionToolBase._coerce_display(stored) == expected


def test_a_valid_colour_is_normalised_to_lower_case():
    from apex_vision.core.base_tool import VisionToolBase
    assert VisionToolBase._coerce_display({"colour": "#2B7BB9"})["colour"] == "#2b7bb9"


def _demo():
    demo = os.path.join(ROOT, "projects", "PCB_Inspection_Demo.apex")
    if not os.path.exists(demo):
        pytest.skip("demo project not present")
    from apex_vision.core.project_manager import ProjectManager
    return ProjectManager().load_project(demo)


def test_saving_an_untouched_project_adds_no_display_element(tmp_path):
    """Round-trip a shipped project and confirm its XML gains no <Display> element."""
    solution = _demo()
    out = tmp_path / "untouched.apex"
    from apex_vision.core.project_manager import ProjectManager
    ProjectManager().save_project(solution, str(out))
    text = out.read_text(encoding="utf-8", errors="replace")
    assert "<Display" not in text, (
        "a project whose display was never edited gained a <Display> element")


def test_a_changed_display_survives_save_and_reload(tmp_path):
    solution = _demo()
    pipe = solution.get_active_flow()
    node = next(iter(pipe.nodes.values()))
    node.display = {**node.display, "roi": False, "colour": "#2b7bb9"}

    out = tmp_path / "changed.apex"
    from apex_vision.core.project_manager import ProjectManager
    pm = ProjectManager()
    pm.save_project(solution, str(out))
    text = out.read_text(encoding="utf-8", errors="replace")
    assert "<Display" in text

    reloaded = pm.load_project(str(out))
    node2 = reloaded.get_active_flow().nodes.get(node.instance_id)
    assert node2 is not None
    assert node2.display["roi"] is False
    assert node2.display["colour"] == "#2b7bb9"
