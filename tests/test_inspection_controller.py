"""Tests for the inspection GUI controller (the non-Qt half of the panel).

The controller is where the interface's behaviour actually lives - which failures are
listed, how they are filtered, what the metric table shows, and whether saving an
experiment can overwrite history.  Testing it here keeps that behaviour covered without
a display, and the panel is then only responsible for rendering.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apex_vision.evaluation import Experiment  # noqa: E402
from apex_vision.evaluation.matching import DUPLICATE, FP, FN  # noqa: E402
from apex_vision.ui.inspection_controller import (  # noqa: E402
    InspectionController, classify_failures, failure_summary, filter_failures,
)


@pytest.fixture()
def dataset_dir(tmp_path):
    from apex_vision.samples.pcb_defect_dataset import build_dataset

    build_dataset(str(tmp_path / "ds"), count=8, seed=777)
    return str(tmp_path / "ds" / "annotations.json")


@pytest.fixture()
def controller(dataset_dir, tmp_path):
    c = InspectionController(store_directory=str(tmp_path / "exp"))
    c.load_dataset(dataset_dir)
    return c


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------
def test_load_dataset_populates_the_summary(controller):
    summary = controller.dataset_summary()
    assert summary["name"] == "pcb_defect_synth"
    assert summary["images"] == 8
    assert summary["annotations"] > 0
    assert summary["classes"]
    assert summary["generator"].startswith("pcb_defect")


def test_load_missing_dataset_raises_a_useful_error(controller, tmp_path):
    with pytest.raises(FileNotFoundError, match="dataset not found"):
        controller.load_dataset(str(tmp_path / "nope.json"))


def test_load_empty_dataset_raises(controller, tmp_path):
    import json

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"name": "e", "images": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="no images"):
        controller.load_dataset(str(empty))


def test_annotated_images_lists_only_labelled_boards(controller):
    assert controller.annotated_images
    assert all(name.endswith(".png") for name in controller.annotated_images)
    # a clean board has no ground truth and must not be offered as an annotated image
    assert len(controller.annotated_images) <= len(controller.dataset.records)


# ---------------------------------------------------------------------------
# Running an evaluation
# ---------------------------------------------------------------------------
def test_run_evaluation_produces_metrics_and_failures(controller):
    outcome = controller.run_evaluation(detector_variant="reference")
    assert outcome.result.images_evaluated == 8
    assert outcome.result.tp > 0
    assert controller.failures, "a run with mistakes must produce inspectable failures"
    assert controller.metrics_table()


def test_run_without_a_dataset_raises(tmp_path):
    c = InspectionController(store_directory=str(tmp_path))
    with pytest.raises(RuntimeError, match="no dataset"):
        c.run_evaluation()


def test_metrics_table_prints_na_for_undefined_values(tmp_path):
    import json

    from apex_vision.evaluation import Annotation, Dataset, ImageRecord

    ds = Dataset(name="empty-truth", root=str(tmp_path), records=[
        ImageRecord("x.png", [], size=(32, 32))])
    ds.save(str(tmp_path / "a.json"))
    c = InspectionController(store_directory=str(tmp_path / "exp"))
    c.load_dataset(str(tmp_path / "a.json"))
    # a predictor that reports nothing -> precision must be n/a, not 0
    c.run_evaluation(predictor=lambda image: [])
    table = dict(c.metrics_table())
    assert table["Precision"] == "n/a"


def test_confidence_threshold_reduces_failures_of_one_kind(controller):
    loose = controller.run_evaluation(confidence_threshold=0.0)
    loose_fp = sum(1 for c in controller.failures if c.kind == FP)
    controller.run_evaluation(confidence_threshold=0.99)
    tight_fp = sum(1 for c in controller.failures if c.kind == FP)
    assert tight_fp <= loose_fp


def test_iou_threshold_is_recorded_in_the_run(controller):
    outcome = controller.run_evaluation(iou_threshold=0.75)
    assert outcome.result.iou_threshold == pytest.approx(0.75)
    assert outcome.config.iou_threshold == pytest.approx(0.75)


def test_run_records_the_layout_setting(controller):
    with_layout = controller.run_evaluation(use_layout=True)
    without = controller.run_evaluation(use_layout=False)
    assert without.result.fp > with_layout.result.fp, (
        "the layout input must measurably reduce false positives, or the "
        "controller's claim about it is wrong")


def test_progress_callback_receives_every_image(controller):
    seen = []
    controller.run_evaluation(progress=lambda i, n, p: seen.append((i, n)))
    assert seen and seen[-1][0] == seen[-1][1] == 8


def test_cancellation_is_honoured(controller):
    state = {"n": 0}

    def cancel():
        state["n"] += 1
        return state["n"] > 2

    outcome = controller.run_evaluation(should_cancel=cancel)
    assert outcome.result.images_evaluated < 8
    assert any(e["stage"] == "cancelled" for e in outcome.result.errors)


# ---------------------------------------------------------------------------
# Failure classification and filtering
# ---------------------------------------------------------------------------
def _cases():
    from apex_vision.evaluation import Annotation, Detection
    from apex_vision.evaluation.metrics import EvaluationResult

    result = EvaluationResult(dataset_name="d", iou_threshold=0.5)
    result.add("a.png", [Annotation((0, 0, 10, 10), "scratch")],
               [Detection((0, 0, 10, 10), "scratch", 0.9),
                Detection((50, 50, 10, 10), "void", 0.8)])
    result.add("b.png", [Annotation((0, 0, 10, 10), "void")], [])
    result.add("c.png", [Annotation((0, 0, 10, 10), "void")],
               [Detection((0, 0, 10, 10), "void", 0.9),
                Detection((1, 1, 10, 10), "void", 0.5)])
    return classify_failures(result, {"a.png": "/tmp/a.png"})


def test_classify_failures_covers_all_three_kinds():
    cases = _cases()
    kinds = {c.kind for c in cases}
    assert FP in kinds
    assert FN in kinds
    assert DUPLICATE in kinds


def test_false_negative_has_no_score_and_is_a_ground_truth_box():
    fn = [c for c in _cases() if c.kind == FN]
    assert fn
    for case in fn:
        assert case.score is None
        assert not case.is_prediction


def test_false_positive_is_a_prediction_with_a_score():
    fp = [c for c in _cases() if c.kind == FP]
    assert fp
    for case in fp:
        assert case.is_prediction
        assert case.score is not None


def test_classify_resolves_the_absolute_path():
    cases = _cases()
    for case in cases:
        if case.image == "a.png":
            assert case.image_path == "/tmp/a.png"


def test_classify_is_deterministic():
    assert [ (c.kind, c.image, c.box) for c in _cases() ] == \
           [ (c.kind, c.image, c.box) for c in _cases() ]


def test_filter_by_kind():
    only_fn = filter_failures(_cases(), kinds=[FN])
    assert only_fn and all(c.kind == FN for c in only_fn)


def test_filter_by_label():
    cases = filter_failures(_cases(), labels=["void"])
    assert cases and all(c.label == "void" for c in cases)


def test_filter_by_image():
    cases = filter_failures(_cases(), image="b.png")
    assert cases and all(c.image == "b.png" for c in cases)


def test_score_filter_never_drops_a_false_negative():
    """A missed defect has no confidence; filtering it out would hide the worst case."""
    cases = filter_failures(_cases(), min_score=0.95)
    assert all(c.score is None or c.score >= 0.95 for c in cases)
    assert any(c.kind == FN for c in cases), "false negatives must survive a score filter"


def test_filter_by_reason_code():
    cases = filter_failures(_cases(), reason_codes=["no_overlap"])
    assert cases and all(c.reason_code == "no_overlap" for c in cases)


def test_filters_compose():
    cases = filter_failures(_cases(), kinds=[FP], labels=["void"], min_score=0.5)
    assert all(c.kind == FP and c.label == "void" for c in cases)


def test_failure_summary_counts():
    summary = failure_summary(_cases())
    assert summary["total"] == len(_cases())
    assert sum(summary["by_kind"].values()) == summary["total"]
    assert set(summary["by_label"]) <= {"scratch", "void"}


def test_available_labels_and_reasons(controller):
    controller.run_evaluation()
    assert controller.available_labels()
    reasons = controller.available_reasons()
    assert reasons and all(isinstance(code, str) and desc for code, desc in reasons)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def test_per_class_rows_show_na_for_undefined(controller):
    controller.run_evaluation()
    rows = controller.per_class_rows()
    assert rows
    for row in rows:
        assert len(row) == 9
        # precision/recall/f1/AP columns must print 'n/a' rather than blank
        for cell in row[5:]:
            assert cell == "n/a" or any(ch.isdigit() for ch in cell)


def test_latency_rows_are_labelled_by_stage(controller):
    controller.run_evaluation()
    rows = controller.latency_rows()
    labels = [r[0] for r in rows]
    assert labels == ["Inference", "Preprocessing", "Harness overhead",
                      "Total per image"]


def test_error_rows_are_empty_for_a_clean_run(controller):
    controller.run_evaluation()
    assert controller.error_rows() == []


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------
def test_save_experiment_records_the_run(controller):
    controller.run_evaluation(detector_variant="reference")
    experiment = controller.save_experiment(name="gui run")
    assert experiment.name == "gui run"
    assert experiment.metrics["precision"] is not None
    assert len(controller.list_experiments()) == 1


def test_saving_twice_keeps_both_records(controller):
    controller.run_evaluation()
    controller.save_experiment(name="same")
    controller.save_experiment(name="same")
    assert len(controller.list_experiments()) == 2, "history must not be overwritten"


def test_save_without_a_run_raises(tmp_path):
    c = InspectionController(store_directory=str(tmp_path / "exp"))
    with pytest.raises(RuntimeError, match="nothing to save"):
        c.save_experiment()


def test_store_is_required_for_saving(tmp_path, dataset_dir):
    c = InspectionController()
    c.load_dataset(dataset_dir)
    c.run_evaluation()
    with pytest.raises(RuntimeError, match="no experiment store"):
        c.save_experiment()


def test_list_experiments_on_a_missing_store_is_empty(controller, tmp_path):
    controller.store_directory = str(tmp_path / "never-created")
    assert controller.list_experiments() == []


def test_compare_two_runs(controller):
    controller.run_evaluation(detector_variant="reference")
    first = controller.save_experiment(name="reference")
    controller.run_evaluation(detector_variant="conservative")
    second = controller.save_experiment(name="conservative")
    comparison = controller.compare_experiments([first, second])
    assert len(comparison.rows) == 2
    assert comparison.rows[1].deltas
    assert comparison.observations


def test_compare_detects_incomparable_runs(controller):
    from apex_vision.evaluation import IncomparableExperiments

    controller.run_evaluation(iou_threshold=0.5)
    a = controller.save_experiment(name="iou50")
    controller.run_evaluation(iou_threshold=0.9)
    b = controller.save_experiment(name="iou90")
    with pytest.raises(IncomparableExperiments):
        controller.compare_experiments([a, b])
    assert controller.compare_experiments([a, b], allow_incomparable=True).warnings
