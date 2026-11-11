# Apex Industrial Vision Studio 1.0.0-beta.4

A public beta of **Apex Industrial Vision Studio**: a desktop tool for building machine-vision
inspections by wiring modules together on a canvas, or by describing the inspection to an AI
assistant that builds the flow for you.

This is a **beta**. Expect rough edges, and please report them.

---

## What changed since beta.3

Most of this release came out of a UI/UX audit: a deliberately rendered and measured pass over
every dialog, every editor and every module panel.

### Fixed — a run could rewrite your project

- **Running a flow no longer modifies it.** Feeding an image to the flow used to write the
  image's path into the Image Source module. The project then reported "unsaved changes" after
  a harmless Run, and saving committed an **absolute path**, replacing a *Synthetic* source
  with a *File* one, so the project no longer opened correctly on another machine. Applying an
  image is now execution state; choosing a source stays an explicit action (loading a folder,
  picking a camera).
- **Reopening a project no longer marks it dirty.** Only the first project opened in a session
  used to be clean.
- A genuine edit is still detected — verified both ways by regression tests.

### New — per-module Display Setup

The **Display Setup** tab in Module Configuration had three checkboxes hardcoded to on and five
colour swatches that could not be clicked. Both now work and are saved with the project: show
or hide the module's ROI, its text labels and its result boxes, and choose the colour its
overlays are drawn in. Untouched projects are written byte-for-byte as before.

### New — a script editor instead of a text box

The script parameter is now a small IDE: Python syntax highlighting (via Python's own
tokenizer), line numbers, current-line and `Ln, Col` readout, auto-indent including after `:`,
Tab / Shift+Tab, **Ctrl+/** to comment a line, **Ctrl+Enter** to apply, and a live syntax check
that marks the offending line in the gutter.

### Layout — the canvas and the viewer keep their proportions

- The canvas and the image column hold a **6:4** split at any window width. A fixed column
  width made the image column wider than the canvas on a 1280-wide window.
- The image viewer and the result block below it also hold **6:4**. The viewer was a fixed
  300 px tall, which made the image the smallest important thing on screen.

### Fixed — accessibility and polish

- **Keyboard users could not reach any input.** Text fields were not in the Tab chain, so Tab
  skipped every numeric and text field. Workspace tabs were not focusable either. Both fixed.
- **The focus ring was invisible on the dark toolbars** (blue on grey at 1.11:1). Chrome
  surfaces now use a light ring.
- Hover fills on the Run and primary buttons were below AA (3.30:1 and 3.90:1); now 5.38:1 and
  5.44:1. The status bar was dark-on-dark at 3.06:1; now 4.79:1.
- Scrollbars rendered near-black against the light panels (the app ran the platform's native
  Qt Quick Controls style, which refuses recolouring). Fixed app-wide.
- "**+ Add Variable**" was clipped by the dialog edge; "**Create & Publish**" was clipped in
  the Plugin Manager; the validation dialog read "1 issue(s) need attention."
- **Reset ROI to default** is now one click (or Ctrl+Shift+R), undoable.
- "Fit to screen" in the image header now shows that it is active when the image is fitted.

### Testing

The suite grew to cover the new behaviour, including regression tests that fail against the
old code: the image pool cannot mutate a project, the Display Setup round-trips through the
project file, and the script editor's highlighter and checker (including that a script cannot
inject markup). As of this release the suite runs green.

## Install

**Windows installer.** Download `ApexVisionStudio_Setup_v1.0.0-beta.4.exe` from the assets below
and run it.

**Portable ZIP.** Download `ApexVisionStudio-v1.0.0-beta.4-Windows-x64.zip`, extract it anywhere
and run `ApexVisionStudio.exe`. No administrator rights or Python needed.

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
- Optional engines are not bundled: install `ultralytics` for YOLO object detection and
  `rapidocr-onnxruntime` for OCR.
- The installer and ZIP are not code-signed, so Windows SmartScreen may warn on first run.
- Only a Windows build is provided. Linux and macOS users run from source.
- A blank project still starts with the bundled sample images in the image strip.
- A project saved by this build carries the new Display Setup block; an older build would drop
  it when re-saving.

## Feedback

Please open an issue at <https://github.com/kwincheah/vision-studio/issues> and include the app
version (shown in the title bar and under Help, About), your OS and, if possible, the project file.
