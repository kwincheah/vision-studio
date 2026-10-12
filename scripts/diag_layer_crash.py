"""Bisect the layer-switch test crash by printing after every step."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
from vm_clone.ui.styles import initialize_app_fonts
initialize_app_fonts(app)
from vm_clone.ui.main_window import VisionMasterMainWindow


def step(msg):
    print(msg, flush=True)


win = VisionMasterMainWindow()
win.resize(1400, 900)
step("1 window created")

win.act_layer_metrics.setChecked(False)
step(f"2 metrics off -> {win.image_canvas._show_measurements}")

win.act_layer_rois.setChecked(False)
step(f"3 rois off -> {win.image_canvas._show_rois}")

win.act_layer_all.setChecked(False)
step(f"4 all off -> {win.image_canvas._show_overlays}")

win.act_layer_all.setChecked(True)
step("5 all on")
win.act_layer_rois.setChecked(True)
step("6 rois on")
win.act_layer_metrics.setChecked(True)
step("7 metrics on")

win.close()
step("8 closed")
win.deleteLater()
step("9 deleteLater")
app.processEvents()
step("10 processed")
step("done")
