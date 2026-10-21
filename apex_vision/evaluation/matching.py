"""Prediction-to-ground-truth matching.

Every metric in this package is derived from the outcome of this module, so the policy
is stated explicitly and implemented once.

Matching policy
---------------
Greedy, confidence-ordered, one-to-one, per (image, class):

1. Predictions are sorted by descending confidence; ties broken by descending area,
   then by position, so the result is **deterministic** for a given input.
2. Each prediction is matched to the unmatched ground truth with which it has the
   highest IoU, provided that IoU is **>= the configured threshold** (default 0.50).
3. A ground truth may be claimed by at most one prediction, and vice versa.
4. A prediction whose label does not equal the ground truth's label is never matched,
   regardless of IoU.  Class confusion is therefore a false positive *and* a false
   negative, which is the honest accounting for a defect-inspection system.

Why greedy and not Hungarian
----------------------------
Greedy-by-confidence is the COCO evaluation convention and is what a line operator
expects: the most confident box wins the object.  An optimal assignment can produce a
higher score by matching a low-confidence box to a ground truth that a high-confidence
box overlapped, which is not how the detector would be used.  At the default threshold
the two agree on all but pathological overlaps, and both are deterministic.  The
trade-off is documented rather than hidden.

What a match does *not* mean
----------------------------
A match says two boxes overlap enough and share a label.  It is **not** evidence that
the detection is correct, that the defect is the one a human would name, or that a
confidence score is meaningful.  Nothing in this module reads `score` except to order
the greedy pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from apex_vision.evaluation.annotations import (
    Annotation, Detection, box_area, iou,
)

#: IoU at or above which a prediction may claim a ground truth.  The COCO convention
#: for a single-operating-point report, and the value recorded in every experiment.
DEFAULT_IOU_THRESHOLD = 0.50

#: Evaluation classes, in increasing severity of the failure they describe.
TP = "TP"   # matched a ground truth
FP = "FP"   # a prediction with no ground truth of the same class
FN = "FN"   # a ground truth no prediction claimed
DUPLICATE = "DUPLICATE"   # an extra prediction overlapping an already-claimed object

#: Why a prediction or an annotation was not matched.
REASONS = {
    "no_overlap": "no ground truth of this class overlaps the box",
    "below_iou": "best overlap was below the IoU threshold",
    "already_claimed": "the overlapping ground truth was claimed by a "
                       "higher-confidence prediction",
    "class_mismatch": "a box overlaps but with a different class",
    "no_prediction": "no prediction of this class overlaps the annotation",
    "unmatched": "not matched",
}


@dataclass
class MatchedPair:
    """A prediction that claimed a ground truth."""
    prediction: Detection
    annotation: Annotation
    iou: float


@dataclass
class UnmatchedPrediction:
    """A prediction that claimed nothing."""
    prediction: Detection
    kind: str                      # FP or DUPLICATE
    reason: str                    # human-readable explanation
    #: stable machine-readable reason, so a report and a test agree on the wording
    reason_code: str = ""
    best_iou: float = 0.0
    #: the class of the nearest ground truth, when the failure was a class mismatch
    nearest_label: Optional[str] = None
    #: index of the claimed ground truth for a DUPLICATE, else None
    claimed_index: Optional[int] = None


@dataclass
class UnmatchedAnnotation:
    """A ground truth that nothing claimed."""
    annotation: Annotation
    reason: str
    reason_code: str = ""
    best_iou: float = 0.0
    nearest_label: Optional[str] = None


@dataclass
class ImageMatchResult:
    """Everything matching produced for one image."""
    image: str
    iou_threshold: float
    pairs: List[MatchedPair] = field(default_factory=list)
    false_positives: List[UnmatchedPrediction] = field(default_factory=list)
    false_negatives: List[UnmatchedAnnotation] = field(default_factory=list)
    duplicates: List[UnmatchedPrediction] = field(default_factory=list)
    #: annotations that were matched, for reporting per-class recall
    matched_annotation_indices: List[int] = field(default_factory=list)

    @property
    def tp(self) -> int:
        return len(self.pairs)

    @property
    def fp(self) -> int:
        return len(self.false_positives) + len(self.duplicates)

    @property
    def fn(self) -> int:
        return len(self.false_negatives)

    def failures(self) -> List[Dict[str, object]]:
        """A flat, exportable list of every non-match, for failure analysis."""
        out: List[Dict[str, object]] = []
        for item in self.false_positives:
            out.append({"kind": FP, "reason_code": item.reason_code,
                        "reason": item.reason, "iou": item.best_iou,
                        "label": item.prediction.label,
                        "score": item.prediction.score,
                        "box": list(item.prediction.box),
                        "nearest_label": item.nearest_label})
        for item in self.duplicates:
            out.append({"kind": DUPLICATE, "reason_code": item.reason_code,
                        "reason": item.reason, "iou": item.best_iou,
                        "label": item.prediction.label,
                        "score": item.prediction.score,
                        "box": list(item.prediction.box),
                        "nearest_label": item.nearest_label})
        for item in self.false_negatives:
            out.append({"kind": FN, "reason_code": item.reason_code,
                        "reason": item.reason, "iou": item.best_iou,
                        "label": item.annotation.label, "score": None,
                        "box": list(item.annotation.box),
                        "nearest_label": item.nearest_label})
        return out

    def to_dict(self) -> Dict[str, object]:
        return {
            "image": self.image,
            "iou_threshold": self.iou_threshold,
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "duplicates": len(self.duplicates),
            "matches": [
                {"label": p.prediction.label, "score": p.prediction.score,
                 "iou": round(p.iou, 4),
                 "prediction_box": list(p.prediction.box),
                 "annotation_box": list(p.annotation.box)}
                for p in self.pairs
            ],
            "failures": self.failures(),
        }


def _sort_key(det: Detection) -> Tuple[float, float, float, float]:
    """Deterministic ordering: confidence desc, area desc, then position."""
    return (-float(det.score), -box_area(det.box), float(det.box[0]), float(det.box[1]))


def match_image(annotations: Sequence[Annotation],
                predictions: Sequence[Detection],
                iou_threshold: float = DEFAULT_IOU_THRESHOLD,
                image: str = "") -> ImageMatchResult:
    """Match one image's predictions against its ground truth.

    ``iou_threshold`` is the minimum overlap for a match.  A threshold of 1.0 means
    only an exact box counts; 0.0 would match any overlap, which is why it is allowed
    but recorded in the result so a report can never hide a degenerate setting.
    """
    threshold = float(iou_threshold)
    result = ImageMatchResult(image=image, iou_threshold=threshold)

    # Per-class candidate ground truths.  Kept as (index, annotation) so a match can be
    # reported against the original annotation without a lookup by value.
    by_class: Dict[str, List[Tuple[int, Annotation]]] = {}
    for idx, ann in enumerate(annotations):
        by_class.setdefault(ann.label, []).append((idx, ann))

    claimed: Dict[int, int] = {}          # annotation index -> prediction order
    ordered = sorted(enumerate(predictions), key=lambda t: _sort_key(t[1]))

    for pred_order, pred in ordered:
        candidates = by_class.get(pred.label) or []

        best_idx, best_iou, best_label = None, 0.0, None
        # Nearest ground truth of *any* class, for diagnosing a mismatch.
        nearest_any_idx, nearest_any_iou = None, 0.0
        for idx, ann in enumerate(annotations):
            value = iou(pred.box, ann.box)
            if value > nearest_any_iou:
                nearest_any_idx, nearest_any_iou = idx, value

        for idx, ann in candidates:
            if idx in claimed:
                continue
            value = iou(pred.box, ann.box)
            if value > best_iou:
                best_idx, best_iou, best_label = idx, value, ann.label

        if best_idx is not None and best_iou >= threshold and best_iou > 0.0:
            claimed[best_idx] = pred_order
            result.pairs.append(MatchedPair(prediction=pred,
                                            annotation=annotations[best_idx],
                                            iou=best_iou))
            continue

        # Not matched: classify the reason.
        claimed_by_other = None
        for idx, ann in candidates:
            if idx in claimed and iou(pred.box, ann.box) >= threshold:
                claimed_by_other = idx
                break

        if claimed_by_other is not None:
            kind = DUPLICATE
            reason_code = "already_claimed"
            evidence = max(iou(pred.box, a.box) for _, a in candidates)
        elif best_idx is not None and 0.0 < best_iou < threshold:
            kind = FP
            reason_code = "below_iou"
            evidence = best_iou
        elif nearest_any_iou > 0.0 and nearest_any_idx is not None \
                and annotations[nearest_any_idx].label != pred.label:
            kind = FP
            reason_code = "class_mismatch"
            evidence = nearest_any_iou
        else:
            kind = FP
            reason_code = "no_overlap"
            evidence = nearest_any_iou

        item = UnmatchedPrediction(
            prediction=pred, kind=kind, reason=REASONS[reason_code],
            reason_code=reason_code, best_iou=round(evidence, 4),
            nearest_label=(annotations[nearest_any_idx].label
                           if nearest_any_idx is not None else best_label),
            claimed_index=claimed_by_other)
        if kind == DUPLICATE:
            result.duplicates.append(item)
        else:
            result.false_positives.append(item)

    # Ground truth nothing claimed.
    for idx, ann in enumerate(annotations):
        if idx in claimed:
            result.matched_annotation_indices.append(idx)
            continue
        best, nearest_label = 0.0, None
        for pred in predictions:
            value = iou(pred.box, ann.box)
            if value > best:
                best, nearest_label = value, pred.label
        if best <= 0.0:
            reason_code = "no_prediction"
        elif nearest_label != ann.label:
            reason_code = "class_mismatch"
        else:
            reason_code = "below_iou"
        result.false_negatives.append(UnmatchedAnnotation(
            annotation=ann, reason=REASONS[reason_code], reason_code=reason_code,
            best_iou=round(best, 4), nearest_label=nearest_label))

    return result
