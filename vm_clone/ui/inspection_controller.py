"""Inspection workflow controller: the non-Qt half of the evaluation GUI.

Everything the interface needs - which datasets are available, running an evaluation,
classifying its failures, loading and comparing experiments - lives here, and knows
nothing about Qt.  The panel in `inspection_panel.py` is a thin view over this, so the
interesting behaviour can be tested without a display, and the CLI and the GUI cannot
drift apart because they call the same functions.

Nothing here invents a metric.  Every number comes from `evaluation.metrics`, which is
driven by `evaluation.matching`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from vm_clone.evaluation.annotations import Dataset, Detection, ImageRecord
from vm_clone.evaluation.experiment import (
    Comparison, Experiment, ExperimentStore, compare,
)
from vm_clone.evaluation.matching import (
    DUPLICATE, FP, FN, ImageMatchResult, match_image,
)
from vm_clone.evaluation.metrics import EvaluationResult
from vm_clone.evaluation.runner import (
    RunConfig, RunOutcome, pipeline_predictor, run_dataset,
)

#: The failure categories the analysis view can filter by.
FAILURE_KINDS = (FP, FN, DUPLICATE)


@dataclass
class FailureCase:
    """One inspectable failure, with everything the view needs to show it."""
    kind: str                       # FP | FN | DUPLICATE
    reason_code: str
    reason: str
    label: str
    score: Optional[float]
    box: Tuple[float, float, float, float]
    image: str                      # the dataset-relative path, as a stable key
    image_path: str                 # absolute, for opening the original
    best_iou: float = 0.0
    nearest_label: Optional[str] = None
    #: index within the owning match result, for stable selection
    index: int = 0

    @property
    def is_prediction(self) -> bool:
        """True when the box came from the detector, False when from ground truth."""
        return self.kind in (FP, DUPLICATE)


def classify_failures(result: EvaluationResult,
                      image_paths: Optional[Dict[str, str]] = None) -> List[FailureCase]:
    """Flatten every false positive, duplicate and false negative into a list.

    Ground-truth-only failures (a missed defect) and prediction-only failures (a false
    alarm) are both included: a failed inspection is caused by either, and a view that
    showed only one would hide half the problem.
    """
    out: List[FailureCase] = []
    paths = image_paths or {}
    for match in result.per_image:
        out.extend(_cases_from(match, paths))
    # Deterministic order: by image, then by kind, then by position.
    out.sort(key=lambda c: (c.image, c.kind, c.box[1], c.box[0]))
    return out


def _cases_from(match: ImageMatchResult,
                paths: Dict[str, str]) -> List[FailureCase]:
    out: List[FailureCase] = []
    absolute = paths.get(match.image, match.image)
    for i, item in enumerate(match.false_positives):
        out.append(FailureCase(
            kind=FP, reason_code=item.reason_code, reason=item.reason,
            label=item.prediction.label, score=item.prediction.score,
            box=tuple(item.prediction.box), image=match.image, image_path=absolute,
            best_iou=item.best_iou, nearest_label=item.nearest_label, index=i))
    for i, item in enumerate(match.duplicates):
        out.append(FailureCase(
            kind=DUPLICATE, reason_code=item.reason_code, reason=item.reason,
            label=item.prediction.label, score=item.prediction.score,
            box=tuple(item.prediction.box), image=match.image, image_path=absolute,
            best_iou=item.best_iou, nearest_label=item.nearest_label, index=i))
    for i, item in enumerate(match.false_negatives):
        out.append(FailureCase(
            kind=FN, reason_code=item.reason_code, reason=item.reason,
            label=item.annotation.label, score=None,
            box=tuple(item.annotation.box), image=match.image, image_path=absolute,
            best_iou=item.best_iou, nearest_label=item.nearest_label, index=i))
    return out


def filter_failures(cases: Sequence[FailureCase],
                    kinds: Optional[Sequence[str]] = None,
                    labels: Optional[Sequence[str]] = None,
                    min_score: Optional[float] = None,
                    max_score: Optional[float] = None,
                    image: Optional[str] = None,
                    reason_codes: Optional[Sequence[str]] = None
                    ) -> List[FailureCase]:
    """Apply the analysis view's filters.

    `min_score`/`max_score` apply only to cases that have a score.  A missed defect has
    none, and excluding it because it fails a confidence filter would hide exactly the
    failures a user most needs to see - so score filters never drop a false negative.
    """
    out = list(cases)
    if kinds:
        wanted = set(kinds)
        out = [c for c in out if c.kind in wanted]
    if labels:
        wanted_labels = set(labels)
        out = [c for c in out if c.label in wanted_labels]
    if reason_codes:
        wanted_reasons = set(reason_codes)
        out = [c for c in out if c.reason_code in wanted_reasons]
    if image:
        out = [c for c in out if c.image == image]
    if min_score is not None:
        out = [c for c in out if c.score is None or c.score >= min_score]
    if max_score is not None:
        out = [c for c in out if c.score is None or c.score <= max_score]
    return out


def failure_summary(cases: Sequence[FailureCase]) -> Dict[str, Any]:
    """Counts by kind, class and reason, for the analysis view's header."""
    by_kind: Dict[str, int] = {}
    by_label: Dict[str, int] = {}
    by_reason: Dict[str, int] = {}
    for case in cases:
        by_kind[case.kind] = by_kind.get(case.kind, 0) + 1
        by_label[case.label] = by_label.get(case.label, 0) + 1
        by_reason[case.reason_code] = by_reason.get(case.reason_code, 0) + 1
    return {"total": len(cases), "by_kind": by_kind, "by_label": by_label,
            "by_reason": by_reason}


@dataclass
class InspectionController:
    """Owns the evaluation state the interface displays.

    Holds the loaded dataset, the last run outcome, the failure list and the experiment
    store, so the view can be rebuilt from this object after any change rather than
    keeping its own copy of the truth.
    """
    store_directory: str = ""
    dataset: Optional[Dataset] = None
    dataset_path: str = ""
    outcome: Optional[RunOutcome] = None
    failures: List[FailureCase] = field(default_factory=list)
    #: images that produced at least one ground-truth box, for the image filter
    annotated_images: List[str] = field(default_factory=list)
    last_error: str = ""

    # -- dataset ---------------------------------------------------------
    def load_dataset(self, path: str) -> Dataset:
        """Load an annotation file.  Raises with a usable message on failure."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"dataset not found: {path}")
        dataset = Dataset.load(path)
        if not dataset.records:
            raise ValueError(f"{os.path.basename(path)} contains no images")
        self.dataset = dataset
        self.dataset_path = path
        self.annotated_images = sorted({r.image_path for r in dataset.records
                                        if not r.is_empty})
        self.outcome = None
        self.failures = []
        self.last_error = ""
        return dataset

    def dataset_summary(self) -> Dict[str, Any]:
        if self.dataset is None:
            return {}
        counts = self.dataset.counts()
        return {
            "name": self.dataset.name,
            "path": self.dataset_path,
            "split": self.dataset.meta.get("split", "test"),
            "generator": self.dataset.meta.get("generator", ""),
            "classes": self.dataset.label_set(),
            **counts,
        }

    # -- running ---------------------------------------------------------
    def run_evaluation(self,
                       predictor: Optional[Callable] = None,
                       detector_variant: str = "reference",
                       iou_threshold: float = 0.5,
                       confidence_threshold: float = 0.0,
                       model_id: str = "",
                       pipeline=None,
                       progress: Optional[Callable[[int, int, str], None]] = None,
                       should_cancel: Optional[Callable[[], bool]] = None,
                       use_layout: bool = True) -> RunOutcome:
        """Evaluate the loaded dataset and remember the outcome.

        When `pipeline` is given, the pipeline's own execution engine supplies the
        predictions; otherwise the built-in reference detector is used.  A run with
        neither is a programming error, not an empty result, so it raises.
        """
        if self.dataset is None:
            raise RuntimeError("no dataset loaded")

        before_image = None
        if pipeline is not None:
            predictor = predictor or pipeline_predictor(pipeline)
            layout_node = _find_tool(pipeline, "PCB Board Layout")
            if layout_node is not None:
                seeds = {r.image_path: int((r.meta or {}).get("seed", 0))
                         for r in self.dataset.records}

                def before_image(record, _node=layout_node, _seeds=seeds):
                    _node.set_param("board_seed", _seeds.get(record.image_path, 0))
            kind = "pipeline"
        else:
            from vm_clone.samples.pcb_defect_dataset import (
                detections_to_records, detect_with_variant,
            )
            state: Dict[str, Any] = {"seed": None, "size": (640, 480)}

            def before_image(record):
                state["seed"] = int((record.meta or {}).get("seed", 0))
                if record.size:
                    state["size"] = (int(record.size[0]), int(record.size[1]))

            def reference_predictor(image):
                seed = state["seed"] if use_layout else None
                dets = detect_with_variant(image, detector_variant, seed=seed,
                                           size=state["size"])
                return detections_to_records(
                    dets, model_id=f"reference_pcb_detector[{detector_variant}]")

            predictor = reference_predictor
            kind = "function"

        config = RunConfig(
            dataset_name=self.dataset.name,
            split=self.dataset.meta.get("split", "test"),
            iou_threshold=float(iou_threshold),
            confidence_threshold=float(confidence_threshold),
            model_id=model_id or (f"reference_pcb_detector[{detector_variant}]"
                                  if pipeline is None else (pipeline.name or "pipeline")),
            predictor_kind=kind,
            detector_variant="" if pipeline is not None else detector_variant,
            extras={"dataset_manifest": {"path": os.path.abspath(self.dataset_path)},
                    "dataset_generator": self.dataset.meta.get("generator", ""),
                    "use_layout": bool(use_layout)})

        outcome = run_dataset(self.dataset, predictor, config, progress=progress,
                              should_cancel=should_cancel, before_image=before_image)
        self.outcome = outcome
        self.failures = classify_failures(outcome.result, outcome.image_paths)
        return outcome

    # -- results ---------------------------------------------------------
    def metrics_table(self) -> List[Tuple[str, str]]:
        """The headline metrics as display strings.  Undefined shows as 'n/a'."""
        if self.outcome is None:
            return []
        r = self.outcome.result

        def pct(value: Optional[float]) -> str:
            return "n/a" if value is None else f"{value:.4f}"

        return [
            ("Images evaluated", str(r.images_evaluated)),
            ("Empty ground truth", str(r.empty_images)),
            ("Ground-truth boxes", str(r.gt_count)),
            ("True positives", str(r.tp)),
            ("False positives", str(r.fp)),
            ("  of which duplicates", str(r.duplicates)),
            ("False negatives", str(r.fn)),
            ("Precision", pct(r.precision)),
            ("Recall", pct(r.recall)),
            ("F1", pct(r.f1)),
            (f"mAP@{r.iou_threshold}", pct(r.map50)),
            ("Errors", str(len(r.errors))),
        ]

    def per_class_rows(self) -> List[List[str]]:
        """One row per class, for the per-class table."""
        if self.outcome is None:
            return []
        rows: List[List[str]] = []
        for label, m in sorted(self.outcome.result.per_class.items()):
            def f(value: Optional[float]) -> str:
                return "n/a" if value is None else f"{value:.4f}"
            rows.append([label, str(m.gt_count), str(m.tp), str(m.fp), str(m.fn),
                         f(m.precision), f(m.recall), f(m.f1), f(m.ap)])
        return rows

    def latency_rows(self) -> List[List[str]]:
        if self.outcome is None:
            return []
        lat = self.outcome.result.latency
        rows = []
        for name, values, note in (
            ("Inference", lat.inference_ms, "the detector itself"),
            ("Preprocessing", lat.preprocessing_ms, "decode and resize"),
            ("Harness overhead", lat.overhead_ms, "graph traversal, adaptation"),
            ("Total per image", lat.total_ms, "everything measured"),
        ):
            s = lat._summary(values)
            def f(v) -> str:
                return "n/a" if v is None else f"{v:.3f}"
            rows.append([name, f(s["mean"]), f(s["median"]), f(s["p95"]), note])
        return rows

    def error_rows(self) -> List[List[str]]:
        if self.outcome is None:
            return []
        return [[e["image"], e["stage"], e["message"]]
                for e in self.outcome.result.errors]

    def available_labels(self) -> List[str]:
        return sorted({c.label for c in self.failures})

    def available_reasons(self) -> List[Tuple[str, str]]:
        """Distinct reason codes with their descriptions."""
        seen: Dict[str, str] = {}
        for case in self.failures:
            seen.setdefault(case.reason_code, case.reason)
        return sorted(seen.items())

    # -- experiments -----------------------------------------------------
    @property
    def store(self) -> ExperimentStore:
        if not self.store_directory:
            raise RuntimeError("no experiment store directory configured")
        return ExperimentStore(self.store_directory)

    def save_experiment(self, name: str = "", notes: str = "",
                        pipeline=None) -> Experiment:
        """Record the last run.  Never overwrites an existing record."""
        if self.outcome is None:
            raise RuntimeError("nothing to save: run an evaluation first")
        experiment = Experiment.from_run(
            self.outcome,
            name=name or (self.outcome.config.model_id or "evaluation"),
            pipeline=pipeline, notes=notes)
        self.store.save(experiment)
        return experiment

    def list_experiments(self) -> List[Experiment]:
        if not self.store_directory or not os.path.isdir(self.store_directory):
            return []
        return self.store.load_all()

    def compare_experiments(self, experiments: Sequence[Experiment],
                            base_index: int = 0,
                            allow_incomparable: bool = False) -> Comparison:
        return compare(experiments, base_index=base_index,
                       allow_incomparable=allow_incomparable)


def _find_tool(pipeline, tool_name: str):
    for node in (getattr(pipeline, "nodes", {}) or {}).values():
        if getattr(node, "tool_name", "") == tool_name:
            return node
    return None
