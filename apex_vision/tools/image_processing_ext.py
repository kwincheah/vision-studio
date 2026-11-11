"""
More Image Processing modules: crop, resize / rotate / flip, colour conversion, brightness and contrast,
image arithmetic, edge detection, and a focus (sharpness) measurement.

Every module takes an ``Image`` port and returns a BGR (3 channel) ``Image`` so that any module can follow any other.
"""
import cv2
import numpy as np
from typing import Any, Dict

from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from apex_vision.core.registry import register_tool

MAX_SIDE = 16384          # largest image a module will produce, so a typo cannot allocate gigabytes


def as_bgr(img: np.ndarray) -> np.ndarray:
    """A 3-channel uint8 copy-or-view of any image."""
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 1:
        return cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    if img.shape[2] == 3:
        return img
    return cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)


def _no_image() -> ToolExecutionResult:
    return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")


def _sizes(img: np.ndarray) -> Dict[str, Any]:
    return {"Width": int(img.shape[1]), "Height": int(img.shape[0])}


@register_tool
class ImageCropTool(VisionToolBase):
    category = "Image Processing"
    tool_name = "Image Crop"
    description = "Cuts a rectangular region out of the image. Draw the region on the image or type X, Y, W, H."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "The cropped region")
        self.outputs["Width"] = ToolPort("Width", DataType.VALUE, "Width of the crop")
        self.outputs["Height"] = ToolPort("Height", DataType.VALUE, "Height of the crop")

    def _init_parameters(self):
        self.parameters = {"roi": [100, 100, 300, 200]}      # x, y, w, h

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=1, min_h=1)
        if img is None:
            return _no_image()
        x, y, w, h = self.get_roi("roi", [100, 100, 300, 200], img_shape=img.shape)
        out = as_bgr(img)[y:y + h, x:x + w].copy()
        return ToolExecutionResult(
            status=ToolStatus.OK, message=f"Cropped {out.shape[1]}x{out.shape[0]} at ({x}, {y})",
            outputs={"Image": out, **_sizes(out)},
            overlays=[{"type": "rect", "box": (x, y, w, h), "color": (0, 200, 255)}])


@register_tool
class ImageTransformTool(VisionToolBase):
    category = "Image Processing"
    tool_name = "Image Transform"
    description = "Resize, rotate by any angle, rotate by 90 degrees or flip the image."

    OPERATIONS = ["Resize", "Rotate", "Rotate 90 CW", "Rotate 90 CCW", "Rotate 180", "Flip Horizontal", "Flip Vertical", "Mirror and Rotate"]

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Transformed image")
        self.outputs["Width"] = ToolPort("Width", DataType.VALUE, "Output width")
        self.outputs["Height"] = ToolPort("Height", DataType.VALUE, "Output height")

    def _init_parameters(self):
        self.parameters = {
            "operation": "Resize",
            "scale": 0.5,           # Resize: 0.5 halves the image
            "angle": 15.0,          # Rotate: degrees, positive turns anticlockwise
            "expand": True,         # Rotate: grow the canvas so the corners are not cut off
            "mirror": "Horizontal",  # Mirror and Rotate: None, Horizontal, Vertical or Diagonal (both), then turned by Angle
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=1, min_h=1)
        if img is None:
            return _no_image()
        img = as_bgr(img)
        h, w = img.shape[:2]
        op = self.get_param("operation", "Resize")
        try:
            if op == "Rotate 90 CW":
                out = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            elif op == "Rotate 90 CCW":
                out = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif op == "Rotate 180":
                out = cv2.rotate(img, cv2.ROTATE_180)
            elif op == "Flip Horizontal":
                out = cv2.flip(img, 1)
            elif op == "Flip Vertical":
                out = cv2.flip(img, 0)
            elif op in ("Rotate", "Mirror and Rotate"):
                if op == "Mirror and Rotate":
                    mirror = str(self.get_param("mirror", "Horizontal"))
                    img = cv2.flip(img, {"Horizontal": 1, "Vertical": 0, "Diagonal": -1}[mirror]) if mirror in ("Horizontal", "Vertical", "Diagonal") else img
                angle = self.as_float(self.get_param("angle", 0.0))
                m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
                nw, nh = w, h
                if bool(self.get_param("expand", True)):
                    cos, sin = abs(m[0, 0]), abs(m[0, 1])
                    nw, nh = int(round(h * sin + w * cos)), int(round(h * cos + w * sin))
                    m[0, 2] += nw / 2.0 - w / 2.0
                    m[1, 2] += nh / 2.0 - h / 2.0
                if max(nw, nh) > MAX_SIDE:
                    return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Result would be larger than {MAX_SIDE} px")
                out = cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))
            else:   # Resize
                scale = self.as_float(self.get_param("scale", 1.0), 1.0)
                nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
                if max(nw, nh) > MAX_SIDE:
                    return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Result would be larger than {MAX_SIDE} px")
                out = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        except cv2.error as exc:
            return ToolExecutionResult(status=ToolStatus.ERROR, message=f"{op} failed: {exc}")
        return ToolExecutionResult(status=ToolStatus.OK, message=f"{op}: {w}x{h} -> {out.shape[1]}x{out.shape[0]}",
                                   outputs={"Image": out, **_sizes(out)})


@register_tool
class ColorConvertTool(VisionToolBase):
    category = "Image Processing"
    tool_name = "Color Convert"
    description = "Converts to grayscale, HSV or Lab, or extracts one colour channel (red, green, blue, hue, saturation, value)."

    MODES = ["Grayscale", "Red channel", "Green channel", "Blue channel", "Hue", "Saturation", "Value", "HSV", "Lab",
             "Gray: Average", "Gray: Minimum", "Gray: Maximum", "Gray: User-defined", "HSI Channel 1", "HSI Channel 2", "HSI Channel 3",
             "YUV Channel 1", "YUV Channel 2", "YUV Channel 3"]

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Converted image")

    def _init_parameters(self):
        self.parameters = {"mode": "Grayscale", "coeff_r": 0.299, "coeff_g": 0.587, "coeff_b": 0.114}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=1, min_h=1)
        if img is None:
            return _no_image()
        bgr = as_bgr(img)
        mode = self.get_param("mode", "Grayscale")
        if mode.startswith("Gray: ") or mode.startswith("HSI") or mode.startswith("YUV"):
            f = bgr.astype(np.float32)
            b, g_, r = f[:, :, 0], f[:, :, 1], f[:, :, 2]
            if mode == "Gray: Average":
                ch = (r + g_ + b) / 3.0
            elif mode == "Gray: Minimum":
                ch = np.minimum(np.minimum(r, g_), b)
            elif mode == "Gray: Maximum":
                ch = np.maximum(np.maximum(r, g_), b)
            elif mode == "Gray: User-defined":
                ch = (self.as_float(self.get_param("coeff_r", 0.299)) * r + self.as_float(self.get_param("coeff_g", 0.587)) * g_
                      + self.as_float(self.get_param("coeff_b", 0.114)) * b)
            elif mode.startswith("YUV"):
                ch = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)[:, :, int(mode[-1]) - 1].astype(np.float32)
            else:                                                   # HSI: hue (angle), saturation (distance from grey), intensity (mean)
                inten = (r + g_ + b) / 3.0
                if mode.endswith("3"):
                    ch = inten
                elif mode.endswith("2"):
                    ch = np.where(inten > 1e-6, 1.0 - np.minimum(np.minimum(r, g_), b) / np.maximum(inten, 1e-6), 0.0) * 255.0
                else:
                    num_ = 0.5 * ((r - g_) + (r - b))
                    den = np.sqrt((r - g_) ** 2 + (r - b) * (g_ - b)) + 1e-6
                    theta = np.degrees(np.arccos(np.clip(num_ / den, -1.0, 1.0)))
                    ch = np.where(b <= g_, theta, 360.0 - theta) / 360.0 * 255.0
            out = cv2.cvtColor(np.clip(ch, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
            return ToolExecutionResult(status=ToolStatus.OK, message=f"Converted to {mode}", outputs={"Image": out})
        if mode == "HSV":
            out = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        elif mode == "Lab":
            out = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab)
        elif mode in ("Hue", "Saturation", "Value"):
            idx = ("Hue", "Saturation", "Value").index(mode)
            ch = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, idx]
            if mode == "Hue":
                ch = (ch.astype(np.uint16) * 255 // 179).astype(np.uint8)      # 0-179 -> 0-255 so it is visible
            out = cv2.cvtColor(ch, cv2.COLOR_GRAY2BGR)
        elif mode in ("Red channel", "Green channel", "Blue channel"):
            idx = {"Blue channel": 0, "Green channel": 1, "Red channel": 2}[mode]
            out = cv2.cvtColor(bgr[:, :, idx], cv2.COLOR_GRAY2BGR)
        else:
            out = cv2.cvtColor(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        return ToolExecutionResult(status=ToolStatus.OK, message=f"Converted to {mode}", outputs={"Image": out})


@register_tool
class BrightnessContrastTool(VisionToolBase):
    category = "Image Processing"
    tool_name = "Brightness Contrast"
    description = ("Brightens or darkens the image: manual brightness and contrast, gamma, automatic brightening to a "
                   "target level, histogram equalisation, or local contrast (CLAHE).")

    MODES = ["Manual", "Auto Brighten", "Gamma", "Equalize", "CLAHE"]

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Adjusted image")
        self.outputs["Mean_Before"] = ToolPort("Mean_Before", DataType.VALUE, "Average brightness before (0-255)")
        self.outputs["Mean_After"] = ToolPort("Mean_After", DataType.VALUE, "Average brightness after (0-255)")

    def _init_parameters(self):
        self.parameters = {
            "mode": "Auto Brighten",
            "brightness": 40,         # Manual: added to every pixel
            "contrast": 1.0,          # Manual: multiplier (1 = unchanged)
            "gamma": 0.6,             # Gamma: below 1 brightens, above 1 darkens
            "target_mean": 120,       # Auto Brighten: the average level to aim for
            "clip_limit": 3.0,        # CLAHE: contrast limit
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=1, min_h=1)
        if img is None:
            return _no_image()
        bgr = as_bgr(img)
        before = float(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).mean())
        mode = self.get_param("mode", "Auto Brighten")
        try:
            if mode == "Manual":
                out = cv2.convertScaleAbs(bgr, alpha=self.as_float(self.get_param("contrast", 1.0), 1.0),
                                          beta=self.as_float(self.get_param("brightness", 0.0)))
            elif mode == "Gamma":
                g = max(0.05, self.as_float(self.get_param("gamma", 1.0), 1.0))
                lut = (np.power(np.arange(256) / 255.0, g) * 255.0).clip(0, 255).astype(np.uint8)
                out = cv2.LUT(bgr, lut)
            elif mode == "Equalize":
                ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
                ycc[:, :, 0] = cv2.equalizeHist(ycc[:, :, 0])
                out = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)
            elif mode == "CLAHE":
                lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab)
                clahe = cv2.createCLAHE(clipLimit=max(0.1, self.as_float(self.get_param("clip_limit", 3.0), 3.0)),
                                        tileGridSize=(8, 8))
                lab[:, :, 0] = clahe.apply(lab[:, :, 0])
                out = cv2.cvtColor(lab, cv2.COLOR_Lab2BGR)
            else:   # Auto Brighten
                target = self.as_float(self.get_param("target_mean", 120.0), 120.0)
                gain = min(8.0, max(0.1, target / max(before, 1.0)))
                out = cv2.convertScaleAbs(bgr, alpha=gain, beta=0)
        except cv2.error as exc:
            return ToolExecutionResult(status=ToolStatus.ERROR, message=f"{mode} failed: {exc}")
        after = float(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).mean())
        return ToolExecutionResult(
            status=ToolStatus.OK, message=f"{mode}: average brightness {before:.1f} -> {after:.1f}",
            outputs={"Image": out, "Mean_Before": before, "Mean_After": after})


@register_tool
class ImageCalculateTool(VisionToolBase):
    category = "Image Processing"
    tool_name = "Image Calculate"
    description = ("Combines two images pixel by pixel: add, subtract, absolute difference (compare with a good sample), "
                   "multiply, average, AND / OR / XOR, brightest or darkest of the two.")

    OPERATIONS = ["Absolute Difference", "Subtract (A - B)", "Add", "Multiply", "Average", "Maximum", "Minimum",
                  "Bitwise AND", "Bitwise OR", "Bitwise XOR", "k1*A + k2*B + c", "k1*A + c", "A + c"]

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Image A")
        self.inputs["Image_B"] = ToolPort("Image_B", DataType.IMAGE, "Image B (a reference picture or a mask)")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Result")
        self.outputs["Mean"] = ToolPort("Mean", DataType.VALUE, "Average level of the result (0-255)")

    def _init_parameters(self):
        self.parameters = {"operation": "Absolute Difference", "image_weight1": 1.0, "image_weight2": 1.0,     # each picture is multiplied by its weight first
                           "calc_weight1": 1.0, "calc_weight2": 1.0, "image_offset": 0.0}                       # k1, k2 and c of the weighted types

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        a = self.get_input_image(context, "Image", min_w=1, min_h=1)
        b = self.get_input_image(context, "Image_B", min_w=1, min_h=1)
        if a is None:
            return _no_image()
        if b is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="Image B is missing: connect a second image to 'Image_B'")
        a, b = as_bgr(a), as_bgr(b)
        note = ""
        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
            note = " (B resized to A)"
        op = self.get_param("operation", "Absolute Difference")
        w1, w2 = self.as_float(self.get_param("image_weight1", 1.0), 1.0), self.as_float(self.get_param("image_weight2", 1.0), 1.0)
        if (w1, w2) != (1.0, 1.0):
            a, b = cv2.convertScaleAbs(a, alpha=w1), cv2.convertScaleAbs(b, alpha=w2)
        if op in ("k1*A + k2*B + c", "k1*A + c", "A + c"):
            k1, k2, c = (self.as_float(self.get_param(n, d), d) for n, d in (("calc_weight1", 1.0), ("calc_weight2", 1.0), ("image_offset", 0.0)))
            if op == "k1*A + k2*B + c":
                out = cv2.addWeighted(a, k1, b, k2, c)
            else:
                out = cv2.convertScaleAbs(a, alpha=(k1 if op == "k1*A + c" else 1.0), beta=c)
        elif op == "Subtract (A - B)":
            out = cv2.subtract(a, b)
        elif op == "Add":
            out = cv2.add(a, b)
        elif op == "Multiply":
            out = cv2.multiply(a, b, scale=1.0 / 255.0)
        elif op == "Average":
            out = cv2.addWeighted(a, 0.5, b, 0.5, 0)
        elif op == "Maximum":
            out = cv2.max(a, b)
        elif op == "Minimum":
            out = cv2.min(a, b)
        elif op == "Bitwise AND":
            out = cv2.bitwise_and(a, b)
        elif op == "Bitwise OR":
            out = cv2.bitwise_or(a, b)
        elif op == "Bitwise XOR":
            out = cv2.bitwise_xor(a, b)
        else:
            out = cv2.absdiff(a, b)
        mean = float(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).mean())
        return ToolExecutionResult(status=ToolStatus.OK, message=f"{op}{note}: mean {mean:.2f}",
                                   outputs={"Image": out, "Mean": mean})


@register_tool
class EdgeDetectionTool(VisionToolBase):
    category = "Image Processing"
    tool_name = "Edge Detection"
    description = "Finds edges over the whole image with Canny, Sobel, Scharr or Laplacian. Output is a white-on-black edge map."

    METHODS = ["Canny", "Sobel", "Scharr", "Laplacian"]

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Edge map")
        self.outputs["Edge_Pixels"] = ToolPort("Edge_Pixels", DataType.VALUE, "Number of edge pixels")
        self.outputs["Edge_Ratio"] = ToolPort("Edge_Ratio", DataType.VALUE, "Edge pixels as a percentage of the image")

    def _init_parameters(self):
        self.parameters = {
            "method": "Canny",
            "low_threshold": 50,        # Canny lower hysteresis limit; for the others, edges weaker than this are dropped
            "high_threshold": 150,      # Canny upper limit
            "blur_size": 3,             # smoothing before detection (odd, 1 = none)
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=3, min_h=3)
        if img is None:
            return _no_image()
        gray = self.to_grayscale(img)
        k = int(round(self.as_float(self.get_param("blur_size", 3), 3.0)))
        k = max(1, min(k, 31))
        if k % 2 == 0:
            k += 1
        if k > 1:
            gray = cv2.GaussianBlur(gray, (k, k), 0)
        lo = self.as_float(self.get_param("low_threshold", 50), 50.0)
        hi = self.as_float(self.get_param("high_threshold", 150), 150.0)
        method = self.get_param("method", "Canny")
        try:
            if method == "Canny":
                edges = cv2.Canny(gray, min(lo, hi), max(lo, hi))
            else:
                if method == "Sobel":
                    gx, gy = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
                    mag = cv2.magnitude(gx, gy)
                elif method == "Scharr":
                    gx, gy = cv2.Scharr(gray, cv2.CV_32F, 1, 0), cv2.Scharr(gray, cv2.CV_32F, 0, 1)
                    mag = cv2.magnitude(gx, gy)
                else:
                    mag = np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3))
                edges = np.where(mag >= lo, 255, 0).astype(np.uint8)
        except cv2.error as exc:
            return ToolExecutionResult(status=ToolStatus.ERROR, message=f"{method} failed: {exc}")
        count = int(np.count_nonzero(edges))
        ratio = 100.0 * count / edges.size
        return ToolExecutionResult(
            status=ToolStatus.OK, message=f"{method}: {count} edge pixels ({ratio:.2f}%)",
            outputs={"Image": cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR), "Edge_Pixels": count, "Edge_Ratio": ratio})


@register_tool
class FocusMeasureTool(VisionToolBase):
    category = "Measurement"
    tool_name = "Focus Measure"
    description = "Measures how sharp (in focus) the image or a region is. Higher is sharper. Fails below a minimum."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Sharpness"] = ToolPort("Sharpness", DataType.VALUE, "Variance of the Laplacian (higher = sharper)")

    def _init_parameters(self):
        self.parameters = {"roi": [0, 0, 640, 480], "min_sharpness": 0.0,
                           "assess_mode": "Laplacian Variance",     # also: Auto Correlation (for auto focus), Gradient Squared (for pictures rich in edges)
                           "noise_level": 0}                        # Auto Correlation: grey steps up to this size are ignored

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=3, min_h=3)
        if img is None:
            return _no_image()
        x, y, w, h = self.get_roi("roi", [0, 0, 640, 480], img_shape=img.shape)
        gray = self.to_grayscale(img)[y:y + h, x:x + w]
        if gray.shape[0] < 3 or gray.shape[1] < 3:
            return ToolExecutionResult(status=ToolStatus.NG, message="The region is too small to measure")
        mode = str(self.get_param("assess_mode", "Laplacian Variance"))
        gf = gray.astype(np.float64)
        if mode == "Auto Correlation":                              # Vollath: how alike neighbours one and two pixels away are
            noise = self.as_float(self.get_param("noise_level", 0), 0.0)
            if gf.shape[1] < 3:
                return ToolExecutionResult(status=ToolStatus.NG, message="The region is too small to measure")
            step = gf[:, 1:] - gf[:, :-1]
            keep = np.abs(step[:, :-1]) > noise if noise > 0 else np.ones_like(step[:, :-1], bool)
            prod1, prod2 = (gf[:, :-1] * gf[:, 1:])[:, :-1], gf[:, :-2] * gf[:, 2:]
            sharp = float((prod1 - prod2)[keep].mean()) if keep.any() else 0.0
        elif mode == "Gradient Squared":
            gx, gy = cv2.Sobel(gf, cv2.CV_64F, 1, 0, ksize=3), cv2.Sobel(gf, cv2.CV_64F, 0, 1, ksize=3)
            sharp = float((gx * gx + gy * gy).mean())
        else:
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        minimum = self.as_float(self.get_param("min_sharpness", 0.0))
        ok = sharp >= minimum
        return ToolExecutionResult(
            status=ToolStatus.OK if ok else ToolStatus.NG,
            message=f"Sharpness {sharp:.1f}" + ("" if ok else f" is below the minimum {minimum:g}"),
            outputs={"Sharpness": sharp},
            overlays=[{"type": "rect", "box": (x, y, w, h), "color": (0, 200, 90) if ok else (0, 0, 255)},
                      {"type": "text", "text": f"Sharpness {sharp:.1f}", "pt": (x + 6, y + 18), "color": (0, 255, 255)}])
