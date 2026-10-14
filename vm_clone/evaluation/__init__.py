"""Inspection evaluation: ground-truth matching, metrics, failure analysis.

The layer exists so an inspection pipeline's output can be *measured* rather than
eyeballed.  It is deliberately independent of Qt: the GUI, the CLI runner and the tests
all call the same functions, so a metric shown in the interface is the same number the
runner writes to a file.

    annotations  -- data models, dataset loading/saving, detector-output adaptation
    matching     -- the prediction-to-ground-truth policy (the correctness-critical part)
    metrics      -- counts, rates, mAP, latency, and the text report
    runner       -- batch execution of a pipeline over a dataset, with stage timings
    experiment   -- reproducible experiment records, persistence and comparison
"""
from vm_clone.evaluation.annotations import (  # noqa: F401
    Annotation, Dataset, Detection, ImageRecord, box_area, detections_from_outputs,
    iou, load_yolo_labels, save_yolo_labels,
)
from vm_clone.evaluation.matching import (  # noqa: F401
    DEFAULT_IOU_THRESHOLD, ImageMatchResult, match_image,
)
from vm_clone.evaluation.metrics import (  # noqa: F401
    ClassMetrics, EvaluationResult, LatencyStats, evaluate_records, render_text_report,
)
from vm_clone.evaluation.runner import (  # noqa: F401
    RunConfig, RunOutcome, find_detector_node, pipeline_predictor, run_dataset,
)
from vm_clone.evaluation.experiment import (  # noqa: F401
    Comparison, Experiment, ExperimentStore, IncomparableExperiments, comparability,
    compare, pipeline_fingerprint, render_comparison,
)

__all__ = [
    "Annotation", "Dataset", "Detection", "ImageRecord", "box_area",
    "detections_from_outputs", "iou", "load_yolo_labels", "save_yolo_labels",
    "DEFAULT_IOU_THRESHOLD", "ImageMatchResult", "match_image",
    "ClassMetrics", "EvaluationResult", "LatencyStats", "evaluate_records",
    "render_text_report",
    "RunConfig", "RunOutcome", "find_detector_node", "pipeline_predictor", "run_dataset",
    "Comparison", "Experiment", "ExperimentStore", "IncomparableExperiments",
    "comparability", "compare", "pipeline_fingerprint", "render_comparison",
]
