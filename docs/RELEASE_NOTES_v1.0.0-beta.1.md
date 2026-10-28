# Apex Industrial Vision Studio 1.0.0-beta.1

The first public beta of **Apex Industrial Vision Studio**: a desktop tool for building machine-vision inspections by wiring modules together on a canvas, or by describing the inspection to an AI assistant that builds the flow for you.

This is a **beta**. It is feature-complete for the first release and well tested (about 1,400 automated tests, run on Windows and Linux), but it has had little time in front of real users. Expect rough edges, and please report them.

---

## What is in it

- **Visual flow canvas.** Drag modules from the toolbox, link ports (with snapping, relinking and keyboard control), rename modules, and run the flow with live per-module results.
- **42 vision modules** across acquisition, image processing, location, measurement, recognition, logic, communication and output, each with typed parameter editors (dropdowns, toggles, file pickers) instead of free text.
- **AI Gen.** A floating chat assistant that reads the built-in module reference and generates a validated flow from a prompt. Bring your own key for Anthropic, OpenAI, Google Gemini, Mistral, DeepSeek, xAI, Groq or OpenRouter, or point it at a local server such as Ollama or LM Studio. Keys are stored in the OS credential store, never in project files.
- **MCP server.** `python main.py --mcp` exposes the same flow-building tools to other AI clients.
- **Multi-flow solutions** with shared global variables, saved as `.vmp` projects or XML.
- **Camera support** for webcams, RTSP streams and Hikrobot MVS industrial cameras, plus a lens-calibration wizard.
- **Plugin SDK** (`apex_vision.sdk`) and an in-app extension manager for third-party modules.

## Install

**Windows installer.** Download `ApexVisionStudio_Setup_v1.0.0-beta.1.exe` from the assets below and run it.

**Portable ZIP.** Download `ApexVisionStudio-v1.0.0-beta.1-Windows-x64.zip`, extract it anywhere and run `ApexVisionStudio.exe`. No administrator rights or Python needed.

**From source** (Windows, Linux, macOS):

```bash
git clone https://github.com/kwincheah/vision-studio.git
cd vision-studio
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Known limitations

- Optional engines are not bundled: install `ultralytics` for YOLO object detection and `rapidocr-onnxruntime` for OCR. The modules report a clear message when the engine is missing.
- The installer and ZIP are not code-signed, so Windows SmartScreen may warn on first run.
- Only the Windows build is produced by the release workflow. Linux and macOS users run from source.
- Projects saved by this beta write `<ApexSolution>` XML. Files from earlier internal builds (`<VisionMasterSolution>`) still open.
- AI Gen output is validated before it is applied, but generated flows should still be reviewed before use on a production line.

## Feedback

Please open an issue at <https://github.com/kwincheah/vision-studio/issues> and include the app version (shown in the title bar and under Help, About), your OS and, if possible, the project file.
