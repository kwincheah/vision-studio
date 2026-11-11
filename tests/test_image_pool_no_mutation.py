"""Regression: applying a strip image must not mutate the project.

`ImagePool.apply_to` used to write `source_type` / `file_path` into the Image Source node
on every run and every strip click.  The visible effect was a project that reported
"unsaved changes" after a harmless Run, and - if the operator saved, as that prompt invites
- a project on disk whose Synthetic source had become a File source with an absolute path.

These tests pin the boundary: choosing which picture to run is execution state, choosing a
project's *source* is a user action.
"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from apex_vision.core.controller import ImagePool          # noqa: E402
from apex_vision.core.pipeline import VisionPipeline        # noqa: E402
from apex_vision.core.registry import create_tool_instance  # noqa: E402


def _source_node():
    return create_tool_instance("Image Source", "src1", "01_Acquisition")


def _pipeline_with_source():
    pipe = VisionPipeline(name="F")
    pipe.add_node(_source_node())
    return pipe


def _pool_with(image=None, path=None, name="pic"):
    """A one-image pool.  `ImagePool.items` is the documented {name, path, image} list."""
    pool = ImagePool()
    pool.items.append({
        "name": name,
        "path": path,
        "image": image if image is not None else np.zeros((8, 8, 3), np.uint8),
    })
    pool.index = 0
    return pool


def _source(pipe):
    return next(n for n in pipe.nodes.values() if n.tool_name == "Image Source")


def test_apply_to_does_not_change_source_type():
    """A Synthetic project must still be Synthetic after an image is applied."""
    pipe = _pipeline_with_source()
    node = _source(pipe)
    node.set_param("source_type", "Synthetic")
    before = node.get_param("source_type")

    _pool_with(path="C:/some/absolute/picture.png").apply_to(pipe)

    assert node.get_param("source_type") == before, (
        "applying a strip image rewrote source_type; running a flow must not "
        "reconfigure the project")


def test_apply_to_does_not_change_file_path():
    pipe = _pipeline_with_source()
    node = _source(pipe)
    node.set_param("file_path", "apex_vision/samples/pcb_sample.png")
    before = node.get_param("file_path")

    _pool_with(path="C:/some/absolute/picture.png").apply_to(pipe)

    assert node.get_param("file_path") == before, (
        "applying a strip image rewrote file_path")


def test_apply_to_still_carries_the_image():
    """The override is the mechanism the executor reads, so it must still be set."""
    pipe = _pipeline_with_source()
    node = _source(pipe)
    image = np.full((4, 4, 3), 7, np.uint8)

    pool = _pool_with(image=image, name="board_7.png")
    assert pool.apply_to(pipe) is True

    assert node._override_image is not None
    assert int(np.asarray(node._override_image)[0, 0, 0]) == 7
    assert node._override_name == "board_7.png"


def test_selecting_each_strip_image_leaves_the_project_identical():
    """Both images in a strip, applied in turn: the node's parameters never move."""
    pipe = _pipeline_with_source()
    node = _source(pipe)
    node.set_param("source_type", "Synthetic")
    node.set_param("file_path", "apex_vision/samples/pcb_sample.png")

    snapshot = dict(node.parameters)

    pool = ImagePool()
    pool.items.append({"name": "a.png", "path": "C:/a.png",
                       "image": np.zeros((4, 4, 3), np.uint8)})
    pool.items.append({"name": "b.png", "path": "C:/b.png",
                       "image": np.ones((4, 4, 3), np.uint8)})
    pool.index = 0

    for row in (0, 1, 0):
        assert pool.apply_to(pipe, row) is True

    assert dict(node.parameters) == snapshot, (
        "walking the image strip mutated the Image Source's parameters")


def test_out_of_range_row_is_rejected_without_mutating():
    pipe = _pipeline_with_source()
    node = _source(pipe)
    snapshot = dict(node.parameters)
    pool = _pool_with()

    assert pool.apply_to(pipe, 99) is False
    assert dict(node.parameters) == snapshot


def test_persist_true_does_write_the_source():
    """The counterpart: loading images *is* a configuration change and must stick.

    Without this the fix would over-correct and stop the project remembering an image the
    operator deliberately loaded.
    """
    pipe = _pipeline_with_source()
    node = _source(pipe)
    node.set_param("source_type", "Synthetic")
    node.set_param("file_path", "")

    _pool_with(path="C:/boards/board_12.png").apply_to(pipe, persist=True)

    assert node.get_param("source_type") == "File"
    assert node.get_param("file_path") == "C:/boards/board_12.png"


def test_persist_true_without_a_path_leaves_the_source_alone():
    """An in-memory image (API / clipboard) has no path, so nothing can be persisted."""
    pipe = _pipeline_with_source()
    node = _source(pipe)
    node.set_param("source_type", "Synthetic")
    node.set_param("file_path", "keep/me.png")

    _pool_with(path=None, image=np.zeros((4, 4, 3), np.uint8)).apply_to(
        pipe, persist=True)

    assert node.get_param("file_path") == "keep/me.png"
    assert node._override_image is not None


# ---------------------------------------------------------------------------
# the user-visible consequence
# ---------------------------------------------------------------------------
def test_running_a_flow_does_not_mark_the_project_dirty():
    """A Run with no user edit must leave the dirty flag alone.

    Uses the real backend because the defect showed up in how the strip, the pipeline and
    the project snapshot interact - not in any one of them.
    """
    pytest.importorskip("PyQt6.QtQml")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine

    from apex_vision.qml_backend import AppBackend, FrameProvider
    from apex_vision.qml_services import install_services

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    provider = FrameProvider()
    engine.addImageProvider("frame", provider)
    backend = AppBackend(provider)
    engine.rootContext().setContextProperty("appBackend", backend)
    engine._services = install_services(engine, backend)
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    if not engine.rootObjects():
        pytest.skip("QML interface unavailable in this environment")
    win = engine.rootObjects()[0]
    win.show()

    import time

    def settle(timeout=40.0):
        waited = 0.0
        for _ in range(20):
            app.processEvents()
        while backend.running and waited < timeout:
            app.processEvents()
            time.sleep(0.02)
            waited += 0.02
        for _ in range(15):
            app.processEvents()

    demo = os.path.join(ROOT, "projects", "PCB_Inspection_Demo.apex")
    backend.openRecent(demo)
    for _ in range(50):
        app.processEvents()

    assert backend.dirty is False, "a freshly opened project must be clean"

    backend.run()
    settle()

    assert backend.dirty is False, (
        "running a flow marked the project dirty; closing would then prompt the "
        "operator to save changes they never made")

    # and a real edit must still be detected
    node_id = backend.nodes[0]["id"]
    backend.beginMove()
    backend.moveNode(node_id, 240, 150)
    for _ in range(20):
        app.processEvents()
    assert backend.dirty is True, (
        "a genuine edit must still mark the project dirty")

    win.close()
