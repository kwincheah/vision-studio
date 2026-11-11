"""
Deep Learning Object Detection Tool (YOLO).
Provides inference-only deep learning detection with configurable:
- Model file path: an exported .onnx model runs anywhere through the built-in engine (the packaged app included);
  a .pt / engine file needs Ultralytics (the bundled default is YOLOv11 'yolo11n.onnx')
- Confidence threshold
- IoU threshold (NMS)
- Class filtering (by index or class name)
- Search ROI support
- Structured feature outputs and canvas overlays
"""
import os
import cv2
from typing import Dict, Any, List, Optional
from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from apex_vision.core import dl_engine as dl
from apex_vision.core.registry import register_tool


# Global model cache to avoid re-instantiating heavy model weights on every frame
_YOLO_MODEL_CACHE: Dict[str, Any] = {}


def _resolve_model_path(model_path: str) -> str:
    """Prefer a weights file shipped next to the application over a cwd-relative download.

    Ultralytics silently downloads a missing ``yolo11n.pt`` into the working directory,
    which stalls the UI thread (and fails offline) when the app is launched from elsewhere.
    """
    if os.path.isabs(model_path) or os.path.exists(model_path):
        return model_path
    app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    bundled = os.path.join(app_root, model_path)
    return bundled if os.path.exists(bundled) else model_path


def _pytorch_available() -> bool:
    """Whether a .pt model can run in this process (the packaged app leaves PyTorch out to stay small)."""
    return dl.pytorch_available()


def _get_yolo_model(model_path: str):
    """Retrieve or load YOLO model from cache with warm-up."""
    path_key = (model_path or "yolo11n.pt").strip()
    if path_key not in _YOLO_MODEL_CACHE:
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError(
                "YOLO inference requires 'ultralytics'. Install via 'pip install ultralytics'."
            ) from e
        model = YOLO(_resolve_model_path(path_key))
        # Warmup model once with a synthetic dummy tensor to avoid initial inference stall
        try:
            import numpy as np
            dummy = np.zeros((64, 64, 3), dtype=np.uint8)
            model.predict(source=dummy, verbose=False, max_det=1)
        except Exception:
            pass
        _YOLO_MODEL_CACHE[path_key] = model
    return _YOLO_MODEL_CACHE[path_key]


@register_tool
class ObjectDetectionTool(VisionToolBase):
    category = "Deep Learning"
    tool_name = "Object Detection"
    description = ("Finds and boxes objects or defects with a YOLO model. An exported .onnx model runs on its own (no PyTorch needed); "
                   "a .pt model runs through Ultralytics.")

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
            "model_path": "yolo11n.onnx",
            "confidence": 0.25,
            "iou": 0.45,
            "classes": "all",
            "device": "cpu",
            "max_detections": 100,
            "roi": [0, 0, 0, 0],            # draw a region to search only there (all zero = the whole image); the ROI input wins
            "labels": "",           # ONNX models: 'crack, dent, scratch' or a .txt file; blank = the model's own names
            "save_in_solution": False,   # ONNX models: keep a copy of the model inside the solution file
            "model_data": {},       # (that copy; not shown for editing)
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

        model_path = str(self.get_param("model_path", "yolo11n.onnx")).strip() or "yolo11n.onnx"
        if model_path.lower().endswith(".pt") and not _pytorch_available():
            try:                                  # no PyTorch here: the model is converted to ONNX once and runs on the built-in engine
                model_path = dl.convert_pt_to_onnx(_resolve_model_path(model_path), int(self.get_param("input_width", 0) or 640))
            except dl.DLModelError as exc:
                return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Object Detection: {exc}")
        if model_path.lower().endswith(".onnx") or self.parameters.get("model_data"):
            try:
                model_path = dl.effective_path(self, "model_path") or model_path
            except dl.DLModelError as exc:
                return ToolExecutionResult(status=ToolStatus.ERROR, message=str(exc))
        if model_path.lower().endswith(".onnx") and not self.parameters.get("model_data"):
            model_path = _resolve_model_path(model_path)             # a bare name means the model shipped with the application
        conf = float(self.get_param("confidence", 0.25))
        iou_thresh = float(self.get_param("iou", 0.45))
        classes_param = self.get_param("classes", "all")
        device_param = str(self.get_param("device", "cpu")).strip()
        max_det = int(self.get_param("max_detections", 100))

        # Handle optional search ROI: [x, y, w, h], {"box": ...}, or [{"box": ...}, ...] from BLOB Analysis
        roi = context.get("ROI")
        offset_x, offset_y = 0, 0
        inference_img = img

        h_img, w_img = img.shape[:2]
        box = None
        if roi is not None:
            if isinstance(roi, dict) and "box" in roi and len(roi["box"]) >= 4:
                box = roi["box"]
            elif isinstance(roi, (list, tuple)) and len(roi) > 0:
                # If it's a list of blob dictionaries from BLOB Analysis
                if isinstance(roi[0], dict) and "box" in roi[0]:
                    valid_boxes = [b["box"] for b in roi if isinstance(b, dict) and "box" in b and len(b["box"]) >= 4]
                    if valid_boxes:
                        min_x = min(int(b[0]) for b in valid_boxes)
                        min_y = min(int(b[1]) for b in valid_boxes)
                        max_x = max(int(b[0]) + int(b[2]) for b in valid_boxes)
                        max_y = max(int(b[1]) + int(b[3]) for b in valid_boxes)
                        box = [min_x, min_y, max_x - min_x, max_y - min_y]
                elif len(roi) >= 4 and all(isinstance(v, (int, float, str)) and not isinstance(v, (dict, list, tuple)) for v in roi[:4]):
                    box = roi[:4]

        if box is None:
            own = self.get_param("roi", [0, 0, 0, 0])
            if isinstance(own, (list, tuple)) and len(own) == 4 and own[2] > 0 and own[3] > 0:
                box = own
        if box is not None:
            try:
                rx, ry, rw, rh = int(box[0]), int(box[1]), int(box[2]), int(box[3])
                rx = max(0, min(rx, w_img - 1))
                ry = max(0, min(ry, h_img - 1))
                rw = max(1, min(rw, w_img - rx))
                rh = max(1, min(rh, h_img - ry))
                if rw > 4 and rh > 4:
                    inference_img = img[ry:ry + rh, rx:rx + rw]
                    offset_x, offset_y = rx, ry
            except (ValueError, TypeError):
                pass

        if model_path.lower().endswith(".onnx"):
            empty = {"Image": img, "Count": 0, "Boxes": [], "Classes": [], "Scores": [], "Status": "NG", "Detections": []}
            try:
                raw = self._detect_onnx(inference_img, model_path, conf, iou_thresh, max_det, classes_param, offset_x, offset_y)
            except dl.DLModelError as e:
                return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Object Detection: {e}", outputs=empty)
            return self._package(img, raw)

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

        raw = []
        if res0 is not None and res0.boxes is not None and len(res0.boxes) > 0:
            for box in res0.boxes:
                xyxy = box.xyxy[0].cpu().numpy()
                cls_id = int(box.cls[0].cpu().numpy())
                raw.append((int(xyxy[0]) + offset_x, int(xyxy[1]) + offset_y, int(xyxy[2] - xyxy[0]), int(xyxy[3] - xyxy[1]),
                            float(box.conf[0].cpu().numpy()),
                            model.names.get(cls_id, str(cls_id)) if hasattr(model, "names") else str(cls_id)))
        return self._package(img, raw)

    def _detect_onnx(self, inference_img, model_path, conf, iou_thresh, max_det, classes_param, offset_x, offset_y):
        """Run an .onnx YOLO model through the built-in engine. Returns [(x, y, w, h, score, class name), ...]."""
        from apex_vision.tools.deep_learning import detect_boxes
        model = dl.load_model(model_path, "Auto", str(self.get_param("device", "cpu")).strip())
        return [(x + offset_x, y + offset_y, w, h, score, name)
                for x, y, w, h, score, name in detect_boxes(model, inference_img, self.get_param("labels", ""), conf, iou_thresh,
                                                            max_det, classes_param)]

    def _package(self, img, raw):
        """Turn [(x, y, w, h, score, name), ...] into the module's outputs and overlays."""
        boxes: List[List[int]] = []
        class_names: List[str] = []
        scores: List[float] = []
        detection_records: List[Dict[str, Any]] = []
        overlays: List[Dict[str, Any]] = []

        for idx, (bx, by, bw, bh, score, cls_name) in enumerate(raw):
            cx = bx + bw // 2
            cy = by + bh // 2
            box_rect = [bx, by, bw, bh]
            boxes.append(box_rect)
            class_names.append(cls_name)
            scores.append(round(score, 4))
            detection_records.append({
                "Index": idx, "Class": cls_name, "Score": round(score, 4), "CentroidX": cx, "CentroidY": cy,
                "Width": bw, "Height": bh, "Box": box_rect
            })
            overlays.append({
                "type": "rect", "box": box_rect, "color": (232, 121, 43),
                "label": f"{cls_name} {score:.2f}", "thickness": 2
            })
            overlays.append({
                "type": "text", "text": f"{cls_name} {score:.2f}", "pt": (bx, max(14, by - 5)), "color": (232, 121, 43)
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
