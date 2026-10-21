# Design System

The interface standardisation reference for Apex Industrial Vision Studio. It records
the tokens, the component conventions, and how each is validated.

**The colour palette is unchanged.** It remains the approved KEYENCE-derived scheme
measured from the official manuals; see `docs/KEYENCE_DESIGN_SPEC.md`. This document
standardises *dimensions, typography, spacing and states*, which is what the component
audit found drifting.

---

## 1. What the audit found

Measured on the running application (`scripts/audit_component_inventory.py`) and in the
source (`scripts/audit_hardcoded_metrics.py`):

| Finding | Before |
|---|---|
| Hardcoded visual constants in `apex_vision/ui` | **383** |
| Distinct `font-size` values | 6 (11/12/13/14/16/17 px) |
| Distinct `padding` shorthands | **29** |
| Distinct `margin` shorthands | 10 |
| Distinct `border-radius` values | 5 (2/3/4/5/6/9 px) |
| Distinct `setContentsMargins` tuples | **24** |
| Distinct `setSpacing` values | 12 (0…24) |
| `QFont(family, size)` built inline | 33, across 6 sizes |
| Button heights in one window | 6 (25/26/28/29/31/33 px) |
| Combo-box heights | 4 (22/25/28/33 px) |
| Tab-bar heights | 3 (23/25/29 px) |

Two structural causes, both invisible in a screenshot:

1. **Two competing typographic channels.** `QApplication.setFont` set a 10 pt font while
   the stylesheet declared `font-size` in pixels. A styled widget resolved through the
   stylesheet, an unstyled one through the application font, so text in different panels
   rendered at different sizes and neither was authoritative.
2. **Every widget owned its own numbers.** Dimensions were literals at each call site,
   so two buttons of the same kind could differ by a pixel or two with no way to tell an
   intentional tier from drift.

---

## 2. Tokens

Defined once in `apex_vision/ui/styles.py` and exposed to the stylesheet under flat names
(`{T['fs_body']}`, `{T['sp_base']}`) so a rule and the ramp cannot disagree.

### 2.1 Type ramp

| Token | px | Role |
|---|---|---|
| `fs_micro` | 10 | build stamps, axis ticks, calibration readouts |
| `fs_caption` | 11 | secondary labels, units, table sub-captions |
| `fs_body` | 12 | **default** — buttons, fields, tables, panels |
| `fs_label` | 13 | form labels, dialog body, module card text |
| `fs_subtitle` | 14 | section headings |
| `fs_title` | 16 | dialog and page titles |

Weights: `fw_regular` 400, `fw_medium` 500, `fw_demibold` 600, `fw_bold` 700.
`font_stack` is one list, used by both channels, so a stylesheet rule and a `QFont`
fall back identically.

Both channels are driven from `fs_body`: `initialize_app_fonts` converts it to points
for `QApplication.setFont`, and `apply_type()` is the supported way to set a widget's
font in code instead of building `QFont(family, size)` inline.

### 2.2 Control heights

Each names a **purpose**, so a widget selects a tier rather than inventing a height.
Distinct heights are expected here — a toolbar button and a status strip are not the
same control.

| Token | px | Role |
|---|---|---|
| `h_input` | 24 | text, numeric and combo fields |
| `h_button` | 26 | standard push buttons |
| `h_compact` | 24 | icon-only buttons in dense rows |
| `h_toolbar` | 30 | the measured command-strip button |
| `h_tab` | 26 | tab-bar and panel-header rows |
| `h_row` | 24 | table and tree row pitch |
| `h_header` | 30 | table header |
| `h_indicator` | 13 | check-box / radio glyph |
| `h_icon_sm/md/lg` | 16/20/24 | icon sizes |

### 2.3 Spacing

`sp_none` 0 · `sp_hair` 2 · `sp_tight` 4 · `sp_snug` 6 · `sp_base` 8 · `sp_loose` 12 ·
`sp_section` 16

Values are **not** forced to one number. `padding: 4px 8px` and `padding: 2px 12px` are
both correct: they are different points on the scale, and collapsing them would remove
intentional differences in density. What matters is that no value is off-scale, which
`scripts/validate_design_tokens.py` enforces.

### 2.4 Radius and border

Radius: `r_control` 3 · `r_panel` 4 · `r_pill` 9.
Border width: `bw_hair` 1 · `bw_focus` 2 · `bw_selected` 2.

### 2.5 Colour

Unchanged, and not restated here — `docs/KEYENCE_DESIGN_SPEC.md` is the authority, and
`scripts/audit_contrast.py` enforces the contrast relationships (39 pairs, 0 below
target).

---

## 3. Component conventions

| Component | Convention |
|---|---|
| Text button | `h_button`, `r_control`, body text, `sp_tight sp_base` padding |
| Icon-only button | `h_compact`, icon `h_icon_md`, square |
| Toolbar button | `h_toolbar`, icon `h_icon_lg`, transparent over the chrome |
| Input / spin / combo | `h_input`, light well (`bg_surface_alt`), `bw_hair` border, focus ring `bw_focus` in `border_focus` |
| Combo popup | white list, accent selection with white ink |
| Table | header `h_header`, rows `h_row`, alternating row surface |
| Tab bar | `h_tab`; selected tab takes the amber fill with dark ink |
| Panel header | `h_tab`, `vm_panel_header` surface, demibold label |
| Section header (group box) | `fs_body` demibold in `text_secondary` |
| Workflow node | `vm_node` card, `vm_node_border` edge; selected adds the `accent_border` edge and amber wash; execution state drives the badge colour |
| Status bar | `h_status_strip`, `vm_chrome_dark`, light ink, **transparent** label backgrounds |

### States

Every interactive component defines: default, hover, pressed, focused, selected,
disabled. Semantic success/warning/error use the `status_*` tokens only. Two rules are
load-bearing and easy to break:

* A **selection indicator is never a lone amber stroke** — amber on the light canvas
  measures 1.0:1, so a selection always pairs the amber fill with the deepened
  `accent_border` edge.
* A **status-bar label must declare `background: transparent`** — a `QLabel` with a
  colour rule otherwise paints its own background and fills the whole strip with the
  window colour.

---

## 4. Validation

| Script | What it enforces | Current |
|---|---|---|
| `scripts/validate_design_tokens.py --strict` | no off-scale length value, in the stylesheets or in any inline widget style | **0 off-scale / 210 declarations** |
| `scripts/audit_declared_metrics.py` | every declared `font-size` is on the type ramp | **5 distinct, all on-ramp** |
| `scripts/audit_text_clipping.py` | no label is narrower than the text it draws | **0 clipped** |
| `scripts/audit_contrast.py --strict` | palette contrast pairs and no stray colour literal | **39 pairs, 0 below target** |
| `scripts/audit_qss_contrast.py` | every colour/background rule is readable | **34 rules, all pass** |
| `scripts/audit_component_inventory.py` | per-class size/font/style spread, for review | baseline recorded |
| `tests/test_design_system.py` | the tokens exist, are on-scale, and are applied | see below |
| Full suite | nothing regressed | **all pass** |

### Reproducing the token layer

A `git checkout` of the stylesheet modules reverts the palette, the tokens and the
contrast fixes together, so the whole layer is reproducible in order:

```bash
python scripts/restore_approved_palette.py --apply   # approved colours
python scripts/install_design_tokens.py --apply      # type/size/space/radius tokens
python scripts/retint_ui.py --apply                  # literals -> tokens
python scripts/rewrap_theme_tokens.py --apply        # f-string interpolation form
python scripts/apply_contrast_qss_fixes.py --apply   # contrast corrections
python scripts/apply_final_contrast_fixes.py --apply
python scripts/fix_status_bar_rules.py --apply       # status strip transparency
python scripts/fix_global_base_rules.py --apply      # QWidget is not chrome
python scripts/apply_design_tokens.py --apply        # literals -> design tokens
python scripts/fix_token_units.py --apply            # ensure every length has a unit
python scripts/fix_start_page_metrics.py --apply     # inline styles onto the scale
python scripts/validate_design_tokens.py --strict    # must report 0 off-scale
```

---

## 5. Before and after

Measured with the same three scripts on the same running application.

| Metric | Before | After |
|---|---|---|
| Off-scale length values (stylesheets) | not enforced | **0 / 210 declarations** |
| Off-scale inline length values | 8 | **0** |
| Declared `font-size` values | 6, none tokenised | **5, every one on the type ramp** |
| Literal `font-size` declarations in the stylesheet sources | 55 | **0** |
| Literal `border-radius` declarations in the sources | 35 | **0** |
| Distinct `padding` shorthands | 29 | **18, every component on the scale** |
| Distinct `margin` shorthands | 10 | **7, every component on the scale** |
| Padding declarations missing a CSS unit (silently dropped by Qt) | 84 | **0** |
| Clipped labels | 1 (`Algorithm: 148.64ms`) | **0** |
| Application-font / stylesheet size conflict | 10 pt vs 12–13 px | **both from `fs_body`** |
| `QFont::setPointSize: Point size <= 0` warnings | 1 per launch | **0** |

Screens captured before and after each change are in
`docs/screenshots/design/` (`H0`–`H6`), produced by
`scripts/capture_design_screens.py` so the set is reproducible.

### One finding that only the validation caught

The first token pass emitted `padding: {T['sp_hair']} {T['sp_loose']};`, which renders as
`padding: 2 12;` — **invalid CSS that Qt silently discards**, leaving the widget at its
default. Nothing about that is visible in a screenshot, and the contrast and clipping
audits both passed. It was found by `scripts/check_token_substitution.py` checking every
mapping entry for a unit, and is now guarded by a test.

---

## 6. Remaining inconsistencies

1. **33 inline `QFont(family, size)` constructions** remain in drawing code
   (`flow_editor`, `image_canvas`, `icons`, `flow_overview`, `inspector`). They are
   *canvas* text — node port labels, overlay captions, ruler ticks — which is scaled
   relative to the graphics transform rather than the UI, so the type ramp does not
   apply directly. `apply_type()` is available for the fixed-size ones.
2. **Widget heights still vary** (buttons 25–33 px, tabs 23–29 px in the raw inventory).
   Part of that is intentional tiering and part is that Qt resolves a control's height
   from its font, padding and border together, so a stylesheet tier is a floor rather
   than a guarantee. The heights are now all *reachable from tokens*; making them exact
   would require `setFixedHeight` on every control, which would break the layouts that
   rely on size hints.
3. **Two sizes remain slightly off-tier by design**: the `QDockWidget::title` rule uses
   `fs_caption` in one place and `fs_body` in another because the dock titles and the
   panel headers are visually different rows.
4. **`resultCaption` and similar rich-text labels** are measured only after their markup
   is stripped; the clipping audit strips it, but a future label using a table or an
   image tag would need the same treatment extended.
