"""Measure the two cramped widgets after the alignment fix.

Run:  python scripts/audit_alignment.py
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

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

# the real solution's flow name, which is what exposed the elision
win.solution.flows["PCB_AOI_Solution"] = win.solution.flows.pop("Flow1")
win.solution.active_flow_name = "PCB_AOI_Solution"
win._refresh_flow_tabs()
win.run_pipeline_step()
for _ in range(14):
    app.processEvents()

bar = win.flow_tab_bar
print(f"flow tab bar: width={bar.width()}  minimumWidth={bar.minimumWidth()}  "
      f"maximumWidth={bar.maximumWidth()}  tabs={bar.count()}")
ok = True
for i in range(bar.count()):
    rect = bar.tabRect(i)
    text = bar.tabText(i)
    fm = QFontMetrics(bar.font())
    button = bar.tabButton(i, bar.ButtonPosition.RightSide)
    close = button.sizeHint().width() if button is not None else 0
    # what Qt needs to draw the label without eliding: the glyphs, the stylesheet's
    # horizontal padding (sp_snug each side), the tab's right margin, the close button,
    # and the 1px border on each side
    needed = fm.horizontalAdvance(text) + 2 * 6 + 2 + close + 2 + 2
    slack = rect.width() - needed
    status = "ok" if slack >= 0 else "ELIDED"
    if slack < 0:
        ok = False
    print(f"  tab {i}: {text!r}")
    print(f"          rendered={rect.width()}px  text={fm.horizontalAdvance(text)}px  "
          f"needs={needed}px  slack={slack:+d}px  {status}")

print()
grid = win.toolbox.flyout.grid
win.toolbox._on_category("Defect Detection")
for _ in range(10):
    app.processEvents()
fm = QFontMetrics(grid.font())
print(f"tool grid: font={grid.font().pixelSize()}px lineSpacing={fm.lineSpacing()} "
      f"cell={grid.gridSize().width()}x{grid.gridSize().height()} "
      f"icon={grid.iconSize().height()}")
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
    slack = rect.height() - needed
    status = "ok" if slack >= 0 else "OVERFLOWS"
    if slack < 0:
        ok = False
    print(f"  {text!r:24s} lines={lines} rendered={rect.height()}px "
          f"needs={needed}px slack={slack:+d}px  {status}")

print()
print("RESULT:", "all elements fit" if ok else "still cramped")
win.close()
sys.exit(0 if ok else 1)
