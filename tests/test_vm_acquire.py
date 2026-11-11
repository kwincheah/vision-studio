"""VisionMaster guide, Acquisition chapter: Multi-image Acquisition and Light Source."""
import socket
import threading

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance
from apex_vision.tools import vm_acquire as va


def make(tool_name, /, **params):
    t = create_tool_instance(tool_name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t


def run(tool_name, ctx=None, /, **params):
    return make(tool_name, **params).execute(ctx or {})


# ---- Light Source ----------------------------------------------------------------------------------------------------------------------------------------------
def test_commands_come_from_the_template():
    assert va.build_commands("SA{channel}{brightness:04d}#", [1, 2], [128, 5]) == ["SA10128#", "SA20005#"]
    assert va.build_commands("CH{channel}={brightness}\\r\\n", [3], [200]) == ["CH3=200\r\n"]
    assert va.build_commands("{brightness:x}", [1], [255]) == ["ff"]
    assert va.build_commands("{brightness:zz}", [1], [7]) == ["7"], "a format that does not fit falls back to the plain number"
    assert va.build_commands("{other}", [1], [7]) == ["{other}"]


def test_light_source_simulation_and_checks():
    r = run("Light Source", brightness="100, 200")
    assert r.status == ToolStatus.OK and r.outputs["Commands"] == ["SA10100#", "SA20200#"] and r.outputs["Levels"] == [100, 200] and r.outputs["Sent"] == 1
    one = run("Light Source", channels="1,2,3", brightness="50")
    assert one.outputs["Levels"] == [50, 50, 50], "a single brightness goes to every channel"
    wired = run("Light Source", {"Brightness": [10, 20]})
    assert wired.outputs["Levels"] == [10, 20]
    assert run("Light Source", {"Brightness": 90}, channels="1,2").outputs["Levels"] == [90, 90]
    assert run("Light Source", channels="").status == ToolStatus.ERROR
    assert run("Light Source", channels="a").status == ToolStatus.ERROR
    assert run("Light Source", brightness="").status == ToolStatus.ERROR
    assert run("Light Source", brightness="1,2,3").status == ToolStatus.ERROR
    assert run("Light Source", brightness="300,0").status == ToolStatus.ERROR
    assert run("Light Source", {"Brightness": "abc"}).status == ToolStatus.ERROR


def test_light_source_over_tcp_reaches_the_controller():
    got = []
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        c, _ = srv.accept()
        c.settimeout(2)
        buf = b""
        try:
            while True:
                d = c.recv(100)
                if not d:
                    break
                buf += d
        except OSError:
            pass
        got.append(buf)
        c.close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    r = run("Light Source", device="TCP Network", host="127.0.0.1", tcp_port=port, brightness="10,20", trigger_time_ms=20, off_after_trigger=True)
    th.join(3)
    srv.close()
    assert r.status == ToolStatus.OK, r.message
    assert got[0] == b"SA10010#SA20020#", "the commands went out together"
    assert r.outputs["Commands"][-2:] == ["SA10000#", "SA20000#"] and "off" in r.message


def test_light_source_reports_a_controller_that_cannot_be_reached():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free = s.getsockname()[1]
    s.close()
    r = run("Light Source", device="TCP Network", host="127.0.0.1", tcp_port=free)
    assert r.status == ToolStatus.ERROR and "could not reach" in r.message and r.outputs["Sent"] == 0
    assert run("Light Source", device="TCP Network", host="").status == ToolStatus.ERROR
    assert run("Light Source", device="Serial Port", port_name="").status == ToolStatus.ERROR
    ser = run("Light Source", device="Serial Port", port_name="NOT_A_PORT")
    assert ser.status == ToolStatus.ERROR and ("not installed" in ser.message or "could not reach" in ser.message)


# ---- Multi-image Acquisition ----------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def folder(tmp_path):
    for i in range(5):
        cv2.imwrite(str(tmp_path / f"img_{i}.png"), np.full((20 + i, 30), 10 * i + 10, np.uint8))
    (tmp_path / "notes.txt").write_text("not a picture")
    return tmp_path


def test_local_images_advance_through_the_folder(folder):
    t = make("Multi-image Acquisition", image_path=str(folder), fetch_quantity=3)
    first = t.execute({})
    assert first.status == ToolStatus.OK and first.outputs["Count"] == 3
    assert [int(first.outputs[f"Image{i}"][0, 0, 0]) for i in (1, 2, 3)] == [10, 20, 30]
    assert first.outputs["Image4"] is None and len(first.outputs["Images"]) == 3
    second = t.execute({})
    assert [int(v[0, 0, 0]) for v in second.outputs["Images"]] == [40, 50, 10], "the next pictures, wrapping round to the start"
    t.execute({"Clear": True})
    assert [int(v[0, 0, 0]) for v in t.execute({"Clear": True}).outputs["Images"]] == [10, 20, 30]
    short = run("Multi-image Acquisition", image_path=str(folder), fetch_quantity=8)
    assert short.status == ToolStatus.ERROR and "5 picture(s) found but 8" in short.message


def test_local_images_from_a_file_list_and_problems(folder):
    names = ";".join(str(folder / f"img_{i}.png") for i in (4, 3, 2))
    r = run("Multi-image Acquisition", image_path=names, fetch_quantity=3)
    assert [int(v[0, 0, 0]) for v in r.outputs["Images"]] == [50, 40, 30], "the order given is kept"
    assert run("Multi-image Acquisition", image_path=str(folder / "nothing"), fetch_quantity=3).status == ToolStatus.ERROR
    assert run("Multi-image Acquisition", image_path="", fetch_quantity=3).status == ToolStatus.ERROR
    corrupt = folder / "img_9.png"
    corrupt.write_bytes(b"not a png")
    assert run("Multi-image Acquisition", image_path=f"{folder / 'img_0.png'};{folder / 'img_1.png'};{corrupt}", fetch_quantity=3).status in (ToolStatus.NG, ToolStatus.ERROR)


def test_camera_pictures_use_each_exposure_and_gain():
    from apex_vision.core.camera_manager import CameraManager
    drv = CameraManager.get_instance().get_or_create_driver("virtual_gige_0")
    calls = []
    orig_e, orig_g = drv.set_exposure, drv.set_gain
    drv.set_exposure = lambda v: calls.append(("e", v)) or orig_e(v)
    drv.set_gain = lambda v: calls.append(("g", v)) or orig_g(v)
    try:
        r = run("Multi-image Acquisition", image_source="Camera", camera_device="virtual_gige_0", fetch_quantity=4, fetch_interval_ms=0, exposures="1000,2000,4000", gains="1,2")
    finally:
        drv.set_exposure, drv.set_gain = orig_e, orig_g
    assert r.status == ToolStatus.OK, r.message
    assert r.outputs["Count"] == 4 and all(isinstance(im, np.ndarray) for im in r.outputs["Images"])
    assert [v for k, v in calls if k == "e"] == [1000.0, 2000.0, 4000.0, 4000.0], "a short list repeats its last value"
    assert [v for k, v in calls if k == "g"] == [1.0, 2.0, 2.0, 2.0]


def test_lights_follow_each_picture_and_angles_are_passed_on(folder):
    r = run("Multi-image Acquisition", image_path=str(folder), fetch_quantity=3, light_enable=True, light_channel=2, light_levels="10,200,255", distribution_angle=45.0,
            illumination_angle=30.0)
    assert r.outputs["Light_Commands"] == ["SA20010#", "SA20200#", "SA20255#"]
    assert r.outputs["Distribution_Angle"] == 45.0 and r.outputs["Illumination_Angle"] == 30.0
    assert run("Multi-image Acquisition", image_path=str(folder), fetch_quantity=3, light_enable=True, light_levels="999").status == ToolStatus.ERROR
    assert run("Multi-image Acquisition", image_path=str(folder), fetch_quantity=3, light_enable=True, light_levels="x").status == ToolStatus.ERROR
    down = run("Multi-image Acquisition", image_path=str(folder), fetch_quantity=3, light_enable=True, light_device="TCP Network", light_host="")
    assert down.status == ToolStatus.ERROR


def test_camera_problems():
    assert run("Multi-image Acquisition", image_source="Camera", camera_device="no_such_camera").status == ToolStatus.ERROR
    assert run("Multi-image Acquisition", image_source="Camera", camera_device="").status == ToolStatus.ERROR
    assert run("Multi-image Acquisition", image_source="Camera", camera_device="virtual_gige_0", exposures="abc").status == ToolStatus.ERROR


@pytest.mark.parametrize("tool_name", ["Light Source", "Multi-image Acquisition"])
def test_junk_input_never_crashes(tool_name):
    for ctx in ({}, {"Brightness": object(), "Clear": "x"}, {"Brightness": [[1, 2], [3]]}):
        r = create_tool_instance(tool_name, "t").execute(ctx)
        assert r.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR) and r.message is not None
