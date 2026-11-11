"""VisionMaster guide, Measurement chapter: L2C, P2C and C2C."""
import math

import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance


def run(name, ctx=None, **params):
    t = create_tool_instance(name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t.execute(ctx or {})


def test_l2c_distance_angle_and_cross_points():
    r = run("L2C Measure", input_mode="By Coordinate", line1=[0, 100, 400, 100], circle_x=200.0, circle_y=40.0, circle_r=20.0)
    o = r.outputs
    assert r.status == ToolStatus.OK
    assert o["Center_Distance"] == pytest.approx(60.0) and o["Distance"] == pytest.approx(40.0) and o["Cross_Count"] == 0
    assert o["Foot"] == pytest.approx((200.0, 100.0)) and o["Nearest_Point"] == pytest.approx((200.0, 60.0))
    assert o["Angle_Deg"] == pytest.approx(90.0), "the centre-to-line connection points straight down the picture"
    cut = run("L2C Measure", input_mode="By Coordinate", line1=[0, 100, 400, 100], circle_x=200.0, circle_y=90.0, circle_r=50.0).outputs
    assert cut["Distance"] == pytest.approx(-40.0) and cut["Cross_Count"] == 2
    xs = sorted(p[0] for p in cut["Cross_Points"])
    assert xs == pytest.approx([200 - math.sqrt(2500 - 100), 200 + math.sqrt(2500 - 100)])
    touch = run("L2C Measure", input_mode="By Coordinate", line1=[0, 100, 400, 100], circle_x=200.0, circle_y=50.0, circle_r=50.0).outputs
    assert touch["Cross_Count"] == 1 and touch["Distance"] == pytest.approx(0.0, abs=1e-9)
    on = run("L2C Measure", input_mode="By Coordinate", line1=[0, 100, 400, 100], circle_x=200.0, circle_y=100.0, circle_r=30.0).outputs
    assert on["Center_Distance"] == 0 and on["Cross_Count"] == 2


def test_l2c_input_modes_angle_range_and_scale():
    line = {"x1": 0.0, "y1": 100.0, "x2": 400.0, "y2": 100.0, "length": 400.0}
    r = run("L2C Measure", {"Line1": line, "Circle": {"cx": 200.0, "cy": 160.0, "r": 20.0}}, input_mode="By Line")
    assert r.status == ToolStatus.OK and r.outputs["Distance"] == pytest.approx(40.0) and r.outputs["Angle_Deg"] == pytest.approx(-90.0)
    tilt = run("L2C Measure", {"Line1": line, "Circle": [200, 40, 10]}, input_mode="By Line", angle_range="-90 to 90")
    assert tilt.outputs["Angle_Deg"] == pytest.approx(90.0)
    left = run("L2C Measure", input_mode="By Coordinate", line1=[100, 0, 100, 300], circle_x=40.0, circle_y=150.0, circle_r=10.0, angle_range="-90 to 90").outputs
    assert abs(left["Angle_Deg"]) < 1e-9, "the connection to the right is 0 and one to the left (180) folds to 0 as well"
    full = run("L2C Measure", input_mode="By Coordinate", line1=[100, 0, 100, 300], circle_x=40.0, circle_y=150.0, circle_r=10.0).outputs
    assert abs(abs(full["Angle_Deg"]) - 0.0) < 1e-9
    pts = run("L2C Measure", {"Point1_Start": (0, 100), "Point1_End": (400, 100), "Circle": [200, 160, 20]}, input_mode="By Point")
    assert pts.outputs["Distance"] == pytest.approx(40.0)
    scaled = run("L2C Measure", input_mode="By Coordinate", line1=[0, 100, 400, 100], circle_x=200.0, circle_y=40.0, circle_r=20.0, scale_factor=0.5).outputs
    assert scaled["Distance"] == pytest.approx(20.0) and scaled["Center_Distance"] == pytest.approx(30.0)


def test_l2c_reports_missing_input():
    assert run("L2C Measure", input_mode="By Line").status == ToolStatus.ERROR
    assert run("L2C Measure", {"Line1": {"x1": 0, "y1": 0, "x2": 10, "y2": 0}}, input_mode="By Line").status == ToolStatus.ERROR
    assert run("L2C Measure", input_mode="By Coordinate", line1=[5, 5, 5, 5]).status == ToolStatus.ERROR
    assert run("L2C Measure", input_mode="By Coordinate", circle_r=0.01).status == ToolStatus.OK


def test_p2c_outside_inside_and_centre():
    o = run("P2C Measure", input_mode="By Coordinate", point_x=100.0, point_y=200.0, circle_x=200.0, circle_y=200.0, circle_r=30.0).outputs
    assert o["Center_Distance"] == pytest.approx(100.0) and o["Distance"] == pytest.approx(70.0) and o["Nearest_Point"] == pytest.approx((170.0, 200.0))
    assert o["Delta_X"] == pytest.approx(100.0) and o["Delta_Y"] == pytest.approx(0.0) and o["Angle_Deg"] == pytest.approx(0.0)
    inside = run("P2C Measure", input_mode="By Coordinate", point_x=210.0, point_y=200.0, circle_x=200.0, circle_y=200.0, circle_r=30.0).outputs
    assert inside["Distance"] == pytest.approx(-20.0) and inside["Abs_Distance"] == pytest.approx(20.0)
    centre = run("P2C Measure", input_mode="By Coordinate", point_x=200.0, point_y=200.0, circle_x=200.0, circle_y=200.0, circle_r=30.0).outputs
    assert centre["Distance"] == pytest.approx(-30.0) and centre["Nearest_Point"] == pytest.approx((230.0, 200.0))
    wired = run("P2C Measure", {"Point": (3, 4), "Circle": {"cx": 0.0, "cy": 0.0, "r": 1.0}}, input_mode="By Circle")
    assert wired.outputs["Distance"] == pytest.approx(4.0) and wired.outputs["Angle_Deg"] == pytest.approx(math.degrees(math.atan2(-4, -3)))
    assert run("P2C Measure", {"Circle": [0, 0, 1]}, input_mode="By Circle").status == ToolStatus.ERROR
    assert run("P2C Measure", {"Point": (1, 1)}, input_mode="By Circle").status == ToolStatus.ERROR


@pytest.mark.parametrize("c1,c2,rel,gap,crosses", [
    ((0, 0, 10), (50, 0, 20), "Apart", 20.0, 0),
    ((0, 0, 30), (40, 0, 20), "Crossing", 0.0, 2),
    ((0, 0, 30), (10, 0, 5), "Inside", 15.0, 0),
    ((0, 0, 10), (30, 0, 20), "Touching", 0.0, 1),
    ((0, 0, 30), (10, 0, 20), "Touching", 0.0, 1),
])
def test_c2c_relations(c1, c2, rel, gap, crosses):
    r = run("C2C Measure", {"Circle": list(c1), "Circle2": list(c2)}, input_mode="By Circle")
    o = r.outputs
    assert r.status == ToolStatus.OK and o["Relation"] == rel, r.message
    assert o["Distance"] == pytest.approx(gap) and o["Cross_Count"] == crosses
    assert o["Center_Distance"] == pytest.approx(math.hypot(c2[0] - c1[0], c2[1] - c1[1]))
    assert o["Max_Distance"] == pytest.approx(o["Center_Distance"] + c1[2] + c2[2])
    for p in o["Cross_Points"]:
        assert math.hypot(p[0] - c1[0], p[1] - c1[1]) == pytest.approx(c1[2], abs=1e-6)
        assert math.hypot(p[0] - c2[0], p[1] - c2[1]) == pytest.approx(c2[2], abs=1e-6)


def test_c2c_closest_points_angle_and_concentric():
    o = run("C2C Measure", input_mode="By Coordinate", circle_x=0.0, circle_y=0.0, circle_r=10.0, circle2_x=0.0, circle2_y=50.0, circle2_r=20.0).outputs
    assert o["Point1"] == pytest.approx((0.0, 10.0)) and o["Point2"] == pytest.approx((0.0, 30.0)) and o["Angle_Deg"] == pytest.approx(90.0)
    assert o["Radius_Diff"] == pytest.approx(10.0)
    con = run("C2C Measure", {"Circle": [5, 5, 10], "Circle2": [5, 5, 25]}, input_mode="By Circle").outputs
    assert con["Relation"] == "Inside" and con["Distance"] == pytest.approx(15.0) and con["Center_Distance"] == 0
    assert run("C2C Measure", {"Circle": [5, 5, 10]}, input_mode="By Circle").status == ToolStatus.ERROR
    assert run("C2C Measure", {"Circle": [5, 5, 10], "Circle2": [5, 5, -1]}, input_mode="By Circle").status == ToolStatus.ERROR


@pytest.mark.parametrize("name", ["L2C Measure", "P2C Measure", "C2C Measure"])
def test_junk_input_never_crashes(name):
    for ctx in ({}, {"Circle": "x", "Line1": 5, "Point": None}, {"Circle": [float("nan")] * 3, "Circle2": [1, 1, 1]}):
        for mode in ("By Line", "By Circle", "By Point", "By Coordinate"):
            t = create_tool_instance(name, "t")
            try:
                t.set_param("input_mode", mode)
            except Exception:
                continue
            assert t.execute(ctx).status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR)
