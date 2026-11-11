"""
Tool Registry and Factory for Apex Vision Studio.
Allows dynamic discovery, instancing, and registration of tools.
"""
import uuid
from typing import Dict, Type, List
from apex_vision.core.base_tool import VisionToolBase

_TOOL_REGISTRY: Dict[str, Type[VisionToolBase]] = {}
_CATEGORIES: Dict[str, List[str]] = {}


def new_instance_id(prefix: str = "node") -> str:
    """A module instance id that cannot collide with an existing one."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def register_tool(cls: Type[VisionToolBase]):
    _TOOL_REGISTRY[cls.tool_name] = cls
    if getattr(cls, "toolbox_hidden", False):
        return cls              # loadable (saved flows, evaluation) but not offered in the toolbox
    cat = getattr(cls, 'category', 'General')
    if cat not in _CATEGORIES:
        _CATEGORIES[cat] = []
    if cls.tool_name not in _CATEGORIES[cat]:
        _CATEGORIES[cat].append(cls.tool_name)
    return cls


def get_tool_class(tool_name: str) -> Type[VisionToolBase]:
    if tool_name not in _TOOL_REGISTRY:
        raise KeyError(f"Tool '{tool_name}' not registered in Apex Vision registry.")
    return _TOOL_REGISTRY[tool_name]


def create_tool_instance(
    tool_name: str,
    instance_id: str,
    name: str = None,
    allow_placeholder: bool = False
) -> VisionToolBase:
    if tool_name not in _TOOL_REGISTRY:
        if allow_placeholder:
            from apex_vision.core.base_tool import MissingPluginPlaceholderTool
            return MissingPluginPlaceholderTool(instance_id=instance_id, name=name, missing_tool_name=tool_name)
        raise KeyError(f"Tool '{tool_name}' not registered in Apex Vision registry.")
    cls = _TOOL_REGISTRY[tool_name]
    return cls(instance_id=instance_id, name=name)


def unregister_tool(tool_name: str) -> bool:
    """Deregister a tool by name from registry and category list."""
    if tool_name not in _TOOL_REGISTRY:
        return False
    cls = _TOOL_REGISTRY.pop(tool_name)
    cat = getattr(cls, 'category', 'General')
    if cat in _CATEGORIES and tool_name in _CATEGORIES[cat]:
        _CATEGORIES[cat].remove(tool_name)
        if not _CATEGORIES[cat]:
            del _CATEGORIES[cat]
    return True


#: toolbox order: the order a flow is built in (acquire, clean up, find, measure, decide, report)
CATEGORY_ORDER = ["Acquisition", "Image Processing", "Color Processing", "Location", "Measurement", "Image Generation", "Calibration", "Calculation",
                  "Recognition", "Defect Detection", "Deep Learning", "Division and Combination", "Logic Tools", "Communication"]

#: inside a category, related tools sit together (a tool not listed follows, in the order it was registered)
TOOL_ORDER: Dict[str, List[str]] = {
    "Acquisition": ["Image Source", "Multi-image Acquisition", "Image Buffer", "Light Source", "Image Output"],
    "Image Processing": ["Image Crop", "Image Transform", "Color Convert", "Brightness Contrast", "Image Enhancement", "Image Filter", "Image Binarization",
                         "Image Morphology", "Edge Detection", "Image Calculate", "Image Combination", "Image Normalization", "Image Correction",
                         "Shade Correction", "Distortion Correction", "Affine Transformation", "Inverse Affine Transformation", "Ring Expansion",
                         "Image Fixture", "Image Stitch", "Multiple Images Fusion", "Frame Mean", "Copy Fill"],
    "Location": ["Template Match", "Mark Location", "Position Correction", "BLOB Analysis", "BLOB Label Analysis", "Target Tracking", "Path Extraction",
                 "Line Search", "Edge Search", "Caliper", "Peak Search", "Multi-line Search", "Line Group Search", "Parallel Lines Search", "Rect Search",
                 "Quadrilateral Search", "Circle Search", "Matrix Circle Search", "Ellipse Search", "Hough Detect",
                 "Edge Intersection", "Find Angle Bisector", "Find Median Line", "Find Vertical Line", "Calculate Parallel Lines"],
    "Measurement": ["Intensity Measure", "Pixel Count", "Histogram", "Focus Measure", "P2P Measure", "P2L Measure", "P2C Measure", "L2L Measure",
                    "L2C Measure", "C2C Measure", "Angle Measure", "Line Intersection", "Edge Distance"],
    "Calibration": ["N-Point Calibration", "CalibBoard Calibration", "N-Image Calibration", "Rotation Calibration", "Translation and Rotation Calibration",
                    "Camera Mapping", "Mapping Calibration", "Lens Distortion Calibration", "Load Calibration"],
    "Defect Detection": ["Defect Detection", "Defect Contrast", "Surface Defect Filter", "OCV"],
    "Deep Learning": ["Object Detection", "DL Classify", "DL Segment", "DL Anomaly", "DL Instance Segment", "DL Image Defect Prediction",
                      "Classification Registration", "DL Image Retrieval"],
    "Logic Tools": ["Trigger", "Condition Branch", "Branch", "Branch String", "If Module", "Condition Detection", "String Comparison", "Variable Calculation",
                    "Data Set", "Point Set", "Graphic Collection", "Format Module", "Save Text", "Time Consuming", "Group", "Script"],
    "Communication": ["Send Data", "Receive Data", "TCP Send", "UDP Send", "Serial Send", "Modbus TCP Write", "Protocol Parsing", "Protocol Assembly",
                      "Camera IO", "Data Log"],
}


def _ordered(items: List[str], order: List[str]) -> List[str]:
    rank = {name: i for i, name in enumerate(order)}
    return sorted(items, key=lambda n: rank.get(n, len(order)))          # stable: unlisted tools keep their registration order


def list_categories() -> Dict[str, List[str]]:
    """Categories in toolbox order (plugin categories last), each with its tools grouped by purpose."""
    names = _ordered(list(_CATEGORIES), CATEGORY_ORDER)
    return {c: _ordered(_CATEGORIES[c], TOOL_ORDER.get(c, [])) for c in names}


def list_all_tools() -> List[str]:
    return list(_TOOL_REGISTRY.keys())
