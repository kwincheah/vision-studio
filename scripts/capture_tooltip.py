"""Capture the QToolTip popup so its surface can be inspected.

Qt shows tooltips in their own top-level window, so a window grab does not include
them.  This raises one, finds the `QTipLabel` top-level, and grabs that.
"""
import os
import sys

sys.path.insert(0, ".")
from PyQt6.QtWidgets import QApplication, QToolTip
from PyQt6.QtCore import QPoint

from vm_clone.ui.styles import initialize_app_fonts

OUT = os.path.join("docs", "screenshots", "audit")

app = QApplication([])
initialize_app_fonts(app)
from vm_clone.ui.main_window import VisionMasterMainWindow

win = VisionMasterMainWindow()
win.resize(1400, 760)
win.show()
for _ in range(24):
    app.processEvents()

# A tooltip long enough to show the wrapped layout.
QToolTip.showText(win.mapToGlobal(QPoint(320, 320)),
                  "Once - execute the active flow a single time", win)
for _ in range(10):
    app.processEvents()

found = False
for w in app.topLevelWidgets():
    cls = w.metaObject().className()
    if cls in ("QTipLabel", "QLabel") and w.isVisible() and w.windowFlags() & 0xFFFF:
        name = os.path.join(OUT, "90_tooltip.png")
        w.grab().save(name)
        print(f"captured {cls} -> {name} {w.width()}x{w.height()}")
        found = True
        break
if not found:
    names = [w.metaObject().className() for w in app.topLevelWidgets() if w.isVisible()]
    print("no tip label found; visible top-levels:", names)

win.close()
