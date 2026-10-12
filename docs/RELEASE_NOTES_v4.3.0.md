# Apex Industrial Vision Studio v4.3.0 - Initial Release

We are proud to announce the initial open-source release of **Apex Industrial Vision Studio (v4.3.0)**, a high-performance, modular machine-vision platform and visual flow orchestration environment built with PyQt6, OpenCV, and modern Python.

---

## 🚀 Key Highlights & Features

- **Visual Node Flow Canvas:** Interactive graph editor for designing multi-stage industrial inspection pipelines with live execution metrics, real-time node validation, and auto-hierarchical layout.
- **Multi-Flow Orchestration:** Run concurrent, isolated inspection flows with shared global variables (up to 32 variables) and dependency triggers.
- **Hikrobot MVS Camera Integration:** Direct compatibility with Hikrobot MVS industrial cameras via native SDK bindings (`MvCameraControl.dll` / `libMvCameraControl.so`) with live frame acquisition and auto-discovery.
- **Camera Lens Distortion Calibration:** Full camera calibration wizard supporting OpenCV Zhang chessboard calibration, sub-pixel corner refinement, radial/tangential distortion correction ($k_1, k_2, k_3, p_1, p_2$), and real-time undistortion preview.
- **Dynamic Plugin Ecosystem:** Stable SDK (`vm_clone.sdk`) allowing third-party engineers to build custom vision tools without modifying the core application.
- **Integrated Plugin Marketplace:** In-app catalog, GitHub direct installer, and automated plugin generator/packager.
- **Industrial Splitter Workspace:** Pixel-accurate layout metrics featuring an integrated Left Tool Box, central multi-view canvas (Flow, Operation Interface, Multi-Flow Overview), and right-hand Image Display & Module Results table.
- **Startup Welcome Hub:** Dedicated project manager supporting project templates (PCB Inspection, Precision Measurement, YOLOv11 Object Detection, Robot Coordinate Calibration) and recent solution tracking.

---

## 📦 Downloads & Installation

### Option 1: Standalone Windows Installer (`.exe`)
Download **`ApexVisionStudio_Setup_v4.3.0.exe`** from the Assets below:
1. Run the setup installer wizard.
2. Select your destination directory (defaults to `C:\Program Files\Apex Industrial Vision Studio`).
3. Launch from the Start Menu or Desktop shortcut.
*No Python installation required.*

### Option 2: Portable Standalone ZIP (`.zip`)
Download **`ApexVisionStudio-v4.3.0-Windows-x64.zip`**:
1. Extract the ZIP archive anywhere on your machine.
2. Double-click `ApexVisionStudio.exe` to launch.
*Runs completely standalone without administrator privileges.*

### Option 3: From Source (Cross-Platform: Windows, Linux, macOS)
```bash
git clone https://github.com/apexvision/vision-studio.git
cd vision-studio
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

---

## 🛡️ Security & Integrity

- **SHA-256 Checksums:**
  - `ApexVisionStudio_Setup_v4.3.0.exe`: *(Generated upon release build)*
  - `ApexVisionStudio-v4.3.0-Windows-x64.zip`: *(Generated upon release build)*
- Scanned with automated secret detection: **Zero credentials, tokens, or proprietary vendor assets committed.**
- Verified across **228 automated unit, UI, and integration tests with a 100% pass rate.**
