# Apex Industrial Vision Studio 1.0.0-beta.3

A public beta of **Apex Industrial Vision Studio**: a desktop tool for building machine-vision inspections by wiring modules together on a canvas, or by describing the inspection to an AI assistant that builds the flow for you.

This is a **beta**. Expect rough edges, and please report them.

---

## What changed since beta.2

- **Local HTTP API.** `python main.py serve` runs your saved flows behind a local web API. Another program sends an image and gets PASS / FAIL and every module's results back as JSON. Loopback only by default, API key required for any other host, flows cannot be uploaded, and parameters can be overridden per request within their limits. See [docs/API.md](https://github.com/kwincheah/vision-studio/blob/main/docs/API.md).
- **Result, History and Help tabs now work.** The top **Result** tab shows a table of every module's status, time and outputs. **History** lists each run with its verdict, time and failed modules (with **Clear**). **Help** explains the selected module and its settings. Previously these tabs only changed colour.
- **Webcam works out of the box.** An Image Source set to **Camera** with the untouched default device now opens your webcam instead of looking for an industrial camera that is not there.
- **New documentation.** A full [User guide](https://github.com/kwincheah/vision-studio/blob/main/docs/USER_GUIDE.md) and a [webcam demo](https://github.com/kwincheah/vision-studio/blob/main/docs/CAMERA_DEMO.md).
- `python main.py run|serve|evaluate|...` now work from the main entry point.

## Install

**Windows installer.** Download `ApexVisionStudio_Setup_v1.0.0-beta.3.exe` from the assets below and run it.

**Portable ZIP.** Download `ApexVisionStudio-v1.0.0-beta.3-Windows-x64.zip`, extract it anywhere and run `ApexVisionStudio.exe`. No administrator rights or Python needed.

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

## Known limitations

- The HTTP API (`serve`) runs from source only; the packaged Windows app has no console.
- The API runs one job at a time.
- Optional engines are not bundled: install `ultralytics` for YOLO object detection and `rapidocr-onnxruntime` for OCR.
- The installer and ZIP are not code-signed, so Windows SmartScreen may warn on first run.
- Only a Windows build is provided. Linux and macOS users run from source.
- The webcam entry in the camera list shows its resolution twice, for example `(640x480) (640x480)`. Cosmetic.
- A blank project still starts with the bundled sample images in the image strip.

## Feedback

Please open an issue at <https://github.com/kwincheah/vision-studio/issues> and include the app version (shown in the title bar and under Help, About), your OS and, if possible, the project file.
