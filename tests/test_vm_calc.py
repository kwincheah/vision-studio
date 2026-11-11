"""VisionMaster guide, Calculation chapter."""
import math

import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance
from apex_vision.tools import vm_calc as vk
from apex_vision.tools import vm_calib as vc


def make(name, **params):
    t = create_tool_instance(name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t


def run(name, ctx=None, **params):
    return make(name, **params).execute(ctx or {})


# image -> physical: 4 px per mm, physical Y points up (the picture's Y points down), origin at (0, 100) mm
CAL = vc.make_calibration(np.array([[0.25, 0, 0], [0, -0.25, 100.0], [0, 0, 1]]), "board")
ROTCAL = dict(CAL, rotation_center_world=[60.0, 50.0], rotation_center_image=[240.0, 200.0])


def R(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def moved(p, turn, d, c):
    return (np.atleast_2d(p) - np.array(c)) @ R(turn).T + np.array(c) + np.array(d)


# ---- Calibration Transformation -----------------------------------------------------------------------------------------------------------
def test_calibration_transformation_both_ways_and_angles():
    r = run("Calibration Transformation", {"Calibration": CAL}, x=200.0, y=100.0, angle=30.0)
    o = r.outputs
    assert r.status == ToolStatus.OK and (o["X"], o["Y"]) == pytest.approx((50.0, 75.0))
    assert o["Angle"] == pytest.approx(-30.0), "the physical Y axis points the other way, so a counterclockwise angle on the picture reads the other way"
    assert o["Pixel_Accuracy"] == pytest.approx(0.25) and o["Scale"] == pytest.approx(4.0) and o["Aspect_Ratio"] == pytest.approx(1.0)
    back = run("Calibration Transformation", {"Calibration": CAL}, x=50.0, y=75.0, angle=-30.0, coordinate_type="Physical to Image").outputs
    assert (back["X"], back["Y"]) == pytest.approx((200.0, 100.0)) and back["Angle"] == pytest.approx(30.0)
    wired = run("Calibration Transformation", {"Calibration": CAL, "Point": (400, 0), "Angle": 170.0}, input_mode="By Point")
    assert wired.outputs["Point"] == pytest.approx((100.0, 100.0)) and wired.outputs["Angle"] == pytest.approx(-170.0)
    many = run("Calibration Transformation", {"Calibration": CAL, "Points": [[0, 0], [400, 400]]})
    assert many.outputs["Points"] == pytest.approx([[0.0, 100.0], [100.0, 0.0]]) if False else np.allclose(many.outputs["Points"], [[0.0, 100.0], [100.0, 0.0]])
    assert run("Calibration Transformation", {"Calibration": CAL, "Points": "x"}).status == ToolStatus.ERROR
    assert run("Calibration Transformation", {"Calibration": CAL}, input_mode="By Point").status == ToolStatus.ERROR
    assert run("Calibration Transformation", {}).status == ToolStatus.ERROR
    assert run("Calibration Transformation", {"Calibration": {"matrix": "x"}}).status == ToolStatus.ERROR


def test_calibration_transformation_reads_a_file(tmp_path):
    path = tmp_path / "c.json"
    vc.save_calibration(CAL, str(path))
    r = run("Calibration Transformation", {}, x=200.0, y=100.0, calibration_file=str(path))
    assert r.status == ToolStatus.OK and (r.outputs["X"], r.outputs["Y"]) == pytest.approx((50.0, 75.0))
    assert run("Calibration Transformation", {}, calibration_file=str(tmp_path / "gone.json")).status == ToolStatus.ERROR


# ---- Scale Transformation -----------------------------------------------------------------------------------------------------------------------
def test_scale_transformation():
    r = run("Scale Transformation", {"Calibration": CAL}, distance=100.0)
    assert r.outputs["Result"] == pytest.approx(25.0) and r.outputs["Pixel_Accuracy"] == pytest.approx(0.25)
    back = run("Scale Transformation", {"Calibration": CAL}, distance=25.0, direction="Physical to Pixel")
    assert back.outputs["Result"] == pytest.approx(100.0)
    lst = run("Scale Transformation", {"Calibration": CAL, "Distance": [4, 8, 12]}, input_mode="By Port")
    assert lst.outputs["Results"] == pytest.approx([1.0, 2.0, 3.0]) and lst.outputs["Result"] == pytest.approx(1.0)
    assert run("Scale Transformation", {"Calibration": CAL, "Distance": "abc"}, input_mode="By Port").status == ToolStatus.ERROR
    assert run("Scale Transformation", {"Calibration": CAL}, input_mode="By Port").status == ToolStatus.ERROR
    assert run("Scale Transformation", {}).status == ToolStatus.ERROR


# ---- Coordinate Transformation -----------------------------------------------------------------------------------------------------------------------
def test_coordinate_transformation_back_to_the_big_picture():
    r = run("Coordinate Transformation", {}, center_x=500.0, center_y=400.0, piece_width=200, piece_height=100, point_x=50.0, point_y=60.0)
    assert (r.outputs["X"], r.outputs["Y"]) == pytest.approx((450.0, 410.0)), "the piece starts at (400, 350)"
    off = run("Coordinate Transformation", {}, enable=False, point_x=50.0, point_y=60.0)
    assert (off.outputs["X"], off.outputs["Y"]) == (50.0, 60.0)
    wired = run("Coordinate Transformation", {"Center": (500, 400), "Point": (0, 0)}, center_mode="By Point", point_mode="By Point", piece_width=200, piece_height=100)
    assert wired.outputs["Point"] == pytest.approx((400.0, 350.0))
    many = run("Coordinate Transformation", {"Points": [[0, 0], [10, 10]]}, center_x=100.0, center_y=100.0, piece_width=100, piece_height=100)
    assert np.allclose(many.outputs["Points"], [[50.0, 50.0], [60.0, 60.0]])
    assert run("Coordinate Transformation", {}, center_mode="By Point").status == ToolStatus.ERROR
    assert run("Coordinate Transformation", {}, point_mode="By Point").status == ToolStatus.ERROR
    assert run("Coordinate Transformation", {"Points": 5}).status == ToolStatus.ERROR


# ---- Calculate Rotation ------------------------------------------------------------------------------------------------------------------------------
def test_calculate_rotation_of_points_and_lines():
    ccw = run("Calculate Rotation", {}, x=200.0, y=100.0, center_x=100.0, center_y=100.0, angle=90.0)
    assert ccw.outputs["Point"] == pytest.approx((100.0, 0.0)), "counterclockwise on the picture takes the right-hand point to the top"
    cw = run("Calculate Rotation", {}, x=200.0, y=100.0, center_x=100.0, center_y=100.0, angle=90.0, direction="Clockwise")
    assert cw.outputs["Point"] == pytest.approx((100.0, 200.0))
    ln = run("Calculate Rotation", {}, input_method="By Line", line=[100, 100, 300, 100], center_x=100.0, center_y=100.0, angle=30.0)
    assert ln.outputs["Line_Angle"] == pytest.approx(-30.0) and ln.outputs["Line"]["length"] == pytest.approx(200.0)
    wired = run("Calculate Rotation", {"Point": (3, 0), "Center": (0, 0), "Angle": 180.0}, input_mode="By Port")
    assert wired.outputs["Point"] == pytest.approx((-3.0, 0.0), abs=1e-9)
    assert run("Calculate Rotation", {}, input_mode="By Port").status == ToolStatus.ERROR
    assert run("Calculate Rotation", {"Center": (0, 0)}, input_mode="By Port").status == ToolStatus.ERROR
    assert run("Calculate Rotation", {"Center": (0, 0), "Angle": "x", "Point": (1, 1)}, input_mode="By Port").status == ToolStatus.ERROR
    assert run("Calculate Rotation", {"Center": (0, 0), "Angle": 5}, input_mode="By Port", input_method="By Line").status == ToolStatus.ERROR


# ---- Single Point Alignment --------------------------------------------------------------------------------------------------------------------------------
def test_single_point_alignment_about_the_object_and_about_a_centre():
    r = run("Single Point Alignment", {}, target_x=100.0, target_y=100.0, target_angle=0.0, object_x=95.0, object_y=103.0, object_angle=5.0)
    assert (r.outputs["Delta_X"], r.outputs["Delta_Y"], r.outputs["Delta_Angle"]) == pytest.approx((5.0, -3.0, -5.0))
    fixed = run("Single Point Alignment", {}, target_x=100.0, target_y=100.0, target_angle=10.0, object_x=95.0, object_y=103.0, object_angle=-20.0, turn_about="A Fixed Centre",
                center_x=40.0, center_y=20.0)
    o = fixed.outputs
    assert o["Delta_Angle"] == pytest.approx(30.0)
    landed = R(30.0) @ (np.array([95.0, 103.0]) - [40.0, 20.0]) + [40.0, 20.0] + [o["Delta_X"], o["Delta_Y"]]
    assert landed == pytest.approx([100.0, 100.0]), "turn about the centre, then shift, puts the object on the target"
    wired = run("Single Point Alignment", {"Target": (10, 10), "Target_Angle": 179.0, "Object": (10, 10), "Object_Angle": -179.0}, input_mode="By Point")
    assert wired.outputs["Delta_Angle"] == pytest.approx(-2.0), "the short way round"
    assert run("Single Point Alignment", {}, input_mode="By Point").status == ToolStatus.ERROR


# ---- Single Point Grasp / Rectification / Mapping Alignment ---------------------------------------------------------------------------------
def _expect_grasp(cal, ref, ref_a, run_p, run_a):
    m = vc.calibration_matrix(cal)
    pr = vc.apply_matrix(m, np.array([ref]))[0]
    pn = vc.apply_matrix(m, np.array([run_p]))[0]
    return pr, pn, vk.map_angle(m, ref, ref_a), vk.map_angle(m, run_p, run_a)


def test_single_point_grasp_coaxial_and_with_a_rotation_centre():
    r = run("Single Point Grasp", {"Calibration": CAL}, ref_x=320.0, ref_y=240.0, ref_angle=0.0, run_x=330.0, run_y=250.0, run_angle=10.0, demo_x=100.0, demo_y=50.0, demo_angle=90.0)
    o = r.outputs
    assert r.status == ToolStatus.OK
    assert (o["Relative_X"], o["Relative_Y"]) == pytest.approx((2.5, -2.5)), "10 px right and 10 px down is 2.5 mm right and 2.5 mm down the physical Y"
    assert o["Relative_R"] == pytest.approx(-10.0)
    assert (o["Absolute_X"], o["Absolute_Y"], o["Absolute_R"]) == pytest.approx((102.5, 47.5, 80.0))
    assert o["Relative"] == pytest.approx([2.5, -2.5, -10.0]) and o["Status"] == 1
    pr, pn, ar, an = _expect_grasp(ROTCAL, (320, 240), 0.0, (330, 250), 10.0)
    off = run("Single Point Grasp", {"Calibration": ROTCAL}, ref_x=320.0, ref_y=240.0, ref_angle=0.0, run_x=330.0, run_y=250.0, run_angle=10.0).outputs
    c = np.array([60.0, 50.0])
    tip = c + R(off["Relative_R"]) @ (pr - c) + [off["Relative_X"], off["Relative_Y"]]
    assert tip == pytest.approx(list(pn)), "with a rotation centre the tool tip, turned about it and moved, lands on the part"
    assert off["Relative_R"] == pytest.approx(an - ar)


def test_single_point_grasp_options():
    base = dict(ref_x=320.0, ref_y=240.0, ref_angle=0.0, run_x=320.0, run_y=240.0, run_angle=0.0)
    shifted = run("Single Point Grasp", {"Calibration": CAL}, **base, capture_x=0.0, capture_y=0.0, run_capture_x=7.0, run_capture_y=-3.0).outputs
    assert (shifted["Relative_X"], shifted["Relative_Y"]) == pytest.approx((7.0, -3.0)), "the camera was somewhere else when it looked"
    rotcap = run("Single Point Grasp", {"Calibration": CAL}, **base, enable_rotation_capture=True, rotation_capture_angle=15.0).outputs
    assert rotcap["Relative_R"] == pytest.approx(15.0)
    pose = run("Single Point Grasp", {"Calibration": CAL, "Demo_Pose": [10, 20, 30]}, **base).outputs
    assert pose["Absolute"] == pytest.approx([10.0, 20.0, 30.0])
    assert run("Single Point Grasp", {"Calibration": CAL, "Demo_Pose": "x"}, **base).status == ToolStatus.ERROR
    assert run("Single Point Grasp", {}, **base).status == ToolStatus.ERROR
    assert run("Single Point Grasp", {"Calibration": CAL}, input_mode="By Point").status == ToolStatus.ERROR
    assert run("Single Point Grasp", {"Calibration": CAL}, input_mode="By Point", **{}).status == ToolStatus.ERROR
    assert run("Single Point Grasp", {"Calibration": CAL, "Run": (1, 1)}, input_mode="By Point").status == ToolStatus.ERROR, "no reference yet"


def test_create_reference_point_remembers_the_first_picture():
    t = make("Single Point Rectification", input_mode="By Point")
    assert t.execute({"Calibration": CAL, "Run": (300, 200)}).status == ToolStatus.ERROR, "nothing created yet"
    first = t.execute({"Calibration": CAL, "Run": (300, 200), "Run_Angle": 4.0, "Set_Reference": True})
    assert first.status == ToolStatus.OK and first.outputs["Relative"] == pytest.approx([0.0, 0.0, 0.0])
    assert (t.get_param("ref_x"), t.get_param("ref_y"), t.get_param("ref_angle")) == (300.0, 200.0, 4.0)
    second = t.execute({"Calibration": CAL, "Run": (310, 200), "Run_Angle": 4.0})
    assert second.outputs["Relative_X"] == pytest.approx(-2.5), "the part is 2.5 mm too far right, so it moves back"
    flag = make("Single Point Rectification", create_reference=True, run_x=111.0, run_y=222.0)
    assert flag.execute({"Calibration": CAL}).status == ToolStatus.OK and flag.get_param("create_reference") is False and flag.get_param("ref_x") == 111.0


def test_rectification_puts_the_part_back_on_the_reference():
    r = run("Single Point Rectification", {"Calibration": ROTCAL}, ref_x=320.0, ref_y=240.0, ref_angle=0.0, run_x=330.0, run_y=250.0, run_angle=10.0, demo_x=1.0, demo_y=2.0,
            demo_angle=3.0)
    o = r.outputs
    pr, pn, ar, an = _expect_grasp(ROTCAL, (320, 240), 0.0, (330, 250), 10.0)
    assert o["Relative_R"] == pytest.approx(ar - an)
    c = np.array([60.0, 50.0])
    part = c + R(o["Relative_R"]) @ (pn - c) + [o["Relative_X"], o["Relative_Y"]]
    assert part == pytest.approx(list(pr)), "the part, turned about the centre and moved, lands on the reference"
    assert (o["Absolute_X"], o["Absolute_Y"], o["Absolute_R"]) == pytest.approx((1.0 + o["Relative_X"], 2.0 + o["Relative_Y"], 3.0 + o["Relative_R"]))
    still = run("Single Point Rectification", {"Calibration": CAL}, ref_x=1.0, ref_y=2.0, run_x=1.0, run_y=2.0, run_angle=0.0).outputs
    assert still["Relative"] == pytest.approx([0.0, 0.0, 0.0])


def test_single_point_mapping_alignment():
    mapping = vc.make_calibration(np.array([[1, 0, 10.0], [0, 1, 5.0], [0, 0, 1]]), "mapping")          # target camera picture -> object camera picture
    r = run("Single Point Mapping Alignment", {"Mapping": mapping, "Calibration": CAL}, target_x=300.0, target_y=200.0, target_angle=0.0, object_x=310.0, object_y=205.0,
            object_angle=0.0)
    assert r.status == ToolStatus.OK and r.outputs["Relative"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)
    off = run("Single Point Mapping Alignment", {"Mapping": mapping, "Calibration": CAL}, target_x=300.0, target_y=200.0, object_x=318.0, object_y=205.0, object_angle=0.0).outputs
    assert off["Relative_X"] == pytest.approx(-2.0) and off["Relative_R"] == pytest.approx(0.0)
    turned = run("Single Point Mapping Alignment", {"Mapping": mapping, "Calibration": CAL}, target_x=300.0, target_y=200.0, object_x=310.0, object_y=205.0, object_angle=-5.0).outputs
    assert turned["Relative_R"] == pytest.approx(-5.0) and turned["Relative_X"] == pytest.approx(0.0, abs=1e-9)
    assert run("Single Point Mapping Alignment", {"Calibration": CAL}).status == ToolStatus.ERROR
    assert run("Single Point Mapping Alignment", {"Mapping": mapping}).status == ToolStatus.ERROR
    assert run("Single Point Mapping Alignment", {"Mapping": mapping, "Calibration": CAL, "Demo_Pose": "x"}).status == ToolStatus.ERROR


# ---- Point Set Alignment ------------------------------------------------------------------------------------------------------------------------------------
def test_point_set_alignment_recovers_the_move():
    tgt = np.array([[100, 100], [200, 100], [200, 200], [100, 220]], float)
    c = tgt.mean(axis=0)
    obj = (tgt - c) @ R(-12.0).T + c + [7.0, -4.0]
    r = run("Point Set Alignment", {}, target_points=tgt.tolist(), object_points=obj.tolist())
    o = r.outputs
    assert r.status == ToolStatus.OK and o["Error"] < 1e-9 and o["Delta_Angle"] == pytest.approx(12.0)
    assert moved(obj, o["Delta_Angle"], [o["Delta_X"], o["Delta_Y"]], o["Center"]) == pytest.approx(tgt)
    assert vc.apply_matrix(np.array(o["Matrix"]), obj) == pytest.approx(tgt)
    noisy = tgt + np.random.default_rng(3).normal(0, 0.2, tgt.shape)
    assert run("Point Set Alignment", {}, target_points=noisy.tolist(), object_points=obj.tolist()).outputs["Error"] < 0.4
    ported = run("Point Set Alignment", {"Target_Points": tgt.tolist(), "Object_Points": tgt.tolist()}, input_mode="By Point")
    assert ported.outputs["Move"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)
    two = run("Point Set Alignment", {}, target_points=[[0, 0], [10, 0]], object_points=[[5, 5], [5, 15]])
    assert two.outputs["Delta_Angle"] == pytest.approx(-90.0) and two.outputs["Error"] < 1e-9
    assert run("Point Set Alignment", {}, target_points=[[0, 0]], object_points=[[1, 1]]).status == ToolStatus.ERROR
    assert run("Point Set Alignment", {}, target_points=[[0, 0], [1, 1]], object_points=[[1, 1]]).status == ToolStatus.ERROR
    assert run("Point Set Alignment", {}, input_mode="By Point").status == ToolStatus.ERROR


# ---- Line Alignment -----------------------------------------------------------------------------------------------------------------------------------------------
def _box_lines():
    pts = [(100, 100), (300, 100), (300, 250), (100, 250)]
    return np.array([[*pts[i], *pts[(i + 1) % 4]] for i in range(4)], float)


def _move_lines(lines, turn, shift, about=(200.0, 175.0)):
    out = []
    for l in lines:
        a = R(turn) @ (l[:2] - about) + about + shift
        b = R(turn) @ (l[2:] - about) + about + shift
        out.append([*a, *b])
    return np.array(out)


def test_line_alignment_recovers_turn_and_shift():
    tgt = _box_lines()
    obj = _move_lines(tgt, -6.0, [9.0, -5.0])
    r = run("Line Alignment", {}, target_lines=tgt.tolist(), object_lines=obj.tolist())
    o = r.outputs
    assert r.status == ToolStatus.OK and o["Delta_Angle"] == pytest.approx(6.0, abs=1e-6) and o["Error"] < 1e-6
    ends = np.vstack([obj[:, :2], obj[:, 2:]])
    land = moved(ends, o["Delta_Angle"], [o["Delta_X"], o["Delta_Y"]], o["Center"])
    assert land == pytest.approx(np.vstack([tgt[:, :2], tgt[:, 2:]]), abs=1e-6)
    dicts = [{"x1": l[0], "y1": l[1], "x2": l[2], "y2": l[3]} for l in obj]
    assert run("Line Alignment", {"Target_Lines": tgt.tolist(), "Object_Lines": dicts}, input_mode="By Point").status == ToolStatus.OK


def test_closed_outline_may_start_at_any_side():
    tgt = _box_lines()
    obj = np.roll(_move_lines(tgt, 3.0, [-4.0, 6.0]), 2, axis=0)
    opened = run("Line Alignment", {}, target_lines=tgt.tolist(), object_lines=obj.tolist(), alignment_shape="Open").outputs
    closed = run("Line Alignment", {}, target_lines=tgt.tolist(), object_lines=obj.tolist(), alignment_shape="Closed").outputs
    assert closed["Error"] < 1e-6 and closed["Delta_Angle"] == pytest.approx(-3.0, abs=1e-6) and closed["Shift"] == 2
    assert abs(opened["Delta_Angle"]) > 170, "paired in the wrong order, an open set turns the part right round (a box maps onto itself)"


def test_line_alignment_input_problems():
    ok_ = _box_lines().tolist()
    assert run("Line Alignment", {}, target_lines=ok_, object_lines=ok_[:3]).status == ToolStatus.ERROR
    assert run("Line Alignment", {}, target_lines=ok_, object_lines="x").status == ToolStatus.ERROR
    assert run("Line Alignment", {}, target_lines=ok_, object_lines=[[1, 2, 3]] * 4).status == ToolStatus.ERROR
    assert run("Line Alignment", {}, target_lines=ok_, object_lines=[[5, 5, 5, 5]] * 4).status == ToolStatus.ERROR
    assert run("Line Alignment", {}, input_mode="By Point").status == ToolStatus.ERROR
    one = run("Line Alignment", {}, target_lines=[[0, 0, 10, 0]], object_lines=[[0, 3, 10, 3]])
    assert one.status == ToolStatus.OK and one.outputs["Delta_Y"] == pytest.approx(-3.0) and one.outputs["Error"] < 1e-9


@pytest.mark.parametrize("name", ["Calibration Transformation", "Scale Transformation", "Coordinate Transformation", "Calculate Rotation", "Single Point Alignment",
                                  "Single Point Grasp", "Single Point Rectification", "Single Point Mapping Alignment", "Point Set Alignment", "Line Alignment"])
def test_every_module_survives_junk(name):
    for ctx in ({}, {"Point": "x", "Calibration": 5, "Mapping": {}}, {"Points": [[1]], "Target_Points": "z", "Object_Lines": [[1, 2]]}, {"Calibration": CAL, "Point": (float("nan"), 1)}):
        for mode in ("By Point", "By Coordinate", "By Port"):
            t = create_tool_instance(name, "t")
            try:
                t.set_param("input_mode", mode)
            except Exception:
                pass
            r = t.execute(ctx)
            assert r.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR) and r.message is not None
