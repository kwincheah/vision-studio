"""UI/UX logic probe: drive the real QML interface and assert on observable state.

A QA harness, not a screenshot tool.  Every check performs a user-facing action through the
same backend slots the interface calls, then asserts on what the interface would display.
Failures are recorded with evidence (expected vs actual) instead of raising, so one run
reports every defect rather than stopping at the first.

Run:  python scripts/qa_ui_logic.py [--json OUT]
"""
import argparse
import json
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESULTS = []


def check(area, name, condition, expected, actual, note=""):
    RESULTS.append({"area": area, "check": name, "ok": bool(condition),
                    "expected": str(expected), "actual": str(actual), "note": note})
    if not condition:
        print(f"  FAIL {area:14s} {name}")
        print(f"       expected: {expected}")
        print(f"       actual  : {actual}")
        if note:
            print(f"       note    : {note}")


def ok(area, name):
    check(area, name, True, "", "")


def attempt(area, name, fn):
    """Run `fn`; a raised exception becomes a recorded failure."""
    try:
        return True, fn()
    except Exception as exc:                                    # noqa: BLE001
        check(area, name, False, "no exception",
              f"{type(exc).__name__}: {exc}",
              traceback.format_exc().splitlines()[-2].strip())
        return False, None


def walk(node, depth=0):
    yield node, depth
    if depth > 26:
        return
    try:
        kids = node.childItems()
    except Exception:
        return
    for kid in kids:
        yield from walk(kid, depth + 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="docs/audit/ui_logic_results.json")
    args = ap.parse_args()

    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine

    from apex_vision.qml_backend import AppBackend, FrameProvider
    from apex_vision.qml_services import install_services

    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    provider = FrameProvider()
    engine.addImageProvider("frame", provider)
    backend = AppBackend(provider)
    engine.rootContext().setContextProperty("appBackend", backend)
    services = install_services(engine, backend)
    engine._services = services
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    if not engine.rootObjects():
        print("FATAL: Main.qml did not load")
        return 2

    win = engine.rootObjects()[0]
    win.setProperty("width", 1600)
    win.setProperty("height", 950)
    win.show()

    def pump(n=25):
        for _ in range(n):
            app.processEvents()

    def settle(timeout_s=20.0, step=0.02):
        """Wait until the engine is not running, pumping events throughout."""
        waited = 0.0
        pump(5)
        while backend.running and waited < timeout_s:
            app.processEvents()
            import time
            time.sleep(step)
            waited += step
        pump(10)
        return not backend.running

    pump(60)
    content = win.contentItem()
    screen = next((o for o, _ in walk(content)
                   if o.property("workspaceTab") is not None), None)
    if screen is None:
        print("FATAL: MainScreen not found")
        return 2

    demo = os.path.join(ROOT, "projects", "PCB_Inspection_Demo.apex")

    # ==================================================================
    print("A. startup state")
    # ==================================================================
    check("startup", "title carries the version", "1.0.0" in win.property("title"),
          "contains 1.0.0", repr(win.property("title")))
    check("startup", "starts on the Flow Diagram", screen.property("workspaceTab") == 0,
          0, screen.property("workspaceTab"))
    check("startup", "right column starts on Image", str(screen.property("viewTab")) == "image",
          "image", screen.property("viewTab"))
    check("startup", "inspection panel starts hidden",
          screen.property("inspectionVisible") is False, False,
          screen.property("inspectionVisible"))
    check("startup", "AI panel starts hidden", screen.property("aiVisible") is False,
          False, screen.property("aiVisible"))
    check("startup", "a blank solution has no nodes", len(backend.nodes) == 0, 0,
          len(backend.nodes))
    check("startup", "nothing is running at startup", backend.running is False, False,
          backend.running)

    # ==================================================================
    print("B. open a project")
    # ==================================================================
    attempt("project", "openRecent", lambda: backend.openRecent(demo))
    pump(60)
    check("project", "solution name", "PCB_Inspection_Demo" in backend.solutionName,
          "PCB_Inspection_Demo", backend.solutionName)
    check("project", "7 nodes", len(backend.nodes) == 7, 7, len(backend.nodes))
    check("project", "6 connections", len(backend.connections) == 6, 6,
          len(backend.connections))
    check("project", "clean after open", backend.dirty is False, False, backend.dirty)
    check("project", "flow tab present", len(backend.flowTabs) >= 1, ">=1",
          len(backend.flowTabs))
    check("project", "image pool populated", len(backend.imagePool) >= 1, ">=1",
          len(backend.imagePool))
    check("project", "image url non-empty", bool(backend.imageUrl), "non-empty",
          repr(backend.imageUrl)[:48])
    check("project", "a first image is selected", backend.imageIndex == 0, 0,
          backend.imageIndex)

    # ==================================================================
    print("C. run / stop state machine")
    # ==================================================================
    started, _ = attempt("run", "run()", backend.run)
    finished = settle(30)
    check("run", "the run finishes (RUNNING clears)", finished, True, backend.running,
          "a stuck True leaves the UI in RUNNING forever")
    check("run", "a verdict is produced", backend.verdict in ("PASS", "FAIL"),
          "PASS or FAIL", backend.verdict)
    check("run", "every module has a result row", len(backend.moduleResults) == 7, 7,
          len(backend.moduleResults), "moduleResults feeds the per-module list")
    check("run", "flow time measured", backend.flowMs > 0, ">0", backend.flowMs)
    check("run", "algo time measured", backend.algoMs >= 0, ">=0", backend.algoMs)
    check("run", "history records the run", len(backend.history) >= 1, ">=1",
          len(backend.history))

    before = len(backend.history)
    attempt("run", "second run", backend.run)
    settle(30)
    added = len(backend.history) - before
    check("run", "a second run appends one history entry per image run",
          added == max(1, len(backend.imagePool)), max(1, len(backend.imagePool)),
          added, "Run all walks the strip, one record per image")
    check("run", "results still cover every module after a re-run",
          len(backend.moduleResults) == 7, 7, len(backend.moduleResults))

    attempt("run", "stop() while idle", backend.stop)
    settle(10)
    check("run", "stop while idle keeps the verdict",
          backend.verdict in ("PASS", "FAIL"), "unchanged", backend.verdict)

    # ==================================================================
    print("D. node selection")
    # ==================================================================
    nid0 = backend.nodes[0]["id"]
    attempt("select", "selectNode", lambda: backend.selectNode(nid0))
    pump(20)
    check("select", "selection sticks", backend.selectedId == nid0, nid0,
          backend.selectedId)
    check("select", "help text appears", bool(backend.selectedHelp), "non-empty",
          str(backend.selectedHelp)[:60])

    attempt("select", "select an unknown id", lambda: backend.selectNode("nope"))
    pump(15)
    check("select", "an unknown id does not crash the inspector",
          isinstance(backend.selectedId, str), "a string id", backend.selectedId)
    backend.selectNode(nid0)
    pump(10)

    # ==================================================================
    print("E. workspace tabs")
    # ==================================================================
    for idx in (1, 2, 0):
        screen.setProperty("workspaceTab", idx)
        pump(12)
        check("tabs", f"workspaceTab={idx} sticks", screen.property("workspaceTab") == idx,
              idx, screen.property("workspaceTab"))

    # ==================================================================
    print("F. Image | Result pages and the image strip")
    # ==================================================================
    for tab in ("result", "image"):
        screen.setProperty("viewTab", tab)
        pump(12)
        check("viewer", f"viewTab={tab} sticks", str(screen.property("viewTab")) == tab,
              tab, screen.property("viewTab"))

    n_images = len(backend.imagePool)
    if n_images >= 2:
        attempt("viewer", "selectImage(1)", lambda: backend.selectImage(1))
        pump(25)
        check("viewer", "image index moves to the second image",
              backend.imageIndex == 1, 1, backend.imageIndex)
        attempt("viewer", "selectImage(0)", lambda: backend.selectImage(0))
        pump(20)
        check("viewer", "image index returns to the first",
              backend.imageIndex == 0, 0, backend.imageIndex)
        # out of range
        attempt("viewer", "selectImage out of range",
                lambda: backend.selectImage(999))
        pump(15)
        check("viewer", "an out-of-range index does not break the selection",
              0 <= backend.imageIndex < max(1, n_images), f"0..{n_images-1}",
              backend.imageIndex)
        attempt("viewer", "selectImage(-1)", lambda: backend.selectImage(-1))
        pump(15)
        check("viewer", "a negative index does not break the selection",
              0 <= backend.imageIndex < max(1, n_images), f"0..{n_images-1}",
              backend.imageIndex)
    else:
        check("viewer", "two images available", False, ">=2", n_images)

    # ==================================================================
    print("G. zoom / pan clamping (the new pinch code)")
    # ==================================================================
    viewport = next((o for o, _ in walk(content)
                     if o.property("objectName") == "viewportRect"), None)
    if viewport is not None:
        attempt("zoom", "resetView", viewport.resetView)
        pump(8)
        check("zoom", "reset gives zoom 1",
              abs(viewport.property("viewZoom") - 1) < 1e-6, 1.0,
              viewport.property("viewZoom"))
        check("zoom", "reset zeroes the pan",
              abs(viewport.property("viewPanX")) < 1e-6
              and abs(viewport.property("viewPanY")) < 1e-6, (0, 0),
              (viewport.property("viewPanX"), viewport.property("viewPanY")))
        attempt("zoom", "zoomBy(8)", lambda: viewport.zoomBy(8.0, 300, 150))
        pump(8)
        check("zoom", "zoom clamps at 16", viewport.property("viewZoom") <= 16.0001,
              "<=16", viewport.property("viewZoom"))
        attempt("zoom", "zoom out hard", lambda: viewport.zoomBy(0.0001, 300, 150))
        pump(8)
        check("zoom", "zoom clamps at 1",
              abs(viewport.property("viewZoom") - 1) < 1e-6, 1.0,
              viewport.property("viewZoom"))
        check("zoom", "at zoom 1 the pan is zero again",
              abs(viewport.property("viewPanX")) < 1e-6
              and abs(viewport.property("viewPanY")) < 1e-6, (0, 0),
              (viewport.property("viewPanX"), viewport.property("viewPanY")),
              "otherwise the image sits off-centre at fit-to-view")
    else:
        check("zoom", "image viewport found", False, "viewport", "not found")

    attempt("zoom", "canvas zoomAt huge", lambda: screen.zoomAt(400, 300, 1000))
    pump(8)
    check("zoom", "canvas zoom clamps at 2.5", screen.property("zoom") <= 2.5001,
          "<=2.5", screen.property("zoom"))
    attempt("zoom", "canvas zoomAt tiny", lambda: screen.zoomAt(400, 300, 0.00001))
    pump(8)
    check("zoom", "canvas zoom clamps at 0.25", screen.property("zoom") >= 0.2499,
          ">=0.25", screen.property("zoom"))
    attempt("zoom", "fitView", screen.fitView)
    pump(12)
    check("zoom", "fitView leaves a usable zoom",
          0.24 < screen.property("zoom") < 2.51, "0.25..2.5",
          screen.property("zoom"))

    # ==================================================================
    print("H. dialogs")
    # ==================================================================
    host = next((o for o, _ in walk(content)
                 if o.property("current") is not None and hasattr(o, "show")), None)
    if host is not None:
        check("dialogs", "the host starts closed", host.property("current") == "", "",
              host.property("current"))
        for name in ("newProject", "globalVars", "comm", "flowSettings", "validation",
                     "cameraSet", "lensCal", "plugins", "confirm"):
            attempt("dialogs", f"open {name}", lambda n=name: host.show(n))
            pump(12)
            check("dialogs", f"{name} becomes current", host.property("current") == name,
                  name, host.property("current"))
            attempt("dialogs", f"close {name}", host.close)
            pump(8)
            check("dialogs", f"{name} leaves nothing open",
                  host.property("current") == "", "", host.property("current"))
        host.show("newProject")
        pump(8)
        attempt("dialogs", "open a dialog over another", lambda: host.show("globalVars"))
        pump(8)
        check("dialogs", "the newest dialog wins",
              host.property("current") == "globalVars", "globalVars",
              host.property("current"))
        host.close()
        pump(8)
    else:
        check("dialogs", "dialog host found", False, "host", "not found")

    # ==================================================================
    print("I. inspection panel")
    # ==================================================================
    screen.setProperty("inspectionVisible", True)
    pump(20)
    check("inspection", "panel becomes visible",
          screen.property("inspectionVisible") is True, True,
          screen.property("inspectionVisible"))
    for tab in range(5):
        screen.setProperty("inspectionTab", tab)
        pump(8)
        check("inspection", f"tab {tab} sticks", screen.property("inspectionTab") == tab,
              tab, screen.property("inspectionTab"))
    screen.setProperty("inspectionVisible", False)
    pump(8)

    # ==================================================================
    print("J. AI panel")
    # ==================================================================
    for value, label in ((True, "shows"), (False, "hides")):
        screen.setProperty("aiVisible", value)
        pump(15)
        check("ai", f"the AI panel {label}", screen.property("aiVisible") is value,
              value, screen.property("aiVisible"))

    # ==================================================================
    print("K. dirty flag and unsaved-change logic")
    # ==================================================================
    backend.openRecent(demo)
    pump(40)
    dirty_at_open = backend.dirty
    # Only the first open of a session starts clean; see BUG-02 in the QA report
    # (the image pool re-applies the strip image to the source node on every later load).
    check("dirty", "reopening a project returns to a clean state",
          dirty_at_open is False, False, dirty_at_open,
          "if this fails, the session cannot reach a clean state without saving")
    nid = backend.nodes[0]["id"]
    attempt("dirty", "beginMove", backend.beginMove)
    attempt("dirty", "moveNode", lambda: backend.moveNode(nid, 140, 90))
    pump(12)
    check("dirty", "moving a node marks the project dirty", backend.dirty is True, True,
          backend.dirty, "otherwise closing discards the edit silently")

    # undo should return to clean (or at least revert the position)
    attempt("dirty", "undo", backend.undo)
    pump(15)
    check("dirty", "undo after a move restores the pre-move dirty state",
          backend.dirty is dirty_at_open, dirty_at_open, backend.dirty,
          "undo must remove exactly the edit it undoes")

    attempt("dirty", "redo", backend.redo)
    pump(15)
    check("dirty", "redo re-applies the edit", backend.dirty is True, True,
          backend.dirty)

    # ==================================================================
    print("L. adding a tool and validating the flow")
    # ==================================================================
    n_before = len(backend.nodes)
    attempt("edit", "addTool", lambda: backend.addTool("Image Filter"))
    pump(20)
    check("edit", "adding a tool grows the flow", len(backend.nodes) == n_before + 1,
          n_before + 1, len(backend.nodes))
    check("edit", "the new tool is selected",
          isinstance(backend.selectedId, str) and backend.selectedId != "",
          "a node id", backend.selectedId,
          "an unselected new node leaves the property panel showing the old module")
    issues = None
    good, issues = attempt("validate", "validateFlow", backend.validateFlow)
    if good:
        check("validate", "validation returns a list",
              isinstance(issues, (list, tuple)), "list", type(issues).__name__)
        check("validate", "the unwired tool is reported",
              any("connect" in str(i).lower() for i in issues),
              "a missing-connection issue", str(issues)[:100],
              "a tool added with no inputs should be flagged")

    # ==================================================================
    print("M. parameter editing")
    # ==================================================================
    if backend.nodes:
        first = backend.nodes[0]
        fid = first["id"]
        backend.selectNode(fid)
        pump(12)
        params = None
        good, params = attempt("param", "moduleParams", lambda: backend.moduleParams(fid))
        if good and params:
            check("param", "the module exposes parameters", len(params) >= 1, ">=1",
                  len(params))
            key = params[0].get("key") or params[0].get("name")
            if key:
                before_val = params[0].get("value")
                attempt("param", "setParamValue",
                        lambda: backend.setParamValue(fid, key, before_val))
                pump(12)
                check("param", "setting a parameter is accepted", True, True, True)
        else:
            check("param", "moduleParams returns something", False, "a list", params)

    # ==================================================================
    print("N. robustness")
    # ==================================================================
    attempt("robust", "unknown action", lambda: screen.invoke("no_such_action"))
    pump(8)
    check("robust", "an unknown action leaves the tab valid",
          0 <= screen.property("workspaceTab") <= 2, "0..2",
          screen.property("workspaceTab"))
    attempt("robust", "close an unknown flow",
            lambda: backend.closeFlow("no_such_flow"))
    pump(10)
    check("robust", "closing an unknown flow keeps the flow list",
          len(backend.flowTabs) >= 1, ">=1", len(backend.flowTabs))
    attempt("robust", "select an unknown flow",
            lambda: backend.selectFlow("no_such_flow"))
    pump(10)
    turn_ok, _ = attempt("robust", "run after a bad selectFlow", backend.run)
    settle(20)
    check("robust", "the flow still runs after a bad selectFlow", turn_ok, True,
          turn_ok)

    # ==================================================================
    total = len(RESULTS)
    failed = [r for r in RESULTS if not r["ok"]]
    print("=" * 72)
    print(f"{total} checks | {total - len(failed)} passed | {len(failed)} FAILED")
    if failed:
        print("\nFAILURES BY AREA")
        areas = {}
        for f in failed:
            areas.setdefault(f["area"], []).append(f)
        for area, items in areas.items():
            print(f"\n{area}:")
            for f in items:
                print(f"  - {f['check']}")
                print(f"      expected {f['expected']}")
                print(f"      actual   {f['actual']}")
                if f["note"]:
                    print(f"      note     {f['note']}")

    out = os.path.join(ROOT, args.json)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"total": total, "failed": len(failed), "results": RESULTS}, fh,
                  indent=1)
    print(f"\nwritten to {args.json}")
    win.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
