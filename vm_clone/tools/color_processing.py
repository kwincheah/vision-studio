"""
Color Processing Tools.
Implements:
- Color Extraction (HSV segmentation, dominant color masking, color area computation)
- Color Measurement (RGB / HSV mean and standard deviation)
- Color Transformation (Color space conversion BGR -> HSV, LAB, YCrCb, Grayscale)
"""
import cv2
import numpy as np
from typing import Dict, Any, List
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class ColorExtractionTool(VisionToolBase):
    category = "Color Processing"
    tool_name = "Color Extraction"
    description = "Extracts target colors in HSV space (Red, Green, Blue, Yellow, Custom) and masks non-target pixels."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input color image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Masked result image")
        self.outputs["Mask"] = ToolPort("Mask", DataType.IMAGE, "Binary segmentation mask")
        self.outputs["Color_Ratio"] = ToolPort("Color_Ratio", DataType.VALUE, "Percentage of target color (0-100%)")
        self.outputs["Pixel_Count"] = ToolPort("Pixel_Count", DataType.VALUE, "Count of target color pixels")

    def _init_parameters(self):
        self.parameters = {
            "preset_color": "Green",  # Red, Green, Blue, Yellow, Custom
            "h_min": 35,
            "h_max": 85,
            "s_min": 40,
            "s_max": 255,
            "v_min": 40,
            "v_max": 255,
            "min_ratio": 5.0,
            "max_ratio": 100.0,
            "mask_output": "Color Keep"  # Color Keep, Binary Mask, Inverse
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=2, min_h=2)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        if len(img.shape) == 2:
            img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif len(img.shape) == 3 and img.shape[2] == 4:
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif len(img.shape) == 3 and img.shape[2] == 3:
            img_bgr = img
        else:
            return ToolExecutionResult(status=ToolStatus.NG, message="Unsupported image channel format")

        preset = self.get_param("preset_color", "Green")
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

        # Apply presets or custom HSV range
        if preset == "Green":
            h_min, h_max = 35, 85
            s_min, s_max = 40, 255
            v_min, v_max = 40, 255
        elif preset == "Red":
            # Red wraps around 0/180
            mask1 = cv2.inRange(hsv, np.array([0, 50, 50]), np.array([10, 255, 255]))
            mask2 = cv2.inRange(hsv, np.array([170, 50, 50]), np.array([180, 255, 255]))
            mask = cv2.bitwise_or(mask1, mask2)
            h_min, h_max, s_min, s_max, v_min, v_max = 0, 180, 50, 255, 50, 255
        elif preset == "Blue":
            h_min, h_max = 100, 130
            s_min, s_max = 50, 255
            v_min, v_max = 50, 255
        elif preset == "Yellow":
            h_min, h_max = 20, 35
            s_min, s_max = 60, 255
            v_min, v_max = 60, 255
        else:  # Custom
            h_min = int(self.get_param("h_min", 35))
            h_max = int(self.get_param("h_max", 85))
            s_min = int(self.get_param("s_min", 40))
            s_max = int(self.get_param("s_max", 255))
            v_min = int(self.get_param("v_min", 40))
            v_max = int(self.get_param("v_max", 255))

        if preset != "Red":
            lower = np.array([h_min, s_min, v_min], dtype=np.uint8)
            upper = np.array([h_max, s_max, v_max], dtype=np.uint8)
            mask = cv2.inRange(hsv, lower, upper)

        total_pixels = mask.shape[0] * mask.shape[1]
        target_count = int(cv2.countNonZero(mask))
        ratio = float((target_count / max(1, total_pixels)) * 100.0)

        min_r = float(self.get_param("min_ratio", 5.0))
        max_r = float(self.get_param("max_ratio", 100.0))
        is_ok = min_r <= ratio <= max_r

        mask_mode = self.get_param("mask_output", "Color Keep")
        if mask_mode == "Color Keep":
            out_img = cv2.bitwise_and(img_bgr, img_bgr, mask=mask)
        elif mask_mode == "Binary Mask":
            out_img = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        else:
            inv_mask = cv2.bitwise_not(mask)
            out_img = cv2.bitwise_and(img_bgr, img_bgr, mask=inv_mask)

        overlays = [
            {"type": "text", "text": f"Color: {preset} ({ratio:.1f}%)", "pt": (15, 30), "color": (0, 255, 0) if is_ok else (0, 0, 255)}
        ]

        return ToolExecutionResult(
            status=ToolStatus.OK if is_ok else ToolStatus.NG,
            message=f"Extracted {preset}: {ratio:.2f}% ({target_count} px) [{'PASS' if is_ok else 'FAIL'}]",
            outputs={
                "Image": out_img,
                "Mask": mask,
                "Color_Ratio": ratio,
                "Pixel_Count": target_count
            },
            overlays=overlays
        )


@register_tool
class ColorMeasurementTool(VisionToolBase):
    category = "Color Processing"
    tool_name = "Color Measurement"
    description = "Measures mean RGB and HSV channels and color similarity inside ROI."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input color image")
        self.outputs["Mean_R"] = ToolPort("Mean_R", DataType.VALUE, "Mean Red channel")
        self.outputs["Mean_G"] = ToolPort("Mean_G", DataType.VALUE, "Mean Green channel")
        self.outputs["Mean_B"] = ToolPort("Mean_B", DataType.VALUE, "Mean Blue channel")
        self.outputs["Mean_H"] = ToolPort("Mean_H", DataType.VALUE, "Mean Hue channel")
        self.outputs["Mean_S"] = ToolPort("Mean_S", DataType.VALUE, "Mean Saturation channel")
        self.outputs["Mean_V"] = ToolPort("Mean_V", DataType.VALUE, "Mean Value channel")

    def _init_parameters(self):
        self.parameters = {
            "roi": [100, 100, 200, 200],  # x, y, w, h
            "target_rgb": [0, 150, 0],
            "max_color_distance": 80.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=2, min_h=2)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif len(img.shape) == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif len(img.shape) == 3 and img.shape[2] != 3:
            return ToolExecutionResult(status=ToolStatus.NG, message="Unsupported image channel format")

        roi = self.get_param("roi", [100, 100, 200, 200])
        if not isinstance(roi, (list, tuple)) or len(roi) < 4:
            roi = [0, 0, img.shape[1], img.shape[0]]
        rx, ry, rw, rh = roi[0], roi[1], roi[2], roi[3]
        h, w = img.shape[:2]
        rx = max(0, min(int(rx), max(0, w - 1)))
        ry = max(0, min(int(ry), max(0, h - 1)))
        rw = max(1, min(int(rw), w - rx))
        rh = max(1, min(int(rh), h - ry))

        crop = img[ry:ry+rh, rx:rx+rw]
        if crop.size == 0:
            return ToolExecutionResult(status=ToolStatus.NG, message="Empty ROI crop")
        mean_b, mean_g, mean_r = cv2.mean(crop)[:3]

        crop_hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mean_h, mean_s, mean_v = cv2.mean(crop_hsv)[:3]

        target_rgb = self.get_param("target_rgb", [0, 150, 0])
        if not isinstance(target_rgb, (list, tuple)) or len(target_rgb) < 3:
            target_rgb = [0, 150, 0]
        tr, tg, tb = float(target_rgb[0]), float(target_rgb[1]), float(target_rgb[2])
        color_dist = float(np.sqrt((mean_r - tr)**2 + (mean_g - tg)**2 + (mean_b - tb)**2))

        max_dist = float(self.get_param("max_color_distance", 80.0))
        is_ok = color_dist <= max_dist

        overlays = [
            {"type": "rect", "box": [rx, ry, rw, rh], "color": (int(mean_b), int(mean_g), int(mean_r)), "label": f"R:{mean_r:.0f} G:{mean_g:.0f} B:{mean_b:.0f}"},
            {"type": "text", "text": f"Color Dist: {color_dist:.1f} (Tol: {max_dist:.0f})", "pt": (rx, max(20, ry - 10)), "color": (0, 255, 0) if is_ok else (0, 0, 255)}
        ]

        return ToolExecutionResult(
            status=ToolStatus.OK if is_ok else ToolStatus.NG,
            message=f"Measured RGB=({mean_r:.1f}, {mean_g:.1f}, {mean_b:.1f}), Dist={color_dist:.1f}",
            outputs={
                "Mean_R": float(mean_r),
                "Mean_G": float(mean_g),
                "Mean_B": float(mean_b),
                "Mean_H": float(mean_h),
                "Mean_S": float(mean_s),
                "Mean_V": float(mean_v)
            },
            overlays=overlays
        )
