<p align="center"><img src="apex_vision/assets/app_icon.png" alt="Apex Industrial Vision Studio" width="112"></p>

<h1 align="center">Apex Industrial Vision Studio</h1>

<p align="center">
Build machine-vision inspections by wiring blocks together, or just describe the inspection and let an AI assistant wire them for you.
</p>

<p align="center">
<a href="https://github.com/kwincheah/vision-studio/actions/workflows/ci.yml"><img src="https://github.com/kwincheah/vision-studio/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
<img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-brightgreen.svg" alt="Python 3.10-3.12">
<img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg" alt="Platform">
</p>

![The flow editor: modules wired together on the left, the live image and per-module results on the right](docs/screenshots/qml/workspace_flow.png)

## What is this?

Apex Vision Studio is a desktop app for designing automated optical inspections: check a PCB for scratches, measure a width
to the pixel, read a serial number, count parts on a tray, send a pass/fail to a PLC. You build each inspection as a **flow**
of small modules (acquire an image, find a feature, measure it, judge the result) and press Run. Nothing to compile, no
script to write unless you want one.

It is written in Python with Qt Quick, OpenCV and NumPy. It runs on Windows, Linux and macOS, talks to Hikrobot industrial
cameras, and works fine with no camera at all (there are synthetic test images and image folders for that).

## A quick tour

**Start with a template or an empty flow.** The start page offers sample solutions (PCB inspection, precision measurement,
YOLO object detection, robot calibration) and remembers your recent projects.

![Start page](docs/screenshots/qml/start_page.png)

**Wire modules together.** Drag from an output port to an input port. Wires are curves coloured by data type. While you
drag, the ports that can take the wire light up and the nearest one snaps. You can also pick a wire up by its end, link
backwards from an input, or drop on a module's body to let it choose the port.

![Dragging a wire: compatible ports are ringed and the nearest one snaps](docs/screenshots/qml/links_2_dragging.png)

**Tune each module with the right control.** Fixed choices are drop-downs, on/off settings are switches, numbers have limits
and units, regions are X/Y/W/H fields. Every module also shows which toolbox entry it is, so a card called "MountingHole"
tells you it is a *Circle Search*. Modules can be renamed (F2).

![Module configuration with typed editors](docs/screenshots/qml/module_params.png)

**Or ask AI Gen to build it.** Press <kbd>Ctrl</kbd>+<kbd>G</kbd>, say what you want ("measure the width between two edges
and pass if it is 100 to 300 px"), and the assistant looks up the module reference, drafts a flow, checks it, and offers it
to you. Nothing is added until you click **Add as new flow**, and Ctrl+Z takes it back.

![AI Gen chat with a proposed flow](docs/screenshots/qml/ai_2_chat.png)

AI Gen uses **your own API key**. Pick a provider and a model once (Claude, OpenAI, Gemini, Mistral, DeepSeek, xAI, Groq,
OpenRouter, or a local Ollama / LM Studio model); the model list loads from your account, and you can switch model from the
chat's title bar at any time. Details, privacy notes and the MCP server are in [docs/AI_GEN.md](docs/AI_GEN.md).

<p align="center">
<img src="docs/screenshots/qml/ai_1_settings.png" alt="AI Gen first-run settings" width="49%">
<img src="docs/screenshots/qml/ai_3_model_picker.png" alt="Switching model from the chat header" width="49%">
</p>

## Example: sorting parts

The bundled **Parts Sorter** demo is a complete little inspection: it counts the parts in a
bin, keeps a running lot tally, and passes only when the count is in range *and* every part
looks right. Open `projects/Parts_Sorter_Demo.apex` with **File > Open**; once you have opened it, it also
appears under **Recent projects** on the start page.

| Module | What it does |
|---|---|
| `01_Camera` | Image Source — reads `parts_good.png` |
| `02_Brightness` | Intensity Measure — mean and spread of the bin |
| `03_Smooth` | Image Filter — Gaussian 5x5 |
| `04_Binarize` | Image Binarization — Otsu |
| `05_BlobCount` | BLOB Analysis — counts the parts |
| `06_Classify` | Script — sorts each object by size and shape, rejects the odd ones |
| `07_LotTracker` | Script — running tally in global variables, cross-checks the blob count |
| `08_Count_1_to_8` | Condition Branch — in range for 1 to 8 parts |

Its image strip lists the two pictures that ship with it, so you can compare a good bin with a
bad one without loading anything:

| Picture | What it shows | Result |
|---|---|---|
| `parts_good.png` | round parts, nothing else | **PASS** — 6 blobs, brightness mean 48.4 |
| `parts_mixed.png` | the same bin with an elongated bar mixed in | **FAIL** — `06_Classify` and `07_LotTracker` report NG; mean 52.2 |

![The Parts Sorter failing on parts_mixed.png](docs/screenshots/qml/parts_sorter.png)

Click a thumbnail to switch pictures; the flow re-runs on the one you picked. Turn on **Loop**
with **Run all** and the PASS/FAIL flips as it alternates the two. The rejected object is
outlined and labelled on the image, and the **Result** tab lists all eight modules.

The same thing from another program — the two pictures are in `apex_vision/samples/parts/`:

```bash
python main.py serve --flows projects

curl -s -X POST -H "Content-Type: image/png" \
     --data-binary @apex_vision/samples/parts/parts_mixed.png \
     http://127.0.0.1:8800/v1/flows/Parts_Sorter_Demo/run
```

```json
{ "flow": "Parts_Sorter_Demo", "flow_name": "Parts_Sorter", "verdict": "FAIL",
  "failed_modules": ["06_Classify", "07_LotTracker"] }
```

Send `parts_good.png` instead and the same flow answers `"verdict": "PASS"` with an empty
`failed_modules`. The API is described in [docs/API.md](docs/API.md).

## What you can do with it

- **Design flows visually.** 152 built-in modules in 14 categories: acquisition, image processing (crop, resize / rotate, brightness, edge
  detection, filters), location (template match, circle / line search, caliper, Hough), measurement (distances, angles,
  intersections, focus), recognition (barcode, OCR), **deep learning** (classify, segment, anomaly and YOLO detection with your own ONNX models), defect detection, colour, calibration, communication (TCP, UDP,
  serial, Modbus, CSV log) and logic. Every module is listed in [docs/MODULES.md](docs/MODULES.md). Typed ports, no loops, one source per input.
- **Run on real or fake images.** Single shot, or loop over a folder of images; the Run button turns into Stop while it works.
  Flows run on a background worker, so the window stays responsive.
- **See results at a glance.** Per-module PASS/FAIL, timings, overlays on the image, and a table of every module's outputs.
- **Evaluate detectors.** Load a labelled dataset, get precision / recall / F1 / AP, browse false positives and negatives, and
  compare experiments.
- **Calibrate cameras.** A lens-distortion wizard (chessboard, circle grids) and N-point pixel-to-world calibration.
- **Save everything as plain files.** Projects are saved as `.apex` files, which are readable **XML** (older `.vmp` JSON projects still open); see [docs/XML_FORMAT.md](docs/XML_FORMAT.md).
- **Call it from other programs.** `python main.py serve` runs your saved flows behind a local HTTP API: send an image, get PASS / FAIL and every measurement back as JSON ([docs/API.md](docs/API.md)).
- **Extend it.** Drop a plugin into `plugins/` to add your own modules ([docs/PLUGIN_DEVELOPMENT_GUIDE.md](docs/PLUGIN_DEVELOPMENT_GUIDE.md)).

## Install and run

**Windows users:** grab the installer or the portable ZIP from [Releases](https://github.com/kwincheah/vision-studio/releases)
and run `ApexVisionStudio.exe`. No Python needed.

**From source** (Python 3.10 or newer):

```bash
git clone https://github.com/kwincheah/vision-studio.git
cd vision-studio
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Useful variations:

```bash
python main.py my_solution.apex    # open a project directly
python main.py --widgets           # the older widget-based interface
python main.py --mcp               # run the flow-generation tools as an MCP server
```

Optional extras: `pip install ultralytics` for the YOLO module, `pip install rapidocr-onnxruntime` for OCR.

## Handy shortcuts

| | |
|---|---|
| **Ctrl+N / O / S** | new / open / save a solution |
| **Ctrl+G** | open AI Gen |
| **Ctrl+Z / Y** | undo / redo (moves, links, parameter edits, renames, AI-built flows) |
| **Arrows, Shift+Arrows** | on the canvas: select the neighbouring module / move it |
| **Enter, F2** | configure / rename the selected module |
| **L** then arrows, Enter | link the selected module to another from the keyboard |
| **K, Delete** | select the next link / delete the selected module or link |
| **+ / -, Home** | zoom and fit |

The whole flow canvas can be used without a mouse. Help > Keyboard Shortcuts lists everything.

## For developers

```text
main.py                 entry point (Qt Quick UI by default)
qml/                    the interface; open qml/ApexVision.qmlproject in Qt Design Studio
apex_vision/core/          flow engine, project files, shared run controller
apex_vision/tools/         the 152 built-in modules
apex_vision/flowgen/       AI Gen: module catalogue, spec validator, assistant, MCP server, reference docs
apex_vision/ui/            the older widget interface
plugins/                sample plugin
projects/               sample solutions
tests/                  pytest suite (2,600 tests)
docs/                   guides and specs
```

Run the tests and the secret scan:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/        # a full run takes a while: many tests drive the real window with mouse and keyboard
python scripts/check_secrets.py
```

The UI tests operate the actual QML window with real mouse and keyboard events (dragging wires, typing into fields,
opening menus) and fail on any Qt warning, so what you see in the screenshots is what the tests drive.

More reading:
[User guide](docs/USER_GUIDE.md) ·
[Module reference](docs/MODULES.md) ·
[Deep learning](docs/DEEP_LEARNING.md) ·
[AI Gen](docs/AI_GEN.md) ·
[HTTP API](docs/API.md) ·
[Parameter editors](docs/PARAMETER_EDITORS.md) ·
[XML format](docs/XML_FORMAT.md) ·
[Plugin guide](docs/PLUGIN_DEVELOPMENT_GUIDE.md) ·
[Release notes](docs/RELEASE_NOTES_v1.0.0-beta.4.md)

### Building the Windows app

```bash
pyinstaller ApexVisionStudio.spec --clean --noconfirm     # dist/ApexVisionStudio/
iscc installer_setup.iss                                  # installer (needs Inno Setup 6)
```

## Good to know

- AI-generated flows can be wrong. Check regions and thresholds against your own images before running a line with them.
- Only your messages, the lookups the assistant makes and the flow it is working on go to the AI provider; images never do.
  API keys stay on your machine (optionally in the Windows Credential Manager / Keychain) and never enter project files.
- The look is a light industrial theme. Product names and manuals mentioned belong to their owners.

## License

MIT, see [LICENSE](LICENSE). Contributions and bug reports are welcome; there are issue and pull-request templates in
`.github/`.
