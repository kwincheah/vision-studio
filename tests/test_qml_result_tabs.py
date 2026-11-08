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
