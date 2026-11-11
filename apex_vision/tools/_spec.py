"""A compact way to define a module: its ports, settings and parameter editors in one declaration, plus the function that does the work.

    @define("Shade Correction", "Image Processing", "Evens out uneven lighting ...",
            inputs=[img("Image")], outputs=[img("Image")],
            params={"kernel_size": 15}, schema={"kernel_size": num(1, 50)})
    def shade_correction(tool, ctx):
        ...
        return ok("corrected", Image=out)

The function receives the module (``tool.get_param`` etc.) and its input context and returns ``ok(...)``, ``ng(...)`` or ``err(...)``.
Any OpenCV / value error it raises becomes a clear ERROR result instead of a crash.
"""
import copy
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from apex_vision.core import param_schema
from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus, VisionToolBase
from apex_vision.core.registry import register_tool

_DT = {"img": DataType.IMAGE, "val": DataType.VALUE, "pt": DataType.POINT, "line": DataType.LINE, "circle": DataType.CIRCLE,
       "str": DataType.STRING, "bool": DataType.BOOLEAN, "any": DataType.ANY, "region": DataType.REGION, "dict": DataType.DICT}


def port(name: str, kind: str, desc: str = "") -> Tuple[str, DataType, str]:
    return (name, _DT[kind], desc or name.replace("_", " "))


def img(name: str = "Image", desc: str = "") -> Tuple[str, DataType, str]:
    return port(name, "img", desc)


def val(name: str, desc: str = "") -> Tuple[str, DataType, str]:
    return port(name, "val", desc)


def ok(message: str = "", overlays: Optional[list] = None, **outputs) -> ToolExecutionResult:
    return ToolExecutionResult(status=ToolStatus.OK, message=message, outputs=outputs, overlays=overlays or [])


def ng(message: str = "", overlays: Optional[list] = None, **outputs) -> ToolExecutionResult:
    return ToolExecutionResult(status=ToolStatus.NG, message=message, outputs=outputs, overlays=overlays or [])


def err(message: str, **outputs) -> ToolExecutionResult:
    return ToolExecutionResult(status=ToolStatus.ERROR, message=message, outputs=outputs)


def define(name: str, category: str, description: str, inputs: Sequence = (), outputs: Sequence = (),
           params: Optional[Dict[str, Any]] = None, schema: Optional[Dict[str, Dict[str, Any]]] = None, hidden: bool = False):
    """Register a module built from a declaration and a function."""
    params = params or {}

    def decorate(fn: Callable[[VisionToolBase, Dict[str, Any]], ToolExecutionResult]):
        def _init_ports(self):
            for n, dt, d in inputs:
                self.inputs[n] = ToolPort(n, dt, d)
            for n, dt, d in outputs:
                self.outputs[n] = ToolPort(n, dt, d)

        def _init_parameters(self):
            self.parameters = copy.deepcopy(params)

        def execute(self, context):
            try:
                result = fn(self, context)
            except (cv2.error, ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, OverflowError, np.linalg.LinAlgError) as exc:
                return err(f"{name}: {str(exc).strip().splitlines()[0][:200] if str(exc).strip() else exc.__class__.__name__}")
            return result

        cls = type(fn.__name__, (VisionToolBase,), {
            "category": category, "tool_name": name, "description": description, "toolbox_hidden": hidden,
            "_init_ports": _init_ports, "_init_parameters": _init_parameters, "execute": execute,
            "__module__": fn.__module__, "__doc__": description,
        })
        register_tool(cls)
        if schema:
            param_schema.SCHEMA[name] = schema
        return cls
    return decorate


# ---- shared helpers ----------------------------------------------------------------------------------------------------------
def as_bgr(a: np.ndarray) -> np.ndarray:
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    if a.ndim == 2:
        return cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
    if a.shape[2] == 4:
        return cv2.cvtColor(a, cv2.COLOR_BGRA2BGR)
    if a.shape[2] == 1:
        return cv2.cvtColor(a[:, :, 0], cv2.COLOR_GRAY2BGR)
    return a


def as_gray(a: np.ndarray) -> np.ndarray:
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    if a.ndim == 2:
        return a
    if a.shape[2] == 4:
        return cv2.cvtColor(a, cv2.COLOR_BGRA2GRAY)
    if a.shape[2] == 1:
        return a[:, :, 0]
    return cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)


def get_image(ctx: Dict[str, Any], port_name: str = "Image") -> Optional[np.ndarray]:
    a = ctx.get(port_name)
    if isinstance(a, np.ndarray) and a.size and a.ndim >= 2 and min(a.shape[:2]) >= 2:
        return a
    return None


def like_input(src: np.ndarray, out_gray_or_bgr: np.ndarray) -> np.ndarray:
    """Return ``out`` as 3-channel if the input was colour, else single channel (keeps a grey image grey)."""
    if src.ndim == 2 or (src.ndim == 3 and src.shape[2] == 1):
        return as_gray(out_gray_or_bgr)
    return as_bgr(out_gray_or_bgr)


def point(v: Any) -> Optional[Tuple[float, float]]:
    return VisionToolBase.as_point(v)


def line(v: Any) -> Optional[Tuple[float, float, float, float]]:
    return VisionToolBase.as_line(v)


def circle(v: Any) -> Optional[Tuple[float, float, float]]:
    if isinstance(v, dict) and all(k in v for k in ("cx", "cy", "r")):
        return float(v["cx"]), float(v["cy"]), float(v["r"])
    if isinstance(v, (list, tuple, np.ndarray)) and len(v) >= 3:
        return float(v[0]), float(v[1]), float(v[2])
    return None


def line_dict(x1, y1, x2, y2) -> Dict[str, float]:
    return {"x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2), "length": float(np.hypot(x2 - x1, y2 - y1))}


def no_image(name: str = "") -> ToolExecutionResult:
    return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")


def pad(img_: np.ndarray, n: int) -> np.ndarray:
    return cv2.copyMakeBorder(img_, n, n, n, n, cv2.BORDER_REPLICATE)
