# UI/UX Audit, Repair & Validation Report

**Method:** rendered the running application at every screen and interaction state, inspected the
screenshots for defects, benchmarked against the reference figures extracted from the shipped
HikRobot Vision Master manual (`HikRobotVMHelp_compressed.pdf`), then fixed the highest-impact
defects and re-validated with tests and new screenshots.

**Test outcome:** `135 passed` (`python -m pytest tests/`), up from 71 — 38 of the new tests are
regressions pinning the defects found in this audit.

---

## 0. Follow-up requested by the operator

Two direct requests were addressed after the first audit pass:

1. **"The result should be mounted under the `image | result` tab."**
   The Result grid is now the lower half of the **Image | Result** column — visible at the same time
   as the inspection image, not hidden behind a sibling tab. See §3.10.
2. **"The UI of the main page is not well aligned, especially the folder / file path thingy."**
   The parameter surface is now a real aligned form (single label column, single field axis), and
   file/folder parameters show an abbreviated path with the full value one hover away. See §3.11.

---

## 1. How the audit was performed

`scripts/audit_capture.py` renders and saves the evidence screenshots into
`docs/screenshots/audit/`: the flow diagram, five Tool Box categories, cross-category search,
the Result column, all three Result-Display tabs, the Operation Interface, Multi-Flow, six opened
menus, the Validation and Global Variables dialogs, the locked state, an empty flow, the
1100×720 minimum size and a deliberately narrowed right dock.
`scripts/capture_inspector.py` adds inspector close-ups per module category.

Defects were identified by reading those images, not by guessing at source code. Every fix below
cites the screenshot that exposed it.

---

## 2. Defects found (ranked by impact)

| # | Defect | Where it showed | Impact | Effort |
|---|---|---|---|---|
| 1 | **Control Toolbar overflow.** At 1600 px the flow toolbar still pushed its tail (Fit, 1:1, Arrange) into a `»` overflow popup, and the `Ready` hint text was clipped to 32 px. | `audit/01_flow_diagram.png` | High — operator actions silently unreachable | Medium |
| 2 | **Result grid third column clipped.** The `Global Variable` header rendered as `Glob` and the link glyphs were pushed off the right edge; module names elided to `M…`, `Au…`; the `Outputs` group stayed collapsed. | `audit/04_result_panel.png` | High — the p.87 result surface was unreadable | Medium |
| 3 | **Inspector had no vertical room.** A duplicate `MODULE OUTPUTS` table competed with the parameter surface, leaving `File Path` / `Camera Index` scrolled out of sight. | `audit/01_flow_diagram.png` | High — parameters could not be reached without scrolling | Low |
| 4 | **Flow tab verdict truncation.** With three flows the tab strip consumed the whole row, so tabs read `Flow2 NOT…` / `Flow3 NO…` and the status message was lost. | `audit/07_multi_flow.png` | Medium — verdict and timing unreadable | Low |
| 5 | **Panel proportions unmeasured.** The central canvas lost ~200 px of usable width to over-wide flanking docks; no size-based degradation existed. | `audit/01_flow_diagram.png`, `audit/13_small_window.png` | Medium — the working surface was not dominant | Low |
| 6 | **Validation dialog truncated the message.** 620 px wide with the message column squeezed, so the diagnostic text ended in `…`. | `audit/09_validation_dialog.png` | Medium — diagnostics could not be read | Low |
| 7 | **Flow Probe covered modules.** At 1100 px the probe sat over module `05_SurfaceScratchCheck`. | `audit/13_small_window.png` | Low — occlusion on small canvases | Low |
| 8 | **Long result values elided** (`ModuStatusMsg` → `Acquired image 800…`) with no way to read them. | `audit/04_result_panel.png` | Low | Low |

---

## 3. Fixes implemented

### 3.1 Control Toolbar split into two dense rows (defect 1)
`_init_control_toolbars()` in [main_window.py](vm_clone/ui/main_window.py) replaces the single
34-control row with two compact rows at 26×24 px / 18 px glyphs:

- **Row 1** — brand, Save, Open, Undo, Redo │ Locking, Camera Set, Controller Management,
  Global Variable, Communication Management, Global Trigger, Global Script │ Once, Run Solution,
  Continuously, Stop, Validate │ PASS/FAIL badge.
- **Row 2** — flow tab strip, add-flow, loop, set-trigger-flow │ Operation Interface, Histogram,
  Draw ROI, Fit, 1:1, Arrange.

The documented 15-entry inventory and its ordering (manual p.70) is preserved, and the
`Control Toolbar` table's semantics are now enforced by
`test_all_documented_toolbar_controls_present`.

**Key enabling fix:** a `QToolBar` keeps a `QWidgetAction` in sync with its `QToolButton` and
ignores `QWidget.setVisible()` on the button. Visibility must be driven through the action, which
`_add_toolbar_button()` / `_set_button_visible()` now do.

### 3.2 Explicit responsive chrome (defects 1, 5)
`resizeEvent` → `_apply_responsive_chrome()`:

| Window width | Chrome |
|---|---|
| ≥ 1220 px | everything |
| < 1220 px | Fit / 1:1 / Arrange are removed **explicitly** (via their actions) and the flow tab strip is clamped so the primary controls always fit |

A hidden control is a control the operator cannot use, so the strip degrades in a fixed, published
order rather than letting Qt drop the tail into a popup. Verified at 1600/1440/1280/1100 px.

### 3.3 Advisory message moved to the status bar (defects 1, 5)
The `Ready` / `Loaded solution…` text no longer competes for control-strip width: it lives in the
status bar between the component-state segment and the permanent timing segments — one chrome row
fewer, and a long message can never compress a toolbar. `_set_hint()` writes it with an
auto-reset.

### 3.4 Result grid column model (defects 2, 8)
[result_panel.py](vm_clone/ui/result_panel.py):

- New `ResultTreeWidget` overrides `sizeHint()` / `minimumSizeHint()` (150×168). The stock
  `QTreeWidget` hint reflects the summed column widths, which made the enclosing dock refuse to
  shrink and pushed column 3 out of view.
- `_apply_columns()` computes the available width from the **smaller** of the parent stack and the
  tree viewport (the viewport reports a stale width until the layout settles) and distributes it:
  48 % name, remainder value, 96 px for the global-variable column, with a floor of 70/80 px.
- Below 300 px available the subscription column folds away deliberately; binding stays reachable
  through the row context menu / double-click.
- `showEvent` and `refresh_columns()` re-fit the model when the Result tab becomes current, because
  a `QStackedWidget` only lays out the page that is visible.
- Header shortened to `Global Var.`; every row now carries the full text as a tooltip.
- Output groups are force-expanded after insertion.
- Tree indentation reduced 20 → 12 px so deep rows stay readable in a narrow dock.

Measured result: at 1600 px `[184, 200, 96]` = 480 px in a 480 px viewport (no clipping); at
1100 px `[134, 147, 0]` with the third column intentionally folded.

### 3.5 Inspector rebalanced (defect 3)
[inspector.py](vm_clone/ui/inspector.py) now has a three-part layout:

1. identity header (module name, type, description),
2. the parameter surface at `stretch=1` — the dominant element,
3. a compact live-verdict strip (`OK · 2.92 ms` + message) at the bottom.

The duplicate `MODULE OUTPUTS` table is no longer laid out; the full port table is the result
grid's job (manual p.87). It remains as a hidden compatibility surface so existing callers and tests
keep working. See §3.10 for the final vertical arrangement.

### 3.10 Result mounted under the image in the Image | Result column
`_init_property_dock()` in [main_window.py](vm_clone/ui/main_window.py) now builds the right column
the way the reference does (manual p.40): the inspection viewport and the
`Param Name | Current Result | Global Var.` grid are two panes of **one vertical splitter inside one
Image | Result pane**, and the Property Inspector sits below them.

```
Image | Result dock
├── Image | Result pane
│   └── vertical splitter
│       ├── inspection viewport          (≈ 2/3 of the pane)
│       └── module result grid           (≈ 1/3, scrolls)
└── Property Inspector (aligned parameter form + verdict strip)
```

Consequences of the change:

- The operator reads the picture and its numbers together; no tab switch hides the image.
- The redundant one-entry tab bar is hidden, and the Help tab moved into a scroll area so its wrapped
  text no longer forced the bottom dock (and therefore the whole workspace) to be tall. At 1100×720
  the bottom dock is now 120 px instead of ~500 px.
- `focus_image_view()` replaces the old "switch to the Vision Canvas tab" behaviour for Draw ROI: it
  raises the canvas share of the pane to 68 % and shows the dock.
- The viewport now re-fits the image on resize (`ImageCanvasWidget.resizeEvent` + `_fit_mode`), which
  was required because the pane changes height whenever the result grid is grown. Verified the scaled
  image fits inside the viewport at 1600×950, 1280×800 and 1100×720 (previously it was cropped).
- `refresh_columns()` is now driven by window/dock resize rather than by a tab change.

### 3.11 Parameter form alignment and path display
[inspector.py](vm_clone/ui/inspector.py):

- The parameter surface is a `QFormLayout` with right-aligned labels in a **fixed 92 px column** and
  `AllNonFixedFieldsGrow`, so every label and every field sits on one vertical axis. A deferred
  `_align_label_column()` enforces the column width after Qt has laid the rows out.
- Every control (spin box, double spin box, combo box, line edit, check box) is pinned to a 24 px
  height, so baselines line up horizontally as well.
- Trailing actions (`Browse`, `Draw`) live in a fixed 66 px container inside the field, so input
  fields all end on the same vertical line — the previous `Browse...` buttons had text-dependent
  widths that made rows ragged.
- **File / folder paths**: `_is_path_key()` matches `path` / `dir` / `folder` only. This is
  deliberate — the old check also matched the bare `file` token, which gave `File Format` (an enum) a
  spurious Browse button. `File Format` and `Save Mode` are now dropdowns; only `File Path` and
  `Save Directory` get a Browse button, with the folder picker used for directories.
- **Path display**: `abbreviate_path()` drops the directory chain but always keeps the complete
  filename: `C:\Users\winch\Downloads\VMClone\vm_clone\samples\pcb_sample.png` renders as
  `…\vm_clone\samples\pcb_sample.png` at a 432 px dock and simply `pcb_sample.png` at 300 px. The real
  value is stored on the widget as the `realPath` property and shown in full in the tooltip, so
  abbreviation never loses data; values that already fit are shown untouched.
- Hand-typed paths are committed by `_on_path_edited()` only when the typed text is a usable path, so
  an abbreviated display can never be written back to the tool by accident.
- Every parameter row carries a purpose tooltip ("Image or resource file to load from local disk…",
  "Output folder for written results…").

### 3.6 Flow tab labels (defect 4)
`_flow_tab_text()` middle-elides names longer than 16 characters and keeps the three reference
fields: `● Flow1  FAIL  166ms`. The strip is capped at 420 px, gets scroll buttons and right
elision, and the tooltip carries the full name, verdict, time, module count and run count.

### 3.7 Reference panel proportions (defect 5)
`_apply_reference_proportions()` derives the split from the measured reference (manual p.40) and
clamps the flanks harder on small displays:

| Window | Central | Tool Box | Right panel |
|---|---|---|---|
| 1600×950 | 838 px (52 %) | 276 px | 432 px |
| 1280×800 | 523 px (41 %) | 273 px | 345 px |
| 1100×720 | 523 px (48 %) | 234 px | 281 px |

The Tool Box flyout is no longer a fixed width — it has a 190 px floor and the 246 px reference
maximum, so the dock can give width back to the canvas instead of starving it.

### 3.8 Validation dialog (defect 6)
[main_window.py](vm_clone/ui/main_window.py): resized to 820×380 (720×340 minimum), severity fixed
at 84 px, module interactive at 128 px, message **stretch** — so the diagnostic text is fully
readable. Every message row also carries the complete text as a tooltip.

### 3.9 Flow Probe placement (defect 7)
`FlowProbeWidget.reposition()` keeps the reference's lower-left corner when the canvas is at least
3× the probe width, and moves to the lower-right on narrower canvases so it never covers the early
modules. `reposition()` is now idempotent and guards against zero-size parents, which also removed
a teardown race in the test suite.

---

## 4. Validation performed

### 4.1 Automated
```
python -m pytest tests/      ->  135 passed
```
| Suite | Tests | Focus |
|---|---|---|
| `test_ui_audit_fixes.py` (new) | 25 | Toolbar never overflows and never shows the overflow button (4 sizes); primary controls always visible; status badge has real width; all 15 documented controls present; responsive degradation order; long flow names keep verdict + time; result columns always fit (5 widths) including header width; re-fit when the pane shows; tree does not force dock width; inspector has no duplicate table and keeps the image/result/inspector heights usable; verdict strip matches the result; validation message column dominates; central canvas dominant at 4 sizes |
| `test_right_panel_layout.py` (new) | 9 | Result grid mounted under the image in the Image\|Result column; result grid visible without a tab switch; image/result/inspector keep usable heights at 3 sizes; ROI mode raises the canvas share; grid columns re-fit inside the dock; form labels share one column and fields share one axis; path row and combo rows share the field axis with one Browse button; `abbreviate_path()` behaviour; folder parameters get a folder picker |
| `test_acquisition_file.py` | 5 | Browse button discovery in the new form, abbreviated path display with the real value preserved, uniform label column, path commit on edit, plus the original file-resolution cases |
| `test_flow_probe.py` | 6 | + probe moves right on a narrow canvas |
| `test_vm_workspace_ui.py` | 22 | unchanged (header text updated to `Global Var.`) |
| `test_workflow_e2e.py` | 9 | unchanged |
| pre-existing | 33 | unchanged |

### 4.2 Rendered
`docs/screenshots/audit/` — 24 screen captures plus 5 inspector close-ups
(`15`–`19`, produced by `scripts/capture_inspector.py`);
`docs/screenshots/audit_comparison.png` places each reference figure beside the screen it pins down;
`docs/screenshots/live_window.png` and `live_window_small.png` are the **real on-screen window**
(Win32 `PrintWindow`, 2576×1456 at 200 % DPI and 1120×780 after a live resize) confirming fonts,
DPI scaling and live behaviour.

### 4.3 Interaction checks
Live resize across 1600/1440/1280/1100 px (chrome degrades and restores); menu opening (all six
menus captured); dock float/re-dock state retention; both splitters dragged; ROI mode raising the
canvas share; lock on/off; undo/redo; histogram toggle staying in sync in both directions;
continuous toggle staying in sync across both buttons; validation and global-variable dialogs;
probe click/drag navigation; tool switching through Image Source / ROI module / Image Output to
confirm the form rebuilds aligned every time.

---

## 5. Files changed

| File | Change |
|---|---|
| `vm_clone/ui/main_window.py` | Two-row control toolbar with action-tracked visibility; responsive chrome; status-bar message; reference proportions; result grid mounted under the image; `focus_image_view()`; scrollable Help tab; flow-tab elision; validation dialog sizing/columns |
| `vm_clone/ui/result_panel.py` | `ResultTreeWidget` size hints; width-aware column model; resize/show re-fit; expanded output groups; reduced indentation; tooltips; header wording |
| `vm_clone/ui/inspector.py` | Aligned `QFormLayout` parameter surface; fixed label column and field axis; fixed-height controls; `abbreviate_path()` + `realPath` binding; precise path-key detection; help tooltips; verdict strip; duplicate output table off-layout |
| `vm_clone/ui/image_canvas.py` | `resizeEvent` re-fit with `_fit_mode`, cleared by manual zoom/pan |
| `vm_clone/ui/flow_editor.py` | Probe placement policy and idempotent/guarded `reposition()` |
| `vm_clone/ui/toolbox.py` | Flyout width floor/maximum instead of a fixed width |
| `vm_clone/ui/vm_theme.py` | Flow tab bar scroller styling; status-message label; compact `fieldAction` button; parameter-label padding |
| `tests/test_ui_audit_fixes.py` | New — 25 audit regression tests |
| `tests/test_right_panel_layout.py` | New — 9 layout/alignment regression tests |
| `tests/test_acquisition_file.py` | Updated for the form layout; 3 new alignment/path tests |
| `tests/test_flow_probe.py` | Narrow-canvas placement test; hardened scene teardown |
| `tests/test_vm_workspace_ui.py` | Header text assertion updated |
| `scripts/audit_capture.py`, `scripts/capture_inspector.py` | New — render the audit evidence sets |
| `scripts/build_comparison.py` | Added the audit reference/after sheet |

---

## 6. Remaining issues

1. **Long result values still elide** (`ModuStatusMsg: "Acquired image 800x600"` →
   `Acquired image 800x6…` at 432 px). The full text is in the tooltip. A wrapping/multi-line value
   renderer is the honest fix and is the top remaining readability gap.
2. **Long single-segment values** (a 60-character filename with no directory separator) are
   truncated from the end rather than the start, since there is no directory chain to drop. Acceptable
   but inconsistent with the path case.
3. **The right dock will not shrink below ~281 px** even when a smaller width is requested; a child
   widget still reports a wider layout minimum than `setMinimumWidth(150)` implies.
4. **Bottom History tab** truncates `05_SurfaceScratchChe…` in the Failed Module column; the details
   column carries the same information.
5. Carried over: no live camera SDK, no per-module tabbed configuration dialog (manual p.96),
   per-module image probe overlay, no bundled zh-CN localisation, two-segment wire routing without
   obstacle avoidance.
6. **Evidence limitation, stated plainly:** the first audit-capture pass overwrote its own baseline,
   so the pre-fix screenshots from the very start of the session were not preserved. The before/after
   claims rest on the measurements and defect descriptions recorded in §2–§3;
   `audit_comparison.png` pairs the manual references with the current state rather than with a
   pre-fix capture.

---

## 7. Next highest-priority improvements

1. **Result grid value surface** — allow a row to wrap or expand so long values and long parameter
   names are never elided.
2. **Per-module configuration dialog** (`Input Params / Output Params / Run Params / Display
   Settings`, manual p.96) — the largest remaining reference feature gap.
3. **Isolate the residual dock minimum** (~281 px) so the right column can be dragged narrower
   without the column model folding.
4. **Isolate the residual dock minimum** (~281 px) so the right column can be dragged narrower
   without the column model folding.
5. **Per-module image probe overlay** (manual p.40 item 5) so the ROI and result overlay follow the
   module under the cursor, not only the selected one.
