"""
Core data structures for the Vision Master Clone.
Provides Tool base class, Execution Context, Status, and Pin definitions.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import time
import numpy as np


class ToolStatus(Enum):
    READY = "Ready"
    RUNNING = "Running"
    OK = "OK"
    NG = "NG"
    ERROR = "Error"
    BYPASS = "Bypass"
    TIMEOUT = "Timeout"


class DataType(Enum):
    IMAGE = "Image"
    REGION = "Region"  # Box / ROI / Points
    LINE = "Line"
    CIRCLE = "Circle"
    POINT = "Point"
    VALUE = "Value"  # float/int
    STRING = "String"
    BOOLEAN = "Boolean"
    DICT = "Dict"
    ANY = "Any"


def is_compatible_type(src: DataType, dst: DataType) -> bool:
    """Type-checking rule consistent with industrial DAG port rules."""
    if src == DataType.ANY or dst == DataType.ANY:
        return True
    if src == dst:
        return True
    if src in (DataType.VALUE, DataType.BOOLEAN) and dst in (DataType.VALUE, DataType.BOOLEAN):
        return True
    return False


@dataclass
class ToolPort:
    name: str
    data_type: DataType
    description: str = ""
    value: Any = None


@dataclass
class ToolExecutionResult:
    status: ToolStatus = ToolStatus.READY
    message: str = ""
    elapsed_ms: float = 0.0
    outputs: Dict[str, Any] = field(default_factory=dict)
    overlays: List[Dict[str, Any]] = field(default_factory=list)  # Draw commands on canvas


class VisionToolBase:
    """Base class for all Vision Master tools (both built-in and plugin extensions)."""
    category: str = "General"
    tool_name: str = "BaseTool"
    description: str = ""
    plugin_id: str = "builtin"
    param_definitions: Dict[str, Any] = {}

    def __init__(self, instance_id: str, name: Optional[str] = None):
        self.instance_id: str = instance_id
        self.name: str = name or self.tool_name
        self.enabled: bool = True
        self.inputs: Dict[str, ToolPort] = {}
        self.outputs: Dict[str, ToolPort] = {}
        self.parameters: Dict[str, Any] = {}
        self._init_ports()
        self._init_parameters()

    def _init_ports(self):
        """Define inputs and outputs."""
        pass

    def _init_parameters(self):
        """Define parameter schema and default values."""
        pass

    def get_param_defs(self) -> Dict[str, Any]:
        """Returns typed parameter schema definitions if defined."""
        return getattr(self, "param_definitions", {}) or {}

    def set_param(self, key: str, value: Any):
        if key in self.parameters:
            self.parameters[key] = value

    def get_param(self, key: str, default: Any = None) -> Any:
        return self.parameters.get(key, default)

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        """
        Execute the tool algorithm.
        :param context: Contains resolved inputs and global context.
        :return: ToolExecutionResult
        """
        raise NotImplementedError

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "tool_name": self.tool_name,
            "category": self.category,
            "name": self.name,
            "enabled": self.enabled,
            "parameters": self.parameters,
        }

    def load_dict(self, data: Dict[str, Any]):
        self.name = data.get("name", self.name)
        self.enabled = data.get("enabled", self.enabled)
        self.parameters.update(data.get("parameters", {}))

    def get_input_image(
        self,
        context: Dict[str, Any],
        port_name: str = "Image",
        min_w: int = 4,
        min_h: int = 4
    ) -> Optional[np.ndarray]:
        """
        Safely extracts and validates a numpy image from the execution context.
        Returns a valid ndarray, or None if missing, non-numpy, empty, or too small.
        """
        img = context.get(port_name)
        if img is None or not isinstance(img, np.ndarray):
            return None
        if img.size == 0 or img.ndim < 2:
            return None
        h, w = img.shape[:2]
        if h < min_h or w < min_w:
            return None
        return img

    def get_roi(
        self,
        key: str = "roi",
        default: Optional[List[int]] = None,
        img_shape: Optional[Tuple[int, int]] = None
    ) -> Tuple[int, int, int, int]:
        """
        Safely retrieves and validates a bounding box ROI [x, y, w, h].
        Clamps to image boundary if img_shape=(h, w) is provided.
        """
        if default is None:
            default = [0, 0, 100, 100]
        val = self.get_param(key, default)
        if not isinstance(val, (list, tuple)) or len(val) < 4:
            val = default
        try:
            rx, ry, rw, rh = int(val[0]), int(val[1]), int(val[2]), int(val[3])
        except (ValueError, TypeError):
            rx, ry, rw, rh = int(default[0]), int(default[1]), int(default[2]), int(default[3])

        if img_shape is not None and len(img_shape) >= 2:
            h, w = img_shape[:2]
            rx = max(0, min(rx, max(0, w - 1)))
            ry = max(0, min(ry, max(0, h - 1)))
            rw = max(1, min(rw, max(1, w - rx)))
            rh = max(1, min(rh, max(1, h - ry)))

        return rx, ry, rw, rh

    @staticmethod
    def to_grayscale(img: np.ndarray) -> np.ndarray:
        """Safely convert 2D or 3D/4D numpy array to single-channel uint8 grayscale."""
        import cv2
        if not isinstance(img, np.ndarray) or img.size == 0:
            return np.zeros((1, 1), dtype=np.uint8)
        if img.ndim == 2:
            return img if img.dtype == np.uint8 else np.clip(img, 0, 255).astype(np.uint8)
        if img.ndim == 3:
            c = img.shape[2]
            if c == 1:
                res = img[:, :, 0]
            elif c == 3:
                res = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            elif c == 4:
                res = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
            else:
                res = img[:, :, 0]
            return res if res.dtype == np.uint8 else np.clip(res, 0, 255).astype(np.uint8)
        return img.reshape(img.shape[0], img.shape[1], -1)[:, :, 0].astype(np.uint8)


class MissingPluginPlaceholderTool(VisionToolBase):
    """Fallback placeholder for an unavailable or uninstalled third-party plugin tool."""
    category = "Missing Plugin"
    tool_name = "Missing Plugin Tool"
    description = "Placeholder for an uninstalled or missing vision tool plugin."

    def __init__(self, instance_id: str, name: str = None, missing_tool_name: str = ""):
        super().__init__(instance_id, name)
        self.missing_tool_name = missing_tool_name or name or "Unknown"

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        return ToolExecutionResult(
            status=ToolStatus.ERROR,
            message=f"Plugin tool '{self.missing_tool_name}' is not installed or failed to load."
        )

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["tool_name"] = self.missing_tool_name
        return d


