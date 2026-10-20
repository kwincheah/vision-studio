"""
Image Output and Traceability Tools.
Matches HikRobot Vision Master Acquisition & Image Output category:
- Image Output (Saves original or processed inspection images to disk with formatted timestamp naming)
- Image Buffer (Circular FIFO memory buffer storing recent and NG defect frames for offline inspection)
"""
import os
import time
import cv2
from vm_clone.core.imageio import imwrite
import numpy as np
from collections import deque
from typing import Dict, Any, Deque, Optional
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

        # The `Trigger` port gates the write.  It was declared but never consulted,
        # so a module configured to save only on an external trigger saved anyway.
        # An absent trigger means "not wired", which is treated as always-fire.
        trigger = context.get("Trigger")
        if trigger is not None and not bool(trigger):
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message="Save skipped: trigger is inactive",
                outputs={"File_Path": ""})

        # `save_mode` was likewise inert: "Only on NG" and "Only on OK" behaved as
        # "Always Save", filling the disk during a pass run.  The verdict arrives on
        # the conventional result ports.
        mode = str(self.get_param("save_mode", "Always Save"))
        if mode != "Always Save":
            verdict = self._resolve_verdict(context)
            if verdict is not None:
                if mode == "Only on NG" and verdict:
                    return ToolExecutionResult(
                        status=ToolStatus.OK,
                        message="Save skipped: result is OK (mode: Only on NG)",
                        outputs={"File_Path": ""})
                if mode == "Only on OK" and not verdict:
                    return ToolExecutionResult(
                        status=ToolStatus.OK,
                        message="Save skipped: result is NG (mode: Only on OK)",
                        outputs={"File_Path": ""})

        save_dir = self.get_param("save_directory", "./saved_images")
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as exc:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Cannot create save directory '{save_dir}': {exc}")

        fmt = self.get_param("file_format", "PNG").lower()
        t_str = time.strftime("%Y%m%d_%H%M%S")
        filename = f"VM_IMG_{t_str}_{int(time.time()*1000)%1000}.{fmt}"
        filepath = os.path.join(save_dir, filename)

        # `cv2.imwrite` signals failure by returning False, not by raising, so the
        # return value must be checked: a full disk, a read-only directory or an
        # unsupported extension previously still reported "Saved image to: ...".
        # `image_quality` was also unused; it is applied for the lossy formats.
        params = []
        if fmt in ("jpg", "jpeg"):
            params = [int(cv2.IMWRITE_JPEG_QUALITY),
                      max(1, min(100, int(self.as_float(
                          self.get_param("image_quality", 95), 95))))]
        try:
            written = imwrite(filepath, img, params)
        except Exception as exc:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Failed to write image: {exc}")

        if not written:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Image writer rejected '{filepath}' "
                        f"(format '{fmt}', shape {getattr(img, 'shape', '?')})")

        if not os.path.exists(filepath):
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Image writer reported success but '{filepath}' does not exist")

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Saved image to: {filename}",
            outputs={"File_Path": filepath, "File_Size": os.path.getsize(filepath)},
            overlays=[{"type": "text", "text": f"Output: {filename}", "pt": (15, 50), "color": (0, 240, 255)}]
        )

    @staticmethod
    def _resolve_verdict(context: Dict[str, Any]) -> Optional[bool]:
        """Read the upstream pass/fail verdict, or ``None`` when it is not supplied."""
        for key in ("Result", "Status", "Branch_Result", "OK", "Pass"):
            if key not in context:
                continue
            value = context[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                text = value.strip().upper()
                if text in ("OK", "PASS", "TRUE", "1"):
                    return True
                if text in ("NG", "FAIL", "FALSE", "0"):
                    return False
        return None


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

        # `deque(maxlen=...)` rejects a negative capacity, so the value is clamped to a
        # usable range rather than passed straight through.
        cap = self.get_bounded_param("buffer_capacity", 30, minimum=1, maximum=100000,
                                     integer=True)
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
