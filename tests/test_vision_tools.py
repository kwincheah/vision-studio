"""
Automated unit and integration test suite for Apex Vision Studio.
Verifies:
- Tool registration and catalog integrity
- Pipeline execution, topological sort, and data passing
- Acquisition, Location, Measurement, Image Processing, Color, Calibration, and Logic tools
"""
import pytest
import numpy as np
import cv2

from apex_vision.core.registry import list_all_tools, list_categories, create_tool_instance
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.pipeline import VisionPipeline
import apex_vision.tools


def test_registry_populated():
    tools = list_all_tools()
    assert len(tools) >= 15
    cats = list_categories()
    assert "Acquisition" in cats
    assert "Location" in cats
    assert "Measurement" in cats
    assert "Image Processing" in cats
    assert "Color Processing" in cats
    assert "Calibration" in cats
    assert "Communication" in cats
    assert "Logic Tools" in cats


def test_acquisition_synthetic_patterns():
    tool = create_tool_instance("Image Source", "acq_test")
    
    # 1. PCB Pattern
    tool.set_param("pattern_type", "PCB Inspection")
    res = tool.execute({})
    assert res.status == ToolStatus.OK
    assert "Image" in res.outputs
    img = res.outputs["Image"]
    assert img.shape == (600, 800, 3)

    # 2. Calibration Grid
    tool.set_param("pattern_type", "Calibration Grid")
    res = tool.execute({})
    assert res.status == ToolStatus.OK
    assert res.outputs["Image"].shape == (600, 800, 3)

    # 3. Circles Pattern
    tool.set_param("pattern_type", "Circles & Holes")
    res = tool.execute({})
    assert res.status == ToolStatus.OK


def test_location_tools():
    # Generate test image with white circle and line
    img = np.zeros((400, 400, 3), dtype=np.uint8)
    cv2.circle(img, (200, 200), 50, (255, 255, 255), -1)
    cv2.line(img, (50, 350), (350, 350), (255, 255, 255), 4)

    # Circle Search
    circle_tool = create_tool_instance("Circle Search", "circle_test")
    circle_tool.set_param("min_radius", 40)
    circle_tool.set_param("max_radius", 60)
    res = circle_tool.execute({"Image": img})
    assert res.status == ToolStatus.OK
    assert abs(res.outputs["Center_X"] - 200) < 5
    assert abs(res.outputs["Center_Y"] - 200) < 5
    assert abs(res.outputs["Radius"] - 50) < 5

    # Line Search
    line_tool = create_tool_instance("Line Search", "line_test")
    res = line_tool.execute({"Image": img})
    assert res.status == ToolStatus.OK
    assert res.outputs["Line"] is not None

    # Blob Analysis
    blob_tool = create_tool_instance("BLOB Analysis", "blob_test")
    blob_tool.set_param("min_area", 500)
    res = blob_tool.execute({"Image": img})
    assert res.status == ToolStatus.OK
    assert res.outputs["Count"] >= 1


def test_measurement_tools():
    # P2P Measure
    p2p = create_tool_instance("P2P Measure", "p2p_test")
    p2p.set_param("scale_factor", 0.5)  # 0.5 mm per pixel
    res = p2p.execute({"Point1": (100, 100), "Point2": (100, 300)})
    assert res.status == ToolStatus.OK
    # 200 pixels * 0.5 = 100.0 mm
    assert abs(res.outputs["Distance"] - 100.0) < 1e-3
    assert abs(res.outputs["Delta_Y"] - 100.0) < 1e-3

    # L2L Measure
    l2l = create_tool_instance("L2L Measure", "l2l_test")
    res = l2l.execute({
        "Line1": {"x1": 50, "y1": 100, "x2": 250, "y2": 100},
        "Line2": {"x1": 50, "y1": 200, "x2": 250, "y2": 200}
    })
    assert res.status == ToolStatus.OK
    assert abs(res.outputs["Distance"] - 100.0) < 1e-3
    assert abs(res.outputs["Angle_Diff"] - 0.0) < 1e-3


def test_calibration_tool():
    calib = create_tool_instance("N-Point Calibration", "calib_test")
    res = calib.execute({"Pixel_X": 400.0, "Pixel_Y": 300.0})
    assert res.status == ToolStatus.OK
    assert abs(res.outputs["World_X"] - 40.0) < 1.0
    assert abs(res.outputs["World_Y"] - 30.0) < 1.0


def test_logic_and_script_tool():
    cond = create_tool_instance("Condition Branch", "cond_test")
    cond.set_param("operator", "Between")
    cond.set_param("threshold_low", 10.0)
    cond.set_param("threshold_high", 50.0)
    
    res_pass = cond.execute({"Val_In": 25.0})
    assert res_pass.status == ToolStatus.OK
    assert res_pass.outputs["Branch_Result"] is True

    res_fail = cond.execute({"Val_In": 75.0})
    assert res_fail.status == ToolStatus.NG
    assert res_fail.outputs["Branch_Result"] is False

    # Script tool
    script = create_tool_instance("Script", "script_test")
    script.set_param("code", "outputs['Result'] = context.get('Val1', 0) * 3\noutputs['Status'] = 'OK'")
    res_script = script.execute({"Val1": 15})
    assert res_script.status == ToolStatus.OK
    assert res_script.outputs["Result"] == 45


def test_pipeline_execution_and_dag_data_flow():
    pipe = VisionPipeline(name="TestDAG")
    
    src = create_tool_instance("Image Source", "src")
    src.set_param("pattern_type", "PCB Inspection")
    pipe.add_node(src)

    tm = create_tool_instance("Template Match", "tm")
    pipe.add_node(tm)
    pipe.connect("src", "Image", "tm", "Image")

    results = pipe.execute_flow()
    assert "src" in results
    assert "tm" in results
    assert results["src"].status == ToolStatus.OK
    assert results["tm"].status == ToolStatus.OK
    assert pipe.last_flow_time_ms > 0
