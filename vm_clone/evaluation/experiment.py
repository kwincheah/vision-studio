"""Experiment records: reproducibility, history, and comparison.

An experiment record captures everything needed to reproduce an evaluation and to
compare it fairly with another:

* what was run (pipeline identity and version, model reference),
* on what (dataset manifest, split, image count),
* how (IoU threshold, confidence threshold, working size, preprocessing),
* what came out (metrics, latency, per-class breakdown, errors), and
* where and when (software versions, platform, hardware, timestamp).

Two rules are enforced in code rather than left to convention:

1. **Records are never overwritten.**  `ExperimentStore.save` takes a timestamp and a
   short content hash and refuses to replace an existing file; a repeat run produces a
   new record with a suffix.  Silent overwriting would destroy the history that makes a
   comparison meaningful.
2. **A comparison refuses mismatched conditions.**  Comparing metrics produced with
   different IoU thresholds or different datasets is not a comparison, so
   `compare` raises unless the caller explicitly acknowledges the difference.

The store is a directory of one JSON file per run plus an index, so records survive a
crash mid-write (each file is written atomically) and can be read without the tool.
"""
from __future__ import annotations

import json
import os
import platform
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from vm_clone.core.fileio import atomic_write_json
from vm_clone.evaluation.metrics import EvaluationResult
from vm_clone.evaluation.runner import find_detector_node

#: Bumped when the record schema changes in a way a reader must know about.
SCHEMA_VERSION = 1


def _software_versions() -> Dict[str, str]:
    """The versions that affect a result, recorded so a difference is explainable."""
    versions = {"python": platform.python_version()}
    try:
        import numpy
        versions["numpy"] = numpy.__version__
    except Exception:                                   # noqa: BLE001
        pass
    try:
        import cv2
        versions["opencv"] = cv2.__version__
    except Exception:                                   # noqa: BLE001
        pass
    try:
        import PyQt6.QtCore as qtcore
        versions["pyqt6"] = qtcore.QT_VERSION_STR
    except Exception:                                   # noqa: BLE001
        pass
    try:
        import ultralytics
        versions["ultralytics"] = ultralytics.__version__
    except Exception:                                   # noqa: BLE001
        pass
    try:
        from vm_clone import __version__ as app_version
        versions["apex"] = str(app_version)
    except Exception:                                   # noqa: BLE001
        versions["apex"] = "unknown"
    return versions


def _hardware() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }
    try:
        import torch
        info["torch_device"] = "cuda" if torch.cuda.is_available() else "cpu"
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
    except Exception:                                   # noqa: BLE001
        pass
    return info


def _safe_model_reference(model_id: str) -> Dict[str, Any]:
    """Describe a model reference without assuming it is a path or a real file.

    A record must be honest about what a model was: for a classical detector there is no
    file, and reporting a missing file would be misleading.  When a path is given, its
    size and mtime are recorded so a changed file is detectable.
    """
    ref: Dict[str, Any] = {"id": model_id or "", "kind": "unknown"}
    if not model_id:
        return ref
    if os.path.isfile(model_id):
        try:
            stat = os.stat(model_id)
            ref.update({"kind": "file", "path": os.path.abspath(model_id),
                        "size_bytes": stat.st_size,
                        "modified": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                  time.localtime(stat.st_mtime))})
        except OSError as exc:
            ref.update({"kind": "file", "path": os.path.abspath(model_id),
                        "stat_error": str(exc)})
    else:
        ref.update({"kind": "identifier"})
    return ref


@dataclass
class Experiment:
    """One recorded evaluation run."""
    #: short human label, e.g. "reference detector 40 boards"
    name: str = ""
    #: ISO timestamp of when the run completed
    timestamp: str = ""
    status: str = "ok"                   # ok | failed | cancelled | partial
    #: identity and version of the workflow that produced the predictions
    workflow: Dict[str, Any] = field(default_factory=dict)
    #: model reference, as `_safe_model_reference` describes it
    model: Dict[str, Any] = field(default_factory=dict)
    #: dataset manifest and split
    dataset: Dict[str, Any] = field(default_factory=dict)
    #: inference and evaluation settings
    settings: Dict[str, Any] = field(default_factory=dict)
    #: the metric payload from `EvaluationResult.to_dict`
    metrics: Dict[str, Any] = field(default_factory=dict)
    #: software and hardware context
    environment: Dict[str, Any] = field(default_factory=dict)
    #: errors encountered during the run
    errors: List[Dict[str, Any]] = field(default_factory=list)
    #: free-form notes, e.g. why this run was made
    notes: str = ""
    schema_version: int = SCHEMA_VERSION

    # -- convenience accessors -------------------------------------------
    @property
    def precision(self) -> Optional[float]:
        return self.metrics.get("precision")

    @property
    def recall(self) -> Optional[float]:
        return self.metrics.get("recall")

    @property
    def f1(self) -> Optional[float]:
        return self.metrics.get("f1")

    @property
    def map50(self) -> Optional[float]:
        return self.metrics.get("mAP@IoU")

    @property
    def fp(self) -> int:
        return int(self.metrics.get("fp", 0) or 0)

    @property
    def fn(self) -> int:
        return int(self.metrics.get("fn", 0) or 0)

    @property
    def tp(self) -> int:
        return int(self.metrics.get("tp", 0) or 0)

    @property
    def iou_threshold(self) -> Optional[float]:
        return self.settings.get("iou_threshold")

    @property
    def dataset_name(self) -> str:
        return str(self.dataset.get("name", ""))

    @property
    def split(self) -> str:
        return str(self.dataset.get("split", ""))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "timestamp": self.timestamp,
            "status": self.status,
            "workflow": self.workflow,
            "model": self.model,
            "dataset": self.dataset,
            "settings": self.settings,
            "metrics": self.metrics,
            "environment": self.environment,
            "errors": self.errors,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Experiment":
        return cls(
            name=str(d.get("name", "")),
            timestamp=str(d.get("timestamp", "")),
            status=str(d.get("status", "ok")),
            workflow=dict(d.get("workflow") or {}),
            model=dict(d.get("model") or {}),
            dataset=dict(d.get("dataset") or {}),
            settings=dict(d.get("settings") or {}),
            metrics=dict(d.get("metrics") or {}),
            environment=dict(d.get("environment") or {}),
            errors=list(d.get("errors") or []),
            notes=str(d.get("notes", "")),
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
        )

    # -- construction ----------------------------------------------------
    @classmethod
    def from_run(cls, outcome, name: str = "", pipeline=None,
                 notes: str = "") -> "Experiment":
        """Build a record from a `RunOutcome` (and optionally the pipeline used)."""
        config = outcome.config
        result: EvaluationResult = outcome.result
        workflow: Dict[str, Any] = {"kind": config.predictor_kind}
        if pipeline is not None:
            workflow.update({
                "name": getattr(pipeline, "name", ""),
                # A content hash makes an edited-but-same-named workflow detectable,
                # which a name or version string alone would not be.
                "fingerprint": pipeline_fingerprint(pipeline),
                "node_count": len(getattr(pipeline, "nodes", {}) or {}),
                "connection_count": len(getattr(pipeline, "connections", []) or []),
                "detector_node": getattr(
                    find_detector_node(pipeline), "tool_name", None),
            })
        if config.detector_variant:
            workflow["detector_variant"] = config.detector_variant

        status = "ok"
        if result.errors:
            status = "partial"
        if result.images_evaluated == 0:
            status = "failed"

        return cls(
            name=name or f"{config.dataset_name or 'dataset'} run",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            status=status,
            workflow=workflow,
            model=_safe_model_reference(config.model_id),
            dataset={
                "name": config.dataset_name or result.dataset_name,
                "split": config.split,
                "images_evaluated": result.images_evaluated,
                "empty_images": result.empty_images,
                "ground_truth_boxes": result.gt_count,
                "manifest": dict(config.extras.get("dataset_manifest", {}))
                if config.extras else {},
                "generator": (config.extras or {}).get("dataset_generator", ""),
            },
            settings={
                "iou_threshold": config.iou_threshold,
                "confidence_threshold": config.confidence_threshold,
                "working_size": list(config.working_size) if config.working_size
                else None,
                "matching_policy": "greedy by descending confidence, one-to-one, "
                                   "per class, IoU >= threshold",
                "extra": dict(config.extras or {}),
            },
            metrics=result.to_dict(),
            environment={"software": _software_versions(), "hardware": _hardware()},
            errors=result.errors,
            notes=notes,
        )


def pipeline_fingerprint(pipeline) -> str:
    """A short stable hash of a pipeline's structure and parameters.

    Uses the serialised form, so it changes when a node's parameters change - which is
    exactly when two runs are no longer comparable.
    """
    import hashlib

    try:
        payload = json.dumps(pipeline.to_dict(), sort_keys=True, default=str)
    except Exception as exc:                            # noqa: BLE001
        return f"unhashable:{type(exc).__name__}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
class IncomparableExperiments(ValueError):
    """Raised when two experiments were not run under comparable conditions."""


#: Settings that must match for a comparison to be valid.
_REQUIRED_MATCH = ("iou_threshold", "split")


def _dig(record: Experiment, path: str):
    if path == "split":
        return record.split
    if path == "iou_threshold":
        return record.iou_threshold
    return None


def comparability(a: Experiment, b: Experiment) -> List[str]:
    """Reasons these two records cannot be compared.  Empty means comparable."""
    problems: List[str] = []
    if a.dataset_name != b.dataset_name:
        problems.append(f"different datasets: {a.dataset_name!r} vs {b.dataset_name!r}")
    for key in _REQUIRED_MATCH:
        va, vb = _dig(a, key), _dig(b, key)
        if va != vb:
            problems.append(f"different {key}: {va!r} vs {vb!r}")
    if a.status == "failed" or b.status == "failed":
        problems.append("at least one run failed, so its metrics are not meaningful")
    return problems


@dataclass
class ComparisonRow:
    """One experiment's line in a comparison."""
    name: str
    timestamp: str
    metrics: Dict[str, Any]
    per_class: Dict[str, Any]
    deltas: Dict[str, Optional[float]] = field(default_factory=dict)


@dataclass
class Comparison:
    """A side-by-side comparison of two or more experiments."""
    rows: List[ComparisonRow]
    warnings: List[str] = field(default_factory=list)
    #: statements about trade-offs, not a ranking
    observations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows": [{"name": r.name, "timestamp": r.timestamp, "metrics": r.metrics,
                      "per_class": r.per_class, "deltas": r.deltas} for r in self.rows],
            "warnings": self.warnings,
            "observations": self.observations,
        }


def _delta(new: Optional[float], base: Optional[float]) -> Optional[float]:
    if new is None or base is None:
        return None
    return round(float(new) - float(base), 6)


def compare(experiments: Sequence[Experiment], base_index: int = 0,
            allow_incomparable: bool = False) -> Comparison:
    """Compare experiments against `base_index`.

    Deltas are reported against the baseline, and the observations describe
    **trade-offs** rather than a winner.  A model with higher recall and more false
    positives has not been shown to be better; it has been shown to sit at a different
    point on the same curve, and the report says so.
    """
    if len(experiments) < 2:
        raise ValueError("a comparison needs at least two experiments")
    if not 0 <= base_index < len(experiments):
        raise IndexError(f"base_index {base_index} out of range")

    base = experiments[base_index]
    warnings: List[str] = []
    for i, other in enumerate(experiments):
        if i == base_index:
            continue
        problems = comparability(base, other)
        if problems:
            message = (f"'{other.name}' is not directly comparable with "
                       f"'{base.name}': " + "; ".join(problems))
            if not allow_incomparable:
                raise IncomparableExperiments(message)
            warnings.append(message)

    metric_keys = ("precision", "recall", "f1", "mAP@IoU", "tp", "fp", "fn",
                   "duplicates", "images_evaluated")
    rows: List[ComparisonRow] = []
    for i, exp in enumerate(experiments):
        metrics = {k: exp.metrics.get(k) for k in metric_keys}
        lat = (exp.metrics.get("latency") or {}).get("inference") or {}
        metrics["inference_mean_ms"] = lat.get("mean")
        metrics["inference_throughput_fps"] = (
            exp.metrics.get("latency") or {}).get("inference_throughput_fps")
        deltas = {} if i == base_index else {
            k: _delta(_numeric(exp.metrics.get(k)), _numeric(base.metrics.get(k)))
            for k in ("precision", "recall", "f1", "mAP@IoU", "tp", "fp", "fn")
        }
        rows.append(ComparisonRow(
            name=exp.name, timestamp=exp.timestamp, metrics=metrics,
            per_class=exp.metrics.get("per_class") or {}, deltas=deltas))

    observations = _observations(base, experiments, base_index)
    return Comparison(rows=rows, warnings=warnings, observations=observations)


def _numeric(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _observations(base: Experiment, experiments: Sequence[Experiment],
                  base_index: int) -> List[str]:
    """Describe the trade-offs, and refuse to declare a winner."""
    out: List[str] = []
    for i, other in enumerate(experiments):
        if i == base_index:
            continue
        name = f"'{other.name}' vs '{base.name}'"
        dp = _delta(_numeric(other.metrics.get("precision")),
                    _numeric(base.metrics.get("precision")))
        dr = _delta(_numeric(other.metrics.get("recall")),
                    _numeric(base.metrics.get("recall")))
        dfp = _delta(_numeric(other.metrics.get("fp")), _numeric(base.metrics.get("fp")))
        dfn = _delta(_numeric(other.metrics.get("fn")), _numeric(base.metrics.get("fn")))

        if dp is not None and dr is not None:
            if dp > 0 and dr < 0:
                out.append(f"{name}: precision +{dp:.4f} but recall {dr:.4f} - "
                           f"fewer false alarms, more missed defects.")
            elif dr > 0 and dp < 0:
                out.append(f"{name}: recall +{dr:.4f} but precision {dp:.4f} - "
                           f"finds more defects, raises more false alarms.")
            elif dp > 0 and dr > 0:
                out.append(f"{name}: precision +{dp:.4f} and recall +{dr:.4f} - "
                           f"dominates on these two metrics.")
            elif dp < 0 and dr < 0:
                out.append(f"{name}: precision {dp:.4f} and recall {dr:.4f} - "
                           f"dominated on these two metrics.")
            else:
                out.append(f"{name}: precision {dp:+.4f}, recall {dr:+.4f} - "
                           f"no material difference on these metrics.")
        if dfp is not None and dfn is not None:
            out.append(f"    false positives {dfp:+.0f}, false negatives {dfn:+.0f} "
                       f"(counts, not rates)")
        si = other.settings.get("confidence_threshold")
        sb = base.settings.get("confidence_threshold")
        if si != sb:
            out.append(f"    NOTE: confidence thresholds differ ({sb} vs {si}), so "
                       f"part of this difference is the operating point, not the model.")
        if other.workflow.get("fingerprint") and \
                other.workflow.get("fingerprint") != base.workflow.get("fingerprint"):
            out.append(f"    NOTE: the workflows differ "
                       f"({base.workflow.get('fingerprint')} vs "
                       f"{other.workflow.get('fingerprint')}).")

    out.append("No metric here establishes that one configuration is universally "
               "better; a higher recall with more false positives is a different "
               "operating point, not an improvement.")
    return out


def render_comparison(comparison: Comparison, width: int = 78) -> str:
    """A text table of a comparison, with undefined metrics shown as 'n/a'."""
    def fmt(value, digits: int = 4) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)

    lines = ["=" * width, "EXPERIMENT COMPARISON", "=" * width]
    if comparison.warnings:
        lines.append("WARNINGS:")
        for w in comparison.warnings:
            lines.append(f"  ! {w}")
        lines.append("")
    header = f"{'metric':<26}" + "".join(f"{r.name[:18]:>20}" for r in comparison.rows)
    lines.append(header)
    lines.append("-" * len(header))
    keys = ("precision", "recall", "f1", "mAP@IoU", "tp", "fp", "fn", "duplicates",
            "images_evaluated", "inference_mean_ms", "inference_throughput_fps")
    for key in keys:
        row = f"{key:<26}"
        for r in comparison.rows:
            row += f"{fmt(r.metrics.get(key)):>20}"
        lines.append(row)
    lines.append("")
    for i, r in enumerate(comparison.rows):
        if not r.deltas:
            continue
        lines.append(f"delta vs baseline ('{r.name}'):")
        for key, value in r.deltas.items():
            if value is None:
                lines.append(f"   {key:<20} n/a (one side undefined)")
            else:
                lines.append(f"   {key:<20} {value:+.4f}")
        lines.append("")
    lines.append("trade-offs:")
    for obs in comparison.observations:
        lines.append(f"  {obs}")
    lines.append("=" * width)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(text: str, limit: int = 48) -> str:
    return _SAFE.sub("-", text.strip())[:limit].strip("-") or "experiment"


@dataclass
class ExperimentStore:
    """A directory of experiment records, with an index.

    One JSON file per run, written atomically.  `save` refuses to reuse a filename, so
    history is append-only by construction: a repeated run gets a suffix rather than
    replacing the earlier record.
    """
    directory: str

    INDEX = "index.json"
    RECORD_DIR = "records"

    def __post_init__(self):
        self.directory = os.path.abspath(self.directory)
        os.makedirs(os.path.join(self.directory, self.RECORD_DIR), exist_ok=True)

    @property
    def records_dir(self) -> str:
        return os.path.join(self.directory, self.RECORD_DIR)

    @property
    def index_path(self) -> str:
        return os.path.join(self.directory, self.INDEX)

    def _existing_names(self) -> set:
        try:
            return {n for n in os.listdir(self.records_dir) if n.endswith(".json")}
        except OSError:
            return set()

    def save(self, experiment: Experiment) -> str:
        """Write a record, never replacing an existing one.  Returns its path."""
        base = f"{_slug(experiment.timestamp)}_{_slug(experiment.name)}"
        candidate = f"{base}.json"
        existing = self._existing_names()
        counter = 2
        while candidate in existing:
            candidate = f"{base}_{counter}.json"
            counter += 1
        path = os.path.join(self.records_dir, candidate)
        atomic_write_json(path, experiment.to_dict())
        self._rebuild_index()
        return path

    def load(self, path: str) -> Experiment:
        with open(path, "r", encoding="utf-8") as fh:
            return Experiment.from_dict(json.load(fh))

    def list_records(self) -> List[Dict[str, Any]]:
        """The index, newest last.  Read from disk so an external write is picked up."""
        return self._read_index()

    def load_all(self) -> List[Experiment]:
        out: List[Experiment] = []
        for entry in self.list_records():
            try:
                out.append(self.load(entry["path"]))
            except (OSError, ValueError, KeyError):
                continue
        return out

    def find(self, needle: str) -> List[Experiment]:
        """Records whose name, dataset or timestamp contains `needle`."""
        needle = needle.lower()
        out = []
        for exp in self.load_all():
            haystack = " ".join([exp.name, exp.dataset_name, exp.timestamp,
                                 str(exp.model.get("id", ""))]).lower()
            if needle in haystack:
                out.append(exp)
        return out

    def _read_index(self) -> List[Dict[str, Any]]:
        try:
            with open(self.index_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return list(data.get("records") or [])
        except (OSError, ValueError):
            return self._rebuild_index()

    def _rebuild_index(self) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        try:
            names = sorted(n for n in os.listdir(self.records_dir)
                           if n.endswith(".json"))
        except OSError:
            names = []
        for name in names:
            path = os.path.join(self.records_dir, name)
            try:
                exp = self.load(path)
            except (OSError, ValueError):
                continue
            entries.append({
                "path": path,
                "name": exp.name,
                "timestamp": exp.timestamp,
                "status": exp.status,
                "dataset": exp.dataset_name,
                "split": exp.split,
                "model": exp.model.get("id", ""),
                "precision": exp.precision,
                "recall": exp.recall,
                "f1": exp.f1,
                "mAP@IoU": exp.map50,
                "fp": exp.fp,
                "fn": exp.fn,
                "errors": len(exp.errors),
            })
        atomic_write_json(self.index_path, {"records": entries})
        return entries
