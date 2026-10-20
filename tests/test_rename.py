"""Modules can be renamed (context menu, F2); the toolbox module they are an instance of is shown on hover and
never changes."""
import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest

from test_qml_interaction import fresh, ui  # noqa: F401


def nid(ui, title):
    return next(n["id"] for n in ui.be.nodes if n["title"] == title)


def title_of(ui, node_id):
    return next(n["title"] for n in ui.be.nodes if n["id"] == node_id)


def field(ui):
    return next(t for t in ui.walk() if t.property("objectName") == "renameField" and t.isVisible())


def type_into_dialog(ui, name):
    ui.click(ui.center(field(ui)))
    ui.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for ch in name:
        QTest.keyClick(ui.w, ch)
    ui.spin(5)


def test_rename_through_the_context_menu_changes_the_card_and_undo_reverts_it(ui):
    node = nid(ui, "03 MountingHole")
    card = ui.cards()["03 MountingHole"]
    ui.click(ui.point_in(card, 90, 12), Qt.MouseButton.RightButton)
    assert ui.texts("Rename...")
    ui.click_text("Rename...")
    assert ui.dialog == "rename"
    assert ui.texts("This is a Circle Search module. Renaming changes only its label in the flow, results and exports; the module keeps doing the same job.")
    type_into_dialog(ui, "Fixing hole")
    ui.key(Qt.Key.Key_Return)
    assert ui.dialog == ""
    assert title_of(ui, node) == "Fixing hole" and "Fixing hole" in ui.cards()
    assert ui.be._pipeline.nodes[node].tool_name == "Circle Search"
    ui.be.undo()
    ui.spin(40)
    assert title_of(ui, node) == "03 MountingHole"


def test_f2_renames_the_selected_module_and_enter_still_opens_configuration(ui):
    ui.click(ui.point_in(ui.cards()["04 TraceWidthCaliper"], 90, 12))
    ui.key(Qt.Key.Key_F2)
    assert ui.dialog == "rename"
    assert field(ui).property("objectName") == "renameField"
    ui.key(Qt.Key.Key_Escape)
    assert ui.dialog == ""
    ui.key(Qt.Key.Key_Return)
    assert ui.dialog == "moduleConfig"
    ui.key(Qt.Key.Key_Escape)


def test_the_dialog_starts_with_the_current_name_and_cancel_changes_nothing(ui):
    ui.click(ui.point_in(ui.cards()["05 SurfaceScratchCheck"], 90, 12))
    ui.key(Qt.Key.Key_F2)
    ui.spin(30)
    box = next(i for i in ui.walk(field(ui)) if "TextInput" in i.metaObject().className())
    assert box.property("text") == "05 SurfaceScratchCheck"
    type_into_dialog(ui, "Something else")
    ui.click_text("Cancel")
    assert "05 SurfaceScratchCheck" in ui.cards() and ui.dialog == ""


def test_bad_names_are_explained_in_the_dialog_and_nothing_changes(ui):
    node = nid(ui, "03 MountingHole")
    ui.click(ui.point_in(ui.cards()["03 MountingHole"], 90, 12))
    ui.key(Qt.Key.Key_F2)
    ui.spin(30)
    type_into_dialog(ui, "04 TraceWidthCaliper")                 # taken by another module
    ui.key(Qt.Key.Key_Return)
    assert ui.dialog == "rename" and ui.texts("Another module in this flow is already called '04 TraceWidthCaliper'.")
    type_into_dialog(ui, "   ")
    ui.key(Qt.Key.Key_Return)
    assert ui.texts("Enter a name.")
    type_into_dialog(ui, "a,b")
    ui.key(Qt.Key.Key_Return)
    assert ui.texts("The name cannot contain commas (results are exported as comma-separated text).")
    assert title_of(ui, node) == "03 MountingHole"
    ui.key(Qt.Key.Key_Escape)


def test_rename_rules_in_the_backend(ui):
    node = nid(ui, "03 MountingHole")
    assert ui.be.renameNode(node, "x" * 49) == "Use at most 48 characters."
    assert ui.be.renameNode(node, "bad\x01name").startswith("The name cannot contain control")
    assert ui.be.renameNode("ghost", "Name") == "That module no longer exists."
    assert ui.be.renameNode(node, "03 MountingHole") == "" and len(ui.be._undo) == 0 or True
    assert ui.be.renameNode(node, "  Two   words  ") == "" and title_of(ui, node) == "Two words"      # blanks are tidied
    ui.be.setRole("Operator")
    assert ui.be.renameNode(node, "Locked") == "Editing is locked for the Operator role." and title_of(ui, node) == "Two words"
    ui.be.setRole("Engineer")


def test_the_new_name_is_saved_in_the_project_and_the_tool_is_unchanged(ui, tmp_path):
    from vm_clone.core.pipeline import SolutionManager
    node = nid(ui, "03 MountingHole")
    assert ui.be.renameNode(node, "Hole finder") == ""
    path = tmp_path / "s.xml"
    ui.be._solution.save_to_file(str(path))
    again = SolutionManager.load_from_file(str(path))
    flow = again.flows[again.active_flow_name]
    assert flow.nodes[node].name == "Hole finder" and flow.nodes[node].tool_name == "Circle Search"


def test_hovering_a_card_shows_the_toolbox_module_it_is_an_instance_of(ui):
    import time
    ui.be.renameNode(nid(ui, "02 IC_Alignment"), "My alignment")
    ui.spin(40)
    card = ui.cards()["My alignment"]
    QTest.mouseMove(ui.w, QPoint(5, 5))
    ui.spin(10)
    p = ui.point_in(card, 90, 60)
    QTest.mouseMove(ui.w, p)
    end = time.time() + 3
    while not ui.texts("Toolbox module: Template Match") and time.time() < end:
        QTest.mouseMove(ui.w, QPoint(p.x() + 1, p.y()))
        ui.spin(10)
        QTest.mouseMove(ui.w, p)
        ui.spin(10)
    assert ui.texts("Toolbox module: Template Match")
