# HikRobot VisionMaster — Reference-Based UI/UX Specification

**Purpose.** Define the target interface for this project from *verifiable vendor and third-party
evidence*, so every implementation decision can be traced to a document or figure rather than to
recollection or guesswork.

**Status of the evidence.** Two of the four external documents were reachable and are quoted below;
two more were reachable from the vendor CDN. Two further sources returned HTTP 404 / 406 and are
explicitly marked as **not obtained** so no unverified claim is attributed to them.

---

## 1. Evidence base

### 1.1 Obtained (and used)

| ID | Source | What it establishes |
|---|---|---|
| **E1** | `HikRobotVMHelp_compressed.pdf` (bundled in this repo, 657 pp.) — chapters *Software Introduction* (pp. 37–99) and *Vision Tools* (pp. 168+) | Home page, control toolbar inventory, tool box rail, flow canvas, Image\|Result column, result grid columns, multi-flow overview, per-tool references |
| **E2** | *海康机器人 Vision Master 算法开发平台 用户手册* 4.3.0 maintenance edition, 928 pp. — downloaded from the vendor CDN to `docs/references/external/visionmaster_v4.3.0_user_manual_cn.pdf` | **Annotated main-interface region map (Fig. 5-2, p. 38)** with a 13-region legend, image-display-area operations (§5.2.3, pp. 43–44), flow configuration window tabs (§8.1, pp. 99–103), module common configuration (§8.2, p. 103+), quick-toolbar icon table (§5.2.2, p. 43), global variables (§9, pp. 110–112), module reference chapter (p. 199+) |
| **E3** | *VisionMaster 3D 算法开发平台* 2.2.0 user manual, 1154 pp. — downloaded from the vendor CDN | Corroborates the module-box rail, flow-canvas card style and parameter-tab structure in a sibling product |
| **E4** | *VisionMaster 算法平台用户手册 V3.0.2* (Chinese, 2019) — downloaded from a third-party archive | Earlier UI region wording and per-tool ROI/parameter figures, used only to corroborate E1/E2 (older release) |

Derived evidence produced by this project:

| Path | Content |
|---|---|
| `docs/references/figs/` | UI figures extracted from **E1** (pp. 37–100) |
| `docs/references/external/ui_pages/` | Full-page renders of the 20 most UI-relevant pages of **E2** |
| `docs/references/external/ui_crops/` | High-resolution crops of the annotated region map, toolbar tables, image display controls and configuration dialogs |
| `docs/references/external/ui_chapters_cn.txt` | Plain text of the 60 most UI-relevant pages of **E2** |
| `docs/references/external/index.json` | Machine-readable index of every extracted figure |

### 1.2 Not obtained (stated plainly)

| Source | Result |
|---|---|
| `pinfo.hikrobotics.com/…/20231101163730_26101_doc/pdf.pdf` (SDK development manual) | **HTTP 404** — the URL has been retired |
| `hnxmsy.com.cn/…/16644533891856488.pdf` (third-party training deck) | **HTTP 406** — the host refuses non-browser `Accept` headers |
| Video walkthroughs | No reliable, machine-readable video source was reachable in this environment, so **no behavioural claim below rests on video**. Where a video would have settled a question, that is noted as an open question instead. |

---

## 2. Confirmed main-interface structure

**Source: E2 Fig. 5-2 (p. 38) annotated region map + E2 Table 5-1 (p. 38) legend.**

The vendor's own numbered legend defines exactly 13 regions. Reading the annotated figure together
with the legend gives the following layout (top to bottom, left to right):

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ ① Menu bar:  File | Settings | Tools | System | Help    ③ current solution name       │
│                                                         ④ role switch  ⑤ window ctrls │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ ② Quick toolbar (single icon strip)                                   [Run Mode]      │
├──────┬───────────────────────────────────────────────┬───────────────────────────────┤
│      │ ⑦ Flow bar:  ☰  ✎  [Flow1]  ▶  ↻  +    ▾      │  ⑥ Image display area        │
│  ⑨   ├───────────────────────────────────────────────┤  ┌─────────────────────────┐  │
│ Mod  │                                               │  │ Image | Module Results  │  │
│ ule  │   ⑧ Flow editing area                         │  ├─────────────────────────┤  │
│ box  │                                               │  │ <name> [□□][+][-][1:1][⤢]│  │
│ rail │      (grey dotted canvas, white module        │  │  ◀   image  ▶            │  │
│      │       cards joined by orange arrows,          │  │ <ts>  WxH | X Y | R G B  │  │
│      │       numbered N<name> with a coloured        │  ├─────────────────────────┤  │
│      │       category badge on the left edge)        │  │ Image Source (1/1) [auto]│  │
│      │                                               │  │ [thumbnail strip]        │  │
│      │                                               │  ├─────────────────────────┤  │
│      │                                    ⑪ zoom ───►│  │⑫ Current|History|Help ▾ │  │
│      │                                               │  │  result table            │  │
├──────┴───────────────────────────────────────────────┴──┴───────────────────────────┤
│ ⑩ Flow time:  Component Config Completed | Flow 25.49ms | Tools 4.55ms | Algo 2.99ms │
└──────────────────────────────────────────────────────────────────────────────────────┘
                                                             ⑬ log bar / status
```

| # | Vendor name | Vendor description (E2 Table 5-1) |
|---|---|---|
| 1 | 菜单栏 Menu bar | File, Settings, Tools, System, Help |
| 2 | 快捷工具条 Quick toolbar | Shortcut entry points: save solution, camera management, controller management, global variables… |
| 3 | 当前加载的方案 Current solution | Shows the name of the loaded solution |
| 4 | 角色切换 Role switch | Switch the logged-in role (admin / technician / operator) |
| 5 | 其他 Other | Window controls |
| 6 | 图像显示区域 Image display area | Two kinds of information: the image output by a single module or by the flow, **and that module's output results** |
| 7 | 流程栏 Flow bar | Flow selector / add / execute controls above the canvas |
| 8 | 流程编辑区 Flow editing area | Canvas where modules are placed and wired |
| 9 | 模块箱 Module box | The module categories, on the **left edge of the flow editing area** |
| 10 | 流程耗时 Flow time | Component configuration state, flow time, tools time, algorithm time |
| 11 | 流程编辑区缩放工具 Flow-area zoom tool | The small square control at the lower-left of the canvas |
| 12 | 结果显示区 Result display area | Current result / history / help tabs over a **column-per-parameter result table** |
| 13 | 日志栏 Log bar | Message log strip |

### 2.1 The single most important structural finding

**The right column is a two-row vertical stack, and each row is its own tab widget with its own tab
bar** (regions 6 and 12). Reading the zoomed crop
`docs/references/external/ui_crops/right_column_zoom.png` directly:

```
┌─ 图像 | 模块结果 ───────────────────────────────────┐  tab bar row 1 (always visible)
│ 图像源1.输出图像      [▣][▣▣] [+] [−] [1:1] [⤢]      │  source name + view toolbar
│  ◀              <image, checkered surround>     ▶   │  paged viewport
│ 0153880-Image_202   1280*1024 | X | Y | R G B      │  status line
├────────────────────────────────────────────────────┤
│ 图像源 (1/1)        自动切换 [==]   运行全部 ▾       │  image strip
└────────────────────────────────────────────────────┘
┌─ 当前结果 | 历史结果 | 帮助 ────────────────────────┐  tab bar row 2 (always visible)
│ 序号 面积 周长 质心X 质心Y 角度 长轴 短轴 圆形度      │  one column per output parameter
└────────────────────────────────────────────────────┘
```

Both tab bars are visible simultaneously. The **upper** bar switches the display block between the
image and the module's result tree; the **lower** bar switches the result table between the current
result, the run history and help. The result block is therefore *not* a separate bottom-left panel,
and *not* a tab inside the image page — which is what this project implemented first and has now
been corrected.

The canvas is also not full-width: the module box is a narrow rail on the canvas's left edge, and the
right column takes roughly 30 % of the window width at 1600 px.

---

## 3. Confirmed per-region detail

### 3.1 Quick toolbar (E2 §5.2.2, p. 43, icon table)

Documented entries, in table order:

| Vendor icon name | Meaning |
|---|---|
| 锁定 Lock | Freeze the flow editing area — no adding, deleting or moving modules or wires |
| 相机管理 Camera management | Camera management screen |
| 控制器管理 Controller management | Controller management screen |
| 全局变量 Global variables | Global variable screen |
| 通信管理 Communication management | Device/protocol screen |
| 全局触发 Global trigger | Event / string trigger screen |
| 全局脚本 Global script | Global script screen |
| 单次执行 Execute once | Run the current solution once |
| 连续执行 Execute continuously | Run the current solution continuously |
| 编辑运行界面 Edit runtime UI | Open the interface-design window |
| 撤销 / 重做 Undo / Redo | Undo/redo; **cached steps configurable, hard limit 15** (E2 §7, p. 72) |
| 保存 / 打开 Save / Open | Solution persistence |

Supplementary behaviour confirmed by the text (E2 p. 43):

- Creating, loading or saving a solution **clears the undo/redo cache**.
- The module count limit is **configurable up to 1024** (E2 §7, p. 72).

### 3.2 Image display area (E2 §5.2.3, pp. 43–44)

Text-confirmed capabilities:

1. Two data sources: **a single module's output image** or **the flow's final output image**.
2. It also displays **the module's output results** (region 12 table).
3. Select a module in the flow → its output image appears in the right-hand image area.
4. Supported image operations: **single/double view switch**, **crosshair auxiliary line**, zoom,
   and local image operations.
5. **Global image display** requires, on the flow card, the ⚙ button → open the flow configuration
   window → **Display Settings** tab → choose *Output Image* as the parameter name → `+` →
   subscribe the image source → execute; then the flow's final image is shown.
6. The image area carries a status line with `resolution | X | Y | R | G | B` — matching the
   composite screenshot (`1280*1024 | X:0937 Y:0177 | R:012 G:012 B:012`).
7. A **thumbnail strip with an index counter `(1/1)`** and an **auto-switch (自动切换)** toggle sits
   between the image and the result table; the thumbnail strip header is labelled with the current
   image source.

### 3.3 Flow configuration window (E2 §8.1, pp. 99–103)

A modal dialog titled with a numeric id and the word 流程 (flow), with **four tabs**:

| Tab | Purpose (from E2) |
|---|---|
| 输入设置 Input settings | Select which flow inputs are exposed; IMAGE / PIXELIMAGE parameters ticked here are treated as data that must be presented in the image display window |
| 输出设置 Output settings | Select which module outputs of this flow are exposed |
| 运行参数 Run parameters | Parameters of the flow's modules collected as flow-level run parameters |
| 显示设置 Display settings | Choose which image is shown in the image display area after the flow runs |

Footer buttons: **连续执行 Continuous execute · 执行 Execute · 确定 OK**.

### 3.4 Module general configuration (E2 §8.2, p. 103+)

> "大部分模块主要由基本参数、运行参数和结果显示组成" — *most modules consist of basic
> parameters, run parameters and result display.*

- **基本参数 Basic parameters**: subscribe the image input and configure the ROI for the inspection
  region.
- **运行参数 Run parameters** are grouped by category, e.g. 图像相关参数 (image cache count, capture
  interval, stop-on-last-frame) and 边缘相关参数 (edge type, edge polarity, edge threshold) — see
  E2 Fig. 8-16.
- Parameter editors follow a fixed vocabulary (E2 p. 109): **dropdown select**, **enable/toggle**,
  **numeric**, and **ROI shape** editors where a shape is drawn on the preview and its numeric
  parameters can also be edited directly.
- **ROI shape vocabulary** (E2 p. 108): point, line, rectangle, circle, annulus, polygon (the V3.0.2
  manual corroborates this vocabulary and lists up to a 32-vertex custom polygon plus a template
  modelling toolbar).
- **Result display** is the per-parameter table (region 12), not a key/value port list.

### 3.5 Flow editing area (E2 Fig. 5-2; E1 pp. 74/95)

- Canvas: flat grey with a faint dot grid.
- Module card: white rounded rectangle, **number + name**, with a **coloured circular badge on the
  left edge** carrying the category glyph; a status accent on the card.
- Connections: **plain orange arrows**, routed with right-angle elbows.
- Multi-flow overview (E1 p. 95) uses larger white cards with play / loop / formatting buttons,
  `NTimes`, cycle time and an orange enable slider.
- Flow bar above the canvas (E2 Fig. 5-2 region 7): a module-box toggle, an "edit flow" pencil, the
  flow tab(s), play and loop buttons, a `+` to add a flow, and a dropdown.

### 3.6 Status bar (E2 Fig. 5-2 region 10, corroborated by E1 p. 40 item 7)

`Component Config Completed | Flow <ms> | Tools <ms> | Algorithm <ms>` — four segments, left to
right, in a single bottom strip.

### 3.7 Global variables (E2 §9, pp. 110–112)

Columns **Name | Comment | Type | Current value**; types `int`, `float`, `string`; values writable
at runtime and settable over the communication interface (`SetGlobalValue:var0=0`).

---

## 4. Gap closure status

Ranked by visual and behavioural impact. "Current" was the state of this repository at the start of
this iteration; "status" is the verified outcome after implementation.

| # | Gap | Was | Specification | Status |
|---|---|---|---|---|
| G1 | **Result area structure** | Result grid stacked under the image *and* a separate module-log table in a bottom dock — two competing surfaces | Two-row right column: upper tab bar `Image \| Module Results`, lower tab bar `Current Result \| History Result \| Help`, both visible at once; no bottom result dock | **CLOSED** — `main_window._init_property_dock` builds `data_tabs` (Image / Module Results) above `ResultDisplayArea` (Current Result / History / Help); the module-execution trace moved to a hidden Module Log dock |
| G2 | **Result table schema** | Fixed columns `Module / Kernel / Status / Latency / Message` | Column per output parameter, module-specific | **CLOSED** — `extract_feature_rows()` builds `Index, Area, Perimeter, Centroid X/Y, Angle, Major, Minor, Circularity, …` from record lists or parallel lists, with a `Parameter\|Value` fallback for scalar modules |
| G3 | **Image display header** | No source header, no view toolbar | Source label, single/dual view, `+`, `−`, `1:1`, fit, expand | **CLOSED** — `image_display.ImageDisplayArea` |
| G4 | **Image strip + auto switch** | Absent | `<source> (1/1)`, thumbnail strip, auto-switch toggle, run-scope selector | **CLOSED (partial)** — strip, index counter, paging arrows and thumbnails are live and select the module whose image is shown; the *auto-switch* toggle and *Run all* selector are present as layout but not yet behaviourally wired (documented as open) |
| G5 | **Module card badge** | Square badge in the top-right corner | Coloured **circular** category badge on the card's left edge | **CLOSED** — badge overhangs the left edge, index + name to its right |
| G6 | **Flow-area zoom tool** | Absent | Small control at the lower-left of the canvas | **CLOSED** — `FlowZoomTool` with live percentage, −, +, fit |
| G7 | **Quick toolbar grouping** | 15 icons in two rows | Single quick-toolbar strip | **ACCEPTED** — content matches; the two-row split is a deliberate adaptation for narrower desktops and keeps every documented control visible (verified at 1100 px) |
| G8 | **Module configuration dialog** | Single flat parameter form in a side inspector | Tabbed `Input Params / Output Params / Run Params / Display Settings` with grouped run parameters and `Continuous / Execute / OK` footer | **CLOSED** — `module_config.py`, opened by double-clicking a module or via its context menu |
| G9 | **ROI shape vocabulary** | Rectangle only | point / line / rect / circle / annulus / polygon drawn on a preview | **OPEN** — rectangle ROI is implemented with 8 interactive handles; the wider shape vocabulary is the largest remaining functional gap |
| G10 | **Global variables columns** | Name / Type / Value | Name / Comment / Type / Current value | **OPEN** — small, self-contained change; not yet done |
| G11 | **Undo/redo step cap** | Unbounded | Configurable, hard limit 15 (E2 p. 72) | **OPEN** |
| G12 | **Module count cap** | Unbounded | Configurable, default 1024 max (E2 p. 72) | **OPEN** |

### 4.1 Verified by test

| Spec item | Test |
|---|---|
| Result display tabs + per-feature columns | `test_reference_spec_ui.py::test_result_display_area_has_the_documented_tabs`, `…::test_result_table_uses_one_column_per_feature`, `…::test_result_table_uses_parallel_lists`, `…::test_result_table_scalar_fallback_is_parameter_value` |
| Two-tier right column (upper/lower tab bars) | `…::test_window_has_the_vendor_two_tier_right_column`, `test_right_panel_layout.py::test_right_column_matches_the_vendor_two_tab_layout`, `…::test_upper_tab_switches_the_display_block`, `…::test_result_table_is_visible_without_switching_tabs` |
| One result table + hidden module log | `…::test_window_exposes_one_result_table_and_a_module_log` |
| Image display controls, dual view, strip paging | `…::test_image_display_area_has_the_documented_controls`, `…::test_image_display_dual_view_toggle_emits`, `…::test_image_display_strip_paging`, `…::test_window_image_strip_lists_flow_images` |
| Card badge on the left edge | `…::test_module_card_has_a_circular_category_badge` |
| Flow-area zoom tool | `…::test_flow_zoom_tool_tracks_and_changes_zoom` |
| Module configuration window | `…::test_module_config_dialog_tabs_and_footer`, `…::test_module_config_dialog_lists_ports_and_subscriptions`, `…::test_module_config_dialog_enum_and_path_editors`, `…::test_module_config_dialog_edits_write_through`, `…::test_window_opens_module_config_and_reruns` |

Rendered evidence: `docs/screenshots/audit/26_right_column_closeup.png` (the reproduced right column),
`…/20_image_display_area.png`, `…/22_module_config_tab0..3.png`, `…/23_image_display.png`,
`…/24_result_display.png`, `docs/screenshots/live_window.png`; the design source is
`docs/references/external/ui_crops/right_column_zoom.png`.

---

## 5. Open questions (evidence not obtained)

1. **Exact view-mode icon semantics** in the image display toolbar (`▣▣` single/double view,
   `⤢` expand) — the icons are visible in E2 Fig. 5-2 but not described in a table. Only the
   *single/double view* and *crosshair auxiliary line* behaviours are text-confirmed (§3.2).
2. **The crosshair auxiliary-line configuration UI** (E1 p. 85 shows a `Cross Line` dialog with
   Coordinates / Thickness / Brush / Display / Locking) is from the older release; whether 4.3 keeps
   that exact dialog is unconfirmed.
3. **Video-level interaction detail** (drag feedback, hover states, menu animation) could not be
   verified from a machine-readable source; the reproduction therefore follows the documented
   behaviour plus the figures, and this is noted rather than guessed at.
4. **Region 5 "Other"** is only "window controls" in the legend; no further detail is documented.
