"""
Main entry point for Apex Industrial Vision Studio.

    python main.py [solution file]      start the Qt Quick (QML) interface   <- default
    python main.py --widgets [file]     start the classic widget interface
    python main.py --mcp                run the flow-generation MCP server (stdio)
"""
import os
import sys

# OpenCV prints a warning for every camera index it probes when no camera is attached; keep the console for real problems.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")

# Ensure root directory is on Python search path
if getattr(sys, "frozen", False):
    app_root = os.path.dirname(sys.executable)
else:
    app_root = os.path.dirname(os.path.abspath(__file__))
if app_root not in sys.path:
    sys.path.insert(0, app_root)


def run_widgets(argv) -> int:
    """The classic PyQt6 widget interface."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

    from vm_clone.core.logging_setup import setup_logging, install_global_excepthook
    from vm_clone.ui.styles import initialize_app_fonts
    from vm_clone.ui.vm_theme import VM_THEME_QSS
    from vm_clone.ui.main_window import VisionMasterMainWindow

    setup_logging()
    install_global_excepthook()

    # Pass-through high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(argv)
    app.setApplicationName("Apex Industrial Vision Studio")
    app.setOrganizationName("ApexVision")

    # Load system fonts cleanly
    initialize_app_fonts(app)
    # Theme the whole application so parentless dialogs and message boxes match the main window.
    app.setStyleSheet(VM_THEME_QSS)

    win = VisionMasterMainWindow()

    # If project file passed on command line, open directly
    if len(argv) > 1 and os.path.isfile(argv[1]):
        file_path = os.path.abspath(argv[1])
        try:
            sol = win.project_manager.load_project(file_path)
            win.load_solution_manager(sol, filepath=file_path)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            import logging
            logging.getLogger("vm_clone.main").exception(f"Error opening project: {e}")
            QMessageBox.critical(None, "Project Load Error", f"Failed to open project '{file_path}':\n\n{e}")
        win.show()
        return app.exec()

    # Execute startup flow: main window is NOT shown before user finishes opening a project
    if win.run_startup_flow():
        return app.exec()
    return 0


def run_mcp() -> int:
    """MCP server (stdio) for flow generation, for Claude Desktop / Claude Code and other MCP clients."""
    try:
        from vm_clone.flowgen.mcp_server import run
    except ImportError as exc:
        print(f"The MCP server needs the 'mcp' package (pip install mcp): {exc}", file=sys.stderr)
        return 1
    run()
    return 0


def main() -> int:
    if "--mcp" in sys.argv[1:]:
        return run_mcp()
    args = [a for a in sys.argv[1:] if a != "--widgets"]
    if "--widgets" in sys.argv[1:]:
        return run_widgets([sys.argv[0]] + args)
    try:
        from vm_clone.qml_app import run
    except ImportError as exc:                       # Qt Quick not installed: keep the app usable
        print(f"Qt Quick is unavailable ({exc}); starting the widget interface instead.", file=sys.stderr)
        return run_widgets([sys.argv[0]] + args)
    return run([sys.argv[0]] + args)


if __name__ == "__main__":
    sys.exit(main())
