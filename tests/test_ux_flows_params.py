"""Flow tabs show every flow of the solution; options that do not apply to the current choice are blank and locked."""
from test_qml_interaction import fresh, ui  # noqa: F401  (fixtures)
from apex_vision.core import param_schema
from apex_vision.core.registry import create_tool_instance
from PyQt6.QtCore import Qt  # noqa: F401


def tab_names(ui):
    return [t["name"] for t in ui.be.flowTabs]


def test_every_flow_has_a_tab_and_the_tab_switches_and_closes_it(ui):
    be = ui.be
    first = be.flowName
    be.addFlow()
    assert len(be.flowTabs) == 2 and be.flowTabs[1]["active"] and not be.flowTabs[0]["active"]
    ui.spin(20)
    names = {t.property("objectName") for t in ui.walk()}
    assert {f"flowTab_{n}" for n in tab_names(ui)} <= names, "a tab is drawn for each flow"
    be.selectFlow(first)
    assert be.flowName == first and be.flowTabs[0]["active"]
    be.closeFlow(first)
    assert tab_names(ui) == [be.flowName] and len(be.flowTabs) == 1
    be.closeFlow(be.flowName)                                    # the last flow stays
    assert len(be.flowTabs) == 1
    be.undo()
    ui.spin(10)


def test_a_flow_tab_remembers_its_last_verdict(ui):
    be = ui.be
    be.run()
    ui.spin(60)
    active = next(t for t in be.flowTabs if t["active"])
    assert active["verdict"] in ("PASS", "FAIL")


def test_only_the_options_of_the_chosen_source_are_editable(ui):
    be = ui.be
    nid = next(i for i, n in be._pipeline.nodes.items() if n.tool_name == "Image Source")

    def rows():
        return {r["name"]: r for r in be.moduleParams(nid)}

    assert be.setParamValue(nid, "source_type", "Camera")
    r = rows()
    assert not r["file_path"]["active"] and r["file_path"]["why"] == "Not used with Camera"
    assert not r["pattern_type"]["active"] and not r["stream_url"]["active"] and not r["mvs_config_file"]["active"]
    assert r["camera_device"]["active"] and r["camera_index"]["active"] and r["auto_exposure"]["active"]
    assert not r["exposure_time_us"]["active"], "with Auto exposure the camera sets exposure and gain itself"
    assert r["camera_device"]["native"].startswith("webcam_"), "the simulated Hikrobot camera is not left selected"
    assert all(c.startswith("webcam_") for c in r["camera_device"]["choices"])

    assert be.setParamValue(nid, "source_type", "File")
    r = rows()
    assert r["file_path"]["active"] and not r["camera_device"]["active"] and not r["exposure_time_us"]["active"] and not r["trigger_mode"]["active"]

    assert be.setParamValue(nid, "source_type", "Industrial GigE")
    r = rows()
    assert r["camera_device"]["native"] == "virtual_gige_0" and not r["camera_index"]["active"]
    assert "mvs_gige_0" not in r["camera_device"]["choices"]

    assert be.setParamValue(nid, "source_type", "IP Stream")
    r = rows()
    assert r["stream_url"]["active"] and not r["camera_device"]["active"] and not r["gain"]["active"]


def test_camera_runs_use_the_device_of_their_own_kind():
    tool = create_tool_instance("Image Source", "s1", "01_Acquisition")
    tool.set_param("source_type", "Industrial USB3")
    assert tool.parameters["camera_device"] == "virtual_usb3_0"
    res = tool.execute({})
    assert res.status.value == "OK" and "USB3" in res.message


def test_the_rules_only_name_real_parameters_and_real_choices():
    from apex_vision.core import registry
    for tool, rules in param_schema.WHEN.items():
        params = create_tool_instance(tool, "x", "c").parameters
        for key, (ctrl, values) in rules.items():
            assert key in params, f"{tool}: no parameter {key}"
            assert ctrl in params, f"{tool}: no controlling parameter {ctrl}"
            choices = param_schema.choices_for(tool, ctrl)
            if choices is not None:
                assert set(values) <= set(choices), f"{tool}.{key}: {values} not all in {choices}"
    assert registry


def test_toolbox_order_names_only_real_tools_and_every_category_has_an_icon():
    import apex_vision.tools  # noqa: F401
    from apex_vision.core import registry
    names = registry.list_all_tools()
    for cat, order in registry.TOOL_ORDER.items():
        assert len(order) == len(set(order)), f"{cat}: a tool is listed twice"
        assert all(n in names for n in order), f"{cat}: {[n for n in order if n not in names]} are not tools"
        assert set(order) <= set(registry._CATEGORIES.get(cat, [])), f"{cat}: lists a tool of another category"
    cats = registry.list_categories()
    assert list(cats)[:3] == ["Acquisition", "Image Processing", "Color Processing"]
    assert all(set(cats[c]) == set(registry._CATEGORIES[c]) for c in cats), "ordering must not add or drop tools"


def test_each_category_rail_icon_is_its_own(ui):
    from apex_vision.core.registry import CATEGORY_ORDER
    icons = [c["icon"] for c in ui.be.toolCategories if c["name"] in CATEGORY_ORDER]       # a plugin's own category gets the generic list icon
    assert len(icons) == len(CATEGORY_ORDER)
    assert len(icons) == len(set(icons)) and "list" not in icons, icons


def test_nothing_brings_a_sample_picture_unless_a_template_is_chosen(ui):
    be = ui.be
    be.startup()
    assert len(be._pool) == 0
    for flow in be._solution.flows.values():
        src = next(n for n in flow.nodes.values() if n.tool_name == "Image Source")
        assert src.get_param("source_type") == "File" and src.get_param("file_path") == ""
    be.addFlow()
    src = next(n for n in be._pipeline.nodes.values() if n.tool_name == "Image Source")
    assert src.get_param("source_type") == "File" and src.get_param("file_path") == "" and len(be._pool) == 0


def test_the_wheel_over_a_dialog_does_not_zoom_the_canvas_or_image(ui):
    from PyQt6.QtCore import QPointF, QPoint
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtCore import Qt as _Qt
    ui.main.invoke("globalVars")
    ui.spin(30)
    assert ui.dialog != ""
    zoom, view = ui.main.property("zoom"), ui.main.findChild(type(ui.main), "viewportRect") if False else None
    for pos in (ui.w.width() // 2, 120):                      # over the dialog, and over the dimmed canvas beside it
        p = QPointF(pos, ui.w.height() / 2)
        ev = QWheelEvent(p, ui.w.mapToGlobal(p), QPoint(0, 0), QPoint(0, 120), _Qt.MouseButton.NoButton, _Qt.KeyboardModifier.NoModifier,
                         _Qt.ScrollPhase.NoScrollPhase, False)
        ui.app.sendEvent(ui.w, ev)
        ui.spin(10)
    assert ui.main.property("zoom") == zoom
    ui.close_dialog()


def test_loop_with_a_camera_source_keeps_capturing_until_stop(ui):
    from apex_vision.core.registry import create_tool_instance
    be = ui.be
    be.startup()
    src = next(n for n in be._pipeline.nodes.values() if n.tool_name == "Image Source")
    src.set_param("source_type", "Industrial GigE")           # a live (simulated) camera: every run grabs a new frame
    be.loop = True
    before = be._pipeline.execution_count
    be.run()
    end = __import__("time").time() + 8
    while __import__("time").time() < end and be._pipeline.execution_count < before + 4:
        ui.spin(10)
    assert be._pipeline.execution_count >= before + 4, "Loop must keep grabbing frames without pressing Run again"
    assert be.running
    be.stop()
    ui.spin(40)
    n = be._pipeline.execution_count
    ui.spin(60)
    assert be._pipeline.execution_count == n and not be.running
    be.loop = False


def test_modules_with_a_drawn_region_work_only_inside_it_and_keep_the_rest():
    import numpy as np
    from apex_vision.core import roi_support
    img = np.full((100, 200, 3), 80, np.uint8)
    img[:, 100:] = 200
    t = create_tool_instance("Image Binarization", "b", "c")
    t.set_param("method", "Manual")
    t.set_param("threshold", 128)
    whole = t.execute({"Image": img}).outputs["Image"]
    assert whole[:, :100].max() == 0 and whole[:, 100:].min() == 255
    t.set_param("roi", [100, 0, 100, 100])
    part = t.execute({"Image": img}).outputs["Image"]
    assert part.shape == img.shape and (part[:, :100] == 80).all() and (part[:, 100:] == 255).all(), "outside the region is untouched"
    t.set_param("roi", [0, 0, 0, 0])
    assert (t.execute({"Image": img}).outputs["Image"] == whole).all(), "all zero means the whole image"
    assert roi_support.region([150, 50, 500, 500], img.shape) == (150, 50, 50, 50), "a region past the edge is trimmed"
    assert roi_support.region([500, 0, 10, 10], img.shape)[2] == 0


def test_the_region_of_a_color_extraction_moves_its_mask_and_every_listed_module_has_one():
    import numpy as np
    for name in ("Image Filter", "Image Binarization", "Image Morphology", "Image Enhancement", "Brightness Contrast", "Edge Detection",
                 "Image Normalization", "Image Correction", "Shade Correction", "Color Convert", "Color Extraction",
                 "BCR Recognition", "2D BCR Recognition", "Object Detection"):
        assert create_tool_instance(name, "x", "c").parameters["roi"] == [0, 0, 0, 0], name
    img = np.zeros((60, 120, 3), np.uint8)
    img[:, 60:] = (0, 255, 0)
    t = create_tool_instance("Color Extraction", "c", "c")
    t.set_param("roi", [60, 0, 60, 60])
    out = t.execute({"Image": img}).outputs
    assert out["Mask"].shape == (60, 120) and out["Mask"][:, :60].sum() == 0 and out["Mask"][:, 60:].sum() > 0


def test_a_region_is_drawn_for_a_module_that_just_got_one(ui):
    be = ui.be
    nid = be.addNode("Image Filter") if hasattr(be, "addNode") else None
    if nid is None:
        return
    be.selectNode(nid)
    assert be.selectedRoi == [0, 0, 0, 0]
    be.setRoi(10, 20, 100, 50)
    assert be._pipeline.nodes[nid].parameters["roi"] == [10, 20, 100, 50]


def test_an_update_keeps_the_cards_and_wires_alive_so_nothing_flickers_and_a_drag_survives(ui):
    """Every backend update used to rebuild all the cards: they flickered and a drag in progress was destroyed."""
    from PyQt6.QtCore import QPoint
    ui.be.addTool("Image Filter")
    ui.settle()
    def shapes():
        return [c for c in ui.walk() if "Shape" in c.metaObject().className() and c.property("a") is not None]
    cards = ui.of_type("NodeCard")
    wires = shapes()
    assert cards and wires
    for c in cards + wires:
        c.setProperty("seen", True)                       # a rebuilt item would not carry the mark
    for _ in range(3):
        ui.be.changed.emit()
        ui.spin(30)
    assert all(c.property("seen") for c in ui.of_type("NodeCard")), "a plain update must not recreate the cards"
    assert all(c.property("seen") for c in shapes()), "nor the wires"
    # drag a card; updates arriving during the drag do not interrupt it, and the new place is kept
    card = min(cards, key=lambda c: c.y())
    p0 = ui.point_in(card, 60, 10)
    x0 = float(card.x())
    from PyQt6.QtTest import QTest
    QTest.mousePress(ui.w, Qt.MouseButton.LeftButton, pos=p0)
    for s in range(1, 9):
        QTest.mouseMove(ui.w, QPoint(p0.x() + 12 * s, p0.y()))
        ui.be.changed.emit()
        ui.spin(3)
    QTest.mouseRelease(ui.w, Qt.MouseButton.LeftButton, pos=QPoint(p0.x() + 96, p0.y()))
    ui.spin(30)
    assert card.property("seen") and card.x() > x0 + 20
    moved = card.x()
    ui.be.changed.emit()
    ui.spin(30)
    assert card.x() == moved, "an update after the drag must keep the module where it was put"
    # and dragging again still works
    p1 = ui.point_in(card, 60, 10)
    ui.drag(p1, p1 + QPoint(60, 0))
    assert card.x() > moved + 10


def test_many_flow_tabs_scroll_and_the_flow_buttons_stay_put(ui):
    from PyQt6.QtCore import QPointF
    def named(name):
        return next(c for c in ui.walk() if c.property("objectName") == name)

    tabs = named("flowTabs")
    controls = [c for c in ui.walk() if c.property("tooltip") in ("Run this flow", "Stop this flow", "Add a sub-flow", "Validate flow")
                and c.isVisible() and c.height() == 28]
    assert controls
    before = [c.mapToScene(QPointF(0, 0)).x() for c in controls]
    width = tabs.width()
    for _ in range(9):
        ui.be.addFlow()
        ui.spin(25)
    after = [c.mapToScene(QPointF(0, 0)).x() for c in controls]
    assert after == before, "adding tabs must not move the flow buttons"
    assert tabs.width() == width, "the tab strip keeps its size; it scrolls instead of growing"
    assert tabs.property("contentWidth") > tabs.width() and tabs.property("interactive")
    ui.spin(40)
    assert tabs.property("contentX") > 0, "the new (active) tab is scrolled into view"
    active = next(t for t in ui.be.flowTabs if t["active"])["name"]
    tab = named(f"flowTab_{active}")
    from PyQt6.QtCore import QPointF
    x = tab.mapToItem(tabs, QPointF(0, 0)).x()
    assert 0 <= x and x + tab.width() <= tabs.width() + 1
    # the first tab can be reached again
    ui.be.selectFlow(ui.be.flowTabs[0]["name"])
    ui.spin(40)
    assert tabs.property("contentX") == 0


def test_a_list_wired_into_an_image_input_does_not_crash_the_app_and_flow_names_are_white(ui):
    """A blob list wired into Image Enhancement used to raise inside the cycle callback, which aborts the app."""
    ui.be.addTool("BLOB Analysis")
    ui.be.addTool("Image Enhancement")
    ui.settle()
    nodes = {n.tool_name: n for n in ui.be._pipeline.nodes.values()}
    blob, enh = nodes["BLOB Analysis"], nodes["Image Enhancement"]
    for i, port in enumerate(blob.outputs):
        if port in ("Blobs", "Areas", "Centers"):
            assert ui.be.connectPorts(blob.instance_id, i, enh.instance_id, 0)
            ui.settle()
            ui.be.selectNode(enh.instance_id)
            ui.spin(20)
    assert ui.be.verdict in ("PASS", "FAIL")
    from apex_vision.core.overlays import render_overlays
    assert render_overlays([{"a": 1}], []) is None and render_overlays(5, []) is None
    tab = next(t for t in ui.walk() if str(t.property("objectName")).startswith("flowTab_"))
    texts = [c for c in ui.walk(tab) if c.metaObject().className().startswith("QQuickText")]
    assert texts and all(t.property("color").name() == "#ffffff" for t in texts)


def test_auto_exposure_leaves_exposure_and_gain_to_the_webcam(ui, monkeypatch):
    from apex_vision.core import camera_manager as cmgr

    class Fake(cmgr.CameraDriverBase):
        def __init__(self):
            super().__init__(cmgr.CameraDeviceInfo("webcam_0", "Fake", "USB"))
            self.log = []
        def set_auto_exposure(self, on): self.log.append(("auto", on)); return True
        def set_exposure(self, v): self.log.append(("exp", v)); return True
        def set_gain(self, v): self.log.append(("gain", v)); return True
        def capture_frame(self, timeout_ms=0): import numpy as np; return True, np.zeros((4, 4, 3), np.uint8), "OK"

    drv = Fake()
    tool = create_tool_instance("Image Source", "s1", "01_Acquisition")
    tool.set_param("source_type", "Camera")
    assert tool.parameters["auto_exposure"] is True
    cm = cmgr.CameraManager.get_instance()
    monkeypatch.setattr(type(cm), "get_or_create_driver", lambda self, *a, **k: drv)
    if True:
        assert tool.execute({}).status.value == "OK"
        assert ("auto", True) in drv.log and not any(k in ("exp", "gain") for k, _ in drv.log), "automatic: nothing is written to the camera"
        drv.log.clear()
        tool.set_param("auto_exposure", False)
        tool.set_param("exposure_time_us", 66000.0)
        tool.execute({})
        assert ("auto", False) in drv.log and ("exp", 66000.0) in drv.log and ("gain", 1.0) in drv.log
    # the editor blanks exposure and gain while the camera is in charge, and only for a webcam
    nid = next(i for i, n in ui.be._pipeline.nodes.items() if n.tool_name == "Image Source")
    ui.be.setParamValue(nid, "source_type", "Camera")
    rows = {r["name"]: r for r in ui.be.moduleParams(nid)}
    assert rows["auto_exposure"]["active"] and not rows["exposure_time_us"]["active"] and not rows["gain"]["active"]
    ui.be.setParamValue(nid, "auto_exposure", False)
    rows = {r["name"]: r for r in ui.be.moduleParams(nid)}
    assert rows["exposure_time_us"]["active"] and rows["gain"]["active"]
    ui.be.setParamValue(nid, "source_type", "Industrial GigE")
    rows = {r["name"]: r for r in ui.be.moduleParams(nid)}
    assert not rows["auto_exposure"]["active"] and rows["exposure_time_us"]["active"]


def test_the_webcam_driver_switches_auto_exposure_on_once_and_skips_the_dark_first_frames():
    from apex_vision.core import camera_manager as cmgr
    calls = []

    class Cap:
        def isOpened(self): return True
        def set(self, prop, v): calls.append(("set", prop, v))
        def read(self):
            import numpy as np
            calls.append(("read",)); return True, np.zeros((2, 2, 3), np.uint8)

    d = cmgr.OpenCVCameraDriver(cmgr.CameraDeviceInfo("webcam_0", "w", "USB"), 0)
    d._cap, d.is_connected = Cap(), True
    d.set_auto_exposure(True)
    d.capture_frame()
    assert ("set", cmgr.cv2.CAP_PROP_AUTO_EXPOSURE, 0.75) in calls and calls.count(("read",)) == 9
    calls.clear()
    d.capture_frame()
    assert calls == [("read",)], "the camera is told once, not on every capture"
    d.set_auto_exposure(False)
    d.capture_frame()
    assert ("set", cmgr.cv2.CAP_PROP_AUTO_EXPOSURE, 0.25) in calls


def _two_runnable_flows(ui):
    be = ui.be
    first = be.flowName
    be.addFlow()
    second = be.flowName
    src = next(n for n in be._pipeline.nodes.values() if n.tool_name == "Image Source")
    src.set_param("source_type", "Synthetic")
    src.set_param("pattern_type", "Circles & Holes")
    ui.settle()
    be.selectFlow(first)
    ui.settle()
    return first, second


def _wait(ui, cond, secs=15):
    import time
    end = time.time() + secs
    while not cond() and time.time() < end:
        ui.spin(10)
    return cond()


def test_the_top_buttons_run_loop_and_stop_every_flow(ui):
    be = ui.be
    first, second = _two_runnable_flows(ui)
    flows = be._solution.flows
    be._flow_stats.clear()
    be.runAll()
    assert _wait(ui, lambda: not be.allRunning and not be._all_active), "one pass over every flow ends by itself"
    assert first in be._flow_stats and second in be._flow_stats, "each flow ran and got its own verdict"
    # Loop: both flows keep running pass after pass until Stop
    n1, n2 = flows[first].execution_count, flows[second].execution_count
    be.allLoop = True
    be.runAll()
    assert _wait(ui, lambda: flows[first].execution_count >= n1 + 3 and flows[second].execution_count >= n2 + 3)
    assert be.allRunning and all(t["running"] for t in be.flowTabs), "every tab shows that it is running"
    be.stopAll()
    assert _wait(ui, lambda: not be._all_active)
    at = (flows[first].execution_count, flows[second].execution_count)
    ui.spin(300)
    assert (flows[first].execution_count, flows[second].execution_count) == at, "nothing runs after Stop"
    assert not be.allRunning and not any(t["running"] for t in be.flowTabs)


def test_the_flow_row_and_image_buttons_act_on_the_open_flow_only_and_stay_in_step(ui):
    be = ui.be
    first, second = _two_runnable_flows(ui)

    def named(name):
        return next(c for c in ui.walk() if c.property("objectName") == name and c.isVisible())

    # Loop of the open flow is its own setting and is separate from the top Loop
    ui.click(ui.center(named("loopThisFlow")))
    assert be.loop is True and be.allLoop is False
    be.selectFlow(second)
    ui.spin(20)
    assert be.loop is False, "another flow has its own Loop"
    be.selectFlow(first)
    ui.spin(20)
    assert be.loop is True
    ui.click(ui.center(named("loopThisFlow")))
    assert be.loop is False
    ui.click(ui.center(named("loopAllFlows")))
    assert be.allLoop is True and be.loop is False
    ui.click(ui.center(named("loopAllFlows")))
    assert be.allLoop is False
    # the Run button in the flow row runs/stops only the open flow, like the one under the image
    f1, f2 = be._solution.flows[first], be._solution.flows[second]
    before2 = f2.execution_count
    be.loop = True
    ui.click(ui.center(named("runThisFlow")))
    assert _wait(ui, lambda: be.running)
    assert not be.allRunning, "this is the open flow's own run, not the all-flows run"
    ui.click(ui.center(named("runThisFlow")))                       # now it is a Stop button
    assert _wait(ui, lambda: not be.running)
    assert f2.execution_count == before2, "the other flow was not touched"


def test_stopping_one_flow_during_run_all_leaves_the_others_running(ui):
    be = ui.be
    first, second = _two_runnable_flows(ui)
    flows = be._solution.flows
    be.allLoop = True
    be.runAll()
    assert _wait(ui, lambda: flows[first].execution_count >= 2 and flows[second].execution_count >= 2)
    be.stop()                                                        # the open flow (first) only
    assert first not in be._all_flows and second in be._all_flows and be.allRunning
    ui.spin(150)
    a1, a2 = flows[first].execution_count, flows[second].execution_count
    assert _wait(ui, lambda: flows[second].execution_count >= a2 + 3)
    assert flows[first].execution_count == a1, "the stopped flow stays stopped"
    be.run()                                                         # and it can join again
    assert first in be._all_flows
    be.stopAll()
    assert _wait(ui, lambda: not be._all_active)
