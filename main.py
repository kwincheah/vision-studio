"""
Main entry point for Apex Industrial Vision Studio application.
"""
import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Ensure root directory is on Python search path
if getattr(sys, "frozen", False):
    app_root = os.path.dirname(sys.executable)
else:
    app_root = os.path.dirname(os.path.abspath(__file__))
if app_root not in sys.path:
    sys.path.insert(0, app_root)

from vm_clone.core.logging_setup import setup_logging, install_global_excepthook
from vm_clone.ui.styles import initialize_app_fonts
from vm_clone.ui.main_window import VisionMasterMainWindow


def main():
    setup_logging()
    install_global_excepthook()

    # Pass-through high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Apex Industrial Vision Studio")
    app.setOrganizationName("ApexVision")

    # Load system fonts cleanly
    initialize_app_fonts(app)

    win = VisionMasterMainWindow()

    # If project file passed on command line, open directly
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        file_path = os.path.abspath(sys.argv[1])
        try:
            sol = win.project_manager.load_project(file_path)
            win.load_solution_manager(sol, filepath=file_path)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            import logging
            logging.getLogger("vm_clone.main").exception(f"Error opening project: {e}")
            QMessageBox.critical(None, "Project Load Error", f"Failed to open project '{file_path}':\n\n{e}")
        win.show()
        sys.exit(app.exec())

    # Execute startup flow: main window is NOT shown before user finishes opening a project
    should_run = win.run_startup_flow()
    if should_run:
        sys.exit(app.exec())
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
