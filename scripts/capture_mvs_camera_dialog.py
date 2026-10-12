"""
Capture high-resolution screenshot of CameraManagementDialog displaying:
1. Hikrobot MVS C SDK status badge in header
2. Enumerated Hikrobot MVS cameras in the device table
3. MVS configuration buttons (Import/Export .mvs)
4. Active live preview with MVS camera telemetry
"""
import sys
import os
import time

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from vm_clone.ui.camera_dialog import CameraManagementDialog

def capture_mvs_dialog():
    os.environ["PYTEST_CURRENT_TEST"] = "1"
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    dialog = CameraManagementDialog(current_device_id="mvs_gige_0")
    dialog.resize(920, 600)

    # Select the MVS camera in the table
    for r in range(dialog.table_devices.rowCount()):
        item = dialog.table_devices.item(r, 0)
        if item and "mvs_gige_0" in item.data(Qt.ItemDataRole.UserRole):
            dialog.table_devices.selectRow(r)
            break

    # Trigger one preview tick to render live MVS frame into label
    dialog._start_preview()
    dialog._on_preview_tick()

    dialog.show()
    app.processEvents()

    pixmap = dialog.grab()
    out_dir = r"C:\Users\winch\.gemini\antigravity\brain\7d3601f0-70b1-4ca6-8295-7780bcda97be"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "mvs_camera_management_dialog.png")
    pixmap.save(out_path)
    print(f"Saved MVS camera management screenshot to: {out_path}")
    dialog.deleteLater()

if __name__ == "__main__":
    capture_mvs_dialog()
