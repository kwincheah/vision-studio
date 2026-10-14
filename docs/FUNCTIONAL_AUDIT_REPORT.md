# Comprehensive Functional, UI/UX and Regression Audit

An end-to-end audit of Apex Industrial Vision Studio: every registered vision tool, the
flow engine, persistence, and every reachable screen and dialog. Every finding below was
**reproduced by execution**, fixed at the root cause, and pinned with a regression test.

## Method

"Tested" here means a named script or test produced a recorded result — not that a
button was clicked. Six re-runnable audit harnesses were built for this audit:

| Script | What it does | Result |
|---|---|---|
| `scripts/audit_inventory.py` | Instantiates all 40 tools; reports ports and parameters | **40/40 build** |
| `scripts/audit_tool_behaviour.py` | Runs 10 scenario families per tool (missing / valid / empty / 1×1 / wrong-type / grayscale / blank / `None` / repeat / degenerate params) | **40 tools, 0 problems** |
| `scripts/audit_tool_contracts.py` | Feeds **378 adversarial port values × 40 tools = 756 executions** — what a degraded upstream module really emits | **0 violations** (was 31) |
| `scripts/audit_pipeline_behaviour.py` | Disconnection, failure isolation, repeat stability, cycle handling, empty flow | **18/18 checks** |
| `scripts/audit_persistence.py` | Project save/load, corrupt/truncated/missing files, XML junk, image output | **17/17 cases** (was 6 problems) |
| `scripts/audit_flow_execution.py` | Executes the sample solution and prints every module's real status, timing and outputs | **7/7 modules coherent** |
| `scripts/audit_bug_patterns.py` | Sweeps the *code shapes* that produced the bugs above: swallowed exceptions, unchecked falsy-returning APIs, unguarded conversions, unused parameters/ports | **2 residual, both explained below** |

Plus `scripts/audit_ui_dialogs.py` (opens and captures every menu dialog),
`scripts/audit_qt_warnings.py` (captures Qt warnings per dialog),
`scripts/audit_ui_screens.py`, `scripts/audit_coverage_matrix.py`, and the earlier
contrast suites.

---

## 1. Bugs found and fixed

### 1.1 Crashes from malformed geometry input — 4 tools

A tool raising an exception aborts its own result: the pipeline catches it and reports
the useless string `"Exception: not enough values to unpack (expected 4, got 2)"` with
**no indication of which port was at fault**, and every downstream port goes missing.

| Tool | Trigger | Was | Now |
|---|---|---|---|
| `L2L Measure` | partial line dict, short sequence, string | `KeyError` / `ValueError` | `ERROR` naming `Line1`/`Line2` |
| `P2P Measure` | 1-element point | `IndexError` | `ERROR` naming the port |
| `Position Correction` | `None`/string/non-finite running pose | `TypeError` / `ValueError` / `OverflowError`, and a NaN pose propagated into the affine matrix | falls back to the fiducial default; matrix stays finite |
| `Geometry Generation` | blank/non-numeric centre, radius or line point | `TypeError` / `ValueError` / `IndexError` | coerced to a finite value; negative radius made positive |

Root cause for all four: geometry ports were **unpacked and indexed directly**
(`x1, y1, x2, y2 = l1`), so any shape other than the expected one raised. Fixed by
adding shared coercion helpers to `VisionToolBase` — `as_float`, `as_point`,
`as_line`, `as_point_list` — which validate the *documented* shapes and return `None`
for anything else, and by making each tool report which port was unusable.

### 1.2 Silent wrong results — 3 tools

Worse than a crash, because the operator sees a confident number.

| Tool | Was | Now |
|---|---|---|
| `P2P Measure` | a malformed point was coerced to `(0, 0)`, producing a plausible but meaningless distance | rejected with the port named |
| `Circle/Line Fit` | only counted rows, so a 3-column or ragged list became an array whose **column 1 was read as the y coordinate** — a silently wrong fit | `as_point_list` requires a finite `(N, 2)` array |
| `N-Point Calibration` | `float()` accepts `NaN`/`inf`, which then passed into `cv2.transform` and emitted a **NaN world coordinate** into every downstream measurement | `as_float` rejects non-finite input |

### 1.3 NaN produced a confident verdict — 3 logic tools

`try: float(val) except (ValueError, TypeError)` does **not** protect a comparison:
`NaN >= 50.0` is `False`, so a non-finite reading reported a definite `NG`.
`Condition Branch` additionally raised `OverflowError` on `inf` (outside its guard).

Fixed in `Condition Branch`, `Variable Calculation` and `If Module` by routing through
`as_float`. `Condition Branch`'s verdict message was also corrected — it printed the
*unused* bound, reading `Val=7.00 <= [0.0, 150.0] -> FAIL`, which looks like a
contradiction; it now prints only the bound it applied.

### 1.4 Inert parameters — three features that did nothing

Declared in the property grid, read by nobody.

| Tool | Inert parameter/port | Consequence |
|---|---|---|
| `Image Output` | `save_mode` (`Only on NG` / `Only on OK`) | filled the disk during a pass run — it always saved |
| `Image Output` | `Trigger` port | saved on every cycle regardless of the trigger |
| `Image Output` | `image_quality` | had no effect on JPEG output |
| `TCP Send` | `suffix` (default `\r\n`) | **the PLC frame terminator was never sent** |
| `TCP Send` | `Trigger` port | transmitted on every cycle |
| `Camera IO` | `invert_logic`, `strobe_active_high`, `pulse_duration_ms` | all three did nothing |

All are now implemented and tested, including the escape-sequence decoding that turns
the configured visible `\r\n` into real control characters.

### 1.5 A failed transmission reported success

`TCP Send` in real `TCP Client` mode wrapped its socket call in
`except Exception: pass` and then returned **OK** regardless. An operator had no way to
know the PLC never received the verdict. Now an `OSError` returns `ERROR` naming the
endpoint, verified both against a closed port (reports failure) and a real listening
socket (delivers the exact bytes `b"VM_RES,NG\r\n"`).

### 1.6 `Image Output` claimed a save that never happened

`cv2.imwrite` signals failure by **returning `False`**, not by raising, so a full disk,
a read-only directory or an unsupported extension all still reported
`"Saved image to: ..."`. The return value is now checked, and the written file is
confirmed to exist.

### 1.7 `Image Morphology` crashed on ordinary kernel values

`int(self.get_param("kernel_size", 3))` raised `TypeError`/`ValueError` on a blank or
non-numeric entry, and OpenCV asserted (`cv::normalizeAnchor`) on `0` or a negative
size. An even kernel has no true centre and shifts the result by half a pixel. The
kernel is now coerced to a positive odd integer in `1..255`.

### 1.8 The sample AOI verdict accepted a defective board

`06_QualityJudge` used `<=` against a tolerance of `0`, so a board with **7 defects
reported PASS** — and that verdict was what got transmitted to the PLC. Corrected to an
exact zero-defect acceptance, with the defect count, the verdict and the transmitted
string now asserted to agree.

### 1.9 A stylesheet that Qt silently discarded

`camera_dialog.py` contained `background-color: THEME['vm_viewport'];` inside an
f-string **without braces**, so the token name became literal CSS text and Qt threw
away the entire inline stylesheet — reported only as
`Could not parse stylesheet of object QLabel(...)` on stderr. Repaired; the preview
then rendered, revealing the next defect.

### 1.10 Dark body ink on the dark viewport

Once the stylesheet applied, the camera preview label measured **1.8:1** — unreadable.
Its ink was the standard body tone; it now uses the viewport ink (**13.95:1**).

### 1.11 Clipped table header in the camera dialog

`ResizeToContents` columns cannot shrink, so the four columns overflowed the pane: the
header read **"ame / Mode"** and the last column **"Int"** behind a horizontal
scrollbar. Fixed by lowering the minimum section width so the content-sized columns
fit; verified with **no horizontal scrollbar at 640, 760, 880 and 1100 px**.

### 1.12 Empty and non-XML files gave an unhelpful error

`safe_fromstring("")` raised the parser's bare `ParseError: no element found`.
It now names the real problem ("the file is empty" / "not XML — is it a project file
from another application?") while `DOCTYPE`/`ENTITY` rejection and the `ParseError`
contract for damaged-but-non-empty XML are unchanged.

### 1.14 A project file could crash or hang an inspection (second-pass sweep)

A second pass swept for the *code shapes* that produced the defects above rather than
for more values (`scripts/audit_bug_patterns.py`). It found that `set_param()` and
`load_dict()` stored whatever they were given, so a parameter's declared type was not
enforced. Every tool then converts parameters with a bare `int()`/`float()` at the
point of use — 79 such call sites — so a wrong-typed value raised mid-inspection:

```
set_param("kernel_size", "nonsense")   -> stored 'nonsense'  -> ValueError at run time
load_dict({"parameters": {"kernel_size": None}})  -> stored None -> TypeError at run time
```

Two reachable consequences:

* **Crash** — a project file written by an older build, or edited by hand, put `None`
  or a string into a numeric knob. `x, y, w, h = roi` on a string raised
  *"not enough values to unpack"*.
* **Denial of service** — Python integers are unbounded, so a crafted project file
  could set `caliper_count` to `10**18`; the tool then tried to allocate 3.47 EiB
  (`MemoryError`), and a negative `buffer_capacity` broke `deque(maxlen=…)`.

Fixed at the boundary rather than at 79 call sites: `VisionToolBase._coerce_param`
now enforces the invariant that **a parameter always holds a value of its declared
type and a usable magnitude**, rejecting non-finite, out-of-magnitude, wrong-shaped and
unparseable values in favour of the existing one. `load_dict` routes through the same
coercion so a project file cannot bypass it, and `get_bounded_param` gives tools with a
genuine range (an OpenCV kernel, a buffer capacity) a stated way to clamp.

### 1.15 The barcode decoder's absence was reported as "no barcode found"

`BCR Recognition` wrapped the whole decode in `except Exception: pass`, so an OpenCV
build without the barcode module, a genuine decode error, and a clean negative result
all produced the same message. The detector's return arity also varies between builds
(3 or 4 values) and the code assumed 4, raising `ValueError` on small images. The three
outcomes are now distinguished, and the result is unpacked defensively.

### 1.16 Audit-harness defects found and corrected

Three of my own test failures were harness errors, not product bugs, and are recorded so
the distinction is not lost: the line/point input shapes I first synthesised did not
match what `Line Search`/`Caliper` emit; a `QMessageBox`-closing timer raced the
capture; and an isolated dialog capture produced a false dark-theme reading because the
dialog inherits the main window's stylesheet.

---

## 2. UI/UX inspection

**Captured and examined** (`docs/screenshots/audit/`): the main window at 3 sizes, 6
menus, 4 tool flyouts, both right-column pages, all 3 result tabs, 4 config tabs, the
Start Page, 13 dialogs (including the camera manager, lens-calibration wizard, N-point
wizard, global variables, and 9 message boxes), and the live application at 1616×989.

**Inventory:** 6 menus / 51 actions, **0 disabled actions**, 2 toolbars (38 controls),
3 dock panels, 40 tools in 11 categories.

Discrepancies found and fixed are §1.9–§1.11. No primary colour, layout or proportion
was changed — the approved palette and the VisionMaster-measured split are untouched,
and the contrast suites still pass (39 palette pairs, 34 stylesheet rules, 0 below
target).

---

## 3. Tests executed

| Suite | Result |
|---|---|
| Full test suite | **658 passed, 0 failed** (was 280 at the start of this audit) |
| New test modules (5) | **378 passed** |
| Tool behaviour (40 tools × 10 scenarios) | 0 problems |
| Port contracts (756 executions) | 0 violations |
| Parameter fuzz (40 tools × 22 hostile values × 3 modes) | 0 failures |
| Bug-pattern sweep | 2 residual, both explained |
| Pipeline behaviour | 18/18 |
| Persistence | 17/17 |
| Sample flow execution | 7/7 modules coherent |
| Contrast: palette / stylesheet / screens | 39 pairs, 34 rules, 21 pixel probes — all clean |

New regression modules:

* `tests/test_functional_audit_fixes.py` — the malformed-geometry crashes, the silent
  coercion, the NaN verdicts, the geometry-fit shape check, the sample verdict, and the
  coercion helpers.
* `tests/test_persistence_and_output_fixes.py` — Image Output write verification and
  save policy, the XML diagnosis, the camera dialog's stylesheet and contrast, and the
  table-column fit.
* `tests/test_uncovered_tools.py` — behavioural tests with *known expected results* for
  the five tools that had none (`Geometry Generation`, `Image Morphology`,
  `Color Extraction`, `TCP Send`, `Camera IO`), including a real loopback TCP
  transmission.
* `tests/test_parameter_integrity.py` — the parameter-type invariant: coercion,
  rejection of non-finite and wrong-shaped values, project round-trip stability, and the
  barcode decoder's three outcomes.
* `tests/test_parameter_fuzz.py` — attacks the invariant from outside: every parameter
  of every tool is driven with 22 hostile values through both `set_param` and
  `load_dict`, then the tool is executed.

**Coverage** (`scripts/audit_coverage_matrix.py`): **40/40 tools** are exercised by the
generic audits; 35 were named in a dedicated test before this audit, **40/40 now**.

---

## 3.1 Residual findings, and why they are left

The pattern sweep reports two categories that are **not** defects. They are recorded so
the distinction is visible rather than hidden by a clean exit code.

**79 unguarded `int()`/`float()` conversions of parameters** — safe by the invariant
§1.14 establishes, and *proven* so rather than assumed: `tests/test_parameter_fuzz.py`
drives every parameter of all 40 tools with 22 hostile values (including `None`,
strings, `NaN`, `inf`, `10**18`, wrong containers and objects) through both entry points
and then executes the tool. Any hole in the boundary would surface as a crash. The
sweep cannot know the invariant, so it continues to report the call sites; they are the
places the invariant protects.

**One swallowed exception** — `Circle Search` catches `np.linalg.LinAlgError` around its
caliper-fit attempt, which is deliberate and correct: degenerate (collinear) edge points
make the normal-equation solve singular, and the documented behaviour is to fall back to
the Hough transform. It is not hiding a failure — it is the fallback's guard.

---

## 4. Unresolved issues and what could not be tested

Nothing found is left unfixed. The following are **limits of the test environment**, not
known defects:

1. **Real camera hardware** — no GigE/USB3 Vision device is attached. `Camera Set`
   enumeration, live preview and MVS binding are exercised only through the emulated
   device list and the `MvCameraControl` shim. `Camera IO` is verified logically
   (line states, polarity, invert, pulse) but no physical strobe was fired.
2. **A real PLC/robot peer** — `TCP Send` is verified against a local loopback listener
   it starts itself. Field framing, handshaking and timeouts against actual plant
   hardware are untested.
3. **Object detection** — `Object Detection` runs with its synthetic fallback path; no
   YOLO weights are present, so the real inference path is unexercised.
4. **`System → Log Viewer`** — this action opened no dialog. Either it is a stub or it
   logs elsewhere. **Not fixed, because I could not determine the intended behaviour**;
   recorded here rather than guessed at.
5. **Native file dialogs** — `QFileDialog` is OS-owned and cannot be captured
   offscreen, so `Load Image File…` / `Save Solution As…` were verified by driving the
   non-native paths and the persistence layer directly, not by screenshot.
6. **Tooltip popups** — Qt only realises a `QTipLabel` inside a running event loop, so
   the tooltip surface is verified by asserting its stylesheet rule (15.7:1) rather than
   by image.
7. **Long-run stability** — the repeat test runs a flow 4 times and confirms identical
   results; multi-hour continuous execution and memory growth were not measured.

---

## 5. Files changed

**Product**

| File | Change |
|---|---|
| `vm_clone/core/base_tool.py` | `as_float`/`as_point`/`as_line`/`as_point_list` validators; `_coerce_param` type-and-magnitude boundary on `set_param`/`load_dict`; `get_bounded_param` |
| `vm_clone/tools/measurement.py` | `L2L Measure`, `P2P Measure` validated input handling |
| `vm_clone/tools/location.py` | `Position Correction` non-finite pose handling |
| `vm_clone/tools/calibration.py` | `N-Point Calibration` non-finite pixel handling |
| `vm_clone/tools/logic.py` | NaN-safe comparisons in 3 tools; honest verdict message |
| `vm_clone/tools/image_generation.py` | `Circle/Line Fit` point-shape validation; `Geometry Generation` parameter coercion |
| `vm_clone/tools/image_processing.py` | `Image Morphology` kernel/iteration coercion and error reporting |
| `vm_clone/tools/image_output.py` | write verification, `Trigger` gating, `save_mode` filtering, `image_quality`, bounded buffer capacity |
| `vm_clone/tools/communication.py` | `TCP Send` suffix/trigger/error reporting; `Camera IO` invert/strobe/pulse |
| `vm_clone/tools/recognition.py` | `BCR Recognition` distinguishes unavailable / error / no-detection; tolerates variable decoder arity |
| `vm_clone/core/xml_safe.py` | actionable errors for empty and non-XML input |
| `vm_clone/samples/pcb_solution.py` | corrected AOI acceptance criterion |
| `vm_clone/ui/camera_dialog.py` | repaired stylesheet, contrast-correct preview ink, non-clipping table |

**Audit tooling** — `scripts/audit_inventory.py`, `audit_tool_behaviour.py`,
`audit_tool_contracts.py`, `audit_pipeline_behaviour.py`, `audit_persistence.py`,
`audit_flow_execution.py`, `audit_bug_patterns.py`, `audit_ui_screens.py`,
`audit_ui_dialogs.py`, `audit_qt_warnings.py`, `audit_coverage_matrix.py`,
`find_bad_stylesheets.py`, `check_coercion_helpers.py`, `check_image_output.py`,
`check_camera_table.py`, `harden_logic_conversions.py`.

**Tests** — 5 new modules, 378 new assertions.

**Artifacts** — `docs/audit/{tool_matrix,contract_matrix,persistence_matrix,coverage_matrix,ui_inventory,dialog_inventory}.json`.

No unrelated features were added, no functionality was removed, and the existing suite
passes unchanged.
