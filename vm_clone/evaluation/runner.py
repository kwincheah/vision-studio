"""Batch evaluation: run a detector over a dataset with per-stage timings.

The runner is deliberately independent of Qt and of the GUI's pipeline editor.  It takes
an *image-to-detections* callable, a dataset, and a threshold, and produces an
`EvaluationResult`.  The GUI and the CLI both drive this one implementation, so a metric
shown in the interface is the number the command line wrote to disk.

Two callables are supported, and they are the two things an inspection platform needs:

* a plain function `(image) -> Sequence[Detection]`, used for the classical reference
  detector and for tests, and
* `pipeline_predictor`, which adapts a `VisionPipeline` (the visual workflow the user
  built) into that callable, so the *same* evaluation measures a hand-built workflow.

Separating the timings is not decoration.  `inference_ms` is a property of the model;
image decode and preprocessing belong to the harness.  Reporting one number and calling
it "latency" would let a slow disk be presented as a slow model.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
from vm_clone.core.imageio import imread
import numpy as np

from vm_clone.evaluation.annotations import (
    Annotation, Dataset, Detection,
)
from vm_clone.evaluation.matching import DEFAULT_IOU_THRESHOLD
from vm_clone.evaluation.metrics import EvaluationResult

#: A predictor turns a decoded image into detections, and may report the time it spent
#: on inference itself.  Returning `None` for the time means "not reported", and the
#: stage is then excluded from the latency statistics rather than counted as zero.
Predictor = Callable[[np.ndarray], Any]


@dataclass
class RunConfig:
    """Everything that affects a run, recorded with the result.

    Kept as a dataclass so it can be serialised into an experiment record without
    hand-written field lists that drift from the code.
    """
    dataset_name: str = ""
    split: str = "test"
    iou_threshold: float = DEFAULT_IOU_THRESHOLD
    confidence_threshold: float = 0.0
    #: image size the detector was allowed to work at; recorded because a resize changes
    #: both accuracy and speed and an experiment is not reproducible without it
    working_size: Optional[Tuple[int, int]] = None
    model_id: str = ""
    predictor_kind: str = "function"
    detector_variant: str = ""
    #: free-form; the caller records workflow identity and parameters here
    extras: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.extras is None:
            self.extras = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "split": self.split,
            "iou_threshold": self.iou_threshold,
            "confidence_threshold": self.confidence_threshold,
            "working_size": list(self.working_size) if self.working_size else None,
            "model_id": self.model_id,
            "predictor_kind": self.predictor_kind,
            "detector_variant": self.detector_variant,
            "extras": dict(self.extras or {}),
        }


@dataclass
class RunOutcome:
    """The result of a batch run, with everything needed to reproduce it."""
    result: EvaluationResult
    config: RunConfig
    #: predictions per image path, kept so average precision can be computed and so the
    #: failure view can show what was predicted where
    predictions: Dict[str, List[Detection]]
    #: resolved absolute path per image path, for the failure view to open originals
    image_paths: Dict[str, str]


def apply_confidence_threshold(predictions: Sequence[Detection],
                               threshold: float) -> List[Detection]:
    """Drop predictions below `threshold`.

    A detector may already have thresholded; applying it again here makes the operating
    point an explicit property of the *experiment* rather than of the model file, which
    is what makes two experiments comparable.
    """
    if threshold <= 0.0:
        return list(predictions)
    return [p for p in predictions if float(p.score) >= float(threshold)]


def run_dataset(dataset: Dataset, predictor: Predictor,
                config: Optional[RunConfig] = None,
                progress: Optional[Callable[[int, int, str], None]] = None,
                should_cancel: Optional[Callable[[], bool]] = None,
                before_image: Optional[Callable[[Any], None]] = None) -> RunOutcome:
    """Evaluate `predictor` over every image in `dataset`.

    `before_image(record)` runs immediately before each image is predicted.  It exists
    for context that belongs to the *record* rather than the pixels - the PCB workflow
    needs to tell its layout node which board's design to emit.  Passing it here keeps
    that dependency explicit instead of hiding it inside a predictor closure.

    Failure handling is explicit at every stage.  An image that cannot be read, a
    predictor that raises, and a predictor that returns something that is not a sequence
    of detections are each recorded in `result.errors` with the stage that failed, and
    the image is excluded from the counts.  Silently skipping it would change the
    denominators without saying so.
    """
    config = config or RunConfig()
    result = EvaluationResult(dataset_name=dataset.name,
                              iou_threshold=float(config.iou_threshold),
                              split=config.split,
                              meta={"config": config.to_dict()})
    predictions: Dict[str, List[Detection]] = {}
    image_paths: Dict[str, str] = {}
    annotations: Dict[str, List[Annotation]] = {}

    total = len(dataset.records)
    for index, record in enumerate(dataset.records):
        if should_cancel is not None and should_cancel():
            result.add_error(record.image_path, "cancelled",
                             "run cancelled before this image")
            break
        if progress is not None:
            progress(index, total, record.image_path)
        if before_image is not None:
            before_image(record)

        resolved = dataset.resolve(record)
        image_paths[record.image_path] = resolved

        # --- stage: load ---------------------------------------------------
        t0 = time.perf_counter()
        try:
            image = imread(resolved)
        except Exception as exc:                       # noqa: BLE001 - reported
            # `cv2.imread` returns None for an unreadable file, but Ultralytics patches
            # it to read through `np.fromfile`, which *raises* FileNotFoundError.  Both
            # behaviours must land in the error list, so the call is guarded.
            result.add_error(record.image_path, "load",
                             f"{type(exc).__name__}: {exc}")
            predictions[record.image_path] = []
            annotations[record.image_path] = list(record.annotations)
            continue
        if image is None:
            result.add_error(record.image_path, "load",
                             f"could not read image: {resolved}")
            predictions[record.image_path] = []
            annotations[record.image_path] = list(record.annotations)
            continue
        load_ms = (time.perf_counter() - t0) * 1000.0

        # --- stage: preprocess ---------------------------------------------
        t1 = time.perf_counter()
        working = image
        if config.working_size:
            working = cv2.resize(image, (int(config.working_size[0]),
                                         int(config.working_size[1])),
                                 interpolation=cv2.INTER_AREA)
        preprocess_ms = (time.perf_counter() - t1) * 1000.0

        # --- stage: predict ------------------------------------------------
        reported_inference_ms: Optional[float] = None
        t2 = time.perf_counter()
        try:
            raw = predictor(working)
        except Exception as exc:                       # noqa: BLE001 - reported, not hidden
            result.add_error(record.image_path, "predict",
                             f"{type(exc).__name__}: {exc}")
            predictions[record.image_path] = []
            annotations[record.image_path] = list(record.annotations)
            continue
        predict_ms = (time.perf_counter() - t2) * 1000.0

        if isinstance(raw, tuple) and len(raw) == 2:
            raw_dets, reported_inference_ms = raw
        else:
            raw_dets = raw

        # --- stage: normalise ----------------------------------------------
        try:
            dets = list(raw_dets)
        except TypeError:
            result.add_error(record.image_path, "normalise",
                             f"predictor returned {type(raw_dets).__name__}, "
                             f"expected a sequence of Detection")
            predictions[record.image_path] = []
            annotations[record.image_path] = list(record.annotations)
            continue

        normalised: List[Detection] = []
        bad = 0
        for item in dets:
            if isinstance(item, Detection):
                normalised.append(item)
            elif isinstance(item, dict):
                normalised.append(Detection.from_dict(item))
            else:
                bad += 1
        if bad:
            result.add_error(record.image_path, "normalise",
                             f"{bad} prediction(s) were not Detection or dict")

        normalised = apply_confidence_threshold(normalised, config.confidence_threshold)

        # Rescale boxes if the image was resized for the detector, so predictions are
        # compared with annotations in the original frame.  Forgetting this would make
        # every match fail at a working size other than native.
        if config.working_size and image.shape[:2] != working.shape[:2]:
            sx = image.shape[1] / float(working.shape[1])
            sy = image.shape[0] / float(working.shape[0])
            normalised = [Detection(box=(d.box[0] * sx, d.box[1] * sy,
                                         d.box[2] * sx, d.box[3] * sy),
                                    label=d.label, score=d.score,
                                    model_id=d.model_id, extra=d.extra)
                          for d in normalised]

        predictions[record.image_path] = normalised
        annotations[record.image_path] = list(record.annotations)
        result.add(record.image_path, record.annotations, normalised)

        # --- record timings -------------------------------------------------
        # The predictor may report its own inference time.  When it does, that is the
        # number used for inference; when it does not, the measured call is used but
        # flagged as including the call overhead.
        result.latency.inference_ms.append(
            float(reported_inference_ms) if reported_inference_ms is not None
            else predict_ms)
        result.latency.preprocessing_ms.append(load_ms + preprocess_ms)
        result.latency.total_ms.append(load_ms + preprocess_ms + predict_ms)
        result.latency.overhead_ms.append(
            max(0.0, predict_ms - float(reported_inference_ms))
            if reported_inference_ms is not None else 0.0)

    if progress is not None:
        progress(total, total, "")

    result.compute_average_precision(predictions, annotations)
    return RunOutcome(result=result, config=config, predictions=predictions,
                      image_paths=image_paths)


# ---------------------------------------------------------------------------
# Pipeline adapter
# ---------------------------------------------------------------------------
def find_detector_node(pipeline, prefer: Sequence[str] = ("Object Detection",
                                                          "PCB Defect Detection",
                                                          "Defect Detection")):
    """The node whose `Detections` output supplies predictions.

    A node is only eligible if it **declares a `Detections` output**.  Preferred tool
    names are tried first, then any node with the output.

    The output check is not a formality.  An earlier version matched a node by its tool
    name alone, and `Defect Detection` reported only a defect *count* - so the evaluator
    selected it, read an output that did not exist, and produced zero detections for
    every image.  The run looked successful and reported 0 TP / all FN, which is exactly
    the kind of silent wrong answer this platform exists to prevent.  Returning `None`
    here makes the caller report "no detector in this workflow" instead.
    """
    nodes = getattr(pipeline, "nodes", {}) or {}

    def has_detections(node) -> bool:
        return "Detections" in (getattr(node, "outputs", {}) or {})

    for name in prefer:
        for node in nodes.values():
            if getattr(node, "tool_name", "") == name and has_detections(node):
                return node
    for node in nodes.values():
        if has_detections(node):
            return node
    return None


def pipeline_predictor(pipeline, image_input: str = "Image",
                       detector_node=None, detector_output: str = "Detections",
                       auto_connect: bool = True,
                       before_execute: Optional[Callable[[Any], None]] = None):
    """Adapt a `VisionPipeline` into an `(image) -> (detections, inference_ms)` callable.

    Uses the pipeline's own `execute_flow`, so the visual workflow the user built is the
    thing being evaluated.  There is no second execution engine.

    Four details matter for correctness:

    * The image is fed to the pipeline's **source** node through the override mechanism
      `ImageSourceTool.execute` already honours (`_override_image`), falling back to the
      named `image_input` node.  Injecting a global variable instead has no effect: the
      source node reads its own parameter, so the run would silently evaluate a
      different image than the caller passed.
    * `before_execute(pipeline)` runs just before each execution.  It exists because a
      pipeline may depend on per-image context that is not the image itself - the PCB
      workflow needs the board's design seed to supply its pad layout.  Setting node
      parameters here is honest about that dependency; hiding it inside the detector
      would not be.
    * The detector node's `elapsed_ms` is reported as the inference time, so graph
      traversal and the other nodes are not counted as model latency.
    * A detector node that did not run, or that returned `Error`, raises.  Returning
      "no detections" would turn an execution failure into a perfect-clean-board result
      and inflate precision.
    """
    node = detector_node or find_detector_node(pipeline)
    if node is None:
        raise ValueError(
            "pipeline has no detector node: none of the preferred tool names matched "
            "and no node declares a 'Detections' output")

    # Which node receives the image.
    target = None
    if auto_connect:
        incoming = {c.to_node for c in getattr(pipeline, "connections", [])}
        for nid, candidate in (getattr(pipeline, "nodes", {}) or {}).items():
            has_image_out = "Image" in (getattr(candidate, "outputs", {}) or {})
            if has_image_out and nid not in incoming:
                target = candidate
                break
    if target is None:
        for candidate in (getattr(pipeline, "nodes", {}) or {}).values():
            if getattr(candidate, "tool_name", "") == image_input:
                target = candidate
                break
    if target is None:
        target = node

    def predict(image: np.ndarray):
        if before_execute is not None:
            before_execute(pipeline)
        target._override_image = np.asarray(image)
        try:
            results = pipeline.execute_flow()
        finally:
            target._override_image = None

        produced = results.get(node.instance_id) if isinstance(results, dict) else None
        if produced is None:
            raise RuntimeError(
                f"detector node {node.instance_id!r} did not execute; the pipeline "
                f"returned results for "
                f"{sorted(results) if isinstance(results, dict) else results!r}")
        status = getattr(produced, "status", None)
        status_name = getattr(status, "value", str(status))
        if status_name.lower() == "error":
            raise RuntimeError(f"detector node failed: {produced.message}")
        outputs = getattr(produced, "outputs", None) or {}
        from vm_clone.evaluation.annotations import detections_from_outputs

        dets = detections_from_outputs(outputs, model_id=node.instance_id)
        ms = float(getattr(produced, "elapsed_ms", 0.0) or 0.0)
        return dets, ms

    return predict
