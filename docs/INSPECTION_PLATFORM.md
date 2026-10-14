# AI Inspection Development and Validation Platform

How the application went from a node editor to a platform where an inspection workflow
can be built, **measured** and debugged. This document records what already existed, what
was added, and what the numbers actually are.

> **The central constraint honoured throughout:** no metric is reported unless the logic
> behind it is implemented and tested. Where a value cannot be defined, the code and the
> interface say `n/a` rather than `0`, because "no confidence ranking exists" and "the
> detector scored zero" are different statements.

---

## 1. What already existed and was reused

Nothing was rebuilt. The audit found a working foundation and the platform is built on
top of it.

| Existing component | State found | How it is reused |
|---|---|---|
| `core/pipeline.py` — `VisionPipeline`, `SolutionManager` | Working. Topological execution, branch bypass, flow timeout, XML/JSON persistence | **The only execution engine.** The GUI, the batch runner and the CLI all call `execute_flow` |
| `core/base_tool.py` — `VisionToolBase`, `ToolPort`, `ToolExecutionResult` | Working, with per-run `elapsed_ms` and `outputs` | Node contract for the new detector; `elapsed_ms` becomes reported inference time |
| 39 registered tool nodes | Working | Untouched. The PCB detector is added as the 40th and 41st |
| `tools/object_detection.py` — YOLO node | Working; `Detections` output already structured | Reused as a detector *source*: the evaluation layer reads its output contract |
| `tools/acquisition.py` — `ImageSourceTool._override_image` | Working | The mechanism that feeds dataset images into a workflow for evaluation |
| `ui/main_window.py`, `ui/result_panel.py`, `ui/styles.py` | The approved KEYENCE-derived design system | The new panel is a dock built from the same tokens; the palette is unchanged |
| `core/fileio.py` — `atomic_write_json` | Working | Experiment records are written atomically |
| 658 passing tests | — | Kept passing; the platform adds 200 more |

**What was missing entirely:** there was no notion of ground truth, no metric, no dataset,
no failure classification and no experiment record. The platform is that layer.

---

## 2. The pipeline that was built

```
                          pipeline built visually, or the built-in detector
                                              │
  annotations ── Dataset ──────────────────────┤
   (JSON / YOLO)                              ▼
                                    evaluation.runner.run_dataset
                                    ├─ load            (timed)
                                    ├─ preprocess      (timed)
                                    ├─ predict         (timed, inference reported apart)
                                    └─ normalise + confidence threshold
                                              │
                                              ▼
                                    evaluation.matching.match_image
                                    greedy · confidence-ordered · one-to-one · per class
                                              │
                    ┌─────────────────────────┼──────────────────────────┐
                    ▼                         ▼                          ▼
            evaluation.metrics        inspection_controller       evaluation.experiment
            TP FP FN · P R F1 mAP     failure classification      record · store · compare
            latency · text report     filters · export             history is append-only
                    │                         │                          │
                    └─────────────┬───────────┴──────────────┬───────────┘
                                  ▼                          ▼
                        ui.inspection_panel            vm_clone.cli
                        (dock, 5 tabs)                 (run/evaluate/compare/list/demo)
```

One implementation of each concern. The GUI panel and the CLI call the same controller and
the same evaluation functions, so a number shown on screen is the number the command line
writes to disk.

---

## 3. What was implemented, and why

### 3.1 Evaluation core — `vm_clone/evaluation/`

**`annotations.py`** — `Detection`, `Annotation`, `ImageRecord`, `Dataset`, IoU, plus
loaders for this project's JSON format and for YOLO/Ultralytics label text. Boxes are
absolute pixels `(x, y, w, h)`, the same convention the detector node and the canvas
already use, so no conversion is needed at any boundary.

**`matching.py`** — the correctness-critical module. Policy, stated once and tested
against hand-computed cases:

1. Predictions sorted by descending confidence; ties broken by area then position, so the
   result is deterministic for a given input.
2. Each prediction claims the unmatched ground truth with the highest IoU, provided it is
   **≥ the threshold** (default 0.50).
3. One-to-one: a ground truth is claimed by at most one prediction.
4. A label mismatch is never a match. Class confusion is therefore a false positive *and*
   a false negative — the honest accounting for defect inspection.

Greedy rather than Hungarian: greedy-by-confidence is the COCO convention and matches how
a line operator reads the output (the most confident box wins the object). The trade-off
is documented in the module rather than hidden.

**`metrics.py`** — counts and rates derived *only* from matching outcomes, plus:
- **Undefined is not zero.** `precision = TP/(TP+FP)` is `None` when nothing was
  predicted; `recall` is `None` with no ground truth; `f1` is `None` if either is.
- **`mAP@IoU` is computed only when a confidence ranking exists.** A detector emitting one
  operating point has no precision–recall curve, so AP is `None`, never a fabricated
  number. All-point interpolation when it can be computed.
- **Micro-averaged** aggregates (every defect instance weighs equally) with a
  macro-averaged per-class table, because a rare class's recall is invisible in the
  aggregate.
- **Latency in four buckets** — inference, preprocessing, harness overhead, total. Only
  inference is a property of the model, and `throughput_fps` is documented as
  inference-only.
- **Errors are counted, not skipped.** A dropped image changes the denominators, so every
  failure is recorded with its stage and the report says the counts exclude it.

**`runner.py`** — batch execution with per-stage timing, a confidence-threshold operating
point, optional working-size resize (with predictions rescaled back to the original
frame — forgetting that would break every match), cancellation, and
`pipeline_predictor`, which adapts a `VisionPipeline` into a predictor through the
pipeline's own `execute_flow`.

**`experiment.py`** — reproducibility records and comparison. Two guarantees are enforced
in code:
- **Records are never overwritten.** `ExperimentStore.save` refuses an existing filename;
  a repeated run gets a suffix. History is append-only by construction.
- **A comparison refuses mismatched conditions.** Different dataset, split or IoU
  threshold raises `IncomparableExperiments` unless the caller explicitly accepts the
  caveat, in which case the warning travels with the result.

Each record holds the workflow fingerprint (a content hash, so an edited-but-same-named
workflow is detectable), the model reference (honest about a classical detector having no
file), dataset manifest and split, IoU and confidence thresholds, working size, metrics,
latency, every error, software versions and hardware.

**`compare` describes trade-offs, not a winner.** Its observations are generated from the
deltas, and it always ends with:

> No metric here establishes that one configuration is universally better; a higher
> recall with more false positives is a different operating point, not an improvement.

### 3.2 A labelled PCB dataset — `vm_clone/samples/pcb_defect_dataset.py`

The repository ships no labelled PCB defect data, and its imagery contains none of the
defects an AOI line cares about. Rather than fabricate metrics against data that does not
exist, this module **generates** boards whose defects are drawn at known positions, so the
ground truth is exact by construction.

Four classes: `scratch`, `void`, `missing_paste`, `missing_cu`.

**This is a development fixture, not a benchmark.** The texture is procedural and the
defect appearance is simple. A model that scores well here has been shown to work on this
generator, nothing more. Every experiment record names the generator, and the dataset's
own metadata says so.

Building it surfaced a **real bug in the ground truth**: `missing_cu` ("a hole in the
copper plane") was being placed on top of pads, so the detector was penalised for
correctly reporting a pad-shaped blob. The fix was to constrain placement to avoid the
design's copper — found because the metrics were wrong, which is the point of measuring.

### 3.3 A detector that can actually be evaluated

Two nodes, in `vm_clone/samples/pcb_defect_tool.py`, registered on the toolbox like any
other so a workflow can be **built visually** with them:

- **`PCB Defect Detection`** — a real classical detector (bright-anomaly detection for
  scratches; locally-dark blobs thresholded at `max(floor, k·MAD)` for the rest; shape and
  depth for classification). It decides from pixels and makes real mistakes.
- **`PCB Board Layout`** — supplies pad and trace geometry from the design, as a real AOI
  system has. Used to tell a pit on a pad from missing copper in the plane.

**Why not YOLO only?** `ultralytics` is installed and `yolo11n.pt` is present, and the
`Object Detection` node works — verified: it runs and returns detections (it found a
"book" in one of the manual PDF renders). But the weights are COCO-pretrained and COCO has
no PCB defect classes, so a YOLO evaluation on this data would report ~0 recall. That is a
true result that says nothing about the platform. The classical detector gives a genuine,
reproducible detector with no external model, so the evaluation, failure analysis and
comparison can be **demonstrated and tested**. Both nodes emit the same `Detections`
contract, so evaluating a YOLO workflow uses exactly the same code path.

### 3.4 Failure analysis — `ui/inspection_controller.py` + `ui/inspection_panel.py`

Every false positive, duplicate and false negative becomes a `FailureCase` with its class,
confidence, best IoU, reason code and box. The classification is tested before any UI is
built on it, because a UI over wrong classification would make wrong results look
rigorous.

Reasons are explained in words, not codes: `no_overlap`, `below_iou`, `already_claimed`,
`class_mismatch`, `no_prediction`.

The view supports filtering by kind, class, image, reason and minimum confidence, with one
deliberate rule:

> **A score filter never drops a false negative.** A missed defect has no confidence;
> filtering it out because it fails a confidence threshold would hide exactly the failure
> a user most needs to see.

Ground truth and predictions are drawn on the same image in different colours *and*
different line styles, so they are distinguishable without relying on colour alone.

### 3.5 The GUI panel

`InspectionPanel` is a bottom dock with five tabs — Evaluate, Results, Failure Analysis,
Experiments, Compare — reachable from a new **Inspection** menu. It is a workspace surface
the user opens when evaluating, **not** a new tab in the measured
rail/canvas/right-column layout: those approved ratios are untouched.

The evaluation runs on a worker thread, because a dataset run takes seconds to minutes and
blocking the event loop would freeze the application.

### 3.6 The command-line runner — `vm_clone/cli.py`

```
python -m vm_clone.cli dataset  --out ./data/pcb --count 40
python -m vm_clone.cli evaluate --dataset ./data/pcb/annotations.json \
                                --detector reference --report
python -m vm_clone.cli evaluate --workflow ./projects/flow.vmflow \
                                --dataset ./data/pcb/annotations.json \
                                --save-experiment ./experiments
python -m vm_clone.cli compare  --store ./experiments --latest 2
python -m vm_clone.cli list     --store ./experiments
python -m vm_clone.cli demo     --workdir ./demo
```

It reuses `pipeline_predictor` and the same execution engine — there is no second
implementation of node execution. Logging goes to stderr and results to stdout, so
`... > results.json` yields a clean file. Exit status is meaningful: 0 success, 1 handled
failure, 2 usage error.

### 3.7 Explainability: deliberately not implemented

The `Inspection > Explainability (Grad-CAM)` menu item explains why it is absent rather
than showing a stub. Grad-CAM needs a differentiable model and a target layer; the
detector this platform can validate is classical. The YOLO node could be explained, but
none of the available weights are trained on PCB defects, so a heatmap would explain the
wrong thing. Shipping one would produce a picture that looks like evidence and is not.
The failure-analysis view is the supported way to inspect why a detection happened, and
everything it shows is measurable.

---

## 4. Measured results

All figures below are from the reference classical detector on the synthetic fixture,
matching IoU 0.50, split `test`, **40 boards / 74 ground-truth boxes**, with the board
design layout supplied. They are a measurement of this detector on this generator.

### Reference operating point

| | |
|---|---|
| True positives | 65 |
| False positives | 10 |
| False negatives | 9 |
| Precision | **0.867** |
| Recall | **0.878** |
| F1 | **0.873** |
| mAP@0.5 | 0.557 |

| Class | GT | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| `missing_cu` | 23 | 23 | 6 | 0 | 0.793 | **1.000** | 0.885 |
| `missing_paste` | 20 | 20 | 0 | 0 | **1.000** | **1.000** | 1.000 |
| `scratch` | 17 | 8 | 4 | 9 | 0.667 | 0.471 | 0.553 |
| `void` | 14 | 14 | 0 | 0 | **1.000** | **1.000** | 1.000 |

`scratch` is the weakest class (F1 0.553) — a 2-pixel bright line at a detection threshold
of 150 luma is genuinely marginal, and the false negatives are the thin or low-contrast
ones. This is the kind of specific, actionable weakness the failure view exists to expose.

### Two operating points, same data

| | reference | conservative |
|---|---|---|
| Precision | 0.867 | **0.953** |
| Recall | **0.878** | 0.514 |
| F1 | **0.873** | 0.690 |
| False positives | 10 | **1** |
| False negatives | **9** | 36 |

The `conservative` point trades 36 missed defects for 9 fewer false alarms. **It is not
better or worse**; it is a different point on the same curve, and the comparison view says
so in those words.

### The board-layout input is load-bearing

| | FP | Precision |
|---|---|---|
| With layout | **3** | **0.880** |
| Without layout | 156 | 0.066 |

Without the design geometry the detector cannot tell a pad defect from missing copper and
over-reports by 52×. This is why the layout is an explicit node in the workflow rather
than hidden state inside the detector.

### Latency, split by what is being measured (ms)

| Stage | mean | median | p95 | Note |
|---|---|---|---|---|
| Inference | 48.5 | 47.9 | 54.5 | the detector itself |
| Preprocessing | 11.8 | 10.0 | 12.4 | image decode and resize |
| Harness overhead | 0.0 | 0.0 | 0.0 | graph traversal, adaptation |
| Total per image | 60.4 | 58.0 | 69.6 | everything measured |

Inference-only throughput: **~20 images/s**. Stated as inference-only because that is what
it is: disk read and preprocessing are excluded.

---

## 5. Files added and changed

### Added

| Path | Purpose |
|---|---|
| `vm_clone/evaluation/__init__.py` | Package surface |
| `vm_clone/evaluation/annotations.py` | Data models, dataset, IoU, YOLO/JSON loaders |
| `vm_clone/evaluation/matching.py` | The matching policy |
| `vm_clone/evaluation/metrics.py` | Metrics, latency, text report |
| `vm_clone/evaluation/runner.py` | Batch execution, pipeline adapter |
| `vm_clone/evaluation/experiment.py` | Records, append-only store, comparison |
| `vm_clone/samples/pcb_defect_dataset.py` | Labelled synthetic dataset generator + reference detector |
| `vm_clone/samples/pcb_defect_tool.py` | `PCB Defect Detection`, `PCB Board Layout` nodes |
| `vm_clone/ui/inspection_controller.py` | Non-Qt evaluation GUI logic |
| `vm_clone/ui/inspection_panel.py` | The five-tab inspection dock |
| `vm_clone/cli.py` | Headless runner |
| `tests/test_evaluation_core.py` | 54 tests: geometry, matching, metrics, persistence |
| `tests/test_evaluation_runner.py` | 33 tests: batch runner, records, comparison |
| `tests/test_cli_runner.py` | 35 tests: every subcommand and its failure modes |
| `tests/test_inspection_controller.py` | 35 tests: classification, filters, tables, history |
| `docs/INSPECTION_PLATFORM.md` | This document |
| 11 audit scripts | `audit_inference_*`, `audit_pipeline_evaluation`, `audit_reference_detector`, `audit_board_separation`, `audit_dark_blobs`, `audit_detector_fps`, `audit_void_vs_paste`, `capture_inspection_screens`, `validate_design_tokens` |

### Changed

| Path | Change | Reason |
|---|---|---|
| `vm_clone/tools/__init__.py` | Imports the two new nodes | Registration on the toolbox |
| `vm_clone/ui/main_window.py` | `_init_inspection_dock`, `Inspection` menu, 3 handler methods | Integration; no existing behaviour altered |
| `vm_clone/ui/vm_theme.py` | 8 scoped rules for the panel | Style the new surface from the existing tokens; the approved palette is unchanged |
| `tests/test_parameter_fuzz.py` | Hermetic working directory | **Fixed a real defect:** the fuzz test wrote ~480 PNGs into the repository root, because a hostile value reached `Image Output`'s `save_directory` and it resolved relative to the CWD |

`main_window.py` is the only existing UI file touched, and only additively: the measured
layout, the palette and every existing menu are as they were.

---

## 6. Tests

**858 tests pass, 0 fail** (658 before this work; 200 added across 4 new modules).

| Suite | Count | Covers |
|---|---|---|
| `test_evaluation_core.py` | 54 | IoU edge cases (zero-area, touching, contained, threshold boundary inclusive), all four match outcomes, duplicate handling, confidence ordering, determinism under input reordering, undefined metrics, mAP presence/absence, dataset and YOLO round-trips, malformed label files, mismatched detector output lists |
| `test_evaluation_runner.py` | 33 | Missing images, predictor that raises, wrong return type, cancellation, resize rescaling, latency buckets, record round-trip, honest model reference, append-only store, corrupt record resilience, comparison deltas and every refusal condition |
| `test_cli_runner.py` | 35 | Every subcommand, both option positions, overwrite refusal, confidence threshold effect, incomparable comparison, workflow run on a file and a directory, unreadable image with and without `--ignore-errors`, workflow without a detector, end-to-end `demo` |
| `test_inspection_controller.py` | 35 | Failure classification for all three kinds, filters composing, score filter never dropping a false negative, `n/a` rendering, latency labels, history preservation, comparison |

Plus the pre-existing 658, including the design-system and contrast suites which still pass
after the theme additions.

**The tests deliberately assert on behaviour that could have been faked.** For example
`test_run_without_layout_scores_worse` fails if the layout input stops mattering, and
`test_filter_by_score_never_drops_a_false_negative` fails if someone "simplifies" the
filter. A test that only checked the code ran would have passed on all seven bugs found
during construction.

---

## 7. Bugs found and fixed during construction

| Bug | How it surfaced | Fix |
|---|---|---|
| Fuzz test wrote ~480 PNGs into the repo root | Directories named `nan`, `abc`, `inf` appeared at the top level | `monkeypatch.chdir(tmp_path)` in the fuzz |
| `missing_cu` ground truth placed on top of pads | Per-class metrics were implausible; the confusion matrix showed the detector "wrong" about correct detections | Constrained placement away from design copper |
| Reference detector fired on the board's own weave (prec. 0.04) | Threshold sweep | Robust `max(floor, k·MAD)` on the residual instead of a fixed threshold |
| Morphological closing bridged the plane border into board-sized blobs | FP feature analysis: 478 FPs all with `fill 0.0` at `IoU 0.0` | `max_dimension` guard |
| Pad outline was a painted dark border | Blob inspection | Subtle outline, and copper rejection via the layout |
| `cv2.imread` **raises** under Ultralytics' patch instead of returning `None` | A missing-file test crashed instead of reporting | Guard the load stage for both behaviours |
| `QFont::setPointSize: Point size <= 0` on the tab bar | Qt warning on launch | Application font expressed in points, not pixels |
| **`Experiment.from_run` called `find_detector_node` without importing it** | Saving from the GUI raised `NameError` inside a modal error dialog. The CLI path never passes a pipeline, so **every test passed while the GUI could not save an experiment at all** | Import it, and add a regression test that saves *with* a pipeline |
| **`find_detector_node` selected a node with no `Detections` output** | A workflow evaluation reported a complete, error-free run with 0 TP and all-FN. `Defect Detection` reported only a defect count, so the evaluator read a non-existent output and got an empty list for every image | Require the output to exist; raise rather than return nothing |
| The classical `Defect Detection` tool had no structured output | Same run | Added `Boxes`/`Classes`/`Scores`/`Detections` alongside its existing outputs |
| The legend rendered literal `&nbsp;` entities | Screenshot inspection | Explicit rich-text format; spacing via entities, which actually render |
| Modal dialogs hung automated capture | The screenshot script blocked indefinitely | `APEX_HEADLESS_UI=1` routes informational and error dialogs to the log and status bar |

Two of these are the most instructive: **both were failures that looked like success.**
The workflow evaluation reported a clean run with zero detections, and the GUI save path
failed only in the one caller the tests did not exercise. Neither would have been caught by
checking that the code runs.

Every one of these was found by measuring rather than by assuming, and each has a test.

---

## 8. Known limitations

1. **The dataset is synthetic and not a benchmark.** Procedural texture, four simple defect
   classes, no real AOI imagery. Metrics describe this generator. The `mAP@IoU` figures are
   meaningful for ranking this detector's operating points, not for comparing against
   published PCB results.
2. **No trained PCB model exists.** `yolo11n.pt` is COCO-pretrained; a YOLO evaluation is
   wired up and would run, but would report near-zero recall on these classes.
3. **The reference detector uses the board layout.** Pad geometry is design data a real AOI
   system also has, but it means the reported accuracy is conditional on that input. The
   measurement above (156 FP without it) quantifies the dependency rather than hiding it.
4. **`missing_paste` and `void` score 1.000.** That is honest for this fixture — the two
   classes are separable by a depth threshold that is large relative to the material
   noise — but it means those columns do not stress the metric. `scratch` (F1 0.553) and
   `missing_cu` (precision 0.793) are the informative ones.
5. **Comparison supports two records at a time** in the GUI (a baseline and one
   comparison). The underlying `compare` accepts any number and the CLI takes `--latest N`.
6. **No multi-class mAP across IoU thresholds.** AP is computed at the single configured
   IoU. COCO-style `mAP@[.5:.95]` would need a threshold sweep; the machinery
   (`compute_average_precision`) is per-threshold and would extend, but it is not done.
7. **Latency is not a benchmark either.** It measures this machine, recorded in each
   record's environment block so a difference across machines is explainable.
8. **Held-out discipline is by convention, not enforcement.** A record stores the split and
   the CLI warns when a run's split differs from the dataset's declared one, but nothing
   prevents a user from evaluating on `train`. The honest-reporting rule is documented in
   §3.1 and enforced in the record, not by a permission.

---

## 9. Next highest-value task

**Train or obtain a small PCB defect model and evaluate it through this platform.**

The evaluation machinery is complete and tested; what it lacks is a *real* model to
measure. The concrete path:

1. Export this generator's dataset as YOLO label text — `save_yolo_labels` already exists
   and is tested.
2. Fine-tune `yolo11n` on it *in a separate environment*, holding out the `test` split and
   not touching it during training.
3. Evaluate the trained weights through the existing `pipeline_predictor` path with the
   `Object Detection` node — no platform code should need to change, which is the test of
   whether the abstraction is right.
4. Compare it against the classical detector on the identical held-out split.

That would produce the platform's first comparison between two genuinely different models,
and would immediately show whether the `Detections` contract really is general enough. If
platform code has to change to accommodate it, that is a finding worth having.

A second, cheaper task: add a `mAP@[.5:.95]` sweep, since `compute_average_precision` is
already per-threshold and only the aggregation is missing.
