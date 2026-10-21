"""Sample Third-Party Vision Plugin for Vision Master Clone.

Demonstrates:
- IVisionPlugin interface implementation
- Custom PluginToolBase tool with typed input/output ports
- Parameter schema definitions (ParamDef) with type constraints and enum choices
- Robust image processing and exception containment
- Plugin lifecycle hooks (on_load, on_unload)
"""
import cv2
import numpy as np
from typing import Dict, Any, List, Type

from apex_vision.sdk import (
    IVisionPlugin,
    PluginMetadata,
    PluginToolBase,
    ParamDef,
    ParamType,
    DataType,
    ToolPort,
    ToolExecutionResult,
    ToolStatus,
)


class SobelEdgeTool(PluginToolBase):
    """Sobel Edge Detection Tool developed as a standalone plugin."""
    plugin_id = "sample_sobel_edge_plugin"
    category = "Custom Filters"
    tool_name = "Sobel Edge Detector"
    description = "Computes image derivatives and edge gradients using the Sobel operator."

    param_definitions = {
        "ksize": ParamDef(
            name="ksize",
            param_type=ParamType.INT,
            default_value=3,
            description="Sobel kernel aperture size (1, 3, 5, or 7)",
            min_value=1,
            max_value=7,
            step=2,
            choices=["1", "3", "5", "7"]
        ),
        "direction": ParamDef(
            name="direction",
            param_type=ParamType.ENUM,
            default_value="Both",
            description="Gradient orientation calculation mode",
            choices=["Both", "Horizontal (X)", "Vertical (Y)"]
        ),
        "scale": ParamDef(
            name="scale",
            param_type=ParamType.FLOAT,
            default_value=1.0,
            description="Optional scale factor for computed derivative values",
            min_value=0.1,
            max_value=10.0,
            step=0.1
        ),
        "delta": ParamDef(
            name="delta",
            param_type=ParamType.FLOAT,
            default_value=0.0,
            description="Optional delta value added to the results prior to conversion",
            min_value=0.0,
            max_value=255.0,
            step=1.0
        ),
        "invert": ParamDef(
            name="invert",
            param_type=ParamType.BOOLEAN,
            default_value=False,
            description="Invert edge response (black edges on white background)"
        )
    }

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image for edge detection")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Gradient / edge magnitude image")
        self.outputs["Edge_Intensity"] = ToolPort("Edge_Intensity", DataType.VALUE, "Average gradient magnitude across the image")

    def _init_parameters(self):
        self.parameters = {
            "ksize": 3,
            "direction": "Both",
            "scale": 1.0,
            "delta": 0.0,
            "invert": False
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        try:
            gray = self.to_grayscale(img)
            ksize = int(self.get_param("ksize", 3))
            if ksize not in (1, 3, 5, 7):
                ksize = 3
            direction = str(self.get_param("direction", "Both"))
            scale = float(self.get_param("scale", 1.0))
            delta = float(self.get_param("delta", 0.0))
            invert = bool(self.get_param("invert", False))

            if direction == "Horizontal (X)":
                grad = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=ksize, scale=scale, delta=delta)
                magnitude = np.abs(grad)
            elif direction == "Vertical (Y)":
                grad = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=ksize, scale=scale, delta=delta)
                magnitude = np.abs(grad)
            else:  # "Both"
                grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=ksize, scale=scale, delta=delta)
                grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=ksize, scale=scale, delta=delta)
                magnitude = cv2.magnitude(grad_x, grad_y)

            magnitude_norm = np.clip(magnitude, 0, 255).astype(np.uint8)

            if invert:
                magnitude_norm = cv2.bitwise_not(magnitude_norm)

            dst_bgr = cv2.cvtColor(magnitude_norm, cv2.COLOR_GRAY2BGR)
            mean_intensity = float(np.mean(magnitude_norm))

            return ToolExecutionResult(
                status=ToolStatus.OK,
                outputs={
                    "Image": dst_bgr,
                    "Edge_Intensity": mean_intensity
                },
                message=f"Sobel edge completed (mean intensity: {mean_intensity:.2f})"
            )
        except Exception as e:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Sobel processing error: {str(e)}"
            )


class SampleSobelPlugin(IVisionPlugin):
    """Entry point plugin descriptor for Sobel Edge Detector."""

    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            plugin_id="sample_sobel_edge_plugin",
            name="Sobel Edge Detector",
            version="1.0.0",
            author="ThirdParty Vision Lab",
            description="High-performance edge detection using directional Sobel operators.",
            category="Custom Filters",
            min_sdk_version="1.0.0",
            tags=["edge", "filter", "gradient", "opencv"]
        )

    @classmethod
    def register_tools(cls) -> List[Type[PluginToolBase]]:
        return [SobelEdgeTool]

    @classmethod
    def on_load(cls) -> bool:
        return True

    @classmethod
    def on_unload(cls):
        pass
