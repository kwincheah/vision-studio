# Apex Industrial Vision Studio v4.3 — UI Specification

**Design direction:** original industrial machine-vision engineering UI/UX, aligned to the
HikRobot Vision Master reference (`HikRobotVMHelp_compressed.pdf`) as **measurable design
evidence** rather than vague inspiration.

**Compliance:** no generic dashboard layouts, oversized headings, neon glows, glassmorphism,
emoji icons, decorative whitespace or arbitrary gradients. Every token below was sampled from
or measured against a reference figure.

---

## 1. Reference evidence base

Every UI decision is traceable to a specific page of the bundled 657-page manual. Reference
figures were extracted to `docs/references/` by
[extract_manual_refs.py](scripts/extract_manual_refs.py) and
[extract_manual_figs.py](scripts/extract_manual_figs.py).

| Reference | Page | What it pins down |
|---|---|---|
| Home Page | 40 | Menu bar → Control Toolbar → left category rail → flow tab bar → central canvas → Image\|Result right panel → segmented status bar |
| Control Toolbar | 70 | Exact icon inventory **and ordering**: Save, Open, Undo, Redo, Locking, Camera Set, Controller Management, Global Variable, Communication Management, Global Trigger, Global Script, Once, Continuously, Stop, Operation Interface |
| Tool Box | 72 | Narrow vertical category glyph rail down the left edge of the flow workspace |
| Tool grid | 74 | Flyout titled with the category name; icon-above-wrapped-label cells in a dense multi-column grid; white module cards with an orange numbered prefix and an orange wire |
| Result grid | 87 | `Param Name | Current Result | Global Variable` columns with collapsible parameter groups and a link glyph per leaf value |
| Multi-Flow | 95 | White flow cards with play / continuous / formatting buttons, `NTimes` + `NNN.NNms`, and an orange converging dependency bus |

**Colour sampling** (`docs/references/figs/p074_01.png`, `p040_01.png`):

| Sample point | RGB | Token |
|---|---|---|
| Chrome / title strip | `(32, 31, 36)` | `vm_chrome` `#201f24` |
| Flow canvas base | `(68, 67, 72)` | `vm_canvas` `#444348` |
| Flyout surface | `(45, 45, 45)` | `vm_flyout` `#2d2d2d` |
| Panel surface | `(58, 62, 65)` | `vm_panel` `#3a3e41` |
| Module card body | `(245, 246, 241)` | `vm_node` `#f7f8f3` |
| Dependency wire | warm orange | `vm_wire` `#e8963c` |
| Functional accent | product orange | `vm_accent` `#e8792b` |

---

## 2. Design system tokens

Defined once in [styles.py](vm_clone/ui/styles.py) (`THEME`) and consumed by
[vm_theme.py](vm_clone/ui/vm_theme.py) (stylesheet) and the `QGraphicsScene` / `QGraphicsItem`
painters.

### 2.1 Surfaces (depth hierarchy, darkest → lightest)
- Application root / chrome: `#0f1217` → VisionMaster chrome `#201f24`
- Docks, panels, table headers: `#151921` / `#3a3e41` (`vm_panel`) / `#444850` (`vm_panel_header`)
- Controls, inputs: `#202633`, hover `#272f3e`, pressed `#171c26`
- Flow canvas: `#444348` with a `20 px` dot grid at `#514f56` and a `100 px` major dot at
  `#5c5a63` (measured from p.74)
- Module cards: `#f7f8f3` (near white) with `#2b2d31` primary / `#7d838c` secondary text

### 2.2 Typography
- UI: `Segoe UI` 12 px base (11 px in dense tables/tooltips), falling back to
  `Microsoft YaHei UI` → `Arial`
- Telemetry: `Consolas` 8–9 pt for coordinates, latencies, FPS
- `initialize_app_fonts()` pre-loads `segoeui.ttf`, `segoeuib.ttf`, `arial.ttf`, `consola.ttf`

### 2.3 Functional colour (strictly reserved)
- **Orange `#e8792b`** — module numbering, selection, dependency wires, active rail category
- **Blue `#3b82f6`** — preserved engineering-blue identity: focus rings, Image-typed data wires
- **Green `#22c55e` / Red `#ef4444` / Amber `#f59e0b` / Sky `#38bdf8`** — PASS / FAIL / TIMEOUT / RUNNING
- **Amber `#f59e0b`** — Value / Point / Circle / Line / Region ports
- **Purple `#a855f7`** — Boolean (verdict) ports, **Teal `#14b8a6`** — String ports

---

## 3. Screen architecture

```
+-------------------------------------------------------------------------------------------+
| [brand]  File   Settings   Tools   System   View   Help              Component Config ...  |
+-------------------------------------------------------------------------------------------+
| [brand] Save Open Undo Redo | Lock Cam Ctlr Var Com Trig Script | > >> () [] | [] Hist ROI Fit 1:1 | FAIL |
+-------------------------------------------------------------------------------------------+
|  (o Flow1 FAIL 157ms x) + (o) | v                                                                   |
+--------+--------------------------------------------------------------+---------------------+
| RAIL   | [ Flow Diagram ] [ Operation Interface ] [ Multi-Flow ]      | [Image][Module Res] |
| [cam]  |                                                              | 01_Acq.Output Image |
| [loc]  |   white module cards  --orange wire-->  white module cards   | [][][] [+] [-] [1:1]|
| [cal]  |                                                              |  ◀   image    ▶     |
| [gen]  |                                                              | 1280*1024 | X Y |RGB|
| [dsp]  |                                                              | 01_Acq (1/4)  [auto]|
| [col]  |                                                              | [thumb][thumb][thumb]|
| [ocr]  |                                                              +---------------------+
| [def]  |                                                              | [Current][History]  |
| [clb]  |                                                              |    [Help]           |
| [com]  |                                                              | Parameter | Value   |
| [lif]  |                                                              | Width     | 800     |
| [Q]    |                                                              | Height    | 600     |
|        |                                                              +---------------------+
|        |                                                              | PROPERTY INSPECTOR  |
|        |                                                              |  Source Type [Synth]|
|        |                                                              |  File Path   [...]  |
+--------+--------------------------------------------------------------+---------------------+
| Component Config Completed | Flow 156.56ms | Tools 7 | Algorithm 156.48ms | FPS 6.4         |
+-------------------------------------------------------------------------------------------+
```

The right column is one dock with **two tab widgets stacked**, each with its own visible tab bar —
reproducing Vision Master 4.3.0 manual Fig. 5-2 regions 6 and 12. The vendor has no bottom result
dock; this project's module-execution trace lives in a hidden `Module Log` dock (View ▸ Panels).

The right column is a single dock whose children are ordered exactly as the reference has them
(manual p.40): **inspection image on top, result grid directly beneath it, property inspector
below that** — all visible at once, with no tab switch that hides the image.

### 3.1 Left Tool Box (manual p.72/p.74) — [toolbox.py](vm_clone/ui/toolbox.py)
- `ToolCategoryRail`: 44 px vertical rail, one 38 px glyph per registered category + brand mark
  + "search all modules" shortcut. Active category gets an orange left edge and the flyout surface
  colour; clicking the active glyph again collapses the flyout.
- `ToolFlyoutPanel`: 246 px. Category header + search field + `ToolGridWidget`.
- `ToolGridWidget`: `IconMode` grid, `74 × 74` cells, 28 px accent-tinted glyph above a wrapped
  label, drag-out support (`QDrag` carrying the tool name) and double-click to insert.

### 3.2 Flow Diagram (manual p.74/p.95) — [flow_editor.py](vm_clone/ui/flow_editor.py)
- `FlowScene` paints the sampled dot grid; `set_grid_visible()` and `set_locked()` supported.
- `FlowNodeItem`: `202 px` wide white rounded card — 34 px header (orange `NN` index + module
  name + 24 px module-type badge), port rows on both edges, 17 px footer with the verdict and
  latency. The **border colour is the primary state channel**: orange while selected, green PASS,
  red FAIL, amber TIMEOUT, sky RUNNING, grey idle.
- `ConnectionItem`: orthogonal routed wire with a rounded elbow and an arrow head at the target
  port. Orange for control/data-flow, blue for Image-typed wires, dashed + brighter when selected,
  with a soft dark halo for legibility on the mid-grey canvas.
- `PortItem`: 9 px type-coloured square with a generous hit area and hover growth.
- Wires can be created by dragging **from either end** (output→input or input→output).
- `AddNodeCommand` / `DeleteNodeCommand` / `MoveNodeCommand` / `AddConnectionCommand` /
  `DeleteConnectionCommand` provide full undo/redo on the `QUndoStack`.

### 3.3 Multi-Flow (manual p.95) — [flow_overview.py](vm_clone/ui/flow_overview.py)
- One `FlowCardItem` (`184 × 106`) per flow: header with the name and glyphs, play / continuous /
  formatting buttons, `NTimes` + `NNN.NNms`, an orange enable slider and a PASS/FAIL footer.
- Producers fan out in rows; the trigger flow sits centred below and receives orange orthogonal
  dependency wires with arrow heads.
- Play executes that single flow; double-click activates it in the Flow Diagram; the context menu
  offers open / execute / enable-disable.

### 3.4 Right column: display block and result block (manual Fig. 5-2 regions 6/12)

Two tab widgets stacked in one dock, **each with its own visible tab bar**, reproducing the vendor
figure exactly. Source: `docs/references/external/ui_crops/right_column_zoom.png`.

**Upper block — `Image | Module Results`** ([image_display.py](vm_clone/ui/image_display.py))
- `Image` page: source-name header + view toolbar (single/dual view, zoom in/out, 1:1, fit,
  crosshair, expand), the paged viewport with previous/next arrows, the `WxH | X Y | R G B` status
  line, and the image strip labelled `<source> (n/N)` with the auto-switch toggle.
- `Module Results` page ([result_panel.py](vm_clone/ui/result_panel.py)): 3-column tree —
  `Param Name | Current Result | Global Var.` — with collapsible `Outputs` groups, 4-decimal numeric
  formatting, a chain-link subscription glyph per leaf row and full-value tooltips. A width-aware
  column model keeps all three columns inside the viewport and folds the subscription column below
  300 px instead of clipping it.

**Lower block — `Current Result | History | Help`** ([result_display.py](vm_clone/ui/result_display.py))
- `Current Result`: a table with **one column per output parameter**
  (`Index, Area, Perimeter, Centroid X/Y, Angle, Major, Minor, Circularity, …`), built from record
  lists or parallel lists, falling back to `Parameter | Value` for scalar modules.
- `History`: one row per cycle with verdict, flow time, failed module and details.
- `Help`: a scrollable shortcut card.

There is **no bottom result dock** in the vendor layout; this project's per-module execution trace
lives in a hidden `Module Log` dock (View ▸ Panels ▸ Module Log, or System ▸ Log Viewer).

### 3.5 Inspection viewport (manual p.40 item 5) — [image_canvas.py](vm_clone/ui/image_canvas.py)
- Subpixel pan/zoom anchored at the cursor, fit-to-window, 1:1, 8 ROI resize handles with
  contextual cursors, corner-bracket ROI accents, ROI dimension badge, coordinate reticle, RGB /
  luminance read-out, resolution tag and a live 0–255 histogram HUD.
- Re-fits the frame automatically on viewport resize (the result block shares the same column, so the
  viewport height changes when the window is resized); a manual zoom or pan disengages the auto-fit.
- Overlay layers filtered by All / ROIs & Defect Boxes / Measurements & Labels / Datums & Crosshairs.

### 3.6 Property Inspector (manual p.96) — [inspector.py](vm_clone/ui/inspector.py)
- Identity header (module name, type, description), an aligned `QFormLayout` parameter surface, and a
  live verdict strip (`OK · 3.19 ms` + message).
- Right-aligned labels occupy a fixed 92 px column; every control is 24 px high, so labels and fields
  share one vertical axis and one baseline grid.
- Trailing actions (`Browse`, `Draw`) sit in a fixed 66 px slot inside the field, so all inputs end on
  the same vertical line.
- File / folder parameters display an abbreviated path (`…\samples\pcb_sample.png`, or just
  `pcb_sample.png` in a narrow dock) while the full value is preserved on the widget and in the
  tooltip. `File Format` / `Save Mode` are enums and deliberately get no Browse button.

---

## 4. Verification & test evidence

| Suite | Tests | Result |
|---|---|---|
| `tests/test_vm_workspace_ui.py` | 22 | PASS — theme tokens vs sampled colours, rail/flyout, search, drag payload, result grid, overview cards + wires, toolbar inventory, menu structure, lock, undo/redo, status segments, history, verdict tabs, panel switches, toggle sync |
| `tests/test_workflow_e2e.py` | 9 | PASS — insert → wire → validate → run → every result surface → persistence round-trip; CSV export; multi-flow isolation; layout consistency at 1100×720 … 1920×1080; dock float/re-dock; disconnected-module validation |
| `tests/test_flow_probe.py` | 6 | PASS — probe docking, resize repositioning, narrow-canvas right-shift, rendering, scene↔probe coordinate mapping, click/drag recentring, toggle + status repaint |
| `tests/test_ui_audit_fixes.py` | 25 | PASS — toolbar overflow/responsive chrome, result-grid column model, inspector balance, validation dialog, panel proportions (see `UI_UX_AUDIT_REPORT.md`) |
| `tests/test_right_panel_layout.py` | 9 | PASS — result grid mounted under the image, image/result/inspector heights, ROI canvas priority, form label column + field axis, abbreviated path display |
| Pre-existing suites | 36 | PASS (unchanged behaviour; `test_flow_duplication_and_serialization` moved off the sandbox-blocked temp root; `test_acquisition_file.py` extended for the new form) |
| **Total** | **135** | **135 passed** |

Rendered evidence: `docs/screenshots/live_window.png` (real on-screen window via Win32
`PrintWindow`), `docs/screenshots/vm_*.png` (per-screen captures) and
`docs/screenshots/comparison_sheet.png` (before / reference / after).

## 5. Visual rendering verification
- Glyph rendering, contrast and absence of tofu boxes confirmed on the **live on-screen window**
  (`live_window.png`), not only offscreen.
- Panel proportions checked at four window sizes (1100×720, 1280×800, 1600×950, 1920×1080): no
  panel overflow, central workspace retains > 400 px, right dock always the minority column.
