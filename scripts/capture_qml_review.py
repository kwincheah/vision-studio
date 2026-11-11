"""Render the QML interface with a real project loaded, plus each dialog.

Reviewing a design needs the populated state, not the empty startup canvas.  This opens
a shipped `.apex` project through the backend's own `openRecent`, then captures the
workspace, the tabs, and every dialog.

Run:  python scripts/capture_qml_review.py [--project PATH]
"""
import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "screenshots", "qml_review")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.path.join("projects", "PCB_Inspection_Demo.apex"))
    ap.add_argument("--size", default="1600x950")
    args = ap.parse_args()
    width, height = (int(v) for v in args.size.lower().split("x"))

    os.makedirs(OUT, exist_ok=True)

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
    engine._services = install_services(engine, backend)
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    if not engine.rootObjects():
        print("FAIL: Main.qml did not load")
        return 1

    win = engine.rootObjects()[0]
    win.setProperty("width", width)
    win.setProperty("height", height)
    win.show()

    def pump(n=30):
        for _ in range(n):
            app.processEvents()

    def shot(name):
        pump(30)
        img = win.grabWindow()
        img.save(os.path.join(OUT, name))
        print(f"saved {name}  {img.width()}x{img.height()}", flush=True)

    content = win.contentItem()

    def walk(node, depth=0):
        yield node
        if depth > 18:
            return
        try:
            kids = node.childItems()
        except Exception:
            return
        for kid in kids:
            yield from walk(kid, depth + 1)

    def by_object_name(name):
        return next((o for o in walk(content)
                     if o.property("objectName") == name), None)

    # `workspaceTab` / `viewTab` / `resultTab` belong to MainScreen, not to the Window, so
    # setting them on the window is a silent no-op.  Find the screen object itself.
    screen = by_object_name("mainScreen")
    if screen is None:
        # MainScreen is the first Item child of the window with a `workspaceTab` property
        screen = next((o for o in walk(content)
                       if o.property("workspaceTab") is not None), None)
    if screen is None:
        print("FAIL: could not find the MainScreen object")
        return 1
    print(f"  screen objectName={screen.property('objectName')!r}", flush=True)

    pump(50)

    project = os.path.abspath(os.path.join(ROOT, args.project))
    print(f"opening {project}")
    backend.openRecent(project)
    pump(60)
    print(f"  solution={backend.solutionName!r} nodes={len(backend.nodes)} "
          f"connections={len(backend.connections)}")

    # run the flow so the result panes are populated
    try:
        backend.run()
        pump(80)
    except Exception as exc:                        # noqa: BLE001 - reported
        print(f"  runFlow: {type(exc).__name__}: {exc}")

    shot("C0_workspace_loaded.png")

    # --- the three workspace tabs ----------------------------------------
    for index, label in enumerate(("flow", "operation", "multi_flow")):
        try:
            screen.setProperty("workspaceTab", index)
            pump(25)
            shot(f"C1_tab_{index}_{label}.png")
        except Exception as exc:
            print(f"  workspaceTab={index}: {exc}", flush=True)
    screen.setProperty("workspaceTab", 0)
    pump(12)

    # --- the Image | Result pages on the right ----------------------------
    for tab in ("image", "result"):
        try:
            screen.setProperty("viewTab", tab)
            pump(20)
            shot(f"C2_view_{tab}.png")
        except Exception as exc:
            print(f"  viewTab={tab}: {exc}", flush=True)
    screen.setProperty("viewTab", "image")
    pump(10)

    # --- the AI panel -----------------------------------------------------
    for prop in ("aiPanelVisible", "aiVisible", "showAiPanel"):
        if screen.property(prop) is not None:
            try:
                screen.setProperty(prop, True)
                pump(30)
                shot("C3_ai_panel.png")
                screen.setProperty(prop, False)
                pump(10)
                print(f"  AI panel driven through {prop}", flush=True)
            except Exception as exc:
                print(f"  {prop}: {exc}", flush=True)
            break

    # --- dialogs ----------------------------------------------------------
    # The DialogHost has an id (`dialogs`) but no objectName, so it is found by capability:
    # the only item exposing both `show` and `current`.
    host = None
    for obj in walk(content):
        try:
            if obj.property("current") is not None and hasattr(obj, "show"):
                host = obj
                break
        except Exception:
            continue
    if host is not None:
        print(f"  dialog host found (current={host.property('current')!r})", flush=True)
        for dialog in ("newProject", "globalVars", "comm", "flowSettings", "validation",
                       "cameraSet", "lensCal", "plugins", "confirm"):
            try:
                host.show(dialog)
                pump(20)
                if host.property("current") == dialog:
                    shot(f"D_{dialog}.png")
                else:
                    print(f"    {dialog}: did not open "
                          f"(current={host.property('current')!r})", flush=True)
            except Exception as exc:
                print(f"    {dialog}: {type(exc).__name__}: {exc}", flush=True)
        # the message box is opened through a helper rather than by name
        try:
            host.showInfo("Hardware Trigger Settings",
                          "Trigger source, debounce and exposure for the line controller.")
            pump(20)
            shot("D_info.png")
        except Exception as exc:
            print(f"    info: {type(exc).__name__}: {exc}", flush=True)
        # module config and rename need a real node
        try:
            node = backend.nodes[0] if backend.nodes else None
            if node:
                host.showModule(node.get("id", ""), node.get("title", ""))
                pump(20)
                shot("D_moduleConfig.png")
                host.showRename(node.get("id", ""), node.get("title", ""),
                                node.get("tool", ""))
                pump(20)
                shot("D_rename.png")
        except Exception as exc:
            print(f"    moduleConfig/rename: {type(exc).__name__}: {exc}", flush=True)
        try:
            host.close()
        except Exception:
            pass
        pump(10)
    else:
        print("  no dialog host found", flush=True)

    print(f"\nsaved to {OUT}")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
