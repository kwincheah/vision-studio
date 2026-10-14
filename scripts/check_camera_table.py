"""Check the camera device table's column sizing at several dialog widths."""
import sys

sys.path.insert(0, ".")
from PyQt6.QtWidgets import QApplication

from vm_clone.ui.styles import initialize_app_fonts

app = QApplication([])
initialize_app_fonts(app)
from vm_clone.ui.camera_dialog import CameraManagementDialog

for size in ((880, 580), (1100, 700), (760, 560), (640, 520)):
    d = CameraManagementDialog()
    d.resize(*size)
    d.show()
    for _ in range(20):
        app.processEvents()
    h = d.table_devices.horizontalHeader()
    widths = [h.sectionSize(i) for i in range(4)]
    vp = d.table_devices.viewport().width()
    print(f"{size[0]}x{size[1]}  cols={widths} sum={sum(widths)} "
          f"viewport={vp} hscroll={d.table_devices.horizontalScrollBar().isVisible()}")
    if size == (880, 580):
        d.grab().save("docs/screenshots/audit/C_camera_set_CameraManagementDialog.png")
    d.close()
    d.deleteLater()
    for _ in range(4):
        app.processEvents()
