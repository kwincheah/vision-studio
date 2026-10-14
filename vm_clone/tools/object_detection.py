"""
Deep Learning Object Detection Tool powered by Ultralytics YOLO.
Provides inference-only deep learning detection with configurable:
- Model file path (.pt / .onnx / engine, defaulting to YOLOv11 'yolo11n.pt')
- Confidence threshold
- IoU threshold (NMS)
- Class filtering (by index or class name)
- Search ROI support
- Structured feature outputs and canvas overlays
"""
import os
import cv2
import numpy as np
from typing import Dict, Any, List, Optional, Union
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


# Global model cache to avoid re-instantiating heavy model weights on every frame
_YOLO_MODEL_CACHE: Dict[str, Any] = {}


def _get_yolo_model(model_path: str):
    """Retrieve or load YOLO model from cache."""
    path_key = (model_path or "yolo11n.pt").strip()
    if path_key not in _YOLO_MODEL_CACHE:
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError(
                "YOLO inference requires 'ultralytics'. Install via 'pip install ultralytics'."
            ) from e
        _YOLO_MODEL_CACHE[path_key] = YOLO(path_key)
    return _YOLO_MODEL_CACHE[path_key]


@register_tool
class ObjectDetectionTool(VisionToolBase):
    category = "Recognition"
    tool_name = "Object Detection"
    description = "Object detection inference powered by Ultralytics YOLO (YOLOv11 default)."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image for object detection")
        self.inputs["ROI"] = ToolPort("ROI", DataType.REGION, "Optional bounding box search ROI [x, y, w, h]")

        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Output image with visual overlays")
        self.outputs["Count"] = ToolPort("Count", DataType.VALUE, "Total number of detected objects")
        self.outputs["Boxes"] = ToolPort("Boxes", DataType.ANY, "List of bounding boxes [[x, y, w, h], ...]")
        self.outputs["Classes"] = ToolPort("Classes", DataType.ANY, "List of detected class names")
        self.outputs["Scores"] = ToolPort("Scores", DataType.ANY, "List of detection confidence scores")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "Inspection status ('OK' if detected, 'NG' if empty)")
        self.outputs["Detections"] = ToolPort("Detections", DataType.ANY, "Detailed detection records for Result Table")

    def _init_parameters(self):
        self.parameters = {
            "model_path": "yolo11n.pt",
            "confidence": 0.25,
            "iou": 0.45,
            "classes": "all",
            "device": "cpu",
            "max_detections": 100,
        }

    def _parse_classes(self, classes_input: Any, model_names: Dict[int, str]) -> Optional[List[int]]:
        """Parse user-provided classes string/list into list of integer class IDs."""
        if classes_input is None:
            return None
        if isinstance(classes_input, str):
            s = classes_input.strip()
            if not s or s.lower() in ("all", "*", "any"):
                return None
            items = [item.strip() for item in s.split(",") if item.strip()]
        elif isinstance(classes_input, (list, tuple)):
            if not classes_input:
                return None
            items = [str(item).strip() for item in classes_input if str(item).strip()]
        else:
            return None

        name_to_id = {str(name).lower(): cid for cid, name in (model_names or {}).items()}
        class_ids = []
        for item in items:
            if item.isdigit():
                class_ids.append(int(item))
            elif item.lower() in name_to_id:
                class_ids.append(name_to_id[item.lower()])

        return class_ids if class_ids else None

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=4, min_h=4)
        if img is None:
            return ToolExecutionResult(
                status=ToolStatus.NG,
                message="No input image provided",
                outputs={
                    "Count": 0,
                    "Boxes": [],
                    "Classes": [],
                    "Scores": [],
                    "Status": "NG",
                    "Detections": []
                }
            )

        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif len(img.shape) == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        model_path = str(self.get_param("model_path", "yolo11n.pt")).strip() or "yolo11n.pt"
        conf = float(self.get_param("confidence", 0.25))
        iou_thresh = float(self.get_param("iou", 0.45))
        classes_param = self.get_param("classes", "all")
        device_param = str(self.get_param("device", "cpu")).strip()
        max_det = int(self.get_param("max_detections", 100))

        # Handle optional search ROI [x, y, w, h]
        roi = context.get("ROI")
        offset_x, offset_y = 0, 0
        inference_img = img

        h_img, w_img = img.shape[:2]
        if roi and isinstance(roi, (list, tuple)) and len(roi) >= 4:
            rx, ry, rw, rh = int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])
            rx = max(0, min(rx, w_img - 1))
            ry = max(0, min(ry, h_img - 1))
            rw = max(1, min(rw, w_img - rx))
            rh = max(1, min(rh, h_img - ry))
            if rw > 4 and rh > 4:
                inference_img = img[ry:ry + rh, rx:rx + rw]
                offset_x, offset_y = rx, ry

        try:
            model = _get_yolo_model(model_path)
            class_filter = self._parse_classes(classes_param, getattr(model, "names", {}))

            predict_kwargs: Dict[str, Any] = {
                "source": inference_img,
                "conf": conf,
                "iou": iou_thresh,
                "verbose": False,
                "max_det": max_det
            }
            if class_filter is not None:
                predict_kwargs["classes"] = class_filter
            if device_param in ("cpu", "cuda"):
                predict_kwargs["device"] = device_param

            results = model.predict(**predict_kwargs)
            res0 = results[0] if results else None
        except Exception as e:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"YOLO Inference Error: {str(e)}",
                outputs={
                    "Image": img,
                    "Count": 0,
                    "Boxes": [],
                    "Classes": [],
                    "Scores": [],
                    "Status": "NG",
                    "Detections": []
                }
            )

        boxes: List[List[int]] = []
        class_names: List[str] = []
        scores: List[float] = []
        detection_records: List[Dict[str, Any]] = []
        overlays: List[Dict[str, Any]] = []

        if res0 is not None and res0.boxes is not None and len(res0.boxes) > 0:
            for idx, box in enumerate(res0.boxes):
                xyxy = box.xyxy[0].cpu().numpy()
                score = float(box.conf[0].cpu().numpy())
                cls_id = int(box.cls[0].cpu().numpy())
                cls_name = model.names.get(cls_id, str(cls_id)) if hasattr(model, "names") else str(cls_id)

                bx = int(xyxy[0]) + offset_x
                by = int(xyxy[1]) + offset_y
                bw = int(xyxy[2] - xyxy[0])
                bh = int(xyxy[3] - xyxy[1])
                cx = bx + bw // 2
                cy = by + bh // 2

                box_rect = [bx, by, bw, bh]
                boxes.append(box_rect)
                class_names.append(cls_name)
                scores.append(round(score, 4))

                detection_records.append({
                    "Index": idx,
                    "Class": cls_name,
                    "Score": round(score, 4),
                    "CentroidX": cx,
                    "CentroidY": cy,
                    "Width": bw,
                    "Height": bh,
                    "Box": box_rect
                })

                # Visual overlays: box outline + tag
                overlays.append({
                    "type": "rect",
                    "box": box_rect,
                    "color": (232, 121, 43),  # Vision Master orange #e4b030
                    "label": f"{cls_name} {score:.2f}",
                    "thickness": 2
                })
                overlays.append({
                    "type": "text",
                    "text": f"{cls_name} {score:.2f}",
                    "pt": (bx, max(14, by - 5)),
                    "color": (232, 121, 43)
                })

        count = len(boxes)
        status_verdict = ToolStatus.OK if count > 0 else ToolStatus.READY
        msg = f"Detected {count} object(s)"
        if count > 0:
            summary = ", ".join(f"{c}: {class_names.count(c)}" for c in sorted(set(class_names)))
            msg += f" ({summary})"

        return ToolExecutionResult(
            status=status_verdict,
            message=msg,
            outputs={
                "Image": img,
                "Count": count,
                "Boxes": boxes,
                "Classes": class_names,
                "Scores": scores,
                "Status": "OK" if count > 0 else "NG",
                "Detections": detection_records
            },
            overlays=overlays
        )
