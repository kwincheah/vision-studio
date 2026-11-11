"""VisionMaster guide, Logic Tools: Group (modules that run together, optionally in a loop)."""
import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.pipeline import SolutionManager, VisionPipeline
from apex_vision.core.registry import create_tool_instance


def script(flow, name, code):
    t = create_tool_instance("Script", name, name)
    t.set_param("code", code)
    flow.add_node(t)
    return t


def group(flow, name="grp", **params):
    g = create_tool_instance("Group", name, name)
    for k, v in params.items():
        g.set_param(k, v)
    flow.add_node(g)
    return g


COUNT = "n = get_global('count', 0) + 1\nset_global('count', n)\noutputs['Result'] = n\n"


def run(flow, gv=None):
    gv = {} if gv is None else gv
    return flow.execute_flow(global_vars=gv), gv


def test_members_run_once_without_a_loop_and_the_group_reports_them():
    f = VisionPipeline("F")
    group(f)
    script(f, "a", COUNT)
    script(f, "b", COUNT)
    assert f.set_group("a", "grp") and f.set_group("b", "grp")
    res, gv = run(f)
    assert gv["count"] == 2 and res["grp"].status == ToolStatus.OK and res["grp"].outputs["Loops"] == 1 and "2 module" in res["grp"].message
    assert f.group_members("grp") == ["a", "b"]
    assert f.execution_order.index("grp") < f.execution_order.index("a")


def test_a_loop_runs_the_members_for_each_number():
    f = VisionPipeline("F")
    group(f, loop_enable=True, loop_start=2, loop_end=7)
    script(f, "a", "seen = get_global('seen', [])\nseen.append(context.get('Val1'))\nset_global('seen', seen)\nset_global('count', get_global('count', 0) + 1)\n")
    f.set_group("a", "grp")
    assert f.connect("grp", "Cycle", "a", "Val1")
    res, gv = run(f)
    assert gv["count"] == 5 and gv["seen"] == [2, 3, 4, 5, 6] and res["grp"].outputs["Loops"] == 5 and res["grp"].outputs["Cycle"] == 6
    again = run(f, gv)[1]
    assert again["count"] == 10, "every run of the flow loops again"


def test_modules_after_the_group_see_the_last_pass_and_those_before_feed_it():
    f = VisionPipeline("F")
    script(f, "before", "outputs['Result'] = 10\n")
    group(f, loop_enable=True, loop_start=0, loop_end=4)
    script(f, "inner", "outputs['Result'] = context['Val1'] + context['Val2']\n")
    script(f, "after", "set_global('final', context['Val1'])\noutputs['Result'] = 0\n")
    f.set_group("inner", "grp")
    assert f.connect("before", "Result", "inner", "Val1") and f.connect("grp", "Cycle", "inner", "Val2") and f.connect("inner", "Result", "after", "Val1")
    order = f.execution_order
    assert order.index("before") < order.index("grp") < order.index("inner") < order.index("after")
    res, gv = run(f)
    assert gv["final"] == 13, "10 + the last loop number (3)"


def test_the_break_condition_ends_the_loop_early():
    f = VisionPipeline("F")
    group(f, loop_enable=True, loop_start=0, loop_end=50, break_enable=True, compare_type="Int", break_when=">=", base_value="0", target_value="3")
    script(f, "a", "set_global('count', get_global('count', 0) + 1)\noutputs['Result'] = context.get('Val1', 0)\n")
    f.set_group("a", "grp")
    assert f.connect("a", "Result", "grp", "Base")
    f.connect("grp", "Cycle", "a", "Val1")
    res, gv = run(f)
    assert res["grp"].outputs["Broke"] is True and gv["count"] == 4, "the module's result reached 3 on the pass numbered 3"
    assert "break condition" in res["grp"].message
    never = VisionPipeline("G")
    group(never, loop_enable=True, loop_end=3, break_enable=True, base_value="1", target_value="2", break_when="==")
    script(never, "a", COUNT)
    never.set_group("a", "grp")
    r2, g2 = run(never)
    assert g2["count"] == 3 and r2["grp"].outputs["Broke"] is False
    texty = VisionPipeline("H")
    group(texty, loop_enable=True, loop_end=9, break_enable=True, compare_type="String", break_when="==", base_value="stop", target_value="stop")
    script(texty, "a", COUNT)
    texty.set_group("a", "grp")
    assert run(texty)[1]["count"] == 1, "strings can be compared for equality"
    bad = VisionPipeline("I")
    group(bad, loop_enable=True, loop_end=3, break_enable=True, compare_type="Int", base_value="x", target_value="1")
    script(bad, "a", COUNT)
    bad.set_group("a", "grp")
    assert run(bad)[1]["count"] == 3, "a value that is not a number never breaks"


def test_the_group_takes_the_worst_result():
    f = VisionPipeline("F")
    group(f)
    script(f, "ok_", "outputs['Status'] = 'OK'\n")
    script(f, "bad", "outputs['Status'] = 'NG'\n")
    f.set_group("ok_", "grp")
    f.set_group("bad", "grp")
    res, _ = run(f)
    assert res["grp"].status == ToolStatus.NG
    boom = VisionPipeline("G")
    group(boom)
    script(boom, "x", "raise ValueError('no')\n")
    boom.set_group("x", "grp")
    assert run(boom)[0]["grp"].status == ToolStatus.ERROR


def test_a_disabled_group_bypasses_its_modules():
    off = VisionPipeline("H")
    g = group(off, loop_enable=True, loop_end=4)
    script(off, "a", COUNT)
    off.set_group("a", "grp")
    g.enabled = False
    res, gv = run(off)
    assert gv.get("count") is None and res["grp"].status == ToolStatus.BYPASS and res["a"].status == ToolStatus.BYPASS


def test_groups_cannot_nest_and_membership_rules():
    f = VisionPipeline("F")
    group(f, "g1")
    group(f, "g2")
    script(f, "a", COUNT)
    assert f.set_group("a", "g1") and not f.set_group("g2", "g1"), "a Group cannot go inside a Group"
    assert not f.set_group("a", "a") and not f.set_group("a", "nope") and not f.set_group("nope", "g1")
    assert f.set_group("a", "g2") and f.group_of("a") == "g2"
    assert f.set_group("a", "") and f.group_of("a") == ""
    f.set_group("a", "g1")
    f.remove_node("g1")
    assert f.nodes["a"].group == "" and f.group_of("a") == "", "removing the group frees its modules"


def test_membership_survives_saving_in_both_formats():
    f = VisionPipeline("F")
    group(f, loop_enable=True, loop_end=2)
    script(f, "a", COUNT)
    f.set_group("a", "grp")
    back = VisionPipeline.from_xml(f.to_xml())
    assert back.nodes["a"].group == "grp" and back.group_members("grp") == ["a"] and back.nodes["grp"].get_param("loop_enable") is True
    sol = SolutionManager()
    sol.flows = {"F": f}
    sol.active_flow_name = sol.trigger_flow_name = "F"
    again = SolutionManager.from_xml(sol.to_xml())
    assert again.flows["F"].nodes["a"].group == "grp"
    clone = VisionPipeline.from_dict(f.to_dict())
    assert clone.nodes["a"].group == "grp"
    other = script(f, "b", COUNT)
    assert "group" not in other.to_dict(), "modules outside a group save exactly what they did before"


def test_a_flow_without_groups_runs_exactly_as_before():
    f = VisionPipeline("F")
    script(f, "a", COUNT)
    script(f, "b", "outputs['Result'] = context['Val1'] * 2\n")
    assert f.connect("a", "Result", "b", "Val1")
    assert f.execution_order == ["a", "b"]
    res, gv = run(f)
    assert res["b"].outputs["Result"] == 2 and gv["count"] == 1


def test_the_flow_timeout_stops_a_long_loop():
    f = VisionPipeline("F")
    f.flow_timeout_ms = 300.0
    group(f, loop_enable=True, loop_end=100000, interval_ms=50)
    script(f, "a", COUNT)
    f.set_group("a", "grp")
    res, gv = run(f)
    assert 1 <= gv["count"] < 100, "the loop is cut off by the flow timeout instead of running for ever"


def test_progress_is_reported_for_the_modules_in_a_group():
    f = VisionPipeline("F")
    group(f, loop_enable=True, loop_end=2)
    script(f, "a", COUNT)
    f.set_group("a", "grp")
    seen = []
    f.execute_flow(global_vars={}, on_step_callback=lambda nid, r: seen.append(nid))
    assert seen.count("a") == 2 and seen.count("grp") == 1 and seen[-1] == "grp"
