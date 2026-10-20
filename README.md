# Apex Industrial Vision Studio

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-brightgreen.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](https://github.com/kwincheah/vision-studio)

**Apex Industrial Vision Studio** is an open-source, modular industrial machine-vision platform and visual flow orchestration studio built with **Python 3.12, PyQt6, OpenCV, and NumPy**. It provides an intuitive, node-based workflow environment for designing, calibrating, and executing high-speed automated optical inspection (AOI) pipelines.

## 🎨 Visual design

The interface is a **light industrial theme whose palette is measured from official
KEYENCE manual screenshots**, not chosen by eye: steel-grey chrome (`#646c6c` toolbar,
`#848c94` menus), near-white panels (`#ecf0f0`), a light canvas (`#b4b8c0`) with white
module cards, a dark image viewport (`#201c20`), and the signature **amber selection**
(`#e4b030`). Green / red / orange stay functional signals for run, fail and caution.

Chrome, amber selection, viewport and panel tones match their measured reference values
at **ΔE 0.0**. See [docs/KEYENCE_DESIGN_SPEC.md](docs/KEYENCE_DESIGN_SPEC.md) for the
sampled evidence and [docs/screenshots/keyence_comparison.png](docs/screenshots/keyence_comparison.png)
for the side-by-side.

---

## 🌟 Key Capabilities

- **AI Gen** (toolbar, Ctrl+G): describe an inspection in plain words and an assistant builds the flow from the built-in module reference, validating its own work. Works with your own API key (Claude, OpenAI, Gemini, Mistral, DeepSeek, xAI, Groq, OpenRouter, or a local Ollama / LM Studio model); also available as an MCP server (`python main.py --mcp`). See [docs/AI_GEN.md](docs/AI_GEN.md).

### 1. Visual Flow Diagram Engine
- **Node-Based DAG Orchestration:** Connect vision modules with typed ports (`Image`, `ROI`, `Number`, `String`, `Datum`) and orthogonal wire routing.
- **Hierarchical Auto-Layout:** One-click automated graph layout for clean, legible multi-stage inspection topologies.
- **Continuous & Single-Shot Execution:** Asynchronous non-blocking loop execution with millisecond timing diagnostics.
- **Multi-Flow Architecture:** Manage and execute isolated concurrent inspection sub-flows with a unified dependency bus.

### 2. Industrial Camera & Hardware Support
- **Hikrobot MVS SDK Integration:** Direct compatibility with Hikrobot Gigabit Ethernet and USB 3.0 Vision industrial cameras (`MvCameraControl.dll` / `libMvCameraControl.so`).
- **Live Discovery & Stream Acquisition:** Auto-detect connected cameras, configure gain/exposure, and stream frames directly into inspection flows.
- **Image Source Fail-Safe:** Seamless fallback to synthetic image generators or paged file datasets for offline development.

### 3. Camera Lens Distortion Calibration
- **OpenCV Zhang Calibration:** Integrated calibration wizard supporting standard chessboard targets with sub-pixel corner extraction.
- **Full Distortion Correction:** Calculates camera intrinsic matrix and 5-parameter distortion coefficients ($k_1, k_2, k_3, p_1, p_2$).
- **Live Undistortion Preview:** Interactive side-by-side comparison of raw vs undistorted camera streams with RMS reprojection error reporting.

### 4. Dynamic Plugin Ecosystem & Marketplace
- **Stable Plugin SDK (`vm_clone.sdk`):** Build custom vision tools in isolated packages without modifying application source code.
- **Exception Containment:** Untrusted third-party plugins run with timeout supervision and isolated exception boundaries.
- **In-App Marketplace & GitHub Installer:** Discover curated community plugins, download directly from GitHub repositories, or scaffold new plugins with one click.

### 5. Industrial Splitter Workspace
- **Left Tool Box:** Flush, permanent 42 px category glyph rail and 3-column expandable tool grid flyout.
- **Central Workspace:** Switch between Flow Diagram, Operation Interface (layer toggles & formatting), and Multi-Flow Overview.
- **Right Inspector & Results:** Upper Image Viewport (interactive zoom, pan, ROI editing, histogram HUD) over live tabular output metrics.
- **Start Page Welcome Hub:** Project template scaffolding (PCB Inspection, Precision Measurement, YOLOv11 Object Detection, Robot Calibration) and recent solution tracking.

---

## 🚀 Quick Start

### For End Users (Standalone Windows Application)
Download the latest pre-built release from [Releases](https://github.com/kwincheah/vision-studio/releases):
- **Installer:** Download `ApexVisionStudio_Setup_v4.3.0.exe` and follow the setup wizard.
- **Portable ZIP:** Download `ApexVisionStudio-v4.3.0-Windows-x64.zip`, extract, and launch `ApexVisionStudio.exe`.
*No Python or compiler installation required.*

---

### For Developers (Running from Source)

#### 1. Clone the Repository
```bash
git clone https://github.com/kwincheah/vision-studio.git
cd vision-studio
```

#### 2. Set Up Virtual Environment
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate
```

#### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 4. Launch the Studio
```bash
python main.py
```

---

## 🧪 Testing & Verification

The codebase includes an extensive automated test suite covering algorithm correctness, UI layouts, plugin lifecycles, and edge cases.

```bash
# Install development & test dependencies
pip install -r requirements-dev.txt

# Run all 1,300+ automated tests
python -m pytest tests/ -v

# Run secrets and security scan
python scripts/check_secrets.py
```

---

## 📦 Packaging as a Desktop Application

The repository includes reproducible build configurations using PyInstaller and Inno Setup:

```bash
# 1. Build standalone executable directory (dist/ApexVisionStudio/)
pyinstaller ApexVisionStudio.spec --clean --noconfirm

# 2. Compile Windows setup wizard (requires Inno Setup 6)
iscc installer_setup.iss
```
For full details, cross-platform packaging, and code signing, see the [Desktop Packaging Guide](docs/PLUGIN_DEVELOPMENT_GUIDE.md).

---

## 🧩 Developing Custom Plugins

Third-party developers can extend the studio by adding vision tools to `./plugins/` or `~/.apex_vision/plugins/`:

```python
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus
from vm_clone.sdk import IVisionPlugin, PluginMetadata

class MyCustomFilterTool(VisionToolBase):
    tool_name = "My Custom Filter"
    category = "Image Processing"

    def execute(self, inputs):
        img = inputs.get("image")
        # Custom OpenCV algorithm...
        return ToolExecutionResult(status=ToolStatus.SUCCESS, outputs={"image": img})
```

See the full [Plugin Development Guide](docs/PLUGIN_DEVELOPMENT_GUIDE.md) for complete instructions.

---

## 📁 Repository Structure

```text
├── .github/              # GitHub Actions CI/CD workflows and issue templates
├── docs/                 # Documentation, specifications, and architecture guides
│   ├── KEYENCE_DESIGN_SPEC.md          # measured palette + verification + gaps
│   ├── VISIONMASTER_STORYBOARD.md      # 分镜 layout breakdown (measured geometry)
│   ├── VISIONMASTER_REFERENCE_SPEC.md  # vendor region map + gap status
│   ├── PLUGIN_DEVELOPMENT_GUIDE.md
│   ├── RELEASE_NOTES_v4.3.0.md
│   └── ...
├── qml/                  # Qt Quick interface (what python main.py starts); open qml/ApexVision.qmlproject in Qt Design Studio
├── plugins/              # Bundled sample plugins (e.g. Sobel edge detector)
├── projects/             # Built-in solution templates (.vmp)
├── scripts/              # Verification, secret scanning, and UI measurement utilities
├── tests/                # Automated pytest suite (1,300+ tests across 58 files)
├── vm_clone/             # Core application package
│   ├── core/             # DAG pipeline, registry, project manager, MVS camera SDK
│   ├── sdk/              # Plugin SDK interfaces, manager, marketplace
│   ├── tools/            # 42 built-in vision tools across 11 categories
│   └── ui/               # PyQt6 interface: main window, canvas, docks, themes
├── ApexVisionStudio.spec # PyInstaller standalone build configuration
├── installer_setup.iss   # Inno Setup Windows installer script
├── LICENSE               # MIT License
├── main.py               # Application entry point
├── pyproject.toml        # PEP 517/621 packaging metadata
├── requirements.txt      # Core runtime dependencies
└── requirements-dev.txt  # Testing and packaging dependencies
```

---

## 🔒 Security & Data Privacy

- **User Data Isolation:** User projects (`Documents/ApexVision/Projects`), settings (`Windows Registry` / `~/.apex_vision`), and installed plugins are stored separately from application installation directories.
- **Zero Secrets Policy:** Automated CI scanner verifies zero embedded API keys, credentials, or private keys.
- **License & Legal:** Released under the [MIT License](LICENSE). Third-party trademarks and reference manuals are the property of their respective owners.
