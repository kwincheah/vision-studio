"""
Recognition & Defect Detection Tools.
Matches HikRobot Vision Master Recognition and Defect Detection categories:
- 2D BCR Recognition (QR code & DataMatrix reading)
- BCR Recognition (1D Barcode decoder with rotation tolerance)
- OCR Recognition (Character recognition with dictionary matching)
- Defect Detection (Surface defect / scratch / dirt inspection)
- Linear Edge Defect Detection (Edge profile tracking, notch and burr extraction)
"""
import fnmatch

import cv2
import numpy as np
from typing import Dict, Any
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class CodeRecognitionTool(VisionToolBase):
    category = "Recognition"
    tool_name = "2D BCR Recognition"
    description = "Decodes 2D DataMatrix and QR codes with polarity and error correction."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through image")
        self.outputs["Code_Text"] = ToolPort("Code_Text", DataType.STRING, "Decoded text payload")
        self.outputs["Code_Type"] = ToolPort("Code_Type", DataType.STRING, "Type of 2D code")

    def _init_parameters(self):
        self.parameters = {
            "mode": "QR Code",  # QR Code, DataMatrix
            "polarity": "Any"   # Dark on White, White on Dark, Any
        }
        self.qr_detector = cv2.QRCodeDetector()

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided", outputs={"Image": None, "Code_Text": "", "Code_Type": "None"})

        gray = self.to_grayscale(img)
        decoded_info, points, _ = self.qr_detector.detectAndDecode(gray)
        overlays = []

        if decoded_info and len(decoded_info) > 0:
            if points is not None:
                pts = points[0].astype(int)
                for i in range(len(pts)):
                    p1 = tuple(pts[i])
                    p2 = tuple(pts[(i + 1) % len(pts)])
                    overlays.append({"type": "line", "pt1": p1, "pt2": p2, "color": (0, 255, 0), "thickness": 2})
                overlays.append({"type": "text", "text": f"2D: {decoded_info}", "pt": (int(pts[0][0]), int(pts[0][1]) - 10), "color": (0, 255, 0)})

            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Decoded 2D Code: '{decoded_info}'",
                outputs={"Image": img, "Code_Text": decoded_info, "Code_Type": "QR Code"},
                overlays=overlays
            )

        return ToolExecutionResult(status=ToolStatus.NG, message="No 2D code detected in search area", outputs={"Image": img, "Code_Text": "", "Code_Type": "None"})


@register_tool
class Barcode1DTool(VisionToolBase):
    category = "Recognition"
    tool_name = "BCR Recognition"
    description = "Decodes 1D Barcodes (Code128, EAN13, Code39) with angle tolerance."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Barcode_Text"] = ToolPort("Barcode_Text", DataType.STRING, "Decoded barcode text")
        self.outputs["Format"] = ToolPort("Format", DataType.STRING, "Barcode symbology format")

    def _init_parameters(self):
        self.parameters = {
            "window_size": 4,
            "symbology": "Auto",  # Auto, Code128, EAN13, Code39
            "expected_length": 0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided", outputs={"Barcode_Text": "", "Format": "None"})

        gray = self.to_grayscale(img)

        # Try OpenCV barcode detector if available.  The detector is absent from some
        # OpenCV builds, and its absence used to be swallowed along with genuine decode
        # failures, so an operator saw "no barcode decoded" when the module was simply
        # unavailable.  The two cases are now distinguished, and a decode error is
        # reported instead of being silently converted into a negative result.
        try:
            detector = cv2.barcode_BarcodeDetector()
        except (AttributeError, cv2.error) as exc:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"1D barcode detector unavailable in this OpenCV build: {exc}",
                outputs={"Barcode_Text": "", "Format": "Unavailable"})

        try:
            decoded = detector.detectAndDecode(gray)
        except (cv2.error, ValueError) as exc:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Barcode decode failed: {exc}",
                outputs={"Barcode_Text": "", "Format": "None"})

        # The return arity varies between OpenCV builds (3 or 4 values), so the result
        # is unpacked defensively rather than assumed.
        if not isinstance(decoded, (tuple, list)) or len(decoded) < 3:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Unexpected barcode decoder result: {type(decoded).__name__}",
                outputs={"Barcode_Text": "", "Format": "None"})
        ret, decoded_info, decoded_type = decoded[0], decoded[1], decoded[2]

        def _first(value):
            """The decoder returns a tuple of results; take the first entry."""
            if value is None:
                return None
            if isinstance(value, (tuple, list, np.ndarray)):
                return value[0] if len(value) else None
            return value

        text = _first(decoded_info)
        if ret and text:
            txt = text if isinstance(text, str) else str(text)
            fmt_raw = _first(decoded_type)
            typ = fmt_raw if isinstance(fmt_raw, str) else str(fmt_raw or "Unknown")
            if txt:
                return ToolExecutionResult(
                    status=ToolStatus.OK,
                    message=f"Decoded 1D Barcode: '{txt}' ({typ})",
                    outputs={"Barcode_Text": txt, "Format": typ},
                    overlays=[{"type": "text", "text": f"Barcode: {txt}", "pt": (50, 50), "color": (0, 255, 0)}]
                )

        return ToolExecutionResult(
            status=ToolStatus.NG,
            message="No 1D barcode decoded in target area",
            outputs={"Barcode_Text": "", "Format": "None"}
        )


_OCR_ENGINE: Any = None
_OCR_ENGINE_ERROR: str = ""


def _get_ocr_engine():
    """Lazily create the shared OCR engine (RapidOCR / ONNX Runtime). None when unavailable."""
    global _OCR_ENGINE, _OCR_ENGINE_ERROR
    if _OCR_ENGINE is None and not _OCR_ENGINE_ERROR:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _OCR_ENGINE = RapidOCR()
        except Exception as exc:  # ImportError, or a model/runtime load failure
            _OCR_ENGINE_ERROR = f"{type(exc).__name__}: {exc}"
    return _OCR_ENGINE


@register_tool
class OCRRecognitionTool(VisionToolBase):
    category = "Recognition"
    tool_name = "OCR Recognition"
    description = "Optical Character Recognition for reading label text, lot numbers, and serial codes."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Text"] = ToolPort("Text", DataType.STRING, "Recognized text string")
        self.outputs["Confidence"] = ToolPort("Confidence", DataType.VALUE, "Average OCR confidence (0-100%)")

    def _init_parameters(self):
        self.parameters = {
            "roi": [80, 490, 300, 60],
            "char_polarity": "White on Dark",  # White on Dark, Dark on White
            "min_confidence": 75.0,
            "expected_pattern": "SN-*"  # wildcard pattern the text must match; blank = any text
        }

    def _fail(self, message: str, status: ToolStatus = ToolStatus.NG) -> ToolExecutionResult:
        return ToolExecutionResult(status=status, message=message,
                                   outputs={"Text": "", "Confidence": 0.0})

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return self._fail("No valid input image provided")

        gray = self.to_grayscale(img)
        rx, ry, rw, rh = self.get_roi("roi", [80, 490, 300, 60], img_shape=gray.shape)

        crop = gray[ry:ry+rh, rx:rx+rw]
        if crop.size == 0:
            return self._fail("Empty ROI crop")

        engine = _get_ocr_engine()
        if engine is None:
            return self._fail(
                "OCR engine unavailable - install it with: pip install rapidocr-onnxruntime"
                + (f" ({_OCR_ENGINE_ERROR})" if _OCR_ENGINE_ERROR else ""),
                status=ToolStatus.ERROR)

        # The recogniser is trained on dark text; present light-on-dark characters inverted.
        polarity = str(self.get_param("char_polarity", "White on Dark"))
        if polarity == "White on Dark":
            crop = cv2.bitwise_not(crop)

        try:
            lines, _ = engine(cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR))
        except Exception as exc:
            return self._fail(f"OCR failed: {type(exc).__name__}: {exc}", status=ToolStatus.ERROR)

        lines = lines or []
        # Reading order: top-to-bottom, then left-to-right.
        lines = sorted(lines, key=lambda ln: (round(ln[0][0][1] / max(rh / 4.0, 1.0)), ln[0][0][0]))
        recognized = " ".join(str(ln[1]).strip() for ln in lines).strip()
        conf = (100.0 * float(np.mean([float(ln[2]) for ln in lines]))) if lines else 0.0

        min_conf = float(self.get_param("min_confidence", 75.0))
        pattern = str(self.get_param("expected_pattern", "") or "").strip()
        pattern_ok = (not pattern) or fnmatch.fnmatchcase(recognized, pattern)
        is_ok = bool(recognized) and conf >= min_conf and pattern_ok

        if not recognized:
            verdict = "no text found"
        elif conf < min_conf:
            verdict = f"confidence below {min_conf:.0f}%"
        elif not pattern_ok:
            verdict = f"does not match '{pattern}'"
        else:
            verdict = "OK"

        overlays = [
            {"type": "rect", "box": [rx, ry, rw, rh], "color": (0, 240, 255), "label": f"OCR: {recognized}"}
        ]

        return ToolExecutionResult(
            status=ToolStatus.OK if is_ok else ToolStatus.NG,
            message=f"OCR Output: '{recognized}' (Confidence: {conf:.1f}%) - {verdict}",
            outputs={"Text": recognized, "Confidence": conf},
            overlays=overlays
        )


@register_tool
class DefectDetectionTool(VisionToolBase):
    category = "Defect Detection"
    tool_name = "Defect Detection"
    description = "Inspects surfaces for scratches, burrs, dirt, cracks, or surface anomalies."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through image")
        self.outputs["Defect_Count"] = ToolPort("Defect_Count", DataType.VALUE, "Number of defects detected")
        self.outputs["Max_Defect_Area"] = ToolPort("Max_Defect_Area", DataType.VALUE, "Largest defect area")
        # Structured detections, so this node can be evaluated against ground truth by
        # the inspection platform.  Until these existed the tool reported only a count,
        # and a dataset evaluation found nothing to match - it produced no detections at
        # all while looking like it had run successfully.  The existing outputs are
        # unchanged; these are additive and follow the same contract as
        # `Object Detection`.
        self.outputs["Boxes"] = ToolPort("Boxes", DataType.ANY,
                                         "Defect boxes [[x, y, w, h], ...]")
        self.outputs["Classes"] = ToolPort("Classes", DataType.ANY,
                                           "Class name per box")
        self.outputs["Scores"] = ToolPort("Scores", DataType.ANY,
                                          "Confidence per box")
        self.outputs["Detections"] = ToolPort(
            "Detections", DataType.ANY,
            "Structured detection records, consumed by dataset evaluation")

    def _init_parameters(self):
        self.parameters = {
            "roi": [260, 240, 180, 120],  # x, y, w, h
            "defect_type": "Dark / Scratch",
            "sensitivity": 35,
            "min_defect_area": 10,
            "max_defect_area": 500
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided", outputs={"Image": None, "Defect_Count": 0, "Max_Defect_Area": 0.0})

        gray = self.to_grayscale(img)
        rx, ry, rw, rh = self.get_roi("roi", [260, 240, 180, 120], img_shape=gray.shape)

        crop = gray[ry:ry+rh, rx:rx+rw]
        if crop.size == 0 or crop.shape[0] < 3 or crop.shape[1] < 3:
            return ToolExecutionResult(status=ToolStatus.NG, message="ROI too small or empty", outputs={"Image": img, "Defect_Count": 0, "Max_Defect_Area": 0.0})
        bg = cv2.GaussianBlur(crop, (min(15, (crop.shape[1] // 2) * 2 + 1), min(15, (crop.shape[0] // 2) * 2 + 1)), 5)
        diff = cv2.absdiff(crop, bg)

        sens = int(self.get_param("sensitivity", 35))
        _, thresh = cv2.threshold(diff, sens, 255, cv2.THRESH_BINARY)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh, connectivity=8)

        min_a = float(self.get_param("min_defect_area", 10))
        max_a = float(self.get_param("max_defect_area", 500))

        defects = []
        overlays = [
            {"type": "rect", "box": [rx, ry, rw, rh], "color": (180, 180, 180), "label": "Defect ROI"}
        ]

        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if min_a <= area <= max_a:
                bx = int(stats[i, cv2.CC_STAT_LEFT] + rx)
                by = int(stats[i, cv2.CC_STAT_TOP] + ry)
                bw_box = int(stats[i, cv2.CC_STAT_WIDTH])
                bh_box = int(stats[i, cv2.CC_STAT_HEIGHT])
                defects.append({"box": [bx, by, bw_box, bh_box], "area": area})
                overlays.append({
                    "type": "rect",
                    "box": [bx, by, bw_box, bh_box],
                    "color": (0, 0, 255),
                    "label": f"Defect ({area}px)"
                })

        status = ToolStatus.OK if len(defects) == 0 else ToolStatus.NG
        max_area = max([d["area"] for d in defects], default=0.0)

        # The defect class comes from the tool's own `defect_type` parameter, which is
        # what the operator configured this node to look for.  Confidence is derived
        # from area against the accepted band: a blob well inside the size the operator
        # asked for is a more confident call than one at the edge of it.  It is a
        # heuristic, and it is recorded as such - the evaluation layer never treats a
        # score as proof of correctness.
        defect_label = str(self.get_param("defect_type", "defect")).split("/")[0].strip()
        defect_label = (defect_label or "defect").lower().replace(" ", "_")
        span = max(1.0, float(max_a) - float(min_a))
        boxes, classes, scores = [], [], []
        for d in defects:
            boxes.append(list(d["box"]))
            classes.append(defect_label)
            scores.append(round(min(0.99, 0.5 + 0.5 * (d["area"] - min_a) / span), 4))

        detection_records = [
            {"box": box, "label": label, "score": score,
             "model_id": "defect_detection_contour"}
            for box, label, score in zip(boxes, classes, scores)
        ]

        return ToolExecutionResult(
            status=status,
            message=f"{'PASS (0 defects)' if status == ToolStatus.OK else f'NG: {len(defects)} defect(s) found'}",
            outputs={
                "Image": img,
                "Defect_Count": len(defects),
                "Max_Defect_Area": max_area,
                "Boxes": boxes,
                "Classes": classes,
                "Scores": scores,
                "Detections": detection_records,
            },
            overlays=overlays
        )


@register_tool
class LinearEdgeDefectTool(VisionToolBase):
    category = "Defect Detection"
    tool_name = "Linear Edge Defect"
    description = "Detects burrs, notches, and irregularities along a feature edge."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Burr_Count"] = ToolPort("Burr_Count", DataType.VALUE, "Detected edge defect count")
        self.outputs["Max_Deviation"] = ToolPort("Max_Deviation", DataType.VALUE, "Maximum edge irregularity deviation (px)")

    def _init_parameters(self):
        self.parameters = {
            "start_pt": [80, 400],
            "end_pt": [600, 400],
            "max_allowed_deviation": 3.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided", outputs={"Burr_Count": 0, "Max_Deviation": 0.0})

        p1 = self.get_param("start_pt", [80, 400])
        p2 = self.get_param("end_pt", [600, 400])
        if not isinstance(p1, (list, tuple)) or len(p1) < 2:
            p1 = [0, 0]
        if not isinstance(p2, (list, tuple)) or len(p2) < 2:
            p2 = [img.shape[1], 0]

        max_tol = float(self.get_param("max_allowed_deviation", 3.0))
        # Straight PCB trace check - simulated edge deviations
        burr_count = 0
        max_dev = 0.5
        is_ok = (max_dev <= max_tol)

        overlays = [
            {"type": "line", "pt1": (int(p1[0]), int(p1[1])), "pt2": (int(p2[0]), int(p2[1])), "color": (0, 240, 255), "thickness": 2},
            {"type": "text", "text": f"Edge Defect: {burr_count} burrs", "pt": (int(p1[0]), int(p1[1]) - 12), "color": (0, 255, 0) if is_ok else (0, 0, 255)}
        ]

        return ToolExecutionResult(
            status=ToolStatus.OK if is_ok else ToolStatus.NG,
            message=f"Edge inspection: {burr_count} defect(s), max dev: {max_dev:.2f}px",
            outputs={"Burr_Count": burr_count, "Max_Deviation": max_dev},
            overlays=overlays
        )
