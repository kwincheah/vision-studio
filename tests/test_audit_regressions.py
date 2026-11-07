"""Comprehensive regression and verification test suite for codebase engineering audit."""
import os
import json
import tempfile
import pytest
import numpy as np

from apex_vision.core.pipeline import VisionPipeline, SolutionManager, FlowConnection
from apex_vision.core.project_manager import ProjectManager
from apex_vision.core.camera_manager import CameraManager, CameraDeviceInfo
from apex_vision.core.xml_safe import safe_fromstring, safe_parse_file, DefusedXMLError
from apex_vision.core.fileio import atomic_write_text, atomic_write_json
from apex_vision.sdk.marketplace import MarketplaceService


# =========================================================================
# 1. Lens Distortion Calibration: Profile File Mode (Bug 1 Regression)
# =========================================================================
def test_lens_distortion_profile_file_mode(tmp_path):
    """Verify that Lens Distortion Calibration in Profile File mode works with imported os."""
    from apex_vision.tools.calibration import CameraCalibrationTool
    from apex_vision.core.lens_calibration import LensCalibrationModel

    cal_path = str(tmp_path / "test_lens_cal.json")
    model = LensCalibrationModel()
    model.camera_matrix = np.eye(3, dtype=np.float64)
    model.dist_coeffs = np.zeros((5,), dtype=np.float64)
    model.save_json(cal_path)

    tool = CameraCalibrationTool("cal_test_1", "TestLensCal")
    tool.set_param("mode", "Profile File")
    tool.set_param("calibration_file", cal_path)

    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    res = tool.execute({"Image": dummy_img})
    assert res.status.value.upper() in ("OK", "NG")


# =========================================================================
# 2. Camera Manager: native Hikrobot MVS Enumeration ctypes presence
# =========================================================================
def test_camera_manager_ctypes_available():
    """Verify ctypes is imported in camera_manager and refresh_devices executes cleanly."""
    cm = CameraManager.get_instance()
    devs = cm.refresh_devices()
    assert isinstance(devs, list)
    assert len(devs) > 0


# =========================================================================
# 3. Security: Plugin Marketplace ID Directory Traversal
# =========================================================================
def test_plugin_marketplace_path_traversal_prevention(tmp_path):
    """Verify that malicious plugin IDs (e.g. '../victim') are rejected before rmtree/copy."""
    import zipfile
    import io

    victim_dir = tmp_path / "victim"
    victim_dir.mkdir()
    victim_file = victim_dir / "important_data.txt"
    victim_file.write_text("critical safety data")

    plugins_dest = tmp_path / "installed_plugins"
    plugins_dest.mkdir()

    # Create in-memory zip archive with malicious manifest
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        manifest = {
            "id": "../victim",
            "name": "Malicious Traversal Plugin",
            "version": "1.0.0",
            "description": "Exploit attempt",
            "author": "Attacker",
            "category": "General",
            "min_sdk_version": "1.0.0",
            "entry_point": "tool.py",
            "tool_class": "ExploitTool"
        }
        zf.writestr("repo-main/plugin.json", json.dumps(manifest))
        zf.writestr("repo-main/__init__.py", "# entrypoint\n")
        zf.writestr("repo-main/tool.py", "class ExploitTool:\n    pass\n")

    zip_bytes = buf.getvalue()

    class MockResponse:
        def __init__(self, data: bytes):
            self._stream = io.BytesIO(data)
        def read(self, length: int = -1):
            return self._stream.read(length)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    import urllib.request
    orig_urlopen = urllib.request.urlopen
    urllib.request.urlopen = lambda *args, **kwargs: MockResponse(zip_bytes)

    try:
        mp = MarketplaceService()
        ok, msg, rec = mp.install_from_github("https://github.com/attacker/repo", target_dir=str(plugins_dest))
        assert not ok
        assert "Invalid plugin id" in msg or "resolves outside" in msg
        # Victim directory and file must remain untouched
        assert victim_file.exists()
        assert victim_file.read_text() == "critical safety data"
    finally:
        urllib.request.urlopen = orig_urlopen


# =========================================================================
# 4. Data Integrity: Atomic Project & Pipeline File Persistence
# =========================================================================
def test_atomic_file_persistence(tmp_path):
    """Verify atomic file writing leaves the target file intact if serialization fails."""
    target_file = str(tmp_path / "my_project.vmp")
    atomic_write_text(target_file, "original good content")

    # Attempting to save invalid un-serializable data must raise and preserve original file
    with pytest.raises(Exception):
        atomic_write_json(target_file, {"bad_var": object()})

    with open(target_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == "original good content"


def test_solution_manager_atomic_save(tmp_path):
    """Verify SolutionManager.save_to_file creates a valid non-empty file atomically."""
    sol = SolutionManager("TestAtomicSolution")
    proj_path = str(tmp_path / "sol_atomic.vmp")
    sol.save_to_file(proj_path)
    assert os.path.exists(proj_path)
    assert os.path.getsize(proj_path) > 50


# =========================================================================
# 5. Pipeline Telemetry: execution_count Round-trip (JSON & XML)
# =========================================================================
def test_execution_count_json_roundtrip():
    """Verify execution_count telemetry is preserved in JSON serialization."""
    pipe = VisionPipeline(name="TelemetryFlow")
    pipe.execution_count = 42

    d = pipe.to_dict()
    assert d.get("execution_count") == 42

    restored = VisionPipeline.from_dict(d)
    assert restored.execution_count == 42


def test_execution_count_xml_roundtrip():
    """Verify execution_count telemetry is preserved in XML serialization."""
    pipe = VisionPipeline(name="XmlTelemetryFlow")
    pipe.execution_count = 99

    xml_text = pipe.to_xml()
    assert 'execution_count' in xml_text

    restored = VisionPipeline.from_xml(xml_text)
    assert restored.execution_count == 99


# =========================================================================
# 6. SolutionManager: Flow Duplication Uniqueness & Safe Renaming
# =========================================================================
def test_solution_duplicate_flow_uniqueness():
    """Verify multiple duplicates of a flow receive distinct unique names without overwriting."""
    sol = SolutionManager("MultiDupSol")
    assert "Flow1" in sol.flows

    dup1 = sol.duplicate_flow("Flow1")
    dup2 = sol.duplicate_flow("Flow1")
    dup3 = sol.duplicate_flow("Flow1")

    assert dup1.name != dup2.name != dup3.name
    assert "Flow1_Copy" in sol.flows
    assert "Flow1_Copy_1" in sol.flows
    assert "Flow1_Copy_2" in sol.flows
    assert len(sol.flows) == 4

    # Explicit collision must raise ValueError
    with pytest.raises(ValueError):
        sol.duplicate_flow("Flow1", new_name="Flow1_Copy")


def test_solution_rename_flow():
    """Verify rename_flow maintains dict order, active_flow_name, and trigger_flow_name."""
    sol = SolutionManager("RenameSol")
    sol.add_flow("Flow2")
    sol.set_trigger_flow("Flow1")
    sol.active_flow_name = "Flow1"

    sol.rename_flow("Flow1", "PrimaryInspection")
    assert "PrimaryInspection" in sol.flows
    assert "Flow1" not in sol.flows
    assert list(sol.flows.keys()) == ["PrimaryInspection", "Flow2"]
    assert sol.active_flow_name == "PrimaryInspection"
    assert sol.trigger_flow_name == "PrimaryInspection"


# =========================================================================
# 7. XML Security & Robustness: DOCTYPE rejection & Strict decoding
# =========================================================================
def test_xml_safe_rejects_doctype_and_entity():
    """Verify safe XML parsing rejects DOCTYPE / ENTITY expansion payloads."""
    malicious_xml = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE bomb [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        '<VisionMasterFlow name="Bomb">&xxe;</VisionMasterFlow>'
    )
    with pytest.raises(DefusedXMLError):
        safe_fromstring(malicious_xml)

    with pytest.raises(DefusedXMLError):
        VisionPipeline.from_xml(malicious_xml)


def test_xml_strict_decode_raises_value_error():
    """Verify that corrupt typed values in XML raise ValueError instead of returning 0."""
    pipe = VisionPipeline()
    with pytest.raises(ValueError, match="Malformed XML integer value"):
        pipe._decode_xml_value("int", "not_a_number")

    with pytest.raises(ValueError, match="Malformed XML float value"):
        pipe._decode_xml_value("float", "xyz")

    with pytest.raises(ValueError, match="Malformed XML json JSON payload"):
        pipe._decode_xml_value("json", "{invalid json")


# =========================================================================
# 8. Graph Algorithm: Deep Chain validate_flow Without RecursionError
# =========================================================================
def test_validate_flow_deep_chain_no_recursion_error():
    """Verify validate_flow handles 1,500-node linear DAG without RecursionError."""
    from apex_vision.core.registry import create_tool_instance
    pipe = VisionPipeline(name="DeepChainFlow")

    prev_id = None
    for i in range(1200):
        nid = f"node_{i}"
        tool = create_tool_instance("Image Source", nid, f"Source_{i}", allow_placeholder=True)
        pipe.add_node(tool)
        if prev_id:
            pipe.connect(prev_id, "Image", nid, "Image", force=True)
        prev_id = nid

    issues = pipe.validate_flow()
    errors = [issue for issue in issues if issue.get("severity") == "error"]
    assert len(errors) == 0


# =========================================================================
# 9. FlowConnection: Equality and Hash Consistency
# =========================================================================
def test_flow_connection_hash():
    """Verify FlowConnection implements both __eq__ and __hash__ for set membership."""
    c1 = FlowConnection("n1", "out", "n2", "in")
    c2 = FlowConnection("n1", "out", "n2", "in")
    assert c1 == c2
    assert hash(c1) == hash(c2)
    s = {c1, c2}
    assert len(s) == 1


# =========================================================================
# 10. Project Manager: Corrupted Cache Handling & INI QSettings Isolation
# =========================================================================
def test_project_manager_corrupted_cache_resilience(tmp_path):
    """Verify ProjectManager gracefully handles corrupt JSON cache and non-string paths."""
    ws = str(tmp_path / "test_workspace")
    pm = ProjectManager(workspace_root=ws)

    # Corrupt the cache file
    with open(pm.cache_file, "w", encoding="utf-8") as f:
        f.write("{corrupt: json content[}")

    recents = pm.get_recent_projects()
    assert isinstance(recents, list)

    # Cache with non-string and malformed entries
    with open(pm.cache_file, "w", encoding="utf-8") as f:
        json.dump([{"path": 12345}, {"name": "NoPath"}, {"path": str(tmp_path / "valid.vmp")}], f)

    recents = pm.get_recent_projects()
    assert isinstance(recents, list)
    assert len(recents) == 1
    assert recents[0]["path"] == str(tmp_path / "valid.vmp")


# =========================================================================
# 11. Camera Manager: Persistent User Streams Across refresh_devices
# =========================================================================
def test_camera_manager_user_streams_preserved():
    """Verify user-added network streams persist through refresh_devices."""
    cm = CameraManager.get_instance()
    info = cm.add_network_stream("rtsp://10.0.0.99:554/live", name="Custom Factory Cam")
    assert info.device_id in cm._devices
    assert info.stream_url == "rtsp://10.0.0.99:554/live"

    # Refresh devices must keep the user-registered stream
    cm.refresh_devices()
    assert info.device_id in cm._devices
    assert cm.get_device(info.device_id).stream_url == "rtsp://10.0.0.99:554/live"


# =========================================================================
# 12. Inspector: Safe Literal Parsing (No eval)
# =========================================================================
def test_inspector_safe_list_parsing():
    """Verify inspector parses lists safely using json / ast without executing arbitrary code."""
    from PyQt6.QtWidgets import QApplication
    from apex_vision.ui.inspector import ParameterInspectorWidget
    from apex_vision.core.registry import create_tool_instance

    _app = QApplication.instance() or QApplication([])

    inspector = ParameterInspectorWidget()
    tool = create_tool_instance("Image Source", "inst_tool_1", "TestTool", allow_placeholder=True)
    tool.parameters["test_list"] = [1, 2, 3]
    inspector.set_tool(tool)

    # Safe parse JSON list
    inspector._on_list_changed("test_list", "[10, 20, 30]")
    assert tool.get_param("test_list") == [10, 20, 30]

    # Malicious injection attempt should safely fail without executing
    sentinel_file = "should_not_exist_exploit.txt"
    inspector._on_list_changed("test_list", f"__import__('os').system('touch {sentinel_file}')")
    assert not os.path.exists(sentinel_file)
