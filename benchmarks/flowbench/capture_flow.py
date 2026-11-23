"""Open a flow spec in Apex Vision Studio (offscreen QML) and screenshot the workspace.

Uses the app's own flowgen.build_solution, so what you see is exactly what the grader built.
Also writes the solution XML next to the PNG, so the flow can be opened in the real app.
Run with Vision Studio's Python:  python capture_flow.py <spec.json> <out.png> [WxH]
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)


def main() -> int:
    spec_path, out = sys.argv[1], os.path.abspath(sys.argv[2])
    width, height = (int(v) for v in (sys.argv[3] if len(sys.argv) > 3 else "1600x950").split("x"))
    spec = json.load(open(spec_path, encoding="utf-8"))

    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine

    from apex_vision.flowgen.spec import build_solution
    from apex_vision.qml_backend import AppBackend, FrameProvider
    from apex_vision.qml_services import install_services

    solution, issues = build_solution(spec)
    if solution is None:
        print("FAIL: spec does not build:", [i.get("code") for i in issues])
        return 1
    with open(out[:-4] + ".xml", "w", encoding="utf-8") as f:
        f.write(solution.to_xml())

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

    def pump(n):
        for _ in range(n):
            app.processEvents()

    pump(50)
    backend.load_solution(solution, None)
    pump(60)
    try:
        backend.run()
    except Exception as exc:  # noqa: BLE001 - reported, screenshot still useful
        print(f"run: {type(exc).__name__}: {exc}")
    import time
    deadline = time.time() + 20  # let the run finish so the canvas shows final PASS/FAIL, not RUNNING
    while time.time() < deadline:
        pump(20)
        time.sleep(0.1)
    img = win.grabWindow()
    img.save(out)
    print(f"saved {out} {img.width()}x{img.height()} nodes={len(backend.nodes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
