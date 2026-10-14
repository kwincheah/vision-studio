# UI Polish & Contrast Audit

**Scope.** Every screen, dialog, toolbar, menu, button, input, label, table, tree, tab,
dock, workflow node, canvas and status indicator, audited against WCAG 2.1
(4.5:1 normal text, 3:1 large text and non-text UI), with the approved
KEYENCE-derived palette left intact.

**Approved palette preserved.** No brand colour changed. The signature amber
`#e4b030`, the accent blue `#0078b0`, the chrome greys `#848c94` / `#646c6c`, the
canvas `#b4b8c0`, the card `#fcfcfc` and the viewport `#201c20` are all unchanged.
Only *text ink*, *border*, *surface-role* and *state* values moved, and each move is
recorded below with the ratio it fixes.

**Method.** Re-runnable tooling, all currently clean:

| Script | Checks |
|---|---|
| `scripts/audit_contrast.py` | 39 palette pairs (text + non-text), and any colour literal in widget code that bypasses the palette |
| `scripts/audit_qss_contrast.py` | every generated stylesheet rule that carries both a `color` and a `background-color` |
| `scripts/audit_screens.py` | captures 26 screens (3 window sizes, 6 menus, 4 flyouts, both right-column pages, 3 result tabs, 4 config tabs) and pixel-probes 7 regions per size |
| `scripts/find_literal_tokens.py` | token names left inert inside plain strings (§1.13) |
| `scripts/find_unbackgrounded_labels.py` | styled labels that paint the surface behind them (§1.8) |
| `scripts/find_styled_background_gaps.py` | `QWidget` subclasses ignoring their stylesheet background (§1.9) |

Plus `tests/test_contrast_and_readability.py` (31 assertions) to stop regressions.

---

## 1. Issues found and fixed

### 1.1 Dark ink on dark chrome — the most serious class of bug

The palette conversion turned the `text_*` tokens dark, but rules that *paint the
steel chrome* kept using them. The result was near-invisible text on the most-read
surfaces.

| Where | Was | Ratio | Now | Ratio |
|---|---|---|---|---|
| Status bar labels (`statusSegment`, `statusLeading`, `statusMessage`, `statusVersion`) | `#4f565c` / `#414850` on `#848c94` | **1.9:1** | `text_on_chrome` on `vm_chrome_dark` | **5.1:1** |
| Flow tab labels (unselected) | `#414850` on `#848c94` | **2.7:1** | `text_on_chrome` on `vm_chrome_dark` | **5.6:1** |
| Flow tab (selected) | `#1a2024` on `#5f666d` | **2.8:1** | `#1a2024` on amber `#e4b030` | **9.7:1** |
| Flow-tab scroller buttons | `#414850` on `#848c94` | **2.7:1** | `text_primary` on `bg_control` | **9.4:1** |
| Menu-bar labels | light ink on the mid chrome | **3.0:1** | `text_on_menu` `#1a2120` | **5.1:1** |
| QMenu body | `#5f666d` on `#848c94` | **1.7:1** | `text_primary` on `bg_surface_alt` | **15.7:1** |

The menu fix follows the **reference's own measurement**: the KEYENCE CV-X menu strip
carries *dark* ink on its light chrome (measured 4.99:1), while its darker toolbar
carries white labels (5.22:1). Both relationships are now reproduced.

### 1.2 The catch-all `QWidget` rule painted the chrome colour

`QMainWindow, QWidget { background-color: <chrome> }` filled **every unstyled
container** with mid steel grey. That is what made tooltips dark (`ToolTipBase`
`#3c3c3c` with `#d4d4d4` ink), dialogs mid-grey, and toolbar spacers a light band
across the chrome strip.

| Where | Was | Now |
|---|---|---|
| `QWidget` base | chrome grey `#848c94` | window field `#e4e7ea` |
| `QDialog` | `bg_header` `#848c94` → body text 1.7:1 | `bg_surface` `#ecf0f0` → **14.3:1** |
| `QToolTip` | `bg_app` + inherited dark base | `bg_surface_alt` with `text_primary` → **15.7:1** |
| `QProgressBar` | `bg_header` | `bg_surface_alt` |
| Toolbar spacer widgets | filled with the window colour, cutting a **890 px light band** across the toolbar | `QToolBar > QWidget { background: transparent }` |

### 1.3 Input fields were chrome-grey wells

`QSpinBox, QDoubleSpinBox, QComboBox` used `bg_header` (`#848c94`), leaving the typed
value at **2.3:1** against its own fill. They now use `bg_surface_alt`, brightening to
`#ffffff` on focus — a real sunken field with a border lighter than its base.

The combo popup had the same problem and now uses a white list with white-on-accent
selection.

### 1.4 Borders were below the 3:1 non-text target

The reference draws its borders *hard* — a CV-X group box border measures 13.1:1 on its
panel and an XG unit-node edge 5.5:1 on the canvas. This app's were decorative
hairlines.

| Token | Was | Ratio | Now | Ratio |
|---|---|---|---|---|
| `border_subtle` | `#b8bcc0` | **1.7:1** | `#5f666d` | **4.3:1** |
| `border_control` | `#98a0a6` | **1.5:1** | `#5a6069` | **3.5:1** |
| `vm_node_border` | `#8a9096` | **1.6:1** | `#5c636a` | **3.1:1** |
| `accent_border` | `#d89a28` | **2.4:1** | `#6f4a04` | **6.8:1** |
| `vm_wire` | `#0078b0` | **2.5:1** | `#005f8c` | **3.5:1** |
| `status_ok_border` | `#00ac64` | **2.6:1** | `#00754a` | **5.0:1** |
| `status_warn_border` | `#f49c34` | **1.9:1** | `#8a5a0e` | **5.2:1** |

### 1.5 Muted text missed AA

`text_muted` `#6e767c` reached only 3.7:1 on the window field (4.0:1 on panels) — it is
used for captions, timestamps, hints and placeholders. Deepened to `#5a6168` (**6.0:1**),
and `text_secondary` `#4a5258` → `#414850` (**7.6:1**).

### 1.6 Meaningful icons were low-contrast

* **Toolbar glyphs**: the buttons are transparent over the dark strip, so the glyph
  carried the contrast — dark icons on `#848c94` gave **1.9:1**. The icons are now
  rendered in `text_on_chrome` (**4.7:1**), matching the reference's white-on-chrome
  icons. `get_action_icon()` gained a `color` parameter so callers pick ink for their
  surface.
* **Rail glyphs**: the selected rail item kept a *light* glyph on the flyout's *light*
  fill, making the selection **invisible**. `ToolCategoryRail.select_category()` now
  re-inks the selected glyph in dark body ink and the rest in chrome ink, and the
  selected item gained a full amber border.

### 1.7 Selection was not distinguishable at 3:1

| State | Was | Now |
|---|---|---|
| Node selection edge vs card | 1.9:1 (amber stroke) | 6.8:1 (`accent_border`) |
| Node selection edge vs canvas | 1.0:1 | 3.6:1 |
| Flow tab selected vs unselected | 1.2:1 | 9.7:1 |

The amber is still the selection *fill* — the approved brand colour — but it is never
the *sole* indicator any more; selections pair it with the deepened edge.

### 1.8 A styled `QLabel` filled the whole status bar with the window colour

The most obscure bug found, and the one that took the longest to isolate. Once Qt
treats a `QLabel` as a styled sub-control, the label **paints its own background**.
Under the global light `QWidget` rule that meant:

    QLabel#statusLeading { color: …; padding: …; }   /* no background */

filled the **entire status strip** with `#e4e7ea`, hiding the dark chrome and leaving
its light labels unreadable — and an explicit `background-color` on `QStatusBar`
could not override it. Isolated repro: a bare window with the same rule set renders
the strip light; remove the label rule and it renders dark.

Fixed by declaring `background: transparent;` on every `status*` label. Detector:
`scripts/find_unbackgrounded_labels.py`.

### 1.9 `QWidget` subclasses ignored their stylesheet background

Qt only paints `#objectName { background-color: … }` on a plain `QWidget` subclass
when the widget sets `WA_StyledBackground`. The category rail did not, so it fell
back to the global light background — leaving its (correctly) light glyphs invisible
on a light strip. The rail, the tool flyout and the image display area now set the
attribute. Detector: `scripts/find_styled_background_gaps.py`.

### 1.10 Two more chrome-grey surfaces

| Where | Was | Now |
|---|---|---|
| `QLineEdit, QPlainTextEdit, QTextEdit` | `bg_header` `#848c94` → typed value **2.3:1** | `bg_surface_alt` → **15.7:1** |
| `QComboBox#runScopeCombo QAbstractItemView` | `bg_header` | `#ffffff` |

### 1.11 Truncation at the reference window size

At the measured 925×765 reference size the right-column run row is tight enough that
the execution-scope combo clipped its label to **"Ru"**. Both controls now take a
minimum width derived from their content (`sizeHint` for the Run button, the widest
entry plus the arrow for the combo), so the label survives the squeeze without
changing the row height or the measured column split.

### 1.12 The Start Page was a separate, dark-themed application

`start_page.py` predates the palette work and hardcodes its own palette — a different
accent blue (`#2563EB`), a different ink (`#1E293B`) and a near-black page header
(`#201F24`). It rendered as a dark screen in front of a light workspace. Retinted onto
the approved tokens (`scripts/retint_start_page.py`), keeping `#FFFFFF` only where it
is ink on the blue action buttons.

### 1.13 Tooling defects found and repaired along the way

Retinting a light palette exposes tooling that was written for a dark one:

| Defect | Effect | Repair |
|---|---|---|
| `retint_ui.py` inserted the token **name** into the theme's f-string template | Qt discarded every declaration | f-string mode writes `{THEME['x']}` (`scripts/rewrap_theme_tokens.py` re-wraps strays) |
| `link_literals_to_tokens.py` left `THEME['x']` inside **plain** strings | inert text; the Start Page's primary buttons lost their label colour | `scripts/resolve_plain_string_tokens.py` substitutes the resolved value |
| …and produced `f"… {#ecf0f0} …"` | **syntax error** (the `#` comments out the expression) | `scripts/fix_malformed_placeholders.py` |
| `apply_contrast_qss_fixes.py` inserted the `QToolBar > QWidget` rule inside `QToolButton` | spacer rule became dead text | corrected; the 890 px light band across the toolbar is gone |

---

## 2. Remaining contrast problems

Two pairs are still below target and are **deliberate**, because the constraint was to
preserve the approved palette:

| Pair | Ratio | Why it stands |
|---|---|---|
| **Signature amber `#e4b030` as a stroke on the canvas** | 1.0:1 | `#e4b030` is the approved brand colour. It is never used alone: node selection adds the 3.6:1 `accent_border` edge, and the category badge sits on a white-bordered capsule. |
| **Signature amber as a stroke on a card** | 1.9:1 | Same; the selected card carries the 6.8:1 edge as well. |

Recorded as approved exceptions in `scripts/audit_contrast.py`
(`APPROVED_EXCEPTIONS`) so they are visible rather than silently passing.

One further honest limitation:

* **The decorative dot grid** (`vm_canvas_dot` on `vm_canvas`) measures 1.5:1. It is a
  layout aid, not an indicator — nodes align by drag — so it is exempt from the
  non-text rule by WCAG's own wording ("purely decorative"). Deepened from `#a2a8b2`
  to `#949aa4` for visibility regardless.

---

## 3. Screens inspected

Captured to `docs/screenshots/audit/` by `scripts/audit_screens.py` and
`scripts/capture_states.py`:

| Set | Contents |
|---|---|
| `80_main_*` | main window at **925×765, 1400×760, 1120×760** |
| `81_menu_*` | File, Settings, Tools, System, View, Help dropdowns |
| `82_flyout_*` | Acquisition, Location, Measurement, Image Generation tool flyouts |
| `83_result_page*`, `84_resulttab_*` | right column: Image page, Result page, and each result tab (Current Result / History / Help) |
| `85_moduleconfig_0-3` | module configuration window, all four tabs |
| `90`–`94` | interaction states: tooltip, disabled toolbar, System menu, flyout states, result tree |
| `95_start_page` | the Start Page / New Project screen |
| `70_polish_main` | full-window frame after the fixes |

Every capture is re-probed in the same run, so a regression in any of them is caught
rather than merely photographed.

Not captured, with the reason: the **tooltip popup** could not be grabbed as an
image — Qt only realises a `QTipLabel` inside a running event loop, and offscreen
`grab()` never produced one. Its surface is instead verified by
`test_tooltip_and_dialog_are_light_and_readable`, which asserts the `QToolTip` rule is
a light surface with ≥4.5:1 ink (currently `#1a2024` on `#f8fafb` = 15.7:1).

---

## 4. Tests performed

| Check | Result |
|---|---|
| `python -m pytest tests/` | **all pass** (264 assertions incl. the 31 new) |
| `scripts/audit_contrast.py --strict` | **39 pairs, 0 below target**; no colour literal outside the palette in widget code |
| `scripts/audit_qss_contrast.py` | **33 rules, every one passes its target** |
| `scripts/audit_screens.py` | 21 pixel probes across 3 window sizes, **no readability issue**; probe ratios 4.69–15.25:1 |
| Resize | 925×765, 1120×760, 1400×760 all re-rendered and re-probed after the fixes |
| Interaction | menus opened, flyouts toggled for 4 categories, both right-column pages and all 3 result tabs switched, all 4 config tabs opened, a control disabled/enabled, toolbar and rail selection states exercised |

New regression tests (`tests/test_contrast_and_readability.py`):
`test_text_pairs_meet_wcag_aa` (20 pairs), `test_ui_pairs_meet_wcag_non_text`
(11 pairs), `test_no_rule_puts_dark_ink_on_dark_chrome` (sweeps the whole stylesheet
against all dark surfaces — this is what catches the §1.1 class),
`test_input_widgets_are_light_wells`, `test_global_widget_rule_is_not_chrome`,
`test_tooltip_and_dialog_are_light_and_readable`,
`test_every_literal_pair_in_the_stylesheet_is_readable`.

Re-runnable audits, all currently clean:

| Command | Checks |
|---|---|
| `scripts/audit_contrast.py --strict` | 39 palette pairs + palette-literal sweep |
| `scripts/audit_qss_contrast.py` | every colour/background rule in the generated sheet |
| `scripts/audit_screens.py` | captures 26 screens and probes 7 regions each |
| `scripts/find_literal_tokens.py` | token names left inert inside plain strings |
| `scripts/find_unbackgrounded_labels.py` | the §1.8 status-bar class |
| `scripts/find_styled_background_gaps.py` | the §1.9 `WA_StyledBackground` class |
| `scripts/fix_malformed_placeholders.py` | `{#rrggbb}` syntax-error placeholders |

---

## 5. Files changed

| File | Change |
|---|---|
| `vm_clone/ui/styles.py` | Ink deepened (`text_secondary`, `text_muted`), `text_on_menu` added, borders raised to 3:1, selection edge deepened, status borders deepened, `status_ok_text` corrected, `QLineEdit`/spin/combo/combo-popup/text-edit moved to light wells |
| `vm_clone/ui/vm_theme.py` | Global base split so `QWidget` is no longer chrome; menu bar takes the reference's dark ink; status bar, flow tab bar, toolbar and image strip moved to the darker chrome with light ink; **status labels made transparent** (§1.8); selected flow tab uses the amber fill; `QMenu`, `QDialog`, `QToolTip`, `QProgressBar`, text-edit, spin/combo and combo-popup rules moved to light surfaces; toolbar spacer rule made real (§1.12); rail checked-state border completed |
| `vm_clone/ui/icons.py` | `get_action_icon()` accepts an ink colour |
| `vm_clone/ui/main_window.py` | Toolbar icons rendered in the chrome ink; version label ink moved to its QSS rule |
| `vm_clone/ui/toolbox.py` | `get_rail_icon()` accessor; rail glyphs re-inked on selection; rail painter default ink is the chrome tone; `WA_StyledBackground` on the rail and flyout |
| `vm_clone/ui/flow_editor.py`, `image_display.py` | `WA_StyledBackground` on the zoom tool and image display area |
| `vm_clone/ui/start_page.py` | Retinted from its private dark palette onto the approved tokens |
| `scripts/` (13 files) | Audit, capture and repair tooling; all re-runnable |
| `tests/test_contrast_and_readability.py` | **New** — 31 regression assertions |

No layout, geometry, workflow or behaviour changed: the VisionMaster-measured split
(rail 0.0513 / canvas 0.5452 / right column 0.4034, image 0.604 / result 0.396) is
untouched, and the full functional suite still passes.
