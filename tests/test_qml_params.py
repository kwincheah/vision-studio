"""Module configuration > Run Params: each parameter is edited with the control that fits it (drop-down, switch,
number with limits, region fields, path, script editor) - operated with real mouse and keyboard events."""
import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest

from test_qml_interaction import fresh, ui  # noqa: F401


def node(ui, tool):
    return next(n for n in ui.be._pipeline.nodes.values() if n.tool_name == tool)


def open_config(ui, tool, tab="Run Params"):
    nid = node(ui, tool).instance_id
    dlg = next(c for c in ui.of_type("ModuleConfigDialog"))
    dlg.setProperty("nodeId", nid)
    dlg.setProperty("moduleName", tool)
    ui.host.setProperty("current", "moduleConfig")
    ui.spin(40)
    ui.click_text(tab)
    ui.spin(30)
    return nid


def editors(ui):
    out = {}
    for e in ui.of_type("ParamEditor"):
        if e.isVisible():
            out[e.property("spec")["name"]] = e
    return out


def child(ui, editor, object_name):
    return [c for c in ui.walk(editor) if c.property("objectName") == object_name and c.isVisible()]


def choose(ui, box, label):
    ui.click(ui.center(box))
    ui.spin(15)
    y0 = ui.center(box).y()
    entry = next(t for t in ui.texts(label) if ui.center(t).y() > y0 + 5)
    ui.click(ui.center(entry))
    ui.spin(40)


def test_each_kind_of_parameter_gets_its_own_editor(ui):
    open_config(ui, "Caliper")
    ed = editors(ui)
    assert child(ui, ed["polarity"], "paramEnum") and child(ui, ed["caliper_mode"], "paramEnum"), "text values with fixed choices must be drop-downs"
    assert not child(ui, ed["polarity"], "paramText")
    assert len(child(ui, ed["line_p1"], "paramTuple0")) == 1 and len(child(ui, ed["line_p1"], "paramTuple1")) == 1
    assert child(ui, ed["edge_threshold"], "paramNumber")
    ui.close_dialog()


def test_booleans_are_switches_and_numbers_show_their_limits(ui):
    ui.be.addTool("Image Binarization")
    ui.settle()
    open_config(ui, "Image Binarization")
    ed = editors(ui)
    assert child(ui, ed["invert"], "paramSwitch"), "a true/false parameter must be a switch, not a text box"
    assert child(ui, ed["method"], "paramEnum")
    assert ui.texts("0 to 255") and ui.texts("Adaptive block size")
    ui.close_dialog()


def test_choosing_from_a_dropdown_changes_the_module_and_undo_reverts_it(ui):
    nid = open_config(ui, "Caliper")
    box = child(ui, editors(ui)["polarity"], "paramEnum")[0]
    choose(ui, box, "Dark to light")
    assert node(ui, "Caliper").parameters["polarity"] == "Dark to light"
    assert "Polarity set to Dark to light" in ui.be.hint
    ui.close_dialog()
    ui.be.undo()
    ui.settle()
    assert node(ui, "Caliper").parameters["polarity"] == "Any"


def test_the_switch_toggles_the_boolean_parameter(ui):
    ui.be.addTool("Image Binarization")
    ui.settle()
    open_config(ui, "Image Binarization")
    sw = child(ui, editors(ui)["invert"], "paramSwitch")[0]
    ui.click(ui.center(sw))
    assert node(ui, "Image Binarization").parameters["invert"] is True
    ui.click(ui.center(sw))
    assert node(ui, "Image Binarization").parameters["invert"] is False
    ui.close_dialog()


def test_number_buttons_step_and_the_limits_hold(ui):
    open_config(ui, "TCP Send")
    nb = child(ui, editors(ui)["server_port"], "paramNumber")[0]
    port = node(ui, "TCP Send").parameters["server_port"]
    plus = nb.mapToScene(QPointF(nb.width() - 12, nb.height() / 2))
    ui.click(QPoint(int(plus.x()), int(plus.y())))
    assert node(ui, "TCP Send").parameters["server_port"] == port + 1 and isinstance(node(ui, "TCP Send").parameters["server_port"], int)
    # typing a value beyond the limit is brought back to the limit
    ui.click(QPoint(int(nb.mapToScene(QPointF(20, 12)).x()), int(nb.mapToScene(QPointF(20, 12)).y())))
    ui.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for ch in "99999":
        QTest.keyClick(ui.w, ch)
    ui.key(Qt.Key.Key_Return)
    ui.spin(30)
    assert node(ui, "TCP Send").parameters["server_port"] == 65535
    ui.close_dialog()


def test_a_region_is_four_labelled_fields_and_editing_one_keeps_the_others(ui):
    open_config(ui, "Template Match")
    ed = editors(ui)["template_roi"]
    before = list(node(ui, "Template Match").parameters["template_roi"])
    assert all(len(child(ui, ed, f"paramTuple{i}")) == 1 for i in range(4))
    assert ui.texts("X") and ui.texts("W") and ui.texts("H")
    nb = child(ui, ed, "paramTuple2")[0]                                       # W
    plus = nb.mapToScene(QPointF(nb.width() - 12, nb.height() / 2))
    ui.click(QPoint(int(plus.x()), int(plus.y())))
    after = node(ui, "Template Match").parameters["template_roi"]
    assert after == [before[0], before[1], before[2] + 1, before[3]]
    ui.close_dialog()


def test_text_values_commit_on_enter(ui):
    open_config(ui, "TCP Send")
    box = child(ui, editors(ui)["prefix"], "paramText")[0]
    ui.click(ui.center(box))
    ui.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for ch in "ABC,":
        QTest.keyClick(ui.w, ch)
    ui.key(Qt.Key.Key_Return)
    ui.spin(30)
    assert node(ui, "TCP Send").parameters["prefix"] == "ABC,"
    ui.close_dialog()


def test_the_script_is_edited_in_a_code_editor_and_applied_on_demand(ui):
    ui.be.addTool("Script")
    ui.settle()
    open_config(ui, "Script")
    ed = editors(ui)["code"]
    code = child(ui, ed, "paramCode")[0]
    code.setProperty("text", "outputs['Result'] = 42\n")
    ui.spin(10)
    ui.click_text("Apply script")
    assert node(ui, "Script").parameters["code"] == "outputs['Result'] = 42\n"
    ui.close_dialog()


def test_trigger_target_flow_is_a_dropdown_of_the_flows_that_exist(ui):
    ui.be.addFlow()
    ui.settle()
    ui.be.addTool("Trigger")
    ui.settle()
    open_config(ui, "Trigger")
    box = child(ui, editors(ui)["target_flow"], "paramEnum")[0]
    assert box.property("model") is not None
    flows = list(ui.be._solution.flows)
    assert len(flows) >= 2
    choose(ui, box, flows[-1])
    assert node(ui, "Trigger").parameters["target_flow"] == flows[-1]
    ui.close_dialog()


def test_points_are_edited_one_per_line_and_bad_lines_are_explained(ui):
    ui.be.addTool("Circle/Line Fit")
    ui.settle()
    open_config(ui, "Circle/Line Fit")
    ed = editors(ui)["default_points"]
    area = child(ui, ed, "paramPoints")[0]
    area.setProperty("text", "10, 20\n30, 40\n50, 20\n")
    ui.click_text("Apply points")
    assert node(ui, "Circle/Line Fit").parameters["default_points"] == [[10, 20], [30, 40], [50, 20]]
    area.setProperty("text", "10, 20\noops\n")
    ui.click_text("Apply points")
    assert ui.texts("Line 2: write x, y")
    assert node(ui, "Circle/Line Fit").parameters["default_points"] == [[10, 20], [30, 40], [50, 20]]
    ui.close_dialog()


def test_the_dialog_title_names_the_toolbox_module_and_cards_show_it(ui):
    nid = open_config(ui, "Template Match")
    assert ui.texts("Module Configuration - Template Match  (Template Match)") or any(
        "(Template Match)" in (t.property("text") or "") for t in ui.of_type("QQuickText") if t.isVisible())
    ui.close_dialog()
    names = {c.property("title"): c for c in ui.cards().values()} if False else None
    tool_labels = {t.property("text") for t in ui.walk() if t.property("objectName") == "cardToolName" and t.isVisible()}
    assert {"Image Source", "Template Match", "Circle Search", "Caliper", "Defect Detection", "Condition Branch", "TCP Send"} <= tool_labels


def test_every_card_in_every_sample_names_a_module_that_is_in_the_toolbox(ui):
    """The names on a card are the user's own; the footer shows the toolbox module, and it must exist there."""
    toolbox = {t for c in ui.be.toolCategories for t in c["tools"]}
    import glob
    import os
    from apex_vision.core.pipeline import SolutionManager
    root = os.path.join(os.path.dirname(__file__), "..")
    files = glob.glob(os.path.join(root, "projects", "*.vmp"))
    assert files
    for f in files:
        for flow in SolutionManager.load_from_file(f).flows.values():
            for n in flow.nodes.values():
                assert n.tool_name in toolbox, f"{os.path.basename(f)}: {n.name} is a {n.tool_name!r}, which the toolbox does not offer"
    from apex_vision.samples import pcb_solution as ps
    for make in (ps.create_pcb_inspection_solution, ps.create_calibration_robot_solution,
                 ps.create_precision_measurement_solution, ps.create_object_detection_solution):
        for n in make().nodes.values():
            assert n.tool_name in toolbox and type(n).__name__ != "MissingPluginPlaceholderTool"
