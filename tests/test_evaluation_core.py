"""Tests for annotation models, matching and metrics.

Matching is the correctness-critical part of the evaluation platform: every reported
number is derived from it, so the policy is tested against hand-computed cases rather
than against itself.

Matching policy under test:
  greedy, confidence-ordered, one-to-one, per class, IoU >= threshold.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apex_vision.evaluation import (  # noqa: E402
    Annotation, Dataset, Detection, ImageRecord, box_area, detections_from_outputs,
    evaluate_records, iou, load_yolo_labels, render_text_report, save_yolo_labels,
)
from apex_vision.evaluation.matching import (  # noqa: E402
    DUPLICATE, FP, FN, DEFAULT_IOU_THRESHOLD, match_image,
)
from apex_vision.evaluation.metrics import EvaluationResult  # noqa: E402


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def test_iou_of_identical_boxes_is_one():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)


def test_iou_of_disjoint_boxes_is_zero():
    assert iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0


def test_iou_half_overlap():
    """Two 10x10 boxes sharing half their area: inter 50, union 150."""
    assert iou((0, 0, 10, 10), (5, 0, 10, 10)) == pytest.approx(50 / 150, abs=1e-9)


def test_iou_contained_box():
    """A 5x5 inside a 10x10: inter 25, union 100."""
    assert iou((0, 0, 10, 10), (2, 2, 5, 5)) == pytest.approx(25 / 100, abs=1e-9)


def test_iou_touching_edges_is_zero():
    """Boxes that share an edge but no area must not match."""
    assert iou((0, 0, 10, 10), (10, 0, 10, 10)) == 0.0


@pytest.mark.parametrize("degenerate", [(0, 0, 0, 0), (5, 5, 0, 10), (5, 5, 10, 0),
                                        (0, 0, -5, -5)])
def test_iou_with_a_zero_area_box_is_zero(degenerate):
    assert iou((0, 0, 10, 10), degenerate) == 0.0
    assert iou(degenerate, (0, 0, 10, 10)) == 0.0


def test_box_area_never_negative():
    assert box_area((0, 0, -5, -5)) == 0.0
    assert box_area((0, 0, 4, 5)) == 20.0


# ---------------------------------------------------------------------------
# Matching: the four outcomes
# ---------------------------------------------------------------------------
def test_perfect_match():
    anns = [Annotation((0, 0, 10, 10), "scratch")]
    preds = [Detection((0, 0, 10, 10), "scratch", 0.9)]
    r = match_image(anns, preds)
    assert r.tp == 1 and r.fp == 0 and r.fn == 0
    assert r.pairs[0].iou == pytest.approx(1.0)


def test_missed_defect_is_a_false_negative():
    anns = [Annotation((0, 0, 10, 10), "scratch")]
    r = match_image(anns, [])
    assert r.tp == 0 and r.fp == 0 and r.fn == 1
    assert r.false_negatives[0].reason_code == "no_prediction"


def test_spurious_detection_is_a_false_positive():
    preds = [Detection((50, 50, 10, 10), "scratch", 0.8)]
    r = match_image([], preds)
    assert r.tp == 0 and r.fp == 1 and r.fn == 0
    assert r.false_positives[0].reason_code == "no_overlap"


def test_class_mismatch_is_both_a_fp_and_an_fn():
    """Confusing one defect for another is not a detection."""
    anns = [Annotation((0, 0, 10, 10), "scratch")]
    preds = [Detection((0, 0, 10, 10), "void", 0.9)]
    r = match_image(anns, preds)
    assert r.tp == 0
    assert r.fp == 1 and r.false_positives[0].reason_code == "class_mismatch"
    assert r.fn == 1 and r.false_negatives[0].reason_code == "class_mismatch"
    assert r.false_positives[0].nearest_label == "scratch"


# ---------------------------------------------------------------------------
# Threshold behaviour
# ---------------------------------------------------------------------------
def test_overlap_below_the_threshold_does_not_match():
    """IoU 0.5 exactly is the default boundary; just under must fail."""
    anns = [Annotation((0, 0, 10, 10), "scratch")]
    # shift by 1px -> inter 90, union 110 -> IoU 0.818 (matches)
    assert match_image(anns, [Detection((1, 0, 10, 10), "scratch", 0.9)]).tp == 1
    # make the overlap small: inter 10, union 190 -> IoU 0.0526 (no match)
    r = match_image(anns, [Detection((9, 0, 10, 10), "scratch", 0.9)])
    assert r.tp == 0 and r.fp == 1 and r.fn == 1
    assert r.false_positives[0].reason_code == "below_iou"


def test_threshold_is_inclusive_at_the_boundary():
    """IoU exactly equal to the threshold must match."""
    anns = [Annotation((0, 0, 10, 10), "scratch")]
    # candidate: inter 50, union 150 -> exactly 1/3
    r_loose = match_image(anns, [Detection((5, 0, 10, 10), "scratch", 0.9)],
                          iou_threshold=1 / 3)
    assert r_loose.tp == 1
    r_tight = match_image(anns, [Detection((5, 0, 10, 10), "scratch", 0.9)],
                          iou_threshold=0.34)
    assert r_tight.tp == 0


@pytest.mark.parametrize("threshold,expected_tp", [
    (0.3, 1), (0.4, 1), (0.5, 1), (0.6, 0), (0.9, 0), (1.0, 0),
])
def test_threshold_sweep_on_a_known_iou(threshold, expected_tp):
    """Two boxes with IoU ~0.473 must match only below that threshold."""
    anns = [Annotation((0, 0, 20, 20), "void")]
    preds = [Detection((3, 3, 20, 20), "void", 0.9)]
    # inter 17*17=289, union 400+400-289=511 -> 0.5656
    assert iou((0, 0, 20, 20), (3, 3, 20, 20)) == pytest.approx(289 / 511, abs=1e-9)
    assert match_image(anns, preds, iou_threshold=threshold).tp == expected_tp


def test_zero_threshold_still_requires_some_overlap():
    """A threshold of 0 must not let a disjoint box match."""
    anns = [Annotation((0, 0, 10, 10), "scratch")]
    r = match_image(anns, [Detection((100, 100, 10, 10), "scratch", 0.9)],
                    iou_threshold=0.0)
    assert r.tp == 0 and r.fp == 1 and r.fn == 1


# ---------------------------------------------------------------------------
# One-to-one and duplicates
# ---------------------------------------------------------------------------
def test_two_predictions_one_object_yields_one_tp_and_one_duplicate():
    anns = [Annotation((0, 0, 10, 10), "scratch")]
    preds = [Detection((0, 0, 10, 10), "scratch", 0.9),
             Detection((1, 1, 10, 10), "scratch", 0.7)]
    r = match_image(anns, preds)
    assert r.tp == 1 and r.fn == 0
    assert len(r.duplicates) == 1
    # the duplicate is still a false positive for precision
    assert r.fp == 1
    assert r.pairs[0].prediction.score == 0.9, "the higher-confidence box must win"


def test_confidence_order_decides_which_prediction_matches():
    """The greedy pass must take the most confident box first."""
    anns = [Annotation((0, 0, 10, 10), "scratch")]
    low_then_high = [Detection((2, 0, 10, 10), "scratch", 0.4),
                     Detection((0, 0, 10, 10), "scratch", 0.95)]
    r = match_image(anns, low_then_high)
    assert r.tp == 1
    assert r.pairs[0].prediction.score == 0.95
    assert len(r.duplicates) == 1


def test_two_objects_two_predictions_is_two_tp():
    anns = [Annotation((0, 0, 10, 10), "scratch"), Annotation((50, 50, 10, 10), "void")]
    preds = [Detection((0, 0, 10, 10), "scratch", 0.9),
             Detection((50, 50, 10, 10), "void", 0.8)]
    r = match_image(anns, preds)
    assert r.tp == 2 and r.fp == 0 and r.fn == 0


def test_predictions_matched_per_class_not_globally():
    """A scratch box must not consume a void's ground truth."""
    anns = [Annotation((0, 0, 10, 10), "void")]
    preds = [Detection((0, 0, 10, 10), "scratch", 0.9)]
    r = match_image(anns, preds)
    assert r.tp == 0 and r.fp == 1 and r.fn == 1


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_matching_is_deterministic_regardless_of_input_order():
    anns = [Annotation((0, 0, 10, 10), "scratch"), Annotation((30, 0, 10, 10), "scratch")]
    preds = [Detection((0, 0, 10, 10), "scratch", 0.8),
             Detection((30, 0, 10, 10), "scratch", 0.8)]
    a = match_image(anns, preds)
    b = match_image(list(reversed(anns)), list(reversed(preds)))
    assert (a.tp, a.fp, a.fn) == (b.tp, b.fp, b.fn) == (2, 0, 0)


def test_tied_confidences_are_broken_deterministically():
    """Same confidence, same area: the lower x/y is considered first, every time.

    Both boxes overlap the annotation above the threshold, so one is the match and the
    other a duplicate - and which is which must not depend on input order.
    """
    anns = [Annotation((0, 0, 20, 20), "scratch")]
    left = Detection((0, 0, 20, 20), "scratch", 0.5)
    right = Detection((3, 3, 20, 20), "scratch", 0.5)
    r1 = match_image(anns, [left, right])
    r2 = match_image(anns, [right, left])
    assert r1.tp == r2.tp == 1
    assert len(r1.duplicates) == len(r2.duplicates) == 1
    # the same box wins both times
    assert r1.pairs[0].prediction.box == r2.pairs[0].prediction.box
    assert r1.pairs[0].prediction.box == (0, 0, 20, 20)


# ---------------------------------------------------------------------------
# Empty and degenerate images
# ---------------------------------------------------------------------------
def test_empty_image_with_no_predictions_is_not_an_error():
    r = match_image([], [])
    assert (r.tp, r.fp, r.fn) == (0, 0, 0)


def test_empty_ground_truth_with_predictions():
    """A clean board with a spurious detection: recall is undefined, not zero."""
    r = match_image([], [Detection((0, 0, 5, 5), "scratch", 0.9)])
    assert r.tp == 0 and r.fp == 1 and r.fn == 0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def test_precision_recall_f1_on_a_known_case():
    """2 TP, 1 FP, 1 FN -> precision 2/3, recall 2/3, F1 2/3."""
    records = [
        ImageRecord("a.png", [Annotation((0, 0, 10, 10), "scratch")],
                    predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)]),
        ImageRecord("b.png", [Annotation((0, 0, 10, 10), "scratch")],
                    predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)]),
        ImageRecord("c.png", [Annotation((0, 0, 10, 10), "scratch")],
                    predictions=[Detection((80, 80, 10, 10), "scratch", 0.9)]),
        ImageRecord("d.png", [], predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)]),
    ]
    result = evaluate_records(records, dataset_name="known")
    assert (result.tp, result.fp, result.fn) == (2, 2, 1)
    assert result.precision == pytest.approx(0.5)
    assert result.recall == pytest.approx(2 / 3)
    assert result.f1 == pytest.approx(2 * 0.5 * (2 / 3) / (0.5 + 2 / 3))


def test_perfect_detector_scores_one():
    records = [ImageRecord(f"{i}.png", [Annotation((0, 0, 10, 10), "scratch")],
                           predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)])
               for i in range(5)]
    result = evaluate_records(records)
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == 1.0


def test_detector_that_predicts_nothing_has_undefined_precision():
    """"Reported nothing" is not "reported nothing correctly"."""
    records = [ImageRecord("a.png", [Annotation((0, 0, 10, 10), "scratch")],
                           predictions=[])]
    result = evaluate_records(records)
    assert result.precision is None
    assert result.recall == 0.0
    assert result.f1 is None


def test_no_ground_truth_anywhere_has_undefined_recall():
    records = [ImageRecord("a.png", [], predictions=[Detection((0, 0, 5, 5), "x", 0.9)])]
    result = evaluate_records(records)
    assert result.precision == 0.0
    assert result.recall is None
    assert result.f1 is None


def test_per_class_breakdown():
    records = [
        ImageRecord("a.png",
                    [Annotation((0, 0, 10, 10), "scratch"),
                     Annotation((50, 50, 10, 10), "void")],
                    predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)]),
    ]
    result = evaluate_records(records)
    assert result.per_class["scratch"].tp == 1
    assert result.per_class["scratch"].recall == 1.0
    assert result.per_class["void"].fn == 1
    assert result.per_class["void"].recall == 0.0
    assert result.per_class["void"].precision is None


def test_micro_average_counts_every_instance_not_every_image():
    """An image with 3 defects must weigh the same as 3 images with 1."""
    many = ImageRecord("many.png",
                       [Annotation((i * 30, 0, 10, 10), "scratch") for i in range(3)],
                       predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)])
    singles = [ImageRecord(f"s{i}.png", [Annotation((0, 0, 10, 10), "scratch")],
                           predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)])
               for i in range(3)]
    result = evaluate_records([many] + singles)
    assert result.tp == 4
    assert result.fn == 2
    assert result.gt_count == 6


def test_map_is_none_without_a_confidence_ranking():
    """A single operating point cannot define a precision-recall curve."""
    records = [ImageRecord(f"{i}.png", [Annotation((0, 0, 10, 10), "scratch")],
                           predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)])
               for i in range(3)]
    result = evaluate_records(records)
    assert result.map50 is None


def test_map_is_computed_with_a_varying_confidence_ranking():
    records = [
        ImageRecord("a.png", [Annotation((0, 0, 10, 10), "scratch")],
                    predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)]),
        ImageRecord("b.png", [Annotation((0, 0, 10, 10), "scratch")],
                    predictions=[Detection((0, 0, 10, 10), "scratch", 0.8),
                                 Detection((90, 90, 10, 10), "scratch", 0.2)]),
    ]
    result = evaluate_records(records)
    assert result.map50 is not None
    assert 0.0 < result.map50 <= 1.0


def test_map_is_one_for_a_perfectly_ranked_detector():
    """Every prediction correct, distinct confidences: AP is 1 for the class."""
    records = [
        ImageRecord("a.png", [Annotation((0, 0, 10, 10), "scratch")],
                    predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)]),
        ImageRecord("b.png", [Annotation((0, 0, 10, 10), "scratch")],
                    predictions=[Detection((0, 0, 10, 10), "scratch", 0.7)]),
    ]
    result = evaluate_records(records)
    assert result.map50 == pytest.approx(1.0)


def test_errors_are_recorded_and_excluded_from_counts():
    result = EvaluationResult(dataset_name="x")
    result.add("good.png", [Annotation((0, 0, 10, 10), "scratch")],
               [Detection((0, 0, 10, 10), "scratch", 0.9)])
    result.add_error("bad.png", "load", "file not found")
    assert result.images_evaluated == 1
    assert len(result.errors) == 1
    assert result.tp == 1


def test_result_serialises_to_json_safely():
    records = [ImageRecord("a.png", [Annotation((0, 0, 10, 10), "scratch")],
                           predictions=[Detection((0, 0, 10, 10), "scratch", 0.9)])]
    payload = evaluate_records(records, dataset_name="s").to_dict()
    text = json.dumps(payload)          # must not raise on numpy or None
    assert "precision" in text
    assert payload["tp"] == 1


def test_text_report_prints_na_for_undefined_metrics():
    records = [ImageRecord("a.png", [Annotation((0, 0, 10, 10), "s")], predictions=[])]
    report = render_text_report(evaluate_records(records, dataset_name="d"))
    assert "precision              : n/a" in report
    assert "not a score of zero" in report


# ---------------------------------------------------------------------------
# Annotation and dataset persistence
# ---------------------------------------------------------------------------
def test_dataset_round_trip(tmp_path):
    ds = Dataset(name="round", root=str(tmp_path), records=[
        ImageRecord("a.png", [Annotation((1, 2, 3, 4), "scratch", {"source": "synthetic"})],
                    size=(640, 480), meta={"board": "A"}),
        ImageRecord("b.png", [], split="train"),
    ])
    path = ds.save(str(tmp_path / "ann.json"))
    back = Dataset.load(path)
    assert back.name == "round"
    assert len(back) == 2
    assert back.records[0].annotations[0].box == (1.0, 2.0, 3.0, 4.0)
    assert back.records[0].annotations[0].label == "scratch"
    assert back.records[0].annotations[0].meta["source"] == "synthetic"
    assert back.records[1].split == "train"
    assert back.counts()["empty_images"] == 1


def test_dataset_label_set_and_counts(tmp_path):
    ds = Dataset(name="c", records=[
        ImageRecord("a.png", [Annotation((0, 0, 1, 1), "void"),
                              Annotation((0, 0, 1, 1), "scratch")]),
        ImageRecord("b.png", [Annotation((0, 0, 1, 1), "void")]),
    ])
    assert ds.label_set() == ["scratch", "void"]
    assert ds.counts() == {"images": 2, "annotations": 3, "empty_images": 0,
                           "labelled_images": 2}


def test_yolo_label_round_trip(tmp_path):
    anns = [Annotation((10, 20, 30, 40), "scratch"),
            Annotation((0, 0, 64, 48), "void")]
    path = save_yolo_labels(str(tmp_path / "a.txt"), anns, ["scratch", "void"], 640, 480)
    back = load_yolo_labels(path, 640, 480, ["scratch", "void"])
    assert len(back) == 2
    assert back[0].label == "scratch"
    assert back[0].box == pytest.approx((10, 20, 30, 40), abs=0.01)
    assert back[1].label == "void"


def test_yolo_loader_skips_malformed_lines(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("0 0.5 0.5 0.1 0.1\nnot a label\n1 0.2\n2 0.3 0.3 0.2 0.2\n",
                 encoding="utf-8")
    anns = load_yolo_labels(str(p), 100, 100, ["a", "b", "c"])
    assert len(anns) == 2
    assert anns[0].label == "a" and anns[1].label == "c"


def test_yolo_loader_tolerates_missing_file(tmp_path):
    assert load_yolo_labels(str(tmp_path / "nope.txt"), 100, 100) == []


def test_yolo_loader_rejects_a_zero_sized_image(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("0 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    assert load_yolo_labels(str(p), 0, 0) == []


def test_detections_from_outputs_zips_to_the_shortest_list():
    """Mismatched parallel lists are a detector bug; do not fabricate confidences."""
    dets = detections_from_outputs({"Boxes": [[0, 0, 1, 1], [1, 1, 1, 1]],
                                    "Classes": ["a", "b"],
                                    "Scores": [0.9]})
    assert len(dets) == 1
    assert dets[0].label == "a" and dets[0].score == 0.9


def test_detections_from_empty_outputs():
    assert detections_from_outputs({}) == []
    assert detections_from_outputs({"Boxes": [], "Classes": [], "Scores": []}) == []


def test_annotation_and_detection_round_trip():
    a = Annotation((1, 2, 3, 4), "scratch", {"k": "v"})
    assert Annotation.from_dict(a.to_dict()).box == a.box
    d = Detection((1, 2, 3, 4), "scratch", 0.5, model_id="m")
    back = Detection.from_dict(d.to_dict())
    assert back.box == d.box and back.score == d.score and back.model_id == "m"


def test_box_normalisation_of_a_negative_size():
    """A negative width is normalised rather than silently matching nothing."""
    a = Annotation.from_dict({"box": [10, 10, -5, -5], "label": "x"})
    assert a.box == (5.0, 5.0, 5.0, 5.0)


def test_short_box_is_padded_not_dropped():
    a = Annotation.from_dict({"box": [1, 2], "label": "x"})
    assert a.box == (1.0, 2.0, 0.0, 0.0)
