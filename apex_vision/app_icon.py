"""The application icon: window / taskbar icon for both front ends."""
import os
import sys

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
ICON_PNG = os.path.join(ASSETS, "app_icon.png")
ICON_ICO = os.path.join(ASSETS, "app_icon.ico")
APP_ID = "ApexVision.IndustrialVisionStudio"


def load_icon():
    """QIcon of the app icon (empty QIcon when the file is missing)."""
    from PyQt6.QtGui import QIcon
    path = ICON_ICO if sys.platform == "win32" and os.path.isfile(ICON_ICO) else ICON_PNG
    return QIcon(path) if os.path.isfile(path) else QIcon()


def install(app) -> None:
    """Give every window of ``app`` the icon, and (Windows) group the taskbar button under this app rather than python.exe."""
    app.setWindowIcon(load_icon())
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:                                  # cosmetic only
            pass
