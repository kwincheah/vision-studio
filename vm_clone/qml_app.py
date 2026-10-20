"""Application entry for the QML user interface (what ``main.py`` starts)."""
import logging
import os
import sys
from typing import List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logger = logging.getLogger("vm_clone.qml_app")


def run(argv: Optional[List[str]] = None) -> int:
    """Start the QML application. ``argv[1]`` may be a solution file to open directly."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine

    from vm_clone.core.logging_setup import install_global_excepthook, setup_logging
    from vm_clone.qml_backend import AppBackend, FrameProvider
    from vm_clone.qml_services import install_services

    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    install_global_excepthook()

    app = QGuiApplication(argv)
    app.setApplicationName("Apex Industrial Vision Studio")
    app.setOrganizationName("ApexVision")
    from vm_clone.app_icon import install as install_icon
    install_icon(app)

    engine = QQmlApplicationEngine()
    provider = FrameProvider()
    engine.addImageProvider("frame", provider)
    engine._provider = provider                      # keep a Python reference for set_array()
    backend = AppBackend(provider)
    engine.rootContext().setContextProperty("appBackend", backend)
    engine._services = install_services(engine, backend)   # lens, camera, plugins, inspection
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    if not engine.rootObjects():
        logger.error("The QML interface failed to load")
        return 1

    def release_hardware():
        try:
            engine._services["appCamera"].shutdown()
            from vm_clone.core.camera_manager import CameraManager
            if CameraManager._instance is not None:
                CameraManager._instance.close_all()
        except Exception as exc:                     # never block the exit
            logger.warning("Error releasing cameras during exit: %s", exc)

    app.aboutToQuit.connect(release_hardware)
    backend.closeApproved.connect(app.quit)

    quit_after = os.environ.get("APEX_AUTOQUIT_MS")        # test hook: leave the event loop after N ms
    if quit_after and quit_after.isdigit():
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(int(quit_after), app.quit)

    target = next((a for a in argv[1:] if os.path.isfile(a)), None)
    backend.startup(os.path.abspath(target) if target else None)
    return app.exec()
