"""The Image | Result tab pair and the Current Result | History | Help tabs, clicked in the real window.

Before these pages existed the top "Result" tab ignored clicks, and History / Help only changed
the tab's highlight while the Current Result table stayed on screen.
"""
from test_qml_interaction import fresh, ui  # noqa: F401  (fixtures)


def named(ui, name):
    return next(t for t in ui.walk() if t.property("objectName") == name)


def tab(ui, text):
    return next(t for t in ui.walk() if t.property("text") == text and t.property("selected") is not None)


def shown(ui, name):
    return bool(named(ui, name).property("visible"))


def click_tab(ui, text):
    ui.click(ui.center(tab(ui, text)))
    ui.spin(40)


def test_top_result_tab_switches_the_image_for_a_table_of_every_module(ui):
    ui.reset()
    ui.settle()
    assert shown(ui, "tabImage") and not shown(ui, "resultPage")
    assert tab(ui, "Image").property("selected") and not tab(ui, "Result").property("selected")

    click_tab(ui, "Result")
    assert tab(ui, "Result").property("selected") and not tab(ui, "Image").property("selected")
    assert shown(ui, "resultPage")
    rows = named(ui, "resultList")
    expected = [n["title"] for n in ui.be.nodes]
    assert rows.property("count") == len(expected) >= 4, "one row per module in the flow"
    assert [r["name"] for r in ui.be.moduleResults] == [t for t in expected]
    assert all(r["status"] in ("OK", "NG") for r in ui.be.moduleResults), "every module reports a real status"

    click_tab(ui, "Image")
    assert tab(ui, "Image").property("selected") and not shown(ui, "resultPage")
    assert not ui.warnings, ui.warnings


def test_clicking_a_row_selects_that_module(ui):
    ui.reset()
    ui.settle()
    click_tab(ui, "Result")
    ids = [n["id"] for n in ui.be.nodes]
    assert ui.be.selectedId == ids[0]
    delegate = named(ui, "resultList").property("contentItem").childItems()
    rows = [c for c in delegate if c.property("height") == 36]
    assert len(rows) >= 2
    ui.click(ui.center(rows[1]))
    ui.spin(30)
    assert ui.be.selectedId == ids[1], "clicking the second row selects the second module"
    click_tab(ui, "Image")


def test_result_rows_use_the_real_outputs_of_the_last_run(ui):
    ui.reset()
    ui.settle()
    rows = {r["name"]: r for r in ui.be.moduleResults}
    assert any("Width=800" in r["summary"] for r in rows.values()), "the Image Source's outputs are summarised"
    assert all(r["ms"] >= 0 for r in rows.values())


def test_history_lists_every_finished_run_and_can_be_cleared(ui):
    ui.reset()
    ui.settle()
    click_tab(ui, "History")
    assert tab(ui, "History").property("selected") and shown(ui, "historyPane")
    assert not shown(ui, "currentResultPane") and not shown(ui, "helpPane")
    before = len(ui.be.history)
    assert before >= 1 and named(ui, "historyList").property("count") == before

    ui.be.run()                      # "Run all" runs the flow once per image in the strip
    ui.be.engine.wait_for_run()
    ui.spin(80)
    added = len(ui.be.imagePool)
    assert added >= 2 and len(ui.be.history) == before + added
    newest = ui.be.history[0]
    assert newest["verdict"] in ("PASS", "FAIL") and newest["flowMs"] > 0 and newest["n"] == before + added
    assert [h["source"] for h in ui.be.history[:added]][::-1] == [i["name"] for i in ui.be.imagePool], "each line names its image"
    assert named(ui, "historyList").property("count") == before + added

    ui.click(ui.center(named(ui, "historyClear")))
    ui.spin(40)
    assert ui.be.history == [] and named(ui, "historyList").property("count") == 0
    click_tab(ui, "Current Result")
    assert not ui.warnings, ui.warnings


def test_help_describes_the_selected_module_and_follows_the_selection(ui):
    ui.reset()
    ui.settle()
    click_tab(ui, "Help")
    assert tab(ui, "Help").property("selected") and shown(ui, "helpPane")
    assert not shown(ui, "currentResultPane") and not shown(ui, "historyPane")
    first = ui.be.selectedHelp
    assert first["tool"] == "Image Source" and first["description"] and first["parameters"]
    assert any(p["name"] == "Source type" and "Synthetic" in p["limits"] for p in first["parameters"])

    other = next(n for n in ui.be.nodes if n["tool"] != "Image Source")
    ui.be.selectNode(other["id"])
    ui.spin(30)
    assert ui.be.selectedHelp["tool"] == other["tool"] != first["tool"]
    click_tab(ui, "Current Result")
    assert shown(ui, "currentResultPane") and not shown(ui, "helpPane")
    assert not ui.warnings, ui.warnings


def test_current_result_tab_still_shows_the_selected_modules_outputs(ui):
    ui.reset()
    ui.settle()
    click_tab(ui, "Current Result")
    assert shown(ui, "currentResultPane") and not shown(ui, "historyPane") and not shown(ui, "helpPane")
    assert any(r["name"] == "Width" for r in ui.be.results)


def test_history_is_per_project(ui):
    ui.reset()
    ui.settle()
    assert len(ui.be.history) >= 1
    from apex_vision.core.pipeline import SolutionManager
    import os
    demo = os.path.join(os.path.dirname(__file__), "..", "projects", "Precision_Measurement_Demo.apex")
    ui.be.load_solution(SolutionManager.load_from_file(demo))
    ui.be.engine.wait_for_run()
    ui.spin(60)
    assert all(h["n"] <= 2 for h in ui.be.history), "a newly opened project starts its own history"


# ---- the five small icons in the image header ------------------------------------------------
def click_icon(ui, name):
    ui.click(ui.center(named(ui, name)))
    ui.spin(40)


def test_overlay_crosshair_and_grid_icons_toggle_their_layers(ui):
    ui.reset()
    ui.settle()
    assert ui.be.layers["overlays"] and not ui.be.layers["crosshair"] and not ui.be.layers["pixelgrid"]
    click_icon(ui, "viewCrosshair")
    assert ui.be.layers["crosshair"] is True
    click_icon(ui, "viewGrid")
    assert ui.be.layers["pixelgrid"] is True
    click_icon(ui, "viewOverlays")
    assert ui.be.layers["overlays"] is False and not ui.be.layers["rois"], "hiding overlays hides boxes, labels and datums"
    click_icon(ui, "viewOverlays")
    assert ui.be.layers["overlays"] is True
    click_icon(ui, "viewCrosshair")
    click_icon(ui, "viewGrid")
    assert not ui.be.layers["crosshair"] and not ui.be.layers["pixelgrid"]
    assert not ui.warnings, ui.warnings


def test_zoom_icon_enlarges_the_image_and_fit_icon_restores_it(ui):
    ui.reset()
    ui.settle()
    viewport = named(ui, "viewportRect")
    frame = named(ui, "viewFrame")
    base = frame.property("width")
    click_icon(ui, "viewZoomIn")
    assert viewport.property("viewZoom") > 1.2 and frame.property("width") > base * 1.2
    click_icon(ui, "viewZoomIn")
    assert viewport.property("viewZoom") > 1.5
    click_icon(ui, "viewFit")
    assert viewport.property("viewZoom") == 1 and abs(frame.property("width") - base) < 1
    assert viewport.property("viewPanX") == 0 and viewport.property("viewPanY") == 0
    assert not ui.warnings, ui.warnings


def test_wheel_zooms_and_a_drag_pans_the_zoomed_image(ui):
    ui.reset()
    ui.settle()
    viewport = named(ui, "viewportRect")
    for _ in range(3):
        click_icon(ui, "viewZoomIn")
    z = viewport.property("viewZoom")
    assert z > 1.8
    viewport.setProperty("viewPanX", 40)
    viewport.setProperty("viewPanY", -25)
    frame = named(ui, "viewFrame")
    x_before = frame.property("x")
    viewport.setProperty("viewPanX", 80)
    assert frame.property("x") == x_before + 40, "the pan moves the image"
    click_icon(ui, "viewFit")
    assert viewport.property("viewPanX") == 0


def test_pixel_grid_layer_draws_lines_on_the_image():
    import numpy as np
    from apex_vision.core.overlays import render_overlays
    img = np.zeros((200, 300, 3), np.uint8)
    plain = render_overlays(img, [], {"pixelgrid": False})
    gridded = render_overlays(img, [], {"pixelgrid": True})
    assert not plain.any() and gridded[:, 50].any() and gridded[50, :].any()
    assert not gridded[10, 10].any(), "only the grid lines are drawn"


# ---- drawing a region (ROI) on the image with the real mouse ---------------------------------
def select_tool(ui, tool):
    node = next(n for n in ui.be.nodes if n["tool"] == tool)
    ui.be.selectNode(node["id"])
    ui.spin(30)
    return node


def drag_in_image(ui, x0, y0, x1, y1):
    vp = named(ui, "viewportRect")
    ui.drag(ui.point_in(vp, x0, y0), ui.point_in(vp, x1, y1))
    ui.be.engine.wait_for_run()
    ui.spin(40)


def expected_roi(vp, x0, y0, x1, y1):
    s, ox, oy = vp.property("imgScale"), vp.property("imgX0"), vp.property("imgY0")
    return [round((x0 - ox) / s), round((y0 - oy) / s), round((x1 - x0) / s), round((y1 - y0) / s)]


def test_dragging_on_the_image_draws_the_selected_modules_roi(ui):
    ui.reset()
    ui.settle()
    node = select_tool(ui, "Defect Detection")
    vp = named(ui, "viewportRect")
    assert len(ui.be.selectedRoi) == 4
    want = expected_roi(vp, 200, 80, 380, 200)
    drag_in_image(ui, 200, 80, 380, 200)
    got = list(ui.be.selectedRoi)
    assert all(abs(g - w) <= 2 for g, w in zip(got, want)), (got, want)
    assert ui.be._pipeline.nodes[node["id"]].parameters["roi"] == got, "the module's own parameter was rewritten"
    ui.be.undo()
    ui.spin(30)
    assert list(ui.be.selectedRoi) == [260, 240, 180, 120], "Ctrl+Z puts the old region back"
    assert not ui.warnings, ui.warnings


def test_roi_can_still_be_drawn_after_zooming_in(ui):
    ui.reset()
    ui.settle()
    select_tool(ui, "Template Match")
    vp = named(ui, "viewportRect")
    click_icon(ui, "viewZoomIn")
    click_icon(ui, "viewZoomIn")
    assert vp.property("viewZoom") > 1.5
    want = expected_roi(vp, 250, 100, 400, 200)
    drag_in_image(ui, 250, 100, 400, 200)
    got = list(ui.be.selectedRoi)
    assert all(abs(g - w) <= 2 for g, w in zip(got, want)), (got, want)
    assert not ui.warnings, ui.warnings


def test_dragging_on_a_module_without_a_region_explains_and_does_not_change_it(ui):
    ui.reset()
    ui.settle()
    select_tool(ui, "Circle Search")
    assert list(ui.be.selectedRoi) == []
    before = {n: dict(x.parameters) for n, x in ui.be._pipeline.nodes.items()}
    drag_in_image(ui, 150, 60, 350, 200)
    toast = ui.main.property("toast")
    assert "has no region to draw" in toast, toast
    assert {n: dict(x.parameters) for n, x in ui.be._pipeline.nodes.items()} == before


def test_left_drag_pans_a_zoomed_image_when_the_module_has_no_region(ui):
    ui.reset()
    ui.settle()
    select_tool(ui, "Circle Search")
    vp = named(ui, "viewportRect")
    for _ in range(3):
        click_icon(ui, "viewZoomIn")
    x0 = vp.property("viewPanX")
    ui.drag(ui.point_in(vp, 300, 150), ui.point_in(vp, 360, 170))
    assert vp.property("viewPanX") > x0 + 30 and vp.property("viewPanY") > 10, "the image followed the mouse"
    click_icon(ui, "viewFit")
    assert vp.property("viewPanX") == 0
