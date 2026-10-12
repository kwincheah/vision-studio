# HikRobot Vision Master Clone — Verification Matrix & Audit Checklist

**Standard ref:** official HikRobot Vision Master manuals — bundled `HikRobotVMHelp_compressed.pdf` (657 pp.)
plus the downloaded 4.3.0 maintenance manual (928 pp., see `docs/VISIONMASTER_REFERENCE_SPEC.md`)
**Measured layout:** `docs/VISIONMASTER_STORYBOARD.md` (分镜 breakdown; worst deviation 0.32 %)
**Test suite:** 135 automated tests, `135 passed` (`python -m pytest tests/`)
**Rendered evidence:** `docs/screenshots/` (`layout_comparison.png` at the reference size,
`audit/` screen set, `spec_comparison.png`, `live_window.png` from the running application)

---

## 1. System architecture & capabilities

| Module / subsystem | Manual page | Status | Evidence |
|---|---|---|---|
| Pipeline DAG runner | 92–97 | VERIFIED | Topological ordering, typed port validation, cycle prevention — `tests/test_vision_tools.py`, `tests/test_flow_control.py` |
| Multi-flow management | 93–97 | VERIFIED | `SolutionManager` with per-flow timing, trigger-flow selection, isolation — `tests/test_workflow_e2e.py::test_multi_flow_isolation_and_overview_sync` |
| Global variables | 108–112 | VERIFIED | 32-channel store, editor dialog, result-grid subscriptions — `test_result_panel_binds_parameter_to_global_variable` |
| Image viewport | 81–88 | VERIFIED | Subpixel pan/zoom, 8 ROI handles, corner brackets, reticle, histogram HUD — `tests/test_ui_canvas_and_flow.py` |
| Flow editor | 92–97 | VERIFIED | Module cards, typed ports, routed wires, undo/redo, auto-layout, drag-and-drop — `tests/test_flow_editor_interactions.py` |
| Parameter inspector | 43–45 | VERIFIED | Typed form controls, file/folder browse, ROI draw round-trip, inline script editor — `tests/test_acquisition_file.py` |
| Result display | 81–88 / p.87 | VERIFIED | `Param Name \| Current Result \| Global Variable` grid, per-module verdict grid, history log, CSV export |
| Persistence | 93 | VERIFIED | Flow `.prc` export/import, solution JSON round-trip — `test_workflow_e2e.py`, `test_flow_duplication_and_serialization` |

---

## 2. Vision tools (38 registered modules)

| Category | Tools | Tests |
|---|---|---|
| Acquisition (p.169–180) | Image Source, Image Output, Image Buffer | `test_acquisition_file.py`, `test_acquisition_synthetic_patterns` |
| Location (p.181–279) | Template Match, Position Correction, Circle Search, Line Search, Caliper, Edge Search, BLOB Analysis | `test_location_tools`, `test_position_correction`, `test_edge_search` |
| Measurement (p.280–298) | L2L Measure, P2P Measure, Intensity Measure, Pixel Count, Edge Distance, Histogram | `test_measurement_tools`, `test_pixel_count_and_histogram` |
| Image Generation (p.299–304) | Circle/Line Fit, Geometry Generation | `test_geometry_fit_circle` |
| Image Processing (p.414–473) | Image Binarization, Image Filter, Image Morphology | `test_vision_tools.py` |
| Color Processing (p.463–473) | Color Extraction, Color Measurement | `test_extended_tools.py` |
| Recognition (p.304–326) | 2D BCR, BCR 1D, OCR | `test_extended_tools.py` |
| Defect Detection (p.493–544) | Defect Detection, Linear Edge Defect | `test_pipeline_execution_and_dag_data_flow` |
| Calibration (p.346–413) | N-Point Calibration | `test_calibration_tool` |
| Communication (p.545–598) | TCP Send, Camera IO | `test_extended_tools.py` |
| Logic Tools (p.546–598) | Condition Branch, Branch String, If Module, Trigger, Variable Calculation, Script Tool, Image Buffer logic | `test_flow_control.py`, `test_logic_branch_tools_execution` |

---

## 3. UI/UX capability matrix (reference-verified)

| Feature | Reference | Status | Verification |
|---|---|---|---|
| Control Toolbar inventory + ordering | p.70 | VERIFIED | `test_control_toolbar_inventory_and_order`; 15 icons present, no text labels, correct checkability and tooltips |
| Menu structure | p.42–68 | VERIFIED | `test_menu_structure_matches_reference` |
| Category rail with one glyph per category | p.72 | VERIFIED | `test_rail_provides_one_glyph_per_registered_category` |
| Flyout icon grid + category switching | p.74 | VERIFIED | `test_flyout_grid_filters_by_category_and_search`, `test_toolbox_panel_selects_first_category_by_default` |
| Cross-category tool search | p.74 | VERIFIED | `test_flyout_grid_filters_by_category_and_search` |
| Drag-and-drop module insertion | p.74 | VERIFIED | `test_flyout_grid_uses_icon_and_label_and_exposes_drag_payload`, `test_flow_editor_interactions.py` |
| White module cards with orange index + type badge | p.74 | VERIFIED | Rendered: `vm_flow_workspace.png` |
| Verdict-coded card border (PASS/FAIL/TIMEOUT/RUN) | p.74 | VERIFIED | `vm_flow_workspace.png`; `update_node_status()` |
| Orange orthogonal routed wires with arrow heads | p.74/95 | VERIFIED | `test_interactive_wire_connection`, `test_connection_selection_and_deletion` |
| Bidirectional wiring (drag from either end) | p.92 | VERIFIED | `finish_connection_drag_at_pos()` direction normalisation |
| Editing lock protection | p.70 | VERIFIED | `test_lock_protection_blocks_editing` (blocks insert, move, wire drag) |
| Undo / redo across insert, delete, move, connect | p.70 | VERIFIED | `test_undo_redo_from_toolbar`, `test_undo_redo_connection_and_node` |
| Flow tab strip with dot + verdict + timing | p.40 item 8 | VERIFIED | `test_flow_tab_label_and_tooltip_expose_verdict` |
| Image \| Result right split | p.40 item 5/6 | VERIFIED | `test_workspace_tabs_include_reference_screens` |
| `Param Name \| Current Result \| Global Variable` grid | p.87 | VERIFIED | `test_result_panel_three_column_structure` |
| Global-variable subscription from results | p.87 | VERIFIED | `test_result_panel_binds_parameter_to_global_variable` |
| Operation Interface overlay switches | p.40/p.96 | VERIFIED | `test_operation_panel_layer_switches_drive_canvas`, `test_histogram_toggle_stays_in_sync` |
| Multi-Flow overview cards + dependency bus | p.95 | VERIFIED | `test_flow_overview_creates_one_card_per_flow_with_trigger_wires`, `test_flow_overview_card_signals` |
| Segmented status bar | p.40 item 7 | VERIFIED | `test_segmented_status_bar_updates_after_run` |
| Result history per cycle | p.40 item 6 | VERIFIED | `test_history_tab_records_one_row_per_cycle` |
| Layout resilience across window sizes | p.40 | VERIFIED | `test_layout_is_consistent_across_window_sizes` (4 sizes) |
| Flow probe / thumbnail navigator | p.40 item 9 | VERIFIED | `tests/test_flow_probe.py` (5 tests) |
| Dock float / re-dock state retention | usability | VERIFIED | `test_dock_reflow_keeps_state` |
| Disconnected-module diagnostics | p.92 | VERIFIED | `test_validation_reports_disconnected_module` |
| Vector icon engine (no external assets) | UI standard | VERIFIED | `test_category_icons_rendered`, `test_tool_icons_rendered`, `test_toolbar_action_icons` |
| Centralised sampled palette | UI standard | VERIFIED | `test_vm_theme_tokens_match_sampled_reference` |

---

## 4. Autonomous verification summary

- **Registered tools:** 38 across 11 categories.
- **Automated tests:** 135 passed (≈25 s), run both isolated and in a single process.
- **Reference evidence:** 6 manual pages extracted and sampled; colour tokens taken from measured
  RGB values, not estimates.
- **Live verification:** the application was launched with `python main.py`, confirmed as a visible,
  responding top-level window (`Apex Industrial Vision Studio v4.3`) and captured on-screen with
  Win32 `PrintWindow` → `docs/screenshots/live_window.png`.
- **Known environment limitation:** the DSH file sandbox forbids deleting directories under the
  platform temp root, so `tempfile.TemporaryDirectory()` fails during cleanup; one test was moved to
  an auto-removed workspace file. This is not a product defect.
- **Open gaps:** no live camera SDK, no per-module tabbed configuration dialog (p.96), per-module
  image probe overlay, and no bundled zh-CN localisation — see
  `VISIONMASTER_ALIGNMENT_REPORT.md` §6.
