"""
Measurement Tools matching HikRobot Vision Master Measurement category:
- L2L Measure (Line to Line distance & angle difference)
- P2P Measure (Point to Point distance, delta X, delta Y)
- Intensity Measure (Mean, StdDev, Min, Max grayscale within ROI)
- Pixel Count (Counts pixels between Low and High grayscale thresholds within ROI)
- Edge Distance (Caliper distance between two feature edges along projection axis)
- Histogram (Min, Max, Mean, Median, Peak, StdDev, Contrast of gray distribution)
"""
import cv2
import numpy as np
from typing import Dict, Any
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class L2LMeasureTool(VisionToolBase):
    category = "Measurement"
    tool_name = "L2L Measure"
    description = "Line to Line Distance and Angle measurement."

    def _init_ports(self):
        self.inputs["Line1"] = ToolPort("Line1", DataType.LINE, "First line dict (x1, y1, x2, y2)")
        self.inputs["Line2"] = ToolPort("Line2", DataType.LINE, "Second line dict (x1, y1, x2, y2)")
        self.outputs["Distance"] = ToolPort("Distance", DataType.VALUE, "Distance between lines (scaled)")
        self.outputs["Angle_Diff"] = ToolPort("Angle_Diff", DataType.VALUE, "Angle difference in degrees")

    def _init_parameters(self):
        self.parameters = {
            "scale_factor": 1.0,  # mm per pixel
            "min_distance": 0.0,
            "max_distance": 1000.0,
            "default_l1": [50, 150, 450, 150],
            "default_l2": [80, 400, 600, 400]
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        l1_raw = context.get("Line1") or self.get_param("default_l1")
        l2_raw = context.get("Line2") or self.get_param("default_l2")

        # Both lines must be well formed before anything is computed.  A search
        # module that finds no edge emits `None`, and a partial mapping or a short
        # sequence is equally reachable from the canvas, so each input is validated
        # instead of unpacked: unpacking raised, and the operator only ever saw the
        # pipeline's generic "Exception: ..." with no indication of which port.
        l1 = self.as_line(l1_raw)
        if l1 is None:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Line1 is not a valid line (need x1,y1,x2,y2): {l1_raw!r:.80}")
        l2 = self.as_line(l2_raw)
        if l2 is None:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Line2 is not a valid line (need x1,y1,x2,y2): {l2_raw!r:.80}")

        x1_a, y1_a, x2_a, y2_a = l1
        x1_b, y1_b, x2_b, y2_b = l2

        mid1 = ((x1_a + x2_a) / 2.0, (y1_a + y2_a) / 2.0)
        mid2 = ((x1_b + x2_b) / 2.0, (y1_b + y2_b) / 2.0)

        dist_px = float(np.hypot(mid2[0] - mid1[0], mid2[1] - mid1[1]))
        scale = float(self.get_param("scale_factor", 1.0))
        dist_scaled = dist_px * scale

        angle1 = np.degrees(np.arctan2(y2_a - y1_a, x2_a - x1_a))
        angle2 = np.degrees(np.arctan2(y2_b - y1_b, x2_b - x1_b))
        angle_diff = float(abs((angle1 - angle2 + 180) % 360 - 180))

        min_d = float(self.get_param("min_distance", 0.0))
        max_d = float(self.get_param("max_distance", 1000.0))
        status = ToolStatus.OK if (min_d <= dist_scaled <= max_d) else ToolStatus.NG

        overlays = [
            {"type": "line", "pt1": (int(mid1[0]), int(mid1[1])), "pt2": (int(mid2[0]), int(mid2[1])), "color": (0, 165, 255), "thickness": 2},
            {"type": "text", "text": f"L2L Dist: {dist_scaled:.2f} ({dist_px:.1f}px), AngleDiff: {angle_diff:.1f}°", "pt": (int(mid1[0]), int(mid1[1]) - 15), "color": (0, 165, 255)}
        ]

        return ToolExecutionResult(
            status=status,
            message=f"L2L Dist={dist_scaled:.2f}, AngleDiff={angle_diff:.2f}°",
            outputs={
                "Distance": dist_scaled,
                "Angle_Diff": angle_diff
            },
            overlays=overlays
        )


@register_tool
class P2PMeasureTool(VisionToolBase):
    category = "Measurement"
    tool_name = "P2P Measure"
    description = "Point to Point Euclidean and axis distance measurement."

    def _init_ports(self):
        self.inputs["Point1"] = ToolPort("Point1", DataType.POINT, "First point (x, y)")
        self.inputs["Point2"] = ToolPort("Point2", DataType.POINT, "Second point (x, y)")
        self.outputs["Distance"] = ToolPort("Distance", DataType.VALUE, "Euclidean distance")
        self.outputs["Delta_X"] = ToolPort("Delta_X", DataType.VALUE, "X distance")
        self.outputs["Delta_Y"] = ToolPort("Delta_Y", DataType.VALUE, "Y distance")

    def _init_parameters(self):
        self.parameters = {
            "scale_factor": 1.0,
            "default_p1": [150, 150],
            "default_p2": [350, 150],
            "min_distance": 0.0,
            "max_distance": 1000.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        p1_raw = context.get("Point1")
        p2_raw = context.get("Point2")

        # A malformed point used to be silently coerced to (0, 0), which produced a
        # confident but meaningless distance; a short tuple raised instead.  Both
        # now report which port was unusable.
        p1 = self.as_point(p1_raw if p1_raw is not None else self.get_param("default_p1"))
        if p1 is None:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Point1 is not a valid point (need x,y): {p1_raw!r:.80}")
        p2 = self.as_point(p2_raw if p2_raw is not None else self.get_param("default_p2"))
        if p2 is None:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Point2 is not a valid point (need x,y): {p2_raw!r:.80}")

        x1, y1 = p1
        x2, y2 = p2

        dx = float(abs(x2 - x1))
        dy = float(abs(y2 - y1))
        dist_px = float(np.hypot(dx, dy))
        scale = float(self.get_param("scale_factor", 1.0))
        dist_scaled = dist_px * scale

        min_d = float(self.get_param("min_distance", 0.0))
        max_d = float(self.get_param("max_distance", 1000.0))
        status = ToolStatus.OK if (min_d <= dist_scaled <= max_d) else ToolStatus.NG

        overlays = [
            {"type": "cross", "pt": (int(x1), int(y1)), "size": 8, "color": (0, 255, 0)},
            {"type": "cross", "pt": (int(x2), int(y2)), "size": 8, "color": (0, 255, 0)},
            {"type": "line", "pt1": (int(x1), int(y1)), "pt2": (int(x2), int(y2)), "color": (255, 255, 0), "thickness": 2},
            {"type": "text", "text": f"P2P: {dist_scaled:.2f} (dx:{dx:.1f}, dy:{dy:.1f})", "pt": (int((x1+x2)/2), int((y1+y2)/2)-10), "color": (255, 255, 0)}
        ]

        return ToolExecutionResult(
            status=status,
            message=f"P2P Dist: {dist_scaled:.2f}",
            outputs={
                "Distance": dist_scaled,
                "Delta_X": dx * scale,
                "Delta_Y": dy * scale
            },
            overlays=overlays
        )


@register_tool
class IntensityMeasureTool(VisionToolBase):
    category = "Measurement"
    tool_name = "Intensity Measure"
    description = "Measures mean, min, max, and std deviation of gray intensity inside ROI."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Mean"] = ToolPort("Mean", DataType.VALUE, "Mean intensity")
        self.outputs["StdDev"] = ToolPort("StdDev", DataType.VALUE, "Standard deviation")
        self.outputs["Min"] = ToolPort("Min", DataType.VALUE, "Minimum value")
        self.outputs["Max"] = ToolPort("Max", DataType.VALUE, "Maximum value")

    def _init_parameters(self):
        self.parameters = {
            "roi": [200, 200, 200, 150],  # x, y, w, h
            "min_mean": 20.0,
            "max_mean": 240.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)
        rx, ry, rw, rh = self.get_roi("roi", [200, 200, 200, 150], img_shape=gray.shape)

        crop = gray[ry:ry+rh, rx:rx+rw]
        if crop.size == 0:
            return ToolExecutionResult(status=ToolStatus.NG, message="Empty ROI crop")
        mean_val = float(np.mean(crop))
        std_val = float(np.std(crop))
        min_val = float(np.min(crop))
        max_val = float(np.max(crop))

        min_m = float(self.get_param("min_mean", 20.0))
        max_m = float(self.get_param("max_mean", 240.0))
        status = ToolStatus.OK if (min_m <= mean_val <= max_m) else ToolStatus.NG

        overlays = [
            {"type": "rect", "box": [rx, ry, rw, rh], "color": (255, 0, 255), "label": f"Mean:{mean_val:.1f} Std:{std_val:.1f}"}
        ]

        return ToolExecutionResult(
            status=status,
            message=f"Intensity Mean={mean_val:.2f}, StdDev={std_val:.2f}",
            outputs={
                "Mean": mean_val,
                "StdDev": std_val,
                "Min": min_val,
                "Max": max_val
            },
            overlays=overlays
        )


@register_tool
class PixelCountTool(VisionToolBase):
    category = "Measurement"
    tool_name = "Pixel Count"
    description = "Counts pixels matching low/high threshold range within specified ROI."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Pixel_Count"] = ToolPort("Pixel_Count", DataType.VALUE, "Number of qualifying pixels")
        self.outputs["Ratio"] = ToolPort("Ratio", DataType.VALUE, "Percentage of ROI area (0-100%)")

    def _init_parameters(self):
        self.parameters = {
            "roi": [100, 100, 300, 200],
            "low_threshold": 128,
            "high_threshold": 255,
            "min_count": 100,
            "max_count": 50000
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)
        rx, ry, rw, rh = self.get_roi("roi", [100, 100, 300, 200], img_shape=gray.shape)

        crop = gray[ry:ry+rh, rx:rx+rw]
        if crop.size == 0:
            return ToolExecutionResult(status=ToolStatus.NG, message="Empty ROI crop")
        low_th = int(self.get_param("low_threshold", 128))
        high_th = int(self.get_param("high_threshold", 255))

        mask = (crop >= low_th) & (crop <= high_th)
        count = int(np.count_nonzero(mask))
        total_roi_pixels = rw * rh
        ratio = float((count / max(1, total_roi_pixels)) * 100.0)

        min_c = int(self.get_param("min_count", 100))
        max_c = int(self.get_param("max_count", 50000))
        is_ok = min_c <= count <= max_c

        overlays = [
            {"type": "rect", "box": [rx, ry, rw, rh], "color": (0, 240, 255), "label": f"Count:{count} ({ratio:.1f}%)"}
        ]

        return ToolExecutionResult(
            status=ToolStatus.OK if is_ok else ToolStatus.NG,
            message=f"Pixel count: {count} ({ratio:.1f}% of ROI)",
            outputs={"Pixel_Count": count, "Ratio": ratio},
            overlays=overlays
        )


@register_tool
class EdgeDistanceTool(VisionToolBase):
    category = "Measurement"
    tool_name = "Edge Distance"
    description = "Measures distance between two feature edges along scan projection axis."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Distance"] = ToolPort("Distance", DataType.VALUE, "Measured distance between edges (pixels)")

    def _init_parameters(self):
        self.parameters = {
            "start_pt": [100, 300],
            "end_pt": [500, 300],
            "min_distance": 10.0,
            "max_distance": 1000.0,
            "edge_threshold": 25.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)
        p1 = self.get_param("start_pt", [100, 300])
        p2 = self.get_param("end_pt", [500, 300])
        x1, y1 = float(p1[0]), float(p1[1])
        x2, y2 = float(p2[0]), float(p2[1])

        length = int(np.hypot(x2 - x1, y2 - y1))
        if length < 10:
            return ToolExecutionResult(status=ToolStatus.NG, message="Projection path too short")

        h, w = gray.shape[:2]
        xs = np.linspace(x1, x2, length)
        ys = np.linspace(y1, y2, length)

        valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        if np.count_nonzero(valid) < 2:
            return ToolExecutionResult(status=ToolStatus.NG, message="Projection path out of bounds", outputs={"Distance": 0.0})
        profile = gray[ys[valid].astype(int), xs[valid].astype(int)].astype(np.float32)
        if profile.size < 2:
            return ToolExecutionResult(status=ToolStatus.NG, message="Projection profile too small", outputs={"Distance": 0.0})
        grad = np.abs(np.gradient(profile))

        thresh = float(self.get_param("edge_threshold", 25.0))
        peaks = np.where(grad >= thresh)[0]

        if len(peaks) >= 2:
            e1_idx = peaks[0]
            e2_idx = peaks[-1]
            e1 = (float(xs[valid][e1_idx]), float(ys[valid][e1_idx]))
            e2 = (float(xs[valid][e2_idx]), float(ys[valid][e2_idx]))
            dist = float(np.hypot(e2[0] - e1[0], e2[1] - e1[1]))

            min_d = float(self.get_param("min_distance", 10.0))
            max_d = float(self.get_param("max_distance", 1000.0))
            is_ok = min_d <= dist <= max_d

            overlays = [
                {"type": "line", "pt1": (int(e1[0]), int(e1[1])), "pt2": (int(e2[0]), int(e2[1])), "color": (0, 255, 255), "thickness": 2},
                {"type": "cross", "pt": (int(e1[0]), int(e1[1])), "size": 6, "color": (0, 255, 0)},
                {"type": "cross", "pt": (int(e2[0]), int(e2[1])), "size": 6, "color": (0, 255, 0)},
                {"type": "text", "text": f"EdgeDist: {dist:.2f}px", "pt": (int((e1[0]+e2[0])/2), int((e1[1]+e2[1])/2) - 10), "color": (0, 255, 255)}
            ]

            return ToolExecutionResult(
                status=ToolStatus.OK if is_ok else ToolStatus.NG,
                message=f"Edge Distance: {dist:.2f}px",
                outputs={"Distance": dist},
                overlays=overlays
            )

        return ToolExecutionResult(status=ToolStatus.NG, message="Fewer than 2 feature edges detected", outputs={"Distance": 0.0})


@register_tool
class HistogramTool(VisionToolBase):
    category = "Measurement"
    tool_name = "Histogram"
    description = "Statistical analysis of grayscale distribution (Mean, Median, Peak, StdDev, Contrast, Min, Max)."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Mean"] = ToolPort("Mean", DataType.VALUE, "Mean intensity")
        self.outputs["Median"] = ToolPort("Median", DataType.VALUE, "Median intensity")
        self.outputs["Peak"] = ToolPort("Peak", DataType.VALUE, "Peak (mode) intensity")
        self.outputs["StdDev"] = ToolPort("StdDev", DataType.VALUE, "Standard deviation")
        self.outputs["Contrast"] = ToolPort("Contrast", DataType.VALUE, "Contrast ratio")

    def _init_parameters(self):
        self.parameters = {
            "roi": [50, 50, 400, 300]
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)
        rx, ry, rw, rh = self.get_roi("roi", [50, 50, 400, 300], img_shape=gray.shape)

        crop = gray[ry:ry+rh, rx:rx+rw]
        if crop.size == 0:
            return ToolExecutionResult(status=ToolStatus.NG, message="Empty ROI crop")
        mean_v = float(np.mean(crop))
        std_v = float(np.std(crop))
        med_v = float(np.median(crop))
        min_v = float(np.min(crop))
        max_v = float(np.max(crop))

        # Peak (mode of histogram)
        hist = cv2.calcHist([crop], [0], None, [256], [0, 256]).flatten()
        peak_v = float(np.argmax(hist))

        # Contrast
        contrast = float((max_v - min_v) / max(1.0, max_v + min_v))

        overlays = [
            {"type": "rect", "box": [rx, ry, rw, rh], "color": (180, 100, 255), "label": f"Mean:{mean_v:.1f} Peak:{peak_v:.0f}"}
        ]

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Histogram: Mean={mean_v:.1f}, Median={med_v:.1f}, Peak={peak_v:.0f}, Std={std_v:.1f}",
            outputs={
                "Mean": mean_v,
                "Median": med_v,
                "Peak": peak_v,
                "StdDev": std_v,
                "Contrast": contrast
            },
            overlays=overlays
        )
