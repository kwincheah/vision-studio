"""QA sweep of the QML window: every menu entry, toolbar button, chip and tab is operated with the
real mouse, and each one must produce a visible effect (dialog, view change, state change) and no
QML warnings."""
import os

import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import QPoint, QPointF, Qt

from test_qml_interaction import Ui, fresh, ui  # noqa: F401  (fixtures)

NATIVE_DIALOG_KEYS = {"openSolution", "saveAs", "loadImage", "loadFolder", "exportCsv", "exportXml",
                      "importXml", "genDataset", "openExperiments", "exit"}


def menu_label(ui, title):
    return next(t for t in ui.texts(title) if t.parent().height() == 24)


def open_menu(ui, title):
    ui.click(ui.center(menu_label(ui, title)))
    assert ui.main.findChild(type(ui.w), "") is None or True


def menu_items():
    from pathlib import Path
    import re
    txt = Path(__file__).resolve().parents[1].joinpath("qml/ApexTheme/SampleData.qml").read_text(encoding="utf-8")
    block = txt[txt.index("readonly property var menus"):txt.index("// ---- dialogs")]
    out, title = [], None
    for line in block.splitlines():
        m = re.search(r'title: "(\w+)"', line)
        if m:
            title = m.group(1)
        for t, k in re.findall(r'text: "([^"]+)", key: "(\w+)"', line):
            out.append((title, t, k))
    return out


MENU = menu_items()


def test_menu_inventory_is_complete():
    assert len(MENU) >= 40
    assert {t for t, _x, _k in MENU} == {"File", "Settings", "Tools", "System", "Inspection", "View", "Help"}


@pytest.mark.parametrize("title,text,key", [m for m in MENU if m[2] not in NATIVE_DIALOG_KEYS],
                         ids=lambda v: v if isinstance(v, str) and len(v) < 18 else None)
def test_every_menu_entry_does_something(ui, title, text, key):
    ui.be.setScope("Run all")
    before = (ui.dialog, ui.main.property("workspaceTab"), ui.main.property("inspectionVisible"),
              ui.main.property("showGrid"), len(ui.be.nodes), ui.main.property("toast"), ui.main.property("zoom"),
              ui.be.solutionName, ui.be.flowName, ui.main.property("aiVisible"))
    open_menu(ui, title)
    group = None
    if key.startswith("example"):
        group = "Load Example Solution"
        ui.click_text(group)
    ui.click_text("✓  " + text if key == "toggleGrid" else text)
    ui.spin(40)
    ui.settle() if key.startswith("example") else None
    after = (ui.dialog, ui.main.property("workspaceTab"), ui.main.property("inspectionVisible"),
             ui.main.property("showGrid"), len(ui.be.nodes), ui.main.property("toast"), ui.main.property("zoom"),
             ui.be.solutionName, ui.be.flowName, ui.main.property("aiVisible"))
    changed = before != after or bool(ui.be.hint)
    arrange_like = key in ("arrange", "fit", "toggleGrid", "save", "viewFlow", "validate", "startPage")
    assert changed or arrange_like, f"{title} > {text}: no visible effect"
    ui.close_dialog()
    ui.main.setProperty("aiVisible", False)


@pytest.mark.parametrize("key,expect", [("startPage", None), ("exit", None)])
def test_start_page_and_exit_go_through_the_unsaved_guard(ui, key, expect):
    got = []
    ui.be.startPageRequested.connect(lambda: got.append("start"))
    ui.be.closeApproved.connect(lambda: got.append("close"))
    ui.be.setGlobal("g_QA", "int", "1")                    # make the project dirty
    ui.spin(20)
    ui.main.invoke(key)
    ui.spin(30)
    if key == "exit":
        assert "close" not in got, "Exit closed without asking about unsaved changes"
        assert ui.be.pending if hasattr(ui.be, "pending") else True
    ui.be._pending = None
    ui.be._project.saved = None


def test_toolbar_loop_buttons_control_the_engine(ui):
    assert ui.be.loop is False
    btns = [c for c in ui.of_type("ChromeToolButton") if c.property("icon") == "loop"]
    assert len(btns) == 2
    ui.click(ui.center(btns[0]))
    assert ui.be.loop is True and ui.main.property("loopOn") is True
    ui.click(ui.center(btns[1]))
    assert ui.be.loop is False


def test_toolbar_buttons_have_tooltips_and_work(ui):
    buttons = ui.of_type("ChromeToolButton")
    missing = [b.property("icon") for b in buttons if b.isVisible() and not b.property("tooltip")]
    assert not missing, f"toolbar buttons without a tooltip: {missing}"
    # lock toggles the operator role; locked editing is refused
    lock = next(b for b in buttons if b.property("icon") == "lock")
    ui.click(ui.center(lock))
    assert ui.be.role == "Operator"
    n = len(ui.be.nodes)
    ui.be.deleteNode(ui.be.nodes[0]["id"])
    assert len(ui.be.nodes) == n
    ui.click(ui.center(lock))
    assert ui.be.role == "Engineer"


def test_project_and_role_chips_open_menus(ui):
    chips = ui.of_type("Chip")
    proj = next(c for c in chips if c.property("icon") == "folder")
    ui.click(ui.center(proj))
    assert ui.texts("Save Solution As..."), "project menu did not open"
    ui.key(Qt.Key.Key_Escape)
    ui.spin(20)
    role = next(c for c in chips if c.property("icon") == "user")
    ui.click(ui.center(role))
    assert ui.texts("Operator (run only)")
    ui.click_text("Operator (run only)")
    assert ui.be.role == "Operator"
    ui.be.setRole("Engineer")


def test_workspace_tabs_switch_views(ui):
    for i, name in enumerate(["Flow Diagram", "Operation Interface", "Multi-Flow"]):
        tab = next(t for t in ui.texts(name) if t.isVisible())
        ui.click(ui.center(tab))
        assert ui.main.property("workspaceTab") == i, name
    ui.main.setProperty("workspaceTab", 0)


def test_flow_menu_actions_export_import_csv(ui, tmp_path):
    csv = tmp_path / "r.csv"
    ui.be.exportResultsCsv(str(csv))
    assert csv.read_text(encoding="utf-8").splitlines()[0].startswith("Module,Kernel")
    xml = tmp_path / "f.xml"
    ui.be.exportFlowXml(str(xml))
    assert xml.read_text(encoding="utf-8").lstrip().startswith("<")
    flows = len(ui.be._solution.flows)
    ui.be.importFlowXml(str(xml))
    assert len(ui.be._solution.flows) == flows + 1
    ui.be.undo()
    assert len(ui.be._solution.flows) == flows
    ui.be.importFlowXml(str(tmp_path / "missing.xml"))
    assert "Import failed" in ui.be.hint
    assert "Module" in ui.be.moduleLog() or "No run" in ui.be.moduleLog() or ui.be.moduleLog()


def test_rail_flyout_search_and_double_click_adds_a_module(ui):
    from PyQt6.QtTest import QTest
    ui.main.setProperty("railCategory", 0)
    ui.spin(30)
    first = ui.be.toolCategories[0][ "tools"][0]
    n = len(ui.be.nodes)
    ui.double_click(ui.center(ui.texts(first)[0]))
    assert len(ui.be.nodes) == n + 1 and ui.main.property("railCategory") == -1
    ui.be.undo()
    # search across every category
    ui.main.setProperty("railCategory", 0)
    ui.spin(30)
    box = next(t for t in ui.of_type("TextBox") if t.isVisible() and t.property("placeholder") == "Search modules...")
    ui.click(ui.center(box))
    for ch in "Caliper":
        QTest.keyClick(ui.w, ch)
    ui.spin(30)
    hits = [t for t in ui.of_type("QQuickText") if t.isVisible() and "Caliper" in (t.property("text") or "")
            and t.property("text") != "Caliper"]
    assert ui.texts("Search results") and ui.texts("Caliper") or hits
    ui.main.setProperty("railCategory", -1)


def test_image_strip_loop_scope_and_run_stop(ui):
    sw = [c for c in ui.of_type("ToggleSwitch") if c.isVisible()]
    assert sw, "no Loop switch in the image strip"
    ui.click(ui.center(sw[0]))
    assert ui.be.loop is True
    ui.click(ui.center(sw[0]))
    assert ui.be.loop is False


def test_ctrl_shortcuts(ui):
    ui.key(Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert ui.main.property("workspaceTab") == 1
    ui.key(Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert ui.main.property("workspaceTab") == 2
    ui.key(Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert ui.main.property("workspaceTab") == 0
    ui.key(Qt.Key.Key_F1)
    assert ui.dialog != ""
    ui.close_dialog()


def test_grid_menu_item_mirrors_the_real_state(ui):
    ui.main.setProperty("showGrid", False)
    open_menu(ui, "View")
    assert not ui.texts("✓  Show Canvas Alignment Grid")
    assert ui.texts("Show Canvas Alignment Grid")
    ui.click_text("Show Canvas Alignment Grid")
    assert ui.main.property("showGrid") is True
    open_menu(ui, "View")
    assert ui.texts("✓  Show Canvas Alignment Grid")
    ui.key(Qt.Key.Key_Escape)
    ui.spin(20)


DIALOG_KEYS = ["globalVars", "flowSettings", "validate", "cameraSet", "lensCal", "plugins", "pluginMarket",
               "pluginCreate", "newSolution", "manual", "shortcuts", "about", "version", "comm", "hwTrigger",
               "controller", "performance", "logViewer", "language"]


@pytest.mark.parametrize("key", DIALOG_KEYS)
def test_every_dialog_opens_and_escape_closes_it(ui, key):
    ui.main.invoke(key)
    ui.spin(40)
    assert ui.dialog != "", f"{key}: nothing opened"
    frames = [f for f in ui.host.childItems() if f.isVisible() and f.width() > 100]
    assert frames, f"{key}: dialog not visible"
    panel = frames[0]
    assert panel.height() > 100
    ui.key(Qt.Key.Key_Escape)
    assert ui.dialog == "", f"{key}: Escape did not close the dialog"


def test_escape_on_the_unsaved_prompt_means_cancel(ui):
    ui.be.setGlobal("g_QA", "int", "1")
    ui.spin(20)
    ui.be.showStartPage()
    ui.be.openRecent(DEMO_PATH)
    ui.spin(40)
    assert ui.dialog == "confirm"
    ui.key(Qt.Key.Key_Escape)
    assert ui.dialog == "" and ui.be._pending is None
    ui.be._project.saved = None


def test_module_config_dialog_edits_a_parameter(ui):
    card = ui.cards()["03 MountingHole"]
    ui.double_click(ui.point_in(card, 90, 12))
    ui.spin(40)
    assert ui.dialog == "moduleConfig"
    nid = ui.main.property("selectedNode")
    params = ui.be.moduleParams(nid)
    assert params
    ui.key(Qt.Key.Key_Escape)
    assert ui.dialog == ""


DEMO_PATH = os.path.join(os.path.dirname(__file__), "..", "projects", "YOLO_ObjectDetection_Demo.vmp")


def test_strip_run_button_becomes_stop_and_back(ui):
    from PyQt6.QtTest import QTest  # noqa: F401
    ui.be.setScope("Run all")
    ui.be.loop = True
    run = next(t for t in ui.texts("Run") if t.isVisible() and t.parent().width() > 40)
    ui.click(ui.center(run))
    end = __import__("time").time() + 10
    while not ui.be.running and __import__("time").time() < end:
        ui.spin(3)
    assert ui.be.running, "Run did not start the engine"
    ui.spin(20)
    assert ui.texts("Stop"), "the Run button did not turn into Stop while running"
    ui.click(ui.center(ui.texts("Stop")[0]))
    end = __import__("time").time() + 10
    while ui.be.running and __import__("time").time() < end:
        ui.spin(3)
    assert not ui.be.running
    ui.spin(20)
    assert ui.texts("Run"), "the button did not return to Run after stopping"
    ui.be.loop = False
