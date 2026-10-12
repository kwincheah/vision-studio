"""
Image Output and Traceability Tools.
Matches HikRobot Vision Master Acquisition & Image Output category:
- Image Output (Saves original or processed inspection images to disk with formatted timestamp naming)
- Image Buffer (Circular FIFO memory buffer storing recent and NG defect frames for offline inspection)
"""
import os
import time
import cv2
import numpy as np
from collections import deque
from typing import Dict, Any, List, Deque
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class ImageOutputTool(VisionToolBase):
    category = "Acquisition"
    tool_name = "Image Output"
    description = "Saves acquired or processed images to disk with date/time formatting and quality options."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Image to save")
        self.inputs["Trigger"] = ToolPort("Trigger", DataType.BOOLEAN, "Save trigger condition")
        self.outputs["File_Path"] = ToolPort("File_Path", DataType.STRING, "Saved image absolute path")

    def _init_parameters(self):
        self.parameters = {
            "save_directory": "./saved_images",
            "file_format": "PNG",  # PNG, JPEG, BMP
            "save_mode": "Always Save",  # Always Save, Only on NG, Only on OK
            "image_quality": 95
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=1, min_h=1)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid image to save")

        save_dir = self.get_param("save_directory", "./saved_images")
        os.makedirs(save_dir, exist_ok=True)

        fmt = self.get_param("file_format", "PNG").lower()
        t_str = time.strftime("%Y%m%d_%H%M%S")
        filename = f"VM_IMG_{t_str}_{int(time.time()*1000)%1000}.{fmt}"
        filepath = os.path.join(save_dir, filename)

        try:
            cv2.imwrite(filepath, img)
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Saved image to: {filename}",
                outputs={"File_Path": filepath},
                overlays=[{"type": "text", "text": f"Output: {filename}", "pt": (15, 50), "color": (0, 240, 255)}]
            )
        except Exception as e:
            return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Failed to write image: {str(e)}")


@register_tool
class ImageBufferTool(VisionToolBase):
    category = "Acquisition"
    tool_name = "Image Buffer"
    description = "Circular FIFO image buffer for defect review and solution traceability."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image stream")
        self.outputs["Buffer_Count"] = ToolPort("Buffer_Count", DataType.VALUE, "Current count in buffer")
        self.outputs["Latest_Image"] = ToolPort("Latest_Image", DataType.IMAGE, "Latest buffered image")

    def _init_parameters(self):
        self.parameters = {
            "buffer_capacity": 30,
            "buffer_condition": "All Images"  # All Images, NG Only
        }
        self.buffer_queue: Deque[np.ndarray] = deque(maxlen=30)

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context, min_w=1, min_h=1)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid image provided")

        cap = int(self.get_param("buffer_capacity", 30))
        if self.buffer_queue.maxlen != cap:
            self.buffer_queue = deque(self.buffer_queue, maxlen=cap)

        self.buffer_queue.append(img.copy())
        cnt = len(self.buffer_queue)

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Image Buffer: {cnt}/{cap} frames cached",
            outputs={"Buffer_Count": cnt, "Latest_Image": img},
            overlays=[{"type": "text", "text": f"Buffer: {cnt}/{cap}", "pt": (15, 75), "color": (255, 179, 0)}]
        )
