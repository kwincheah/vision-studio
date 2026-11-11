"""Groups on the canvas, in the real window: right-click a module to put it in a Group, see the frame round them, take it out again."""
from PyQt6.QtCore import Qt

from test_qml_interaction import fresh, ui  # noqa: F401  (fixtures)


def frames(ui):
    return [t for t in ui.walk() if t.property("objectName") == "groupFrame"]


def title_to_id(ui, title):
    return next(n["id"] for n in ui.be.nodes if n["title"] == title)


def test_a_group_module_can_be_added_and_modules_put_in_it_from_the_right_click_menu(ui):
    be = ui.be
    be.addTool("Group")
    ui.spin(30)
    group = next(n for n in be.nodes if n["tool"] == "Group")
    assert group["group"] == "" and be.groupsFor(group["id"]) == [], "a Group cannot be put in a group"
    card = ui.cards()["06 QualityJudge"]
    ui.click(ui.point_in(card, 90, 12), Qt.MouseButton.RightButton)
    assert ui.texts("Add to group: " + group["title"]), "the menu offers the group"
    ui.click_text("Add to group: " + group["title"])
    ui.spin(30)
    judge = title_to_id(ui, "06 QualityJudge")
    assert be._pipeline.group_of(judge) == group["id"]
    assert next(n for n in be.nodes if n["id"] == judge)["group"] == group["id"]
    assert len(frames(ui)) == 1
    f = be.groupFrames[0]
    assert f["count"] == 1 and f["w"] > 190 and f["h"] > 60 and group["title"] in f["title"]


def test_the_menu_takes_a_module_out_again_and_undo_redo_work(ui):
    be = ui.be
    be.addTool("Group")
    ui.spin(20)
    group = next(n for n in be.nodes if n["tool"] == "Group")
    judge = title_to_id(ui, "06 QualityJudge")
    assert be.setNodeGroup(judge, group["id"]) == ""
    ui.spin(20)
    card = ui.cards()["06 QualityJudge"]
    ui.click(ui.point_in(card, 90, 12), Qt.MouseButton.RightButton)
    assert ui.texts("In group: " + group["title"]) and ui.texts("Take out of group")
    ui.click_text("Take out of group")
    ui.spin(20)
    assert be._pipeline.group_of(judge) == "" and len(frames(ui)) == 1, "the empty group keeps its frame"
    ui.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert be._pipeline.group_of(judge) == group["id"]
    ui.key(Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert be._pipeline.group_of(judge) == ""


def test_backend_rules(ui):
    be = ui.be
    be.addTool("Group")
    be.addTool("Group")
    ui.spin(20)
    groups = [n for n in be.nodes if n["tool"] == "Group"]
    assert len(groups) == 2
    assert be.setNodeGroup(groups[0]["id"], groups[1]["id"]) != "", "a Group cannot be inside a Group"
    judge = title_to_id(ui, "06 QualityJudge")
    assert be.setNodeGroup("nobody", groups[0]["id"]) != ""
    assert be.setNodeGroup(judge, judge) != ""
    assert be.setNodeGroup(judge, groups[0]["id"]) == "" and be.setNodeGroup(judge, groups[0]["id"]) == "", "putting it where it already is does nothing"
    assert be.setNodeGroup(judge, groups[1]["id"]) == "" and be._pipeline.group_of(judge) == groups[1]["id"], "moving it to the other group"
    assert [g["current"] for g in be.groupsFor(judge)] == [False, True] or any(g["current"] for g in be.groupsFor(judge))
    be.deleteNode(groups[1]["id"])
    ui.spin(20)
    assert be._pipeline.group_of(judge) == "" and not any(n["group"] for n in be.nodes)


def test_a_group_with_a_loop_runs_through_the_window(ui):
    be = ui.be
    be.addTool("Group")
    ui.spin(20)
    group = next(n for n in be.nodes if n["tool"] == "Group")
    judge = title_to_id(ui, "06 QualityJudge")
    be.setNodeGroup(judge, group["id"])
    node = be._pipeline.nodes[group["id"]]
    node.set_param("loop_enable", True)
    node.set_param("loop_end", 3)
    be.run()
    ui.spin(60)
    res = be._pipeline.last_results
    assert res[group["id"]].outputs["Loops"] == 3 and judge in res
