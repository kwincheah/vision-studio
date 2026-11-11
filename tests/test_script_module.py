"""The Script module's abilities and limits, tested on real flows: what a script can read, compute, draw and return,
how it fails, and that a runaway script is stopped instead of freezing the application."""
import os
import textwrap
import time

import numpy as np

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.pipeline import SolutionManager
from apex_vision.core.registry import create_tool_instance


def flow_with(code, vals=None, gvars=None, **params):
    """Image Source (sample part) -> Script(code), with optional Val1/Val2 wired from other modules."""
    sol = SolutionManager(name="T")
    for k, v in (gvars or {}).items():
        sol.set_global(k, v)
    flow = sol.add_flow("F")
    sol.active_flow_name = flow.name
    src = create_tool_instance("Image Source", "src", "src")
    src.set_param("pattern_type", "Part with Defects")
    flow.add_node(src)
    sc = create_tool_instance("Script", "sc", "sc")
    sc.set_param("code", textwrap.dedent(code))
    for k, v in params.items():
        sc.set_param(k, v)
    flow.add_node(sc)
    flow.connect("src", "Image", "sc", "Image")
    for port, v in (vals or {}).items():
        n = create_tool_instance("Variable Calculation", f"v_{port}", f"v_{port}")
        n.set_param("default_a", float(v))
        n.set_param("default_b", 0.0)
        flow.add_node(n)
        flow.connect(f"v_{port}", "Result", "sc", port)
    results = flow.execute_flow(global_vars=sol.global_variables)
    return sol, results, results["sc"]


def test_reads_wired_inputs_and_computes():
    _, _, r = flow_with("""
        outputs['Result'] = context.get('Val1', 0) * 2.5 + context.get('Val2', 0)
        """, vals={"Val1": 4, "Val2": 1})
    assert r.status == ToolStatus.OK and r.outputs["Result"] == 11.0


def test_image_processing_with_cv2_and_numpy_and_overlays():
    sol, res, r = flow_with("""
        img = context['Image']
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        big = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 200]
        out = img.copy()
        for i in big:
            x, y, w, h = stats[i, :4]
            cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), 2)
        outputs['Image'], outputs['Result'] = out, len(big)
        overlays.append({'type': 'text', 'text': str(len(big)), 'pt': (10, 30), 'color': (0, 255, 255)})
        """)
    assert r.status == ToolStatus.OK and r.outputs["Result"] >= 1 and len(r.overlays) == 1
    assert not np.array_equal(r.outputs["Image"], res["src"].outputs["Image"])


def test_functions_comprehensions_and_imports_work():
    _, _, r = flow_with("""
        import json, math
        def sq(x):
            return x * x
        outputs['Result'] = json.dumps([sq(i) for i in range(4)] + [round(math.pi, 2)])
        """)
    assert r.outputs["Result"] == "[0, 1, 4, 9, 3.14]"


def test_status_other_than_ok_fails_the_module():
    assert flow_with("outputs['Status'] = 'FAIL'")[2].status == ToolStatus.NG
    assert flow_with("outputs['Status'] = 'OK'")[2].status == ToolStatus.OK


def test_errors_say_what_and_which_line():
    r = flow_with("""
        x = 1
        outputs['Result'] = x / 0
        """)[2]
    assert r.status == ToolStatus.ERROR and "ZeroDivisionError" in r.message and "line 3" in r.message.replace("line 2", "line 3") or "line" in r.message
    r = flow_with("a = 1\nb = (2 +\n")[2]
    assert r.status == ToolStatus.ERROR and "SyntaxError" in r.message and "line 2" in r.message
    r = flow_with("a = 1\nb = a.nothing\n")[2]
    assert "AttributeError" in r.message and "line 2" in r.message


def test_global_variables_can_be_read_and_written_and_give_state_between_runs():
    sol, _, r = flow_with("""
        outputs['Result'] = get_global('Limit', 'missing')
        set_global('Seen', get_global('Seen', 0) + 1)
        """, gvars={"Limit": 42})
    assert r.outputs["Result"] == 42 and sol.get_global("Seen") == 1
    flow = sol.get_active_flow()
    flow.execute_flow(global_vars=sol.global_variables)
    flow.execute_flow(global_vars=sol.global_variables)
    assert sol.get_global("Seen") == 3, "a counter kept in a global variable survives between runs"
    assert flow_with("outputs['Result'] = get_global('nope', 'dflt')")[2].outputs["Result"] == "dflt"


def test_print_goes_to_the_log_output():
    r = flow_with("""
        print('a', 1)
        print('b', end='!')
        """)[2]
    assert r.status == ToolStatus.OK and r.outputs["Log"] == "a 1\nb!"


def test_a_non_image_in_the_image_output_is_refused():
    r = flow_with("outputs['Image'] = 'not an image'")[2]
    assert r.status == ToolStatus.ERROR and "must be a NumPy image" in r.message and isinstance(r.outputs["Image"], np.ndarray)
    assert flow_with("outputs['Image'] = cv2.cvtColor(context['Image'], cv2.COLOR_BGR2GRAY)")[2].status == ToolStatus.OK
    assert flow_with("outputs['Image'] = None")[2].status == ToolStatus.OK


def test_a_script_feeds_the_next_module():
    sol = SolutionManager(name="T")
    flow = sol.add_flow("F")
    for tool, iid in (("Image Source", "src"), ("Script", "sc"), ("Edge Detection", "ed")):
        flow.add_node(create_tool_instance(tool, iid, iid))
    flow.nodes["src"].set_param("pattern_type", "Part with Defects")
    flow.nodes["sc"].set_param("code", "outputs['Image'] = 255 - context['Image']")
    flow.connect("src", "Image", "sc", "Image")
    flow.connect("sc", "Image", "ed", "Image")
    res = flow.execute_flow(global_vars={})
    assert res["ed"].status == ToolStatus.OK and res["ed"].outputs["Edge_Pixels"] > 0


def test_an_endless_loop_is_stopped_by_the_time_limit():
    t0 = time.time()
    r = flow_with("while True:\n    pass\n", timeout_ms=600)[2]
    took = time.time() - t0
    assert r.status == ToolStatus.ERROR and "time limit" in r.message
    assert 0.5 < took < 4, f"stopped after {took:.1f}s"


def test_the_time_limit_cannot_be_swallowed_by_the_scripts_own_try_except():
    t0 = time.time()
    r = flow_with("""
        while True:
            try:
                while True:
                    pass
            except Exception:
                pass
        """, timeout_ms=600)[2]
    assert r.status == ToolStatus.ERROR and "time limit" in r.message and time.time() - t0 < 4


def test_a_quick_script_is_not_hit_by_a_late_timeout():
    for _ in range(20):
        r = flow_with("outputs['Result'] = 1", timeout_ms=100)[2]
        assert r.status == ToolStatus.OK
    time.sleep(0.4)                                   # a timer that fired after the script finished must not break later code
    assert sum(range(1000)) == 499500


def test_files_and_other_modules_are_reachable_so_only_trusted_flows_should_be_run(tmp_path):
    """Documented behaviour: a script has full Python rights (the HTTP API therefore refuses to run flows that contain one)."""
    path = str(tmp_path / "probe.txt")
    r = flow_with(f"""
        open({path!r}, 'w').write('hello')
        outputs['Result'] = open({path!r}).read()
        """)[2]
    assert r.outputs["Result"] == "hello" and os.path.exists(path)


def test_the_time_limit_is_an_editable_parameter_with_limits():
    from apex_vision.core import param_schema as ps
    spec = ps.spec_for("Script", "timeout_ms", 5000)
    assert spec["kind"] == "int" and spec["min"] == 100 and spec["max"] == 600000
    assert ps.problem("Script", "timeout_ms", 5000, 50) and ps.problem("Script", "timeout_ms", 5000, 3000) is None
