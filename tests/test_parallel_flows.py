"""Senior QA concurrency & multi-flow tests for parallel solution execution."""
import os
import threading
import time

import numpy as np
import pytest

from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus, VisionToolBase
from apex_vision.core.camera_manager import CameraManager
from apex_vision.core.pipeline import SolutionManager


class _SleepTool(VisionToolBase):
    tool_name = "_QaParallelSleep"

    def __init__(self, instance_id: str, name: str = None, delay_s: float = 0.12, counter_key: str = ""):
        self.delay_s = delay_s
        self.counter_key = counter_key
        self.calls = 0
        super().__init__(instance_id, name=name)

    def _init_ports(self):
        self.outputs["Value"] = ToolPort("Value", DataType.VALUE)

    def execute(self, context):
        self.calls += 1
        if self.delay_s > 0:
            time.sleep(self.delay_s)  # releases GIL (simulates C++/I/O wait)
        g = context.get("global", {})
        gv = g.get("globals")
        lock = g.get("global_lock")
        if self.counter_key and gv is not None:
            if lock is not None:
                with lock:
                    gv[self.counter_key] = int(gv.get(self.counter_key, 0)) + 1
            else:
                gv[self.counter_key] = int(gv.get(self.counter_key, 0)) + 1
        return ToolExecutionResult(ToolStatus.OK, "OK", {"Value": self.calls})


def test_execute_all_flows_runs_in_parallel_and_preserves_order():
    sol = SolutionManager("ParallelTest")
    sol.flows.clear()
    for i in range(3):
        f = sol.add_flow(f"Flow{i + 1}")
        f.add_node(_SleepTool(f"n{i}", delay_s=0.15))

    # Disabled flow must not execute
    disabled = sol.add_flow("DisabledFlow")
    disabled.enabled = False
    disabled_tool = _SleepTool("ndis", delay_s=0.5)
    disabled.add_node(disabled_tool)

    t0 = time.perf_counter()
    res = sol.execute_all_flows(parallel=True)
    elapsed_parallel = time.perf_counter() - t0

    assert list(res.keys()) == ["Flow1", "Flow2", "Flow3"]
    assert disabled_tool.calls == 0
    # 3 x 0.15s = 0.45s sequentially; parallel must finish well under 0.32s
    assert elapsed_parallel < 0.32, f"Expected parallel execution <0.32s, got {elapsed_parallel:.3f}s"
    assert all(r["n" + str(i)].status == ToolStatus.OK for i, r in enumerate([res["Flow1"], res["Flow2"], res["Flow3"]]))


def test_global_variables_thread_safety_under_concurrent_flows():
    sol = SolutionManager("GlobalsRaceTest")
    sol.flows.clear()
    sol.set_global("shared_hits", 0)

    for i in range(4):
        f = sol.add_flow(f"Worker{i}")
        f.add_node(_SleepTool(f"w{i}", delay_s=0.0, counter_key="shared_hits"))

    for _ in range(100):
        sol.execute_all_flows(parallel=True)

    assert sol.get_global("shared_hits") == 400
    snap = sol.to_dict()
    assert snap["global_variables"]["shared_hits"] == 400


def test_camera_driver_thread_safety_and_ring_buffer():
    cm = CameraManager.get_instance()
    driver = cm.get_or_create_driver("virtual_gige_0")
    assert driver is not None
    driver.ring_buffer.clear()

    errors = []

    def grab_many():
        try:
            for _ in range(10):
                d = cm.get_or_create_driver("virtual_gige_0")
                ok, frame, _ = d.capture_frame()
                assert ok and frame is not None and frame.ndim == 3
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=grab_many) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    stats = driver.ring_buffer.stats()
    assert stats["total_pushed"] >= 40
    assert driver.latest_buffered_frame() is not None


def test_qml_backend_run_all_parallel_and_independent_stop():
    """Verify AppBackend.runAll() runs flows concurrently, supports independent stop/rejoin,
    and respects single-flow run() vs top runAll()."""
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtTest import QTest
    from apex_vision.qml_backend import AppBackend, FrameProvider

    qt_app = QGuiApplication.instance() or QGuiApplication([])
    provider = FrameProvider()
    backend = AppBackend(provider)

    sol = SolutionManager("BackendParallel")
    sol.flows.clear()

    fast_tool = _SleepTool("fast_n", delay_s=0.02)
    slow_tool = _SleepTool("slow_n", delay_s=0.14)
    f1 = sol.add_flow("FastFlow")
    f1.run_interval_ms = 20.0
    f1.add_node(fast_tool)

    f2 = sol.add_flow("SlowFlow")
    f2.run_interval_ms = 20.0
    f2.add_node(slow_tool)

    backend.load_solution(sol, sample_images=False)
    # Wait for load_solution's initial active-flow cycle to finish
    backend.engine.wait_for_run()
    fast_tool.calls = 0
    slow_tool.calls = 0

    # 1. Active tab run() only touches the active flow (FastFlow)
    backend.selectFlow("FastFlow")
    backend.run()
    deadline = time.perf_counter() + 2.0
    while (backend.engine.busy or backend.engine.is_strip_busy()) and time.perf_counter() < deadline:
        qt_app.processEvents()
        QTest.qWait(10)
    assert fast_tool.calls == 1
    assert slow_tool.calls == 0

    # 2. One-shot runAll() runs BOTH flows in parallel
    fast_tool.calls = 0
    slow_tool.calls = 0
    t0 = time.perf_counter()
    backend.runAll()
    deadline = time.perf_counter() + 2.0
    while backend._all_active and time.perf_counter() < deadline:
        qt_app.processEvents()
        QTest.qWait(10)
    elapsed = time.perf_counter() - t0
    assert not backend._all_active
    assert fast_tool.calls == 1 and slow_tool.calls == 1
    assert elapsed < 0.50

    # 3. Continuous parallel loop: FastFlow runs multiple cycles without waiting for SlowFlow
    fast_tool.calls = 0
    slow_tool.calls = 0
    backend.allLoop = True
    backend.runAll()

    t_start = time.perf_counter()
    while time.perf_counter() - t_start < 0.35:
        qt_app.processEvents()
        QTest.qWait(15)

    assert fast_tool.calls >= slow_tool.calls + 2, (
        f"Expected FastFlow ({fast_tool.calls}) to outpace SlowFlow ({slow_tool.calls}) independently"
    )

    # Stopping FastFlow leaves SlowFlow running
    backend.selectFlow("FastFlow")
    backend.stop()
    fast_at_stop = fast_tool.calls
    slow_at_stop = slow_tool.calls
    assert backend._all_live()
    assert "FastFlow" not in backend._all_flows
    assert "SlowFlow" in backend._all_flows

    t_mid = time.perf_counter()
    while time.perf_counter() - t_mid < 0.25:
        qt_app.processEvents()
        QTest.qWait(15)
    assert slow_tool.calls > slow_at_stop
    assert fast_tool.calls <= fast_at_stop + 1  # allows at most 1 in-flight cycle completing

    # stopAll() terminates cleanly
    backend.stopAll()
    deadline = time.perf_counter() + 2.0
    while backend._all_active and time.perf_counter() < deadline:
        qt_app.processEvents()
        QTest.qWait(10)
    assert not backend._all_active
    assert backend._all_flows == []
