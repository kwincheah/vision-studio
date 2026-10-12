"""
Extended test suite for all new tools:
- Position Correction
- Edge Search
- Geometry Fit & Generation
- Pixel Count, Edge Distance, Histogram
- Image Output & Image Buffer
- OCR Recognition & BCR 1D
- Linear Edge Defect
"""
import pytest
import numpy as np
import cv2

from vm_clone.core.registry import create_tool_instance
from vm_clone.core.base_tool import ToolStatus
import vm_clone.tools


def test_position_correction():
    pc = create_tool_instance("Position Correction", "pc_test")
    pc.set_param("fiducial_x", 300.0)
    pc.set_param("fiducial_y", 200.0)
    pc.set_param("fiducial_angle", 0.0)

    res = pc.execute({"Running_X": 310.0, "Running_Y": 205.0, "Running_Angle": 5.0})
    assert res.status == ToolStatus.OK
    assert abs(res.outputs["Delta_X"] - 10.0) < 1e-3
    assert abs(res.outputs["Delta_Y"] - 5.0) < 1e-3
    assert abs(res.outputs["Delta_Angle"] - 5.0) < 1e-3
    assert "Affine_Matrix" in res.outputs


def test_edge_search():
    img = np.zeros((300, 300), dtype=np.uint8)
    img[:, 150:] = 255  # Vertical edge at x=150

    es = create_tool_instance("Edge Search", "es_test")
    es.set_param("start_pt", [50, 150])
    es.set_param("end_pt", [250, 150])
    res = es.execute({"Image": img})

    assert res.status == ToolStatus.OK
    assert abs(res.outputs["Edge_X"] - 150.0) < 2.0
    assert abs(res.outputs["Edge_Y"] - 150.0) < 2.0


def test_geometry_fit_circle():
    pts = [[250, 200], [200, 250], [150, 200], [200, 150]]
    gf = create_tool_instance("Circle/Line Fit", "gf_test")
    gf.set_param("fit_type", "Circle Fit")
    res = gf.execute({"Point_Set": pts})

    assert res.status == ToolStatus.OK
    assert abs(res.outputs["Center_X"] - 200.0) < 1e-3
    assert abs(res.outputs["Center_Y"] - 200.0) < 1e-3
    assert abs(res.outputs["Radius"] - 50.0) < 1e-3


def test_pixel_count_and_histogram():
    img = np.full((200, 200), 100, dtype=np.uint8)
    img[50:150, 50:150] = 200  # 100x100 = 10000 pixels of value 200

    pc = create_tool_instance("Pixel Count", "pc_test")
    pc.set_param("roi", [0, 0, 200, 200])
    pc.set_param("low_threshold", 150)
    pc.set_param("high_threshold", 255)
    res_pc = pc.execute({"Image": img})

    assert res_pc.status == ToolStatus.OK
    assert res_pc.outputs["Pixel_Count"] == 10000

    hist = create_tool_instance("Histogram", "hist_test")
    hist.set_param("roi", [0, 0, 200, 200])
    res_h = hist.execute({"Image": img})

    assert res_h.status == ToolStatus.OK
    assert abs(res_h.outputs["Mean"] - 125.0) < 1.0


def test_image_buffer():
    buf = create_tool_instance("Image Buffer", "buf_test")
    buf.set_param("buffer_capacity", 5)

    test_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    for i in range(8):
        res = buf.execute({"Image": test_frame})
    
    assert res.status == ToolStatus.OK
    assert res.outputs["Buffer_Count"] == 5
