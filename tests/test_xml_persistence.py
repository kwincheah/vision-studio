"""Everything the application saves must round-trip through XML losslessly.

XML is the declarative, hand-/machine-editable representation of a solution, so it has to
carry exactly what the JSON project carries: flows, wiring, parameters of every type, node
layout, global variables and the global script.
"""
import glob
import json
import os

import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.pipeline import SolutionManager, VisionPipeline
from apex_vision.core.registry import create_tool_instance, list_all_tools

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECTS = sorted(glob.glob(os.path.join(ROOT, "projects", "*.vmp")))


def _canon(solution: SolutionManager) -> str:
    d = solution.to_dict()
    for f in d["flows"]:
        f.pop("execution_count", None)
    return json.dumps(d, sort_keys=True, default=str)


@pytest.mark.parametrize("path", PROJECTS, ids=[os.path.basename(p) for p in PROJECTS])
def test_demo_projects_round_trip_through_xml(path):
    original = SolutionManager.load_from_file(path)
    again = SolutionManager.from_xml(original.to_xml())
    assert _canon(again) == _canon(original)


@pytest.mark.parametrize("tool_name", sorted(list_all_tools()))
def test_every_tool_parameter_set_round_trips(tool_name):
    pipe = VisionPipeline("F")
    pipe.add_node(create_tool_instance(tool_name, "n1", "01_Tool"))
    back = VisionPipeline.from_xml(pipe.to_xml())
    assert back.nodes["n1"].parameters == pipe.nodes["n1"].parameters
    assert back.nodes["n1"].tool_name == tool_name


def test_awkward_values_survive_xml(tmp_path):
    sol = SolutionManager(name="Awkward <&> \"name\"")
    flow = sol.add_flow("Flow <1>")
    sol.active_flow_name = "Flow <1>"
    sol.trigger_flow_name = "Flow <1>"
    flow.add_node(create_tool_instance("Script", "s1", "Script & Co"))
    nasty = "line1\nline2\r\nTab\there  <tag attr=\"x\"> & ]]> 日本語 \x01 end  "
    flow.nodes["s1"].parameters["code"] = nasty
    flow.node_positions["s1"] = [12.5, -40.25]
    sol.global_variables = {"none": None, "t": True, "i": -3, "f": 1.5, "s": "  padded  ",
                            "empty": "", "lst": [1, "a", None], "d": {"k": [1, 2]}}
    sol.global_script = "def process(context):\n    context.set_global('x', 'é')\r\n"
    path = str(tmp_path / "awkward.xml")
    sol.save_to_file(path)
    back = SolutionManager.load_from_file(path)
    assert back.name == sol.name and back.active_flow_name == "Flow <1>"
    assert back.flows["Flow <1>"].nodes["s1"].name == "Script & Co"
    assert back.flows["Flow <1>"].nodes["s1"].parameters["code"] == nasty
    assert back.flows["Flow <1>"].node_positions["s1"] == [12.5, -40.25]
    assert back.global_variables == sol.global_variables
    assert back.global_script == sol.global_script


def test_xml_and_json_describe_the_same_solution(tmp_path):
    original = SolutionManager.load_from_file(PROJECTS[0])
    xml_path, json_path = str(tmp_path / "s.xml"), str(tmp_path / "s.json")
    original.save_to_file(xml_path)
    original.save_to_file(json_path)
    assert _canon(SolutionManager.load_from_file(xml_path)) == _canon(SolutionManager.load_from_file(json_path))
    assert open(xml_path, encoding="utf-8").read().lstrip().startswith("<?xml")


def test_single_flow_xml_still_loads_as_a_solution(tmp_path):
    pipe = SolutionManager.load_from_file(PROJECTS[0]).get_active_flow()
    path = str(tmp_path / "flow.xml")
    pipe.export_to_xml(path)
    sol = SolutionManager.load_from_file(path)
    assert list(sol.flows) == [pipe.name]
    assert sol.flows[pipe.name].node_positions == pipe.node_positions


@pytest.mark.parametrize("content", ["<VisionMasterSolution", "<Other/>", "<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'b'>]><x/>", ""])
def test_bad_xml_is_rejected_with_a_readable_error(tmp_path, content):
    path = tmp_path / "bad.xml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        SolutionManager.load_from_file(str(path))


def test_unknown_xml_tool_becomes_placeholder_and_keeps_its_parameters(tmp_path):
    xml = ('<?xml version="1.0"?><VisionMasterSolution name="x"><Flows>'
           '<VisionMasterFlow name="F"><Nodes><Node instance_id="a" tool_name="Future Tool" name="A">'
           '<Parameters><Parameter name="k" type="int">7</Parameter></Parameters></Node></Nodes>'
           '</VisionMasterFlow></Flows></VisionMasterSolution>')
    path = tmp_path / "f.xml"
    path.write_text(xml, encoding="utf-8")
    sol = SolutionManager.load_from_file(str(path))
    node = sol.flows["F"].nodes["a"]
    assert node.to_dict()["tool_name"] == "Future Tool"


def test_window_saves_and_reopens_xml_in_place(tmp_path):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from apex_vision.ui.main_window import VisionMasterMainWindow
    win = VisionMasterMainWindow()
    try:
        path = str(tmp_path / "ui.xml")
        win.current_project_path = path
        win.on_save_solution()
        assert open(path, encoding="utf-8").read().lstrip().startswith("<?xml")
        sol = win.project_manager.load_project(path)
        win.load_solution_manager(sol, filepath=path)
        assert not win.has_unsaved_changes()
        assert len(win.pipeline.nodes) == len(sol.get_active_flow().nodes)
    finally:
        win.close()
        win.deleteLater()
