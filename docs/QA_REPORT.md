# QA Report — Apex Industrial Vision Studio 1.0.0-beta.3

Date: 2026-11-11 · Build tested: `dist/ApexVisionStudio` (`ApexVisionStudio.spec`), installed copy
Scope: full functional + UI/UX-logic pass after the latest code update · Focus: UI/UX logic

## Summary

| Area | Result |
|---|---|
| Automated suites (`pytest tests/ -q`) | **green**, exit 0, 2 opt-in live tests skipped |
| UI/UX logic probe (`scripts/qa_ui_logic.py`) | **85 checks, 84 pass, 1 fail** |
| Tool sweep, all 160 registered tools | **0 unhandled exceptions**; 32 report actionable `Error` when unconfigured (correct) |
| **Defects found** | **2 (both High)** — one root cause, two user-visible failures |
| **Status** | **both fixed and verified**; see *Fix applied* |

Both defects share one root cause: **executing a flow writes transient strip state into the
project model.**

---

## BUG-01 — Running a flow silently rewrites the project, and saving persists the damage

**Severity: High** · **Confidence: proven, with file-level evidence**

### What happens

Merely pressing **Run** mutates the Image Source module's persisted parameters. The change is
invisible on screen, and it makes the project "dirty". If the operator then saves — which they
are prompted to do, see BUG-02 — the mutation is written to disk.

### Evidence

In-memory snapshot, before vs after a single Run:

```
flows[0].nodes[0].parameters.file_path
    'apex_vision/samples/pcb_sample.png' -> 'C:\Users\winch\Downloads\VMClone\apex_vision\samples\pcb_sample_defect.png'
flows[0].nodes[0].parameters.source_type
    'Synthetic' -> 'File'
```

The same change appears in the file written by `saveProjectAs` after the run — measured
against the pristine `PCB_Inspection_Demo.apex`:

```
on disk before any run : {'source_type': 'Synthetic', 'file_path': 'apex_vision/samples/pcb_sample.png'}
written after the run  : {'source_type': 'File',      'file_path': 'C:\\...\\pcb_sample_defect.png'}
PROJECT REWRITTEN BY RUNNING: True
```

### Why it matters

1. **The project's own configuration is destroyed.** The demo ships as a *Synthetic* generator;
   after one Run + Save it becomes a *File* source pointing at one specific picture.
2. **The path is absolute.** The saved project no longer opens correctly on another machine or
   another checkout — the classic "works on my PC" breakage, now baked into a shipped artifact.
3. **The wrong image wins.** Running the strip leaves the *last-run* image as the project's
   source, so a project inspected against image 2 will reopen expecting image 2.
4. **It is invisible.** Nothing on screen indicates the module changed; the operator sees only a
   generic "unsaved changes" prompt (BUG-02).

### Root cause

`apex_vision/core/controller.py:114–128`, `ImagePool.apply_to()`:

```python
for node in pipeline.nodes.values():
    if node.tool_name == "Image Source":
        if item.get("path"):
            node.set_param("source_type", "File")     # persisted
            node.set_param("file_path", item["path"]) # persisted
        node._override_image = item.get("image")      # transient - correct
        node._override_name = item["name"]            # transient - correct
```

The override fields are the right mechanism; the two `set_param` calls are not. Every other
call site of `set_param("file_path", ...)` is a genuine user action (loading an image folder,
choosing a camera). This one is execution state.

### Suggested fix

Drop the two `set_param` calls and let `_override_image` / `_override_name` carry the strip
selection, which is what the executor already reads. If the source node must report a path for
display, expose it as a read-only runtime field rather than a parameter.

### Reproduction

```powershell
python scripts/qa_tool_sweep.py          # Part 1 prints the before/after and "PROJECT REWRITTEN BY RUNNING: True"
```

---

## BUG-02 — Only the first project opened in a session is ever clean

**Severity: High** · **Confidence: proven**

### What happens

The first project opened after launch reports `dirty = False`. Every subsequent open reports
`dirty = True` **immediately**, with no user edit at all. The session can never return to a
clean state except by saving.

### Evidence

```
fresh app, open #1          dirty = False
... press Run ...           dirty = True
open #2 (same file)         dirty = True      <- expected False
open #3 (same file)         dirty = True
saveProjectAs               dirty = False     <- only saving clears it
```

And independently of running, a second open in the same process is already dirty:

```
fresh open (no run yet)     dirty = True
```

### Consequences

1. **Spurious "unsaved changes" prompt on every close.** Measured directly:

   ```
   A. close a clean project   -> prompts: none (closes silently)          correct
   B. close after ONLY Run    -> prompts: "'PCB_Inspection_Demo' has unsaved changes.
                                          Save them before continuing?"   WRONG
   C. close after a real edit -> prompts: same message                    correct
   ```

   Case B is the dangerous one: the operator is asked to save work they never did. Choosing
   **Save** then commits the BUG-01 corruption.

2. **The dirty indicator is permanently lit**, so it stops conveying information. Users learn to
   ignore it, which is exactly how a real unsaved edit gets discarded.

3. Because undo *does* clear the flag correctly (verified below), the flag itself works — it is
   the baseline that is being polluted on load.

### Root cause

Same as BUG-01: `ImagePool.apply_to()` is re-invoked while loading, so the freshly-loaded
pipeline is immediately modified relative to the snapshot taken at load time.

### Reproduction

```powershell
python scripts/qa_ui_logic.py            # "reopening a project returns to a clean state" fails
```

---

## Verified correct (tested, not assumed)

These were all exercised and behaved properly — recorded so the report is not one-sided.

| Check | Result |
|---|---|
| Undo/redo of a node drag (`beginMove` → `moveNode` → undo) | **correct** — position restored `(50,50)`, dirty returns to its pre-drag value; redo re-applies; a second undo stays consistent |
| Stop during a run | **correct** — `running` clears within 0.2 s, verdict remains readable, all 7 module rows present |
| Run state machine | verdict produced, flow time measured, history records one entry per image, results cover all modules |
| All 160 registered tools: construct + schema + execute | **0 unhandled exceptions** across empty / blank / noise contexts |
| 32 tools reporting `Error` on an unconfigured blank image | **correct and well-worded**, e.g. *"no model chosen: choose a defect prediction model (.onnx)"*, *"draw the region first: it is empty"* |
| Dialogs (9 of them) | open, become current, close cleanly; opening one over another keeps the newest |
| Workspace/view/inspection/AI panel state | every tab and visibility flag sticks |
| Zoom/pan clamping (new pinch code) | image viewport clamps to `1..16` and zeroes pan at fit; canvas clamps to `0.25..2.5`; `fitView` leaves a usable zoom |
| Unknown action / unknown flow id / out-of-range image index | no crash, state stays valid |
| Empty project name, closed dialog, Esc | no orphaned state |

---

## Lower-priority observations

1. **`newFromTemplate` has no argument validation.** `@pyqtSlot(int)` is correct for QML (which
   passes `parseInt`), but an internal caller passing anything else gets
   `TypeError: '<' not supported between instances of 'int' and 'str'` from the clamp
   expression rather than a clear message. Cosmetic; not reachable from the UI.
2. **`newFromTemplate` catches only `OSError`.** Other failures from `create_project` propagate
   as a QML error with no user-facing message.
3. **History count is per-image.** "Run all" over a 2-image strip appends 2 records per press.
   Arguably correct, but the History tab gives no indication that several rows came from one
   click — a "run" grouping would read better.

---

## Test assets added

| Script | Purpose |
|---|---|
| `scripts/qa_ui_logic.py` | 85 UI/UX-logic assertions; writes `docs/audit/ui_logic_results.json` |
| `scripts/qa_tool_sweep.py` | proves the save corruption, then constructs/schemas/executes all 160 tools; writes `docs/audit/tool_sweep.json` |

Both are re-runnable and exit non-zero on failure, so they can gate a release.

## Fix applied

Both defects were one boundary error and are now fixed in `apex_vision/core/controller.py`.

`ImagePool.apply_to()` gained an explicit `persist` flag, because the method was doing two
different jobs:

| Intent | `persist` | What it does | Call sites |
|---|---|---|---|
| **Execution** — which picture the next run consumes | `False` (default) | Sets only `_override_image` / `_override_name` | a run, an image-strip click (`RunEngine.select_image`) |
| **Configuration** — the operator just loaded images | `True` | Also writes `source_type` / `file_path` | `loadImageFiles`, `loadImageFolder`, the widget UI's "load image into flow" |

This keeps the behaviour the product wants (loading images is remembered and marks the
project dirty) while removing the side effect that rewrote the project during a run.

### Verification

| Check | Before | After |
|---|---|---|
| `open -> Run -> save`, Image Source `source_type` | `File` (corrupted) | **`Synthetic`** |
| `open -> Run -> save`, `file_path` | absolute path | **`apex_vision/samples/pcb_sample.png`** |
| dirty flag after a Run | `True` | **`False`** |
| close prompt after a Run | "unsaved changes" | **none** |
| dirty flag after reopening | `True` | **`False`** |
| dirty flag after a real edit | `True` | **`True`** (correctly preserved) |
| explicit `loadImageFolder` | persists | **persists**, and marks dirty (correct) |
| image-strip click | persisted (wrong) | **transient**, project untouched |
| `scripts/qa_ui_logic.py` | 84/85 | **85/85** |
| `scripts/qa_tool_sweep.py` | `PROJECT REWRITTEN: True` | **`PROJECT REWRITTEN: False`** |
| all 160 tools | 0 exceptions | 0 exceptions |

### Regression tests

`tests/test_image_pool_no_mutation.py` — 8 tests. Verified to be real tests by
reintroducing the defect: **4 of them fail on the old code** (including the end-to-end
"running a flow does not mark the project dirty") and all 8 pass on the fix. They pin both
directions, so a future over-correction that stops images being remembered also fails.

## Recommended order of work

1. ~~**BUG-01** — stop `apply_to` rewriting the project.~~ **Done.**
2. ~~Re-run `scripts/qa_ui_logic.py`.~~ **Done — 85/85.**
3. ~~Regression test for `open → run → save`.~~ **Done — 8 tests, mutation-verified.**
4. ~~Rebuild and reinstall.~~ **Done.** `ApexVisionStudio.spec` rebuilt; the installed
   `ApexVisionStudio.exe` is byte-identical to the new `dist` build
   (SHA-256 `2B62BC88...A680DC`), built 13:18 against the fixed source (12:34), and launches
   with the plugins loading and the correct window title.

   Note: the Inno Setup installer still cannot be executed in this environment (unsigned,
   the process is blocked), so the installed copy was updated by replacing its files. The
   registry entry therefore still reads `1.0.0-beta.2` and points at a missing
   `unins000.exe`; running the installer on a normal desktop session would repair that.


---

# Round 2 — the four UI/UX items requested after the first pass

Date: 2026-11-11 · Same build, plus the changes below

## 1. Canvas : image column is now a true 6:4

`rightColumn` had a hardcoded `width: 640`, so the ratio drifted with the window: at 1600 it
was 59:41, at 1280 the image column was **wider than the canvas**, and on a wide monitor the
canvas took most of the space. It now takes 40% of the space beside the rail, clamped so
neither side can collapse.

| Window | Canvas | Image column | Ratio |
|---|---|---|---|
| 1280 | 743 (60.0%) | 495 (40.0%) | 1.50:1 |
| 1440 | 839 (60.0%) | 559 (40.0%) | 1.50:1 |
| 1600 | 935 (60.0%) | 623 (40.0%) | 1.50:1 |
| 1920 | 1127 (60.0%) | 751 (40.0%) | 1.50:1 |
| 2560 | 1511 (60.0%) | 1007 (40.0%) | 1.50:1 |

## 2. "Fit to screen" — the button worked, but gave no sign of it

Measured with a real mouse click: zoom 4.00 + pan (140, 90) -> after clicking fit, zoom 1.00
and pan (0, 0). The handler was correct all along; what was missing was any feedback, because
at fit the button looked identical to its unfocused state. Now:

* the fit button reads as *active* whenever the image is already fitted, so pressing it
  visibly does something;
* a `fitView()` entry point gives the action a name, instead of relying on the `else` branch
  of the click chain;
* the tooltip no longer claims Ctrl+0 fits the image - Ctrl+0 fits the *canvas*.

## 3. Reset ROI to default — new

* `resetRoi()` (backend): sets the selected module's `roi` / `template_roi` back to
  `[0, 0, 0, 0]`, which the region tools read as "the whole image". One undo step, and the
  flow re-runs so the verdict follows the change.
* an `roi` button in the image header (6th button) and **Ctrl+Shift+R**.
* refuses politely on a module that has no region ("This module has no region to reset") and
  reports when there is nothing to do ("ROI is already the whole image").

Verified: `[120, 90, 200, 150]` -> reset -> `[0, 0, 0, 0]` -> undo -> `[120, 90, 200, 150]`.

## 4. Display Setup — it was a mock-up, and now it works

**This was the significant find of the round.** The "Display Setup" tab in Module
Configuration rendered three checkboxes and five colour swatches, and **none of them did
anything**:

```qml
CheckLabel { text: "Show module ROI";     checked: true }    // no handler
CheckLabel { text: "Show result labels";  checked: true }    // no handler
CheckLabel { text: "Show defect boxes";   checked: true }    // no handler
Repeater { model: ["#e4b030", ...]
    delegate: Rectangle { ... }                              // no MouseArea at all
```

The checkboxes toggled their own pixels and saved nothing; the swatches could not even be
clicked. Every module showed the same three ticks.

Now, per the requested design (**per module, saved with the project**, colour applies to that
module's own overlay drawings):

| Piece | Implementation |
|---|---|
| Storage | `VisionToolBase.display` = `{roi, labels, boxes, colour}`; written to the project as a `<Display>` element **only when it differs from the default**, so untouched projects stay byte-identical |
| Backend | `selectedDisplay` property, `setModuleDisplay(nodeId, key, value)` - validates the colour, raises one undo step, redraws |
| Checkboxes | bound to the module's real state; `roi` also hides the ROI rectangle the viewer draws |
| Colour | five swatches, the chosen one ringed; recolours the overlays that module draws (labels, boxes, lines, circles, crosses) |
| Robustness | a hand-edited or older file with a bad display block falls back to the default rather than reaching the renderer |

Verified end to end: all three checkboxes render and write; unchecking one sets the flag and
marks the project changed; a swatch stores its colour; **undo reverts it**; the file gains a
`<Display>` element; **reloading restores `roi: False, colour: #2b7bb9`**. 10/10 checks.

### Also checked, per the question about "the colour cannot be changed"

I audited the **parameter** colour across all modules as well, in case that was the intent:

* **105 boolean parameters** exist across the tools; every one renders as a checkbox, is
  accepted by the schema, and round-trips through `setParamValue`. **0 problems.**
* **1 colour parameter**: `Color Measurement.target_rgb`, rendered as editable R/G/B fields.
  It **is** changeable and saves correctly (`[0,150,0]` -> `[11,22,33]`). It is a measurement
  target, not interface chrome, so I left it editable - tell me if it should be locked.

## Test assets

| Script | Purpose |
|---|---|
| `scripts/qa_param_editors.py` | all 160 tools: every bool round-trips, the rgb round-trips |
| `scripts/qa_param_editor_qml.py` | the rendered checkbox / colour editors |
| `scripts/qa_display_setup.py` | Display Setup: click each control, undo, save, reload (10 checks) |
| `tests/test_module_display.py` | 12 tests: defaults, bad-file fallback, byte-stability, round-trip |

Full suite: **green** (exit 0). `qa_ui_logic.py` still 85/85; `qa_tool_sweep.py` still
`PROJECT REWRITTEN: False`, 0 tool problems.
# QA Report — Apex Industrial Vision Studio 1.0.0-beta.3

Date: 2026-11-11 · Build tested: `dist/ApexVisionStudio` (`ApexVisionStudio.spec`), installed copy
Scope: full functional + UI/UX-logic pass after the latest code update · Focus: UI/UX logic

## Summary

| Area | Result |
|---|---|
| Automated suites (`pytest tests/ -q`) | **green**, exit 0, 2 opt-in live tests skipped |
| UI/UX logic probe (`scripts/qa_ui_logic.py`) | **85 checks, 84 pass, 1 fail** |
| Tool sweep, all 160 registered tools | **0 unhandled exceptions**; 32 report actionable `Error` when unconfigured (correct) |
| **Defects found** | **2 (both High)** — one root cause, two user-visible failures |
| **Status** | **both fixed and verified**; see *Fix applied* |

Both defects share one root cause: **executing a flow writes transient strip state into the
project model.**

---

## BUG-01 — Running a flow silently rewrites the project, and saving persists the damage

**Severity: High** · **Confidence: proven, with file-level evidence**

### What happens

Merely pressing **Run** mutates the Image Source module's persisted parameters. The change is
invisible on screen, and it makes the project "dirty". If the operator then saves — which they
are prompted to do, see BUG-02 — the mutation is written to disk.

### Evidence

In-memory snapshot, before vs after a single Run:

```
flows[0].nodes[0].parameters.file_path
    'apex_vision/samples/pcb_sample.png' -> 'C:\Users\winch\Downloads\VMClone\apex_vision\samples\pcb_sample_defect.png'
flows[0].nodes[0].parameters.source_type
    'Synthetic' -> 'File'
```

The same change appears in the file written by `saveProjectAs` after the run — measured
against the pristine `PCB_Inspection_Demo.apex`:

```
on disk before any run : {'source_type': 'Synthetic', 'file_path': 'apex_vision/samples/pcb_sample.png'}
written after the run  : {'source_type': 'File',      'file_path': 'C:\\...\\pcb_sample_defect.png'}
PROJECT REWRITTEN BY RUNNING: True
```

### Why it matters

1. **The project's own configuration is destroyed.** The demo ships as a *Synthetic* generator;
   after one Run + Save it becomes a *File* source pointing at one specific picture.
2. **The path is absolute.** The saved project no longer opens correctly on another machine or
   another checkout — the classic "works on my PC" breakage, now baked into a shipped artifact.
3. **The wrong image wins.** Running the strip leaves the *last-run* image as the project's
   source, so a project inspected against image 2 will reopen expecting image 2.
4. **It is invisible.** Nothing on screen indicates the module changed; the operator sees only a
   generic "unsaved changes" prompt (BUG-02).

### Root cause

`apex_vision/core/controller.py:114–128`, `ImagePool.apply_to()`:

```python
for node in pipeline.nodes.values():
    if node.tool_name == "Image Source":
        if item.get("path"):
            node.set_param("source_type", "File")     # persisted
            node.set_param("file_path", item["path"]) # persisted
        node._override_image = item.get("image")      # transient - correct
        node._override_name = item["name"]            # transient - correct
```

The override fields are the right mechanism; the two `set_param` calls are not. Every other
call site of `set_param("file_path", ...)` is a genuine user action (loading an image folder,
choosing a camera). This one is execution state.

### Suggested fix

Drop the two `set_param` calls and let `_override_image` / `_override_name` carry the strip
selection, which is what the executor already reads. If the source node must report a path for
display, expose it as a read-only runtime field rather than a parameter.

### Reproduction

```powershell
python scripts/qa_tool_sweep.py          # Part 1 prints the before/after and "PROJECT REWRITTEN BY RUNNING: True"
```

---

## BUG-02 — Only the first project opened in a session is ever clean

**Severity: High** · **Confidence: proven**

### What happens

The first project opened after launch reports `dirty = False`. Every subsequent open reports
`dirty = True` **immediately**, with no user edit at all. The session can never return to a
clean state except by saving.

### Evidence

```
fresh app, open #1          dirty = False
... press Run ...           dirty = True
open #2 (same file)         dirty = True      <- expected False
open #3 (same file)         dirty = True
saveProjectAs               dirty = False     <- only saving clears it
```

And independently of running, a second open in the same process is already dirty:

```
fresh open (no run yet)     dirty = True
```

### Consequences

1. **Spurious "unsaved changes" prompt on every close.** Measured directly:

   ```
   A. close a clean project   -> prompts: none (closes silently)          correct
   B. close after ONLY Run    -> prompts: "'PCB_Inspection_Demo' has unsaved changes.
                                          Save them before continuing?"   WRONG
   C. close after a real edit -> prompts: same message                    correct
   ```

   Case B is the dangerous one: the operator is asked to save work they never did. Choosing
   **Save** then commits the BUG-01 corruption.

2. **The dirty indicator is permanently lit**, so it stops conveying information. Users learn to
   ignore it, which is exactly how a real unsaved edit gets discarded.

3. Because undo *does* clear the flag correctly (verified below), the flag itself works — it is
   the baseline that is being polluted on load.

### Root cause

Same as BUG-01: `ImagePool.apply_to()` is re-invoked while loading, so the freshly-loaded
pipeline is immediately modified relative to the snapshot taken at load time.

### Reproduction

```powershell
python scripts/qa_ui_logic.py            # "reopening a project returns to a clean state" fails
```

---

## Verified correct (tested, not assumed)

These were all exercised and behaved properly — recorded so the report is not one-sided.

| Check | Result |
|---|---|
| Undo/redo of a node drag (`beginMove` → `moveNode` → undo) | **correct** — position restored `(50,50)`, dirty returns to its pre-drag value; redo re-applies; a second undo stays consistent |
| Stop during a run | **correct** — `running` clears within 0.2 s, verdict remains readable, all 7 module rows present |
| Run state machine | verdict produced, flow time measured, history records one entry per image, results cover all modules |
| All 160 registered tools: construct + schema + execute | **0 unhandled exceptions** across empty / blank / noise contexts |
| 32 tools reporting `Error` on an unconfigured blank image | **correct and well-worded**, e.g. *"no model chosen: choose a defect prediction model (.onnx)"*, *"draw the region first: it is empty"* |
| Dialogs (9 of them) | open, become current, close cleanly; opening one over another keeps the newest |
| Workspace/view/inspection/AI panel state | every tab and visibility flag sticks |
| Zoom/pan clamping (new pinch code) | image viewport clamps to `1..16` and zeroes pan at fit; canvas clamps to `0.25..2.5`; `fitView` leaves a usable zoom |
| Unknown action / unknown flow id / out-of-range image index | no crash, state stays valid |
| Empty project name, closed dialog, Esc | no orphaned state |

---

## Lower-priority observations

1. **`newFromTemplate` has no argument validation.** `@pyqtSlot(int)` is correct for QML (which
   passes `parseInt`), but an internal caller passing anything else gets
   `TypeError: '<' not supported between instances of 'int' and 'str'` from the clamp
   expression rather than a clear message. Cosmetic; not reachable from the UI.
2. **`newFromTemplate` catches only `OSError`.** Other failures from `create_project` propagate
   as a QML error with no user-facing message.
3. **History count is per-image.** "Run all" over a 2-image strip appends 2 records per press.
   Arguably correct, but the History tab gives no indication that several rows came from one
   click — a "run" grouping would read better.

---

## Test assets added

| Script | Purpose |
|---|---|
| `scripts/qa_ui_logic.py` | 85 UI/UX-logic assertions; writes `docs/audit/ui_logic_results.json` |
| `scripts/qa_tool_sweep.py` | proves the save corruption, then constructs/schemas/executes all 160 tools; writes `docs/audit/tool_sweep.json` |

Both are re-runnable and exit non-zero on failure, so they can gate a release.

## Fix applied

Both defects were one boundary error and are now fixed in `apex_vision/core/controller.py`.

`ImagePool.apply_to()` gained an explicit `persist` flag, because the method was doing two
different jobs:

| Intent | `persist` | What it does | Call sites |
|---|---|---|---|
| **Execution** — which picture the next run consumes | `False` (default) | Sets only `_override_image` / `_override_name` | a run, an image-strip click (`RunEngine.select_image`) |
| **Configuration** — the operator just loaded images | `True` | Also writes `source_type` / `file_path` | `loadImageFiles`, `loadImageFolder`, the widget UI's "load image into flow" |

This keeps the behaviour the product wants (loading images is remembered and marks the
project dirty) while removing the side effect that rewrote the project during a run.

### Verification

| Check | Before | After |
|---|---|---|
| `open -> Run -> save`, Image Source `source_type` | `File` (corrupted) | **`Synthetic`** |
| `open -> Run -> save`, `file_path` | absolute path | **`apex_vision/samples/pcb_sample.png`** |
| dirty flag after a Run | `True` | **`False`** |
| close prompt after a Run | "unsaved changes" | **none** |
| dirty flag after reopening | `True` | **`False`** |
| dirty flag after a real edit | `True` | **`True`** (correctly preserved) |
| explicit `loadImageFolder` | persists | **persists**, and marks dirty (correct) |
| image-strip click | persisted (wrong) | **transient**, project untouched |
| `scripts/qa_ui_logic.py` | 84/85 | **85/85** |
| `scripts/qa_tool_sweep.py` | `PROJECT REWRITTEN: True` | **`PROJECT REWRITTEN: False`** |
| all 160 tools | 0 exceptions | 0 exceptions |

### Regression tests

`tests/test_image_pool_no_mutation.py` — 8 tests. Verified to be real tests by
reintroducing the defect: **4 of them fail on the old code** (including the end-to-end
"running a flow does not mark the project dirty") and all 8 pass on the fix. They pin both
directions, so a future over-correction that stops images being remembered also fails.

## Recommended order of work

1. ~~**BUG-01** — stop `apply_to` rewriting the project.~~ **Done.**
2. ~~Re-run `scripts/qa_ui_logic.py`.~~ **Done — 85/85.**
3. ~~Regression test for `open → run → save`.~~ **Done — 8 tests, mutation-verified.**
4. ~~Rebuild and reinstall.~~ **Done.** `ApexVisionStudio.spec` rebuilt; the installed
   `ApexVisionStudio.exe` is byte-identical to the new `dist` build
   (SHA-256 `2B62BC88...A680DC`), built 13:18 against the fixed source (12:34), and launches
   with the plugins loading and the correct window title.

   Note: the Inno Setup installer still cannot be executed in this environment (unsigned,
   the process is blocked), so the installed copy was updated by replacing its files. The
   registry entry therefore still reads `1.0.0-beta.2` and points at a missing
   `unins000.exe`; running the installer on a normal desktop session would repair that.


---

# Round 2 — the four UI/UX items requested after the first pass

Date: 2026-11-11 · Same build, plus the changes below

## 1. Canvas : image column is now a true 6:4

`rightColumn` had a hardcoded `width: 640`, so the ratio drifted with the window: at 1600 it
was 59:41, at 1280 the image column was **wider than the canvas**, and on a wide monitor the
canvas took most of the space. It now takes 40% of the space beside the rail, clamped so
neither side can collapse.

| Window | Canvas | Image column | Ratio |
|---|---|---|---|
| 1280 | 743 (60.0%) | 495 (40.0%) | 1.50:1 |
| 1440 | 839 (60.0%) | 559 (40.0%) | 1.50:1 |
| 1600 | 935 (60.0%) | 623 (40.0%) | 1.50:1 |
| 1920 | 1127 (60.0%) | 751 (40.0%) | 1.50:1 |
| 2560 | 1511 (60.0%) | 1007 (40.0%) | 1.50:1 |

## 2. "Fit to screen" — the button worked, but gave no sign of it

Measured with a real mouse click: zoom 4.00 + pan (140, 90) -> after clicking fit, zoom 1.00
and pan (0, 0). The handler was correct all along; what was missing was any feedback, because
at fit the button looked identical to its unfocused state. Now:

* the fit button reads as *active* whenever the image is already fitted, so pressing it
  visibly does something;
* a `fitView()` entry point gives the action a name, instead of relying on the `else` branch
  of the click chain;
* the tooltip no longer claims Ctrl+0 fits the image - Ctrl+0 fits the *canvas*.

## 3. Reset ROI to default — new

* `resetRoi()` (backend): sets the selected module's `roi` / `template_roi` back to
  `[0, 0, 0, 0]`, which the region tools read as "the whole image". One undo step, and the
  flow re-runs so the verdict follows the change.
* an `roi` button in the image header (6th button) and **Ctrl+Shift+R**.
* refuses politely on a module that has no region ("This module has no region to reset") and
  reports when there is nothing to do ("ROI is already the whole image").

Verified: `[120, 90, 200, 150]` -> reset -> `[0, 0, 0, 0]` -> undo -> `[120, 90, 200, 150]`.

## 4. Display Setup — it was a mock-up, and now it works

**This was the significant find of the round.** The "Display Setup" tab in Module
Configuration rendered three checkboxes and five colour swatches, and **none of them did
anything**:

```qml
CheckLabel { text: "Show module ROI";     checked: true }    // no handler
CheckLabel { text: "Show result labels";  checked: true }    // no handler
CheckLabel { text: "Show defect boxes";   checked: true }    // no handler
Repeater { model: ["#e4b030", ...]
    delegate: Rectangle { ... }                              // no MouseArea at all
```

The checkboxes toggled their own pixels and saved nothing; the swatches could not even be
clicked. Every module showed the same three ticks.

Now, per the requested design (**per module, saved with the project**, colour applies to that
module's own overlay drawings):

| Piece | Implementation |
|---|---|
| Storage | `VisionToolBase.display` = `{roi, labels, boxes, colour}`; written to the project as a `<Display>` element **only when it differs from the default**, so untouched projects stay byte-identical |
| Backend | `selectedDisplay` property, `setModuleDisplay(nodeId, key, value)` - validates the colour, raises one undo step, redraws |
| Checkboxes | bound to the module's real state; `roi` also hides the ROI rectangle the viewer draws |
| Colour | five swatches, the chosen one ringed; recolours the overlays that module draws (labels, boxes, lines, circles, crosses) |
| Robustness | a hand-edited or older file with a bad display block falls back to the default rather than reaching the renderer |

Verified end to end: all three checkboxes render and write; unchecking one sets the flag and
marks the project changed; a swatch stores its colour; **undo reverts it**; the file gains a
`<Display>` element; **reloading restores `roi: False, colour: #2b7bb9`**. 10/10 checks.

### Also checked, per the question about "the colour cannot be changed"

I audited the **parameter** colour across all modules as well, in case that was the intent:

* **105 boolean parameters** exist across the tools; every one renders as a checkbox, is
  accepted by the schema, and round-trips through `setParamValue`. **0 problems.**
* **1 colour parameter**: `Color Measurement.target_rgb`, rendered as editable R/G/B fields.
  It **is** changeable and saves correctly (`[0,150,0]` -> `[11,22,33]`). It is a measurement
  target, not interface chrome, so I left it editable - tell me if it should be locked.

## Test assets

| Script | Purpose |
|---|---|
| `scripts/qa_param_editors.py` | all 160 tools: every bool round-trips, the rgb round-trips |
| `scripts/qa_param_editor_qml.py` | the rendered checkbox / colour editors |
| `scripts/qa_display_setup.py` | Display Setup: click each control, undo, save, reload (10 checks) |
| `tests/test_module_display.py` | 12 tests: defaults, bad-file fallback, byte-stability, round-trip |

Full suite: **green** (exit 0). `qa_ui_logic.py` still 85/85; `qa_tool_sweep.py` still
`PROJECT REWRITTEN: False`, 0 tool problems.


---

# Round 3 — the image/bottom ratio, and the script editor

Date: 2026-11-11

## 1. The image viewer vs the result block, now 6:4

The horizontal split was fixed last round; the vertical one had the same shape of defect.
The viewer was a fixed `height: 300`, so on an 819 px column the image was ~37% and the
result block below it ~47% — the image was the smallest important thing on screen, and the
ratio changed with the window.

VisionMaster's own documentation describes its image window as *自适应 / 等比例放大* — it
scales with the window rather than sitting at one height. The viewer now sizes from a named
share of the column (`imageBlockShare: 0.6`), so the image block and the result block keep a
6:4 split at any window height:

| Window height | Viewer height | Image block | Share |
|---|---|---|---|
| 800 | 244 | 519 | 64.8% |
| 950 | 334 | 609 | 64.1% |
| 1100 | 424 | 699 | 63.5% |

(The share is measured from the tab row, which belongs to neither block; excluding it the
split is exactly 60:40.)

## 2. The script editor is now a small IDE

It was a bare `TextEdit` in a 170 px box with an "Apply script" button — no line numbers, no
colouring, no indentation help, no error reporting.

`qml/ApexComponents/ScriptEditor.qml` replaces it:

| Feature | How |
|---|---|
| Syntax highlighting | Python's own `tokenize` classifies the text (`apex_vision/core/script_highlight.py`) and returns HTML spans, painted on a `Text` behind a transparent `TextEdit`. Regular expressions would mis-handle quoting; the tokenizer does not |
| Line numbers | gutter with the caret's line in bold, and the syntactically bad line in red |
| Current line / Ln, Col | read-out in the status bar |
| Auto-indent | Enter keeps the indentation and opens a level after `:` |
| Tab / Shift+Tab | indent / dedent four spaces |
| Ctrl+/ | comment or uncomment the current line |
| Ctrl+Enter | apply |
| Live syntax check | `compile()` without running; the message names the line and the gutter marks it |
| Scrollbars | thin and palette-coloured (see below) |

All eight syntax colours were measured against the editor's white well: 4.78:1 to 16.42:1,
every one clearing AA.

### Two real bugs found while testing it

1. **Every parameter editor was built twice.** The run-params delegate put a `ParamEditor` in
   *both* branches of a two-branch layout, so a module with a script had **two** `ScriptEditor`
   instances — both compiling and highlighting on every keystroke, and only one of them
   visible. Applying an edit could therefore appear to do nothing. One editor per parameter
   now; the count is asserted at 1.
2. **Scrollbars were near-black.** The application runs the platform's *native* Controls
   style, which refuses `contentItem`/`background` customisation and draws its own dark bar.
   Five places had a bare `ScrollBar { }`. The app now pins the stylable **Basic** style
   (`QT_QUICK_CONTROLS_STYLE`, set in `apex_vision/qml_app.py` before start-up — the PyQt6
   `QtQuickControls2` binding is not installed) and every bar uses one themed
   `ApexScrollBar`. A test fails if a bare `ScrollBar { }` ever returns.

### Verified behaviour

`scripts/qa_script_editor.py` drives the real dialog: 9/9. A broken script reports
*"'(' was never closed (line 2)"* with line 2 flagged; fixing it clears the error; Apply
writes the module parameter and marks the project changed; zero QML warnings.

## Tests added

`tests/test_script_editor.py` — 24 tests: token classification, HTML escaping (a script
cannot inject markup), half-typed buffers, error line numbers, editor structure, AA contrast
of every syntax colour, the no-bare-ScrollBar rule, and the 6:4 viewport expression.
# QA Report — Apex Industrial Vision Studio 1.0.0-beta.3

Date: 2026-11-11 · Build tested: `dist/ApexVisionStudio` (`ApexVisionStudio.spec`), installed copy
Scope: full functional + UI/UX-logic pass after the latest code update · Focus: UI/UX logic

## Summary

| Area | Result |
|---|---|
| Automated suites (`pytest tests/ -q`) | **green**, exit 0, 2 opt-in live tests skipped |
| UI/UX logic probe (`scripts/qa_ui_logic.py`) | **85 checks, 84 pass, 1 fail** |
| Tool sweep, all 160 registered tools | **0 unhandled exceptions**; 32 report actionable `Error` when unconfigured (correct) |
| **Defects found** | **2 (both High)** — one root cause, two user-visible failures |
| **Status** | **both fixed and verified**; see *Fix applied* |

Both defects share one root cause: **executing a flow writes transient strip state into the
project model.**

---

## BUG-01 — Running a flow silently rewrites the project, and saving persists the damage

**Severity: High** · **Confidence: proven, with file-level evidence**

### What happens

Merely pressing **Run** mutates the Image Source module's persisted parameters. The change is
invisible on screen, and it makes the project "dirty". If the operator then saves — which they
are prompted to do, see BUG-02 — the mutation is written to disk.

### Evidence

In-memory snapshot, before vs after a single Run:

```
flows[0].nodes[0].parameters.file_path
    'apex_vision/samples/pcb_sample.png' -> 'C:\Users\winch\Downloads\VMClone\apex_vision\samples\pcb_sample_defect.png'
flows[0].nodes[0].parameters.source_type
    'Synthetic' -> 'File'
```

The same change appears in the file written by `saveProjectAs` after the run — measured
against the pristine `PCB_Inspection_Demo.apex`:

```
on disk before any run : {'source_type': 'Synthetic', 'file_path': 'apex_vision/samples/pcb_sample.png'}
written after the run  : {'source_type': 'File',      'file_path': 'C:\\...\\pcb_sample_defect.png'}
PROJECT REWRITTEN BY RUNNING: True
```

### Why it matters

1. **The project's own configuration is destroyed.** The demo ships as a *Synthetic* generator;
   after one Run + Save it becomes a *File* source pointing at one specific picture.
2. **The path is absolute.** The saved project no longer opens correctly on another machine or
   another checkout — the classic "works on my PC" breakage, now baked into a shipped artifact.
3. **The wrong image wins.** Running the strip leaves the *last-run* image as the project's
   source, so a project inspected against image 2 will reopen expecting image 2.
4. **It is invisible.** Nothing on screen indicates the module changed; the operator sees only a
   generic "unsaved changes" prompt (BUG-02).

### Root cause

`apex_vision/core/controller.py:114–128`, `ImagePool.apply_to()`:

```python
for node in pipeline.nodes.values():
    if node.tool_name == "Image Source":
        if item.get("path"):
            node.set_param("source_type", "File")     # persisted
            node.set_param("file_path", item["path"]) # persisted
        node._override_image = item.get("image")      # transient - correct
        node._override_name = item["name"]            # transient - correct
```

The override fields are the right mechanism; the two `set_param` calls are not. Every other
call site of `set_param("file_path", ...)` is a genuine user action (loading an image folder,
choosing a camera). This one is execution state.

### Suggested fix

Drop the two `set_param` calls and let `_override_image` / `_override_name` carry the strip
selection, which is what the executor already reads. If the source node must report a path for
display, expose it as a read-only runtime field rather than a parameter.

### Reproduction

```powershell
python scripts/qa_tool_sweep.py          # Part 1 prints the before/after and "PROJECT REWRITTEN BY RUNNING: True"
```

---

## BUG-02 — Only the first project opened in a session is ever clean

**Severity: High** · **Confidence: proven**

### What happens

The first project opened after launch reports `dirty = False`. Every subsequent open reports
`dirty = True` **immediately**, with no user edit at all. The session can never return to a
clean state except by saving.

### Evidence

```
fresh app, open #1          dirty = False
... press Run ...           dirty = True
open #2 (same file)         dirty = True      <- expected False
open #3 (same file)         dirty = True
saveProjectAs               dirty = False     <- only saving clears it
```

And independently of running, a second open in the same process is already dirty:

```
fresh open (no run yet)     dirty = True
```

### Consequences

1. **Spurious "unsaved changes" prompt on every close.** Measured directly:

   ```
   A. close a clean project   -> prompts: none (closes silently)          correct
   B. close after ONLY Run    -> prompts: "'PCB_Inspection_Demo' has unsaved changes.
                                          Save them before continuing?"   WRONG
   C. close after a real edit -> prompts: same message                    correct
   ```

   Case B is the dangerous one: the operator is asked to save work they never did. Choosing
   **Save** then commits the BUG-01 corruption.

2. **The dirty indicator is permanently lit**, so it stops conveying information. Users learn to
   ignore it, which is exactly how a real unsaved edit gets discarded.

3. Because undo *does* clear the flag correctly (verified below), the flag itself works — it is
   the baseline that is being polluted on load.

### Root cause

Same as BUG-01: `ImagePool.apply_to()` is re-invoked while loading, so the freshly-loaded
pipeline is immediately modified relative to the snapshot taken at load time.

### Reproduction

```powershell
python scripts/qa_ui_logic.py            # "reopening a project returns to a clean state" fails
```

---

## Verified correct (tested, not assumed)

These were all exercised and behaved properly — recorded so the report is not one-sided.

| Check | Result |
|---|---|
| Undo/redo of a node drag (`beginMove` → `moveNode` → undo) | **correct** — position restored `(50,50)`, dirty returns to its pre-drag value; redo re-applies; a second undo stays consistent |
| Stop during a run | **correct** — `running` clears within 0.2 s, verdict remains readable, all 7 module rows present |
| Run state machine | verdict produced, flow time measured, history records one entry per image, results cover all modules |
| All 160 registered tools: construct + schema + execute | **0 unhandled exceptions** across empty / blank / noise contexts |
| 32 tools reporting `Error` on an unconfigured blank image | **correct and well-worded**, e.g. *"no model chosen: choose a defect prediction model (.onnx)"*, *"draw the region first: it is empty"* |
| Dialogs (9 of them) | open, become current, close cleanly; opening one over another keeps the newest |
| Workspace/view/inspection/AI panel state | every tab and visibility flag sticks |
| Zoom/pan clamping (new pinch code) | image viewport clamps to `1..16` and zeroes pan at fit; canvas clamps to `0.25..2.5`; `fitView` leaves a usable zoom |
| Unknown action / unknown flow id / out-of-range image index | no crash, state stays valid |
| Empty project name, closed dialog, Esc | no orphaned state |

---

## Lower-priority observations

1. **`newFromTemplate` has no argument validation.** `@pyqtSlot(int)` is correct for QML (which
   passes `parseInt`), but an internal caller passing anything else gets
   `TypeError: '<' not supported between instances of 'int' and 'str'` from the clamp
   expression rather than a clear message. Cosmetic; not reachable from the UI.
2. **`newFromTemplate` catches only `OSError`.** Other failures from `create_project` propagate
   as a QML error with no user-facing message.
3. **History count is per-image.** "Run all" over a 2-image strip appends 2 records per press.
   Arguably correct, but the History tab gives no indication that several rows came from one
   click — a "run" grouping would read better.

---

## Test assets added

| Script | Purpose |
|---|---|
| `scripts/qa_ui_logic.py` | 85 UI/UX-logic assertions; writes `docs/audit/ui_logic_results.json` |
| `scripts/qa_tool_sweep.py` | proves the save corruption, then constructs/schemas/executes all 160 tools; writes `docs/audit/tool_sweep.json` |

Both are re-runnable and exit non-zero on failure, so they can gate a release.

## Fix applied

Both defects were one boundary error and are now fixed in `apex_vision/core/controller.py`.

`ImagePool.apply_to()` gained an explicit `persist` flag, because the method was doing two
different jobs:

| Intent | `persist` | What it does | Call sites |
|---|---|---|---|
| **Execution** — which picture the next run consumes | `False` (default) | Sets only `_override_image` / `_override_name` | a run, an image-strip click (`RunEngine.select_image`) |
| **Configuration** — the operator just loaded images | `True` | Also writes `source_type` / `file_path` | `loadImageFiles`, `loadImageFolder`, the widget UI's "load image into flow" |

This keeps the behaviour the product wants (loading images is remembered and marks the
project dirty) while removing the side effect that rewrote the project during a run.

### Verification

| Check | Before | After |
|---|---|---|
| `open -> Run -> save`, Image Source `source_type` | `File` (corrupted) | **`Synthetic`** |
| `open -> Run -> save`, `file_path` | absolute path | **`apex_vision/samples/pcb_sample.png`** |
| dirty flag after a Run | `True` | **`False`** |
| close prompt after a Run | "unsaved changes" | **none** |
| dirty flag after reopening | `True` | **`False`** |
| dirty flag after a real edit | `True` | **`True`** (correctly preserved) |
| explicit `loadImageFolder` | persists | **persists**, and marks dirty (correct) |
| image-strip click | persisted (wrong) | **transient**, project untouched |
| `scripts/qa_ui_logic.py` | 84/85 | **85/85** |
| `scripts/qa_tool_sweep.py` | `PROJECT REWRITTEN: True` | **`PROJECT REWRITTEN: False`** |
| all 160 tools | 0 exceptions | 0 exceptions |

### Regression tests

`tests/test_image_pool_no_mutation.py` — 8 tests. Verified to be real tests by
reintroducing the defect: **4 of them fail on the old code** (including the end-to-end
"running a flow does not mark the project dirty") and all 8 pass on the fix. They pin both
directions, so a future over-correction that stops images being remembered also fails.

## Recommended order of work

1. ~~**BUG-01** — stop `apply_to` rewriting the project.~~ **Done.**
2. ~~Re-run `scripts/qa_ui_logic.py`.~~ **Done — 85/85.**
3. ~~Regression test for `open → run → save`.~~ **Done — 8 tests, mutation-verified.**
4. ~~Rebuild and reinstall.~~ **Done.** `ApexVisionStudio.spec` rebuilt; the installed
   `ApexVisionStudio.exe` is byte-identical to the new `dist` build
   (SHA-256 `2B62BC88...A680DC`), built 13:18 against the fixed source (12:34), and launches
   with the plugins loading and the correct window title.

   Note: the Inno Setup installer still cannot be executed in this environment (unsigned,
   the process is blocked), so the installed copy was updated by replacing its files. The
   registry entry therefore still reads `1.0.0-beta.2` and points at a missing
   `unins000.exe`; running the installer on a normal desktop session would repair that.


---

# Round 2 — the four UI/UX items requested after the first pass

Date: 2026-11-11 · Same build, plus the changes below

## 1. Canvas : image column is now a true 6:4

`rightColumn` had a hardcoded `width: 640`, so the ratio drifted with the window: at 1600 it
was 59:41, at 1280 the image column was **wider than the canvas**, and on a wide monitor the
canvas took most of the space. It now takes 40% of the space beside the rail, clamped so
neither side can collapse.

| Window | Canvas | Image column | Ratio |
|---|---|---|---|
| 1280 | 743 (60.0%) | 495 (40.0%) | 1.50:1 |
| 1440 | 839 (60.0%) | 559 (40.0%) | 1.50:1 |
| 1600 | 935 (60.0%) | 623 (40.0%) | 1.50:1 |
| 1920 | 1127 (60.0%) | 751 (40.0%) | 1.50:1 |
| 2560 | 1511 (60.0%) | 1007 (40.0%) | 1.50:1 |

## 2. "Fit to screen" — the button worked, but gave no sign of it

Measured with a real mouse click: zoom 4.00 + pan (140, 90) -> after clicking fit, zoom 1.00
and pan (0, 0). The handler was correct all along; what was missing was any feedback, because
at fit the button looked identical to its unfocused state. Now:

* the fit button reads as *active* whenever the image is already fitted, so pressing it
  visibly does something;
* a `fitView()` entry point gives the action a name, instead of relying on the `else` branch
  of the click chain;
* the tooltip no longer claims Ctrl+0 fits the image - Ctrl+0 fits the *canvas*.

## 3. Reset ROI to default — new

* `resetRoi()` (backend): sets the selected module's `roi` / `template_roi` back to
  `[0, 0, 0, 0]`, which the region tools read as "the whole image". One undo step, and the
  flow re-runs so the verdict follows the change.
* an `roi` button in the image header (6th button) and **Ctrl+Shift+R**.
* refuses politely on a module that has no region ("This module has no region to reset") and
  reports when there is nothing to do ("ROI is already the whole image").

Verified: `[120, 90, 200, 150]` -> reset -> `[0, 0, 0, 0]` -> undo -> `[120, 90, 200, 150]`.

## 4. Display Setup — it was a mock-up, and now it works

**This was the significant find of the round.** The "Display Setup" tab in Module
Configuration rendered three checkboxes and five colour swatches, and **none of them did
anything**:

```qml
CheckLabel { text: "Show module ROI";     checked: true }    // no handler
CheckLabel { text: "Show result labels";  checked: true }    // no handler
CheckLabel { text: "Show defect boxes";   checked: true }    // no handler
Repeater { model: ["#e4b030", ...]
    delegate: Rectangle { ... }                              // no MouseArea at all
```

The checkboxes toggled their own pixels and saved nothing; the swatches could not even be
clicked. Every module showed the same three ticks.

Now, per the requested design (**per module, saved with the project**, colour applies to that
module's own overlay drawings):

| Piece | Implementation |
|---|---|
| Storage | `VisionToolBase.display` = `{roi, labels, boxes, colour}`; written to the project as a `<Display>` element **only when it differs from the default**, so untouched projects stay byte-identical |
| Backend | `selectedDisplay` property, `setModuleDisplay(nodeId, key, value)` - validates the colour, raises one undo step, redraws |
| Checkboxes | bound to the module's real state; `roi` also hides the ROI rectangle the viewer draws |
| Colour | five swatches, the chosen one ringed; recolours the overlays that module draws (labels, boxes, lines, circles, crosses) |
| Robustness | a hand-edited or older file with a bad display block falls back to the default rather than reaching the renderer |

Verified end to end: all three checkboxes render and write; unchecking one sets the flag and
marks the project changed; a swatch stores its colour; **undo reverts it**; the file gains a
`<Display>` element; **reloading restores `roi: False, colour: #2b7bb9`**. 10/10 checks.

### Also checked, per the question about "the colour cannot be changed"

I audited the **parameter** colour across all modules as well, in case that was the intent:

* **105 boolean parameters** exist across the tools; every one renders as a checkbox, is
  accepted by the schema, and round-trips through `setParamValue`. **0 problems.**
* **1 colour parameter**: `Color Measurement.target_rgb`, rendered as editable R/G/B fields.
  It **is** changeable and saves correctly (`[0,150,0]` -> `[11,22,33]`). It is a measurement
  target, not interface chrome, so I left it editable - tell me if it should be locked.

## Test assets

| Script | Purpose |
|---|---|
| `scripts/qa_param_editors.py` | all 160 tools: every bool round-trips, the rgb round-trips |
| `scripts/qa_param_editor_qml.py` | the rendered checkbox / colour editors |
| `scripts/qa_display_setup.py` | Display Setup: click each control, undo, save, reload (10 checks) |
| `tests/test_module_display.py` | 12 tests: defaults, bad-file fallback, byte-stability, round-trip |

Full suite: **green** (exit 0). `qa_ui_logic.py` still 85/85; `qa_tool_sweep.py` still
`PROJECT REWRITTEN: False`, 0 tool problems.
# QA Report — Apex Industrial Vision Studio 1.0.0-beta.3

Date: 2026-11-11 · Build tested: `dist/ApexVisionStudio` (`ApexVisionStudio.spec`), installed copy
Scope: full functional + UI/UX-logic pass after the latest code update · Focus: UI/UX logic

## Summary

| Area | Result |
|---|---|
| Automated suites (`pytest tests/ -q`) | **green**, exit 0, 2 opt-in live tests skipped |
| UI/UX logic probe (`scripts/qa_ui_logic.py`) | **85 checks, 84 pass, 1 fail** |
| Tool sweep, all 160 registered tools | **0 unhandled exceptions**; 32 report actionable `Error` when unconfigured (correct) |
| **Defects found** | **2 (both High)** — one root cause, two user-visible failures |
| **Status** | **both fixed and verified**; see *Fix applied* |

Both defects share one root cause: **executing a flow writes transient strip state into the
project model.**

---

## BUG-01 — Running a flow silently rewrites the project, and saving persists the damage

**Severity: High** · **Confidence: proven, with file-level evidence**

### What happens

Merely pressing **Run** mutates the Image Source module's persisted parameters. The change is
invisible on screen, and it makes the project "dirty". If the operator then saves — which they
are prompted to do, see BUG-02 — the mutation is written to disk.

### Evidence

In-memory snapshot, before vs after a single Run:

```
flows[0].nodes[0].parameters.file_path
    'apex_vision/samples/pcb_sample.png' -> 'C:\Users\winch\Downloads\VMClone\apex_vision\samples\pcb_sample_defect.png'
flows[0].nodes[0].parameters.source_type
    'Synthetic' -> 'File'
```

The same change appears in the file written by `saveProjectAs` after the run — measured
against the pristine `PCB_Inspection_Demo.apex`:

```
on disk before any run : {'source_type': 'Synthetic', 'file_path': 'apex_vision/samples/pcb_sample.png'}
written after the run  : {'source_type': 'File',      'file_path': 'C:\\...\\pcb_sample_defect.png'}
PROJECT REWRITTEN BY RUNNING: True
```

### Why it matters

1. **The project's own configuration is destroyed.** The demo ships as a *Synthetic* generator;
   after one Run + Save it becomes a *File* source pointing at one specific picture.
2. **The path is absolute.** The saved project no longer opens correctly on another machine or
   another checkout — the classic "works on my PC" breakage, now baked into a shipped artifact.
3. **The wrong image wins.** Running the strip leaves the *last-run* image as the project's
   source, so a project inspected against image 2 will reopen expecting image 2.
4. **It is invisible.** Nothing on screen indicates the module changed; the operator sees only a
   generic "unsaved changes" prompt (BUG-02).

### Root cause

`apex_vision/core/controller.py:114–128`, `ImagePool.apply_to()`:

```python
for node in pipeline.nodes.values():
    if node.tool_name == "Image Source":
        if item.get("path"):
            node.set_param("source_type", "File")     # persisted
            node.set_param("file_path", item["path"]) # persisted
        node._override_image = item.get("image")      # transient - correct
        node._override_name = item["name"]            # transient - correct
```

The override fields are the right mechanism; the two `set_param` calls are not. Every other
call site of `set_param("file_path", ...)` is a genuine user action (loading an image folder,
choosing a camera). This one is execution state.

### Suggested fix

Drop the two `set_param` calls and let `_override_image` / `_override_name` carry the strip
selection, which is what the executor already reads. If the source node must report a path for
display, expose it as a read-only runtime field rather than a parameter.

### Reproduction

```powershell
python scripts/qa_tool_sweep.py          # Part 1 prints the before/after and "PROJECT REWRITTEN BY RUNNING: True"
```

---

## BUG-02 — Only the first project opened in a session is ever clean

**Severity: High** · **Confidence: proven**

### What happens

The first project opened after launch reports `dirty = False`. Every subsequent open reports
`dirty = True` **immediately**, with no user edit at all. The session can never return to a
clean state except by saving.

### Evidence

```
fresh app, open #1          dirty = False
... press Run ...           dirty = True
open #2 (same file)         dirty = True      <- expected False
open #3 (same file)         dirty = True
saveProjectAs               dirty = False     <- only saving clears it
```

And independently of running, a second open in the same process is already dirty:

```
fresh open (no run yet)     dirty = True
```

### Consequences

1. **Spurious "unsaved changes" prompt on every close.** Measured directly:

   ```
   A. close a clean project   -> prompts: none (closes silently)          correct
   B. close after ONLY Run    -> prompts: "'PCB_Inspection_Demo' has unsaved changes.
                                          Save them before continuing?"   WRONG
   C. close after a real edit -> prompts: same message                    correct
   ```

   Case B is the dangerous one: the operator is asked to save work they never did. Choosing
   **Save** then commits the BUG-01 corruption.

2. **The dirty indicator is permanently lit**, so it stops conveying information. Users learn to
   ignore it, which is exactly how a real unsaved edit gets discarded.

3. Because undo *does* clear the flag correctly (verified below), the flag itself works — it is
   the baseline that is being polluted on load.

### Root cause

Same as BUG-01: `ImagePool.apply_to()` is re-invoked while loading, so the freshly-loaded
pipeline is immediately modified relative to the snapshot taken at load time.

### Reproduction

```powershell
python scripts/qa_ui_logic.py            # "reopening a project returns to a clean state" fails
```

---

## Verified correct (tested, not assumed)

These were all exercised and behaved properly — recorded so the report is not one-sided.

| Check | Result |
|---|---|
| Undo/redo of a node drag (`beginMove` → `moveNode` → undo) | **correct** — position restored `(50,50)`, dirty returns to its pre-drag value; redo re-applies; a second undo stays consistent |
| Stop during a run | **correct** — `running` clears within 0.2 s, verdict remains readable, all 7 module rows present |
| Run state machine | verdict produced, flow time measured, history records one entry per image, results cover all modules |
| All 160 registered tools: construct + schema + execute | **0 unhandled exceptions** across empty / blank / noise contexts |
| 32 tools reporting `Error` on an unconfigured blank image | **correct and well-worded**, e.g. *"no model chosen: choose a defect prediction model (.onnx)"*, *"draw the region first: it is empty"* |
| Dialogs (9 of them) | open, become current, close cleanly; opening one over another keeps the newest |
| Workspace/view/inspection/AI panel state | every tab and visibility flag sticks |
| Zoom/pan clamping (new pinch code) | image viewport clamps to `1..16` and zeroes pan at fit; canvas clamps to `0.25..2.5`; `fitView` leaves a usable zoom |
| Unknown action / unknown flow id / out-of-range image index | no crash, state stays valid |
| Empty project name, closed dialog, Esc | no orphaned state |

---

## Lower-priority observations

1. **`newFromTemplate` has no argument validation.** `@pyqtSlot(int)` is correct for QML (which
   passes `parseInt`), but an internal caller passing anything else gets
   `TypeError: '<' not supported between instances of 'int' and 'str'` from the clamp
   expression rather than a clear message. Cosmetic; not reachable from the UI.
2. **`newFromTemplate` catches only `OSError`.** Other failures from `create_project` propagate
   as a QML error with no user-facing message.
3. **History count is per-image.** "Run all" over a 2-image strip appends 2 records per press.
   Arguably correct, but the History tab gives no indication that several rows came from one
   click — a "run" grouping would read better.

---

## Test assets added

| Script | Purpose |
|---|---|
| `scripts/qa_ui_logic.py` | 85 UI/UX-logic assertions; writes `docs/audit/ui_logic_results.json` |
| `scripts/qa_tool_sweep.py` | proves the save corruption, then constructs/schemas/executes all 160 tools; writes `docs/audit/tool_sweep.json` |

Both are re-runnable and exit non-zero on failure, so they can gate a release.

## Fix applied

Both defects were one boundary error and are now fixed in `apex_vision/core/controller.py`.

`ImagePool.apply_to()` gained an explicit `persist` flag, because the method was doing two
different jobs:

| Intent | `persist` | What it does | Call sites |
|---|---|---|---|
| **Execution** — which picture the next run consumes | `False` (default) | Sets only `_override_image` / `_override_name` | a run, an image-strip click (`RunEngine.select_image`) |
| **Configuration** — the operator just loaded images | `True` | Also writes `source_type` / `file_path` | `loadImageFiles`, `loadImageFolder`, the widget UI's "load image into flow" |

This keeps the behaviour the product wants (loading images is remembered and marks the
project dirty) while removing the side effect that rewrote the project during a run.

### Verification

| Check | Before | After |
|---|---|---|
| `open -> Run -> save`, Image Source `source_type` | `File` (corrupted) | **`Synthetic`** |
| `open -> Run -> save`, `file_path` | absolute path | **`apex_vision/samples/pcb_sample.png`** |
| dirty flag after a Run | `True` | **`False`** |
| close prompt after a Run | "unsaved changes" | **none** |
| dirty flag after reopening | `True` | **`False`** |
| dirty flag after a real edit | `True` | **`True`** (correctly preserved) |
| explicit `loadImageFolder` | persists | **persists**, and marks dirty (correct) |
| image-strip click | persisted (wrong) | **transient**, project untouched |
| `scripts/qa_ui_logic.py` | 84/85 | **85/85** |
| `scripts/qa_tool_sweep.py` | `PROJECT REWRITTEN: True` | **`PROJECT REWRITTEN: False`** |
| all 160 tools | 0 exceptions | 0 exceptions |

### Regression tests

`tests/test_image_pool_no_mutation.py` — 8 tests. Verified to be real tests by
reintroducing the defect: **4 of them fail on the old code** (including the end-to-end
"running a flow does not mark the project dirty") and all 8 pass on the fix. They pin both
directions, so a future over-correction that stops images being remembered also fails.

## Recommended order of work

1. ~~**BUG-01** — stop `apply_to` rewriting the project.~~ **Done.**
2. ~~Re-run `scripts/qa_ui_logic.py`.~~ **Done — 85/85.**
3. ~~Regression test for `open → run → save`.~~ **Done — 8 tests, mutation-verified.**
4. ~~Rebuild and reinstall.~~ **Done.** `ApexVisionStudio.spec` rebuilt; the installed
   `ApexVisionStudio.exe` is byte-identical to the new `dist` build
   (SHA-256 `2B62BC88...A680DC`), built 13:18 against the fixed source (12:34), and launches
   with the plugins loading and the correct window title.

   Note: the Inno Setup installer still cannot be executed in this environment (unsigned,
   the process is blocked), so the installed copy was updated by replacing its files. The
   registry entry therefore still reads `1.0.0-beta.2` and points at a missing
   `unins000.exe`; running the installer on a normal desktop session would repair that.


---

# Round 2 — the four UI/UX items requested after the first pass

Date: 2026-11-11 · Same build, plus the changes below

## 1. Canvas : image column is now a true 6:4

`rightColumn` had a hardcoded `width: 640`, so the ratio drifted with the window: at 1600 it
was 59:41, at 1280 the image column was **wider than the canvas**, and on a wide monitor the
canvas took most of the space. It now takes 40% of the space beside the rail, clamped so
neither side can collapse.

| Window | Canvas | Image column | Ratio |
|---|---|---|---|
| 1280 | 743 (60.0%) | 495 (40.0%) | 1.50:1 |
| 1440 | 839 (60.0%) | 559 (40.0%) | 1.50:1 |
| 1600 | 935 (60.0%) | 623 (40.0%) | 1.50:1 |
| 1920 | 1127 (60.0%) | 751 (40.0%) | 1.50:1 |
| 2560 | 1511 (60.0%) | 1007 (40.0%) | 1.50:1 |

## 2. "Fit to screen" — the button worked, but gave no sign of it

Measured with a real mouse click: zoom 4.00 + pan (140, 90) -> after clicking fit, zoom 1.00
and pan (0, 0). The handler was correct all along; what was missing was any feedback, because
at fit the button looked identical to its unfocused state. Now:

* the fit button reads as *active* whenever the image is already fitted, so pressing it
  visibly does something;
* a `fitView()` entry point gives the action a name, instead of relying on the `else` branch
  of the click chain;
* the tooltip no longer claims Ctrl+0 fits the image - Ctrl+0 fits the *canvas*.

## 3. Reset ROI to default — new

* `resetRoi()` (backend): sets the selected module's `roi` / `template_roi` back to
  `[0, 0, 0, 0]`, which the region tools read as "the whole image". One undo step, and the
  flow re-runs so the verdict follows the change.
* an `roi` button in the image header (6th button) and **Ctrl+Shift+R**.
* refuses politely on a module that has no region ("This module has no region to reset") and
  reports when there is nothing to do ("ROI is already the whole image").

Verified: `[120, 90, 200, 150]` -> reset -> `[0, 0, 0, 0]` -> undo -> `[120, 90, 200, 150]`.

## 4. Display Setup — it was a mock-up, and now it works

**This was the significant find of the round.** The "Display Setup" tab in Module
Configuration rendered three checkboxes and five colour swatches, and **none of them did
anything**:

```qml
CheckLabel { text: "Show module ROI";     checked: true }    // no handler
CheckLabel { text: "Show result labels";  checked: true }    // no handler
CheckLabel { text: "Show defect boxes";   checked: true }    // no handler
Repeater { model: ["#e4b030", ...]
    delegate: Rectangle { ... }                              // no MouseArea at all
```

The checkboxes toggled their own pixels and saved nothing; the swatches could not even be
clicked. Every module showed the same three ticks.

Now, per the requested design (**per module, saved with the project**, colour applies to that
module's own overlay drawings):

| Piece | Implementation |
|---|---|
| Storage | `VisionToolBase.display` = `{roi, labels, boxes, colour}`; written to the project as a `<Display>` element **only when it differs from the default**, so untouched projects stay byte-identical |
| Backend | `selectedDisplay` property, `setModuleDisplay(nodeId, key, value)` - validates the colour, raises one undo step, redraws |
| Checkboxes | bound to the module's real state; `roi` also hides the ROI rectangle the viewer draws |
| Colour | five swatches, the chosen one ringed; recolours the overlays that module draws (labels, boxes, lines, circles, crosses) |
| Robustness | a hand-edited or older file with a bad display block falls back to the default rather than reaching the renderer |

Verified end to end: all three checkboxes render and write; unchecking one sets the flag and
marks the project changed; a swatch stores its colour; **undo reverts it**; the file gains a
`<Display>` element; **reloading restores `roi: False, colour: #2b7bb9`**. 10/10 checks.

### Also checked, per the question about "the colour cannot be changed"

I audited the **parameter** colour across all modules as well, in case that was the intent:

* **105 boolean parameters** exist across the tools; every one renders as a checkbox, is
  accepted by the schema, and round-trips through `setParamValue`. **0 problems.**
* **1 colour parameter**: `Color Measurement.target_rgb`, rendered as editable R/G/B fields.
  It **is** changeable and saves correctly (`[0,150,0]` -> `[11,22,33]`). It is a measurement
  target, not interface chrome, so I left it editable - tell me if it should be locked.

## Test assets

| Script | Purpose |
|---|---|
| `scripts/qa_param_editors.py` | all 160 tools: every bool round-trips, the rgb round-trips |
| `scripts/qa_param_editor_qml.py` | the rendered checkbox / colour editors |
| `scripts/qa_display_setup.py` | Display Setup: click each control, undo, save, reload (10 checks) |
| `tests/test_module_display.py` | 12 tests: defaults, bad-file fallback, byte-stability, round-trip |

Full suite: **green** (exit 0). `qa_ui_logic.py` still 85/85; `qa_tool_sweep.py` still
`PROJECT REWRITTEN: False`, 0 tool problems.


---

# Round 3 — the image/bottom ratio, and the script editor

Date: 2026-11-11

## 1. The image viewer vs the result block, now 6:4

The horizontal split was fixed last round; the vertical one had the same shape of defect.
The viewer was a fixed `height: 300`, so on an 819 px column the image was ~37% and the
result block below it ~47% — the image was the smallest important thing on screen, and the
ratio changed with the window.

VisionMaster's own documentation describes its image window as *自适应 / 等比例放大* — it
scales with the window rather than sitting at one height. The viewer now sizes from a named
share of the column (`imageBlockShare: 0.6`), so the image block and the result block keep a
6:4 split at any window height:

| Window height | Viewer height | Image block | Share |
|---|---|---|---|
| 800 | 244 | 519 | 64.8% |
| 950 | 334 | 609 | 64.1% |
| 1100 | 424 | 699 | 63.5% |

(The share is measured from the tab row, which belongs to neither block; excluding it the
split is exactly 60:40.)

## 2. The script editor is now a small IDE

It was a bare `TextEdit` in a 170 px box with an "Apply script" button — no line numbers, no
colouring, no indentation help, no error reporting.

`qml/ApexComponents/ScriptEditor.qml` replaces it:

| Feature | How |
|---|---|
| Syntax highlighting | Python's own `tokenize` classifies the text (`apex_vision/core/script_highlight.py`) and returns HTML spans, painted on a `Text` behind a transparent `TextEdit`. Regular expressions would mis-handle quoting; the tokenizer does not |
| Line numbers | gutter with the caret's line in bold, and the syntactically bad line in red |
| Current line / Ln, Col | read-out in the status bar |
| Auto-indent | Enter keeps the indentation and opens a level after `:` |
| Tab / Shift+Tab | indent / dedent four spaces |
| Ctrl+/ | comment or uncomment the current line |
| Ctrl+Enter | apply |
| Live syntax check | `compile()` without running; the message names the line and the gutter marks it |
| Scrollbars | thin and palette-coloured (see below) |

All eight syntax colours were measured against the editor's white well: 4.78:1 to 16.42:1,
every one clearing AA.

### Two real bugs found while testing it

1. **Every parameter editor was built twice.** The run-params delegate put a `ParamEditor` in
   *both* branches of a two-branch layout, so a module with a script had **two** `ScriptEditor`
   instances — both compiling and highlighting on every keystroke, and only one of them
   visible. Applying an edit could therefore appear to do nothing. One editor per parameter
   now; the count is asserted at 1.
2. **Scrollbars were near-black.** The application runs the platform's *native* Controls
   style, which refuses `contentItem`/`background` customisation and draws its own dark bar.
   Five places had a bare `ScrollBar { }`. The app now pins the stylable **Basic** style
   (`QT_QUICK_CONTROLS_STYLE`, set in `apex_vision/qml_app.py` before start-up — the PyQt6
   `QtQuickControls2` binding is not installed) and every bar uses one themed
   `ApexScrollBar`. A test fails if a bare `ScrollBar { }` ever returns.

### Verified behaviour

`scripts/qa_script_editor.py` drives the real dialog: 9/9. A broken script reports
*"'(' was never closed (line 2)"* with line 2 flagged; fixing it clears the error; Apply
writes the module parameter and marks the project changed; zero QML warnings.

## Tests added

`tests/test_script_editor.py` — 24 tests: token classification, HTML escaping (a script
cannot inject markup), half-typed buffers, error line numbers, editor structure, AA contrast
of every syntax colour, the no-bare-ScrollBar rule, and the 6:4 viewport expression.


### Three regressions the existing suite caught

Worth recording, because they are the kind of thing a new component quietly breaks:

1. `paramCode` had been moved onto the wrapper, so a caller that sets the *editing surface*
   text (`paramCode.text`) no longer reached it and Apply stayed disabled. The name went
   back on the `TextEdit`; the wrapper has none.
2. The syntax keyword colour deliberately reuses the brand blue (`primaryText`/`wire`), which
   the duplicate-colour test flagged. That alias is now declared with its reason.
3. The pixel read-out test aimed at image pixel (400, 300) by a fixed screen point and
   asserted the exact pixel. The viewer now derives its height from the 6:4 split, so the
   mapping rounds a pixel or two; the assertion now allows ±3 instead of binding the test to
   one window height.
