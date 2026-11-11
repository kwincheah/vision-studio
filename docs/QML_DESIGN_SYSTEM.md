# QML Interface Design System

The design reference for the Qt Quick interface in `qml/`. It records the token layer, the
component conventions, and — importantly — the defects found by *rendering and measuring*
the interface rather than reading it.

> **The approved palette is unchanged.** The signature amber `#e4b030`, the accent blue
> `#0078b0`, the chrome greys `#848c94` / `#646c6c`, the canvas `#b4b8c0`, the card
> `#fcfcfc` and the viewport `#201c20` are exactly as measured. What changed below is
> *ink roles*, *state fills* and *token discipline*.

---

## 1. Structure

```
qml/
  Main.qml                  application window; hosts MainScreen and StartScreen
  ApexTheme/
    Theme.qml               the only place colour, type, spacing and radii are defined
    SampleData.qml          demo content for the design canvas (not styling)
  ApexComponents/           reusable controls: AppButton, ChromeToolButton, TextBox,
                            SelectBox, NumberBox, CheckLabel, ToggleSwitch, NodeCard,
                            StatusBadge, Chip, DataTable, DropMenu, ModelPicker,
                            ParamEditor, DialogFrame, FormRow, SectionLabel, ...
  ApexDialogs/              the modal dialogs hosted by DialogHost
  screens/
    MainScreen.qml          the workspace (menus, toolbars, canvas, viewer, results)
    StartScreen.qml         the start page
    ToolFlyout.qml          the tool rail's flyout
    AiChatPanel.qml         the floating AI flow generator
    AiSettings.qml          AI provider configuration
    InspectionPanel.qml     evaluation and failure analysis
```

**Rule:** colour, font size, spacing and radius come from `Theme`. A literal in a
component is a second source of truth that no contrast audit can see.

---

## 2. Tokens

### 2.1 Colour roles

| Role | Token | Notes |
|---|---|---|
| Window field | `appBg` | behind everything |
| Panel | `panel`, `panelAlt`, `panelHeader` | alternating rows use `panelAlt` |
| Card | `card` | node cards and floating panels |
| Canvas | `canvas`, `canvasDot` | dotted flow grid |
| Viewport | `viewport`, `viewportText` | the image well is dark by design |
| Chrome — light | `chrome` | the **menu strip**, with **dark** ink |
| Chrome — dark | `chromeDark` | toolbars **and the status bar**, with light ink |
| Rail | `rail`, `railHover` | the left tool rail, light ink |
| Field | `fieldBg`, `fieldBorder`, `fieldBorderHover` | inputs |
| Button | `buttonBg`, `buttonHover`, `buttonPressed` | secondary buttons |
| Ink | `textPrimary`, `textSecondary`, `textMuted`, `textOnChrome` | |
| Accent | `accent`, `accentHover`, `accentDim`, `accentBorder` | selection and the signature amber |
| Primary action | `primary`, `primaryHover`, `primaryText` | |
| Status | `okText/okBg/okBorder`, `errorText/errorBg/errorBorder`, `warnText/warnBg` | |
| Filled action fills | `runGreen/runGreenHover`, `stopRed/stopRedHover` | white text on these |

**Two chrome tiers, two inks.** The menu strip is the lighter `chrome` and takes dark ink;
the toolbars and status bar are the darker `chromeDark` and take `textOnChrome`. Mixing
the two is the most common mistake in this codebase — see §4.1.

### 2.2 Type scale

| Token | px | Role |
|---|---|---|
| `fontCaption` | 11 | captions, footer lines, tab labels, table sub-headers |
| `fontBody` | 12 | **default** — buttons, fields, most labels |
| `fontLabel` | 13 | form labels, dialog body |
| `fontSubtitle` | 14 | section headings |
| `fontTitle` | 16 | dialog and page titles |

`fontMicro` was removed: it was a second name for 11 px, so either name could be used for
the same size and neither meant anything. One size, one name.

### 2.3 Spacing, radii and heights

`spHair` 2 · `spTight` 4 · `spSnug` 6 · `spBase` 8 · `spLoose` 12 · `spSection` 16

`radiusControl` 3 · `radiusPanel` 4

`heightControl` 24 · `heightButton` 26 · `heightMenuBar` 31 · `heightToolbar` 42 ·
`heightTabBar` 34 · `railWidth` 42 · `statusBarHeight` 24

---

## 3. Component conventions

| Component | Convention |
|---|---|
| `AppButton` | `kind`: `secondary` (default, dark ink) · `primary` (blue fill, white ink) · `run` (green fill) · `stop` (red fill) · `danger` (red outline, red ink). Filled kinds use white **DemiBold** ink. |
| `ChromeToolButton` | Square icon button for the dark strips. `tone: "light"` on chrome. `kind: "run"/"stop"` gives a dark filled variant so the white glyph clears AA. |
| `ChromePillButton` | Labelled pill for the chrome strips (e.g. **AI Gen**). |
| `StatusBadge` | `kind`: `ok` · `error` · `warn` · `run`. Solid fill, white caption text. |
| `NodeCard` | `card` fill; border is `accent` when selected, else the status token (`okBorder` / `errorBorder`). |
| `TabButton2` | The workspace tabs (Flow Diagram / Operation Interface / Multi-Flow). |
| `TextBox`, `SelectBox`, `NumberBox` | `fieldBg` well, `fieldBorder`, focus ring in `primary`. |
| `DataTable` | Header on `panelHeader`, alternating `panel` / `panelAlt` rows. |
| `DialogFrame` | Every modal; provides the title strip, body and button row. |
| `SectionLabel` | Small caps-ish section heading inside panels. |

### States

Every interactive component defines rest, hover, pressed, focused, disabled. **Hover must
not reduce contrast** — see §4.2.

---

## 4. Defects found and fixed

Each was found by rendering the interface, measuring the geometry or sampling the pixels,
and each now has a regression test in `tests/test_qml_design_system.py`.

### 4.1 Dark ink on the dark status bar — 3.06:1

The status bar was filled with `Theme.chrome` (the *light* menu-strip grey) and its five
text runs used `Theme.textPrimary` (dark ink). Measured **3.06:1**, below the 4.5:1 the rest
of the interface holds to, and visibly muddy.

Fixed by giving the status bar the same `chromeDark` fill as the toolbars and
`textOnChrome` ink — **4.79:1**. It now reads as the bottom of the same chrome family
rather than a detached band.

### 4.2 Hover states dropped below AA

Two filled buttons lightened past the threshold on hover:

| | rest | hover (before) | hover (after) |
|---|---|---|---|
| `run` | 5.02:1 | **3.30:1** (`#16a34a`) | **5.38:1** (`#1c7a3f`) |
| `primary` | 4.87:1 | **3.90:1** (`#0a89c4`) | **5.44:1** (`#00719f`) |

The hover fills are chosen for hue by eye, so they drift. Hover now lightens only as far
as the ratio allows: the affordance survives, the label stays legible.

### 4.3 The flow tab elided its own cycle time

The tab was a fixed **190 px**. Its label — state dot, flow name, verdict and timing —
needs **171 px of text** in a 190 px tab that also spends 10 px on a left inset and 16 px
on a close button. Qt therefore elided the last characters:

```
before:  ● PCB_AOI_Solution  FAIL  1…
after:   ● PCB_AOI_Solution  FAIL  162ms
```

Fixed by deriving the width from the label with a floor and a ceiling:

```qml
width: Math.max(190, Math.min(320, tabLabel.implicitWidth + 44))
```

`showActive()` also hardcoded a 192 px pitch (`i * 192`) to scroll the selected tab into
view; it now walks the real tabs and sums their widths.

### 4.4 The Multi-Flow overview was a placeholder

It drew **one** card, centred, with the flow name `"PCB_AOI_Solution"` hardcoded and the
timing taken from whichever flow was active. On any other project the overview named a flow
that did not exist and reported another flow's numbers.

It now renders `root.tabList` — the same list the tab bar uses — so the two cannot
disagree, in a self-sizing `Grid` (a `Flow` reports no implicit size, which is why the old
single card sat off-centre).

### 4.5 The start screen listed pytest temp paths

The "Recent projects" list showed 30 entries of which **28** were
`...\Temp\pytest-of-<user>\pytest-665\Mine2.apex`. Three modules construct a default
`ProjectManager()` — the widget window, the QML backend and the start page — and the test
fixture isolated only the first.

All three are now redirected to a per-test workspace, and the polluted history was pruned
to the two real projects.

### 4.6 The same PASS verdict was drawn in three greens

| Where | Colour | |
|---|---|---|
| `StatusBadge` ok fill | `#00754a` | token `okBorder` |
| `NodeCard` PASS border | `#2fa56a` | literal |
| `MainScreen` verdict border | `#2fa56a` | literal |
| `AppButton` run border | `#16a34a` | literal |

The node cards and the verdict badge therefore showed the same PASS in visibly different
greens. All of them now resolve through `okBorder` / `errorBorder`.

### 4.7 "+ Add Variable" was clipped by the dialog edge

In Global Variables the add row was fixed at 190 + 124 + 170 + 120 = **604 px plus three
8 px gaps = 628 px**, inside a **608 px** body. The button therefore ended 4 px past the
card's right edge and was cut off. The button keeps a fixed width; the three fields now
share what is left.

Found by measuring the card rather than the window: every dialog is
`anchors.fill: parent`, so a naive overflow check compares children against the *window*
and reports that everything fits.

### 4.8 "Create & Publish" was clipped in the Plugin Manager

`TabButton2.implicitWidth` was `label + 2·12 + 4`, which omits the **1 px border on each
side** — so the tab came out exactly as wide as its text plus padding, and a bold
(selected) label lost its last pixel. Short labels (`Installed Plugins`) survived; the
longest one did not. The border term is now included.

### 4.9 The focus ring was invisible on the dark chrome

Focus used `Theme.primary` everywhere. On `chromeDark` that is **1.11:1** — the ring was
present in the code and invisible in practice. A dedicated `focusOnChrome` token (white,
4.79:1 on chromeDark, 7.33:1 on the rail) is now used by `ChromeToolButton` and
`ChromePillButton`.

### 4.10 Keyboard users could not reach the inputs

`TextInput` does not join the Tab chain unless it opts in, and neither `TextBox` nor
`NumberBox` did. Measured with real key injection in Flow Settings:

```
before:  [dialog] -> CheckLabel -> CheckLabel -> Cancel -> OK -> (repeat)
after:   [dialog] -> "50 ms" -> "5000 ms" -> CheckLabel -> CheckLabel -> Cancel -> OK
```

Both numeric fields were unreachable. `TabButton2` was likewise not focusable at all, so
the three workspace tabs could not be switched by keyboard. Both now opt in, and the tab
draws a focus ring and responds to Enter/Space.

### 4.11 A user-visible grammar bug

The validation dialog read **"1 issue(s) need attention."** Both the placeholder plural and
the verb agreement were wrong; it now reads "1 issue needs attention." or "N issues need
attention."

---

## 5. Validation

| Tool | Checks | Current |
|---|---|---|
| `scripts/audit_qml_contrast.py --strict` | 23 token pairs, 9 filled-button pairs, and the ink each chrome strip actually declares (extracted by brace matching) | **all pass** |
| `scripts/audit_qml_focus.py` | 8 focus-ring pairs against 3:1, and that every interactive component is in the Tab chain with a ring | **all pass** |
| `scripts/audit_qml_overflow.py` | each dialog's card, for text clipped without elide/wrap and for controls past its right edge | **0 problems in 9 dialogs** |
| `scripts/audit_qml_tokens.py` | every colour literal outside `Theme.qml`, and whether it duplicates a token | 68 literals, **0 duplicate a token** |
| `scripts/audit_qml_layout.py` | the rect of every major region and its share of the window | see below |
| `scripts/capture_qml_review.py` | renders the real window with a real project: workspace, three tabs, both right-column pages, the AI panel, and all 13 dialogs | 22 screenshots |
| `tests/test_qml_design_system.py` | structural guards for §4.3–§4.6 | **passing** |
| `tests/test_qml_accessibility.py` | keyboard reach, focus-ring contrast, filled-button contrast, dialog overflow, grammar | **passing** |

### The measured layout at 1600×950

| Region | Size | Share |
|---|---|---|
| Flow canvas | 918 × 793 | 47.9% |
| Right column (viewer + results) | 640 wide | 40.0% |
| Tool rail | 42 wide | 2.6% |
| Flow tab bar | 1181 × 28 | — |

The canvas and the right column are roughly 55/40 — close to the VisionMaster-measured
split the widget UI uses, and the rail keeps the reference's 42 px.

---

## 6. Remaining inconsistencies

1. **68 colour literals remain outside `Theme.qml`.** None duplicates an existing token, so
   none is a *second* source of truth for an existing colour; they are fills (icon-button
   backgrounds), image-overlay colours (which must be pixel colours, not interface colours)
   and the data-type palette inside `Theme.portColor()`. A further pass could promote the
   remaining fills, but each one needs a semantic name first or it just moves the problem.
2. **`fontCaption` and `fontBody` are one pixel apart** (11 vs 12). That is deliberate — it
   is the reference's hierarchy — but the distinction is only perceptible in dense areas.
3. **The AI panel is a floating overlay** anchored top-right at `z: 45`, so it covers the
   image viewer and results while open. It is dismissible and the canvas stays usable, but
   anchoring it over the canvas would let the user read the flow it is about to change.
4. **The image viewport is a fixed 300 px tall** with `PreserveAspectFit`, so a 4:3 image
   letterboxes inside a 2.2:1 frame.
5. **Dialog Tab order follows the object tree**, not a designed order. It is correct and
   complete (verified by key injection), but the order in a form is whatever order the
   controls were declared in.
6. **Two inspection panels exist**: `qml/screens/InspectionPanel.qml` in the primary QML UI
   and `apex_vision/ui/inspection_panel.py` in the legacy `--widgets` UI. They share the
   same `apex_vision/evaluation` backend but are separate views. That is parallel, not
   duplicated, but both need maintaining until the widget UI is retired.
7. **`.apex_config/recent_projects.json` had been polluted** by tests (28 of 30 entries were
   pytest temp paths) because only one of the three modules constructing a default
   `ProjectManager` was isolated. Fixed in `tests/conftest.py` and pruned; the file is
   per-workspace state, so a stale copy can still ship if it is committed.

---

## 7. Reproducing the review

```bash
python scripts/capture_qml_review.py        # workspace, tabs, AI panel and all 13 dialogs
python scripts/audit_qml_contrast.py --strict
python scripts/audit_qml_focus.py
python scripts/audit_qml_overflow.py
python scripts/audit_qml_tokens.py
python scripts/audit_qml_layout.py
python -m pytest tests/test_qml_design_system.py tests/test_qml_accessibility.py -q
```

The capture script drives the real `Main.qml` through the real `AppBackend` with a shipped
project loaded, because an empty startup canvas hides most of the interface.
