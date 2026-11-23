"""Regression tests for bugs identified and fixed during full-component Apex Vision audit."""
import os
import sys
import tempfile

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.camera_manager import (
    CameraDeviceInfo,
    CameraManager,
    OpenCVCameraDriver,
    StreamCameraDriver,
)
from apex_vision.core.overlays import render_overlays
from apex_vision.core.pipeline import VisionPipeline
from apex_vision.core.registry import create_tool_instance
from apex_vision.flowgen.catalog import tool_spec
from apex_vision.server import FlowService


# ---------------------------------------------------------------------------
# 1. Camera drivers & multi-RTSP isolation
# ---------------------------------------------------------------------------
def test_opencv_webcam_driver_capture_does_not_require_stream_url():
    class FakeCap:
        def isOpened(self):
            return True

        def set(self, prop, val):
            return True

        def read(self):
            return True, np.full((8, 8, 3), 64, dtype=np.uint8)

    drv = OpenCVCameraDriver(CameraDeviceInfo("webcam_0", "cam", "USB/Webcam"), 0)
    drv._cap = FakeCap()
    drv.is_connected = True
    assert not hasattr(drv, "stream_url")
    ok, frame, msg = drv.capture_frame()
    assert ok is True and frame is not None and msg == "OK"


def test_parallel_ip_streams_get_distinct_persistent_drivers():
    cm = CameraManager.get_instance()
    d1 = cm.get_or_create_driver("ip_stream_custom", stream_url="rtsp://127.0.0.1:8554/cam1")
    d2 = cm.get_or_create_driver("ip_stream_custom", stream_url="rtsp://127.0.0.1:8554/cam2")
    assert isinstance(d1, StreamCameraDriver)
    assert isinstance(d2, StreamCameraDriver)
    assert d1 is not d2
    assert d1.stream_url.endswith("/cam1")
    assert d2.stream_url.endswith("/cam2")
    d1_again = cm.get_or_create_driver("ip_stream_custom", stream_url="rtsp://127.0.0.1:8554/cam1")
    assert d1_again is d1


def test_stream_driver_unreachable_opens_once_with_fast_timeout(monkeypatch):
    seen = []

    class UnopenedCap:
        def isOpened(self):
            return False

        def release(self):
            pass

    def fake_cap(*args, **kwargs):
        seen.append(args)
        return UnopenedCap()

    monkeypatch.setattr("apex_vision.core.camera_manager.cv2.VideoCapture", fake_cap)
    drv = StreamCameraDriver(
        CameraDeviceInfo("ip_test", "RTSP", "IP/RTSP Stream"),
        stream_url="rtsp://127.0.0.1:9999/none",
    )
    ok, frame, msg = drv.capture_frame()
    assert ok is False and frame is None
    assert len(seen) == 1
    if len(seen[0]) >= 3:
        params = seen[0][2]
        assert cv2.CAP_PROP_OPEN_TIMEOUT_MSEC in params
    drv.close()


# ---------------------------------------------------------------------------
# 2. Theft-recognition plugin multi-channel & dtype fuzz resilience
# ---------------------------------------------------------------------------
def test_theft_recognition_plugin_handles_5ch_and_float32_frames():
    from apex_vision.sdk.manager import PluginManager

    PluginManager.get_instance().discover_and_load_all()
    for tool_name in ("Motion Gate", "Behavior Gate"):
        tool = create_tool_instance(tool_name, f"fuzz_{tool_name}")
        for img in (
            np.zeros((24, 24, 5), dtype=np.uint8),
            np.ones((24, 24, 4), dtype=np.float32) * 128.0,
        ):
            res = tool.execute({"Image": img})
            assert res is not None

    from plugins.theft_recognition_plugin.vlm_module_tool import _encode_image_b64

    b64_5 = _encode_image_b64(np.zeros((24, 24, 5), dtype=np.uint8))
    b64_f = _encode_image_b64(np.ones((24, 24, 3), dtype=np.float32) * 120.0)
    assert isinstance(b64_5, str) and len(b64_5) > 0
    assert isinstance(b64_f, str) and len(b64_f) > 0


# ---------------------------------------------------------------------------
# 3. Overlays hex colour & sliced translucent alpha blending
# ---------------------------------------------------------------------------
def test_overlays_render_hex_colours_as_exact_bgr_and_alpha_roi():
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    out = render_overlays(
        img,
        [
            {"type": "rect", "box": (4, 4, 12, 12), "color": "#e0585c", "thickness": 2},
            {"type": "rect", "box": (22, 22, 10, 10), "color": "#00f", "alpha": 0.5, "thickness": 0},
        ],
    )
    assert out is not None
    # "#e0585c" -> R=224, G=88, B=92 -> OpenCV BGR (92, 88, 224)
    assert tuple(int(c) for c in out[4, 4]) == (92, 88, 224)
    # "#00f" -> R=0, G=0, B=255 -> OpenCV BGR (255, 0, 0) with 0.5 alpha over 0 -> ~128
    pixel_inside = tuple(int(c) for c in out[27, 27])
    assert pixel_inside[2] == 0 and pixel_inside[1] == 0 and 125 <= pixel_inside[0] <= 130
    # Outside both boxes remains untouched black
    assert tuple(int(c) for c in out[0, 0]) == (0, 0, 0)


# ---------------------------------------------------------------------------
# 4. Pipeline Group duplication & ImageBuffer NG Only
# ---------------------------------------------------------------------------
def test_pipeline_duplicate_preserves_group_memberships():
    pipe = VisionPipeline("Orig")
    grp = create_tool_instance("Group", "grp1", "01_Group")
    step = create_tool_instance("Image Filter", "flt1", "02_Filter")
    step.group = "grp1"
    pipe.add_node(grp)
    pipe.add_node(step)
    pipe.connect("grp1", "Image", "flt1", "Image")
    assert pipe.group_members("grp1") == ["flt1"]

    dup = pipe.duplicate("Dup")
    dup_grp = next(n for n in dup.nodes.values() if n.tool_name == "Group")
    dup_step = next(n for n in dup.nodes.values() if n.tool_name == "Image Filter")
    assert dup_step.group == dup_grp.instance_id
    assert dup.group_members(dup_grp.instance_id) == [dup_step.instance_id]


def test_image_buffer_ng_only_skips_ok_and_caches_ng():
    buf = create_tool_instance("Image Buffer", "buf1")
    buf.set_param("buffer_condition", "NG Only")
    img_ok = np.full((16, 16, 3), 10, dtype=np.uint8)
    img_ng = np.full((16, 16, 3), 200, dtype=np.uint8)

    r_ok = buf.execute({"Image": img_ok, "Result": "OK"})
    assert r_ok.status == ToolStatus.OK
    assert r_ok.outputs["Buffer_Count"] == 0

    r_ng = buf.execute({"Image": img_ng, "Result": "NG"})
    assert r_ng.status == ToolStatus.OK
    assert r_ng.outputs["Buffer_Count"] == 1
    assert np.array_equal(r_ng.outputs["Latest_Image"], img_ng)


# ---------------------------------------------------------------------------
# 5. Server & FlowGen honor plugin ParamDef schemas
# ---------------------------------------------------------------------------
def test_server_and_flowgen_expose_plugin_param_defs(tmp_path):
    from apex_vision.sdk.manager import PluginManager

    PluginManager.get_instance().discover_and_load_all()
    spec = tool_spec("Motion Gate")
    assert spec["parameters"]["ratio_thresh"]["min"] == pytest.approx(0.0001)
    assert spec["parameters"]["ratio_thresh"]["max"] == pytest.approx(0.5)

    sol_path = tmp_path / "plug_demo.apex"
    from apex_vision.core.pipeline import SolutionManager

    sol = SolutionManager("PlugDemo")
    pipe = VisionPipeline("Flow1")
    mg = create_tool_instance("Motion Gate", "mg1", "01_MotionGate")
    pipe.add_node(mg)
    sol.flows["Flow1"] = pipe
    sol.active_flow_name = "Flow1"
    sol.save_to_file(str(sol_path))

    svc = FlowService(str(tmp_path))
    desc = svc.describe("plug_demo")
    mg_params = desc["flows"][0]["modules"][0]["parameters"]
    assert mg_params["ratio_thresh"]["min"] == pytest.approx(0.0001)
    assert mg_params["ratio_thresh"]["max"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 6. FrameProvider BGR888, AppBackend undo/outputs/display & QML UI fixes
# ---------------------------------------------------------------------------
def test_frame_provider_bgr888_preserves_channel_order_and_handles_variants():
    pytest.importorskip("PyQt6.QtQml")
    from PyQt6.QtGui import QGuiApplication
    from apex_vision.qml_backend import FrameProvider

    QGuiApplication.instance() or QGuiApplication(sys.argv)
    prov = FrameProvider()

    # Pure red pixel in OpenCV BGR is (0, 0, 255)
    bgr = np.zeros((4, 4, 3), dtype=np.uint8)
    bgr[1, 2] = (0, 0, 255)
    bgr[2, 1] = (255, 0, 0)
    prov.set_array(bgr)
    c_red = prov.image.pixelColor(2, 1)
    c_blue = prov.image.pixelColor(1, 2)
    assert (c_red.red(), c_red.green(), c_red.blue()) == (255, 0, 0)
    assert (c_blue.red(), c_blue.green(), c_blue.blue()) == (0, 0, 255)

    # 2D grayscale & 5-channel float32 do not crash
    prov.set_array(np.full((4, 4), 123, dtype=np.uint8))
    assert prov.image.width() == 4
    prov.set_array(np.full((4, 4, 5), 50.0, dtype=np.float32))
    assert prov.image.width() == 4


def test_backend_undo_module_outputs_and_display(tmp_path):
    pytest.importorskip("PyQt6.QtQml")
    from PyQt6.QtGui import QGuiApplication
    from apex_vision.core.pipeline import SolutionManager
    from apex_vision.core.project_manager import ProjectManager
    from apex_vision.qml_backend import AppBackend, FrameProvider

    QGuiApplication.instance() or QGuiApplication(sys.argv)
    pm = ProjectManager(workspace_root=str(tmp_path))
    be = AppBackend(FrameProvider(), pm)
    demo = os.path.join(os.path.dirname(__file__), "..", "projects", "PCB_Inspection_Demo.apex")
    be.load_solution(SolutionManager.load_from_file(demo), demo)
    be.engine.wait_for_run()
    QGuiApplication.processEvents()

    first_id = be.nodes[0]["id"]
    outputs = be.moduleOutputs(first_id)
    assert outputs and any(o["name"] == "Image" and o["value"].startswith("Image (") for o in outputs)

    # moduleDisplay reads requested node even when another node is selected
    second_id = be.nodes[1]["id"]
    be.setModuleDisplay(first_id, "colour", "#e0585c")
    be.selectNode(second_id)
    assert be.moduleDisplay(first_id)["colour"] == "#e0585c"

    # undo removes stale entries from _last_results
    be.addTool("Image Filter")
    flt_id = be._selected
    be.engine.wait_for_run()
    QGuiApplication.processEvents()
    assert flt_id in be._last_results
    be.undo()
    assert flt_id not in be._last_results


def test_qml_dialog_confirm_datatable_flyout_flowsettings_and_layout():
    pytest.importorskip("PyQt6.QtQml")
    import socket
    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    from apex_vision.core import comm_manager as cm
    from test_qml_interaction import Ui

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free_port = s.getsockname()[1]
    s.close()

    ui = Ui()
    ui.reset()
    ui.settle()
    seen = []

    def handler(kind, ctx, msg):
        if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            seen.append(msg)

    qInstallMessageHandler(handler)
    try:
        # 1. Dirty NewProjectDialog must open ConfirmDialog instead of closing it
        ui.be.setGlobal("g_DirtyTest", "Integer", "7")
        ui.host.show("newProject")
        ui.spin(20)
        ui.be.createProject("DirtyChild", ui.be.projectsFolder, 0)
        # Simulate dialog emitted created() right after createProject()
        new_proj = next(c for c in ui.of_type("NewProjectDialog"))
        new_proj.created.emit("DirtyChild", ui.be.projectsFolder, 0)
        ui.spin(20)
        assert ui.dialog == "confirm"
        assert ui.be._pending is not None
        ui.be.confirmCancel()
        ui.host.close()
        ui.spin(20)

        # 2. DataTable clamps currentRow to -1 on empty rows; Comm delete doesn't TypeError
        cm.get_manager().load([])
        ui.host.show("comm")
        ui.spin(20)
        err = ui.be.addCommDevice("tmp_tcp", "TCP Server", "127.0.0.1", free_port, "\\n", "", False, "")
        assert err == ""
        ui.spin(20)
        comm_dlg = next(c for c in ui.of_type("CommunicationDialog"))
        tbl = next(c for c in ui.walk(comm_dlg) if c.metaObject().className().startswith("DataTable"))
        tbl.setProperty("currentRow", 0)
        del_btn = next(c for c in ui.walk(comm_dlg) if c.property("objectName") == "commDelete")
        del_btn.clicked.emit()
        ui.spin(20)
        assert tbl.property("currentRow") == -1
        del_btn.clicked.emit()  # second click must not throw TypeError
        ui.spin(10)
        ui.host.close()
        cm.get_manager().load([])

        # 3. ToolFlyout is clipped and has a Flickable
        ui.main.setProperty("railCategory", 0)
        ui.spin(20)
        flyout = next(c for c in ui.of_type("ToolFlyout"))
        assert flyout.property("clip") is True
        flicks = [c for c in ui.walk(flyout) if c.metaObject().className().startswith("QQuickFlickable")]
        assert flicks
        ui.main.setProperty("railCategory", -1)

        # 4. FlowSettingsDialog resets cancelled edits when reopened
        ui.host.show("flowSettings")
        ui.spin(20)
        fs_dlg = next(c for c in ui.of_type("FlowSettingsDialog"))
        nb = next(c for c in ui.walk(fs_dlg) if c.metaObject().className().startswith("NumberBox"))
        orig_val = nb.property("value")
        nb.setProperty("value", orig_val + 123)
        ui.host.close()
        ui.spin(15)
        ui.host.show("flowSettings")
        ui.spin(15)
        assert nb.property("value") == orig_val
        ui.host.close()

        # 5. resultPage height matches image header + viewport + readout
        rp = next(c for c in ui.walk() if c.property("objectName") == "resultPage")
        vp = next(c for c in ui.walk() if c.property("objectName") == "viewportRect")
        assert rp.height() == pytest.approx(vp.height() + 28 + 22, abs=1.0)

        # 6. SelectBox handles currentIndex = -1 without warnings
        sb = next(c for c in ui.of_type("SelectBox"))
        sb.setProperty("currentIndex", -1)
        ui.spin(10)
        assert sb.property("currentText") == ""
        sb.setProperty("currentIndex", 0)
    finally:
        qInstallMessageHandler(None)
        ui.w.close()
        ui.app.processEvents()

    bad = [m for m in seen if "libpng" not in m and "QFont::" not in m]
    assert not bad, bad
