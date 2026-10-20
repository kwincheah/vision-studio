"""Every module parameter has the right kind of editor (checkbox / drop-down / number with limits / region / path /
text), the drop-down values are exactly the ones the tools understand, and the backend refuses what a parameter
cannot hold.  Part of the review of all 42 modules."""
import numpy as np
import pytest

import vm_clone.tools  # noqa: F401
from vm_clone.core import param_schema as ps
from vm_clone.core.base_tool import ToolStatus
from vm_clone.core.registry import create_tool_instance, list_all_tools

TOOLS = sorted(list_all_tools())
# free-text parameters that were reviewed one by one: there is no fixed set of values to offer
REVIEWED_TEXT = {"target_branches", "server_ip", "prefix", "suffix", "target_text", "stream_url", "expected_pattern", "classes"}


def all_params():
    for name in TOOLS:
        tool = create_tool_instance(name, "t")
        for key, default in tool.parameters.items():
            yield name, key, default


def test_every_schema_entry_names_a_real_parameter_of_a_real_tool():
    for name, entries in ps.SCHEMA.items():
        assert name in TOOLS, name
        params = create_tool_instance(name, "t").parameters
        for key in entries:
            assert key in params, f"{name}.{key} is in the schema but the tool has no such parameter"


def test_every_default_value_is_accepted_by_its_own_editor():
    for name, key, default in all_params():
        assert ps.problem(name, key, default, default) is None, (name, key, default, ps.problem(name, key, default, default))


def test_no_parameter_is_left_to_free_typing_by_accident():
    """Strings are drop-downs, paths or code unless they were reviewed as genuinely free text; numbers are bounded."""
    unreviewed = []
    for name, key, default in all_params():
        spec = ps.spec_for(name, key, default)
        if spec["kind"] == "text" and key not in REVIEWED_TEXT:
            unreviewed.append((name, key, default))
        if spec["kind"] == "json":
            unreviewed.append((name, key, default))
        if spec["kind"] in ("int", "float") and not ("min" in spec and "max" in spec) and key not in (
                "threshold_low", "threshold_high", "min_val", "max_val", "scale_factor", "default_a", "default_b",
                "fiducial_x", "fiducial_y", "manual_k1", "manual_k2", "manual_p1", "manual_p2", "target_value"):
            unreviewed.append((name, key, "unbounded number"))
    assert not unreviewed, unreviewed


def test_every_dropdown_contains_its_default_and_has_no_duplicates():
    for name, key, default in all_params():
        spec = ps.spec_for(name, key, default)
        if spec["kind"] in ("enum", "combo"):
            assert default in spec["choices"], (name, key, default, spec["choices"])
            assert len(spec["choices"]) == len(set(spec["choices"])), (name, key)
            assert len(spec["choices"]) >= 2 or (name, key) == ("PCB Defect Detection", "variant"), (name, key)   # one detector variant exists today


def test_the_kinds_follow_the_values():
    kind = lambda n, k: ps.spec_for(n, k, create_tool_instance(n, "t").parameters[k])["kind"]
    assert kind("Image Binarization", "invert") == "bool"
    assert kind("Image Binarization", "method") == "enum"
    assert kind("Template Match", "template_roi") == "rect"
    assert kind("Caliper", "line_p1") == "point"
    assert kind("L2L Measure", "default_l1") == "line"
    assert kind("N-Point Calibration", "pixel_points") == "points"
    assert kind("Color Measurement", "target_rgb") == "rgb"
    assert kind("Script", "code") == "code"
    assert kind("Image Source", "file_path") == "path"
    assert kind("Image Output", "save_directory") == "dir"
    assert kind("Image Source", "camera_device") == "device"
    assert kind("Trigger", "target_flow") == "flow"
    assert kind("Defect Detection", "defect_type") == "combo"
    assert kind("TCP Send", "server_port") == "int"
    assert ps.spec_for("TCP Send", "server_port", 8080)["max"] == 65535


@pytest.mark.parametrize("tool_name", TOOLS)
def test_every_dropdown_choice_runs_without_crashing_the_tool(tool_name):
    """A drop-down must only offer values the tool handles: run the tool once per choice."""
    tool = create_tool_instance(tool_name, "t")
    img = np.full((120, 160, 3), 90, np.uint8)
    img[30:90, 40:120] = 200
    for key, default in tool.parameters.items():
        spec = ps.spec_for(tool_name, key, default)
        if spec["kind"] not in ("enum", "combo") or tool_name in ("TCP Send", "Camera IO", "Image Output", "Object Detection"):
            continue
        for choice in spec["choices"]:
            t = create_tool_instance(tool_name, "t")
            t.set_param(key, choice)
            assert t.parameters[key] == choice, f"{tool_name}.{key}: the tool rejected its own drop-down value {choice!r}"
            if tool_name in ("Image Source",):                      # would open files / cameras
                continue
            result = t.execute({"Image": img})
            assert result.status != ToolStatus.ERROR or "unavailable" in result.message.lower() or "not installed" in result.message.lower(), \
                (tool_name, key, choice, result.message)


def test_caliper_polarity_choices_really_select_the_edge_direction():
    """Regression: the editor offered 'Dark to light' but the tool compared 'Dark to Light', so the choice was ignored."""
    img = np.zeros((60, 200, 3), np.uint8)
    img[:, 100:] = 255                                           # a dark -> light edge at x = 100, going left to right

    def width(polarity):
        t = create_tool_instance("Caliper", "c")
        t.set_param("line_p1", [10, 30])
        t.set_param("line_p2", [190, 30])
        t.set_param("caliper_mode", "Single Edge")
        t.set_param("polarity", polarity)
        r = t.execute({"Image": img})
        return r.status, r.outputs.get("Edge1")

    ok_status, ok_edge = width("Dark to light")
    bad_status, bad_edge = width("Light to dark")
    any_status, any_edge = width("Any")
    assert ok_edge is not None and any_edge is not None
    assert bad_edge is None or bad_status != ok_status, "'Light to dark' must not find a dark-to-light edge"
    assert width("Dark to Light")[1] is not None, "older project files wrote 'Dark to Light'"


def test_clamp_and_problem_rules():
    spec = ps.spec_for("Template Match", "min_score", 0.65)
    assert ps.clamp(spec, 7) == 1 and ps.clamp(spec, -3) == 0 and ps.clamp(spec, 0.5) == 0.5
    spec = ps.spec_for("TCP Send", "server_port", 8080)
    assert ps.clamp(spec, 99999.4) == 65535 and isinstance(ps.clamp(spec, 80.0), int)
    assert ps.problem("Image Filter", "filter_type", "Gaussian", "Box") and ps.problem("Image Filter", "filter_type", "Gaussian", "Median") is None
    assert ps.problem("Template Match", "template_roi", [1, 2, 3, 4], [1, 2, 3]) and ps.problem("Template Match", "template_roi", [1, 2, 3, 4], [1, 2, 3, 4]) is None
    assert ps.problem("Color Measurement", "target_rgb", [0, 150, 0], [0, 300, 0]) and ps.problem("Image Binarization", "invert", False, "yes")
    assert ps.problem("Circle/Line Fit", "default_points", [[1, 2]], [[1, 2], [3]])


# ---------------------------------------------------------------- the backend slots
@pytest.fixture
def backend():
    from PyQt6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])
    from vm_clone.core.pipeline import SolutionManager
    from vm_clone.qml_backend import AppBackend, FrameProvider
    from vm_clone.samples.pcb_solution import create_pcb_inspection_solution
    b = AppBackend(FrameProvider())
    sol = SolutionManager(name="S")
    sol.flows["F"] = create_pcb_inspection_solution()
    sol.flows["F"].name = "F"
    sol.active_flow_name = "F"
    b.load_solution(sol, None)
    b.engine.wait_for_run()
    return b


def node(b, tool):
    return next(n for n in b._pipeline.nodes.values() if n.tool_name == tool)


def test_moduleparams_describes_each_parameter_for_its_editor(backend):
    cal = node(backend, "Caliper")
    rows = {r["name"]: r for r in backend.moduleParams(cal.instance_id)}
    assert rows["polarity"]["kind"] == "enum" and rows["polarity"]["choices"] == ["Any", "Dark to light", "Light to dark"]
    assert rows["line_p1"]["kind"] == "point" and rows["line_p1"]["native"] == [50, 150]
    assert rows["edge_threshold"]["kind"] == "float" and rows["edge_threshold"]["max"] == 255
    assert rows["polarity"]["label"] == "Polarity" and rows["polarity"]["value"] == "Any"
    trig = backend.moduleParams(node(backend, "TCP Send").instance_id)
    assert next(r for r in trig if r["name"] == "mode")["choices"] == ["Simulation (Loopback Log)", "TCP Client"]


def test_trigger_target_flow_offers_the_flows_that_exist(backend):
    backend.addFlow()
    backend.engine.wait_for_run()
    from vm_clone.core.registry import create_tool_instance as mk
    trig = mk("Trigger", "trg")
    backend._pipeline.add_node(trig)
    row = next(r for r in backend.moduleParams("trg") if r["name"] == "target_flow")
    assert row["kind"] == "flow" and set(row["choices"]) == set(backend._solution.flows) and len(row["choices"]) >= 2


def test_setparamvalue_clamps_validates_and_is_undoable(backend):
    tm = node(backend, "Template Match")
    nid = tm.instance_id
    assert backend.setParamValue(nid, "min_score", 5.0) and tm.parameters["min_score"] == 1.0          # clamped to the limit
    assert backend.setParamValue(nid, "template_roi", [10, 20, 30, 40]) and tm.parameters["template_roi"] == [10, 20, 30, 40]
    assert not backend.setParamValue(nid, "template_roi", [1, 2]) and tm.parameters["template_roi"] == [10, 20, 30, 40]
    assert "must be 4 numbers" in backend.hint
    filt = node(backend, "Defect Detection")
    assert not backend.setParamValue(filt.instance_id, "defect_type", 5)
    cal = node(backend, "Caliper")
    assert not backend.setParamValue(cal.instance_id, "polarity", "Sideways") and cal.parameters["polarity"] == "Any"
    assert backend.setParamValue(cal.instance_id, "polarity", "Dark to light") and cal.parameters["polarity"] == "Dark to light"
    backend.undo()
    assert node(backend, "Caliper").parameters["polarity"] == "Any"            # undo rebuilds the flow: look the module up again
    tm = node(backend, "Template Match")
    nid = tm.instance_id
    assert not backend.setParamValue("nope", "x", 1)
    backend.setRole("Operator")
    assert not backend.setParamValue(nid, "min_score", 0.2) and tm.parameters["min_score"] == 1.0
    backend.setRole("Engineer")


def test_whole_number_parameters_round_and_text_setparam_still_works(backend):
    circ = node(backend, "Circle Search")
    assert backend.setParamValue(circ.instance_id, "min_radius", 21.6) and circ.parameters["min_radius"] == 22 and isinstance(circ.parameters["min_radius"], int)
    backend.setParam(circ.instance_id, "max_radius", "70")
    assert circ.parameters["max_radius"] == 70
