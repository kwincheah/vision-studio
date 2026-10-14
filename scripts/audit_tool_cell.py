"""Measure the tool grid cell: font, line count and required height.

Run:  python scripts/audit_tool_cell.py
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication

from vm_clone.ui.styles import initialize_app_fonts

app = QApplication([])
initialize_app_fonts(app)

from vm_clone.ui.main_window import VisionMasterMainWindow

win = VisionMasterMainWindow()
win.resize(1400, 760)
win.show()
for _ in range(30):
    app.processEvents()

def audit_category(name: str) -> None:
    win.toolbox._on_category(name)
    for _ in range(10):
        app.processEvents()
    grid = win.toolbox.flyout.grid
    # Measure at the size the cell is actually rendered at: `item.font()` is the model's
    # font, not the view's, and the view applies the stylesheet.
    font = grid.font()
    fm = QFontMetrics(font)
    print(f"\n== {name} ==  grid={grid.gridSize().width()}x{grid.gridSize().height()} "
          f"icon={grid.iconSize().height()}  rendered font={font.pixelSize()}px "
          f"lineSpacing={fm.lineSpacing()}")
    for i in range(grid.count()):
        item = grid.item(i)
        rect = grid.visualItemRect(item)
        text = item.text()
        inner = grid.gridSize().width() - 8
        lines, current = 1, ""
        for word in text.split():
            candidate = (current + " " + word).strip()
            if fm.horizontalAdvance(candidate) <= inner or not current:
                current = candidate
            else:
                lines += 1
                current = word
        needed = grid.iconSize().height() + 4 + lines * fm.lineSpacing() + 6
        mark = "   <-- TEXT HITS THE BOTTOM" if needed > rect.height() else ""
        print(f"  {text!r:26s} cell={rect.width()}x{rect.height()} lines={lines} "
              f"need~{needed}px{mark}")


audit_category("Recognition")
audit_category("Defect Detection")
audit_category("Location")
win.close()

