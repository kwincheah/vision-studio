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


# ---------------------------------------------------------------------------
# OCR Recognition must read the pixels, never return a canned string
# ---------------------------------------------------------------------------
def _ocr_engine_available() -> bool:
    from vm_clone.tools.recognition import _get_ocr_engine
    return _get_ocr_engine() is not None


def test_ocr_reports_engine_unavailable_instead_of_fabricating(monkeypatch):
    import vm_clone.tools.recognition as rec
    monkeypatch.setattr(rec, "_get_ocr_engine", lambda: None)
    img = np.full((600, 800, 3), 255, dtype=np.uint8)
    cv2.putText(img, "LOT-4711", (90, 530), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    tool = create_tool_instance("OCR Recognition", "ocr_noengine")
    res = tool.execute({"Image": img})
    assert res.status == ToolStatus.ERROR
    assert res.outputs["Text"] == ""
    assert "rapidocr" in res.message.lower()


@pytest.mark.skipif(not _ocr_engine_available(), reason="rapidocr-onnxruntime not installed")
def test_ocr_reads_actual_text_and_honours_pattern():
    img = np.full((600, 800, 3), 255, dtype=np.uint8)
    cv2.putText(img, "LOT-4711", (90, 530), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    tool = create_tool_instance("OCR Recognition", "ocr_real")
    tool.set_param("char_polarity", "Dark on White")
    tool.set_param("expected_pattern", "LOT-*")
    res = tool.execute({"Image": img})
    assert res.status == ToolStatus.OK, res.message
    assert "4711" in res.outputs["Text"]
    tool.set_param("expected_pattern", "SN-*")
    assert tool.execute({"Image": img}).status == ToolStatus.NG
    # A blank image must not yield text.
    blank = tool.execute({"Image": np.full((600, 800, 3), 255, dtype=np.uint8)})
    assert blank.status == ToolStatus.NG and blank.outputs["Text"] == ""


def test_script_tool_functions_and_comprehensions_see_injected_names():
    t = create_tool_instance("Script", "script_scope")
    t.set_param("code", "vals = [np.sqrt(x) for x in (4, 9)]\n"
                        "def total(a):\n    return float(np.sum(a))\n"
                        "outputs['Result'] = total(vals)\n")
    res = t.execute({})
    assert res.status == ToolStatus.OK, res.message
    assert res.outputs["Result"] == 5.0


def test_calibration_target_is_detectable_by_opencv():
    from vm_clone.core.target_generator import make_calibration_target, inner_pattern_size
    img = make_calibration_target("Chessboard", 10, 7)
    ok, _ = cv2.findChessboardCorners(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                                      inner_pattern_size("Chessboard", 10, 7))
    assert ok
    grid = make_calibration_target("Asymmetric Circles", 4, 11)
    ok, _ = cv2.findCirclesGrid(cv2.cvtColor(grid, cv2.COLOR_BGR2GRAY), (4, 11),
                                flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
    assert ok
    with pytest.raises(ValueError):
        make_calibration_target("Chessboard", 1, 7)


def test_global_script_runs_persists_and_reports_errors(tmp_path):
    from vm_clone.core.pipeline import SolutionManager
    sol = SolutionManager(name="gs")
    flow = sol.add_flow("Flow1")
    flow.add_node(create_tool_instance("Image Source", "src", "01_Src"))
    sol.active_flow_name = "Flow1"
    sol.global_script = ("def process(context):\n"
                         "    context.set_global('seen', sorted(context.results.items()))\n")
    results = flow.execute_flow(global_vars=sol.global_variables)
    assert sol.run_global_script(results) is None
    assert sol.global_variables["seen"] == [("01_Src", "OK")]
    path = str(tmp_path / "gs.vmp")
    sol.save_to_file(path)
    assert SolutionManager.load_from_file(path).global_script == sol.global_script
    sol.global_script = "def process(context):\n    raise RuntimeError('boom')\n"
    assert "boom" in sol.run_global_script(results)
    sol.global_script = "x = 1"
    assert "process" in sol.run_global_script(results)


def test_imageio_round_trips_non_ascii_paths(tmp_path):
    from vm_clone.core.imageio import imread, imwrite
    folder = tmp_path / "ünï_目录"
    folder.mkdir()
    path = str(folder / "图像.png")
    img = np.full((12, 16, 3), 123, np.uint8)
    assert imwrite(path, img)
    back = imread(path)
    assert back is not None and back.shape == img.shape and int(back[0, 0, 0]) == 123
    # failure modes return None / False rather than raising
    assert imread(str(folder / "missing.png")) is None
    (folder / "empty.png").write_bytes(b"")
    assert imread(str(folder / "empty.png")) is None
    (folder / "junk.png").write_bytes(b"not an image")
    assert imread(str(folder / "junk.png")) is None
    assert imwrite(str(folder / "no_such_dir" / "x.png"), img) is False
