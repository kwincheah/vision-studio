"""Tests for modular Vision Tracking & VLM Suite, ROI Zone Manager, Script prompt/verdict decoupling, and RTSP flow."""
from __future__ import annotations

import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core import param_schema as ps
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.camera_manager import CameraDeviceInfo, StreamCameraDriver
from apex_vision.core.pipeline import SolutionManager
from apex_vision.core.registry import create_tool_instance, list_categories
from apex_vision.sdk.manager import PluginManager, PluginState

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(ROOT, "plugins", "theft_recognition_plugin")
PROJECT_PATH = os.path.join(ROOT, "projects", "Theft_Recognition_RTSP.apex")


@pytest.fixture
def loaded_theft_plugin():
    pm = PluginManager.get_instance()
    was_loaded = (
        pm.get_plugin("theft_recognition_plugin") is not None
        and pm.get_plugin("theft_recognition_plugin").state == PluginState.LOADED
    )
    rec = pm.load_plugin_from_directory(PLUGIN_DIR, reload=True)
    assert rec is not None and rec.state == PluginState.LOADED, getattr(rec, "error_message", "load failed")
    yield rec
    if not was_loaded:
        pm.unload_plugin("theft_recognition_plugin")


def test_modular_plugin_exports_four_decoupled_tools(loaded_theft_plugin):
    cats = list_categories()
    assert "ROI Zone Manager" in cats.get("ROI & Zones", [])
    assert "YOLO Pose" in cats.get("Theft Recognition", [])
    assert "BoT-SORT Tracker" in cats.get("Theft Recognition", [])
    assert "VLM" in cats.get("Theft Recognition", [])

    # Built-in param_schema.SCHEMA must stay strictly built-in
    for name in ("ROI Zone Manager", "YOLO Pose", "BoT-SORT Tracker", "VLM"):
        assert name not in ps.SCHEMA

    roi_mgr = create_tool_instance("ROI Zone Manager", "t_roi")
    pose = create_tool_instance("YOLO Pose", "t_pose")
    botsort = create_tool_instance("BoT-SORT Tracker", "t_bot")
    vlm = create_tool_instance("VLM", "t_vlm")

    assert ps.spec_for_tool(roi_mgr, "zones", roi_mgr.get_param("zones"))["kind"] == "roi_list"
    assert ps.spec_for_tool(botsort, "tracker_type", botsort.get_param("tracker_type"))["kind"] == "enum"
    assert ps.spec_for_tool(vlm, "provider", vlm.get_param("provider"))["kind"] == "enum"

    for tool in (roi_mgr, pose, botsort, vlm):
        for key, val in tool.parameters.items():
            assert ps.problem_for_tool(tool, key, val, val) is None


def test_roi_zone_manager_dynamic_ports_draw_rename_delete_and_autodisconnect(loaded_theft_plugin):
    from PyQt6.QtWidgets import QApplication
    from apex_vision.qml_backend import AppBackend, FrameProvider

    QApplication.instance() or QApplication([])
    b = AppBackend(FrameProvider())

    roi_mgr = create_tool_instance("ROI Zone Manager", "n_roi", "ROI_Zones")
    scr = create_tool_instance("Script", "n_scr", "Script_1")
    b._pipeline.add_node(roi_mgr)
    b._pipeline.add_node(scr)

    # Default ports include shelf and aisle
    assert "shelf" in roi_mgr.outputs and "aisle" in roi_mgr.outputs
    assert b._pipeline.connect("n_roi", "shelf", "n_scr", "Data3")
    assert b._pipeline.connect("n_roi", "aisle", "n_scr", "Data4")
    assert len(b._pipeline.connections) == 2

    # Interactive draw on row 0 ("shelf") via zones:0
    assert b.beginDrawParam("n_roi", "zones:0") is True
    assert b.commitDrawParam([100, 40, 220, 300]) is True
    assert roi_mgr.parameters["zones"][0]["rect"] == [100, 40, 220, 300]

    # Add a 3rd named ROI + rename row 1 ("aisle" -> "corridor") -> old "aisle" link auto-disconnects
    b.setParamValue("n_roi", "zones", [
        {"name": "shelf", "rect": [100, 40, 220, 300]},
        {"name": "corridor", "rect": [50, 20, 320, 380]},
        {"name": "cashier", "rect": [400, 50, 120, 180]},
    ])
    assert "shelf" in roi_mgr.outputs
    assert "corridor" in roi_mgr.outputs
    assert "cashier" in roi_mgr.outputs
    assert "aisle" not in roi_mgr.outputs
    # Global variables must NOT be polluted
    assert "shelf" not in b._solution.global_variables
    assert "cashier" not in b._solution.global_variables
    # Stale "aisle" wire was dropped while "shelf" wire remained
    remaining_ports = [(c.from_port, c.to_port) for c in b._pipeline.connections]
    assert remaining_ports == [("shelf", "Data3")]

    # Delete "shelf" -> remaining wire auto-disconnects
    b.setParamValue("n_roi", "zones", [{"name": "corridor", "rect": [50, 20, 320, 380]}])
    assert b._pipeline.connections == []

    # Execute outputs each named ROI plus Named_ROIs dict
    res = roi_mgr.execute({"Image": np.zeros((420, 640, 3), dtype=np.uint8)})
    assert res.status == ToolStatus.OK
    assert res.outputs["corridor"] == [50, 20, 320, 380]
    assert res.outputs["Named_ROIs"] == {"corridor": [50, 20, 320, 380]}
    assert res.outputs["Zone_Count"] == 1


def test_yolo_pose_and_botsort_tracker_decoupled_execution(loaded_theft_plugin):
    pose = create_tool_instance("YOLO Pose", "p_node")
    botsort = create_tool_instance("BoT-SORT Tracker", "b_node")
    frame = np.zeros((320, 480, 3), dtype=np.uint8)

    # Stateless pose run on blank frame + BoT-SORT tracker run
    r_pose = pose.execute({"Image": frame})
    assert r_pose.status == ToolStatus.OK
    assert r_pose.outputs["Count"] == 0

    r_bot0 = botsort.execute({"Image": frame, "Detections": r_pose.outputs["Detections"], "Keypoints": r_pose.outputs["Keypoints"]})
    assert r_bot0.status == ToolStatus.OK
    assert r_bot0.outputs["Tracked_Count"] == 0

    # Pure BoT-SORT tracks synthetic/upstream Detections + Keypoints consistently across frames
    botsort.reset_tracker()
    det_frame = [
        {"Index": 0, "Class": "person", "Score": 0.91, "Box": [120, 60, 90, 220], "Keypoints": [[165, 90, 0.9]] * 17}
    ]
    r1 = botsort.execute({"Image": frame, "Detections": det_frame})
    r2 = botsort.execute({"Image": frame, "Detections": det_frame})
    assert r1.status == ToolStatus.OK and r2.status == ToolStatus.OK
    assert r1.outputs["Tracked_Count"] == 1
    assert r2.outputs["Tracked_Count"] == 1
    tid1 = r1.outputs["Tracks"][0]["track_id"]
    tid2 = r2.outputs["Tracks"][0]["track_id"]
    assert tid1 == tid2
    assert len(r2.outputs["Tracks"][0]["keypoints"]) == 17

    # Reset clears active track IDs cleanly
    r_rst = botsort.execute({"Image": frame, "Detections": [], "Reset": True})
    assert r_rst.status == ToolStatus.OK
    assert r_rst.outputs["Tracked_Count"] == 0


def test_generic_vlm_module_async_prompt_and_image_preservation(loaded_theft_plugin):
    vlm = create_tool_instance("VLM", "v_node")
    grid = np.full((256, 384, 3), 120, dtype=np.uint8)
    raw_later = np.full((256, 384, 3), 25, dtype=np.uint8)

    # 1. Trigger=False keeps VLM IDLE without calling API
    r_idle = vlm.execute({"Image": raw_later, "Prompt": "check this", "Trigger": False})
    assert r_idle.status == ToolStatus.OK
    assert r_idle.outputs["Status"] == "IDLE"
    assert r_idle.outputs["Has_Response"] is False

    # 2. Dry-run echoes inputs cleanly
    vlm_dry = create_tool_instance("VLM", "v_dry")
    vlm_dry.set_param("mode", "Dry-Run (Echo Inputs)")
    r_dry = vlm_dry.execute({"Image": grid, "Prompt": "Analyze shelf sequence", "Trigger": True})
    assert r_dry.status == ToolStatus.OK
    assert r_dry.outputs["Has_Response"] is True
    assert r_dry.outputs["Response_JSON"]["has_image"] is True

    # 3. Cloud async preserves submitted grid image when reply arrives later with Trigger=False
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '```json\n{"behavior_category":"high_risk_concealment_attempt","confidence_score":0.91,"justification":"Concealed item."}\n```'}}]
    }
    vlm.set_param("provider", "openai")
    vlm.set_param("api_key", "sk-test-key")
    vlm.set_param("async_non_blocking", True)

    with patch("requests.post", return_value=mock_resp):
        r_sub = vlm.execute({"Image": grid, "Prompt": "check 2x3 grid", "System_Prompt": "be strict", "Trigger": True})
        assert r_sub.outputs["Status"] in ("PENDING", "OK")
        deadline = time.monotonic() + 3.0
        done = None
        while time.monotonic() < deadline:
            time.sleep(0.05)
            cur = vlm.execute({"Image": raw_later, "Prompt": "", "Trigger": False})
            if cur.outputs["Has_Response"]:
                done = cur
                break
        assert done is not None
        assert done.outputs["Response_JSON"]["behavior_category"] == "high_risk_concealment_attempt"
        # Async completion returns the originally submitted grid, not raw_later
        assert int(done.outputs["Image"].mean()) == 120


def _make_pose_kps(sh_span=48, l_wrist=(205, 160), r_wrist=(235, 160), torso_y=115, hip_y=195):
    kps = [[0.0, 0.0, 0.0] for _ in range(17)]
    kps[0] = [220.0, float(torso_y - 35), 0.9]
    kps[5] = [220.0 - sh_span / 2.0, float(torso_y), 0.9]
    kps[6] = [220.0 + sh_span / 2.0, float(torso_y), 0.9]
    kps[7] = [200.0, float((torso_y + hip_y) / 2), 0.9]
    kps[8] = [240.0, float((torso_y + hip_y) / 2), 0.9]
    kps[9] = [float(l_wrist[0]), float(l_wrist[1]), 0.9 if l_wrist[0] > 0 else 0.0]
    kps[10] = [float(r_wrist[0]), float(r_wrist[1]), 0.9 if r_wrist[0] > 0 else 0.0]
    kps[11] = [205.0, float(hip_y), 0.9]
    kps[12] = [235.0, float(hip_y), 0.9]
    return kps


def test_modular_theft_recognition_project_end_to_end_verdicts(loaded_theft_plugin, tmp_path):
    assert os.path.exists(PROJECT_PATH)
    sol = SolutionManager.load_from_file(PROJECT_PATH)
    pipe = sol.get_active_flow()
    assert pipe is not None
    assert pipe.validate_flow() == [] or all(i.get("severity") != "error" for i in pipe.validate_flow())

    # Configure isolated log/evidence paths and synchronous mock VLM
    pipe.nodes["node_roi_zones"].set_param("zones", [
        {"name": "shelf", "rect": [280, 40, 160, 200]},
        {"name": "aisle", "rect": [140, 30, 310, 300]},
    ])
    pipe.nodes["node_bag_detector"].enabled = False
    pipe.nodes["node_yolo_pose"].enabled = False
    pipe.nodes["node_botsort"].enabled = True

    vlm_node = pipe.nodes["node_vlm"]
    vlm_node.set_param("provider", "openai")
    vlm_node.set_param("api_key", "sk-test-key")
    vlm_node.set_param("async_non_blocking", False)
    pipe.nodes["node_theft_log"].set_param("file_path", str(tmp_path / "theft.csv"))
    pipe.nodes["node_evidence_saver"].set_param("save_directory", str(tmp_path / "ev"))

    frame = np.full((360, 480, 3), 100, dtype=np.uint8)
    clock = [100.0]

    # Helper to inject Track dicts into Script 1 while keeping full pipeline wired
    def run_step(dt, tracks_list):
        clock[0] += dt
        pipe.nodes["node_rtsp_cam1"]._override_image = frame
        # Patch BoT-SORT execute to emit desired Tracks directly while running real ROI + Scripts + VLM + Condition Branch
        with patch.object(pipe.nodes["node_botsort"], "execute") as m_bot, patch("time.monotonic", side_effect=lambda: clock[0]):
            m_bot.return_value = SimpleNamespace(
                status=ToolStatus.OK,
                message="mocked tracks",
                elapsed_ms=1.0,
                outputs={"Image": frame, "Tracks": tracks_list, "Tracked_Count": len(tracks_list), "Status": "OK"},
                overlays=[],
            )
            return pipe.execute_flow(global_vars=sol.global_variables)

    kp_pre = _make_pose_kps(sh_span=50, l_wrist=(205, 160), r_wrist=(235, 160))
    kp_reach = _make_pose_kps(sh_span=50, l_wrist=(315, 95), r_wrist=(235, 170))
    kp_tuck = _make_pose_kps(sh_span=24, l_wrist=(220, 185), r_wrist=(225, 190))

    mock_theft_resp = MagicMock()
    mock_theft_resp.raise_for_status.return_value = None
    mock_theft_resp.json.return_value = {
        "choices": [{"message": {"content": '{"person_detected":true,"behavior_category":"high_risk_concealment_attempt","confidence_score":0.88,"sequence_verification":{"reach_detected":true,"hand_to_shelf_location":"shelf","personal_bag_backpack_overlap":true,"occluded_movement":true},"justification":"Concealed item into bag."}'}}]
    }

    with patch("requests.post", return_value=mock_theft_resp):
        # 1. Idle / dwelling -> Condition Branch is NG (no theft yet), Scripts stay OK (Option B)
        for dt in (0.0, 1.5, 2.0):
            res = run_step(dt, [{"track_id": 11, "bbox": [180, 60, 95, 250], "keypoints": kp_pre}])
            assert res["node_behavior_script"].status == ToolStatus.OK
            assert res["node_verdict_script"].status == ToolStatus.OK
            assert res["node_theft_branch"].status == ToolStatus.NG

        # 2. Reach -> Tuck -> Release fires VLM -> Theft Detected => Condition Branch PASS (OK)!
        run_step(0.5, [{"track_id": 11, "bbox": [180, 60, 95, 250], "keypoints": kp_reach}])
        run_step(0.6, [{"track_id": 11, "bbox": [180, 60, 95, 250], "keypoints": kp_tuck}])
        res_hit = run_step(3.6, [{"track_id": 11, "bbox": [180, 60, 95, 250], "keypoints": kp_pre}])

        assert res_hit["node_behavior_script"].outputs["Trigger"] is True
        assert "Active Monitored ROIs" in res_hit["node_prompt_script"].outputs["Text"]
        assert res_hit["node_vlm"].outputs["Has_Response"] is True
        assert res_hit["node_theft_branch"].status == ToolStatus.OK  # PASS when theft detected!
        assert res_hit["node_theft_log"].outputs["Rows_Written"] == 1
        assert os.path.exists(str(tmp_path / "theft.csv"))
        assert len(os.listdir(str(tmp_path / "ev"))) == 1

        # 3. After 6.0s hold expires, Condition Branch reverts back to NG without extra CSV/PNG writes
        res_after = run_step(6.5, [{"track_id": 11, "bbox": [180, 60, 95, 250], "keypoints": kp_pre}])
        assert res_after["node_theft_branch"].status == ToolStatus.NG
        assert res_after["node_theft_log"].outputs["Rows_Written"] == 0
        assert len(os.listdir(str(tmp_path / "ev"))) == 1


def test_rtsp_stream_driver_handles_quotes_and_retries_cap_open():
    drv = StreamCameraDriver(CameraDeviceInfo(device_id="rtsp_test", name="RTSP", camera_type="IP Stream"), '"rtsp://127.0.0.1:8554/live"')
    cap_first = MagicMock()
    cap_first.isOpened.return_value = True
    cap_first.read.return_value = (False, None)
    cap_retry = MagicMock()
    cap_retry.isOpened.return_value = True
    cap_retry.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))

    with patch("cv2.VideoCapture", side_effect=[cap_first, cap_retry]):
        ok, frame, msg = drv.capture_frame()
    assert ok is True
    assert frame is not None and frame.shape == (480, 640, 3)


def test_plugin_manager_discovers_repo_plugins_from_any_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pm = PluginManager()
    records = pm.discover_and_load_all(reload=True)
    assert "theft_recognition_plugin" in records
    assert records["theft_recognition_plugin"].state == PluginState.LOADED


def test_validate_flow_flags_missing_plugin_placeholder():
    from apex_vision.core.base_tool import MissingPluginPlaceholderTool
    from apex_vision.core.pipeline import VisionPipeline

    pipe = VisionPipeline("MissingPluginFlow")
    node = MissingPluginPlaceholderTool("m1", "04_BoTSORT_Tracker", missing_tool_name="BoT-SORT Tracker")
    pipe.add_node(node)
    issues = pipe.validate_flow()
    errors = [iss for iss in issues if iss.get("severity") == "error"]
    assert len(errors) == 1
    assert "BoT-SORT Tracker" in errors[0]["message"]


def test_roi_zone_manager_qml_ui_add_draw_delete_and_script_alignment(loaded_theft_plugin):
    from PyQt6.QtCore import QUrl
    from PyQt6.QtQml import QQmlApplicationEngine
    from PyQt6.QtQuick import QQuickItem
    from PyQt6.QtWidgets import QApplication
    from apex_vision.qml_backend import AppBackend, FrameProvider

    app = QApplication.instance() or QApplication([])
    eng = QQmlApplicationEngine()
    b = AppBackend(FrameProvider())
    b.openRecent(PROJECT_PATH)
    eng.rootContext().setContextProperty("appBackend", b)
    eng.addImportPath(os.path.join(ROOT, "qml"))
    eng.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    app.processEvents()
    win = eng.rootObjects()[0]

    def walk(node):
        seen, stack, out = set(), [node], []
        while stack:
            cur = stack.pop()
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            out.append(cur)
            if isinstance(cur, QQuickItem):
                stack.extend(cur.childItems())
            stack.extend(cur.children())
        return out

    mod_dlg = [it for it in walk(win) if it.property("moduleName") is not None and it.property("nodeId") is not None][0]
    host = mod_dlg.parentItem()
    host.showModule("node_roi_zones", "01b ROI_Zones")
    mod_dlg.setProperty("tab", 2)
    app.processEvents()

    items = walk(win)
    names = [it for it in items if it.objectName().startswith("paramRoiName")]
    assert len(names) == 2  # shelf and aisle both render in QML
    add_btn = [it for it in items if it.objectName() == "paramRoiAdd"][0]
    add_btn.clicked.emit()
    app.processEvents()
    assert len(b._pipeline.nodes["node_roi_zones"].parameters["zones"]) == 3

    items2 = walk(win)
    assert len([it for it in items2 if it.objectName().startswith("paramRoiName")]) == 3
    draw_btn0 = [it for it in items2 if it.objectName() == "paramRoiDraw0"][0]
    draw_btn0.clicked.emit()
    app.processEvents()
    assert b.drawingParam["active"] is True
    assert b.commitDrawParam([15, 25, 210, 190]) is True
    app.processEvents()
    assert b._pipeline.nodes["node_roi_zones"].parameters["zones"][0]["rect"] == [15, 25, 210, 190]

    # ScriptEditor highlight width matches TextEdit contentWidth on indented Python code
    host.close()
    app.processEvents()
    host.showModule("node_behavior_script", "05 Behavior_Gate_Grid")
    mod_dlg.setProperty("tab", 2)
    app.processEvents()
    items3 = walk(win)
    hl = [it for it in items3 if it.objectName() == "scriptHighlight"][0]
    ed = [it for it in items3 if it.objectName() == "paramCode"][0]
    assert abs(float(hl.property("contentWidth")) - float(ed.property("contentWidth"))) < 1.5
    assert abs(float(hl.property("contentHeight")) - float(ed.property("contentHeight"))) < 1.5


def test_dl_and_tracker_cpu_gpu_device_options_and_reid(loaded_theft_plugin):
    from apex_vision.core import dl_engine as dl
    from apex_vision.core import param_schema as ps
    from apex_vision.core.base_tool import ToolStatus
    from apex_vision.core.registry import create_tool_instance

    # Built-in DL & Object Detection schemas expose CPU/GPU + auto choices
    assert set(ps.SCHEMA["Object Detection"]["device"]["choices"]) >= {"auto", "cpu", "cuda", "cuda:0"}
    assert set(ps.SCHEMA["DL Classify"]["device"]["choices"]) >= {"auto", "cpu", "cuda", "cuda:0"}
    assert dl.resolve_torch_device("cpu") == "cpu"
    assert dl.resolve_torch_device("auto") in ("cpu", "cuda:0", "mps")
    # Graceful fallback to cpu if CUDA requested on CPU-only machine
    fallback = dl.resolve_torch_device("cuda:0")
    assert fallback in ("cpu", "cuda:0")
    providers, _ = dl.resolve_onnx_device("auto")
    assert "CPUExecutionProvider" in providers

    # YOLO Pose exposes auto/cpu/cuda/cuda:0/mps
    pose = create_tool_instance("YOLO Pose", "pose_dev")
    assert set(pose.param_definitions["device"].choices) >= {"auto", "cpu", "cuda", "cuda:0"}

    # BoT-SORT Tracker exposes device + enable_reid and runs ReID without crashing
    tracker = create_tool_instance("BoT-SORT Tracker", "bs_reid")
    assert set(tracker.param_definitions["device"].choices) >= {"auto", "cpu", "cuda", "cuda:0"}
    assert "enable_reid" in tracker.param_definitions
    tracker.set_param("device", "cuda:0")
    tracker.set_param("enable_reid", True)

    frame = np.full((360, 640, 3), 120, dtype=np.uint8)
    cv2.rectangle(frame, (100, 80), (190, 300), (40, 90, 200), -1)
    cv2.rectangle(frame, (380, 90), (460, 290), (200, 120, 40), -1)
    dets = [
        {"Box": [100, 80, 90, 220], "Score": 0.92, "Class": "person", "Class_Id": 0, "Keypoints": []},
        {"Box": [380, 90, 80, 200], "Score": 0.89, "Class": "person", "Class_Id": 0, "Keypoints": []},
    ]
    res1 = tracker.execute({"Image": frame, "Detections": dets})
    assert res1.status == ToolStatus.OK
    assert res1.outputs["Tracked_Count"] == 2
    assert "ReID" in res1.message
    res2 = tracker.execute({"Image": frame, "Detections": dets})
    assert res2.status == ToolStatus.OK
    assert [t["track_id"] for t in res2.outputs["Tracks"]] == [t["track_id"] for t in res1.outputs["Tracks"]]


def test_vlm_pending_queue_and_explicit_error_surfacing(loaded_theft_plugin):
    import json as _json
    import sys as _sys
    import threading
    import time
    from apex_vision.core.base_tool import ToolStatus
    from apex_vision.core.pipeline import SolutionManager
    from apex_vision.core.registry import create_tool_instance

    vlm = create_tool_instance("VLM", "vlm_queue_test")
    vlm_mod = _sys.modules[vlm.__class__.__module__]
    vlm.set_param("api_key", "test-key")
    vlm.set_param("async_non_blocking", True)

    gate = threading.Event()
    calls = []

    def fake_call(**kwargs):
        calls.append(kwargs["prompt"])
        if len(calls) == 1:
            gate.wait(timeout=2.0)
        return _json.dumps({
            "person_detected": True,
            "behavior_category": "regular_browsing",
            "confidence_score": 0.2,
            "justification": f"handled {kwargs['prompt']}",
        })

    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    with patch.object(vlm_mod, "call_generic_vlm", side_effect=fake_call):
        # Request 1 goes in-flight; request 2 is queued instead of dropped
        r1 = vlm.execute({"Image": frame, "Prompt": "req-1", "Trigger": True})
        assert r1.outputs["Status"] == "PENDING"
        r2 = vlm.execute({"Image": frame, "Prompt": "req-2", "Trigger": True})
        assert r2.outputs["Status"] == "PENDING"
        gate.set()
        deadline = time.monotonic() + 3.0
        seen_replies = []
        while time.monotonic() < deadline and len(seen_replies) < 2:
            rn = vlm.execute({"Image": frame, "Prompt": "", "Trigger": False})
            if rn.outputs["Has_Response"]:
                seen_replies.append(rn.outputs["Response_JSON"].get("justification", ""))
            time.sleep(0.02)
    assert calls == ["req-1", "req-2"]
    assert seen_replies == ["handled req-1", "handled req-2"]

    # Error propagation into Script 3 (08_Parse_Verdict)
    vlm_err = create_tool_instance("VLM", "vlm_err_test")
    vlm_err_mod = _sys.modules[vlm_err.__class__.__module__]
    vlm_err.set_param("api_key", "test-key")
    vlm_err.set_param("async_non_blocking", False)
    with patch.object(vlm_err_mod, "call_generic_vlm", side_effect=RuntimeError("HTTP 504 timeout")):
        re_out = vlm_err.execute({"Image": frame, "Prompt": "req-err", "Trigger": True})
    assert re_out.status == ToolStatus.ERROR
    assert re_out.outputs["Has_Error"] is True
    assert "HTTP 504 timeout" in re_out.outputs["Error"]
    assert re_out.outputs["Status"] == "ERROR"

    sol = SolutionManager.load_from_file(PROJECT_PATH)
    pipe = sol.get_active_flow()
    verdict_node = pipe.nodes["node_verdict_script"]
    vs_res = verdict_node.execute({
        "Image": frame,
        "Data1": re_out.outputs["Response_JSON"],
        "Data2": re_out.outputs["Response_Text"],
        "Data3": re_out.outputs["Error"],
        "Data4": re_out.outputs["Status"],
        "Trigger": re_out.outputs["Has_Response"],
    })
    assert vs_res.status == ToolStatus.NG
    assert vs_res.outputs["Status"] == "ERROR"
    assert vs_res.outputs["Result"]["behavior_category"] == "ERROR"
    assert "HTTP 504 timeout" in vs_res.outputs["Result"]["error"]


def test_image_source_timestamp_and_behavior_script_loop_and_multi_dispatch(loaded_theft_plugin):
    from apex_vision.core.base_tool import ToolStatus
    from apex_vision.core.pipeline import SolutionManager
    from apex_vision.tools.acquisition import ImageSourceTool

    src = ImageSourceTool("ts_src")
    res = src.execute({})
    assert res.status == ToolStatus.OK
    assert isinstance(res.outputs["Timestamp"], float)

    # Behavior gate handles video timestamps, loop rewind, and simultaneous two-shopper dispatches
    sol = SolutionManager.load_from_file(PROJECT_PATH)
    pipe = sol.get_active_flow()
    beh = pipe.nodes["node_behavior_script"]
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    def mk_track(tid, cx, reach=False, tuck=False):
        kps = [[0.0, 0.0, 0.0] for _ in range(17)]
        kps[0] = [cx, 95.0, 0.9]
        kps[5] = [cx - 22.0, 130.0, 0.9]
        kps[6] = [cx + 22.0, 130.0, 0.9]
        kps[11] = [cx - 18.0, 210.0, 0.9]
        kps[12] = [cx + 18.0, 210.0, 0.9]
        if reach:
            kps[9] = [cx - 85.0, 140.0, 0.9]
            kps[10] = [cx + 22.0, 185.0, 0.9]
        elif tuck:
            kps[9] = [cx, 180.0, 0.9]
            kps[10] = [cx + 6.0, 185.0, 0.9]
        else:
            kps[9] = [cx - 25.0, 195.0, 0.9]
            kps[10] = [cx + 25.0, 195.0, 0.9]
        return {"track_id": tid, "bbox": [int(cx - 35), 80, 70, 220], "keypoints": kps}

    dispatched_ids = []
    # Dwell 3.2s, reach at 3.5s, tuck at 4.5s, wait past 3.5s release window -> simultaneous dispatch at t=8.5s
    timeline = [
        (0.0, False, False), (1.0, False, False), (2.0, False, False), (3.2, False, False),
        (3.5, True, False), (4.5, False, True),
        (8.2, False, False),  # both tracks release on this timestamp!
        (8.3, False, False),  # 2nd queued track emits on next cycle!
        # Simulate video loop rewind back to 0.0s -> must NOT go negative or skip frames
        (0.0, False, False),
        (0.1, False, False),
    ]
    for ts, reach, tuck in timeline:
        out = beh.execute({
            "Image": frame,
            "Val1": ts,
            "Data1": [mk_track(1, 180.0, reach=reach, tuck=tuck), mk_track(2, 460.0, reach=reach, tuck=tuck)],
            "Data2": [],
            "Data3": None,
            "Data4": None,
        })
        if out.outputs["Trigger"]:
            dispatched_ids.append(out.outputs["Data"]["track_id"])

    assert dispatched_ids == [1, 2]


def _make_shelf_test_frame(*, include_a: bool = True, include_b: bool = True, shadow_center: bool = False) -> np.ndarray:
    img = np.full((360, 640, 3), 55, dtype=np.uint8)
    for y in range(40, 220, 12):
        img[y:y + 4, 100:520] = (85, 85, 90)
    for x in range(100, 520, 16):
        img[40:220, x:x + 4] = (75, 80, 85)
    if include_a:
        cv2.rectangle(img, (140, 80), (188, 136), (240, 220, 80), -1)
        cv2.rectangle(img, (146, 90), (182, 126), (40, 60, 210), -1)
    if include_b:
        cv2.rectangle(img, (416, 80), (464, 136), (70, 235, 190), -1)
        cv2.rectangle(img, (422, 92), (458, 124), (200, 40, 90), -1)
    if shadow_center:
        img[50:200, 245:365] = np.clip(img[50:200, 245:365].astype(np.float32) * 0.68 - 8.0, 0, 255).astype(np.uint8)
    return img


def test_apex_union_roi_vlm_frames_concurrency_and_four_fact_watch_routing(loaded_theft_plugin):
    import sys as _sys

    roi_mgr = create_tool_instance("ROI Zone Manager", "r_union")
    roi_mgr.set_param("zones", [
        {"name": "shelf_left", "rect": [40, 40, 120, 180]},
        {"name": "aisle_main", "rect": [180, 60, 260, 240]},
    ])
    res_roi = roi_mgr.execute({"Image": np.zeros((360, 640, 3), dtype=np.uint8)})
    ux, uy, uw, uh = res_roi.outputs["Union_ROI"]
    # Union_ROI spans both shelf_left (x=40) and aisle_main (right edge x=440) with margin
    assert ux < 40 and (ux + uw) > 440 and uy < 40 and (uy + uh) > 300

    # VLMTool: Frames port + response_format + 400 retry + max_concurrent=3 FIFO ordering
    vlm = create_tool_instance("VLM", "v_frames")
    vlm_mod = _sys.modules[vlm.__class__.__module__]
    frame = np.full((64, 64, 3), 90, dtype=np.uint8)
    ok_j, jpg = cv2.imencode(".jpg", frame)
    assert ok_j
    posted = []
    r400 = MagicMock(status_code=400)
    r200 = MagicMock(status_code=200)
    r200.raise_for_status.return_value = None
    r200.json.return_value = {"choices": [{"message": {"content": '{"behavior_category":"regular_browsing","confidence_score":0.2}'}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        posted.append(dict(json))
        return r400 if len(posted) == 1 else r200

    vlm.set_param("api_key", "sk-test")
    vlm.set_param("async_non_blocking", False)
    with patch("requests.post", side_effect=fake_post):
        out = vlm.execute({"Image": frame, "Frames": [jpg.tobytes(), jpg.tobytes(), jpg.tobytes()], "Prompt": "check seq", "Trigger": True})
    assert out.status == ToolStatus.OK
    assert "response_format" in posted[0] and "response_format" not in posted[1]
    assert len([p for p in posted[1]["messages"][-1]["content"] if p.get("type") == "image_url"]) == 3

    vlm_c = create_tool_instance("VLM", "v_conc")
    vlm_c.set_param("api_key", "sk-test")
    vlm_c.set_param("async_non_blocking", True)
    vlm_c.set_param("max_concurrent", 3)
    delivered = []

    def fake_conc(**kwargs):
        if kwargs["prompt"] == "p1":
            time.sleep(0.16)
        else:
            time.sleep(0.02)
        return f'{{"behavior_category":"regular_browsing","confidence_score":0.1,"justification":"{kwargs["prompt"]}"}}'

    with patch.object(vlm_mod, "call_generic_vlm", side_effect=fake_conc):
        for p in ("p1", "p2", "p3"):
            vlm_c.execute({"Image": frame, "Prompt": p, "Trigger": True})
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and len(delivered) < 3:
            rn = vlm_c.execute({"Image": frame, "Prompt": "", "Trigger": False})
            if rn.outputs["Has_Response"]:
                delivered.append(rn.outputs["Response_JSON"]["justification"])
            time.sleep(0.02)
    assert delivered == ["p1", "p2", "p3"]

    # 08_Parse_Verdict: 4-Fact Red Alert vs Silent Watch_Trigger gating
    sol = SolutionManager.load_from_file(PROJECT_PATH)
    pipe = sol.get_active_flow()
    verdict_node = pipe.nodes["node_verdict_script"]
    res_watch = verdict_node.execute({
        "Image": frame,
        "Data1": {
            "behavior_category": "high_risk_concealment_attempt",
            "item_removed_from_shelf": "unclear",
            "visible_destination": "unclear",
            "likely_personal_object": False,
            "staff_or_byob_indicator": False,
            "confidence_score": 0.72,
        },
        "Data2": "",
        "Data3": "",
        "Data4": "OK",
        "Trigger": True,
    })
    assert res_watch.outputs["Trigger"] is False
    assert res_watch.outputs["Watch_Trigger"] is True
    assert res_watch.outputs["Value"] == 0.0

    res_red = verdict_node.execute({
        "Image": frame,
        "Data1": {
            "behavior_category": "high_risk_concealment_attempt",
            "item_removed_from_shelf": "yes",
            "visible_destination": "personal_bag_or_clothing",
            "likely_personal_object": False,
            "staff_or_byob_indicator": False,
            "confidence_score": 0.89,
        },
        "Data2": "",
        "Data3": "",
        "Data4": "OK",
        "Trigger": True,
    })
    assert res_red.outputs["Trigger"] is True
    assert res_red.outputs["Watch_Trigger"] is False
    assert res_red.outputs["Value"] == 89.0


def test_apex_multi_person_shelf_delta_and_behavior_script_hardening(loaded_theft_plugin):
    import sys as _sys
    import importlib.util

    sd_path = os.path.join(PLUGIN_DIR, "shelf_delta.py")
    spec = importlib.util.spec_from_file_location("theft_shelf_delta_test", sd_path)
    sd_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sd_mod)

    tracker = sd_mod.LocalizedShelfDeltaTracker()
    shelf_rects = [(100, 40, 420, 180)]
    clean_frame = _make_shelf_test_frame(include_a=True, include_b=True)
    for ts in (0.0, 0.25, 0.5, 0.75):
        tracker.step(clean_frame, ts, shelf_rects, [])

    # Concurrent left (no take) vs right (item B taken) on the SAME shelf ROI
    for ts in (1.0, 1.2):
        tracker.step(
            clean_frame,
            ts,
            shelf_rects,
            [
                {"tid": 1, "bbox": (130, 140, 70, 200), "wrists": [(164, 108)], "reach_active": True, "touched_shelf_idx": 0},
                {"tid": 2, "bbox": (406, 140, 70, 200), "wrists": [(440, 108)], "reach_active": True, "touched_shelf_idx": 0},
            ],
        )
    frame_b_gone = _make_shelf_test_frame(include_a=True, include_b=False)
    for ts in (1.5, 1.7, 1.9):
        res = tracker.step(
            frame_b_gone,
            ts,
            shelf_rects,
            [
                {"tid": 1, "bbox": (120, 245, 70, 110), "wrists": [(150, 260)], "reach_active": False, "touched_shelf_idx": None},
                {"tid": 2, "bbox": (410, 245, 70, 110), "wrists": [(440, 260)], "reach_active": False, "touched_shelf_idx": None},
            ],
        )
    assert res[1]["status"] == "unchanged" and res[1]["confirmed"] is False
    assert res[2]["status"] == "confirmed" and res[2]["confirmed"] is True

    # Zone exit dispatches armed track cleanly inside Apex Script 1
    sol = SolutionManager.load_from_file(PROJECT_PATH)
    pipe = sol.get_active_flow()
    beh = pipe.nodes["node_behavior_script"]
    rois = {"shelf_left": [40, 40, 110, 200], "aisle_main": [160, 40, 200, 260]}

    def mk_person(tid, cx, *, reach=False, tuck=False):
        kps = _make_pose_kps(sh_span=50, l_wrist=(cx - 20, 175), r_wrist=(cx + 20, 175))
        kps[5] = [cx - 25.0, 115.0, 0.9]
        kps[6] = [cx + 25.0, 115.0, 0.9]
        if reach:
            kps[9] = [95.0, 120.0, 0.9]
        elif tuck:
            kps[9] = [cx - 2.0, 165.0, 0.9]
            kps[10] = [cx + 4.0, 168.0, 0.9]
        return {"track_id": tid, "bbox": [int(cx - 35), 70, 70, 220], "keypoints": kps}

    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    for ts in (0.0, 0.7, 1.4):
        beh.execute({"Image": frame, "Val1": ts, "Data1": [mk_person(7, 250)], "Data2": [], "Data3": rois, "Data4": None})
    beh.execute({"Image": frame, "Val1": 1.6, "Data1": [mk_person(7, 250, reach=True)], "Data2": [], "Data3": rois, "Data4": None})
    beh.execute({"Image": frame, "Val1": 2.0, "Data1": [mk_person(7, 250, tuck=True)], "Data2": [], "Data3": rois, "Data4": None})
    beh.execute({"Image": frame, "Val1": 2.2, "Data1": [mk_person(7, 480)], "Data2": [], "Data3": rois, "Data4": None})
    out_exit = beh.execute({"Image": frame, "Val1": 2.9, "Data1": [mk_person(7, 480)], "Data2": [], "Data3": rois, "Data4": None})
    assert out_exit.outputs["Trigger"] is True
    assert out_exit.outputs["Data"]["dispatch_cause"] == "zone_exit"
    assert len(out_exit.outputs["Sequence_Frames"]) >= 2



def test_apex_dual_trigger_path_b_and_shared_recent_pickups_sheet():
    from pathlib import Path
    import xml.etree.ElementTree as ET
    import cv2
    import numpy as np
    from apex_vision.tools.script_tool import ScriptTool

    apex_path = Path(__file__).resolve().parents[1] / "projects" / "Theft_Recognition_RTSP.apex"
    root = ET.parse(str(apex_path)).getroot()
    nodes = {n.attrib["instance_id"]: n for n in root.findall("./Flows/ApexFlow/Nodes/Node")}

    def get_code(node_el):
        for p in node_el.findall("./Parameters/Parameter"):
            if p.attrib.get("name") == "code":
                return p.text or ""
        return ""

    code_gate = get_code(nodes["node_behavior_script"])
    code_prompt = get_code(nodes["node_prompt_script"])

    shared_globals = {}

    def kps(cx, lw, rw):
        pts = [[0.0, 0.0, 0.0] for _ in range(17)]
        pts[0] = [cx, 95.0, 0.9]
        pts[5] = [cx - 25.0, 135.0, 0.9]
        pts[6] = [cx + 25.0, 135.0, 0.9]
        pts[7] = [cx - 32.0, 170.0, 0.9]
        pts[8] = [cx + 32.0, 170.0, 0.9]
        pts[9] = [float(lw[0]), float(lw[1]), 0.92]
        pts[10] = [float(rw[0]), float(rw[1]), 0.92]
        pts[11] = [cx - 18.0, 210.0, 0.9]
        pts[12] = [cx + 18.0, 210.0, 0.9]
        return pts

    frame = np.full((360, 640, 3), 85, dtype=np.uint8)
    frame[100:250, 270:340] = (25, 45, 220)

    # Flow A (cam_aisle): shopper reaches shelf -> populates g_RecentPickups
    gate_cam1 = ScriptTool("gate_cam1")
    gate_cam1.set_param("code", code_gate)
    rois_cam1 = {"shelf_1": [380, 90, 180, 180], "aisle_1": [180, 60, 240, 280]}
    for i in range(4):
        gate_cam1.execute({
            "Image": frame,
            "Val1": 10.0 + i * 0.25,
            "camera_id": "cam_aisle",
            "Data1": [{"track_id": 10, "bbox": [260, 80, 90, 220], "keypoints": kps(305, (235, 165), (415, 155))}],
            "Data2": [],
            "Data3": rois_cam1,
            "global": {"globals": shared_globals},
        })
    assert "g_RecentPickups" in shared_globals and len(shared_globals["g_RecentPickups"]) == 1

    # Flow B (cam_corridor): frame-0 hands in pockets does NOT arm Path B
    gate_cam2_rest = ScriptTool("gate_cam2_rest")
    gate_cam2_rest.set_param("code", code_gate)
    for i in range(12):
        r = gate_cam2_rest.execute({
            "Image": frame,
            "Val1": 20.0 + i * 0.25,
            "camera_id": "cam_corridor",
            "Data1": [{"track_id": 20, "bbox": [260, 80, 90, 220], "keypoints": kps(305, (300, 190), (310, 190))}],
            "Data2": [],
            "Data3": {},
            "global": {"globals": shared_globals},
        })
        assert r.outputs["Trigger"] is False

    # Flow B (cam_corridor): open wrists -> sustained backpack stuff -> fires Path B with Image #1 Ref Sheet
    gate_cam2 = ScriptTool("gate_cam2")
    gate_cam2.set_param("code", code_gate)
    bag_det = [{"Class": "backpack", "Box": [320, 160, 65, 85]}]
    fired = None
    for i in range(5):
        gate_cam2.execute({
            "Image": frame,
            "Val1": 30.0 + i * 0.25,
            "camera_id": "cam_corridor",
            "Data1": [{"track_id": 21, "bbox": [260, 80, 90, 220], "keypoints": kps(305, (235, 165), (375, 165))}],
            "Data2": bag_det,
            "Data3": {},
            "global": {"globals": shared_globals},
        })
    for i in range(5, 32):
        r = gate_cam2.execute({
            "Image": frame,
            "Val1": 30.0 + i * 0.25,
            "camera_id": "cam_corridor",
            "Data1": [{"track_id": 21, "bbox": [260, 80, 90, 220], "keypoints": kps(305, (235, 165), (345, 195))}],
            "Data2": bag_det,
            "Data3": {},
            "global": {"globals": shared_globals},
        })
        if r.outputs["Trigger"]:
            fired = r
            break

    assert fired is not None
    cand = fired.outputs["Data"]
    assert cand["trigger_mode"] == "shelf_free_tuck"
    assert cand["has_reference_sheet"] is True
    assert "bag_stuff" in cand["behaviors"]
    seq = fired.outputs["Sequence_Frames"]
    assert len(seq) >= 2
    decoded_sheet = cv2.imdecode(np.frombuffer(seq[0], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded_sheet is not None and decoded_sheet.shape[0] >= 200

    prompt_tool = ScriptTool("prompt_test")
    prompt_tool.set_param("code", code_prompt)
    pr = prompt_tool.execute({
        "Image": fired.outputs["Image"],
        "Trigger": True,
        "Data1": cand,
        "Data2": {},
    })
    assert "RECENT STORE PICKUPS" in pr.outputs["System_Prompt"]
    assert "RECENT STORE PICKUPS reference sheet" in pr.outputs["Text"]
    assert "Trigger Path: shelf_free_tuck" in pr.outputs["Text"]


def test_vlm_tool_gemini_truncation_retry(loaded_theft_plugin):
    from unittest.mock import patch
    from plugins.theft_recognition_plugin.vlm_module_tool import VLMTool, call_generic_vlm, parse_json_response

    tool = VLMTool("vlm_budget_test")
    assert int(tool.get_param("max_tokens")) == 2048

    posted = []

    class FakeResp:
        def __init__(self, body):
            self.status_code = 200
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    def fake_post(url, headers=None, json=None, timeout=None):
        posted.append(dict(json or {}))
        if len(posted) == 1:
            return FakeResp({
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": '```json\n{\n  "person_detected": true,\n  "behavior_'},
                }]
            })
        return FakeResp({
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": '{"person_detected": true, "behavior_category": "regular_browsing", "confidence_score": 0.14}'
                },
            }]
        })

    with patch("requests.post", side_effect=fake_post):
        txt = call_generic_vlm(
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key="test",
            model_name="gemini-2.5-flash",
            prompt="usr",
            system_prompt="sys",
            image_b64="",
            frames_b64=["YWJj"],
            temperature=0.1,
            max_tokens=512,
            timeout_sec=10.0,
            want_json=True,
        )

    assert len(posted) == 2
    assert posted[0]["max_tokens"] == 2048
    assert posted[0]["reasoning_effort"] == "low"
    assert posted[1]["max_tokens"] == 4096
    assert posted[1]["reasoning_effort"] == "none"
    parsed = parse_json_response(txt)
    assert parsed["behavior_category"] == "regular_browsing"


def test_vlm_tool_429_retry_after_recovery(loaded_theft_plugin):
    from unittest.mock import patch
    from plugins.theft_recognition_plugin.vlm_module_tool import call_generic_vlm, parse_json_response

    class FakeResp:
        def __init__(self, status_code, body, headers=None):
            self.status_code = status_code
            self._body = body
            self.headers = headers or {}
            self.text = str(body)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._body

    calls = {"n": 0}

    def post_recover(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(
                429,
                {"error": {"message": "Quota exceeded for GenerateRequestsPerMinutePerProject, retry in 0.01s"}},
                headers={"Retry-After": "0.01"},
            )
        return FakeResp(
            200,
            {"choices": [{"finish_reason": "stop", "message": {"content": '{"person_detected": true, "behavior_category": "regular_browsing", "confidence_score": 0.11}'}}]},
        )

    with patch("requests.post", side_effect=post_recover):
        txt = call_generic_vlm(
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key="test",
            model_name="gemini-2.5-flash",
            prompt="usr",
            system_prompt="sys",
            image_b64="",
            frames_b64=["YWJj"],
            temperature=0.1,
            max_tokens=512,
            timeout_sec=10.0,
            want_json=True,
        )

    assert calls["n"] == 2
    assert parse_json_response(txt)["behavior_category"] == "regular_browsing"


def test_vlm_tool_deepseek_endpoint_and_400_fallback(loaded_theft_plugin, monkeypatch):
    from unittest.mock import patch
    from plugins.theft_recognition_plugin.vlm_module_tool import VLMTool, call_generic_vlm, resolve_endpoint_and_key

    tool = VLMTool("vlm_ds_test")
    assert "deepseek" in tool.param_definitions["provider"].choices

    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-vm-secret")
    prov, url, key = resolve_endpoint_and_key("deepseek", "", "")
    assert prov == "deepseek"
    assert url == "https://api.deepseek.com"
    assert key == "ds-vm-secret"

    posted = []

    class FakeResp:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body
            self.headers = {}
            self.text = str(body)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._body

    def fake_post(url, headers=None, json=None, timeout=None):
        posted.append(dict(json or {}))
        if len(posted) == 1:
            return FakeResp(400, {"error": {"message": "max_tokens is unsupported; use max_completion_tokens"}})
        return FakeResp(200, {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}]})

    with patch("requests.post", side_effect=fake_post):
        txt = call_generic_vlm(
            provider="deepseek",
            base_url=url,
            api_key=key,
            model_name="deepseek-flash",
            prompt="usr",
            system_prompt="sys",
            image_b64="",
            frames_b64=["YWJj"],
            temperature=0.1,
            max_tokens=512,
            timeout_sec=10.0,
            want_json=True,
        )
    assert len(posted) == 2
    assert "max_completion_tokens" in posted[1] and "max_tokens" not in posted[1]
    assert '"ok": true' in txt
