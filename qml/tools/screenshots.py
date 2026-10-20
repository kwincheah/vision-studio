"""Render every QML screen and dialog to docs/screenshots/qml (live backend, real demo project).

    python qml/tools/screenshots.py
"""
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
OUT = os.path.join(ROOT, "docs", "screenshots", "qml")
os.makedirs(OUT, exist_ok=True)

from PyQt6.QtCore import Q_ARG, QMetaObject, QTimer, QUrl, Qt, QVariant
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickItem

from vm_clone.qml_backend import AppBackend, FrameProvider
from vm_clone.qml_services import install_services

DIALOGS = ["globalVars", "flowSettings", "validation", "cameraSet", "lensCal", "plugins", "newProject"]


def main() -> int:
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    provider = FrameProvider()
    engine.addImageProvider("frame", provider)
    backend = AppBackend(provider)
    engine.rootContext().setContextProperty("appBackend", backend)
    services = install_services(engine, backend)
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    if not engine.rootObjects():
        print("QML failed to load")
        return 1
    window = engine.rootObjects()[0]
    backend.openRecent(os.path.join(ROOT, "projects", "PCB_Inspection_Demo.vmp"))

    def pump(n=15):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.02)

    def find(cls):
        return [c for c in window.findChildren(QQuickItem) if c.metaObject().className().startswith(cls)][0]

    def run():
        pump(40)
        main, host = find("MainScreen"), find("DialogHost")

        def shot(name):
            pump(12)
            window.grabWindow().save(os.path.join(OUT, f"{name}.png"))
            print("  ", name)

        shot("main_live")
        for key in DIALOGS:
            host.setProperty("current", key)
            shot(f"dialog_{key}")
        QMetaObject.invokeMethod(host, "showModule", Qt.ConnectionType.DirectConnection,
                                 Q_ARG(QVariant, "x"), Q_ARG(QVariant, "02 IC Alignment"))
        shot("dialog_moduleConfig")
        host.setProperty("current", "")
        for tab in range(5):
            main.setProperty("inspectionTab", tab)
            main.setProperty("inspectionVisible", True)
            shot(f"inspection_{tab}")
        main.setProperty("inspectionVisible", False)
        main.setProperty("railCategory", 1)
        shot("tool_flyout")
        main.setProperty("railCategory", -1)
        for tab, name in enumerate(["flow", "operation", "multiflow"]):
            main.setProperty("workspaceTab", tab)
            shot(f"workspace_{name}")
        print("\n".join(sorted(set(warnings))) or "no QML warnings")
        print(f"saved to {OUT}")
        app.exit(1 if warnings else 0)

    QTimer.singleShot(2500, run)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
