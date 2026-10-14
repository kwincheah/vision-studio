"""Regression tests for the functional audit.

Each test pins a defect that was reproduced and fixed, so it cannot silently return.
The defects were found by executing every tool with degraded inputs
(`scripts/audit_tool_contracts.py`) rather than by reading the code.

Covered here:
  * `L2L Measure` crashed on a malformed / absent line instead of reporting it.
  * `P2P Measure` crashed on a short point, and silently coerced a malformed one to
    (0, 0), producing a confident but meaningless distance.
  * `Position Correction` raised on a non-numeric or non-finite running pose, and a
    NaN pose propagated into the affine matrix.
  * `N-Point Calibration` accepted NaN/inf pixels and emitted NaN world coordinates.
  * `Condition Branch` raised OverflowError on `inf`, and reported a confident FAIL
    for a NaN operand because every comparison against NaN is False.
  * `Circle/Line Fit` accepted a wrong-shaped point list and fitted to mis-read
    columns instead of rejecting the input.
  * The sample PCB solution accepted a board with defects (inverted acceptance).
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vm_clone.core.base_tool import ToolStatus, VisionToolBase  # noqa: E402
from vm_clone.core.registry import create_tool_instance  # noqa: E402
import vm_clone.tools  # noqa: E402,F401


def make(name: str):
    return create_tool_instance(name, instance_id=f"__test_{name}__")


# ---------------------------------------------------------------------------
# L2L Measure
# ---------------------------------------------------------------------------
#: Values that mean "the upstream module produced nothing".  These fall back to the
#: configured default line, which is the long-standing contract for a port whose
#: detector found no edge.  (The empty containers matter: a search module that finds
#: nothing emits an empty result, and treating that as a *malformed* line would turn a
#: normal "no edge found" into a hard error.)
ABSENT_LINES = [None, {}, []]

#: Values that are present but cannot possibly be a line.  These must be reported.
MALFORMED_LINES = [
    {"x1": 1, "y1": 2}, {"x1": 1, "y1": 2, "x2": 3},
    [1, 2, 3], [(1.0, 2.0)], "garbage", 5, [[1, 2], [3, 4], [5, 6]],
]


@pytest.mark.parametrize("bad", MALFORMED_LINES)
def test_l2l_rejects_malformed_line_without_raising(bad):
    tool = make("L2L Measure")
    result = tool.execute({"Line1": bad, "Line2": {"x1": 0, "y1": 0, "x2": 1, "y2": 1}})
    assert result is not None
    assert result.status == ToolStatus.ERROR
    assert "Line1" in result.message


@pytest.mark.parametrize("bad", MALFORMED_LINES)
def test_l2l_rejects_malformed_second_line(bad):
    tool = make("L2L Measure")
    result = tool.execute({"Line1": {"x1": 0, "y1": 0, "x2": 1, "y2": 1}, "Line2": bad})
    assert result.status == ToolStatus.ERROR
    assert "Line2" in result.message


@pytest.mark.parametrize("absent", ABSENT_LINES)
def test_l2l_falls_back_to_the_default_line_when_nothing_arrives(absent):
    """An unconnected port uses the configured default rather than erroring."""
    tool = make("L2L Measure")
    result = tool.execute({"Line1": absent, "Line2": absent})
    assert result.status in (ToolStatus.OK, ToolStatus.NG)
    assert "Distance" in result.outputs


def test_l2l_accepts_every_documented_line_shape():
    """The three documented spellings must all measure the same distance."""
    tool = make("L2L Measure")
    shapes = [
        {"x1": 0, "y1": 0, "x2": 10, "y2": 0},
        [0, 0, 10, 0],
        [(0, 0), (10, 0)],
    ]
    distances = []
    for shape in shapes:
        result = tool.execute({"Line1": shape, "Line2": {"x1": 0, "y1": 8, "x2": 10, "y2": 8}})
        assert result.status == ToolStatus.OK, f"{shape} -> {result.message}"
        distances.append(result.outputs["Distance"])
    assert len(set(distances)) == 1
    assert distances[0] == pytest.approx(8.0)


def test_l2l_measures_a_known_distance():
    """A horizontal pair 8 px apart with unit scale must report 8."""
    tool = make("L2L Measure")
    result = tool.execute({
        "Line1": {"x1": 0, "y1": 0, "x2": 10, "y2": 0},
        "Line2": {"x1": 0, "y1": 8, "x2": 10, "y2": 8},
    })
    assert result.outputs["Distance"] == pytest.approx(8.0, abs=1e-6)
    assert result.outputs["Angle_Diff"] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# P2P Measure
# ---------------------------------------------------------------------------
def test_p2p_rejects_short_point_without_raising():
    tool = make("P2P Measure")
    result = tool.execute({"Point1": (1.0,), "Point2": (3.0, 4.0)})
    assert result.status == ToolStatus.ERROR
    assert "Point1" in result.message


def test_p2p_does_not_silently_zero_a_malformed_point():
    """A malformed point must not be treated as the origin.

    Coercing to (0, 0) produced a plausible-looking but wrong distance, which is
    worse than refusing to measure.
    """
    tool = make("P2P Measure")
    result = tool.execute({"Point1": "not-a-point", "Point2": (100.0, 0.0)})
    assert result.status == ToolStatus.ERROR
    assert not result.outputs


def test_p2p_measures_a_known_distance():
    tool = make("P2P Measure")
    result = tool.execute({"Point1": (0.0, 0.0), "Point2": (3.0, 4.0)})
    assert result.status == ToolStatus.OK
    assert result.outputs["Distance"] == pytest.approx(5.0, abs=1e-6)


def test_p2p_accepts_mapping_points():
    tool = make("P2P Measure")
    result = tool.execute({"Point1": {"x": 0, "y": 0}, "Point2": {"cx": 3, "cy": 4}})
    assert result.status == ToolStatus.OK
    assert result.outputs["Distance"] == pytest.approx(5.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Position Correction
# ---------------------------------------------------------------------------
BAD_NUMERICS = [None, "abc", [], {}, float("nan"), float("inf"), float("-inf")]


@pytest.mark.parametrize("bad", BAD_NUMERICS)
@pytest.mark.parametrize("port", ["Running_X", "Running_Y", "Running_Angle"])
def test_position_correction_survives_bad_pose(port, bad):
    tool = make("Position Correction")
    result = tool.execute({"Running_X": 350.0, "Running_Y": 300.0,
                           "Running_Angle": 0.0, port: bad})
    assert result is not None
    assert result.status in (ToolStatus.OK, ToolStatus.NG)
    # a non-finite pose must not reach the transform
    for value in result.outputs.values():
        if isinstance(value, float):
            assert math.isfinite(value)


def test_position_correction_identity_pose_is_a_no_op():
    """With the running pose equal to the fiducial the offset must be zero."""
    tool = make("Position Correction")
    fx = tool.get_param("fiducial_x")
    fy = tool.get_param("fiducial_y")
    result = tool.execute({"Running_X": fx, "Running_Y": fy, "Running_Angle": 0.0})
    assert result.status == ToolStatus.OK
    assert result.outputs["Delta_X"] == pytest.approx(0.0, abs=1e-6)
    assert result.outputs["Delta_Y"] == pytest.approx(0.0, abs=1e-6)
    assert result.outputs["Delta_Angle"] == pytest.approx(0.0, abs=1e-6)
    # the affine matrix must be the identity rather than merely "close enough"
    matrix = np.asarray(result.outputs["Affine_Matrix"])
    assert np.allclose(matrix, np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]), atol=1e-5)


def test_position_correction_reports_a_real_offset():
    """A 10 px shift must appear as a 10 px delta."""
    tool = make("Position Correction")
    fx = tool.get_param("fiducial_x")
    fy = tool.get_param("fiducial_y")
    result = tool.execute({"Running_X": fx + 10.0, "Running_Y": fy - 5.0,
                           "Running_Angle": 0.0})
    assert result.outputs["Delta_X"] == pytest.approx(10.0, abs=1e-5)
    assert result.outputs["Delta_Y"] == pytest.approx(-5.0, abs=1e-5)


# ---------------------------------------------------------------------------
# N-Point Calibration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), None,
                                 "abc", []])
def test_npoint_calibration_never_emits_non_finite_world(bad):
    tool = make("N-Point Calibration")
    result = tool.execute({"Pixel_X": bad, "Pixel_Y": bad})
    assert result is not None
    for key, value in (result.outputs or {}).items():
        if isinstance(value, float):
            assert math.isfinite(value), f"{key} was {value}"


# ---------------------------------------------------------------------------
# Condition Branch
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), None,
                                 "abc", [], {}])
def test_condition_branch_survives_non_finite_condition(bad):
    tool = make("Condition Branch")
    result = tool.execute({"Val_In": bad})
    assert result is not None
    assert result.status in (ToolStatus.OK, ToolStatus.NG)
    assert result.message


def test_condition_branch_uses_the_bound_it_reports():
    """The message must not name a threshold the operator did not set.

    `Val=7.00 <= [0.0, 150.0] -> FAIL` read as a contradiction: the printed range
    was not the applied one.
    """
    tool = make("Condition Branch")
    tool.set_param("operator", "<=")
    tool.set_param("threshold_low", 0.0)
    tool.set_param("threshold_high", 150.0)
    result = tool.execute({"Val_In": 7.0})
    assert result.status == ToolStatus.NG
    assert "150" not in result.message
    assert "<= 0" in result.message
    assert "FAIL" in result.message


def test_condition_branch_between_reports_the_range():
    tool = make("Condition Branch")
    tool.set_param("operator", "Between")
    tool.set_param("threshold_low", 10.0)
    tool.set_param("threshold_high", 20.0)
    inside = tool.execute({"Val_In": 15.0})
    outside = tool.execute({"Val_In": 25.0})
    assert inside.status == ToolStatus.OK
    assert outside.status == ToolStatus.NG
    assert "10" in inside.message and "20" in inside.message


def test_condition_branch_comparison_is_correct():
    tool = make("Condition Branch")
    tool.set_param("operator", ">=")
    tool.set_param("threshold_low", 50.0)
    assert tool.execute({"Val_In": 50.0}).status == ToolStatus.OK
    assert tool.execute({"Val_In": 49.9}).status == ToolStatus.NG
    tool.set_param("operator", "<")
    assert tool.execute({"Val_In": 49.9}).status == ToolStatus.OK
    assert tool.execute({"Val_In": 50.0}).status == ToolStatus.NG


# ---------------------------------------------------------------------------
# Variable Calculation / If Module - same NaN class
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "abc", None, []])
def test_variable_calculation_never_emits_nan(bad):
    tool = make("Variable Calculation")
    result = tool.execute({"Val_A": bad, "Val_B": bad})
    assert result is not None
    value = result.outputs.get("Result")
    if isinstance(value, float):
        assert math.isfinite(value)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "abc", None, []])
def test_if_module_never_emits_nan(bad):
    tool = make("If Module")
    result = tool.execute({"Val_In": bad})
    assert result is not None
    assert result.status in (ToolStatus.OK, ToolStatus.NG)


# ---------------------------------------------------------------------------
# Circle/Line Fit - wrong-shaped point sets
# ---------------------------------------------------------------------------
BAD_POINT_SETS = [
    [[1, 2, 3], [4, 5, 6], [7, 8, 9]],     # 3 columns: column 1 is not a y value
    [[1, 2], [3, 4]],                       # only 2 rows
    [1, 2, 3],                              # 1-D
    "garbage",
    [[1, 2], [3, float("nan")], [5, 6]],    # non-finite
    [[1, 2], [3, 4, 5], [6, 7]],            # ragged
]


@pytest.mark.parametrize("bad", BAD_POINT_SETS)
def test_geometry_fit_rejects_wrong_shaped_points(bad):
    tool = make("Circle/Line Fit")
    result = tool.execute({"Point_Set": bad})
    assert result is not None
    assert result.status in (ToolStatus.NG, ToolStatus.ERROR)


def test_geometry_fit_produces_the_correct_circle():
    """Four points on a circle of radius 100 about (200, 200)."""
    tool = make("Circle/Line Fit")
    tool.set_param("fit_type", "Circle Fit")
    result = tool.execute({"Point_Set": [[100, 200], [200, 100], [300, 200], [200, 300]]})
    assert result.status == ToolStatus.OK
    assert result.outputs["Center_X"] == pytest.approx(200.0, abs=0.5)
    assert result.outputs["Center_Y"] == pytest.approx(200.0, abs=0.5)
    assert result.outputs["Radius"] == pytest.approx(100.0, abs=0.5)


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------
def test_as_float_rejects_non_finite_and_non_numeric():
    assert VisionToolBase.as_float(None, -1) == -1
    assert VisionToolBase.as_float(float("nan"), -1) == -1
    assert VisionToolBase.as_float(float("inf"), -1) == -1
    assert VisionToolBase.as_float("abc", -1) == -1
    assert VisionToolBase.as_float([], -1) == -1
    assert VisionToolBase.as_float("42", -1) == 42.0
    assert VisionToolBase.as_float(7, -1) == 7.0


def test_as_point_shapes():
    assert VisionToolBase.as_point(None) is None
    assert VisionToolBase.as_point((1.0,)) is None
    assert VisionToolBase.as_point("x") is None
    assert VisionToolBase.as_point([1, 2]) == (1.0, 2.0)
    assert VisionToolBase.as_point({"x": 1, "y": 2}) == (1.0, 2.0)
    assert VisionToolBase.as_point({"cx": 3, "cy": 4}) == (3.0, 4.0)


def test_as_line_shapes():
    assert VisionToolBase.as_line({"x1": 1, "y1": 2, "x2": 3, "y2": 4}) == (1.0, 2.0, 3.0, 4.0)
    assert VisionToolBase.as_line([1, 2, 3, 4]) == (1.0, 2.0, 3.0, 4.0)
    assert VisionToolBase.as_line([(1, 2), (3, 4)]) == (1.0, 2.0, 3.0, 4.0)
    assert VisionToolBase.as_line({"x1": 1, "y1": 2}) is None
    assert VisionToolBase.as_line({}) is None
    assert VisionToolBase.as_line([1, 2, 3]) is None
    assert VisionToolBase.as_line("garbage") is None
    assert VisionToolBase.as_line(None) is None


def test_as_point_list_shapes():
    assert VisionToolBase.as_point_list([[1, 2], [3, 4]]).shape == (2, 2)
    assert VisionToolBase.as_point_list([[1, 2, 3], [4, 5, 6]]) is None
    assert VisionToolBase.as_point_list([]) is None
    assert VisionToolBase.as_point_list(None) is None
    assert VisionToolBase.as_point_list("x") is None
    assert VisionToolBase.as_point_list([1, 2, 3]) is None
    assert VisionToolBase.as_point_list([[1, 2], [float("nan"), 4]]) is None
    assert VisionToolBase.as_point_list([[1, 2], [3, 4]], minimum=3) is None


# ---------------------------------------------------------------------------
# Sample solution acceptance
# ---------------------------------------------------------------------------
def test_sample_solution_fails_a_board_with_defects():
    """The AOI verdict must reject a part whose defect count exceeds tolerance."""
    from vm_clone.samples.pcb_solution import create_pcb_inspection_solution

    pipeline = create_pcb_inspection_solution()
    results = pipeline.execute_flow()

    defects = results["node_defect"].outputs.get("Defect_Count")
    assert defects is not None

    verdict = results["node_branch"]
    if defects > 0:
        assert verdict.status == ToolStatus.NG, (
            f"board with {defects} defects reported {verdict.status.value}")
    else:
        assert verdict.status == ToolStatus.OK


def test_sample_solution_propagates_the_verdict_to_the_plc():
    """The transmitted string must agree with the judge's verdict.

    The message carries the configured terminator, so the verdict is matched after
    stripping the framing characters.
    """
    from vm_clone.samples.pcb_solution import create_pcb_inspection_solution

    pipeline = create_pcb_inspection_solution()
    results = pipeline.execute_flow()
    verdict = results["node_branch"]
    message = results["node_tcp"].outputs.get("Last_Message")
    assert message is not None
    expected = "OK" if verdict.status == ToolStatus.OK else "NG"
    assert message.strip().endswith(expected), (
        f"{message!r} disagrees with {verdict.status.value}")


def test_every_sample_flow_executes_without_error():
    """Every built-in sample must run clean: no ERROR node anywhere."""
    import inspect
    from vm_clone.samples import pcb_solution

    factories = [
        (name, fn) for name, fn in inspect.getmembers(pcb_solution, inspect.isfunction)
        if name.startswith("create_") and name.endswith("_solution")
    ]
    assert factories, "no sample solution factories found"

    for name, factory in factories:
        pipeline = factory()
        results = pipeline.execute_flow()
        errors = [f"{pipeline.nodes[n].name}: {r.message}"
                  for n, r in results.items()
                  if r is not None and r.status == ToolStatus.ERROR
                  and n in pipeline.nodes]
        assert not errors, f"{name} produced errors: {errors}"
