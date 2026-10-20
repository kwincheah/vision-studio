"""Detection metrics computed from matching outcomes.

Every number here is a function of the counts `matching.match_image` produced, so no
metric is defined independently of the matching policy.  The definitions used:

* ``precision = TP / (TP + FP)`` — of the boxes reported, the fraction that
  corresponded to a real defect.  Undefined with no predictions, reported as ``None``
  rather than 0.0, because "reported nothing" is not "reported nothing correctly".
* ``recall = TP / (TP + FN)`` — of the real defects, the fraction found.  Undefined on
  an image with no ground truth, which is why per-class and aggregate recall ignore
  empty images rather than counting them as perfect.
* ``f1 = 2PR / (P + R)`` — harmonic mean, ``None`` when either is undefined.
* ``mAP@IoU`` — average precision per class from the precision/recall curve, computed
  **only** when a confidence ranking is available.  It requires more than one operating
  point, so it is reported as ``None`` (not 0.0) when the detector emits a single
  confidence or none.  A deterministic detector with no confidence ordering has no
  meaningful AP, and inventing one would be a fabricated result.

Aggregates are **micro-averaged** across images (total TP/FP/FN), which is the correct
choice for an inspection line where every defect instance matters equally.  A
macro-averaged per-class table is also produced, because a rare class's recall is
invisible in the micro figure.

Latency is kept in three separate buckets so an evaluation number can never be
presented as an inference speed:

* ``inference_ms`` — the detector's own reported time,
* ``preprocessing_ms`` — decode and any resize,
* ``overhead_ms`` — everything else the harness did.

Only ``inference_ms`` is a property of the model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from vm_clone.evaluation.annotations import Annotation, Detection
from vm_clone.evaluation.matching import (
    DEFAULT_IOU_THRESHOLD, ImageMatchResult, match_image,
)


def _safe_div(num: float, den: float) -> Optional[float]:
    """Division that reports "undefined" instead of raising or returning 0."""
    if den <= 0:
        return None
    return num / den


def _f1(precision: Optional[float], recall: Optional[float]) -> Optional[float]:
    if precision is None or recall is None:
        return None
    if precision + recall <= 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


@dataclass
class ClassMetrics:
    """Counts and derived rates for one class."""
    label: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    duplicates: int = 0
    gt_count: int = 0

    @property
    def precision(self) -> Optional[float]:
        return _safe_div(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> Optional[float]:
        return _safe_div(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> Optional[float]:
        return _f1(self.precision, self.recall)

    @property
    def ap(self) -> Optional[float]:
        """Set by the aggregate when a confidence ranking exists."""
        return getattr(self, "_ap", None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label, "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "duplicates": self.duplicates, "gt_count": self.gt_count,
            "precision": _round(self.precision), "recall": _round(self.recall),
            "f1": _round(self.f1), "ap": _round(self.ap),
        }


def _round(value: Optional[float], digits: int = 6) -> Optional[float]:
    return None if value is None else round(float(value), digits)


@dataclass
class LatencyStats:
    """Timing, in milliseconds, split by what was being measured."""
    inference_ms: List[float] = field(default_factory=list)
    preprocessing_ms: List[float] = field(default_factory=list)
    overhead_ms: List[float] = field(default_factory=list)
    total_ms: List[float] = field(default_factory=list)

    @staticmethod
    def _summary(values: Sequence[float]) -> Dict[str, Optional[float]]:
        if not values:
            return {"count": 0, "mean": None, "median": None, "p95": None,
                    "min": None, "max": None, "total": None}
        ordered = sorted(values)
        n = len(ordered)
        p95_index = min(n - 1, int(math.ceil(0.95 * n)) - 1)

        def mean(seq):
            return sum(seq) / len(seq)

        return {
            "count": n,
            "mean": round(mean(ordered), 4),
            "median": round(ordered[n // 2], 4),
            "p95": round(ordered[p95_index], 4),
            "min": round(ordered[0], 4),
            "max": round(ordered[-1], 4),
            "total": round(sum(ordered), 4),
        }

    @property
    def throughput_fps(self) -> Optional[float]:
        """Images per second from the *inference* time only.

        Documented as such: the harness's preprocessing and the disk read are excluded,
        so this is a property of the model, not of the platform.
        """
        total = sum(self.inference_ms)
        if total <= 0 or not self.inference_ms:
            return None
        return round(len(self.inference_ms) / (total / 1000.0), 3)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inference": self._summary(self.inference_ms),
            "preprocessing": self._summary(self.preprocessing_ms),
            "overhead": self._summary(self.overhead_ms),
            "total": self._summary(self.total_ms),
            "inference_throughput_fps": self.throughput_fps,
            "measurement_note": (
                "throughput_fps uses inference time only, excluding image decode, "
                "preprocessing, visualisation and reporting"),
        }


@dataclass
class EvaluationResult:
    """The complete outcome of evaluating a dataset."""
    dataset_name: str = ""
    iou_threshold: float = DEFAULT_IOU_THRESHOLD
    per_image: List[ImageMatchResult] = field(default_factory=list)
    per_class: Dict[str, ClassMetrics] = field(default_factory=dict)
    latency: LatencyStats = field(default_factory=LatencyStats)
    #: images that failed to load or errored during inference
    errors: List[Dict[str, Any]] = field(default_factory=list)
    #: images whose ground truth is empty (a legitimate source of false positives)
    empty_images: int = 0
    images_evaluated: int = 0
    split: str = "test"
    meta: Dict[str, Any] = field(default_factory=dict)

    # -- aggregates ------------------------------------------------------
    @property
    def tp(self) -> int:
        return sum(r.tp for r in self.per_image)

    @property
    def fp(self) -> int:
        return sum(r.fp for r in self.per_image)

    @property
    def fn(self) -> int:
        return sum(r.fn for r in self.per_image)

    @property
    def duplicates(self) -> int:
        return sum(len(r.duplicates) for r in self.per_image)

    @property
    def gt_count(self) -> int:
        return sum(len(r.false_negatives) + len(r.pairs) for r in self.per_image)

    @property
    def precision(self) -> Optional[float]:
        return _safe_div(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> Optional[float]:
        return _safe_div(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> Optional[float]:
        return _f1(self.precision, self.recall)

    @property
    def map50(self) -> Optional[float]:
        """Mean AP at this IoU threshold, or None when no ranking is available."""
        values = [m.ap for m in self.per_class.values() if m.ap is not None]
        if not values:
            return None
        return sum(values) / len(values)

    # -- construction ----------------------------------------------------
    def add(self, image: str, annotations: Sequence[Annotation],
            predictions: Sequence[Detection], iou_threshold: Optional[float] = None
            ) -> ImageMatchResult:
        """Match one image and fold its outcome into the aggregate."""
        result = match_image(annotations, predictions,
                             iou_threshold if iou_threshold is not None
                             else self.iou_threshold, image=image)
        self.per_image.append(result)
        self.images_evaluated += 1
        if not annotations:
            self.empty_images += 1

        labels = {a.label for a in annotations} | {p.label for p in predictions}
        for label in labels:
            metrics = self.per_class.setdefault(label, ClassMetrics(label=label))
            metrics.gt_count += sum(1 for a in annotations if a.label == label)
        for pair in result.pairs:
            self.per_class[pair.prediction.label].tp += 1
        for item in result.false_positives:
            self.per_class[item.prediction.label].fp += 1
        for item in result.duplicates:
            self.per_class[item.prediction.label].fp += 1
            self.per_class[item.prediction.label].duplicates += 1
        for item in result.false_negatives:
            self.per_class[item.annotation.label].fn += 1
        return result

    def add_error(self, image: str, stage: str, message: str) -> None:
        """Record a failure explicitly instead of dropping the image silently.

        A dropped image changes the denominators, so every error is counted and
        reported; a run with errors is not presented as a clean evaluation.
        """
        self.errors.append({"image": image, "stage": stage, "message": str(message)})

    def compute_average_precision(self, record_predictions: Dict[str, List[Detection]],
                                  annotations: Dict[str, List[Annotation]]) -> None:
        """Per-class average precision from the confidence ranking.

        Uses the standard interpolated precision-recall area (all-point interpolation).
        Only called when the detector emits *varying* confidences; a constant-confidence
        detector produces a single operating point and therefore no AP, which is
        reported as None rather than a fabricated number.
        """
        for label, metrics in self.per_class.items():
            # Gather every prediction of this class across the dataset with its
            # confidence and whether it matched, by replaying the matching outcome.
            scored: List[Tuple[float, int]] = []
            total_gt = 0
            for image, anns in annotations.items():
                total_gt += sum(1 for a in anns if a.label == label)
                match = next((r for r in self.per_image if r.image == image), None)
                if match is None:
                    continue
                matched_boxes = {id(p.prediction) for p in match.pairs}
                for pred in record_predictions.get(image, []):
                    if pred.label != label:
                        continue
                    scored.append((float(pred.score), 1 if id(pred) in matched_boxes else 0))
            if total_gt == 0 or not scored:
                continue
            confidences = {score for score, _ in scored}
            if len(confidences) < 2:
                # A single operating point cannot define a curve.
                continue

            scored.sort(key=lambda t: -t[0])
            tp = fp = 0
            points: List[Tuple[float, float]] = []
            for _score, hit in scored:
                if hit:
                    tp += 1
                else:
                    fp += 1
                precision = tp / (tp + fp)
                recall = tp / total_gt
                points.append((recall, precision))

            # All-point interpolation.
            best = 0.0
            area = 0.0
            prev_recall = 0.0
            for recall, precision in reversed(points):
                best = max(best, precision)
                area += best * max(0.0, recall - prev_recall)
                prev_recall = recall
            metrics._ap = area

    # -- reporting -------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset_name,
            "split": self.split,
            "iou_threshold": self.iou_threshold,
            "images_evaluated": self.images_evaluated,
            "empty_images": self.empty_images,
            "ground_truth_boxes": self.gt_count,
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "duplicates": self.duplicates,
            "precision": _round(self.precision),
            "recall": _round(self.recall),
            "f1": _round(self.f1),
            "mAP@IoU": _round(self.map50),
            "per_class": {k: v.to_dict() for k, v in sorted(self.per_class.items())},
            "latency": self.latency.to_dict(),
            "errors": self.errors,
            "meta": self.meta,
            "metric_definitions": {
                "precision": "TP / (TP + FP); None when nothing was predicted",
                "recall": "TP / (TP + FN); None when there is no ground truth",
                "f1": "harmonic mean; None when either is undefined",
                "mAP@IoU": "all-point interpolated AP averaged over classes; None "
                           "when the detector has no confidence ranking",
                "matching": "greedy by descending confidence, one-to-one, per class, "
                            "IoU >= threshold",
            },
        }


def evaluate_records(records: Sequence[Any],
                     iou_threshold: float = DEFAULT_IOU_THRESHOLD,
                     dataset_name: str = "",
                     split: str = "test") -> EvaluationResult:
    """Evaluate records that already carry `annotations` and `predictions`.

    Convenience for tests and for the in-process path; the runner uses
    `EvaluationResult.add` directly so it can time each stage.
    """
    result = EvaluationResult(dataset_name=dataset_name, iou_threshold=iou_threshold,
                              split=split)
    ann_map: Dict[str, List[Annotation]] = {}
    pred_map: Dict[str, List[Detection]] = {}
    for record in records:
        ann_map[record.image_path] = list(record.annotations)
        pred_map[record.image_path] = list(record.predictions)
        result.add(record.image_path, record.annotations, record.predictions)
    result.compute_average_precision(pred_map, ann_map)
    return result


def render_text_report(result: EvaluationResult, width: int = 78) -> str:
    """A human-readable report.  Undefined metrics print as 'n/a', never as 0."""
    def fmt(value: Optional[float], digits: int = 4) -> str:
        return "n/a" if value is None else f"{value:.{digits}f}"

    lines: List[str] = []
    lines.append("=" * width)
    lines.append(f"INSPECTION EVALUATION  -  {result.dataset_name or '(unnamed dataset)'}")
    lines.append("=" * width)
    lines.append(f"split                  : {result.split}")
    lines.append(f"matching IoU threshold : {result.iou_threshold}")
    lines.append(f"images evaluated       : {result.images_evaluated}"
                 f"  (empty ground truth: {result.empty_images})")
    lines.append(f"ground-truth boxes     : {result.gt_count}")
    lines.append("")
    lines.append(f"true positives         : {result.tp}")
    lines.append(f"false positives        : {result.fp}"
                 f"  (of which duplicate boxes: {result.duplicates})")
    lines.append(f"false negatives        : {result.fn}")
    lines.append("")
    lines.append(f"precision              : {fmt(result.precision)}")
    lines.append(f"recall                 : {fmt(result.recall)}")
    lines.append(f"F1                     : {fmt(result.f1)}")
    lines.append(f"mAP@{result.iou_threshold:<4}             : {fmt(result.map50)}")
    if result.map50 is None:
        lines.append("    (n/a: the detector produced no confidence ranking, so no")
        lines.append("     precision-recall curve exists - this is not a score of zero)")
    lines.append("")

    if result.per_class:
        lines.append("per class:")
        lines.append(f"  {'label':<22}{'gt':>5}{'tp':>5}{'fp':>5}{'fn':>5}"
                     f"{'prec':>8}{'rec':>8}{'f1':>8}{'AP':>8}")
        for label, m in sorted(result.per_class.items()):
            lines.append(f"  {label[:20]:<22}{m.gt_count:>5}{m.tp:>5}{m.fp:>5}"
                         f"{m.fn:>5}{fmt(m.precision, 3):>8}{fmt(m.recall, 3):>8}"
                         f"{fmt(m.f1, 3):>8}{fmt(m.ap, 3):>8}")
        lines.append("")

    lat = result.latency
    inf = lat._summary(lat.inference_ms)
    pre = lat._summary(lat.preprocessing_ms)
    ovh = lat._summary(lat.overhead_ms)
    lines.append("latency (ms):")
    lines.append(f"  inference      mean {fmt(inf['mean'], 3):>9}  "
                 f"median {fmt(inf['median'], 3):>9}  p95 {fmt(inf['p95'], 3):>9}")
    lines.append(f"  preprocessing  mean {fmt(pre['mean'], 3):>9}  "
                 f"median {fmt(pre['median'], 3):>9}  p95 {fmt(pre['p95'], 3):>9}")
    lines.append(f"  harness        mean {fmt(ovh['mean'], 3):>9}  "
                 f"median {fmt(ovh['median'], 3):>9}  p95 {fmt(ovh['p95'], 3):>9}")
    lines.append(f"  inference-only throughput: {fmt(lat.throughput_fps, 2)} images/s")
    lines.append("    (excludes decode, preprocessing, visualisation and reporting)")
    lines.append("")

    if result.errors:
        lines.append(f"ERRORS ({len(result.errors)}):")
        for err in result.errors[:12]:
            lines.append(f"  {err['stage']:<12} {err['image'][:40]:<42} "
                         f"{err['message'][:40]}")
        if len(result.errors) > 12:
            lines.append(f"  ... {len(result.errors) - 12} more")
        lines.append("  NOTE: images that errored are excluded from the counts above,")
        lines.append("        so the metric denominators are smaller than the dataset.")
        lines.append("")

    lines.append("A match means a box overlapped ground truth above the IoU threshold")
    lines.append("with the same class. It is not evidence that the detection is correct.")
    lines.append("=" * width)
    return "\n".join(lines)
