"""
Core data structures for the Vision Master Clone.
Provides Tool base class, Execution Context, Status, and Pin definitions.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
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

    def _init_parameters(self):
        """Define parameter schema and default values."""

    def get_param_defs(self) -> Dict[str, Any]:
        """Returns typed parameter schema definitions if defined."""
        return getattr(self, "param_definitions", {}) or {}

    #: Largest magnitude a numeric parameter may hold.  Python integers are unbounded,
    #: so a crafted project file could set `caliper_count` to 10**18 and the tool would
    #: then try to allocate an array of that many samples (a MemoryError, i.e. a
    #: denial of service from a data file).  No real inspection parameter -
    #: coordinates, gains, counts, timings - approaches 1e12, so anything beyond it is
    #: treated as invalid input and the current value is kept.
    MAX_PARAM_MAGNITUDE = 1e12

    def _coerce_param(self, key: str, value: Any) -> Any:
        """Make ``value`` compatible with the parameter's declared type.

        A parameter's type is fixed by the default its `_init_parameters` supplies.  A
        value of any other type can only arrive from outside the type-aware property
        editor - a hand-edited or older project file, a plugin, or scripted use - and
        every tool then converts it with a bare `int()`/`float()` at the point of use.
        Coercing here keeps that invariant, so a bad stored value degrades to the
        default instead of raising out of the tool mid-inspection.

        Only scalars are coerced; lists, dicts and tuples are passed through because
        several tools legitimately store structured values there.
        """
        current = self.parameters.get(key)
        # A parameter that is already absent/None carries no type information, so the
        # value is stored as given rather than coerced against a missing default.
        if current is None:
            return value
        if value is None:
            # Clearing a parameter keeps its typed default so an accidental blank in a
            # project file cannot turn a numeric knob into None.
            return current
        if isinstance(current, bool):
            if isinstance(value, str):
                text = value.strip().lower()
                if text in ("true", "1", "yes", "on"):
                    return True
                if text in ("false", "0", "no", "off"):
                    return False
                return current
            if isinstance(value, (int, float)):
                return bool(value)
            return current
        if isinstance(current, int) and not isinstance(current, bool):
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value if abs(value) <= self.MAX_PARAM_MAGNITUDE else current
            if isinstance(value, float):
                # `int(inf)` raises OverflowError and `int(nan)` raises ValueError, so
                # both are screened rather than caught.
                if not np.isfinite(value) or abs(value) > self.MAX_PARAM_MAGNITUDE:
                    return current
                return int(value)
            if isinstance(value, str):
                # "1e999" parses to infinity and then overflows the int conversion.
                try:
                    parsed = float(value)
                except (TypeError, ValueError, OverflowError):
                    return current
                if not np.isfinite(parsed) or abs(parsed) > self.MAX_PARAM_MAGNITUDE:
                    return current
                try:
                    return int(parsed)
                except (OverflowError, ValueError):
                    return current
            return current
        if isinstance(current, float):
            if isinstance(value, bool):
                return float(value)
            if isinstance(value, (int, float)):
                if not np.isfinite(value) or abs(value) > self.MAX_PARAM_MAGNITUDE:
                    return current
                return float(value)
            if isinstance(value, str):
                try:
                    parsed = float(value)
                except (TypeError, ValueError, OverflowError):
                    return current
                if not np.isfinite(parsed) or abs(parsed) > self.MAX_PARAM_MAGNITUDE:
                    return current
                return parsed
            return current
        if isinstance(current, str):
            if isinstance(value, (int, float, bool)):
                return str(value)
            if isinstance(value, str):
                return value
            return current
        # Structured parameters (ROIs, point lists, dictionaries) carry geometry, so
        # their *shape* is validated rather than their scalar type: a string or a
        # scalar stored here reaches code that unpacks it (`x, y, w, h = roi`) and
        # raised "not enough values to unpack".  A value of the wrong shape is
        # rejected in favour of the current one.
        if isinstance(current, (list, tuple)):
            if not isinstance(value, (list, tuple)):
                return current
            if current and all(isinstance(c, (list, tuple)) for c in current):
                # a list of points / pairs: any number of entries, each the same shape as the current ones
                width = len(current[0])
                if not all(isinstance(v, (list, tuple)) and len(v) == width for v in value):
                    return current
            elif current and len(value) != len(current):
                return current
            return type(current)(value) if isinstance(current, tuple) else list(value)
        if isinstance(current, dict):
            if not isinstance(value, dict):
                return current
            return dict(value)
        return value

    def set_param(self, key: str, value: Any):
        if key in self.parameters:
            self.parameters[key] = self._coerce_param(key, value)

    def get_param(self, key: str, default: Any = None) -> Any:
        return self.parameters.get(key, default)

    def get_bounded_param(self, key: str, default: float = 0.0,
                          minimum: Optional[float] = None,
                          maximum: Optional[float] = None,
                          integer: bool = False) -> Any:
        """Read a numeric parameter clamped to a usable range.

        `_coerce_param` guarantees the *type*, but a value can still be outside the
        range the algorithm tolerates - a negative buffer capacity fails
        `deque(maxlen=...)`, and a zero kernel size asserts in OpenCV.  Tools with such
        a constraint read through this helper so the constraint is stated once, in the
        place that depends on it.
        """
        value = self.as_float(self.get_param(key, default), float(default))
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return int(round(value)) if integer else value

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
        # Route every stored value through the same type coercion as `set_param`, so a
        # project file written by an older build (or edited by hand) cannot put a
        # wrong-typed value into a parameter and crash the tool at inspection time.
        for key, value in (data.get("parameters") or {}).items():
            if key in self.parameters:
                self.parameters[key] = self._coerce_param(key, value)
            else:
                # An unknown key is kept: plugins may read their own extra keys, and
                # dropping it would silently lose data on a save/load round trip.
                self.parameters[key] = value

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

    # ------------------------------------------------------------------
    # Input coercion helpers
    # ------------------------------------------------------------------
    # Region and geometry ports are fed either by an upstream module or by a
    # technician dragging handles on the canvas, so a downstream tool must treat
    # every value as hostile.  These helpers convert, validate and report rather
    # than unpacking and raising, which would surface to the operator as a bare
    # "Exception: ..." with no diagnosis.
    @staticmethod
    def as_float(value: Any, default: float = 0.0) -> float:
        """Coerce to a finite float, falling back to ``default``.

        Rejects ``None``, non-numeric strings, sequences, ``NaN`` and ``inf`` - all
        of which a numeric port can legitimately receive, and each of which would
        otherwise raise deep inside the algorithm.
        """
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        if not np.isfinite(result):
            return default
        return result

    @classmethod
    def as_point(cls, value: Any) -> Optional[Tuple[float, float]]:
        """Coerce a point port to ``(x, y)``, or ``None`` when malformed.

        Accepts a 2-sequence or a mapping using any of the documented key pairs.
        """
        if isinstance(value, dict):
            for xk, yk in (("cx", "cy"), ("x", "y"), ("x1", "y1")):
                if xk in value and yk in value:
                    return (cls.as_float(value[xk]), cls.as_float(value[yk]))
            return None
        if isinstance(value, (list, tuple, np.ndarray)) and len(value) >= 2:
            return (cls.as_float(value[0]), cls.as_float(value[1]))
        return None

    @classmethod
    def as_line(cls, value: Any) -> Optional[Tuple[float, float, float, float]]:
        """Coerce a line port to ``(x1, y1, x2, y2)``, or ``None`` when malformed.

        Accepts the documented ``{x1, y1, x2, y2}`` mapping, a 4-sequence, or the
        ``[(x1, y1), (x2, y2)]`` pair-of-endpoints form.  A partial mapping or a
        3-element sequence is reported as malformed instead of raising.
        """
        if isinstance(value, dict):
            try:
                return (cls.as_float(value["x1"]), cls.as_float(value["y1"]),
                        cls.as_float(value["x2"]), cls.as_float(value["y2"]))
            except KeyError:
                return None
        if isinstance(value, (list, tuple, np.ndarray)):
            if len(value) == 4 and not isinstance(value[0], (list, tuple, np.ndarray, dict)):
                return (cls.as_float(value[0]), cls.as_float(value[1]),
                        cls.as_float(value[2]), cls.as_float(value[3]))
            if len(value) == 2:
                a = cls.as_point(value[0])
                b = cls.as_point(value[1])
                if a is not None and b is not None:
                    return (a[0], a[1], b[0], b[1])
            return None
        return None

    @classmethod
    def as_point_list(cls, value: Any, minimum: int = 1) -> Optional[np.ndarray]:
        """Coerce a point-set port to an ``(N, 2)`` float array, or ``None``.

        A ragged or wrongly-shaped list yields ``None`` rather than a silently
        mis-shaped array whose columns are then read as coordinates.
        """
        if value is None or isinstance(value, (str, bytes)):
            return None
        try:
            arr = np.asarray(value, dtype=np.float64)
        except (TypeError, ValueError):
            return None
        if arr.ndim != 2 or arr.shape[0] < minimum or arr.shape[1] != 2:
            return None
        if not np.all(np.isfinite(arr)):
            return None
        return arr


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


