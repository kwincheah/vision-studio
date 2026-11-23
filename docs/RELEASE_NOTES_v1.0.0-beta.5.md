# Apex Industrial Vision Studio 1.0.0-beta.5

A public beta of **Apex Industrial Vision Studio**: a desktop tool and headless SDK for building machine-vision inspections and multi-camera video analytics by wiring modules together on a canvas, or by describing the inspection to an AI assistant that builds the flow for you.

This is a **beta**. Expect rough edges, and please report them.

---

## What changed since beta.4

### New — Hybrid C++17 Native Core (`_apex_core`)
- Added an optional C++17 `pybind11` native accelerator (`cpp/`, `build_cpp.py`, `apex_vision/core/_native.py`) providing GIL-free topological flow sorting, caliper 1D projection & peak finding, fast pixel counting, and native ring-buffer JPEG encoding.
- Automatically falls back to pure Python/NumPy when the compiled extension is absent.

### New — Headless Multi-Stream SDK Runtime (`apex_vision.sdk`)
- **`ApexRuntimeEngine` & `ApexStreamWorker`**: Run any `.apex` solution across multiple concurrent RTSP/MP4 camera streams with cross-camera dynamic ONNX micro-batching (`SharedModelRegistry` & `DynamicBatchScheduler`), hot-reloadable ROI zones, per-stream ring buffers, and live MJPEG streaming.
- **Per-Layer Live Overlays & Anti-Aliased Badges**: Toggle individual overlay layers (`shelf`, `aisle`, `pose`, `botsort`, `bags`, `motion`) with cached TrueType (`Segoe UI Semibold`) pill badges.

### New — Theft Recognition Plugin (`plugins/theft_recognition_plugin`)
- 6 custom vision modules for retail multi-stream CCTV behavioral analytics:
  - **ROI Zone Manager (`TheftZoneManagerTool`)**
  - **Motion Gate (`TheftMotionGateTool`)**
  - **YOLO11n Pose Estimation (`TheftYoloPoseTool`)**
  - **Context Object Detector (`TheftBagDetectorTool`)**
  - **BoT-SORT Multi-Object Tracker (`TheftBotSortTool`)**
  - **Dual-Trigger Behavior Gate (`TheftBehaviorGateTool`)**
  - **Async Cloud/Local VLM Verifier (`TheftVlmModuleTool`)**

### Fixed — 23 Core, Camera, Server & UI/QML Bugs
- **Camera & RTSP reliability**: Fixed `OpenCVCameraDriver.capture_frame` `stream_url` crash on disconnect, added bounded 3-second RTSP open/read timeouts, and replaced hardcoded `"opencv_rtsp"` driver IDs with URL-hashed IDs so multiple RTSP streams run simultaneously without collision.
- **5-channel & Arbitrary-channel Image Robustness**: Fixed crashes across `overlays.py` (`draw_overlays`) and all theft recognition plugin tools when processing >4-channel NumPy tensors.
- **Pipeline & HTTP Server**: Fixed `Flow.reset_counts` synchronization, hex colour `#RRGGBB` parsing in `overlays.py`, `Image Output` relative paths, `/inspect` HTTP multipart collision on duplicate `"image"` form fields, and `catalog.py` doc path generation.
- **Qt Quick / QML Polish**: Fixed `DataTable` stale rows on project switch, `ToolFlyout` Escape/focus handling, `ModuleConfigDialog` dirty state tracking, `SelectBox` overflow clipping, and added a scrollable `ToolCategoryRail` when window height is compact.

---

## Install

**Windows installer.** Download `ApexVisionStudio_Setup_v1.0.0-beta.5.exe` from the assets below and run it.

**Portable ZIP.** Download `ApexVisionStudio-v1.0.0-beta.5-Windows-x64.zip`, extract it anywhere and run `ApexVisionStudio.exe`. No administrator rights or Python needed.

**From source** (Windows, Linux, macOS):

```bash
git clone https://github.com/kwincheah/vision-studio.git
cd vision-studio
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

New here? Start with the [User guide](https://github.com/kwincheah/vision-studio/blob/main/docs/USER_GUIDE.md).

## Feedback

Please open an issue at <https://github.com/kwincheah/vision-studio/issues> and include the app version (shown in the title bar and under Help, About), your OS and, if possible, the project file.
