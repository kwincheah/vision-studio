"""The QML tool services (lens calibration, camera, plugins, inspection) driven without any QML."""
import os
import sys
import time

import cv2
import numpy as np
import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication

from vm_clone.core.pipeline import SolutionManager
from vm_clone.qml_backend import AppBackend, FrameProvider
from vm_clone.qml_services import CameraService, InspectionService, LensService, PluginService

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEMO = os.path.join(ROOT, "projects", "PCB_Inspection_Demo.vmp")


@pytest.fixture(scope="module")
def gui():
    return QGuiApplication.instance() or QGuiApplication(sys.argv)


def spin(app, predicate, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end and not predicate():
        app.processEvents()
        time.sleep(0.005)
    return predicate()


@pytest.fixture
def app_backend(gui):
    backend = AppBackend(FrameProvider())
    backend._solution = SolutionManager.load_from_file(DEMO)
    backend._freeze_layout()
    backend._project.mark_saved(backend._solution)
    return backend


def url(path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()


# ----------------------------------------------------------------------------- lens
def test_lens_service_calibrates_previews_saves_and_applies(gui, app_backend, tmp_path):
    provider = FrameProvider()
    lens = LensService(app_backend, provider)
    lens.compute()
    assert "at least 1" in lens.status                       # nothing to solve yet
    for _ in range(3):
        lens.addSynthetic()
    assert [v["ok"] for v in lens.views] == [True, True, True] and lens.currentView == 2
    assert not provider.image.isNull()                       # detected-corners preview rendered
    lens.setMode("Undistorted (Rectified)")
    assert not lens.result["calibrated"]
    lens.compute()
    assert lens.result["calibrated"] and lens.result["rms"] < 1.0 and lens.result["valid_views"] == 3
    lens.setMode("Undistorted (Rectified)")
    assert provider.image.width() == 800
    lens.remove(0)
    assert len(lens.views) == 2 and lens.session.model.object_points_list.__len__() == 2
    profile = tmp_path / "lens.calib.json"
    lens.saveProfile(url(profile))
    assert profile.exists()
    fresh = LensService(app_backend, FrameProvider())
    fresh.loadProfile(url(profile))
    assert fresh.result["calibrated"]
    # apply to the active flow: the module is created, wired to the source and parameterised
    before = len(app_backend.nodes)
    lens.apply()
    nodes = app_backend.nodes
    assert len(nodes) == before + 1
    node = next(n for n in app_backend._pipeline.nodes.values() if n.tool_name == "Lens Distortion Calibration")
    assert node.parameters["mode"] == "Manual Coefficients" and node.parameters["manual_fx"] > 100
    app_backend.undo()
    assert len(app_backend.nodes) == before


def test_lens_service_rejects_images_without_a_pattern(gui, app_backend, tmp_path):
    lens = LensService(app_backend, FrameProvider())
    path = tmp_path / "blank.png"
    cv2.imwrite(str(path), np.full((120, 160, 3), 200, np.uint8))
    lens.addFiles([url(path)])
    assert lens.views[0]["ok"] is False
    lens.compute()
    assert not lens.result["calibrated"]
    lens.setPattern("Chessboard", 1, 1, -3)                   # clamped, never crashes
    assert lens.pattern["cols"] == 3 and lens.pattern["squareMm"] > 0


# ----------------------------------------------------------------------------- camera
def test_camera_service_lists_selects_and_streams_frames(gui, app_backend):
    provider = FrameProvider()
    cam = CameraService(app_backend, provider)
    cam.refresh()
    assert cam.devices and "device" in cam.status
    assert "SDK" in cam.sdkStatus
    # other tests may have registered network streams; stream with a device that really emits frames
    index = next(i for i, d in enumerate(cam.devices) if d["type"].startswith("Hikrobot MVS"))
    cam.select(index)
    assert cam.selected == index
    cam.setParams(15000.0, 2.0, "Continuous", "BGR8 (Color)")
    cam.startPreview()
    assert cam.previewing
    assert spin(gui, lambda: not provider.image.isNull(), timeout=10)
    cam.stopPreview()
    assert not cam.previewing
    cam.startPreview()                                         # restartable
    cam.shutdown()
    cam.select(99)                                             # out of range is ignored


# ----------------------------------------------------------------------------- plugins
def test_plugin_service_scaffolds_validates_and_packages(gui, app_backend, tmp_path):
    svc = PluginService(app_backend)
    assert isinstance(svc.installed, list)
    svc.scaffold(url(tmp_path), "demo_blur", "Demo Blur", "Tester", "Custom Filters", "Demo Blur Tool", "x")
    assert (tmp_path / "demo_blur" / "plugin.json").exists() and "Created" in svc.log
    svc.package(url(tmp_path / "demo_blur"))
    assert (tmp_path / "demo_blur.vmpkg").exists() and "Packaged" in svc.log
    svc.loadFolder(url(tmp_path / "demo_blur"))
    assert any(p["name"] == "Demo Blur" for p in svc.installed)
    svc.unload(next(p["id"] for p in svc.installed if p["name"] == "Demo Blur"))
    assert not any(p["name"] == "Demo Blur" for p in svc.installed)
    svc.installGithub("", "main")
    assert "Enter a GitHub" in svc.log
    svc.installGithub("not a url", "main")
    assert spin(gui, lambda: not svc.busy, timeout=15)
    assert "Failed" in svc.log


def test_tool_categories_include_plugin_tools(gui, app_backend, tmp_path):
    svc = PluginService(app_backend)
    svc.scaffold(url(tmp_path), "cat_plugin", "Cat Plugin", "T", "Custom Filters", "Cat Tool", "x")
    svc.loadFolder(url(tmp_path / "cat_plugin"))
    tools = [t for c in app_backend.toolCategories for t in c["tools"]]
    assert "Cat Tool" in tools and "Image Source" in tools
    svc.unload("cat_plugin")


# ----------------------------------------------------------------------------- inspection
def test_inspection_service_full_evaluation_cycle(gui, app_backend, tmp_path):
    provider = FrameProvider()
    svc = InspectionService(app_backend, provider, str(tmp_path / "store"))
    svc.run("Reference detector", "reference", 0.5, 0.0, True)
    assert "Load or generate" in svc.error
    svc.generateDataset(url(tmp_path), 8)
    assert svc.error == "" and "8 images" in svc.datasetText
    for variant in ("reference", "conservative"):
        svc.run("Reference detector", variant, 0.5, 0.0, True)
        assert svc.busy
        assert spin(gui, lambda: not svc.busy)
        assert svc.error == "", svc.error
        assert any(m["name"] == "Precision" for m in svc.metrics) and svc.perClass
        svc.saveExperiment(f"exp-{variant}")
    assert [e["name"] for e in svc.experiments] == ["exp-conservative", "exp-reference"] or \
        sorted(e["name"] for e in svc.experiments) == ["exp-conservative", "exp-reference"]
    # failures: filter and view a case with its box drawn
    total = len(svc.failures)
    assert "failure(s)" in svc.failureSummary or total == 0
    if total:
        svc.setFilter("FN", "All", 0.0)
        assert all(f["kind"] == "FN" for f in svc.failures)
        svc.setFilter("All", "All", 0.0)
        svc.showCase(0)
        assert not provider.image.isNull()
    svc.compare("exp-reference", "exp-conservative")
    assert {r["metric"] for r in svc.comparison["rows"]} >= {"precision", "recall", "f1"}
    svc.compare("exp-reference", "exp-reference")
    assert svc.comparison["warnings"] == ["Pick two different experiments"]
    assert "Precision" in svc.reportText()


def test_inspection_service_can_cancel_and_reports_bad_dataset(gui, app_backend, tmp_path):
    svc = InspectionService(app_backend, FrameProvider(), str(tmp_path / "store"))
    svc.loadDataset(url(tmp_path / "missing.json"))
    assert "not found" in svc.error
    svc.generateDataset(url(tmp_path), 40)
    svc.run("Reference detector", "reference", 0.5, 0.0, True)
    svc.cancel()
    assert spin(gui, lambda: not svc.busy)
    svc.saveExperiment("after-cancel")
    # a cancelled run is either saved or the user is told why - never silently dropped
    assert any(e["name"] == "after-cancel" for e in svc.experiments) or svc.error != ""
