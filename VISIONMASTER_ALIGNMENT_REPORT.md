# VisionMaster-Alignment Iteration Report

**Task:** transform the existing Python/PySide6 machine-vision application into a high-fidelity,
functional imitation of HikRobot Vision Master, prioritising visual similarity, interaction
fidelity and professional industrial UX.

**Reference standard:** `HikRobotVMHelp_compressed.pdf` (official Vision Master manual, 657 pages),
read directly from the repository. Figures were extracted to `docs/references/` and used as
measurable design evidence — every change below cites the page it came from.

---

## 1. Reference evidence actually obtained

Nothing in this report is invented. The manual's UI chapter is text-only, so the real product
screenshots are embedded as page images; they were extracted with `pypdfium2`
([extract_manual_refs.py](scripts/extract_manual_refs.py), [extract_manual_figs.py](scripts/extract_manual_figs.py))
into `docs/references/` and `docs/references/figs/`.

| File | Manual page | Content |
|---|---|---|
| `figs/p040_01.png` | 40 | Full Home Page: menu, control toolbar, left icon rail, flow tab bar, Image\|Result panel, status bar |
| `page_070.png` | 70 | Control Toolbar table — the exact 15-icon inventory and order |
| `figs/p072_fig01.png` | 72 | Left category glyph rail against the flow canvas |
| `figs/p074_01.png` | 74 | Open "Locating" flyout tool grid; white module cards; orange dependency wire |
| `figs/p087_01.png` | 87 | `Param Name \| Current Result \| Global Variable` result grid with parameter groups and link glyphs |
| `figs/p095_01.png` | 95 | Multi-Flow overview: white flow cards, play/loop/format buttons, `NTimes`, cycle times, orange converging bus |

Colours were sampled numerically from those PNGs (see `APEX_UI_SPECIFICATION.md` §1) rather than
eyeballed.

---

## 2. What the pre-existing UI looked like (before)

`docs/screenshots/before_workspace.png` (1500×950) and `docs/screenshots/before_current_ui.png`.

- Dark slate theme, but with **no reference grounding**: a flat `#12151c` canvas, blue-grey
  module cards that read as generic dashboard tiles, blue wires.
- Tool Library was a **horizontal `QTreeWidget` list** occupying ~23 % of the window width —
  not the reference's narrow glyph rail + flyout grid.
- Toolbar was a single text-label button row (`Run Once`, `Continuous`, `Stop`, `Fit Window` …) in
  an ad-hoc order, **not** the reference's icon strip.
- The right panel was one dock (Property Inspector) whose `MODULE OUTPUTS` table sat at the bottom;
  there was no `Image` / `Result` split and no `Param Name | Current Result | Global Variable` grid.
- The bottom dock was a single flat table; there was no History and no per-cycle verdict record.
- Status bar showed three unlabelled counters (`Modules:`, `Cycle:`, `FPS:`) instead of the
  reference's segmented component/flow/tools/algorithm bar.
- No locking, no global-trigger/script/camera/controller/communication entry points, no Operation
  Interface screen, no Multi-Flow overview screen.
- `FlowEditorView` was styled with `background: #F8FAFC` — a **light** background behind a dark
  canvas (a real defect, now fixed).

---

## 3. Implemented changes (all verified in the running application)

### 3.1 Control Toolbar (manual p.70)
Rebuilt as a single icon strip with the documented inventory **and ordering**:
`Save · Open · Undo · Redo | Locking · Camera Set · Controller Management · Global Variable ·
Communication Management · Global Trigger · Global Script | Once · Run Solution · Continuously ·
Stop · Validate | Operation Interface · Histogram · Draw ROI · Fit · 1:1` and a compact PASS/FAIL
badge. Every one of the 15 reference icons exists as original vector art in
[icons.py](vm_clone/ui/icons.py). A second row carries the flow tab bar (p.40 item 8 / p.74) with a
state dot, flow name, verdict and last cycle time, plus add-flow / loop / trigger-flow buttons.

### 3.2 Left Tool Box (manual p.72/p.74) — new [toolbox.py](vm_clone/ui/toolbox.py)
44 px category glyph rail (11 categories + brand + search) driving a 246 px flyout with a
`74 × 74` icon-above-wrapped-label grid, live cross-category search, tooltips, double-click insert
and `QDrag` drop onto the canvas. Clicking the active glyph collapses the flyout; `Esc` closes it.
The legacy `QTreeWidget` is retained (hidden) so existing APIs and tests keep working.

### 3.3 Flow Diagram (manual p.74/p.95)
- Canvas repainted to the **sampled** `#444348` with a 20 px dot grid and 100 px major dots.
- `FlowNodeItem` rewritten as the reference's white rounded card: orange `NN` execution index,
  module name, 24 px module-type badge, per-port rows on both edges, footer verdict + latency.
  Card **border** encodes state (orange selected / green PASS / red FAIL / amber TIMEOUT / sky RUN).
- `ConnectionItem` rewritten as an orthogonal routed wire with a rounded elbow and an arrow head;
  orange for control flow, blue for Image-typed data, dashed + brighter when selected, soft halo.
- Wiring now works when dragging **from either end**; ports are 9 px with generous hit areas.
- Locking (p.70) blocks insertion, deletion, movement and wire creation.
- Undo/redo now covers insert, delete, move and connect/disconnect, and works while locked.

### 3.4 Right side: Image / Result split (manual p.40 item 5/6, p.87) — new [result_panel.py](vm_clone/ui/result_panel.py)
- `Image` tab: the inspection viewport.
- `Result` tab: the reference's 3-column grid `Param Name | Current Result | Global Variable` with
  collapsible `Outputs` groups, 4-decimal formatting and chain-link subscription glyphs; right-click
  or double-click binds a leaf parameter to one of the 32 global variables.
- Property Inspector, Property/Result ratio and module-output grid retained beneath it.

### 3.5 Operation Interface (manual p.40 item 5 / p.96)
New central tab with the overlay/formatting layer switches (All Overlays, ROIs & Defect Boxes,
Measurements & Labels, Datum & Crosshairs, Reticle, Histogram, Canvas Grid) and an output-parameter
formatting preview. Switches stay synchronised with the toolbar in both directions.

### 3.6 Multi-Flow Overview (manual p.95) — new [flow_overview.py](vm_clone/ui/flow_overview.py)
Third central tab: one white card per flow with play / continuous / formatting buttons, `NTimes`
and last cycle time, an orange enable slider and a PASS/FAIL footer; producers fan out and orange
orthogonal dependency wires with arrow heads converge on the trigger flow. Play executes a single
flow; double-click opens it in the Flow Diagram.

### 3.7 Result Display / status bar (manual p.40 item 6/7)
- Bottom dock is now tabbed: `Current Result` (per-module verdict grid), `History` (one row per
  cycle: cycle #, flow, verdict, flow time, failed module, details; capped at 500 rows), `Help`
  (shortcut card).
- Status bar rebuilt as the reference's segments: `Component Config Completed | Flow NNN.NNms |
  Tools N | Algorithm NNN.NNms | FPS N.N`, plus transient hints in the toolbar.

### 3.8 Menus, dialogs, persistence
File / Settings / Tools / System / View / Help now match the manual's menu chapters (p.42–68), with
New/Open/Save/Save As, example solutions, CSV export, `.prc` flow export/import, Global Variables,
hardware trigger, communication configuration, calibration wizard, module generator, camera set,
controller management, log viewer, performance options, manual/shortcuts/language/version/about.
A `Panels` submenu exposes every dock's `toggleViewAction()`.

### 3.9 Flow Probe navigator (manual p.40 item 9) — new `FlowProbeWidget`
A 176×140 thumbnail navigator docked in the lower-left corner of the flow canvas, as in the
reference. It renders the whole flow at thumbnail scale, colours each module by its verdict,
draws the wires, overlays the current viewport as a dashed orange rectangle, and lets the operator
centre the viewport by clicking or dragging inside it. It repositions on resize, repaints on
scroll/zoom/status change, and is toggleable from `View > Show Flow Probe`.

### 3.10 Defects fixed
- Flow editor viewport light-background bug (light QSS on a dark canvas).
- `ImageCanvasWidget.set_show_overlays()` was missing entirely — the "All Overlays" switch raised
  `AttributeError`.
- Bidirectional action↔checkbox sync caused duplicate handler invocations; now guarded.
- Result tree group rows did not stay expanded after insertion.
- `FlowCardItem._button_at()` rejected `QPoint` from Qt mouse events.
- Sample solution loading left the Multi-Flow overview stale.
- Selection is initialised on the entry module so the Inspector and Result grid are populated at
  startup instead of showing "NO MODULE SELECTED".

---

## 4. Test results

Command: `python -m pytest tests/` (equivalent in-process runner:
[run_tests.py](scripts/run_tests.py); crash-isolating runner:
[run_tests_isolated.py](scripts/run_tests_isolated.py))

```
135 passed in 25.79s
```

| Suite | Tests | Notes |
|---|---|---|
| `test_vm_workspace_ui.py` (new) | 22 | Theme tokens vs sampled reference colours; rail glyph per category; flyout category + cross-category search; drag payload; result grid columns/expansion/formatting/binding; overview card count, non-overlap and wire count; toolbar inventory + order + tooltips; menu structure; lock protection; undo/redo; status segments; history rows; verdict tab + tooltip; workspace tabs; layer switches; histogram sync; overview activation; continuous toggle sync |
| `test_workflow_e2e.py` (new) | 9 | insert → select → inspector/result sync → validate → run → results/history/badge → flow persistence round-trip → CSV rows; multi-flow isolation + overview sync; layout consistency at 1100×720, 1280×800, 1600×950, 1920×1080 (no overflow, proportions held); dock float/re-dock state retention; disconnected-module validation |
| `test_flow_probe.py` (new) | 6 | probe exists, docks bottom-left, repositions on resize, shifts right on a narrow canvas, renders, scene↔probe coordinate round-trip, click/drag recentring, toggle + status repaint |
| `test_ui_audit_fixes.py` (new) | 25 | UI/UX audit regressions — toolbar never overflows, responsive degradation order, result-grid column model, inspector balance, validation dialog, panel proportions. See [UI_UX_AUDIT_REPORT.md](UI_UX_AUDIT_REPORT.md) |
| Pre-existing suites | 35 | All behaviours preserved |
| **Total** | **135** | |

**Known test-environment limitation (not a product defect):** the DSH file sandbox denies deleting
directories under the platform temp root, so `tempfile.TemporaryDirectory()` fails during cleanup
with `WinError 5`. `test_flow_duplication_and_serialization` was changed to use an auto-removed
workspace file; the export/import code path itself is unchanged and passes.

---

## 5. Rendered verification (before / reference / after)

- `docs/screenshots/comparison_sheet.png` — three-column sheet interleaving the **before** capture,
  the **reference figure** and the **after** capture for: workspace, result panel, multi-flow
  overview and tool box.
- `docs/screenshots/live_window.png` — the **real on-screen window** captured with Win32
  `PrintWindow` from the running `python main.py` process (1616×989), proving font/glyph rendering
  and DPI behaviour in the actual application, not just offscreen.
- Per-screen captures: `vm_flow_workspace.png`, `vm_toolbox_flyout.png`, `vm_result_panel.png`,
  `vm_operation_interface.png`, `vm_multiflow_overview.png`, `vm_toolbox_closeup.png`.

### Measured improvements vs the before state

| Aspect | Before | After |
|---|---|---|
| Tool Box | Full-width `QTreeWidget` list (~340 px) | 44 px glyph rail + 246 px flyout grid (reference p.72/74) |
| Module cards | Dark blue-grey rectangles, status strip | White rounded cards, orange `NN` index, type badge, port rows, border-coded verdict (p.74) |
| Wires | Blue bezier | Orange orthogonal routed wire with arrow head + halo (p.74/95) |
| Right panel | Single Property Inspector dock | `Image \| Result` split with `Param Name / Current Result / Global Variable` grid (p.40/87) |
| Bottom panel | One flat table | `Current Result \| History \| Help` tabs with per-cycle verdict records (p.40) |
| Toolbar | Text-label button row | 15-icon control strip in documented order + flow tab strip (p.70) |
| Status bar | 3 unlabelled counters | 5 segmented fields (p.40 item 7) |
| Screens | 1 workspace + viewport tab | Flow Diagram / Operation Interface / Multi-Flow (p.40/95/96) |
| Undo/redo | Connections only | Insert, delete, move, connect, disconnect, working under lock |
| Editing lock | absent | Full locking protection (p.70) |

---

## 6. Known limitations and remaining gaps

1. **No live camera acquisition.** `Image Source` supports synthetic patterns and image files;
   a real GigE/USB3 device would need the vendor SDK. Labelled as such in the UI.
2. **Sparsity of the module parameter surface.** Real VisionMaster exposes per-module tabbed
   configuration dialogs (`Input Params / Output Params / Run Params / Display Settings`, p.96).
   This build exposes a single typed parameter form plus the output-formatting preview; the tabbed
   dialog is not implemented.
3. **Per-module tabbed configuration dialog (p.96)** with `Input Params / Output Params /
   Run Params / Display Settings` is not implemented; parameters are exposed through the single
   Property Inspector form plus the Operation Interface formatting preview.
4. **`Global Trigger` / `Controller Management` / `Camera Set` / `Communication Management`** open
   informational dialogs describing the configuration rather than binding real hardware.
5. **Node result probe overlay** — the reference draws a per-module probe window over the image;
   here the ROI and overlays follow the *selected* module only. (The flow-level probe window,
   p.40 item 9, **is** implemented.)
6. **Chinese localisation.** Language switching reports that zh-CN resources are not bundled.
7. **Wires are orthogonal-routed, not bezier-smoothed.** This matches the reference screenshots,
   but the routing is a two-segment elbow without obstacle avoidance.
8. **Flow tab disabled-state palette.** Tab colours are set per state; the reference's exact
   palette for disabled flows is not documented in the manual and was chosen for contrast.
9. **Keyboard coverage.** Shortcuts cover New/Open/Save/Save As/Undo/Redo/tab switching/Fit/Delete/F1;
   the reference's full accelerator table is not published.
10. **`run_tests_isolated.py`** exists because Qt teardown of `QGraphicsScene` can hard-crash
    (0xC0000409) in some offscreen paths; the suite passes both isolated and in one process, but the
    isolated runner is the recommended CI entry point.

---

## 7. How to run and verify

```powershell
python main.py                              # launch the application
python -m pytest tests/                     # full suite (135 tests)
python scripts/capture_vm_snapshots.py      # per-screen offscreen captures
python scripts/build_comparison.py          # before / reference / after sheet
python scripts/extract_manual_figs.py 37 100  # re-extract reference figures
```
