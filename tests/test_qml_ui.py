"""The QML UI (qml/) must load cleanly and its Python backend must describe a real solution."""
import os
import sys
import time

import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QML = os.path.join(ROOT, "qml")
DEMO = os.path.join(ROOT, "projects", "PCB_Inspection_Demo.vmp")


@pytest.fixture(scope="module")
def gui():
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    return QGuiApplication.instance() or QGuiApplication(sys.argv)


def _spin(app, n=20):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def _load(app, backend=None):
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    if backend is not None:
        engine.rootContext().setContextProperty("appBackend", backend)
        engine._services = __import__("vm_clone.qml_services", fromlist=["install_services"]).install_services(engine, backend)
    engine.addImportPath(QML)
    engine.load(QUrl.fromLocalFile(os.path.join(QML, "Main.qml")))
    _spin(app)
    return engine, warnings


def test_qmlproject_references_existing_entry_points():
    text = open(os.path.join(QML, "ApexVision.qmlproject"), encoding="utf-8").read()
    assert "import QmlProject" in text and 'mainFile: "Main.qml"' in text
    for rel in ("Main.qml", "ApexTheme/Theme.qml", "ApexComponents/qmldir", "screens/MainScreen.qml"):
        assert os.path.exists(os.path.join(QML, rel)), rel


def test_every_icon_used_exists():
    import re
    used = set()
    for folder, _, files in os.walk(QML):
        for f in files:
            if f.endswith(".qml"):
                src = open(os.path.join(folder, f), encoding="utf-8").read()
                used |= set(re.findall(r'icon: "([a-z_]+)"', src))
                used |= set(re.findall(r'Icon \{[^}]*?name: "([a-z_]+)"', src))
    missing = [n for n in used if n and not os.path.exists(os.path.join(QML, "images", "dark", f"{n}.svg"))]
    assert not missing, missing


def test_design_time_load_has_no_warnings_and_shows_both_screens(gui):
    engine, warnings = _load(gui)
    root = engine.rootObjects()[0]
    for start in (False, True):
        root.setProperty("startPageVisible", start)
        _spin(gui)
        assert root.width() > 0 and root.property("startPageVisible") is start
    assert not warnings, warnings


def test_live_backend_feeds_real_solution_into_qml(gui):
    from vm_clone.qml_backend import AppBackend, FrameProvider
    provider = FrameProvider()
    engine = QQmlApplicationEngine()
    engine.addImageProvider("frame", provider)
    backend = AppBackend(provider)
    engine.rootContext().setContextProperty("appBackend", backend)
    engine._services = __import__("vm_clone.qml_services", fromlist=["install_services"]).install_services(engine, backend)
    warnings = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    engine.addImportPath(QML)
    engine.load(QUrl.fromLocalFile(os.path.join(QML, "Main.qml")))
    backend.openRecent(DEMO)
    end = time.time() + 10
    while (backend.engine.busy or backend.flowMs == 0) and time.time() < end:
        _spin(gui, 2)
    _spin(gui)
    nodes = backend.nodes
    assert len(nodes) == 7 and len({(n["x"], n["y"]) for n in nodes}) == 7
    assert backend.connections and backend.flowMs > 0
    assert not provider.image.isNull()
    assert engine.rootObjects()[0].width() > 0
    assert not warnings, warnings
    backend.cycleRole()
    assert backend.role == "Operator"


def _backend(gui):
    from vm_clone.qml_backend import AppBackend, FrameProvider
    from vm_clone.core.pipeline import SolutionManager
    backend = AppBackend(FrameProvider())
    backend._solution = SolutionManager.load_from_file(DEMO)
    backend._selected = next(iter(backend._pipeline.execution_order))
    backend._freeze_layout()
    backend._project.mark_saved(backend._solution)
    return backend


def test_backend_editing_commands_and_undo(gui):
    b = _backend(gui)
    n = len(b.nodes)
    assert not b.dirty
    b.addTool("Image Binarization")
    assert len(b.nodes) == n + 1 and b.dirty
    new = b.nodes[-1]
    assert any(c["to"] == new["id"] for c in b.connections)          # auto-wired from the image producer
    b.undo()
    assert len(b.nodes) == n and not b.dirty
    b.redo()
    assert len(b.nodes) == n + 1
    b.setGlobal("g_Test", "Integer", "41")
    assert {"name": "g_Test", "type": "int", "value": "41"} in b.globalVariables
    b.setGlobal("g_Bad", "Integer", "x")
    assert not any(v["name"] == "g_Bad" for v in b.globalVariables)
    b.removeGlobal("g_Test")
    b.applyFlowSettings(75, 4000, True, True)
    assert b.flowSettings["runIntervalMs"] == 75 and b.flowSettings["stopOnNg"] is True


def test_backend_module_params_validation_and_operator_lock(gui):
    b = _backend(gui)
    nid = next(n["id"] for n in b.nodes if n["title"].endswith("MountingHole"))
    params = {p["name"]: p["value"] for p in b.moduleParams(nid)}
    assert "min_radius" in params
    b.setParam(nid, "min_radius", "21")
    assert {p["name"]: p["value"] for p in b.moduleParams(nid)}["min_radius"] == "21"
    assert b.moduleInputs(nid)[0]["source"] != "(not connected)"
    assert b.validateFlow()
    b._role = "Operator"
    before = len(b.nodes)
    b.addTool("Histogram")
    b.setParam(nid, "min_radius", "99")
    assert len(b.nodes) == before and {p["name"]: p["value"] for p in b.moduleParams(nid)}["min_radius"] == "21"


def test_backend_image_pool_loop_and_stop(gui, tmp_path):
    import cv2
    import numpy as np
    b = _backend(gui)
    urls = []
    for i in range(3):
        p = tmp_path / f"img{i}.png"
        cv2.imwrite(str(p), np.full((40, 60, 3), 30 * i, np.uint8))
        urls.append(QUrl.fromLocalFile(str(p)).toString())
    b.loadImageFiles(urls[:1])
    end = time.time() + 10
    while b.running and time.time() < end:
        _spin(gui, 2)
    b.loadImageFolder(QUrl.fromLocalFile(str(tmp_path)).toString())
    while b.running and time.time() < end:
        _spin(gui, 2)
    assert [i["name"] for i in b.imagePool] == ["img0.png", "img1.png", "img2.png"]
    seen = []
    b.changed.connect(lambda: seen.append(b.imageIndex))
    b.loop = True
    b.run()
    end = time.time() + 15
    while len(set(seen)) < 3 and time.time() < end:
        _spin(gui, 2)
    assert b.running and {0, 1, 2} <= set(seen)                  # looped over every image
    b.stop()
    while b.running and time.time() < end:
        _spin(gui, 2)
    assert not b.running


def test_every_dialog_and_menu_entry_has_a_handler():
    import re
    main = open(os.path.join(QML, "screens", "MainScreen.qml"), encoding="utf-8").read()
    data = open(os.path.join(QML, "ApexTheme", "SampleData.qml"), encoding="utf-8").read()
    handled = set(re.findall(r'case "(\w+)"', main))
    keys = set(re.findall(r'key: "(\w+)"', data))
    prefixed = {k for k in keys if k.startswith(("example", "inspect"))}
    missing = sorted(keys - handled - prefixed)
    assert not missing, missing
    host = open(os.path.join(QML, "ApexDialogs", "DialogHost.qml"), encoding="utf-8").read()
    for name in ("globalVars", "flowSettings", "validation", "moduleConfig", "cameraSet", "lensCal",
                 "plugins", "newProject", "info"):
        assert f'"{name}"' in host, name


def test_backend_wire_delete_and_roi_editing(gui):
    b = _backend(gui)
    # delete a module: its wires go with it, and undo brings both back
    victim = next(n["id"] for n in b.nodes if n["title"].endswith("SurfaceScratchCheck"))
    n_nodes, n_conns = len(b.nodes), len(b.connections)
    b.deleteNode(victim)
    assert len(b.nodes) == n_nodes - 1 and len(b.connections) < n_conns
    b.undo()
    assert len(b.nodes) == n_nodes and len(b.connections) == n_conns
    # disconnect an input, then reconnect it by dragging from the same output
    link = next(c for c in b.connections if c["to"] == victim)
    b.disconnectInput(victim, link["toPort"])
    assert not any(c["to"] == victim for c in b.connections)
    assert b.connectPorts(link["from"], link["fromPort"], victim, link["toPort"]) is True
    assert any(c["to"] == victim for c in b.connections)
    # illegal wires are refused with a reason and leave the undo history untouched
    undo_depth = len(b._undo)
    assert b.connectPorts(victim, 0, victim, 0) is False
    assert "itself" in b.hint.lower() and len(b._undo) == undo_depth
    # ROI: only modules that have one expose it, and setRoi rewrites the parameter
    b.selectNode(victim)
    assert b.selectedRoi == [260, 240, 180, 120]              # Defect Detection carries an ROI
    b.selectNode(b.nodes[0]["id"])
    assert b.selectedRoi == []                                # the Image Source has none
    align = next(n["id"] for n in b.nodes if n["title"].endswith("IC_Alignment") or n["title"].endswith("IC Alignment"))
    b.selectNode(align)
    assert b.selectedRoi == [] or len(b.selectedRoi) == 4
    tmpl = _backend(gui)
    tmpl.addTool("Template Match")
    tmpl.setRoi(10, 20, 30, 40)
    assert tmpl.selectedRoi == [10, 20, 30, 40]
    tmpl.undo()
    assert tmpl.selectedRoi != [10, 20, 30, 40]


def test_qml_canvas_view_functions_and_wire_drop(gui):
    from PyQt6.QtCore import Q_ARG, QMetaObject, Qt
    from PyQt6.QtQuick import QQuickItem
    from vm_clone.qml_backend import AppBackend, FrameProvider
    provider = FrameProvider()
    engine = QQmlApplicationEngine()
    engine.addImageProvider("frame", provider)
    backend = AppBackend(provider)
    engine.rootContext().setContextProperty("appBackend", backend)
    engine._services = __import__("vm_clone.qml_services", fromlist=["install_services"]).install_services(engine, backend)
    warnings = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    engine.addImportPath(QML)
    engine.load(QUrl.fromLocalFile(os.path.join(QML, "Main.qml")))
    backend.openRecent(DEMO)
    end = time.time() + 10
    while (backend.engine.busy or backend.flowMs == 0) and time.time() < end:
        _spin(gui, 2)
    _spin(gui, 10)
    window = engine.rootObjects()[0]
    main = [c for c in window.findChildren(QQuickItem) if c.metaObject().className().startswith("MainScreen")][0]

    def call(name, *args):
        from PyQt6.QtCore import QVariant
        QMetaObject.invokeMethod(main, name, Qt.ConnectionType.DirectConnection,
                                 *[Q_ARG(QVariant, a) for a in args])

    _spin(gui, 60)                                            # the auto-fit after loading has run
    main.setProperty("zoom", 1.0)
    call("zoomAt", 100.0, 100.0, 2.0)
    assert main.property("zoom") == pytest.approx(2.0)
    call("zoomAt", 100.0, 100.0, 100.0)                       # clamped
    assert main.property("zoom") <= 2.5
    call("fitView")
    assert 0.25 <= main.property("zoom") <= 1.5
    assert not warnings, warnings
    # dropping a dragged wire on an empty spot connects nothing
    before = len(backend.connections)
    call("finishWire", {"x": -500.0, "y": -500.0})
    assert len(backend.connections) == before


def test_dragging_between_ports_with_the_mouse_creates_a_wire(gui):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtQuick import QQuickItem
    from PyQt6.QtTest import QTest
    from vm_clone.qml_backend import AppBackend, FrameProvider
    provider = FrameProvider()
    engine = QQmlApplicationEngine()
    engine.addImageProvider("frame", provider)
    backend = AppBackend(provider)
    engine.rootContext().setContextProperty("appBackend", backend)
    engine._services = __import__("vm_clone.qml_services", fromlist=["install_services"]).install_services(engine, backend)
    engine.addImportPath(QML)
    engine.load(QUrl.fromLocalFile(os.path.join(QML, "Main.qml")))
    backend.openRecent(DEMO)
    end = time.time() + 10
    while (backend.engine.busy or backend.flowMs == 0) and time.time() < end:
        _spin(gui, 2)
    window = engine.rootObjects()[0]
    window.show()
    _spin(gui, 20)
    def walk(item):
        for child in item.childItems():
            yield child
            yield from walk(child)

    cards = [c for c in walk(window.contentItem()) if c.metaObject().className().startswith("NodeCard")]
    by_title = {c.property("title"): c for c in cards}
    src, dst = by_title["01 ImageAcquisition"], by_title["03 MountingHole"]
    dst_id = next(n["id"] for n in backend.nodes if n["title"] == "03 MountingHole")
    link = next(c for c in backend.connections if c["to"] == dst_id)
    layout_before = {n["id"]: (n["x"], n["y"]) for n in backend.nodes}
    backend.disconnectInput(dst_id, link["toPort"])
    _spin(gui, 80)                                                # let QML rebuild and lay out the cards
    assert not any(c["to"] == dst_id for c in backend.connections)
    assert {n["id"]: (n["x"], n["y"]) for n in backend.nodes} == layout_before   # modules stay put
    cards = [c for c in walk(window.contentItem()) if c.metaObject().className().startswith("NodeCard")]
    by_title = {c.property("title"): c for c in cards}
    src, dst = by_title["01 ImageAcquisition"], by_title["03 MountingHole"]

    def win_pos(card, x, y):
        p = card.mapToScene(QPointF(x, y))
        return QPoint(int(p.x()), int(p.y()))

    start = win_pos(src, 180.5, 26 + 4 + 4.5)                     # output #0 (Image)
    drop = win_pos(dst, -0.5, 26 + 4 + 4.5)                       # input #0 (Image)
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    for step in range(1, 9):
        QTest.mouseMove(window, QPoint(start.x() + (drop.x() - start.x()) * step // 8,
                                       start.y() + (drop.y() - start.y()) * step // 8))
        _spin(gui, 1)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=drop)
    _spin(gui, 10)
    assert any(c["to"] == dst_id and c["from"] == link["from"] for c in backend.connections), backend.hint

    # right-click an input port clears it again (the cards were rebuilt by the new wire)
    _spin(gui, 60)
    dst = {c.property("title"): c for c in walk(window.contentItem())
           if c.metaObject().className().startswith("NodeCard")}["03 MountingHole"]
    port = win_pos(dst, -0.5, 26 + 4 + 4.5)
    QTest.mouseClick(window, Qt.MouseButton.RightButton, pos=port)
    _spin(gui, 10)
    assert not any(c["to"] == dst_id for c in backend.connections)


def test_unsaved_changes_are_never_replaced_without_asking(gui, tmp_path):
    b = _backend(gui)
    b._project.path = str(tmp_path / "work.vmp")
    asked = []
    b.confirmRequested.connect(asked.append)
    other = os.path.join(ROOT, "projects", "Precision_Measurement_Demo.vmp")
    b.addTool("Image Binarization")
    assert b.dirty
    name = b.solutionName
    b.openRecent(other)                                   # guarded: nothing loaded yet
    assert asked and b.solutionName == name
    b.confirmCancel()
    assert b.solutionName == name and b.dirty
    b.openRecent(other)
    b.confirmDiscard()                                    # discard: the other solution loads
    assert b.solutionName != name
    # Save: writes the file, then continues
    b2 = _backend(gui)
    b2._project.path = str(tmp_path / "keep.vmp")
    b2.addTool("Histogram")
    n = len(b2.nodes)
    b2.openRecent(other)
    b2.confirmSave()
    assert os.path.exists(tmp_path / "keep.vmp") and b2.solutionName != "PCB_AOI_Solution"
    assert len(SolutionManager_load(tmp_path / "keep.vmp").get_active_flow().nodes) == n
    # no file yet: Save cannot silently pick a path
    b3 = _backend(gui)
    b3.addTool("Histogram")
    b3.newFromTemplate(1)
    b3.confirmSave()
    assert "Save Solution As" in b3.hint and b3.dirty


def SolutionManager_load(path):
    from vm_clone.core.pipeline import SolutionManager
    return SolutionManager.load_from_file(str(path))


def test_backend_layers_and_formatted_output(gui):
    b = _backend(gui)
    b.engine.request_run()
    end = time.time() + 10
    while (b.engine.busy or b.flowMs == 0) and time.time() < end:
        _spin(gui, 2)
    assert "SendToPLC" in b.formattedOutput or "01_" in b.formattedOutput
    b.selectNode(next(n["id"] for n in b.nodes if n["title"].endswith("SurfaceScratchCheck")))
    with_overlays = b._provider.image.copy()
    b.setLayer("overlays", False)
    assert b.layers["overlays"] is False and b.layers["rois"] is False
    assert b._provider.image != with_overlays                     # the boxes disappeared
    b.setLayer("overlays", True)
    b.setLayer("histogram", True)
    assert b.layers["histogram"] is True
    b.setLayer("nonsense", True)                                   # ignored
    assert "nonsense" not in b.layers


def test_loading_a_solution_seeds_the_image_strip_without_changing_the_source(gui):
    from vm_clone.qml_backend import AppBackend, FrameProvider
    from vm_clone.core.pipeline import SolutionManager
    b = AppBackend(FrameProvider())
    sol = SolutionManager.load_from_file(DEMO)
    source_before = dict(next(n for n in sol.get_active_flow().nodes.values() if n.tool_name == "Image Source").parameters)
    b.load_solution(sol, DEMO)
    assert [i["name"] for i in b.imagePool] == ["pcb_sample.png", "pcb_sample_defect.png"] and b.imageIndex == 0
    assert all(i["url"].startswith("file:") for i in b.imagePool)
    source = next(n for n in sol.get_active_flow().nodes.values() if n.tool_name == "Image Source")
    assert source.parameters == source_before
    b.engine.wait_for_run()
    b.openRecent(DEMO)                       # reloading never duplicates the samples
    b.engine.wait_for_run()
    assert len(b.imagePool) == 2
