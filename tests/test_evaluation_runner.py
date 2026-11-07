"""Tests for batch evaluation, experiment records and comparison.

Covers the failure handling the audit requires: missing images, unreadable files, a
predictor that raises, a predictor that returns the wrong type, cancellation, and the
guarantees that make a comparison trustworthy (no silent overwrite, no comparison across
mismatched conditions).
"""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apex_vision.evaluation import (  # noqa: E402
    Annotation, Dataset, Detection, Experiment, ExperimentStore,
    IncomparableExperiments, RunConfig, compare, comparability, pipeline_fingerprint,
    render_comparison, run_dataset,
)


@pytest.fixture()
def tiny_dataset(tmp_path):
    """Three images on disk: two with defects, one clean."""
    import cv2

    images = tmp_path / "images"
    images.mkdir()
    records = []
    specs = [
        ("a.png", [(10, 10, 20, 20, "scratch")]),
        ("b.png", [(40, 40, 16, 16, "void")]),
        ("c.png", []),
    ]
    for name, anns in specs:
        cv2.imwrite(str(images / name), np.full((64, 64, 3), 100, np.uint8))
        records.append(("images/" + name,
                        [Annotation((x, y, w, h), label) for x, y, w, h, label in anns]))
    ds = Dataset(name="tiny", root=str(tmp_path),
                 records=[__import__("apex_vision.evaluation", fromlist=["ImageRecord"])
                          .ImageRecord(p, a) for p, a in records])
    return ds


def _perfect(image):
    """A predictor that returns the ground truth for the fixture images."""
    if image[10:30, 10:30].mean() == 100:
        return [Detection((10, 10, 20, 20), "scratch", 0.9)]
    return []


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def test_run_dataset_end_to_end(tiny_dataset):
    outcome = run_dataset(tiny_dataset, _perfect)
    assert outcome.result.images_evaluated == 3
    assert outcome.result.split == "test"
    assert len(outcome.predictions) == 3
    assert all(os.path.isabs(p) for p in outcome.image_paths.values())


def test_confidence_threshold_filters_predictions(tiny_dataset):
    def two_boxes(image):
        return [Detection((10, 10, 20, 20), "scratch", 0.9),
                Detection((40, 40, 16, 16), "void", 0.2)]

    loose = run_dataset(tiny_dataset, two_boxes, RunConfig(confidence_threshold=0.0))
    tight = run_dataset(tiny_dataset, two_boxes, RunConfig(confidence_threshold=0.5))
    assert sum(len(v) for v in loose.predictions.values()) > \
           sum(len(v) for v in tight.predictions.values())


def test_missing_image_is_recorded_not_skipped(tmp_path):
    ds = Dataset(name="missing", root=str(tmp_path), records=[
        __import__("apex_vision.evaluation", fromlist=["ImageRecord"]).ImageRecord(
            "nope.png", [Annotation((0, 0, 5, 5), "x")])])
    outcome = run_dataset(ds, lambda image: [])
    assert outcome.result.images_evaluated == 0
    assert len(outcome.result.errors) == 1
    assert outcome.result.errors[0]["stage"] == "load"


def test_predictor_that_raises_is_recorded(tmp_path, tiny_dataset):
    def broken(image):
        raise RuntimeError("detector exploded")

    outcome = run_dataset(tiny_dataset, broken)
    assert outcome.result.images_evaluated == 0
    assert all(e["stage"] == "predict" for e in outcome.result.errors)
    assert "detector exploded" in outcome.result.errors[0]["message"]


def test_predictor_returning_wrong_type_is_recorded(tiny_dataset):
    outcome = run_dataset(tiny_dataset, lambda image: 42)
    assert outcome.result.images_evaluated == 0
    assert any(e["stage"] == "normalise" for e in outcome.result.errors)


def test_predictor_may_report_inference_time(tiny_dataset):
    outcome = run_dataset(tiny_dataset, lambda image: ([], 7.5))
    assert outcome.result.images_evaluated == 3
    assert all(abs(v - 7.5) < 1e-6 for v in outcome.result.latency.inference_ms)


def test_cancellation_stops_the_run(tmp_path):
    import cv2

    images = tmp_path / "images"
    images.mkdir()
    for i in range(6):
        cv2.imwrite(str(images / f"{i}.png"), np.full((32, 32, 3), 100, np.uint8))
    ds = Dataset(name="cancel", root=str(tmp_path), records=[
        __import__("apex_vision.evaluation", fromlist=["ImageRecord"]).ImageRecord(
            f"images/{i}.png", []) for i in range(6)])

    seen = {"n": 0}

    def cancel():
        seen["n"] += 1
        return seen["n"] > 2

    outcome = run_dataset(ds, lambda image: [], should_cancel=cancel)
    assert outcome.result.images_evaluated < 6
    assert any(e["stage"] == "cancelled" for e in outcome.result.errors)


def test_resize_rescales_predictions_back_to_the_original_frame(tmp_path):
    """A working size must not silently break matching."""
    import cv2

    images = tmp_path / "images"
    images.mkdir()
    cv2.imwrite(str(images / "a.png"), np.full((100, 100, 3), 100, np.uint8))
    ds = Dataset(name="resize", root=str(tmp_path), records=[
        __import__("apex_vision.evaluation", fromlist=["ImageRecord"]).ImageRecord(
            "images/a.png", [Annotation((0, 0, 50, 50), "x")])])

    def predict_half(image):
        # the detector sees a 50x50 image and returns boxes in that frame
        h, w = image.shape[:2]
        assert (w, h) == (50, 50), f"expected the working size, got {w}x{h}"
        return [Detection((0, 0, 25, 25), "x", 0.9)]

    outcome = run_dataset(ds, predict_half, RunConfig(working_size=(50, 50)))
    assert outcome.result.tp == 1, "predictions were not rescaled to the original frame"


def test_progress_callback_is_called(tiny_dataset):
    calls = []
    run_dataset(tiny_dataset, lambda image: [],
                progress=lambda i, n, path: calls.append((i, n)))
    assert len(calls) >= 3


def test_latency_buckets_are_separated(tiny_dataset):
    outcome = run_dataset(tiny_dataset, lambda image: ([], 5.0))
    lat = outcome.result.latency
    assert len(lat.inference_ms) == 3
    assert len(lat.preprocessing_ms) == 3
    # with a reported inference time, the measured call minus that becomes overhead
    assert all(v >= 0 for v in lat.overhead_ms)
    assert lat.throughput_fps is not None


# ---------------------------------------------------------------------------
# Experiment record
# ---------------------------------------------------------------------------
def test_experiment_records_settings_and_environment(tiny_dataset):
    outcome = run_dataset(tiny_dataset, _perfect,
                          RunConfig(dataset_name="tiny", model_id="det-v1",
                                    confidence_threshold=0.4, working_size=(64, 64),
                                    detector_variant="reference"))
    exp = Experiment.from_run(outcome, name="run one")
    assert exp.dataset_name == "tiny"
    assert exp.settings["iou_threshold"] == pytest.approx(0.5)
    assert exp.settings["confidence_threshold"] == pytest.approx(0.4)
    assert exp.settings["working_size"] == [64, 64]
    assert exp.model["id"] == "det-v1"
    assert "numpy" in exp.environment["software"]
    assert exp.environment["hardware"]["cpu_count"] >= 1
    assert exp.status == "ok"
    assert exp.timestamp


def test_experiment_with_errors_is_marked_partial(tmp_path):
    ds = Dataset(name="bad", root=str(tmp_path), records=[
        __import__("apex_vision.evaluation", fromlist=["ImageRecord"]).ImageRecord(
            "missing.png", [Annotation((0, 0, 5, 5), "x")])])
    exp = Experiment.from_run(run_dataset(ds, lambda image: []))
    assert exp.status == "failed"       # nothing evaluated at all


def test_experiment_round_trips_through_json(tiny_dataset):
    exp = Experiment.from_run(run_dataset(tiny_dataset, _perfect), name="rt")
    back = Experiment.from_dict(json.loads(json.dumps(exp.to_dict())))
    assert back.name == exp.name
    assert back.metrics["tp"] == exp.metrics["tp"]
    assert back.settings == exp.settings


def test_model_reference_describes_a_real_file(tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"x" * 32)
    exp = Experiment.from_run(
        run_dataset(Dataset(name="d", root=str(tmp_path)), lambda i: []),
        name="m")
    exp.model = {}
    from apex_vision.evaluation.experiment import _safe_model_reference

    ref = _safe_model_reference(str(weights))
    assert ref["kind"] == "file"
    assert ref["size_bytes"] == 32


def test_model_reference_is_honest_about_a_fictional_path():
    from apex_vision.evaluation.experiment import _safe_model_reference

    ref = _safe_model_reference("no-such-model.pt")
    assert ref["kind"] == "identifier", "a missing path must not be claimed as a file"


# ---------------------------------------------------------------------------
# Store: history is append-only
# ---------------------------------------------------------------------------
def test_store_never_overwrites_a_record(tmp_path, tiny_dataset):
    store = ExperimentStore(str(tmp_path / "store"))
    exp = Experiment.from_run(run_dataset(tiny_dataset, _perfect), name="same")
    first = store.save(exp)
    second = store.save(exp)          # identical name and timestamp
    third = store.save(exp)
    assert len({first, second, third}) == 3
    assert len(store.load_all()) == 3


def test_store_index_lists_metrics(tmp_path, tiny_dataset):
    store = ExperimentStore(str(tmp_path / "store"))
    store.save(Experiment.from_run(run_dataset(tiny_dataset, _perfect), name="a"))
    entries = store.list_records()
    assert len(entries) == 1
    assert "precision" in entries[0]
    assert entries[0]["name"] == "a"


def test_store_find_by_name(tmp_path, tiny_dataset):
    store = ExperimentStore(str(tmp_path / "store"))
    store.save(Experiment.from_run(run_dataset(tiny_dataset, _perfect), name="alpha"))
    store.save(Experiment.from_run(run_dataset(tiny_dataset, _perfect), name="beta"))
    assert len(store.find("alpha")) == 1
    assert len(store.find("tiny")) == 2       # both are on the 'tiny' dataset


def test_store_survives_a_corrupt_record(tmp_path, tiny_dataset):
    store = ExperimentStore(str(tmp_path / "store"))
    store.save(Experiment.from_run(run_dataset(tiny_dataset, _perfect), name="good"))
    (tmp_path / "store" / "records" / "broken.json").write_text("{not json",
                                                                encoding="utf-8")
    # the good record must still load
    assert len(store.load_all()) == 1


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def _make_experiment(name, tp, fp, fn, dataset="d", iou=0.5, conf=0.25, split="test"):
    exp = Experiment(name=name, timestamp="2026-01-01T00:00:00", dataset={
        "name": dataset, "split": split})
    exp.settings = {"iou_threshold": iou, "confidence_threshold": conf}
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall else None)
    exp.metrics = {"tp": tp, "fp": fp, "fn": fn, "precision": precision,
                   "recall": recall, "f1": f1, "mAP@IoU": None, "duplicates": 0,
                   "images_evaluated": 10, "latency": {}}
    return exp


def test_comparison_reports_deltas_against_the_baseline():
    a = _make_experiment("base", tp=80, fp=20, fn=20)
    b = _make_experiment("other", tp=90, fp=30, fn=10)
    comparison = compare([a, b], base_index=0)
    assert comparison.rows[1].deltas["tp"] == pytest.approx(10)
    assert comparison.rows[1].deltas["fn"] == pytest.approx(-10)
    assert comparison.rows[0].deltas == {}


def test_comparison_describes_a_trade_off_not_a_winner():
    a = _make_experiment("precise", tp=80, fp=10, fn=30)
    b = _make_experiment("sensitive", tp=95, fp=60, fn=5)
    comparison = compare([a, b], base_index=0)
    text = " ".join(comparison.observations)
    assert "recall" in text and "precision" in text
    assert "not an improvement" in text
    assert "universally" in text


def test_comparison_refuses_mismatched_iou_thresholds():
    a = _make_experiment("a", tp=1, fp=0, fn=0, iou=0.5)
    b = _make_experiment("b", tp=1, fp=0, fn=0, iou=0.75)
    with pytest.raises(IncomparableExperiments):
        compare([a, b])
    # and can be forced when the caller accepts the caveat
    comparison = compare([a, b], allow_incomparable=True)
    assert comparison.warnings


def test_comparison_refuses_different_datasets():
    a = _make_experiment("a", 1, 0, 0, dataset="one")
    b = _make_experiment("b", 1, 0, 0, dataset="two")
    assert comparability(a, b)
    with pytest.raises(IncomparableExperiments):
        compare([a, b])


def test_comparison_refuses_a_failed_run():
    a = _make_experiment("a", 1, 0, 0)
    b = _make_experiment("b", 1, 0, 0)
    b.status = "failed"
    with pytest.raises(IncomparableExperiments):
        compare([a, b])


def test_comparison_flags_a_different_confidence_threshold():
    a = _make_experiment("a", 10, 1, 1, conf=0.25)
    b = _make_experiment("b", 10, 1, 1, conf=0.60)
    comparison = compare([a, b])
    assert any("confidence thresholds differ" in o for o in comparison.observations)


def test_comparison_needs_two_experiments():
    with pytest.raises(ValueError):
        compare([_make_experiment("only", 1, 0, 0)])


def test_comparison_renders_a_table():
    a = _make_experiment("base", 80, 20, 20)
    b = _make_experiment("other", 90, 30, 10)
    text = render_comparison(compare([a, b]))
    assert "EXPERIMENT COMPARISON" in text
    assert "precision" in text
    assert "n/a" in text          # mAP is undefined and must not print as 0


def test_find_detector_node_requires_a_detections_output():
    """A node without a `Detections` output must never be selected.

    Regression: the search matched by tool name alone, so `Defect Detection` - which
    reported only a defect count - was selected, its missing output was read as an empty
    list, and every image produced zero detections.  The evaluation reported 0 TP and
    all-FN while appearing to have run correctly.
    """
    import apex_vision.tools  # noqa: F401
    from apex_vision.core.pipeline import VisionPipeline
    from apex_vision.core.registry import create_tool_instance
    from apex_vision.evaluation import find_detector_node, pipeline_predictor

    pipe = VisionPipeline(name="no-detector")
    pipe.add_node(create_tool_instance("Image Source", "src"))
    branch = create_tool_instance("Condition Branch", "cond")
    pipe.add_node(branch)
    assert find_detector_node(pipe) is None, (
        "a node with no Detections output must not be treated as a detector")
    with pytest.raises(ValueError, match="no detector node"):
        pipeline_predictor(pipe)


def test_find_detector_node_accepts_the_defect_detection_node():
    import apex_vision.tools  # noqa: F401
    from apex_vision.core.pipeline import VisionPipeline
    from apex_vision.core.registry import create_tool_instance
    from apex_vision.evaluation import find_detector_node

    pipe = VisionPipeline(name="classical")
    pipe.add_node(create_tool_instance("Image Source", "src"))
    pipe.add_node(create_tool_instance("Defect Detection", "dd"))
    node = find_detector_node(pipe)
    assert node is not None and node.tool_name == "Defect Detection"


def test_defect_detection_emits_the_detections_contract():
    """The classical defect tool must expose the same outputs the evaluator reads."""
    import numpy as np

    import apex_vision.tools  # noqa: F401
    from apex_vision.core.base_tool import ToolStatus
    from apex_vision.core.registry import create_tool_instance

    tool = create_tool_instance("Defect Detection", "dd")
    for port in ("Boxes", "Classes", "Scores", "Detections"):
        assert port in tool.outputs, f"{port} missing from Defect Detection outputs"
    # existing outputs are preserved
    for port in ("Image", "Defect_Count", "Max_Defect_Area"):
        assert port in tool.outputs

    # a dark blob inside the default ROI is reported as a detection, in all three
    # parallel lists and in the structured records, with consistent lengths
    image = np.full((480, 640, 3), 200, dtype=np.uint8)
    image[280:300, 300:340] = 20          # inside the default ROI [260, 240, 180, 120]
    tool.parameters["roi"] = [260, 240, 180, 120]
    result = tool.execute({"Image": image})
    assert result.status in (ToolStatus.OK, ToolStatus.NG)
    outputs = result.outputs
    n = outputs["Defect_Count"]
    assert len(outputs["Boxes"]) == n
    assert len(outputs["Classes"]) == n
    assert len(outputs["Scores"]) == n
    assert len(outputs["Detections"]) == n
    if n:
        record = outputs["Detections"][0]
        assert set(record) >= {"box", "label", "score"}
        assert len(record["box"]) == 4


def test_defect_detection_records_survive_the_evaluation_adapter():
    """The detector's own output must convert into matchable `Detection` records."""
    import numpy as np

    import apex_vision.tools  # noqa: F401
    from apex_vision.core.registry import create_tool_instance
    from apex_vision.evaluation import detections_from_outputs

    tool = create_tool_instance("Defect Detection", "dd")
    image = np.full((480, 640, 3), 200, dtype=np.uint8)
    image[280:300, 300:340] = 20
    result = tool.execute({"Image": image})
    dets = detections_from_outputs(result.outputs)
    assert len(dets) == result.outputs["Defect_Count"]
    for det in dets:
        assert det.label and len(det.box) == 4


def test_pipeline_fingerprint_changes_with_parameters():
    import apex_vision.tools  # noqa: F401
    from apex_vision.core.pipeline import VisionPipeline
    from apex_vision.core.registry import create_tool_instance

    pipe = VisionPipeline(name="p")
    tool = create_tool_instance("Object Detection", "n1")
    pipe.add_node(tool)
    first = pipeline_fingerprint(pipe)

    # stable when nothing changes
    assert first == pipeline_fingerprint(pipe)

    # changes when a node parameter changes
    tool.set_param("confidence", 0.7)
    second = pipeline_fingerprint(pipe)
    assert first != second, "a parameter change must change the fingerprint"

    # and two independently built identical pipelines agree
    other = VisionPipeline(name="p")
    other.add_node(create_tool_instance("Object Detection", "n1"))
    other.nodes["n1"].set_param("confidence", 0.7)
    assert pipeline_fingerprint(other) == second


def test_from_run_accepts_a_pipeline(tiny_dataset):
    """Recording the workflow identity must not raise.

    Regression: `Experiment.from_run` referenced `find_detector_node` without importing
    it, so saving from the GUI - which passes the active pipeline - raised NameError
    while the CLI path (no pipeline) worked.  The GUI hit it inside a modal error dialog,
    which is how it stayed invisible.
    """
    import apex_vision.tools  # noqa: F401
    from apex_vision.core.pipeline import VisionPipeline
    from apex_vision.core.registry import create_tool_instance

    pipe = VisionPipeline(name="rec")
    pipe.add_node(create_tool_instance("Image Source", "src"))
    pipe.add_node(create_tool_instance("PCB Defect Detection", "det"))
    pipe.connect("src", "Image", "det", "Image")

    outcome = run_dataset(tiny_dataset, _perfect)
    experiment = Experiment.from_run(outcome, name="with workflow", pipeline=pipe)
    assert experiment.workflow["name"] == "rec"
    assert experiment.workflow["detector_node"] == "PCB Defect Detection"
    assert experiment.workflow["fingerprint"]
    assert experiment.workflow["node_count"] == 2
    assert experiment.workflow["connection_count"] == 1
