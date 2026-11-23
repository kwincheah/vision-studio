"""Tests for the Hikrobot-style ApexSolution / ApexProcedure / ApexRuntimeEngine SDK."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import time
from types import SimpleNamespace
import numpy as np
import pytest

from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.param_schema import problem_for_tool
from apex_vision.sdk import ApexProcedure, ApexRuntimeEngine, ApexSolution, ensure_theft_plugin_loaded


@dataclass
class _StubZone:
    name: str
    role: str = "shelf"
    x_norm: float = 0.2
    y_norm: float = 0.2
    w_norm: float = 0.4
    h_norm: float = 0.5


@dataclass
class _StubCam:
    camera_id: str
    name: str
    rtsp_url: str
    enabled: bool = True
    dwell_sec: float = 3.0
    release_wait_sec: float = 3.5
    cooldown_sec: float = 12.0
    zones: list = field(default_factory=list)


class _StubBroadcaster:
    def __init__(self):
        self.events = []

    def publish_sync(self, event_type: str, payload):
        self.events.append((event_type, payload))


def _make_vlm_cfg(api_key: str = "SUPER_SECRET_KEY_123"):
    return SimpleNamespace(
        provider="dry_run",
        base_url="",
        model_name="dry_run",
        api_key=api_key,
        timeout_sec=10.0,
        alert_threshold_pct=65.0,
        use_native_video=False,
        video_fps=2.0,
        max_sequence_frames=12,
        disable_reasoning=False,
    )


def test_all_eight_plugin_tools_pass_param_schema_and_build_multi_flow():
    ensure_theft_plugin_loaded()
    cams = [
        _StubCam("cam_01", "Aisle 1", "rtsp://127.0.0.1/cam1", zones=[_StubZone("shelf_1", "shelf")]),
        _StubCam("cam_02", "Aisle 2", "rtsp://127.0.0.1/cam2", zones=[_StubZone("aisle_1", "aisle", 0.1, 0.1, 0.7, 0.8)]),
    ]
    sol = ApexSolution.build_from_cameras(cams, vlm_cfg=_make_vlm_cfg())
    assert sol.list_procedures() == ["cam_01", "cam_02"]

    for cam_id in ("cam_01", "cam_02"):
        proc = sol[cam_id]
        assert isinstance(proc, ApexProcedure)
        for nid in ApexSolution.REQUIRED_NODE_IDS:
            nd = proc.node(nid)
            assert nd is not None, f"Missing node {nid}"
            for pname, pval in nd.parameters.items():
                pdef = nd.param_definitions.get(pname)
                default = pdef.default_value if pdef is not None else pval
                assert problem_for_tool(nd.tool_name, pname, default, pval) is None


def test_multi_flow_xml_round_trip_strips_secrets_and_runtime_globals(tmp_path: Path):
    cams = [
        _StubCam("cam_01", "Counter", "rtsp://127.0.0.1/a", zones=[_StubZone("shelf_1", "shelf")]),
        _StubCam("cam_02", "Back", "rtsp://127.0.0.1/b", enabled=False, zones=[_StubZone("aisle_1", "aisle")]),
    ]
    sol = ApexSolution.build_from_cameras(cams, vlm_cfg=_make_vlm_cfg("sk-or-v1-should-never-appear"))
    # Simulate live runtime secrets + objects attached to solution globals and node_vlm
    sol.manager.set_global("__vlm_api_key__", "sk-or-v1-should-never-appear")
    sol.manager.set_global("__vlm_dispatcher__", object())
    sol.manager.set_global("site_name", "MainStore")
    sol["cam_01"].node("node_vlm").parameters["api_key"] = "sk-or-v1-should-never-appear"

    apex_file = tmp_path / "storeguard.apex"
    sol.save(apex_file)
    xml_text = apex_file.read_text(encoding="utf-8")

    assert "sk-or-v1-should-never-appear" not in xml_text
    assert "__vlm_api_key__" not in xml_text
    assert "__vlm_dispatcher__" not in xml_text
    assert "site_name" in xml_text

    # Verify in-memory runtime values were preserved across serialization
    assert sol.manager.global_variables["__vlm_api_key__"] == "sk-or-v1-should-never-appear"
    assert sol["cam_01"].node("node_vlm").parameters["api_key"] == "sk-or-v1-should-never-appear"

    reloaded = ApexSolution.load(apex_file)
    assert reloaded.list_procedures() == ["cam_01", "cam_02"]
    assert reloaded["cam_02"].pipeline.enabled is False
    assert reloaded["cam_01"].get_param("node_roi", "zones")[0]["rect"][2] > 0


def test_motion_gate_idle_bypass_latency_and_statuses():
    cams = [_StubCam("cam_01", "Empty Aisle", "rtsp://127.0.0.1/empty", zones=[_StubZone("shelf_1", "shelf")])]
    sol = ApexSolution.build_from_cameras(cams, vlm_cfg=_make_vlm_cfg())
    proc = sol["cam_01"]
    static_frame = np.full((360, 640, 3), 64, dtype=np.uint8)

    # Frame 0 establishes background reference
    proc.run_once(frame_bgr=static_frame, timestamp=0.0)

    # First idle frame establishes zero motion and emits Inactive_Branches for downstream nodes
    r_idle = proc.run_once(frame_bgr=static_frame, timestamp=4.5)
    assert r_idle["node_motion"].outputs["Active"] is False
    for bypassed_id in ("node_pose", "node_bags", "node_tracker", "node_behavior", "node_vlm"):
        assert r_idle[bypassed_id].status == ToolStatus.BYPASS

    timings_ms = []
    for i in range(20):
        t0 = time.perf_counter()
        res = proc.run_once(frame_bgr=static_frame, timestamp=5.0 + i * 0.125)
        timings_ms.append((time.perf_counter() - t0) * 1000.0)
        assert res["node_pose"].status == ToolStatus.BYPASS

    median_ms = sorted(timings_ms)[len(timings_ms) // 2]
    assert median_ms < 2.0, f"Expected sub-2ms idle bypass, got {median_ms:.3f} ms"


def test_shared_onnx_session_pool_reused_across_procedures():
    ensure_theft_plugin_loaded()
    sg_models = Path(r"C:\Users\winch\Downloads\StoreGuard\models")
    pose_onnx = sg_models / "yolo11n-pose.onnx"
    bag_onnx = sg_models / "yolo11n.onnx"
    if not pose_onnx.is_file() or not bag_onnx.is_file():
        pytest.skip("StoreGuard ONNX models not present on disk")

    prev_env = os.environ.get("APEX_MODELS_DIR")
    os.environ["APEX_MODELS_DIR"] = str(sg_models)
    try:
        from plugins.theft_recognition_plugin import __file__ as _  # noqa: F401
    except Exception:
        pass

    import sys
    pose_mod = sys.modules["apex_plugin_theft_recognition_plugin.pose_detector_tool"]
    bag_mod = sys.modules["apex_plugin_theft_recognition_plugin.context_detector_tool"]

    try:
        s1_pose = pose_mod.get_shared_onnx_pose_session(str(pose_onnx), "cpu")
        s2_pose = pose_mod.get_shared_onnx_pose_session(str(pose_onnx), "cpu")
        s1_bag = bag_mod.get_shared_onnx_bag_session(str(bag_onnx), "cpu")
        s2_bag = bag_mod.get_shared_onnx_bag_session(str(bag_onnx), "cpu")
        assert s1_pose is s2_pose
        assert s1_bag is s2_bag
    finally:
        if prev_env is None:
            os.environ.pop("APEX_MODELS_DIR", None)
        else:
            os.environ["APEX_MODELS_DIR"] = prev_env


def test_procedure_live_param_mutation_and_runtime_engine(tmp_path: Path):
    cams = [_StubCam("cam_01", "Aisle", "rtsp://127.0.0.1/live", zones=[_StubZone("shelf_1", "shelf")])]
    cfg = SimpleNamespace(
        cameras=cams,
        engine=SimpleNamespace(
            models_dir=str(tmp_path / "models"),
            evidence_dir=str(tmp_path / "evidence"),
            logs_dir=str(tmp_path / "logs"),
            device="cpu",
            retention_days=7,
            scheduler_fps=8.0,
        ),
        vlm=_make_vlm_cfg("secret-key-xyz"),
    )
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    broadcaster = _StubBroadcaster()
    engine = ApexRuntimeEngine(cfg, tmp_path, broadcaster, solution_path=tmp_path / "storeguard.apex")
    try:
        health = engine.get_health()
        assert health["runtime"] == "apex_vision"
        assert health["procedures"] == ["cam_01"]

        engine.set_procedure_param("cam_01", "node_motion", "diff_thresh", 24)
        assert engine.get_procedure_param("cam_01", "node_motion", "diff_thresh") == 24
        xml_out = engine.get_solution_xml()
        assert "secret-key-xyz" not in xml_out
        assert "<Parameter name=\"diff_thresh\" type=\"int\">24</Parameter>" in xml_out

        # Frame runs cleanly through VisionPipeline.execute_flow via ApexRuntimeEngine
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        out = engine.run_procedure_once("cam_01", frame_bgr=frame, timestamp=1.0)
        assert out["executed"] is True
        assert out["node_statuses"]["node_motion"] == "OK"
    finally:
        engine.stop()


def test_dynamic_batch_onnx_pose_and_bag_parity():
    import sys

    ensure_theft_plugin_loaded()
    sg_models = Path(r"C:\Users\winch\Downloads\StoreGuard\models")
    pose_onnx = sg_models / "yolo11n-pose.onnx"
    bag_onnx = sg_models / "yolo11n.onnx"
    if not pose_onnx.is_file() or not bag_onnx.is_file():
        pytest.skip("StoreGuard ONNX models not present")

    pose_mod = sys.modules["apex_plugin_theft_recognition_plugin.pose_detector_tool"]
    bag_mod = sys.modules["apex_plugin_theft_recognition_plugin.context_detector_tool"]
    psess = pose_mod.get_shared_onnx_pose_session(str(pose_onnx), "cpu")
    bsess = bag_mod.get_shared_onnx_bag_session(str(bag_onnx), "cpu")
    assert psess.supports_dynamic_batch is True
    assert bsess.supports_dynamic_batch is True

    img = np.full((360, 640, 3), 90, dtype=np.uint8)
    s_dets, _ = psess.infer(img, conf=0.25, iou=0.50, coalesce=False)
    b_out = psess.infer_batch([(img, None)] * 4, conf=0.25, iou=0.50)
    assert len(b_out) == 4
    assert len(b_out[0][0]) == len(s_dets)

    bag_single = bsess.infer(img, conf=0.25, iou=0.45, target_classes=["backpack", "handbag"], coalesce=False)
    bag_batch = bsess.infer_batch([(img, None)] * 4, conf=0.25, iou=0.45, target_classes=["backpack", "handbag"])
    assert len(bag_batch) == 4
    assert len(bag_batch[0]) == len(bag_single)


def test_dynamic_batch_broker_coalesces_concurrent_threads():
    import sys
    from concurrent.futures import ThreadPoolExecutor

    ensure_theft_plugin_loaded()
    broker_mod = sys.modules["apex_plugin_theft_recognition_plugin.batch_broker"]
    seen_batches = []
    barrier = __import__("threading").Barrier(4, timeout=2.0)

    def fake_run(arr4: np.ndarray) -> np.ndarray:
        seen_batches.append(arr4.shape[0])
        return arr4[:, :1, :1, :1] * 2.0

    broker = broker_mod.DynamicBatchBroker(fake_run, max_batch=8, max_wait_ms=40.0, supports_dynamic_batch=True)
    try:
        def worker(val: float):
            barrier.wait()
            blob = np.full((1, 3, 16, 16), val, dtype=np.float32)
            out = broker.submit(blob, coalesce=True)
            return float(out[0, 0, 0, 0])

        with ThreadPoolExecutor(max_workers=4) as pool:
            vals = list(pool.map(worker, [1.0, 2.0, 3.0, 4.0]))

        assert vals == [2.0, 4.0, 6.0, 8.0]
        metrics = broker.get_metrics()
        assert metrics["total_requests"] == 4
        assert metrics["max_batch_seen"] >= 2
        assert metrics["avg_batch_size"] > 1.0
    finally:
        broker.stop()


def test_parallel_scheduler_adaptive_fps_and_substream_snapshot(tmp_path: Path):
    import cv2
    from apex_vision.sdk.stream_worker import CameraStreamWorker

    cams = [
        _StubCam(f"cam_{i:02d}", f"Cam {i}", "", enabled=False, zones=[_StubZone("shelf_1", "shelf")])
        for i in range(1, 5)
    ]
    cfg = SimpleNamespace(
        cameras=cams,
        engine=SimpleNamespace(
            models_dir=str(tmp_path / "models"),
            evidence_dir=str(tmp_path / "evidence"),
            logs_dir=str(tmp_path / "logs"),
            device="cpu",
            retention_days=7,
            target_fps=8,
            worker_threads=4,
            idle_fps=3.0,
            batch_max_size=8,
            batch_max_wait_ms=6.0,
            use_tensorrt=True,
            decode_backend="auto",
            ring_max_width=640,
        ),
        vlm=_make_vlm_cfg(),
    )
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    engine = ApexRuntimeEngine(cfg, tmp_path, _StubBroadcaster(), solution_path=tmp_path / "multi.apex")
    try:
        health = engine.get_health()
        assert health["worker_threads"] == 4
        assert health["idle_fps"] == 3.0
        assert "tensorrt_available" in health
        assert "batch_metrics" in health

        # Verify dual-stream SD snapshot path scales overlays from HD coords onto sub-stream frame directly
        cam_sub = SimpleNamespace(camera_id="cam_sub", name="Dual", rtsp_url="rtsp://hd", sub_stream_url="rtsp://sd", enabled=False, zones=[])
        w = CameraStreamWorker(cam_sub, target_fps=8.0, ring_max_width=640)
        hd_img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        sd_img = np.full((360, 640, 3), 25, dtype=np.uint8)
        with w._lock:
            w._latest_frame = hd_img
            w._main_dims = (1920, 1080)
            w._seq = 1
            w._latest_sub_frame = sd_img
            w._sub_seq = 10
        tracks = [{"track_id": 7, "bbox": [300, 150, 180, 420], "confidence": 0.9, "phase": "REACH", "armed": True}]
        jpg = w.get_snapshot_jpeg(overlays=True, overlay_tracks=tracks, max_width=480, quality=75, cache_key="sub_test")
        assert jpg is not None
        decoded = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape == (270, 480, 3)
        # Overlay box must visibly modify pixels inside the scaled sub-stream image
        assert int(np.count_nonzero(decoded[:, :, 2] > 180)) > 50
    finally:
        engine.stop()


def test_snapshot_per_layer_overlays_and_truetype_badges():
    from apex_vision.sdk.stream_worker import CameraStreamWorker

    cam_cfg = SimpleNamespace(
        camera_id="cam_layers",
        name="Layers",
        rtsp_url="rtsp://none",
        sub_stream_url="",
        enabled=False,
        zones=[],
    )
    w = CameraStreamWorker(cam_cfg, target_fps=8.0, ring_max_width=640)
    base_img = np.full((360, 640, 3), 20, dtype=np.uint8)
    with w._lock:
        w._latest_frame = base_img
        w._main_dims = (640, 360)
        w._seq = 1

    zones = [
        {"name": "milk_shelf", "role": "shelf", "rect_norm": [0.05, 0.10, 0.25, 0.30]},
        {"name": "main_aisle", "role": "aisle", "rect_norm": [0.35, 0.10, 0.25, 0.30]},
    ]
    kps = [[300.0 + (i % 5) * 8.0, 120.0 + (i // 5) * 18.0, 0.95] for i in range(17)]
    poses = [{"Box": [260, 100, 90, 200], "Score": 0.91, "Keypoints": kps}]
    tracks = [
        {
            "track_id": 4,
            "bbox": [260, 100, 90, 200],
            "confidence": 0.91,
            "phase": "REACH",
            "armed": False,
            "keypoints": kps,
            "trail": [(300, 280), (305, 260), (310, 240)],
        }
    ]
    bags = [{"Box": [450, 180, 60, 70], "Class": "backpack", "Score": 0.88}]
    motion_roi = [40, 40, 520, 280]

    raw_jpg = w.get_snapshot_jpeg(zones=zones, overlays=False)
    shelf_only = w.get_snapshot_jpeg(
        zones=zones,
        overlays=True,
        overlay_layers="shelf",
        overlay_tracks=tracks,
        overlay_poses=poses,
        overlay_bags=bags,
        overlay_motion_roi=motion_roi,
    )
    aisle_only = w.get_snapshot_jpeg(
        zones=zones,
        overlays=True,
        overlay_layers="aisle",
        overlay_tracks=tracks,
        overlay_poses=poses,
        overlay_bags=bags,
        overlay_motion_roi=motion_roi,
    )
    pose_only = w.get_snapshot_jpeg(
        zones=zones,
        overlays=True,
        overlay_layers="pose",
        overlay_tracks=tracks,
        overlay_poses=poses,
        overlay_bags=bags,
        overlay_motion_roi=motion_roi,
    )
    botsort_only = w.get_snapshot_jpeg(
        zones=zones,
        overlays=True,
        overlay_layers="botsort",
        overlay_tracks=tracks,
        overlay_poses=poses,
        overlay_bags=bags,
        overlay_motion_roi=motion_roi,
    )
    bags_only = w.get_snapshot_jpeg(
        zones=zones,
        overlays=True,
        overlay_layers="bags",
        overlay_tracks=tracks,
        overlay_poses=poses,
        overlay_bags=bags,
        overlay_motion_roi=motion_roi,
    )
    motion_only = w.get_snapshot_jpeg(
        zones=zones,
        overlays=True,
        overlay_layers="motion",
        overlay_tracks=tracks,
        overlay_poses=poses,
        overlay_bags=bags,
        overlay_motion_roi=motion_roi,
    )

    for b in (raw_jpg, shelf_only, aisle_only, pose_only, botsort_only, bags_only, motion_only):
        assert b is not None and len(b) > 500
    assert shelf_only != raw_jpg
    assert shelf_only != aisle_only
    assert pose_only != botsort_only
    assert bags_only != raw_jpg
    assert motion_only != raw_jpg
