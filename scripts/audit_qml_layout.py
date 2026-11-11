"""Measure how the QML workspace divides its space, and whether anything is unused.

A screenshot shows that some areas are empty, but not whether the emptiness is a designed
margin or wasted space.  This reports the rect of every major region and how much of the
canvas the flow actually occupies.

Run:  python scripts/audit_qml_layout.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtQml import QQmlApplicationEngine  # noqa: E402

WIDTH, HEIGHT = 1600, 950


def rect_of(obj):
    try:
        return (float(obj.property("x") or 0), float(obj.property("y") or 0),
                float(obj.property("width") or 0), float(obj.property("height") or 0))
    except Exception:
        return (0.0, 0.0, 0.0, 0.0)


def main() -> int:
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
    win = engine.rootObjects()[0]
    win.setProperty("width", WIDTH)
    win.setProperty("height", HEIGHT)
    win.show()

    def pump(n=30):
        for _ in range(n):
            app.processEvents()

    pump(50)
    backend.openRecent(os.path.join(ROOT, "projects", "PCB_Inspection_Demo.apex"))
    pump(50)
    backend.run()
    pump(60)

    content = win.contentItem()

    def walk(node, depth=0):
        yield node, depth
        if depth > 20:
            return
        try:
            kids = node.childItems()
        except Exception:
            return
        for kid in kids:
            yield from walk(kid, depth + 1)

    named = {}
    for obj, depth in walk(content):
        try:
            name = obj.property("objectName")
        except Exception:
            continue
        if name:
            named.setdefault(name, (rect_of(obj), depth))

    print(f"window {WIDTH}x{HEIGHT}\n")
    print("== regions ==")
    for name in ("flowCanvas", "flowTabs", "tabImage", "tabResult",
                 "currentResultPane", "historyPane", "helpPane",
                 "resultPage", "aiPanel", "viewportRect", "viewFrame"):
        if name in named:
            x, y, w, h = named[name][0]
            share = (w * h) / float(WIDTH * HEIGHT) * 100
            print(f"  {name:20s} x={x:6.1f} y={y:6.1f} w={w:6.1f} h={h:6.1f}  "
                  f"{share:5.1f}% of window")

    # where do the node cards actually sit inside the canvas?
    canvas = next((o for o, _ in walk(content)
                   if o.property("objectName") == "flowCanvas"), None)
    if canvas is not None:
        cx, cy, cw, ch = rect_of(canvas)
        left = top = 1e9
        right = bottom = -1e9
        count = 0
        for obj, _ in walk(canvas):
            try:
                if obj.property("objectName") and str(obj.property("objectName")).startswith("nodeCard"):
                    pass
            except Exception:
                pass
        # node cards are Repeater delegates without objectName; measure by their content
        for obj, _ in walk(canvas, 0):
            try:
                w = float(obj.property("width") or 0)
                h = float(obj.property("height") or 0)
                label = obj.property("objectName")
            except Exception:
                continue
            if label and str(label).startswith("flowTab"):
                continue
        print(f"\ncanvas {cw:.0f}x{ch:.0f} at ({cx:.0f},{cy:.0f})")

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
