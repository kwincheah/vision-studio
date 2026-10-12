"""Ad-hoc diagnostics for the VisionMaster-aligned workspace widgets."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
from vm_clone.ui.styles import initialize_app_fonts
initialize_app_fonts(app)

from vm_clone.ui.main_window import VisionMasterMainWindow

win = VisionMasterMainWindow()
win.resize(1600, 950)
win.show()
for _ in range(4):
    app.processEvents()

print("== result panel ==")
tree = win.result_panel.tree
print("top level:", tree.topLevelItemCount())
for i in range(tree.topLevelItemCount()):
    it = tree.topLevelItem(i)
    print(" ", it.text(0), "children:", it.childCount(), "expanded:", it.isExpanded())
print("row_count:", win.result_panel.row_count())
print("column widths:", [tree.columnWidth(c) for c in range(3)])
print("viewport width:", tree.viewport().width())

print("== tool grid ==")
grid = win.tool_grid
print("cells:", grid.count(), "cols:", grid.column_count(),
      "viewport:", grid.viewport().width(), "cell:", grid.CELL_W, grid.CELL_H)

print("== overview ==")
print("cards:", list(win.flow_overview.scene.card_items.keys()))

print("== dock widths ==")
print("tool dock:", win.tool_dock.width(), "property dock:", win.property_dock.width(),
      "central:", win.tab_workspace.width())

print("== result dock ==")
print("bottom dock height:", win.result_dock.height())
