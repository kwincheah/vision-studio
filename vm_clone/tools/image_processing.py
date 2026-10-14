"""
Image Processing Tools: Binarization, Morphology, Filtering, Enhancement, Affine/Fixture.
Matches HikRobot Vision Master Image Processing category.
"""
import cv2
import numpy as np
from typing import Dict, Any, List
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class ImageBinarizationTool(VisionToolBase):
    category = "Image Processing"
    tool_name = "Image Binarization"
    description = "Converts grayscale/color image to binary using Manual, Otsu, or Adaptive thresholding."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Binarized image")

    def _init_parameters(self):
        self.parameters = {
            "method": "Otsu",  # Manual, Otsu, Adaptive
            "threshold": 128,
            "invert": False,
            "adaptive_block_size": 11,
            "adaptive_c": 2
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)
        method = self.get_param("method", "Otsu")
        invert = bool(self.get_param("invert", False))
        thresh_val = int(self.get_param("threshold", 128))

        if method == "Otsu":
            flags = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
            flags |= cv2.THRESH_OTSU
            ret, dst = cv2.threshold(gray, 0, 255, flags)
            used_th = ret
        elif method == "Adaptive":
            bs = int(self.get_param("adaptive_block_size", 11))
            if bs % 2 == 0:
                bs += 1
            c = float(self.get_param("adaptive_c", 2))
            ttype = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
            dst = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, ttype, bs, c)
            used_th = "Adaptive"
        else:  # Manual
            ttype = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
            ret, dst = cv2.threshold(gray, thresh_val, 255, ttype)
            used_th = thresh_val

        # Convert back to 3-channel for consistent display
        dst_bgr = cv2.cvtColor(dst, cv2.COLOR_GRAY2BGR)

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Binarized via {method} (Threshold: {used_th})",
            outputs={"Image": dst_bgr},
            overlays=[{"type": "text", "text": f"Binarized ({method})", "pt": (15, 25), "color": (255, 255, 0)}]
        )


@register_tool
class ImageFilterTool(VisionToolBase):
    category = "Image Processing"
    tool_name = "Image Filter"
    description = "Spatial filtering: Gaussian blur, Median filter, Bilateral, or Sharpening."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Filtered output image")

    def _init_parameters(self):
        self.parameters = {
            "filter_type": "Gaussian",  # Gaussian, Median, Sharpen, Bilateral
            "kernel_size": 5,
            "sigma": 1.5
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        ftype = self.get_param("filter_type", "Gaussian")
        ksize = int(self.get_param("kernel_size", 5))
        if ksize % 2 == 0:
            ksize += 1
        sigma = float(self.get_param("sigma", 1.5))

        if ftype == "Gaussian":
            dst = cv2.GaussianBlur(img, (ksize, ksize), sigma)
        elif ftype == "Median":
            dst = cv2.medianBlur(img, ksize)
        elif ftype == "Sharpen":
            kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
            dst = cv2.filter2D(img, -1, kernel)
        else:  # Bilateral
            dst = cv2.bilateralFilter(img, d=9, sigmaColor=75, sigmaSpace=75)

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Applied {ftype} filter (k={ksize})",
            outputs={"Image": dst}
        )


@register_tool
class ImageMorphologyTool(VisionToolBase):
    category = "Image Processing"
    tool_name = "Image Morphology"
    description = "Morphological operations: Dilate, Erode, Open, Close, Gradient."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Processed image")

    def _init_parameters(self):
        self.parameters = {
            "operation": "Open",  # Dilate, Erode, Open, Close, Gradient
            "kernel_size": 3,
            "iterations": 1
        }

    #: Upper bound on the structuring element.  A larger kernel is almost certainly a
    #: typo, and OpenCV allocates it eagerly.
    MAX_KERNEL = 255

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        op = self.get_param("operation", "Open")

        # `kernel_size` must be a positive *odd* integer.  OpenCV asserts on 0 and on
        # negative sizes (cv::normalizeAnchor), and an even size has no true centre so
        # the result is shifted by half a pixel.  A blank or non-numeric entry used to
        # raise straight out of `int()` and surface as a generic pipeline exception.
        ksize = int(round(self.as_float(self.get_param("kernel_size", 3), 3.0)))
        ksize = max(1, min(ksize, self.MAX_KERNEL))
        if ksize % 2 == 0:
            ksize += 1

        iters = max(1, int(round(self.as_float(self.get_param("iterations", 1), 1.0))))

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (ksize, ksize))

        op_map = {
            "Dilate": cv2.MORPH_DILATE,
            "Erode": cv2.MORPH_ERODE,
            "Open": cv2.MORPH_OPEN,
            "Close": cv2.MORPH_CLOSE,
            "Gradient": cv2.MORPH_GRADIENT
        }
        morph_op = op_map.get(op, cv2.MORPH_OPEN)
        try:
            dst = cv2.morphologyEx(img, morph_op, kernel, iterations=iters)
        except cv2.error as exc:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Morphology '{op}' failed (k={ksize}, iters={iters}): {exc}")

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Morphology: {op} (k={ksize}, iters={iters})",
            outputs={"Image": dst}
        )
