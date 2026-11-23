"""Senior QA tests for the Hybrid C++17 `_apex_core` extension and `_native` bridge."""
import sys
import threading
import time

import cv2
import numpy as np
import pytest

from apex_vision.core import _native, dl_engine
from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus, VisionToolBase
from apex_vision.core.pipeline import FlowConnection, VisionPipeline
from apex_vision.tools.object_detection import ObjectDetectionTool


def test_native_core_active_on_windows():
    info = _native.native_info()
    if sys.platform == "win32":
        assert _native.is_native_active() is True
        assert info["active"] is True
        assert info["cpp_std"] >= 201703
        assert info["hardware_concurrency"] >= 1


def test_kahn_sort_and_waves_parity():
    ids = ["n1", "n2", "n3", "n4", "iso"]
    edges = [("n1", "n2"), ("n1", "n3"), ("n2", "n4"), ("n3", "n4")]

    c_order = _native.kahn_sort(ids, edges)
    assert c_order.index("n1") < c_order.index("n2")
    assert c_order.index("n1") < c_order.index("n3")
    assert c_order.index("n2") < c_order.index("n4")
    assert c_order.index("n3") < c_order.index("n4")
    assert set(c_order) == set(ids)

    waves = _native.compute_execution_waves(c_order, edges)
    assert waves[0] == ["n1", "iso"]
    assert set(waves[1]) == {"n2", "n3"}
    assert waves[2] == ["n4"]


def test_kahn_and_cycle_detection_on_cycles():
    ids = ["a", "b", "c", "d"]
    cyclic_edges = [("a", "b"), ("b", "c"), ("c", "b"), ("c", "d")]

    order = _native.kahn_sort(ids, cyclic_edges)
    # Cyclic nodes must still be preserved in order (no silent drops)
    assert order == ["a", "b", "c", "d"]

    cyc = _native.find_cycle_nodes(ids, cyclic_edges)
    assert "b" in cyc and "c" in cyc
    assert "a" not in cyc

    acyclic = _native.find_cycle_nodes(["x", "y", "z"], [("x", "y"), ("y", "z")])
    assert acyclic == []


def test_pipeline_validate_flow_uses_native_cycle_check():
    class DummyTool(VisionToolBase):
        tool_name = "DummyCycleCheck"
        def _init_ports(self):
            self.inputs["In"] = ToolPort("In", DataType.ANY)
            self.outputs["Out"] = ToolPort("Out", DataType.ANY)
        def execute(self, context):
            return ToolExecutionResult(ToolStatus.OK)

    pipe = VisionPipeline()
    pipe.add_node(DummyTool("a", "A"))
    pipe.add_node(DummyTool("b", "B"))
    pipe.connections.append(FlowConnection("a", "Out", "b", "In"))
    pipe.connections.append(FlowConnection("b", "Out", "a", "In"))
    issues = pipe.validate_flow()
    assert any("circular dependencies" in i["message"].lower() for i in issues)


def test_ring_buffer_fifo_overwrite_and_concurrency():
    rb = _native.create_ring_buffer(capacity=3, reserve_bytes=64 * 64 * 3)
    assert rb.latest() is None
    assert rb.pop() is None

    # Push 5 frames into capacity 3 -> 2 dropped, newest 3 retained
    for i in range(1, 6):
        img = np.full((16, 16, 3), i * 20, dtype=np.uint8)
        rb.push(img, frame_id=i, timestamp_s=float(i) * 0.1)

    st = rb.stats()
    assert st["capacity"] == 3
    assert st["count"] == 3
    assert st["total_pushed"] == 5
    assert st["dropped"] == 2

    latest_img, latest_meta = rb.latest()
    assert latest_meta["frame_id"] == 5
    assert int(latest_img[0, 0, 0]) == 100

    # Pop oldest remaining (3, 4, 5)
    popped_ids = []
    while True:
        item = rb.pop()
        if item is None:
            break
        arr, meta = item
        popped_ids.append((meta["frame_id"], int(arr[0, 0, 0])))
    assert popped_ids == [(3, 60), (4, 80), (5, 100)]

    # Multithreaded push & read stress test
    errors = []

    def writer():
        try:
            for k in range(100):
                rb.push(np.full((8, 8), k % 255, dtype=np.uint8), frame_id=k, timestamp_s=float(k))
        except Exception as exc:
            errors.append(exc)

    def reader():
        try:
            for _ in range(100):
                item = rb.latest()
                if item is not None:
                    arr, _ = item
                    assert arr.shape == (8, 8)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    rb.clear()
    assert rb.latest() is None


def test_nms_and_yolo_decode_parity_with_python():
    rng = np.random.default_rng(42)
    # YOLOv8/v11 style output: (1, 4 + 3 classes, 40 candidates)
    out = np.zeros((1, 7, 40), dtype=np.float32)
    out[0, 0, :] = rng.uniform(50, 550, 40)
    out[0, 1, :] = rng.uniform(50, 550, 40)
    out[0, 2, :] = rng.uniform(20, 80, 40)
    out[0, 3, :] = rng.uniform(20, 80, 40)
    out[0, 4:, :] = rng.uniform(0.05, 0.95, (3, 40)).astype(np.float32)

    info = {"scale": (1.0, 1.0), "pad": (0, 0), "orig": (640, 640)}

    cpp_dets = dl_engine.decode_detections([out], info, conf=0.4, iou=0.45, max_det=20)

    # Compare against pure-Python fallback
    orig_core = _native._CORE
    try:
        _native._CORE = None
        py_dets = dl_engine.decode_detections([out], info, conf=0.4, iou=0.45, max_det=20)
    finally:
        _native._CORE = orig_core

    assert len(cpp_dets) == len(py_dets) and len(cpp_dets) > 0
    for cd, pd in zip(cpp_dets, py_dets):
        assert cd["class_id"] == pd["class_id"]
        assert abs(cd["score"] - pd["score"]) < 1e-5
        assert np.allclose(cd["box"], pd["box"], atol=1e-4)

    # End-to-end (N, 6) format
    e2e = np.array([[10, 20, 110, 120, 0.9, 2], [15, 25, 45, 55, 0.2, 1]], dtype=np.float32)
    e2e_dets = dl_engine.decode_detections([e2e], info, conf=0.5, iou=0.45, max_det=10)
    assert len(e2e_dets) == 1
    assert e2e_dets[0]["class_id"] == 2
    assert np.allclose(e2e_dets[0]["box"], [10, 20, 100, 100], atol=1e-4)


def test_optical_stats_and_union_box():
    # Sharp checkerboard image vs blurred image -> sharp must have much higher Laplacian variance
    sharp = np.zeros((100, 100, 3), dtype=np.uint8)
    sharp[::2, ::2] = 255
    sharp[1::2, 1::2] = 255
    blurred = cv2.GaussianBlur(sharp, (9, 9), 3.0)

    st_sharp = _native.compute_optical_stats(sharp)
    st_blur = _native.compute_optical_stats(blurred)
    assert st_sharp["laplacian_variance"] > st_blur["laplacian_variance"] * 5.0
    assert st_sharp["max_val"] == 255
    assert st_sharp["min_val"] == 0

    union = _native.compute_union_box([[10, 20, 30, 40], [50, 10, 20, 60]])
    assert union == [10, 10, 60, 60]
    assert _native.compute_union_box([]) == [0, 0, 0, 0]


def test_fallback_parity_when_native_disabled():
    orig_core = _native._CORE
    try:
        _native._CORE = None
        assert _native.is_native_active() is False
        assert _native.kahn_sort(["a", "b"], [("a", "b")]) == ["a", "b"]
        assert _native.find_cycle_nodes(["a", "b"], [("a", "b"), ("b", "a")]) == ["a", "b"]
        assert _native.compute_union_box([[0, 0, 10, 10], [5, 5, 10, 10]]) == [0, 0, 15, 15]
        rb = _native.create_ring_buffer(2)
        rb.push(np.zeros((4, 4), dtype=np.uint8), 7, 1.0)
        assert rb.latest()[1]["frame_id"] == 7
    finally:
        _native._CORE = orig_core
