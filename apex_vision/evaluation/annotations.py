"""Annotation and detection data models for inspection evaluation.

Everything the evaluation layer consumes is defined here, in one place, with explicit
units and coordinate conventions:

* **Boxes are absolute pixels**, `(x, y, w, h)`, origin top-left, matching the
  `Object Detection` node's `Detections` output and `ImageCanvasWidget`'s overlays.
  They are stored in the file as `[x, y, w, h]` too, so a file can be read by eye
  against a screenshot without a mental conversion.
* **Classes are strings.**  A detector may emit a numeric class id; the loader maps it
  through the model's `names` when one is supplied, otherwise it stays a string.  A
  class mismatch is never treated as a match.
* **Confidence is `[0, 1]`.**  A ground-truth annotation has no confidence; it is not
  a prediction that can be right or wrong.

The formats supported are deliberately the two that the existing codebase and the
existing detector already speak:

* this project's JSON annotation file (lossless, carries image metadata), and
* YOLO/Ultralytics label text (`class cx cy w h`, normalised), for real training data.

Nothing here computes a metric; that is `metrics.py`, and matching is `matching.py`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: A box is (x, y, w, h) in absolute pixels.
Box = Tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def box_area(box: Box) -> float:
    """Area in square pixels; never negative for a degenerate box."""
    _, _, w, h = box
    return max(0.0, float(w)) * max(0.0, float(h))


def box_to_xyxy(box: Box) -> Tuple[float, float, float, float]:
    """Convert (x, y, w, h) to (x1, y1, x2, y2)."""
    x, y, w, h = box
    return float(x), float(y), float(x) + float(w), float(y) + float(h)


def iou(a: Box, b: Box) -> float:
    """Intersection over union of two (x, y, w, h) boxes.

    Returns 0.0 when the boxes do not overlap and when either has zero area, so a
    degenerate box can never match anything.
    """
    ax1, ay1, ax2, ay2 = box_to_xyxy(a)
    bx1, by1, bx2, by2 = box_to_xyxy(b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    union = box_area(a) + box_area(b) - inter
    if union <= 0.0:
        return 0.0
    return float(inter / union)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
@dataclass
class Detection:
    """One predicted box, as emitted by a detector node."""
    box: Box
    label: str
    score: float = 1.0
    #: which model produced it; recorded so two experiments are comparable
    model_id: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {"box": [round(float(v), 3) for v in self.box],
             "label": str(self.label), "score": round(float(self.score), 6)}
        if self.model_id:
            d["model_id"] = self.model_id
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Detection":
        box = d.get("box") or d.get("bbox") or [0, 0, 0, 0]
        return cls(box=_as_box(box), label=str(d.get("label", d.get("class", ""))),
                   score=float(d.get("score", d.get("confidence", 1.0))),
                   model_id=str(d.get("model_id", "")),
                   extra=dict(d.get("extra") or {}))


@dataclass
class Annotation:
    """One ground-truth box.  Has no confidence: it is not a prediction."""
    box: Box
    label: str
    #: free-form provenance, e.g. {"source": "synthetic", "defect": "scratch"}
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {"box": [round(float(v), 3) for v in self.box], "label": str(self.label)}
        if self.meta:
            d["meta"] = self.meta
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Annotation":
        box = d.get("box") or d.get("bbox") or [0, 0, 0, 0]
        return cls(box=_as_box(box), label=str(d.get("label", d.get("class", ""))),
                   meta=dict(d.get("meta") or {}))


@dataclass
class ImageRecord:
    """One dataset item: an image, its ground truth, and any predictions.

    `predictions` is populated by the evaluation runner, not on load, so the same
    record type carries an item through load -> predict -> match.
    """
    image_path: str
    annotations: List[Annotation] = field(default_factory=list)
    #: image size (width, height) in pixels; filled from the file when known
    size: Optional[Tuple[int, int]] = None
    #: opaque per-image metadata from the annotation file
    meta: Dict[str, Any] = field(default_factory=dict)
    predictions: List[Detection] = field(default_factory=list)
    #: what the held-out split this image belongs to, e.g. "test" / "train"
    split: str = "test"

    @property
    def name(self) -> str:
        return os.path.basename(self.image_path)

    @property
    def is_empty(self) -> bool:
        """No ground truth: a legitimate image, and the source of easy false positives."""
        return not self.annotations

    def labels(self) -> List[str]:
        return [a.label for a in self.annotations]

    def predicted_labels(self) -> List[str]:
        return [p.label for p in self.predictions]

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "image": self.image_path,
            "annotations": [a.to_dict() for a in self.annotations],
        }
        if self.size:
            d["size"] = list(self.size)
        if self.meta:
            d["meta"] = self.meta
        if self.split != "test":
            d["split"] = self.split
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ImageRecord":
        size = d.get("size")
        return cls(
            image_path=str(d.get("image", "")),
            annotations=[Annotation.from_dict(a) for a in (d.get("annotations") or [])],
            size=(int(size[0]), int(size[1])) if size else None,
            meta=dict(d.get("meta") or {}),
            split=str(d.get("split", "test")),
        )


def _as_box(value: Sequence[Any]) -> Box:
    """Coerce a 4-sequence to a float box, tolerating short or malformed input."""
    items = list(value or [])
    while len(items) < 4:
        items.append(0.0)
    try:
        x, y, w, h = (float(v) for v in items[:4])
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0, 0.0)
    # A negative width/height is meaningless; normalise rather than propagate it.
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    return (x, y, w, h)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
@dataclass
class Dataset:
    """A labelled image set with a declared split.

    The split is explicit because the evaluation rules require it: metrics computed on
    `train` are not evidence about generalisation, and the report records which split
    was used so a result cannot be presented as held-out performance when it is not.
    """
    name: str
    records: List[ImageRecord] = field(default_factory=list)
    #: absolute or dataset-relative root for the image paths
    root: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    #: the split this dataset is intended for
    SPLITS = ("train", "val", "test")

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self) -> Iterable[ImageRecord]:
        return iter(self.records)

    def resolve(self, record: ImageRecord) -> str:
        """Absolute path of a record's image."""
        if os.path.isabs(record.image_path):
            return record.image_path
        return os.path.normpath(os.path.join(self.root, record.image_path))

    def label_set(self) -> List[str]:
        labels = set()
        for r in self.records:
            labels.update(r.labels())
        return sorted(labels)

    def split_of(self, record: ImageRecord) -> str:
        return record.split or self.meta.get("split", "test")

    def counts(self) -> Dict[str, int]:
        return {
            "images": len(self.records),
            "annotations": sum(len(r.annotations) for r in self.records),
            "empty_images": sum(1 for r in self.records if r.is_empty),
            "labelled_images": sum(1 for r in self.records if not r.is_empty),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "root": self.root,
            "meta": self.meta,
            "images": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any], root: str = "") -> "Dataset":
        return cls(
            name=str(d.get("name", "dataset")),
            records=[ImageRecord.from_dict(r) for r in (d.get("images") or [])],
            root=root or str(d.get("root", "")),
            meta=dict(d.get("meta") or {}),
        )

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1)
        return path

    @classmethod
    def load(cls, path: str) -> "Dataset":
        """Load an annotation file.

        `root` defaults to the file's own directory so a dataset is relocatable: the
        stored image paths are relative to it.
        """
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        root = data.get("root") or os.path.dirname(os.path.abspath(path))
        if not os.path.isabs(root):
            root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)),
                                                 root))
        return cls.from_dict(data, root=root)


# ---------------------------------------------------------------------------
# YOLO / Ultralytics label format
# ---------------------------------------------------------------------------
def load_yolo_labels(label_path: str, image_width: int, image_height: int,
                     class_names: Optional[Sequence[str]] = None) -> List[Annotation]:
    """Read a YOLO label file into absolute-pixel annotations.

    Each line is `class_id cx cy w h` with the geometry normalised to `[0, 1]`.
    Malformed lines are skipped rather than aborting the load: a partially written
    label file should cost those annotations, not the whole dataset.
    """
    out: List[Annotation] = []
    if not os.path.exists(label_path) or image_width <= 0 or image_height <= 0:
        return out
    with open(label_path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                cls_id = int(float(parts[0]))
                cx, cy, nw, nh = (float(v) for v in parts[1:5])
            except ValueError:
                continue
            label = (class_names[cls_id] if class_names and 0 <= cls_id < len(class_names)
                     else str(cls_id))
            w = nw * image_width
            h = nh * image_height
            x = cx * image_width - w / 2.0
            y = cy * image_height - h / 2.0
            out.append(Annotation(box=(x, y, w, h), label=label,
                                 meta={"source": "yolo", "line": lineno}))
    return out


def save_yolo_labels(path: str, annotations: Sequence[Annotation],
                     class_names: Sequence[str], image_width: int,
                     image_height: int) -> str:
    """Write annotations in YOLO label format (normalised centre form)."""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image size must be positive to normalise labels")
    index = {name: i for i, name in enumerate(class_names)}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for a in annotations:
            cid = index.get(a.label, 0)
            x, y, w, h = a.box
            cx = (x + w / 2.0) / image_width
            cy = (y + h / 2.0) / image_height
            fh.write(f"{cid} {cx:.6f} {cy:.6f} {w / image_width:.6f} "
                     f"{h / image_height:.6f}\n")
    return path


# ---------------------------------------------------------------------------
# Predictions from a detector node
# ---------------------------------------------------------------------------
def detections_from_outputs(outputs: Dict[str, Any],
                            classes_key: str = "Classes",
                            boxes_key: str = "Boxes",
                            scores_key: str = "Scores",
                            model_id: str = "") -> List[Detection]:
    """Build `Detection` records from a detector node's outputs.

    The three parallel lists are zipped to the *shortest* length: a detector that
    returns mismatched list lengths has a bug, and silently padding with a default
    confidence would turn that bug into fabricated metric input.
    """
    boxes = list(outputs.get(boxes_key) or [])
    labels = list(outputs.get(classes_key) or [])
    scores = list(outputs.get(scores_key) or [])

    n = min(len(boxes), len(labels), len(scores) or len(boxes))
    if not boxes or n == 0:
        return []

    out: List[Detection] = []
    for i in range(n):
        try:
            score = float(scores[i]) if i < len(scores) else 1.0
        except (TypeError, ValueError):
            score = 1.0
        out.append(Detection(box=_as_box(boxes[i]),
                             label=str(labels[i]) if i < len(labels) else "",
                             score=score, model_id=model_id))
    return out
