# User guide

How to install Apex Industrial Vision Studio, build your first inspection, read its results, use a camera, and call it from
other programs. For the module reference see the in-app **Help** tab; for specific topics see the other guides listed at
the end.

## Contents

1. [Install](#1-install)
2. [Your first inspection](#2-your-first-inspection)
3. [The main window](#3-the-main-window)
4. [Reading results](#4-reading-results)
5. [Using a camera](#5-using-a-camera)
6. [Saving and opening projects](#6-saving-and-opening-projects)
7. [Run from the command line](#7-run-from-the-command-line)
8. [Call it from another program (HTTP API)](#8-call-it-from-another-program-http-api)
9. [Keyboard shortcuts](#9-keyboard-shortcuts)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Install

**Windows installer.** Download `ApexVisionStudio_Setup_v<version>.exe` from the
[Releases page](https://github.com/kwincheah/vision-studio/releases) and run it. It installs for your own user (no
administrator rights needed) and can associate `.apex` project files with the app.

**Portable ZIP.** Download `ApexVisionStudio-v<version>-Windows-x64.zip`, extract it anywhere and run
`ApexVisionStudio.exe`.

The installer and ZIP are not code-signed yet. If Windows SmartScreen warns you, choose **More info > Run anyway**.

**From source** (Windows, Linux, macOS; Python 3.10 to 3.12):

```bash
git clone https://github.com/kwincheah/vision-studio.git
cd vision-studio
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Optional engines are not bundled: `pip install ultralytics` for YOLO detection and `pip install rapidocr-onnxruntime`
for OCR. A module that needs one tells you when it is missing.

## 2. Your first inspection

1. Start the app. The **Start page** lists sample solutions and your recent projects.
2. Open a sample such as *Precision Measurement Demo*, or choose **New Project** and pick a template.
3. Press **Run**. Every module runs in order. Each shows OK or NG, and the image shows what was found.
4. Click a module on the canvas. Its settings appear on the right. Change a number (for example a threshold) and run
   again to see the effect.

To build your own flow:

1. Drag modules from the **toolbox** onto the canvas. Start with an **Image Source** (it supplies the picture).
2. Drag from a module's output port to another module's input port. Compatible ports light up while you drag and the
   nearest one snaps.
3. Set each module's parameters. Fixed choices are drop-downs, on/off settings are switches, numbers have limits.
4. Press **Run**.

A typical measurement flow is: **Image Source > Image Filter > Edge/Circle search > Measure > Condition Branch**. The last
module decides PASS or FAIL.

Press <kbd>Ctrl</kbd>+<kbd>G</kbd> to open **AI Gen** instead: describe the inspection in plain words and it proposes a
flow. Nothing is added until you accept it, and <kbd>Ctrl</kbd>+<kbd>Z</kbd> undoes it. See [AI_GEN.md](AI_GEN.md).

## 3. The main window

| Area | What it does |
|---|---|
| **Toolbox** (left) | All modules by category. Drag one onto the canvas. |
| **Canvas** (middle) | The flow. Modules and wires. Right-click a module for Configuration, Rename (F2), Execute Module, Delete. |
| **Image viewer** (right) | The image with each module's overlays drawn on it. |
| **Image strip** | The images loaded for this project. Click one to run the flow on it. **Run all** runs every image. |
| **Parameters** | Settings of the selected module. |
| **Result panel** (bottom) | Current Result, History and Help (see below). |

The title bar shows the project name and the app version.

## 4. Reading results

The result area has two pairs of tabs.

**Image | Result (above the viewer).**
- **Image** shows the picture with overlays.
- **Result** swaps the picture for a table with one row per module: its status (OK/NG), time in milliseconds, and its key
  outputs, for example `Distance=219.5`. Click a row to select that module.

**Current Result | History | Help (below).**
- **Current Result** lists every output of the selected module.
- **History** has one line per finished run: its number, time, image name, **PASS** or **FAIL**, total flow time and the
  names of the modules that failed. **Clear** empties it. Each project keeps its own history, and it holds the last 100 runs.
- **Help** explains the selected module: what it does, its inputs and outputs, and each setting with its current value
  and allowed range or choices.

A run is **FAIL** when any module reports NG, Error or Timeout.

## 5. Using a camera

Set the **Image Source** module's **Source type** to **Camera**. Then choose the device:

- **Webcam** : devices appear as `webcam_0`, `webcam_1` and so on. If the camera setting is untouched, a webcam is
  opened for you.
- **RTSP stream** : enter the stream address.
- **Hikrobot MVS industrial camera** : requires the Hikrobot MVS runtime to be installed.

Notes:

- Windows lets **one program at a time** use a camera. Close other apps that use it (video calls, the Camera app).
- If the image is black, check *Settings > Privacy & security > Camera* and allow desktop apps. A webcam also needs a
  second or two to adjust its exposure, so the first frames can be dark.
- A ready-made flow that uses the webcam, checks its brightness and counts bright objects is described in
  [CAMERA_DEMO.md](CAMERA_DEMO.md).

## 6. Saving and opening projects

- <kbd>Ctrl</kbd>+<kbd>S</kbd> saves; <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd> saves under a new name.
- Projects are saved as `.apex` files, which are readable **XML** ([XML_FORMAT.md](XML_FORMAT.md)). Older `.vmp`, `.sol`,
  `.json` and `.xml` projects still open.
- **New Project** starts in `Documents/ApexVision/Projects`. Use **Browse...** to pick another folder.
- Plugin packages use the `.apexpkg` extension.

## 7. Run from the command line

The same engine runs without a window:

```bash
python main.py run --workflow projects/PCB_Inspection_Demo.apex --input board.png
python main.py run --workflow my_flow.apex --input images_folder --out-json results.json
```

`--input` may be a single image or a folder. The exit code is non-zero if any image failed, unless you pass
`--ignore-errors`. Other commands are `serve` (see below), `evaluate`, `compare`, `list`, `dataset` and `demo` for
measuring a detector on a labelled dataset. Add `--help` to any of them (for example `python -m apex_vision.cli run --help`).

## 8. Call it from another program (HTTP API)

Another program, a web app for example, can send an image to your computer and get PASS/FAIL and every measurement back as
JSON:

```bash
python main.py serve --flows projects
```

```bash
curl -X POST -H "Content-Type: image/png" --data-binary @tile.png \
     "http://127.0.0.1:8800/v1/flows/PCB_Inspection_Demo/run?return_image=1"
```

The server listens on this computer only unless you set a host **and** an API key. Callers can run flows that are already
in the folder; they cannot upload flows. Everything, with Python and JavaScript examples, is in [API.md](API.md).
The server is available from source (`python main.py serve`); the packaged Windows app has no console yet.

## 9. Keyboard shortcuts

| Keys | Action |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>N</kbd> / <kbd>Ctrl</kbd>+<kbd>O</kbd> | New / open project |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd> | Save / save as |
| <kbd>Ctrl</kbd>+<kbd>I</kbd> | Load an image |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Y</kbd> | Undo / redo |
| <kbd>Ctrl</kbd>+<kbd>G</kbd> | AI Gen assistant |
| <kbd>Ctrl</kbd>+<kbd>1</kbd> / <kbd>2</kbd> / <kbd>3</kbd> | Flow / operation / multi-image view |
| <kbd>Ctrl</kbd>+<kbd>0</kbd> | Fit the canvas to the window |
| <kbd>F2</kbd> | Rename the selected module |
| <kbd>Enter</kbd> | Open the selected module's configuration |
| <kbd>Del</kbd> | Delete the selected module |
| <kbd>F1</kbd> | Open the manual |

## 10. Troubleshooting

| Problem | What to do |
|---|---|
| Windows warns about an unknown publisher | The app is not code-signed yet. **More info > Run anyway**. |
| The camera image is black or the camera will not open | Close other programs using it; allow desktop apps under Windows camera privacy settings; wait a second for exposure to settle. |
| "Missing Plugin Tool" when opening an old project | The project uses a module from a plugin that is not installed. Install the plugin, or remove that module. |
| A module says an engine is missing | Install the optional package it names (`ultralytics`, `rapidocr-onnxruntime`). |
| New Project says the folder cannot be written | Pick another folder with **Browse...**. |
| `python main.py serve` refuses to start | A non-loopback `--host` needs `--api-key`. |
| API returns `503 busy` | Another job is running. Retry. |

Found a bug? Open an issue at <https://github.com/kwincheah/vision-studio/issues> with the app version, your OS and, if you
can, the project file.

## More guides

[AI Gen](AI_GEN.md) · [HTTP API](API.md) · [Camera demo](CAMERA_DEMO.md) · [Parameter editors](PARAMETER_EDITORS.md) ·
[XML format](XML_FORMAT.md) · [Plugin development](PLUGIN_DEVELOPMENT_GUIDE.md)
