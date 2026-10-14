"""Headless command-line runner for inspection workflows and datasets.

Runs the same execution engine the GUI uses (`VisionPipeline.execute_flow` through
`evaluation.runner.pipeline_predictor`), so a result obtained on the command line is the
same result the interface would show.  There is no second implementation of node
execution.

Subcommands
-----------
``run``        execute a saved workflow on one image or a directory, print or save results
``evaluate``   evaluate a workflow, or the built-in reference detector, over a dataset
``compare``    compare two or more saved experiment records
``list``       list saved experiments
``dataset``    build or describe a labelled dataset
``demo``       generate a dataset and run the whole evaluation end to end

Exit status
-----------
0 on success, 1 on a handled failure (a missing file, a failed run, no detector in the
workflow), 2 on a usage error.  The status is meaningful so the runner can be scripted.

Logging goes to stderr and results to stdout, so `apex-vision ... > results.json` produces
a clean file while progress is still visible.

Examples
--------
    python -m vm_clone.cli dataset --out ./data/pcb --count 40
    python -m vm_clone.cli evaluate --dataset ./data/pcb --detector reference \\
        --out-json ./experiments/run1.json --report
    python -m vm_clone.cli evaluate --workflow ./projects/pcb.vmflow \\
        --dataset ./data/pcb --save-experiment ./experiments
    python -m vm_clone.cli compare --store ./experiments --latest 2
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("vm_clone.cli")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _configure_logging(verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)
    logging.basicConfig(stream=sys.stderr, level=level,
                        format="%(levelname)-7s %(name)s: %(message)s")


def _fail(message: str, code: int = 1) -> int:
    LOG.error(message)
    return code


def _reference_predictor(variant: str, with_layout: bool):
    """The built-in deterministic detector, as a predictor callable."""
    from vm_clone.samples.pcb_defect_dataset import (
        board_layout, detections_to_records, detect_with_variant, trace_boxes,
    )

    # The dataset generator gives each board a seed; the CLI reads it from the record so
    # the layout matches the board.  When no seed is available the detector still runs,
    # without the copper mask.
    state: Dict[str, Any] = {"seed": None, "size": (640, 480)}

    def before_image(record):
        state["seed"] = int((record.meta or {}).get("seed", 0))
        if record.size:
            state["size"] = (int(record.size[0]), int(record.size[1]))

    def predict(image):
        seed = state["seed"] if with_layout else None
        dets = detect_with_variant(image, variant, seed=seed, size=state["size"])
        return detections_to_records(dets, model_id=f"reference_pcb_detector[{variant}]")

    return predict, before_image


def _load_workflow(path: str):
    """Load a saved workflow/solution and return a pipeline plus a description."""
    from vm_clone.core.pipeline import SolutionManager, VisionPipeline

    if not os.path.isfile(path):
        raise FileNotFoundError(f"workflow file not found: {path}")

    # A file may be a single flow or a solution containing several.
    try:
        pipe = VisionPipeline.import_from_file(path)
        return pipe, os.path.basename(path)
    except Exception:                                   # noqa: BLE001 - try solution form
        pass
    try:
        solution = SolutionManager.load_from_file(path)
    except Exception as exc:                            # noqa: BLE001
        raise ValueError(f"could not load {path} as a flow or a solution: "
                         f"{type(exc).__name__}: {exc}") from exc

    pipe = solution.get_active_flow()
    if pipe is None:
        raise ValueError(f"{path} contains no flow")
    return pipe, f"{os.path.basename(path)}:{getattr(pipe, 'name', 'flow')}"


def _write_json(path: str, payload: Any) -> None:
    from vm_clone.core.fileio import atomic_write_json

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    atomic_write_json(path, payload)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
def cmd_run(args) -> int:
    """Execute a workflow on an image or a directory of images."""
    from vm_clone.evaluation import pipeline_predictor

    try:
        pipe, label = _load_workflow(args.workflow)
    except (FileNotFoundError, ValueError) as exc:
        return _fail(str(exc))

    try:
        predictor = pipeline_predictor(pipe)
    except ValueError as exc:
        return _fail(f"{label}: {exc}")

    targets: List[str] = []
    if os.path.isdir(args.input):
        for name in sorted(os.listdir(args.input)):
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")):
                targets.append(os.path.join(args.input, name))
    elif os.path.isfile(args.input):
        targets.append(args.input)
    else:
        return _fail(f"input not found: {args.input}")

    if not targets:
        return _fail(f"no images found in {args.input}")

    import cv2

    records: List[Dict[str, Any]] = []
    failures = 0
    for path in targets:
        image = cv2.imread(path)
        if image is None:
            LOG.error("could not read %s", path)
            failures += 1
            records.append({"image": path, "status": "error",
                            "message": "unreadable image"})
            continue
        try:
            dets = predictor(image)
            dets = dets[0] if isinstance(dets, tuple) else dets
        except Exception as exc:                        # noqa: BLE001 - reported
            LOG.error("%s: %s: %s", os.path.basename(path), type(exc).__name__, exc)
            failures += 1
            records.append({"image": path, "status": "error",
                            "message": f"{type(exc).__name__}: {exc}"})
            continue
        records.append({
            "image": path, "status": "ok", "count": len(dets),
            "detections": [d.to_dict() for d in dets],
        })

    ok = sum(1 for r in records if r["status"] == "ok")
    payload = {"workflow": label, "images": len(targets), "succeeded": ok,
               "failed": failures, "results": records}
    if args.out_json:
        _write_json(args.out_json, payload)
        LOG.info("wrote %s", args.out_json)
    else:
        print(json.dumps(payload, indent=2))

    if failures and not args.ignore_errors:
        return _fail(f"{failures} of {len(targets)} image(s) failed", 1)
    LOG.info("ran %s on %d image(s): %d ok, %d failed", label, len(targets), ok, failures)
    return 0


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------
def cmd_evaluate(args) -> int:
    """Evaluate a detector over a labelled dataset and record the experiment."""
    from vm_clone.evaluation import (
        Dataset, Experiment, ExperimentStore, RunConfig, pipeline_predictor,
        render_text_report, run_dataset,
    )

    if not os.path.exists(args.dataset):
        return _fail(f"dataset not found: {args.dataset}")

    try:
        dataset = Dataset.load(args.dataset)
    except Exception as exc:                            # noqa: BLE001 - reported
        return _fail(f"could not load dataset {args.dataset}: "
                     f"{type(exc).__name__}: {exc}")

    if not dataset.records:
        return _fail(f"dataset {args.dataset} contains no images")

    # A split other than 'test' must be requested explicitly, because metrics computed on
    # training data are not evidence about generalisation.
    split = args.split or dataset.meta.get("split", "test")
    if dataset.meta.get("split") and split != dataset.meta.get("split"):
        LOG.warning("dataset declares split '%s' but '%s' was requested; the record "
                    "will say so", dataset.meta.get("split"), split)

    pipeline = None
    before_image = None
    if args.workflow:
        try:
            pipeline, label = _load_workflow(args.workflow)
            predictor = pipeline_predictor(pipeline)
            model_id = args.model or label
            kind = "pipeline"
        except (FileNotFoundError, ValueError) as exc:
            return _fail(str(exc))
    else:
        predictor, before_image = _reference_predictor(args.detector, not args.no_layout)
        model_id = args.model or f"reference_pcb_detector[{args.detector}]"
        kind = "function"

    config = RunConfig(
        dataset_name=dataset.name,
        split=split,
        iou_threshold=float(args.iou),
        confidence_threshold=float(args.confidence),
        working_size=tuple(args.working_size) if args.working_size else None,
        model_id=model_id,
        predictor_kind=kind,
        detector_variant="" if args.workflow else args.detector,
        extras={"dataset_manifest": {"path": os.path.abspath(args.dataset),
                                     "count": len(dataset.records)},
                "dataset_generator": dataset.meta.get("generator", "")},
    )

    def progress(index: int, total: int, path: str) -> None:
        if args.quiet or not total:
            return
        if index % max(1, total // 10) == 0 or index == total:
            LOG.info("  %d/%d", index, total)

    outcome = run_dataset(dataset, predictor, config, progress=progress,
                          before_image=before_image)

    if args.report:
        print(render_text_report(outcome.result))

    if args.out_json:
        _write_json(args.out_json, outcome.result.to_dict())
        LOG.info("wrote %s", args.out_json)

    if args.save_experiment:
        experiment = Experiment.from_run(outcome, name=args.name or model_id,
                                         pipeline=pipeline, notes=args.notes or "")
        store = ExperimentStore(args.save_experiment)
        path = store.save(experiment)
        LOG.info("saved experiment %s", path)
        if not args.report and not args.out_json:
            print(json.dumps({"experiment": path, "metrics": experiment.metrics},
                             indent=2)[:4000])

    if not args.report and not args.out_json and not args.save_experiment:
        # Nothing was asked for explicitly: print a compact summary.
        r = outcome.result
        print(json.dumps({
            "dataset": r.dataset_name, "split": r.split, "iou": r.iou_threshold,
            "images": r.images_evaluated, "tp": r.tp, "fp": r.fp, "fn": r.fn,
            "precision": r.precision, "recall": r.recall, "f1": r.f1,
            "mAP": r.map50, "errors": len(r.errors),
        }, indent=2))

    r = outcome.result
    if r.images_evaluated == 0:
        return _fail("every image failed; see the error list above", 1)
    if r.errors and args.fail_on_error:
        return _fail(f"{len(r.errors)} image(s) errored during the run", 1)
    return 0


# ---------------------------------------------------------------------------
# compare / list
# ---------------------------------------------------------------------------
def cmd_compare(args) -> int:
    from vm_clone.evaluation import (
        ExperimentStore, IncomparableExperiments, compare, render_comparison,
    )

    store = ExperimentStore(args.store)
    available = store.load_all()
    if len(available) < 2:
        return _fail(f"need at least two experiments in {args.store}; "
                     f"found {len(available)}")

    if args.latest:
        chosen = available[-args.latest:]
    elif args.names:
        chosen = []
        for needle in args.names:
            matches = store.find(needle)
            if not matches:
                return _fail(f"no experiment matching {needle!r}")
            chosen.append(matches[-1])
    else:
        chosen = available[-2:]

    try:
        comparison = compare(chosen, base_index=0,
                             allow_incomparable=args.allow_incomparable)
    except IncomparableExperiments as exc:
        return _fail(f"cannot compare: {exc}\n"
                     f"pass --allow-incomparable to see it anyway, with a warning")

    if args.out_json:
        _write_json(args.out_json, comparison.to_dict())
        LOG.info("wrote %s", args.out_json)
    else:
        print(render_comparison(comparison))
    return 0


def cmd_list(args) -> int:
    from vm_clone.evaluation import ExperimentStore

    store = ExperimentStore(args.store)
    entries = store.list_records()
    if not entries:
        print(f"no experiments in {args.store}")
        return 0
    if args.json:
        print(json.dumps(entries, indent=2))
        return 0
    print(f"{'timestamp':<20}{'name':<28}{'dataset':<18}{'P':>8}{'R':>8}{'F1':>8}"
          f"{'FP':>6}{'FN':>6}")
    for e in entries:
        def f(v):
            return "   n/a" if v is None else f"{v:.4f}"
        print(f"{e['timestamp'][:19]:<20}{str(e['name'])[:26]:<28}"
              f"{str(e['dataset'])[:16]:<18}{f(e['precision']):>8}{f(e['recall']):>8}"
              f"{f(e['f1']):>8}{e['fp']:>6}{e['fn']:>6}")
    return 0


# ---------------------------------------------------------------------------
# dataset
# ---------------------------------------------------------------------------
def cmd_dataset(args) -> int:
    from vm_clone.evaluation import Dataset
    from vm_clone.samples.pcb_defect_dataset import build_dataset

    if os.path.exists(args.out) and not args.force:
        return _fail(f"{args.out} already exists; pass --force to overwrite")
    if args.out and os.path.isdir(args.out) and args.force:
        import shutil
        shutil.rmtree(args.out)

    ds = build_dataset(args.out, name=args.name, count=args.count, seed=args.seed,
                       size=(args.width, args.height), split=args.split,
                       clean_ratio=args.clean_ratio)
    counts = ds.counts()
    print(json.dumps({"dataset": ds.name, "path": os.path.abspath(args.out),
                      "generator": ds.meta.get("generator"), **counts,
                      "classes": ds.label_set(), "split": ds.meta.get("split")},
                     indent=2))
    LOG.info("wrote %d images and annotations.json to %s", counts["images"], args.out)
    return 0


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------
def cmd_demo(args) -> int:
    """Generate a dataset, evaluate two operating points, and compare them.

    The end-to-end path a new user takes, in one command, so the platform can be verified
    without the GUI.
    """
    import tempfile

    from vm_clone.evaluation import (
        Experiment, ExperimentStore, RunConfig, compare, render_comparison,
        render_text_report, run_dataset,
    )
    from vm_clone.samples.pcb_defect_dataset import build_dataset

    workdir = args.workdir or tempfile.mkdtemp(prefix="apex_demo_")
    os.makedirs(workdir, exist_ok=True)
    data_dir = os.path.join(workdir, "dataset")
    if not os.path.exists(os.path.join(data_dir, "annotations.json")) or args.force:
        if os.path.isdir(data_dir):
            import shutil
            shutil.rmtree(data_dir)
        LOG.info("generating %d boards in %s", args.count, data_dir)
        build_dataset(data_dir, count=args.count, seed=args.seed)
    ds = __import__("vm_clone.evaluation", fromlist=["Dataset"]).Dataset.load(
        os.path.join(data_dir, "annotations.json"))
    print(f"dataset: {ds.name}  {ds.counts()}\n")

    store = ExperimentStore(os.path.join(workdir, "experiments"))
    experiments = []
    for variant in ("reference", "conservative"):
        predictor, before_image = _reference_predictor(variant, with_layout=True)
        config = RunConfig(dataset_name=ds.name, split="test",
                           iou_threshold=args.iou, model_id=f"pcb_ref[{variant}]",
                           detector_variant=variant,
                           extras={"dataset_generator": ds.meta.get("generator", "")})
        outcome = run_dataset(ds, predictor, config, before_image=before_image)
        if args.report:
            print(render_text_report(outcome.result))
        exp = Experiment.from_run(outcome, name=f"{variant} operating point")
        experiments.append(exp)
        store.save(exp)

    print(render_comparison(compare(experiments)))
    print(f"\nartifacts under {workdir}")
    print(f"   dataset     {data_dir}")
    print(f"   experiments {store.directory}")
    return 0


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    # `--verbose`/`--quiet` are added to each **subcommand** rather than to the parent,
    # because argparse stores a parent's value and then a subparser's default overwrites
    # it - so declaring them in both places silently loses the parent's flag.  They are
    # therefore accepted after the subcommand (`cli evaluate --verbose ...`), which is
    # the position that actually works.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--verbose", action="store_true", help="debug logging")
    common.add_argument("--quiet", action="store_true",
                        help="warnings and errors only")

    parser = argparse.ArgumentParser(
        prog="apex-vision",
        description="Headless inspection workflow runner and dataset evaluation. "
                    "Uses the same execution engine as the GUI. "
                    "Place --verbose/--quiet after the subcommand.")
    sub = parser.add_subparsers(dest="command", required=True)

    def child(name: str, **kwargs):
        return sub.add_parser(name, parents=[common], **kwargs)

    # run ------------------------------------------------------------------
    p = child("run", help="execute a workflow on an image or a directory")
    p.add_argument("--workflow", required=True, help="saved .vmflow or project file")
    p.add_argument("--input", required=True, help="image file or directory")
    p.add_argument("--out-json", help="write results here instead of stdout")
    p.add_argument("--ignore-errors", action="store_true",
                   help="exit 0 even if some images failed")
    p.set_defaults(func=cmd_run)

    # evaluate -------------------------------------------------------------
    p = child("evaluate", help="evaluate a detector over a labelled dataset")
    p.add_argument("--dataset", required=True, help="annotations.json to evaluate")
    p.add_argument("--workflow", help="saved workflow; omit to use the reference detector")
    p.add_argument("--detector", default="reference",
                   choices=("reference", "conservative"),
                   help="built-in detector operating point")
    p.add_argument("--no-layout", action="store_true",
                   help="do not supply the board design layout to the detector")
    p.add_argument("--model", help="model identifier to record")
    p.add_argument("--iou", type=float, default=0.5,
                   help="matching IoU threshold (default 0.5)")
    p.add_argument("--confidence", type=float, default=0.0,
                   help="confidence threshold applied to predictions")
    p.add_argument("--working-size", type=int, nargs=2, metavar=("W", "H"),
                   help="resize images to this size before inference")
    p.add_argument("--split", help="dataset split label (default: the dataset's own)")
    p.add_argument("--report", action="store_true", help="print the text report")
    p.add_argument("--out-json", help="write the metric payload here")
    p.add_argument("--save-experiment", help="experiment store directory")
    p.add_argument("--name", help="experiment name")
    p.add_argument("--notes", help="free-form note recorded with the experiment")
    p.add_argument("--fail-on-error", action="store_true",
                   help="exit non-zero if any image errored")
    p.set_defaults(func=cmd_evaluate)

    # compare --------------------------------------------------------------
    p = child("compare", help="compare saved experiments")
    p.add_argument("--store", required=True, help="experiment store directory")
    p.add_argument("--latest", type=int, help="compare the N most recent")
    p.add_argument("--names", nargs="*", help="substrings identifying experiments")
    p.add_argument("--allow-incomparable", action="store_true",
                   help="compare anyway, with a warning")
    p.add_argument("--out-json", help="write the comparison here")
    p.set_defaults(func=cmd_compare)

    # list -----------------------------------------------------------------
    p = child("list", help="list saved experiments")
    p.add_argument("--store", required=True, help="experiment store directory")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    # dataset --------------------------------------------------------------
    p = child("dataset", help="build a labelled dataset")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--name", default="pcb_defect_synth")
    p.add_argument("--count", type=int, default=40, help="number of boards")
    p.add_argument("--seed", type=int, default=20230510)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--split", default="test", choices=("train", "val", "test"))
    p.add_argument("--clean-ratio", type=float, default=0.18,
                   help="fraction of boards with no defects")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_dataset)

    # demo -----------------------------------------------------------------
    p = child("demo", help="generate a dataset and evaluate it end to end")
    p.add_argument("--workdir", help="where to put the dataset and experiments")
    p.add_argument("--count", type=int, default=40)
    p.add_argument("--seed", type=int, default=20230510)
    p.add_argument("--iou", type=float, default=0.5)
    p.add_argument("--report", action="store_true", help="print both text reports")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_demo)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False), getattr(args, "quiet", False))

    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        LOG.warning("interrupted")
        return 130
    except Exception as exc:                            # noqa: BLE001 - top-level guard
        LOG.exception("unhandled error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
