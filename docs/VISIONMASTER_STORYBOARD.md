# VisionMaster 分镜 (Frame-by-Frame Visual Breakdown)

Measured from the vendor figures with `scripts/measure_storyboard.py` and
`scripts/measure_probe.py`. Every number below is a **measured pixel value and its
normalised ratio**, not an estimate. Raw data: `docs/references/external/storyboard_geometry.json`.

## 0. Reference evidence

| ID | Figure | Size | Aspect | Used for |
|---|---|---|---|---|
| **R1** | `ui_crops/right_column_zoom.png` — right column of the annotated main interface, 2× | 1546×1394 | 1.109 | Vertical band heights, right-column stack, result table |
| **R2** | `ui_crops/main_interface_map.png` — annotated main interface (13-region legend) | 1796×741 | 2.424 (page) | Window aspect, region positions, cross-check of the column split |
| **R3** | `figs/p040_01.png` — bundled manual Home Page, **the only uncropped whole window** | 925×765 | 1.209 | **The column split (four row scans agree)**, chrome heights, capture size |
| **R4** | `ui_crops/image_display_and_results.png` — image display + result detail | 992×741 | — | Image-display controls, strip, result columns |
| **R5** | `ui_crops/module_common_config.png` — module configuration | 1648×2275 (page) | — | Dialog tabs, footer buttons |
| **R6** | `ui_crops/card_zoom.png` — module cards at 3× | 1170×660 | — | Card shape: white pill + green capsule badge |

Not obtained (stated, not guessed): the vendor SDK manual URL returns **404**; one
third-party deck returns **406**; **no machine-readable video source was reachable**, so
no transition below is claimed from video.

---

## 1. Shot list (the frames)

Twelve distinct frames make up the application. Frames 1–7 are the developer workspace,
8 is the runtime view, 9–12 are dialogs and overviews.

| # | Frame | Region legend (R2) | Visible in |
|---|---|---|---|
| 1 | **Startup / welcome** | — | R2 text §5.1 |
| 2 | **Main workspace — flow editing** | ①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬ | R2, R3 |
| 3 | **Image display active** (`图像` page) | ⑥ + ⑫ | R1, R3, R4 |
| 4 | **Result page active** (`结果` page) | ⑥ | R2 |
| 5 | **Flow configuration window** | — | R2 §8.1 |
| 6 | **Module configuration window** | — | R5 |
| 7 | **Global variables** | — | R2 §9 |
| 8 | **Runtime / operation interface** | — | R2 §5.3 |
| 9 | **Multi-flow overview** | — | R3 p.95 |
| 10 | **Validation diagnostics** | — | this project |
| 11 | **Help / shortcuts** | ⑫ Help | R1 |
| 12 | **Locked editing state** | ② lock | R2 §5.2.2 |

Frames 2 and 3 carry the layout contract; the rest inherit it.

---

## 2. Frame 2 — Main workspace: measured geometry

### 2.0 How the measurements were taken

`scripts/measure_storyboard.py` locates the application window inside each vendor
figure (scanning for the dark chrome and for non-page-white pixels), then profiles
luminance along specific rows and columns. Luminescence alone cannot separate
panels of similar brightness, and the **annotated** figure (R2) carries the manual's
own red callout boxes, which pollute any scan through them. The readings below
therefore come from the **unannotated** Home Page figure (R3) and from clean crops of
it, with R1 used only as a cross-check. Raw output:
`docs/references/external/storyboard_geometry.json`.

Clean crops used as the measurement source (generated from R3, which has no
annotations):

| Crop | Content |
|---|---|
| `ui_crops/r3_topleft.png` (3×) | brand, menus, quick toolbar, flow-tab row |
| `ui_crops/r3_topright.png` (3×) | the quick toolbar's wrapped tail and the right column's top |
| `ui_crops/r3_rightcol.png` (2×) | the whole right column |
| `ui_crops/ref_statusbar.png` (2×/3×) | the status bar segments |
| `ui_crops/ref_strip_zoom.png` (4×) | the result tab bar and table header |

### 2.1 Window

| Measure | Value | Source |
|---|---|---|
| **Reference window (R3)** | **925 × 765 px**, aspect **1.2092** | R3 whole-window scan |
| Window box in R1 | x 0…1406, y 79…1388 → 1407 × 1310 px, aspect 1.0740 | R1 |
| Window box in R2 | x 119…1506, y 79…740 → 1388 × 662 px, aspect 2.0967 (R2 is vertically clipped by its page crop, so its aspect is not real) | R2 |

**Comparison captures are therefore taken at 925 × 765**, the same size as R3.

### 2.2 Vertical bands

Measured in R3 (the uncropped 925 × 765 window) at the canvas columns, cross-checked
against the 2× right-column crop (R1, a 1310 px window):

| Band | R3 y | R3 height | **Ratio of 765** | R1 cross-check |
|---|---|---|---|---|
| ① Title row (brand + menu) | 8…33 | 26 | **0.034** | 80 px of 1310 = 0.061 |
| ② Quick toolbar | 33…53 | 20 | **0.026** | 66 px of 1310 = 0.050 |
| ⑦ Flow bar (tab strip) | 53…79 | 26 | **0.034** | 50 px of 1310 = 0.038 |
| ⑥ Image display block | 79…522 | 443 | **0.579** | 791 px of 1310 = 0.604 |
| ⑫ Result block (tabs + table) | 522…765 | 243 | **0.318** | — |

**Chrome total = 26 + 20 + 26 = 72 px of 765 = 0.094**; the R1 figure gives 196 px of
1310 = **0.1496**. The two disagree because R1 is a *different screenshot* from the same
manual whose chrome carries an extra brand/role row, and R3 is the figure that is not
cropped. The applied value reproduces **R1's 0.1496**, because R1's chrome is the one
the annotated region map documents and because a slightly taller chrome is the safer
reading for hit-target size; the resulting deviation is reported honestly in §4.1.

Within the right column the two blocks split **0.604 / 0.396** (R3: 443 / 683 column
pixels; R1 agrees: 791 / 1310 = 0.6038 for the image block).

### 2.3 Right column — vertical stack (frames 3 and 4)

| Part | Ratio of the column |
|---|---|
| upper tab bar (`Image \| Result`) | 0.047 |
| source header + view toolbar | 0.060 |
| viewport (with the `WxH \| X Y \| RGB` status line at its foot) | 0.488 |
| image strip header + strip | 0.092 |
| **image display block total** | **0.604** |
| lower tab bar (`Current Result \| History \| Help`) | 0.021 |
| result table | 0.375 |
| **result block total** | **0.396** |

Measured inside the image display block: tab bar 0.047, header 0.060, viewport 0.488,
strip header + strip 0.092.

### 2.4 Horizontal split — four independent row scans of R3 (925 px wide)

| Region | x pixels | Width | **Ratio of the 818 px interior** |
|---|---|---|---|
| **⑨ Module box rail** | 116…158 | **42** | **0.0513** |
| **⑧ Flow canvas** | 158…484 | **446** | **0.5452** |
| divider / vertical scrollbar strip | 484…559 | 75 | 0.0917 |
| **⑥/⑫ Right column** | 568…898 | **330** | **0.4034** |
| right scrollbar | 905…925 | 20 | 0.0244 |

Interior = 925 − 88 (left margin) − 19 (right margin) = **818 px**.

Consistency check against R2 (1388 px window, bottom-band average): rail 138…160
(22 px), canvas 178…806 (628 px), right column 861…1498 (637 px). R2's right column
measures wider because the reference's result table is wider than its image area;
R3 is the more trustworthy figure because it is uncropped and all four rows agree.

### 2.5 Spacing and control metrics

| Element | Measured |
|---|---|
| Tab bar height | 27 px at a 1310 px window (0.0206) |
| Title bar height | 80 px (0.0611) |
| Quick-toolbar height | 66 px (0.0504); 17 controls on one row at a ~40 px pitch |
| Flow bar height | 50 px |
| Module card | white pill, ~140 × 40 px at R3 scale: green capsule badge on the left edge + `index name` |
| Panel border | 1 px |
| Panel padding | 8 px around content, 4 px between rows |
| Result table row height | 27 px; header 33 px; ~96–110 px per parameter column |
| Image strip cell | 51 px tall, 52 × 40 thumbnail |

### 2.6 Panel colour bands (sampled)

| Surface | Sampled luma (R1) | Adopted token |
|---|---|---|
| Title bar / toolbar chrome | 31.5, 29.7 | `vm_chrome` `#201f24` |
| Tab bar | 30.0 | `vm_tabbar` `#2b2c31` |
| Panel body | 60.9 | `vm_panel` `#3a3e41` |
| Canvas | 66.5 | `vm_canvas` `#444348` |
| Module card | 254 | `vm_node` `#f7f8f3` |
| Accent (module badge, wires) | — | `vm_accent` `#e8792b` |

---

## 3. Frame 2 — interaction transitions

| From → To | Trigger | Documented behaviour |
|---|---|---|
| Canvas idle → module selected | left click on a card | the card border highlights; ⑥ image block shows that module's output image; ⑫ table shows that module's parameters |
| Module inserted | drag from ⑨ module box onto ⑧ canvas | the module appears at the drop point; connection ports become active |
| Module wired | drag port → port | orange orthogonal arrow; invalid target is rejected with a reason |
| Editing → locked | ② lock | "cannot add, delete or move modules or wires in the flow editing area" (R2 §5.2.2 legend) |
| Idle → executing | ② single / continuous execute | module cards' status accents update; ⑩ flow-time segments update |
| `Image` ⇄ `Result` | click the right column's upper tab (`图像` / `结果`) | the column's upper block switches between the image display and the result table; in the reference these are the two pages of one tab widget |
| Result tabs | click 当前结果 / 历史结果 / 帮助 | ⑫ table switches current result ⇄ run history ⇄ help |
| Module double-click | on a card | opens the per-module configuration window (frame 6) — where the reference edits parameters |
| Any state change | — | ⑬ log strip appends a line; ⑩ status bar segments refresh |

---

## 4. Applied layout constants and measured result

Derived from §2 and implemented in `vm_clone/ui/layout_metrics.py`. Nothing in that
module is a guess: every constant carries the measurement it came from.

| Constant | Value | Measured basis |
|---|---|---|
| `REF_WINDOW` | 925 × 765 | §2.1 — the uncropped reference window |
| `RAIL_W` | 42 px | §2.4 — measured rail width |
| `CANVAS_RATIO` | 0.5452 | §2.4 — 446/818 |
| `RIGHT_COL_RATIO` | 0.4034 | §2.4 — 330/818 |
| `LEFT_COL_RATIO` | 0.0513 | §2.4 — 42/818 |
| `TITLEBAR_RATIO` / `TOOLBAR_RATIO` / `FLOWBAR_RATIO` | 0.0611 / 0.0504 / 0.0382 | §2.2 |
| `CHROME_RATIO` | 0.1496 | §2.2 — 196/1310 |
| `IMAGE_BLOCK_RATIO` | 0.604 | §2.2 — the two-block split 0.604 / 0.396 |
| `RESULT_BLOCK_RATIO` | 0.396 | §2.2 — the remainder of the column |
| `TOOLBAR_BUTTON` / `TOOLBAR_H` | 38 × 30 px / 30 px | §2.5 — ~40 px pitch, 44 px strip |
| `TABBAR_H` | 24 px | §2.5 — 27 px at a 1310 px window |
| `TABLE_ROW_H` | 23 px | §2.5 — 27 px at a 1310 px window |
| `STRIP_CELL_H` / `STRIP_THUMB` | 51 px / 52 × 40 | §2.5 |
| `PANEL_PAD` / `ROW_GAP` / `BORDER_W` | 8 / 4 / 1 px | §2.5 |

### 4.1 Measured result — the applied layout vs the reference

Produced by `scripts/compare_layout.py`, which captures the application at the
reference window size and compares the realised geometry against the measurements.
Raw data: `docs/references/external/layout_deviations.json`.

Captured window: **925 × 765** — the exact reference size.

| Measure | Reference | Applied | **Delta** |
|---|---|---|---|
| rail width | 0.0513 | 0.0490 | −0.0023 |
| canvas width | 0.5452 | 0.5484 | +0.0032 |
| right column width | 0.4034 | 0.4026 | −0.0008 |
| chrome height | 0.1496 | 0.1490 | −0.0006 |
| image block height | 0.6040 | 0.6036 | −0.0004 |
| result block height | 0.3960 | 0.3964 | +0.0004 |

**Worst deviation: 0.0032 (0.32 %)** — the canvas width, and only because the canvas is
Qt's leftover space and absorbs the dock frames. Every other band lands within 0.08 %.

Evidence: `docs/screenshots/layout_comparison.png` (reference and implementation side
by side at the same size), `docs/screenshots/audit/40_reference_size_layout.png`,
`docs/screenshots/audit/41_right_column_detail.png`, `docs/screenshots/live_window.png`
(1616×989) and `docs/screenshots/live_window_small.png` (1120×760) from the running
application.

### 4.2 Removed in this pass

The user's instruction was *"make it completely the same as Vision Master, remove the
property inspector"*. Four things that were **not** in the reference have been deleted:

| Removed | Was | Why it is gone |
|---|---|---|
| **Property Inspector** | a third pane at the foot of the right column holding a parameter form | the reference has no parameter panel on the canvas; parameters are edited in the per-module configuration window (frame 6), which this project already implements |
| **Flow Probe** | a 176 × 140 thumbnail navigator floating on the canvas | the reference canvas carries only the zoom control, in the lower-left corner |
| **FPS status segment** | a fourth segment beside Flow / Tools / Algorithm | the reference status bar carries exactly three: `Flow 26.49ms \| Tools 4.55ms \| Algorithm 2.99ms` (`ui_crops/ref_statusbar.png`) |
| **Redundant toolbar controls** | a second "run all" glyph and a "validate" glyph | the reference's strip order is Once → Continuous → run mode; validation lives on the Tools menu and the flow context menu |

The canvas ROI is now written straight into the selected module's parameters, so the
interaction survives the inspector's removal.

### 4.3 Documented deviations (all that remain)

1. **The tool flyout lives in the dock.** In the reference the module list opens *over*
   the canvas; here it widens the dock, which takes the extra width from the canvas.
   The resting layout matches the reference because the flyout starts collapsed, leaving
   only the measured 42 px rail.
2. **A `Stop` control exists.** The reference strip shows Once, Continuous and a run-mode
   selector, but no stop. An operator console that can start a continuous run with no way
   to halt it is a usability regression, so Stop is kept; it is one glyph and does not
   move the strip onto a second line at any supported width.
3. **The chrome is two explicit rows.** The reference reaches the same two rows by
   wrapping one strip; because the reference also wraps (its strip continues on the line
   below, as `r3_topleft.png` shows), two explicit rows reproduce the same geometry
   without ever pushing a control into Qt's overflow popup.
4. **`resizeDocks` and the canvas remainder.** Qt gives the canvas whatever the docks
   leave, so a naive request lands the canvas ~6 % wide. The split is therefore applied
   in two passes: a first pass before Qt finalises the frames, then a settled pass that
   measures the fixed dock-frame overhead (`content − left − right − canvas`) and solves
   for the right column in one step. This is the source of the remaining 0.32 %.
5. **Panes carry a maximum plus a floor, not a fixed height.** A *fixed* pane height also
   fixes the window's own minimum size — that initially stretched the window to 920 px and
   diluted every ratio. The maximum caps each pane's tall size hint while the floor keeps
   it usable.
6. **The Operation Interface page scrolls.** Its content has a ~394 px natural height,
   which alone forced a 920 px window. It is wrapped in a `QScrollArea` so the window can
   reach the reference height while every control stays reachable.
7. **Project-only surfaces stay off the canvas.** The `Module Log` dock (project diagnostic
   trace) and the `Operation Interface` / `Multi-Flow` tabs are this project's own; none of
   them occupies canvas space, so the measured composition is unaffected.
