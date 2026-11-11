"""The modules added after the first release: each one does what its name says, on known pictures and numbers."""
import csv
import socket
import struct
import threading

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance, list_all_tools

NEW = ["Image Crop", "Image Transform", "Color Convert", "Brightness Contrast", "Image Calculate", "Edge Detection",
       "Focus Measure", "P2L Measure", "Angle Measure", "Line Intersection", "Hough Detect", "UDP Send", "Serial Send",
       "Modbus TCP Write", "Data Log"]


def run(name, ctx, **params):
    t = create_tool_instance(name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t.execute(ctx)


def board():
    img = np.full((240, 320, 3), 60, np.uint8)
    cv2.rectangle(img, (80, 60), (240, 180), (200, 200, 200), -1)
    cv2.circle(img, (160, 120), 30, (20, 20, 20), -1)
    return img


def test_all_fifteen_are_registered_and_the_old_ones_remain():
    names = set(list_all_tools())
    assert set(NEW) <= names and len(names) >= 57


# ---- image processing -----------------------------------------------------------------------
def test_crop_returns_exactly_the_requested_region():
    img = board()
    r = run("Image Crop", {"Image": img}, roi=[80, 60, 100, 50])
    assert r.status == ToolStatus.OK and r.outputs["Image"].shape == (50, 100, 3)
    assert r.outputs["Width"] == 100 and r.outputs["Height"] == 50
    assert (r.outputs["Image"][:, :5] == 200).all(), "the crop starts at x=80, the bright square"
    far = run("Image Crop", {"Image": img}, roi=[300, 230, 500, 500])       # runs off the edge: clamped, never a crash
    assert far.status == ToolStatus.OK and far.outputs["Image"].shape[0] >= 1


def test_transform_resize_rotate_flip_have_the_right_shapes_and_content():
    img = board()
    assert run("Image Transform", {"Image": img}, operation="Resize", scale=0.5).outputs["Image"].shape == (120, 160, 3)
    assert run("Image Transform", {"Image": img}, operation="Resize", scale=2.0).outputs["Image"].shape == (480, 640, 3)
    assert run("Image Transform", {"Image": img}, operation="Rotate 90 CW").outputs["Image"].shape == (320, 240, 3)
    flipped = run("Image Transform", {"Image": img}, operation="Flip Horizontal").outputs["Image"]
    assert (flipped == img[:, ::-1]).all()
    assert (run("Image Transform", {"Image": img}, operation="Flip Vertical").outputs["Image"] == img[::-1]).all()
    assert (run("Image Transform", {"Image": img}, operation="Rotate 180").outputs["Image"] == img[::-1, ::-1]).all()
    grown = run("Image Transform", {"Image": img}, operation="Rotate", angle=45.0, expand=True).outputs["Image"]
    kept = run("Image Transform", {"Image": img}, operation="Rotate", angle=45.0, expand=False).outputs["Image"]
    assert grown.shape[0] > 240 and grown.shape[1] > 320 and kept.shape == img.shape
    assert run("Image Transform", {"Image": img}, operation="Resize", scale=1000.0).status == ToolStatus.ERROR


def test_color_convert_channels_and_modes():
    img = np.zeros((20, 20, 3), np.uint8)
    img[:, :] = (10, 120, 250)                                  # B, G, R
    for mode, expected in (("Blue channel", 10), ("Green channel", 120), ("Red channel", 250)):
        out = run("Color Convert", {"Image": img}, mode=mode).outputs["Image"]
        assert out.shape == img.shape and (out == expected).all(), mode
    gray = run("Color Convert", {"Image": img}, mode="Grayscale").outputs["Image"]
    assert (gray[:, :, 0] == gray[:, :, 1]).all() and abs(int(gray[0, 0, 0]) - int(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[0, 0])) <= 1
    assert run("Color Convert", {"Image": img}, mode="HSV").outputs["Image"].shape == img.shape
    assert run("Color Convert", {"Image": img[:, :, 0]}, mode="Lab").status == ToolStatus.OK      # a grey input works too


def test_brightness_contrast_modes_really_change_the_picture():
    dark = np.full((60, 80, 3), 20, np.uint8)
    dark[20:40, 20:60] = 40
    auto = run("Brightness Contrast", {"Image": dark}, mode="Auto Brighten", target_mean=120)
    assert auto.outputs["Mean_After"] > auto.outputs["Mean_Before"] * 2 and 90 < auto.outputs["Mean_After"] < 150
    manual = run("Brightness Contrast", {"Image": dark}, mode="Manual", brightness=50, contrast=1.0).outputs["Image"]
    assert (manual[0, 0] == 70).all()
    brighter = run("Brightness Contrast", {"Image": dark}, mode="Gamma", gamma=0.5).outputs["Mean_After"]
    darker = run("Brightness Contrast", {"Image": dark}, mode="Gamma", gamma=2.0).outputs["Mean_After"]
    assert brighter > auto.outputs["Mean_Before"] > darker
    grad = np.tile(np.linspace(80, 120, 100).astype(np.uint8), (50, 1))
    grad = cv2.cvtColor(grad, cv2.COLOR_GRAY2BGR)
    for mode in ("Equalize", "CLAHE"):
        out = run("Brightness Contrast", {"Image": grad}, mode=mode).outputs["Image"]
        assert int(out.max()) - int(out.min()) > 40, f"{mode} widens the narrow range 80-120"
    black = np.zeros((10, 10, 3), np.uint8)
    assert run("Brightness Contrast", {"Image": black}, mode="Auto Brighten").status == ToolStatus.OK     # no divide by zero


def test_image_calculate_compares_with_a_reference_picture():
    good = board()
    bad = good.copy()
    cv2.rectangle(bad, (100, 80), (110, 90), (0, 0, 0), -1)                     # a scratch
    diff = run("Image Calculate", {"Image": bad, "Image_B": good}, operation="Absolute Difference")
    assert diff.outputs["Mean"] > 0 and diff.outputs["Image"][85, 105].max() > 100
    same = run("Image Calculate", {"Image": good, "Image_B": good}, operation="Absolute Difference")
    assert same.outputs["Mean"] == 0
    assert run("Image Calculate", {"Image": good}, operation="Add").status == ToolStatus.NG, "Image B is required"
    small = cv2.resize(good, (160, 120))
    assert run("Image Calculate", {"Image": good, "Image_B": small}, operation="Average").outputs["Image"].shape == good.shape
    a = np.full((4, 4, 3), 200, np.uint8)
    b = np.full((4, 4, 3), 100, np.uint8)
    assert (run("Image Calculate", {"Image": a, "Image_B": b}, operation="Add").outputs["Image"] == 255).all(), "saturates"
    assert (run("Image Calculate", {"Image": b, "Image_B": a}, operation="Subtract (A - B)").outputs["Image"] == 0).all()
    assert (run("Image Calculate", {"Image": a, "Image_B": b}, operation="Maximum").outputs["Image"] == 200).all()
    assert (run("Image Calculate", {"Image": a, "Image_B": b}, operation="Bitwise AND").outputs["Image"] == (200 & 100)).all()


@pytest.mark.parametrize("method", ["Canny", "Sobel", "Scharr", "Laplacian"])
def test_edge_detection_finds_the_square_outline_and_nothing_in_a_flat_image(method):
    r = run("Edge Detection", {"Image": board()}, method=method, low_threshold=50, high_threshold=150)
    assert r.status == ToolStatus.OK and r.outputs["Edge_Pixels"] > 200
    assert set(np.unique(r.outputs["Image"])) <= {0, 255}
    flat = run("Edge Detection", {"Image": np.full((50, 50, 3), 90, np.uint8)}, method=method)
    assert flat.outputs["Edge_Pixels"] == 0


def test_focus_measure_tells_sharp_from_blurred():
    sharp = board()
    blurred = cv2.GaussianBlur(sharp, (0, 0), 6)
    s = run("Focus Measure", {"Image": sharp}).outputs["Sharpness"]
    b = run("Focus Measure", {"Image": blurred}).outputs["Sharpness"]
    assert s > 5 * b
    assert run("Focus Measure", {"Image": blurred}, min_sharpness=s / 2).status == ToolStatus.NG
    assert run("Focus Measure", {"Image": sharp}, min_sharpness=s / 2).status == ToolStatus.OK


# ---- measurement ----------------------------------------------------------------------------
def test_point_to_line_distance_and_foot():
    r = run("P2L Measure", {"Point": (50, 100), "Line": {"x1": 0, "y1": 0, "x2": 100, "y2": 0}})
    assert r.status == ToolStatus.OK and r.outputs["Distance"] == pytest.approx(100.0)
    assert r.outputs["Foot"] == pytest.approx((50.0, 0.0))
    diag = run("P2L Measure", {"Point": (0, 10), "Line": [0, 0, 10, 10]})
    assert diag.outputs["Distance"] == pytest.approx(10 / np.sqrt(2))
    assert run("P2L Measure", {"Point": (0, 0), "Line": [5, 5, 5, 5]}).status == ToolStatus.NG, "a zero-length line"
    assert run("P2L Measure", {"Point": "junk", "Line": [0, 0, 1, 1]}).status == ToolStatus.ERROR
    scaled = run("P2L Measure", {"Point": (0, 10), "Line": [0, 0, 10, 0]}, scale_factor=0.5)
    assert scaled.outputs["Distance"] == pytest.approx(5.0)
    assert run("P2L Measure", {"Point": (0, 10), "Line": [0, 0, 10, 0]}, max_distance=5.0).status == ToolStatus.NG


def test_angle_between_three_points():
    right = run("Angle Measure", {"Point_A": (10, 0), "Vertex": (0, 0), "Point_C": (0, 10)})
    assert right.outputs["Angle_Deg"] == pytest.approx(90.0)
    assert run("Angle Measure", {"Point_A": (10, 0), "Vertex": (0, 0), "Point_C": (-10, 0)}).outputs["Angle_Deg"] == pytest.approx(180.0)
    assert run("Angle Measure", {"Point_A": (10, 0), "Vertex": (0, 0), "Point_C": (10, 10)}).outputs["Angle_Deg"] == pytest.approx(45.0)
    assert run("Angle Measure", {"Point_A": (0, 0), "Vertex": (0, 0), "Point_C": (1, 1)}).status == ToolStatus.NG
    assert run("Angle Measure", {"Point_A": (10, 0), "Vertex": (0, 0), "Point_C": (0, 10)}, min_angle=80, max_angle=85).status == ToolStatus.NG


def test_line_intersection_point_angle_and_parallel_lines():
    r = run("Line Intersection", {"Line1": [0, 10, 100, 10], "Line2": [40, 0, 40, 50]})
    assert r.outputs["Point"] == pytest.approx((40.0, 10.0)) and r.outputs["Angle_Deg"] == pytest.approx(90.0)
    ext = run("Line Intersection", {"Line1": [0, 0, 10, 10], "Line2": [0, 20, 10, 20]})           # they only meet when extended
    assert ext.outputs["Point"] == pytest.approx((20.0, 20.0)) and ext.outputs["Angle_Deg"] == pytest.approx(45.0)
    assert run("Line Intersection", {"Line1": [0, 0, 10, 0], "Line2": [0, 5, 10, 5]}).status == ToolStatus.NG


# ---- location -------------------------------------------------------------------------------
def test_hough_finds_circles_and_lines_and_passes_the_strongest_on():
    img = np.zeros((300, 400, 3), np.uint8)
    cv2.circle(img, (200, 150), 60, (255, 255, 255), 3)
    c = run("Hough Detect", {"Image": img}, mode="Circles", roi=[0, 0, 400, 300], min_radius=30, max_radius=100, min_distance=50, sensitivity=25)
    assert c.status == ToolStatus.OK and c.outputs["Count"] >= 1
    best = c.outputs["Circle"]
    assert abs(best["cx"] - 200) < 6 and abs(best["cy"] - 150) < 6 and abs(best["r"] - 60) < 6
    lines = np.zeros((300, 400, 3), np.uint8)
    cv2.line(lines, (20, 50), (380, 50), (255, 255, 255), 3)
    li = run("Hough Detect", {"Image": lines}, mode="Lines", roi=[0, 0, 400, 300])
    assert li.status == ToolStatus.OK and li.outputs["Line"]["length"] > 300 and abs(li.outputs["Line"]["y1"] - 50) < 4
    off = run("Hough Detect", {"Image": img}, mode="Circles", roi=[250, 200, 100, 80], min_radius=30, max_radius=100)
    assert off.outputs["Count"] == 0 and off.status == ToolStatus.NG, "nothing in that region, and one was required"
    assert run("Hough Detect", {"Image": img}, mode="Circles", roi=[250, 200, 100, 80], min_count=0).status == ToolStatus.OK
    assert run("Hough Detect", {"Image": np.zeros((2, 2), np.uint8)}).status == ToolStatus.NG


# ---- the filters and morphology that gained options ------------------------------------------
def test_new_filter_and_morphology_options():
    img = board()
    for ftype in ("Box", "Unsharp Mask"):
        out = run("Image Filter", {"Image": img}, filter_type=ftype, kernel_size=5).outputs["Image"]
        assert out.shape == img.shape and not (out == img).all(), ftype
    spots = np.zeros((40, 40), np.uint8)
    spots[18:22, 18:22] = 255
    top = run("Image Morphology", {"Image": spots}, operation="Top Hat", kernel_size=9).outputs["Image"]
    assert top[20, 20] == 255, "a small bright spot survives a Top Hat"
    holes = np.full((40, 40), 255, np.uint8)
    holes[18:22, 18:22] = 0
    black = run("Image Morphology", {"Image": holes}, operation="Black Hat", kernel_size=9).outputs["Image"]
    assert black[20, 20] == 255, "a small dark spot survives a Black Hat"


# ---- communication ---------------------------------------------------------------------------
def test_udp_send_delivers_the_message_and_simulation_sends_nothing():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(3)
    port = rx.getsockname()[1]
    sim = run("UDP Send", {"Data": [1, 2.5, "ok"]})
    assert sim.status == ToolStatus.OK and sim.outputs["Last_Message"] == "APEX_RES,1,2.5,ok\r\n"
    real = run("UDP Send", {"Data": [1, 2.5, "ok"]}, mode="UDP", server_port=port)
    assert real.status == ToolStatus.OK
    assert rx.recvfrom(1024)[0] == b"APEX_RES,1,2.5,ok\r\n"
    rx.close()
    assert run("UDP Send", {"Data": 1, "Trigger": False}, mode="UDP", server_port=port).outputs["Sent_Bytes"] == 0
    js = run("UDP Send", {"Data": {"a": 1}}, format="JSON", suffix="")
    assert js.outputs["Last_Message"] == '{"a": 1}'


def test_serial_send_simulation_and_clear_message_without_pyserial():
    sim = run("Serial Send", {"Data": "PASS"})
    assert sim.status == ToolStatus.OK and sim.outputs["Last_Message"] == "APEX_RES,PASS\r\n"
    try:
        import serial  # noqa: F401
    except ImportError:
        r = run("Serial Send", {"Data": "PASS"}, mode="Serial Port")
        assert r.status == ToolStatus.ERROR and "pyserial" in r.message
    else:
        r = run("Serial Send", {"Data": "PASS"}, mode="Serial Port", port_name="COM_DOES_NOT_EXIST")
        assert r.status == ToolStatus.ERROR


def _modbus_server(reply: bytes = None):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got = {}

    def serve():
        conn, _ = srv.accept()
        with conn:
            got["frame"] = conn.recv(260)
            conn.sendall(reply if reply is not None else got["frame"][:12])      # a write is echoed back
        srv.close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    return srv.getsockname()[1], got, th


def test_modbus_write_single_register_frame_is_correct():
    port, got, th = _modbus_server()
    r = run("Modbus TCP Write", {"Data": 12.5}, mode="Modbus TCP", server_port=port, start_address=100, unit_id=7, value_scale=10)
    th.join(3)
    assert r.status == ToolStatus.OK, r.message
    tid, proto, length, unit, func, addr, value = struct.unpack(">HHHBBHH", got["frame"])
    assert (proto, length, unit, func, addr, value) == (0, 6, 7, 6, 100, 125)


def test_modbus_write_multiple_registers_and_coil_and_plc_error():
    port, got, th = _modbus_server()
    r = run("Modbus TCP Write", {"Data": [1, 2, 3]}, mode="Modbus TCP", server_port=port, function="Write Multiple Registers", start_address=5)
    th.join(3)
    assert r.status == ToolStatus.OK
    assert got["frame"][7] == 16 and struct.unpack(">HH", got["frame"][8:12]) == (5, 3) and struct.unpack(">3H", got["frame"][13:19]) == (1, 2, 3)
    port, got, th = _modbus_server()
    run("Modbus TCP Write", {"Data": True}, mode="Modbus TCP", server_port=port, function="Write Single Coil")
    th.join(3)
    assert got["frame"][7] == 5 and got["frame"][10:12] == b"\xff\x00"
    port, got, th = _modbus_server(reply=bytes(7) + b"\x86\x02")                  # exception reply
    r = run("Modbus TCP Write", {"Data": 1}, mode="Modbus TCP", server_port=port)
    th.join(3)
    assert r.status == ToolStatus.ERROR and "refused" in r.message
    assert run("Modbus TCP Write", {"Data": "abc"}).status == ToolStatus.ERROR
    assert run("Modbus TCP Write", {"Data": 1}, mode="Modbus TCP", server_port=1, connect_timeout_ms=200).status == ToolStatus.ERROR


def test_data_log_appends_rows_with_one_header(tmp_path):
    path = str(tmp_path / "sub" / "log.csv")
    t = create_tool_instance("Data Log", "t")
    t.set_param("file_path", path)
    assert t.execute({"Data": {"width": 12.5, "ok": True}}).outputs["Rows_Written"] == 1
    assert t.execute({"Data": {"width": 13.0, "ok": False}}).status == ToolStatus.OK
    rows = list(csv.reader(open(path, encoding="utf-8")))
    assert rows[0] == ["time", "width", "ok"] and len(rows) == 3 and rows[1][1:] == ["12.5", "1"] and rows[2][1:] == ["13", "0"]
    assert t.execute({"Data": 5, "Trigger": False}).outputs["Rows_Written"] == 0 and len(list(csv.reader(open(path)))) == 3
    assert t.execute({}).outputs["Rows_Written"] == 0, "nothing connected: nothing written"
    t.set_param("file_path", str(tmp_path))                                            # a folder, not a file
    assert t.execute({"Data": 1}).status == ToolStatus.ERROR


# ---- they work inside a real flow, and survive saving ---------------------------------------
def test_a_flow_using_the_new_modules_runs_and_round_trips_through_xml(tmp_path):
    from apex_vision.core.pipeline import SolutionManager
    sol = SolutionManager(name="NewTools")
    flow = sol.add_flow("F")
    sol.active_flow_name = flow.name
    src = create_tool_instance("Image Source", "src", "src")
    bri = create_tool_instance("Brightness Contrast", "bri", "bri")
    edge = create_tool_instance("Edge Detection", "edge", "edge")
    crop = create_tool_instance("Image Crop", "crop", "crop")
    for n in (src, bri, edge, crop):
        flow.add_node(n)
    assert flow.connect("src", "Image", "bri", "Image")
    assert flow.connect("bri", "Image", "edge", "Image")
    assert flow.connect("src", "Image", "crop", "Image")
    results = flow.execute_flow(global_vars=sol.global_variables)
    assert all(results[i].status == ToolStatus.OK for i in ("src", "bri", "edge", "crop")), {k: v.message for k, v in results.items()}
    path = str(tmp_path / "new.apex")
    sol.save_to_file(path)
    back = SolutionManager.load_from_file(path).get_active_flow()
    assert [n.tool_name for n in back.nodes.values()] == ["Image Source", "Brightness Contrast", "Edge Detection", "Image Crop"]
    assert back.nodes["bri"].get_param("mode") == "Auto Brighten"


def test_the_module_reference_page_is_up_to_date():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import gen_module_reference
    with open(gen_module_reference.os.path.join(gen_module_reference.ROOT, "docs", "MODULES.md"), encoding="utf-8") as f:
        assert f.read().replace("\r\n", "\n") == gen_module_reference.render(), "run: python scripts/gen_module_reference.py"


# ---- Linear Edge Defect really measures the edge ---------------------------------------------
def edge_image(bump=None, notch=None, slope=0.0):
    img = np.full((200, 400, 3), 30, np.uint8)
    for x in range(400):
        y = int(100 + slope * x)
        img[y:, x] = 200                                       # bright material below the edge
    if bump:
        x0, x1, h = bump
        for x in range(x0, x1):
            img[int(100 + slope * x) - h:int(100 + slope * x), x] = 200
    if notch:
        x0, x1, d = notch
        for x in range(x0, x1):
            img[int(100 + slope * x):int(100 + slope * x) + d, x] = 30
    return img


def edge_run(img, **kw):
    params = dict(start_pt=[20, 100], end_pt=[380, 100], search_width=15, edge_threshold=20, max_allowed_deviation=3.0)
    params.update(kw)
    return run("Linear Edge Defect", {"Image": img}, **params)


def test_linear_edge_defect_passes_a_straight_edge_and_reports_the_real_deviation():
    r = edge_run(edge_image())
    assert r.status == ToolStatus.OK and r.outputs["Burr_Count"] == 0 and r.outputs["Max_Deviation"] < 1.0
    tilted = edge_run(edge_image(slope=0.05), end_pt=[380, 119])           # a slanted but straight edge is still straight
    assert tilted.status == ToolStatus.OK and tilted.outputs["Max_Deviation"] < 1.5


def test_linear_edge_defect_finds_bumps_and_notches_and_counts_each_one():
    one = edge_run(edge_image(bump=(150, 165, 7)))
    assert one.status == ToolStatus.NG and one.outputs["Burr_Count"] == 1 and 5.5 <= one.outputs["Max_Deviation"] <= 8
    two = edge_run(edge_image(bump=(100, 110, 6), notch=(250, 262, 6)))
    assert two.status == ToolStatus.NG and two.outputs["Burr_Count"] == 2
    small = edge_run(edge_image(bump=(150, 165, 2)))
    assert small.status == ToolStatus.OK, "a 2 px bump is inside the 3 px tolerance"
    strict = edge_run(edge_image(bump=(150, 165, 2)), max_allowed_deviation=1.0)
    assert strict.status == ToolStatus.NG


def test_linear_edge_defect_says_so_when_there_is_no_edge_or_no_line():
    flat = edge_run(np.full((200, 400, 3), 90, np.uint8))
    assert flat.status == ToolStatus.NG and "No edge found" in flat.message
    assert edge_run(edge_image(), end_pt=[22, 100]).status == ToolStatus.NG
    broken = create_tool_instance("Linear Edge Defect", "t")
    broken.parameters["start_pt"] = "not a point"                     # e.g. a hand-edited project file
    assert broken.execute({"Image": edge_image()}).status == ToolStatus.ERROR


# ---- general-purpose naming ------------------------------------------------------------------
def test_board_specific_modules_are_not_offered_but_old_projects_still_load():
    from apex_vision.core.registry import list_categories
    from apex_vision.flowgen.catalog import full_catalog
    offered = {t for tools in list_categories().values() for t in tools}
    assert "PCB Board Layout" not in offered and "PCB Defect Detection" not in offered
    assert not {"PCB Board Layout", "PCB Defect Detection"} & {s["tool"] for s in full_catalog()}
    assert "PCB Defect Detection" in list_all_tools(), "still loadable, for saved flows and the evaluation demo"
    assert create_tool_instance("PCB Defect Detection", "t").toolbox_hidden


def test_the_synthetic_test_pattern_has_a_general_name_and_the_old_name_still_draws_the_same_picture():
    new = run("Image Source", {}, source_type="Synthetic", pattern_type="Part with Defects").outputs["Image"]
    old = create_tool_instance("Image Source", "t")
    old.parameters["pattern_type"] = "PCB Inspection"            # what a project saved by an earlier build contains
    assert (old.execute({}).outputs["Image"] == new).all()


def test_no_toolbox_module_or_menu_text_is_tied_to_one_product():
    import re
    names = [n for n in list_all_tools() if not create_tool_instance(n, "t").toolbox_hidden]
    assert not [n for n in names if re.search(r"pcb|circuit|solder", n, re.I)], names
    from apex_vision.core import param_schema as ps
    for n in names:
        for k, v in create_tool_instance(n, "t").parameters.items():
            if k != "file_path":                                       # the bundled sample picture is a board; that is only sample content
                assert not (isinstance(v, str) and re.search(r"pcb", v, re.I)), (n, k, v)


def test_a_project_saved_with_the_old_pattern_name_loads_under_the_new_one():
    t = create_tool_instance("Image Source", "t")
    t.load_dict({"parameters": {"pattern_type": "PCB Inspection"}})
    assert t.parameters["pattern_type"] == "Part with Defects"


def test_a_project_saved_without_its_plugin_keeps_the_plugin_modules_untouched(tmp_path):
    """Opening a project whose plugin is not installed, then saving, must not rewrite the plugin's modules."""
    from apex_vision.core.pipeline import SolutionManager
    sol = SolutionManager(name="P")
    flow = sol.add_flow("F")
    sol.active_flow_name = flow.name
    node = create_tool_instance("Image Source", "a", "a")
    flow.add_node(node)
    path = str(tmp_path / "p.apex")
    sol.save_to_file(path)
    text = open(path, encoding="utf-8").read().replace('tool_name="Image Source"', 'tool_name="Some Plugin Tool"').replace(
        'category="Acquisition"', 'category="Earth Observation"')
    open(path, "w", encoding="utf-8").write(text)
    again = SolutionManager.load_from_file(path)
    out = str(tmp_path / "again.apex")
    again.save_to_file(out)
    saved = open(out, encoding="utf-8").read()
    assert 'tool_name="Some Plugin Tool"' in saved and 'category="Earth Observation"' in saved and "Missing Plugin" not in saved.replace('tool_name="Some Plugin Tool"', "")
