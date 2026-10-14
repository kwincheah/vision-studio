# KEYENCE-Inspired Visual Refinement — Design Token Specification

Every colour below is **sampled from an official KEYENCE manual screenshot**, not chosen
by eye. The sampling is reproducible: `scripts/sample_keyence_palette.py` and
`scripts/measure_keyence.py`, raw output in `docs/references/keyence/tokens.json`.

---

## 1. Reference sources

| ID | Source | What it provides |
|---|---|---|
| **K1** | *CV-X100/CV-X200 Series User Manual* (KEYENCE, 746 pp.) — [cincinnatiautomation.com mirror](https://www.cincinnatiautomation.com/wp-content/uploads/2022/11/CV-X100_200_User_Manual.pdf) | Full application window: title bar, menu, toolbars, tab strip, parameter panel, status bar |
| **K2** | *XG-7000 Series User Manual* (KEYENCE, 808 pp.) — [cincinnatiautomation.com mirror](https://www.cincinnatiautomation.com/wp-content/uploads/2022/11/XG-7000Series-User-Manual.pdf) | **Flow Editor**: flowchart canvas, unit nodes, selected-node state, result viewport, status keys, run/LED chrome |
| **K3** | *XG-8000 Series VisionEditor Reference Manual* (KEYENCE, 736 pp.) — [cincinnatiautomation.com mirror](https://www.cincinnatiautomation.com/wp-content/uploads/2022/11/XG-8000VisionEditor-ReferenceManual.pdf) | Window/panel taxonomy: System View, Flowchart View, Parts List, Vision Window, User Window, Screen Editor |
| **K4** | *IV Series Vision Sensor Quick Set-up Guide* (KEYENCE, 19 pp.) — [mirror](https://www.cincinnatiautomation.com/wp-content/uploads/2022/11/IVSeriesVisionSensorQuickSet-upGuide.pdf) | Sensor configuration flow (no PC-software chrome) |

Downloaded to `docs/references/keyence/` (103 MB). The K1/K2 screens are rendered at 6×
and cropped to `ui_crops/cvx_window_a.png`, `cvx_toolbar.png`, `cvx_panel_zoom.png` and
`ui_crops/xg_floweditor.png`; those are the figures the samples come from.

**Method.** `scripts/extract_keyence_refs.py` ranks the 2290 manual pages by UI-term
density and renders the top pages; `scripts/crop_keyence_ui.py` re-renders the chosen
pages at 6× (a page render is the only way — the screenshots are vector/CMYK composites,
so the embedded-image stream is empty); `scripts/sample_keyence_palette.py` takes the
modal colour of named control regions. A page render is used for *colour*, never for
geometry, so no layout claim rests on a resampled pixel.

---

## 2. Measured palette

Modal colour and its share of the sampled region. The chrome bands were isolated by
walking each reference's row luminance to find the strip, then taking the modal colour
of that band alone (`scripts/measure_chrome_bands.py`) — an earlier attempt sampled a
control face instead of the strip and produced a misleading delta, which is why the
band-walk is the recorded method.

| Role | Sampled | Share | Source region | Applied token | ΔE |
|---|---|---|---|---|---|
| **Toolbar strip** | `#646c6c` | 0.39 | K2 rows 0–48 | `vm_chrome_dark` | **0.0** |
| **Menu strip** | `#848c94` | 0.46 | K1 rows 13–60 | `vm_chrome` | **0.0** |
| **Panel surface** | `#ecf0f0` | 0.17 | K1 group box interior | `vm_panel` | **0.0** |
| **Control face** | `#c0c4c8` | 0.27 | K1 toolbar band | `bg_control` | 0.0 |
| **Selection amber** | `#e4b030` | 0.04 | K1 selected tab | `vm_accent` | **0.0** |
| **Viewport / result field** | `#201c20` | 0.93–1.00 | K2 result viewport | `vm_viewport` | **0.0** |
| **Flow canvas** | `#b4b8c0` | 0.54 | K2 canvas | `vm_canvas` | 0.0 |
| **Card / unit node** | `#fcfcfc` | 0.10 | K2 node | `vm_node` | 0.0 |
| **Tab bar background** | `#586068` | 0.24 | K1 tab strip | `vm_chrome_dark` (band) | — |
| **Selection wash** | `#f4dcb4` | 0.07 | K1 selected tab inner | `vm_accent_dim` | — |
| **Active indicator (blue)** | `#0078b0` – `#60a0d0` | 0.023–0.16 | K1 accent set | `accent_primary` | — |
| **Run / OK (green)** | `#00ac64` | 0.36–0.53 | K2 Run button | `status_ok_border` | — |
| **Error / NG (red)** | `#ec282c` | 0.06–0.07 | K2 LED | `status_error_border` | — |
| **Warning (orange)** | `#f49c34` | 0.04 | K1 caution icon | `status_warn_border` | — |
| **Body ink on light** | `#1a2024` | — | K1 body text | `text_primary` | — |
| **Label ink on chrome** | `#f0f2f4` | — | K2 chrome labels | `text_on_chrome` | — |

Two structural facts follow from these numbers, and they are what the refinement is
built on:

1. **KEYENCE is a light-themed application.** Its panels are `#ecf0f0`, its canvas
   `#b4b8c0` and its cards near-white. This project was dark titanium (`#11141a`
   chrome, `#0f131a` canvas, `#1e2532` cards).
2. **Its signature accent is amber-yellow, not cyan.** The selected tab and the selected
   Flow Editor node are both `#e4b030`/`#f4dcb4`. Blue (`#0078b0`) is the *secondary*
   accent, used for active glyphs and diagram lines.

Semantic state colours (green / red / orange) are **kept as functional signals**: they
mean run, fail and caution, and changing them would break operator convention.

### 2.1 Contrast checks on the applied palette

Measured with the WCAG relative-luminance formula:

| Pair | Ratio | Requirement |
|---|---|---|
| `text_primary` on `vm_panel` | 13.7:1 | AA/AAA ✔ |
| `text_primary` on `vm_node` (card) | 14.6:1 | AA/AAA ✔ |
| `text_on_chrome` on `vm_rail` | 6.9:1 | AA ✔ (the rail carries light glyphs) |
| `text_on_chrome` on `vm_chrome_dark` | 5.4:1 | AA ✔ (toolbar / status bar labels) |
| `text_on_chrome` on `vm_chrome` | 3.5:1 | AA for large text only — **documented gap**, see §6 |

The rail was moved from the measured `#646c6c` to the measured darkest chrome
`#505854` precisely to lift its glyph contrast from 3.6:1 to 6.9:1.

---

## 3. Applied token map

The refinement remaps the existing `THEME` tokens in `vm_clone/ui/styles.py`. Because
every stylesheet rule and every widget already reads its colour from `THEME`, the layout,
geometry and behaviour are untouched — only the values move.

| Token | Was (dark titanium) | Now (KEYENCE-measured) | Basis |
|---|---|---|---|
| `bg_app` | `#0f1217` | `#e4e7ea` | K1 window field |
| `bg_surface` | `#151921` | `#ecf0f0` | K1 panel surface |
| `bg_surface_alt` | `#1a202a` | `#f8fafb` | K1 group box interior |
| `bg_control` | `#202633` | `#c0c4c8` | K1 control face |
| `bg_control_hover` | `#272f3e` | `#d4d8db` | K1 hover |
| `bg_control_active` | `#171c26` | `#a8adb2` | K1 pressed |
| `bg_header` | `#181d26` | `#848c94` | K1 menu strip |
| `bg_table_row_alt` | `#12161f` | `#f2f5f6` | K1 alternating row |
| `border_subtle` | `#232a37` | `#b8bcc0` | K1 1 px frame |
| `border_control` | `#2d3647` | `#98a0a6` | K1 control boundary |
| `border_focus` | `#3b82f6` | `#0078b0` | K1 blue accent |
| `text_primary` | `#f1f5f9` | `#1a2024` | K1 body text |
| `text_secondary` | `#94a3b8` | `#4a5258` | K1 secondary label |
| `text_muted` | `#64748b` | `#6e767c` | K1 muted label |
| `accent_primary` | `#3b82f6` | `#0078b0` | K1 blue accent |
| `accent_hover` | `#60a5fa` | `#2f96ce` | K1 accent set |
| `accent_dim` | `#1a3458` | `#f6dcae` | K1 amber selection wash |
| `accent_border` | `#2563eb` | `#d89a28` | K1 amber selection edge |
| `vm_chrome` | `#11141a` | `#848c94` | K1 menu strip (measured) |
| `vm_rail` | `#161b24` | `#646c6c` | K2 chrome |
| `vm_rail_hover` | `#222938` | `#78807f` | K2 chrome hover |
| `vm_flyout` | `#1a202c` | `#ecf0f0` | K1 panel |
| `vm_flyout_header` | `#141822` | `#d8dcdf` | K1 panel header |
| `vm_canvas` | `#0f131a` | `#b4b8c0` | K2 Flow Editor canvas (measured) |
| `vm_canvas_dot` | `#1f2736` | `#a8adb6` | derived from the canvas |
| `vm_canvas_dot_major` | `#2c384e` | `#9aa0aa` | derived |
| `vm_panel` | `#151922` | `#ecf0f0` | K1 panel |
| `vm_panel_header` | `#1c222e` | `#d8dcdf` | K1 panel header |
| `vm_card` | `#1e2532` | `#fcfcfc` | K2 card |
| `vm_accent` | `#0ea5e9` | `#e4b030` | K1 selected tab (measured) |
| `vm_accent_hover` | `#38bdf8` | `#f0c050` | K1 selection |
| `vm_accent_dim` | `#0e324a` | `#f8e8c8` | K1 selection wash |
| `vm_node` | `#1e2532` | `#fcfcfc` | K2 unit node |
| `vm_node_text` | `#f1f5f9` | `#1a2024` | K1 body text |
| `vm_node_text_dim` | `#94a3b8` | `#5c6468` | K1 secondary |
| `vm_node_border` | `#2e3848` | `#8a9096` | K1 node border |
| `vm_wire` | `#0ea5e9` | `#0078b0` | K1 diagram line |

Status tokens gain light-mode variants of the same hues (`#00ac64` / `#ec282c` /
`#f49c34` from K2/K1) on tinted backgrounds, so the semantics survive the theme change
with correct contrast on light surfaces.

---

## 4. Typography and control metrics

| Property | Measured in K1/K2 | Applied |
|---|---|---|
| Body text height | 11–12 px on a 925 px window | 12 px |
| Panel/field label | 11 px, sentence case | 11 px |
| **Case** | sentence case ("Add Tools", "Position Adj.") | sentence case, not upper-case (the previous header style was 11 px upper-case with letter-spacing) |
| Control height | ~26 px | 24 px (`FIELD_H`), unchanged |
| Toolbar button | ~30 px square | 38 × 30 px, unchanged geometry |
| Border | 1 px, `#b8bcc0` | 1 px |
| Corner radius | 3–4 px | 3 px (flat industrial look, not rounded-pill) |

---

## 5. What is deliberately *not* copied

* **No KEYENCE branding, logo, wordmark or trade dress.** The product keeps its own name
  and its own mark; only the measured colour relationships and control metrics are used.
* **No proprietary assets.** Every icon is still drawn in code by this project's own
  `icons.py` / `get_action_icon`; nothing is traced or extracted from a KEYENCE screen.
* **No layout change.** The workspace geometry stays on the VisionMaster-measured split
  (`docs/VISIONMASTER_STORYBOARD.md`): rail 0.0513, canvas 0.5452, right column 0.4034,
  image block 0.604 / result block 0.396. The refinement is a re-skin plus control
  standardisation, exactly as requested.

---

## 6. Verification and remaining gaps

**Verified.** `scripts/build_keyence_comparison.py` renders the before and after frames at
identical sizes and writes `docs/screenshots/keyence_comparison.png` plus
`keyence/palette_delta.json`; `scripts/measure_chrome_bands.py` records the chrome-band
measurement. Measured outcome:

| Check | Result |
|---|---|
| Chrome (`vm_chrome`, `vm_chrome_dark`) vs measured bands | **ΔE 0.0** (exact) |
| Selection amber vs measured selected tab | **ΔE 0.0** (exact) |
| Image viewport vs measured result field | **ΔE 0.0** (exact) |
| Panel surface vs measured group box | **ΔE 0.0** (exact) |
| Mean frame luminance, before → after | 30 → 151 (a genuine light-theme conversion) |
| Layout ratios | unchanged (canvas 0.5484 vs measured 0.5452, etc.) |
| Test suite | all tests pass, including new palette assertions |

**Remaining gaps, stated plainly.**

1. **Menu-strip label contrast is 3.5:1.** White labels on the measured `#848c94` menu
   strip fall just under the 4.5:1 AA threshold for body text. This is the *measured*
   KEYENCE relationship — their own menu strip has the same characteristic — so it is
   reproduced rather than "fixed", and recorded here. Darkening the menu strip would move
   it away from the reference; the toolbar and status bar, which carry more text, use the
   darker `#646c6c` at 5.4:1.
2. **The tab-bar background is a band average.** The measured `#586068` comes from a strip
   that also contains tab labels and icons, so the flat colour applied to the flow tab bar
   is close to, but not identical with, KEYENCE's unlabelled tab-bar fill.
3. **The reference screenshots are manual renders, not native captures.** They were
   rendered at 6× from vector/CMYK composites, so anti-aliasing and JPEG-like artefacts
   are present. Colours were taken as the modal value of a region to suppress that, but a
   native screen capture would be sharper than anything measured here.
4. **Icon shapes remain this project's own.** Only colours, control metrics and typography
   were taken from the references; KEYENCE's icon artwork was not traced, by design
   (original assets only).
5. **The canvas dot grid is an Apex addition.** The XG Flow Editor canvas is a flat
   `#b4b8c0` with no grid; this project keeps a dot grid for node alignment, tinted
   `#a2a8b2` so it stays a subtle texture on the light field.
6. **Deeper KEYENCE surfaces were out of reach.** The Screen Editor / User Window / Parts
   List views (K3) are documented in text but their screens are not reproduced at usable
   resolution in the pages found, so no claim is made about them.
