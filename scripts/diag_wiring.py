"""Debug helper: inspect lock/undo/histogram wiring on the main window."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
from vm_clone.ui.styles import initialize_app_fonts
initialize_app_fonts(app)
from vm_clone.ui.main_window import VisionMasterMainWindow

win = VisionMasterMainWindow()
win.resize(1600, 950)
win.show()
for _ in range(3):
    app.processEvents()

print("lock checkable:", win.btn_lock.isCheckable())
print("lock receivers:", win.btn_lock.receivers(win.btn_lock.clicked))
win.btn_lock.setChecked(True)
app.processEvents()
print("after setChecked -> scene locked:", win.flow_scene.is_locked())
win.btn_lock.click()
app.processEvents()
print("after click -> scene locked:", win.flow_scene.is_locked())

print()
print("undo stack before add:", win.flow_scene.undo_stack.count(), win.flow_scene.undo_stack.undoText())
before = len(win.pipeline.nodes)
win.on_add_tool_by_name("Image Filter")
print("after add:", len(win.pipeline.nodes), "undo count:", win.flow_scene.undo_stack.count(),
      "text:", win.flow_scene.undo_stack.undoText())
win.on_undo()
print("after undo:", len(win.pipeline.nodes))

print()
win.btn_hist.setChecked(True)
app.processEvents()
print("hist button checked:", win.btn_hist.isChecked(), "canvas show_hist:", win.image_canvas._show_hist)

print()
win.btn_continuous.setChecked(True)
print("continuous:", win.btn_continuous.isChecked(), "loop:", win.btn_loop_flow.isChecked(),
      "timer:", win.run_timer.isActive())
