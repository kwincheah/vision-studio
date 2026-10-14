"""PCB defect detection as a first-class workflow node.

Exists so the inspection pipeline can be **built visually** the way every other tool is,
and then evaluated through the platform.  The node wraps the deterministic classical
detector in `pcb_defect_dataset.reference_pcb_detector`; it is a real detector that
decides from pixels, and it exposes an operating-point parameter so two runs of the same
workflow can be compared as two experiments.

Why a classical detector rather than only the YOLO node
-------------------------------------------------------
The repository's `Object Detection` node needs a trained model.  The weights that ship
here are COCO-pretrained, and COCO has no PCB defect classes, so a YOLO-based evaluation
on this data would report near-zero recall - a true result, but one that says nothing
about the platform.  The classical detector gives a genuine, reproducible detector with
no external model, so the evaluation, failure-analysis and comparison features can be
demonstrated and *tested* end to end.  Both nodes implement the same output contract, so
evaluating a YOLO workflow uses exactly the same code path.

Design-data inputs
------------------
`Pad Layout` and `Trace Layout` are optional inputs carrying the board's design geometry.
A real AOI system has the CAD data, and using it to decide whether a dark blob is a pit
on a pad or missing copper on the plane is standard inspection logic.  They are inputs
rather than hidden state so the dependency is visible in the workflow.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from vm_clone.core.base_tool import (
    DataType, ToolExecutionResult, ToolPort, ToolStatus, VisionToolBase,
)
from vm_clone.core.registry import register_tool


@register_tool
class PCBBoardLayoutTool(VisionToolBase):
    """Supplies a board's pad and trace geometry from its design seed.

    A real AOI system reads this from the CAD data for the product being inspected.  Here
    it is generated from the same seed the dataset generator used, so a visually built
    workflow can be given the design geometry as an explicit input - which keeps the
    dependency visible in the graph rather than hidden inside the detector.
    """
    category = "Acquisition"
    tool_name = "PCB Board Layout"
    description = ("Board design geometry (pad and trace rectangles) for a synthetic PCB, "
                   "supplied to the defect detector as inspection context.")

    def _init_ports(self):
        self.inputs["Trigger"] = ToolPort("Trigger", DataType.BOOLEAN,
                                          "Optional run gate")
        self.outputs["Pad Layout"] = ToolPort("Pad Layout", DataType.ANY,
                                              "List of [x, y, w, h] pad rectangles")
        self.outputs["Trace Layout"] = ToolPort("Trace Layout", DataType.ANY,
                                                "List of [x, y, w, h] trace rectangles")

    def _init_parameters(self):
        self.parameters = {
            #: must match the dataset generator's seed for the image being inspected
            "board_seed": 20230510,
            "image_width": 640,
            "image_height": 480,
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        from vm_clone.samples.pcb_defect_dataset import board_layout, trace_boxes

        try:
            seed = int(self.parameters.get("board_seed", 0))
            size = (int(self.parameters.get("image_width", 640)),
                    int(self.parameters.get("image_height", 480)))
        except (TypeError, ValueError) as exc:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Board layout parameters are not integers: {exc}")

        try:
            pads, _traces = board_layout(seed, size)
            traces = trace_boxes(seed, size)
        except Exception as exc:                       # noqa: BLE001 - surfaced
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Could not derive the board layout: {type(exc).__name__}: {exc}")

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Layout for seed {seed}: {len(pads)} pads, {len(traces)} traces",
            outputs={
                "Pad Layout": [list(p) for p in pads],
                "Trace Layout": [list(t) for t in traces],
            },
        )


@register_tool
class PCBDefectDetectionTool(VisionToolBase):
    category = "Recognition"
    tool_name = "PCB Defect Detection"
    description = ("Deterministic classical PCB defect detector: finds scratches, voids, "
                   "missing paste and missing copper, and emits structured detections "
                   "for evaluation and failure analysis.")

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE,
                                        "Board image to inspect")
        self.inputs["Pad Layout"] = ToolPort(
            "Pad Layout", DataType.ANY,
            "Optional list of [x, y, w, h] pad rectangles from the board design")
        self.inputs["Trace Layout"] = ToolPort(
            "Trace Layout", DataType.ANY,
            "Optional list of [x, y, w, h] trace rectangles from the board design")

        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE,
                                         "Input image with defect overlays")
        self.outputs["Count"] = ToolPort("Count", DataType.VALUE,
                                         "Number of defects detected")
        self.outputs["Boxes"] = ToolPort("Boxes", DataType.ANY,
                                         "Defect boxes [[x, y, w, h], ...]")
        self.outputs["Classes"] = ToolPort("Classes", DataType.ANY,
                                           "Defect class per box")
        self.outputs["Scores"] = ToolPort("Scores", DataType.ANY,
                                          "Detector confidence per box")
        self.outputs["Detections"] = ToolPort(
            "Detections", DataType.ANY,
            "Structured detection records, consumed by dataset evaluation")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING,
                                          "'NG' when any defect was found, else 'OK'")

    def _init_parameters(self):
        self.parameters = {
            #: the operating point; see DETECTOR_VARIANTS in pcb_defect_dataset
            "variant": "reference",
            "confidence_threshold": 0.0,
            "min_area": 60,
            "dark_floor": 30,
            "max_detections": 40,
        }

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _as_boxes(value: Any) -> Optional[List[List[int]]]:
        """Coerce a layout input into a list of integer rectangles, or None."""
        if value is None:
            return None
        if isinstance(value, np.ndarray):
            value = value.tolist()
        if not isinstance(value, (list, tuple)) or not value:
            return None
        out: List[List[int]] = []
        for item in value:
            try:
                x, y, w, h = (int(round(float(v))) for v in list(item)[:4])
            except (TypeError, ValueError):
                continue
            out.append([x, y, w, h])
        return out or None

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        from vm_clone.samples.pcb_defect_dataset import (
            DETECTOR_VARIANTS, reference_pcb_detector,
        )

        image = context.get("Image")
        if image is None:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message="No image connected to the Image input.")
        if not isinstance(image, np.ndarray) or image.size == 0:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Image input is not a usable image ({type(image).__name__}).")

        variant = str(self.parameters.get("variant", "reference"))
        params = dict(DETECTOR_VARIANTS.get(variant) or DETECTOR_VARIANTS["reference"])

        # Node parameters override the variant defaults, so a user can tune the operating
        # point on the canvas without editing the code.
        for key in ("min_area", "dark_floor", "max_dimensions", "max_detections",
                    "bright_threshold", "dark_sigma"):
            declared = self.parameters.get(key)
            if declared is not None and key in params:
                try:
                    params[key] = int(declared)
                except (TypeError, ValueError):
                    pass

        try:
            detections = reference_pcb_detector(
                image,
                pad_boxes=self._as_boxes(context.get("Pad Layout")),
                trace_boxes=self._as_boxes(context.get("Trace Layout")),
                **params)
        except Exception as exc:                       # noqa: BLE001 - surfaced, not swallowed
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"PCB defect detection failed: {type(exc).__name__}: {exc}")

        threshold = float(self.parameters.get("confidence_threshold") or 0.0)
        if threshold > 0:
            detections = [d for d in detections if float(d["score"]) >= threshold]

        boxes = [list(d["box"]) for d in detections]
        classes = [str(d["label"]) for d in detections]
        scores = [float(d["score"]) for d in detections]

        out_image = image.copy()
        overlays: List[Dict[str, Any]] = []
        for det, label, score in zip(boxes, classes, scores):
            x, y, w, h = det
            overlays.append({"type": "rect", "x": x, "y": y, "w": w, "h": h,
                             "color": (60, 60, 230), "width": 2, "label": label})
            overlays.append({"type": "text", "x": int(x), "y": max(12, int(y) - 4),
                             "text": f"{label} {score:.2f}",
                             "color": (60, 60, 230)})

        if detections:
            summary_parts = []
            for name in sorted(set(classes)):
                summary_parts.append(f"{name}: {classes.count(name)}")
            message = (f"Detected {len(detections)} defect(s) "
                       f"({', '.join(summary_parts)})")
            status = ToolStatus.NG
            verdict = "NG"
        else:
            message = "No defects detected"
            status = ToolStatus.OK
            verdict = "OK"

        records = [
            {"box": box, "label": label, "score": score,
             "model_id": f"pcb_reference[{variant}]"}
            for box, label, score in zip(boxes, classes, scores)
        ]

        return ToolExecutionResult(
            status=status,
            message=message,
            outputs={
                "Image": out_image,
                "Count": len(detections),
                "Boxes": boxes,
                "Classes": classes,
                "Scores": scores,
                "Detections": records,
                "Status": verdict,
            },
            overlays=overlays,
        )
