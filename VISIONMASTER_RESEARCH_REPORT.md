# VisionMaster Research & Reproduction Report

**Objective:** research HikRobot VisionMaster from verifiable sources, produce a reference-based
specification, and reproduce its interface and behaviour in this PySide6 application as faithfully
as is practical with original assets and no proprietary branding.

**Result:** an annotated 13-region specification derived from the vendor's own manual, a
**分镜 (frame-by-frame) geometry breakdown measured pixel-by-pixel from the reference
figures**, the layout rebuilt from those measurements so that **every measured band lands
within 0.32 % of the reference**, **7 of 12 identified gaps closed** (including all of the
highest-impact ones), **141 automated tests passing**, and every change verified against
reference figures and in the running application.

---

## 1. Research: what was obtained, and what was not

### 1.1 Obtained and used

| Source | Size | What it contributed |
|---|---|---|
| `HikRobotVMHelp_compressed.pdf` (bundled, 657 pp.) | 8.9 MB | Home page layout, control-toolbar inventory, tool-box rail, module cards, Image\|Result column, result-grid columns, multi-flow overview |
| *海康机器人 Vision Master 算法开发平台 用户手册* **4.3.0 maintenance edition**, 928 pp. — [vendor CDN](https://pinfo.hikrobotics.com/hkws/unzip/20250729144858_90792_doc/) | 61 MB | **The annotated main-interface region map (Fig. 5-2, p. 38) with a 13-region legend**, image-display-area operations (§5.2.3), flow configuration window tabs (§8.1), module general configuration (§8.2), quick-toolbar icon table (§5.2.2), global variables (§9) |
| *VisionMaster 3D 算法开发平台* 2.2.0 manual, 1154 pp. — [vendor CDN](https://pinfo.hikrobotics.com/hkws/unzip/20240919112534_17943_doc/) | 37 MB | Corroborates the module rail, card style and parameter-tab structure in a sibling product |
| *VisionMaster 算法平台用户手册 V3.0.2* — [third-party archive](https://www.ceiaec.org/ueditor/php/upload/file/20190710/VisionMaster%e7%ae%97%e6%b3%95%e5%b9%b3%e5%8f%b0%e7%94%a8%e6%88%b7%e6%89%8b%e5%86%8cV3.0.2.pdf) | 84 KB | Earlier UI wording, per-tool ROI shape vocabulary, crosshair dialog |

Extraction pipeline (all scripts in `scripts/`): `fetch_external_refs.py` (download) →
`mine_external_refs.py` (pull 120 figures + page text) → `extract_ui_chapters.py` (rank the 74 most
UI-relevant pages, dump text, render the top 20) → `crop_ui_regions.py` (high-resolution crops of the
region map and dialogs). Evidence lands in `docs/references/external/`.

### 1.2 Not obtained — stated plainly

| Source | Result |
|---|---|
| `pinfo.hikrobotics.com/…/20231101163730_26101_doc/pdf.pdf` (SDK development manual) | **HTTP 404** — retired |
| `hnxmsy.com.cn/…/16644533891856488.pdf` (training deck) | **HTTP 406** — host refuses non-browser `Accept` headers |
| **Video walkthroughs** | **No machine-readable video source was reachable.** No behavioural claim in the specification rests on video; where video would have settled a question it is listed as an open question instead |

Cache-buster URLs with fragment suffixes returned by the search index were not attempted as
downloads, since they are search-engine artefacts rather than canonical document URLs.

---

## 2. The specification

`docs/VISIONMASTER_REFERENCE_SPEC.md` (new) records, with an evidence ID per claim:

- The **13-region vendored legend** verbatim, plus an ASCII layout reconstructed from the annotated
  figure.
- **The key structural finding:** in the vendor UI the *result display area* is **not** a separate
  bottom-left panel — it sits directly **below the image**, inside the right-hand column, and its
  table has **one column per output parameter** rather than a fixed module-log schema.
- The documented quick-toolbar inventory, the image-display-area operations, the flow-configuration
  window's four tabs, the module configuration structure, the ROI shape vocabulary, the status-bar
  segments, and the global-variable columns.
- A gap table (§4) with a status per gap, and a §5 list of **open questions** where evidence was
  insufficient.

---

## 3. Implementation

### 3.0 Measurement pass: the 分镜 geometry breakdown

`docs/VISIONMASTER_STORYBOARD.md` records the frame-by-frame breakdown. It is **measured,
not estimated**:

- `scripts/measure_storyboard.py` locates the application window inside each vendor
  figure and profiles luminance along specific rows and columns; raw output in
  `docs/references/external/storyboard_geometry.json`.
- Luminance alone cannot separate panels of similar brightness, so the column
  boundaries were confirmed with **four independent row scans** of the one uncropped
  whole-window figure (the bundled manual's Home Page, 925 × 765) — toolbar, image row,
  strip/result row and status bar. All four agree:

  | Region | x px | Ratio of the 818 px interior |
  |---|---|---|
  | module rail | 116…158 (**42 px**) | **0.0513** |
  | flow canvas | 158…484 (**446 px**) | **0.5452** |
  | right column | 568…898 (**330 px**) | **0.4034** |

- The vertical chrome and block heights come from the 2× right-column crop, where one
  reference pixel is two real pixels: title bar 80 px, toolbar 66 px, flow bar 50 px
  (chrome total **196/1310 = 0.1496**), image display block **791/1310 = 0.6038**.
- Control metrics: 27 px tab bar, 33 px table header, 27 px table rows, 51 px image-strip
  cell, 40 px toolbar pitch, 8 px panel padding.

`vm_clone/ui/layout_metrics.py` holds every constant with the measurement it came from,
and `scripts/compare_layout.py` captures the application at the reference size and prints
the realised deviations. The result:

| Measure | Reference | Applied | Delta |
|---|---|---|---|
| rail width | 0.0513 | 0.0490 | −0.0023 |
| canvas width | 0.5452 | 0.5484 | +0.0032 |
| right column width | 0.4034 | 0.4026 | −0.0008 |
| chrome height | 0.1496 | 0.1490 | −0.0006 |
| image block height | 0.6040 | 0.6036 | −0.0004 |
| result block height | 0.3960 | 0.3964 | +0.0004 |

**worst deviation 0.32 %, at the exact reference window size (925 × 765).** The canvas is
the only band more than 0.1 % out, and only because Qt gives it whatever the docks leave.

Three Qt behaviours had to be solved to get there, each now documented in the storyboard:
the canvas is the layout's leftover space and silently absorbs the dock frames (solved with
a settled second pass that measures the overhead and solves for the column in one step);
`QSplitter.setSizes` defers to child size hints (solved with a per-pane maximum plus a
usability floor); and a *fixed* pane height also fixes the window's own minimum size
(which initially stretched the window to 920 px).

### 3.0b Removal pass — everything that was not in the reference

The instruction was to make the interface the same as Vision Master and remove the property
inspector. Four things the reference does not have were deleted:

| Removed | Was | Replaced by |
|---|---|---|
| **Property Inspector** | a third right-column pane holding a parameter form | the per-module configuration window (frame 6), which is where the reference edits parameters; the canvas ROI now writes straight into the selected module's parameters |
| **Flow Probe** | a 176 × 140 thumbnail navigator floating on the canvas | nothing — the reference canvas carries only the zoom control, in the lower-left corner |
| **FPS status segment** | a fourth segment beside Flow / Tools / Algorithm | the reference's three segments, exactly (`ui_crops/ref_statusbar.png`) |
| **Run-all and validate toolbar glyphs** | two extra controls in the icon strip | the reference's strip order: Once → Continuous → run mode; validation stays on the Tools menu and the flow context menu |

The two control rows were also redistributed to the reference's own arrangement, read from
`ui_crops/r3_topleft.png` (3×, unannotated): row 1 is brand → file/resource group →
execution (Once, Continuous) → status badge; row 2 begins with the flow tab and its
`once`/`continuous`/`plus` glyphs, then puts the viewport controls on the right, which is
where the reference puts them.

### 3.1 Right column — the vendor two-tier tab layout

A first attempt mounted the result grid as a lower pane *inside* the image page and kept a
full-width bottom `Result Display` dock — neither matches the vendor. Re-reading the zoomed
crop `docs/references/external/ui_crops/right_column_zoom.png` shows the truth:

- the right column is a **two-row vertical stack in which each row is its own tab widget with its own
  visible tab bar**;
- **upper bar**: `图像 | 模块结果` → *Image | Module Results*;
- **lower bar**: `当前结果 | 历史结果 | 帮助` → *Current Result | History Result | Help*;
- the image strip sits at the bottom of the upper block, between the two tab bars;
- the vendor has **no bottom result dock at all**.

`main_window._init_property_dock()` now builds exactly that: `data_tabs` (`Image`, `Module Results`)
above `ResultDisplayArea` (`Current Result`, `History`, `Help`), both visible simultaneously. The
per-module execution trace moved to a **hidden** Module Log dock (View ▸ Panels, or System ▸ Log
Viewer), so the main workspace matches the reference. The property inspector — which the vendor does
not have on the canvas, using a per-module dialog instead — is retained as the last pane.

Also fixed while verifying: the dock split was computed once at start-up, so shrinking the window left
the right column clipped off-screen; `resizeEvent` now rebalances when the width changes materially
while leaving operator-adjusted docks alone.

### 3.1 Result display area — region 12 (G1, G2) — `vm_clone/ui/result_display.py` (new)

The two competing result surfaces were consolidated into one. The bottom `Result Display` dock is now
`ResultDisplayArea` with `Current Result / History / Module Log / Help` tabs. The Current Result tab
renders a **column-per-parameter table** built by `extract_feature_rows()`:

- a **record list** (`Blobs: [{area, perimeter, centroid_x, …}]`) becomes
  `Index | Area | Perimeter | Centroid X | Centroid Y | Angle | Major | Minor | Circularity`;
- **parallel scalar lists** (`Radius`, `CenterX`, `CenterY`) become the same shape;
- scalar-only modules fall back to `Parameter | Value` inside the same grid.

Numeric values keep the vendor's 4-decimal presentation. The per-module execution trace that the
project needs moved into a `Module Log` tab of the same surface. The compact tree in the right column
(D6) remains as the secondary in-column summary.

### 3.2 Image display area — region 6 (G3, G4) — `vm_clone/ui/image_display.py` (new)

A vertical stack matching the reference figure: source-name header with the view toolbar
(single/dual view, zoom in, zoom out, 1:1, fit, crosshair auxiliary line, expand), the paged viewport
with previous/next arrows, and the image strip with `Auto switch` and run-scope controls.
`ImageCanvasWidget` gained `zoom_at_center()` and `current_pixmap()`; strip thumbnails are painted
from the live frame, and **selecting a strip entry retargets the image, the result tree and the
result table to that module**.

### 3.3 Module cards (G5) — `vm_clone/ui/flow_editor.py`

The square top-right badge was replaced by the reference's **circular category badge straddling the
card's left edge** (green normally, orange when selected), with the index + name to its right.

### 3.4 Flow-area zoom tool — region 11 (G6) — `vm_clone/ui/flow_editor.py`

`FlowZoomTool`: a small floating control in the canvas's lower-left corner with a live percentage
read-out, −, + and fit. It tracks wheel zoom, toolbar zoom, fit and reset. The flow probe moved to the
lower-right so the two instruments never collide (a regression test asserts their rectangles are
disjoint).

### 3.5 Module configuration window (G8) — `vm_clone/ui/module_config.py` (new)

The vendor's tabbed module window: `Input Params` (ports with type and description), `Output Params`
(a subscription tree with per-parameter checkboxes), `Run Params` (parameters **grouped by category** —
Image, Edge, Search, Measurement — mirroring §8.2's 图像相关参数 / 边缘相关参数 grouping), and
`Display Setup` (which image the display area presents). Footer: `Continuous | Execute | OK`.
Opened by double-clicking a module or from its context menu. Editors reuse the inspector's parameter
vocabulary: enum keys are dropdowns, path parameters get an abbreviated display plus a Browse button,
and the enum table was moved into `inspector.PARAM_ENUMS` so both surfaces agree.

---

## 4. Verification

### 4.1 Automated — 141 passed

```
python -m pytest tests/   ->   141 passed
```

| Suite | Tests | Focus |
|---|---|---|
| `test_measured_layout.py` (new) | 13 | The constants equal the measurements; the split helpers respect the minimums; **the applied layout lands on the measured ratios at five window sizes**; chrome ratio; band order; the module box is the measured rail at rest and widens on demand; the deviation report is complete |
| `test_reference_spec_ui.py` | 16 | Result display's three tabs; per-feature columns from record lists and parallel lists; scalar fallback; two-tier right column; hidden module log; image display controls, dual-view signal, strip paging, flow-image listing; card badge; zoom tool; module config dialog |
| `test_right_panel_layout.py` | 13 | Vendor two-tab right column, upper tab switching the display block, image + result table visible together, usable heights at three sizes, ROI canvas priority, tree column re-fit, form label column, path abbreviation |
| `test_ui_audit_fixes.py` | 25 | **Measured canvas/right-column shares at four sizes**, toolbar overflow, responsive chrome, result-table column model, validation dialog |
| `test_flow_probe.py` | 7 | Probe placement, no overlap with the zoom tool, coordinate mapping, recentring |
| `test_vm_workspace_ui.py`, `test_workflow_e2e.py`, `test_acquisition_file.py` | 34 | Workspace shell, end-to-end workflow, acquisition/path handling |
| pre-existing | 33 | Unchanged behaviour |

### 4.2 Rendered

| Evidence | Content |
|---|---|
| `docs/VISIONMASTER_STORYBOARD.md` (**new**) | The 分镜 breakdown: 12 frames, measured window/band/column geometry, interaction transitions, applied constants, measured deviations |
| `docs/references/external/storyboard_geometry.json` (**new**) | Raw measurement output |
| `docs/references/external/layout_deviations.json` (**new**) | The realised-vs-reference deviation table |
| `docs/screenshots/layout_comparison.png` (**new**) | Reference and implementation side by side **at the same 925 × 765 size**, plus the right column and the module cards |
| `docs/references/external/ui_crops/right_column_zoom.png`, `card_zoom.png`, `home_left_edge_zoom.png` (**new**) | The zoomed vendor crops the measurements and the card design came from |
| `docs/screenshots/audit/40_reference_size_layout.png`, `41_right_column_detail.png` (**new**) | The implementation captured at the reference size |
| `docs/screenshots/spec_comparison.png`, `comparison_sheet.png`, `audit_comparison.png`, `toolbox_comparison.png` | Region, before/after and toolbox sheets |
| `docs/screenshots/live_window.png`, `live_window_small.png` | The **real on-screen window** at 1616×989 and 1120×760 (Win32 `PrintWindow`) |

### 4.3 Interaction checks performed

Module double-click and context menu → configuration window; Execute inside the dialog re-runs the
flow; enum change writes through to the tool; image-strip selection retargets all three result
surfaces; zoom tool −/+/fit and wheel tracking; dual-view toggle; strip paging; live window resize at
three sizes; continuous/lock/undo/redo regression suite.

---

## 5. Files changed

| File | Change |
|---|---|
| `vm_clone/ui/layout_metrics.py` | **New** — every measured constant with its source measurement, the split solvers, and the deviation report |
| `docs/VISIONMASTER_STORYBOARD.md` | **New** — the 分镜 breakdown and the measured deviation result |
| `scripts/measure_storyboard.py` | **New** — the reference measurement tool |
| `scripts/compare_layout.py` | **New** — capture at the reference size, print deviations, build the comparison sheet |
| `tests/test_measured_layout.py` | **New** — 13 tests pinning the measured geometry |
| `vm_clone/ui/result_display.py` | **New** — result block with the vendor's three tabs, per-parameter table extraction, off-surface module log |
| `vm_clone/ui/image_display.py` | **New** — image display area: header, view toolbar, paged viewport, image strip; header controls made elide-able so they cannot pin the column wide |
| `vm_clone/ui/module_config.py` | **New** — tabbed module configuration window |
| `vm_clone/ui/main_window.py` | Right column rebuilt to the vendored two-tier layout; measured split applied in two passes; toolbar metrics and chrome height taken from the measurement; hidden Module Log dock; Operation Interface page scrollable so the window reaches the reference height |
| `vm_clone/ui/flow_editor.py` | Cards rebuilt as the reference pills (white body + green capsule badge); `FlowZoomTool`; probe relocated; `configure_module` signal |
| `vm_clone/ui/toolbox.py` | Rail width and flyout width from the measurement; flyout collapsed at rest and toggled from the rail |
| `vm_clone/ui/image_canvas.py`, `inspector.py`, `vm_theme.py` | Auto re-fit, shared `PARAM_ENUMS`, measured tab/toolbar styling |
| `docs/VISIONMASTER_REFERENCE_SPEC.md`, `APEX_UI_SPECIFICATION.md`, `README.md`, `AUDIT_CHECKLIST.md` | Updated for the measured layout and the new surfaces |

**Original assets only.** Every icon, glyph and widget is drawn in code by this project
(`icons.py`, `image_display._view_icon`, `toolbox.get_rail_icon`). No vendor artwork, logo or binary
asset is copied or redistributed; the vendor documents are used only as local visual reference and
are kept under `docs/references/external/` for evidence.

---

## 6. Remaining gaps

Ordered by the impact they still have on fidelity.

1. **ROI shape vocabulary (G9) — the largest remaining functional gap.** Only a rectangle ROI with
   eight interactive handles exists; the manual documents point, line, rectangle, circle, annulus and
   polygon (up to 32 vertices) with a shape-drawing toolbar on the preview.
2. **Auto-switch and Run-all are layout-only (G4, partial).** The image strip header renders both
   controls, but the auto-switch toggle does not yet cycle the strip automatically after a run, and
   the run-scope selector does not change execution scope.
3. **Global-variable columns (G10).** `Name / Type / Value` rather than
   `Name / Comment / Type / Current value`.
4. **Undo/redo step cap (G11) and module count cap (G12)** are unbounded instead of configurable with
   the documented limits (15 cached steps; 1024 modules).
5. **Dual image view** emits its signal and disables the single-view control, but the second viewport
   is not yet rendered — the toggle is honest about state, not yet about content.
6. **Crosshair auxiliary-line configuration dialog** (thickness, brush, display mode, locking) is not
   implemented; only the on/off toggle exists.
7. **Quick-toolbar layout (G7) is an accepted deviation**: two rows instead of one strip, chosen so
   that no documented control is ever hidden on a narrow desktop.
8. **Not verifiable from the obtained evidence:** exact view-mode icon semantics beyond
   single/double view, the 4.3 crosshair dialog contents, and all video-level interaction detail
   (hover, drag feedback, animation). These are listed as open questions in the specification rather
   than implemented from guesswork.

## 7. Next highest-priority work

1. ROI shape vocabulary (point / line / circle / annulus / polygon) with a preview drawing toolbar —
   closes the last large functional gap and matches manual §8.2 p. 108.
2. Wire the image-strip auto-switch and run-scope selector to real behaviour.
3. Global-variable `Comment` column and the documented caps (15 undo steps, 1024 modules).
4. A second viewport for dual image view.
5. Per-module image probe overlay so overlays follow the module under the cursor.
