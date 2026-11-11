"""How each module parameter is edited: checkbox, drop-down, number with limits, region, path ... or free text.

The tools only know a parameter's default value; this table says what kind of value it is, so the property
editors (QML and widget), the AI assistant and the validators all agree and the user never has to type a value
that has a fixed set of choices.  Parameters not listed here are described from their default value (bool ->
checkbox, int / float -> number, ``[x, y, w, h]`` named ``*roi`` -> region, ``[x, y]`` -> point ...).

kinds: bool | int | float | enum | combo (drop-down that also accepts typed text) | text | path | dir |
       rect | point | line | points | rgb | code | device | flow
"""
import math
from typing import Any, Dict, List, Optional

POLARITY = ["Any", "Dark to light", "Light to dark"]
EDGE_TYPE = ["Strongest Edge", "First Edge", "Last Edge"]
IMAGE_FILES = "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*)"


def enum(*choices: str) -> Dict[str, Any]:
    return {"kind": "enum", "choices": list(choices)}


def combo(*choices: str) -> Dict[str, Any]:
    return {"kind": "combo", "choices": list(choices)}


def num(lo: float, hi: float, step: float = 1, unit: str = "", decimals: Optional[int] = None) -> Dict[str, Any]:
    d: Dict[str, Any] = {"min": lo, "max": hi, "step": step}
    if unit:
        d["unit"] = unit
    if decimals is not None:
        d["decimals"] = decimals
    return d


def path(filters: str = "All files (*)") -> Dict[str, Any]:
    return {"kind": "path", "filters": filters}


_PCB_VARIANTS: List[str] = []
try:                                                     # the detector's own list of operating points
    from apex_vision.samples.pcb_defect_tool import DETECTOR_VARIANTS
    _PCB_VARIANTS = list(DETECTOR_VARIANTS)
except Exception:                                        # pragma: no cover
    _PCB_VARIANTS = ["reference"]

from apex_vision.core import dl_engine as _dl

_DL_COMMON: Dict[str, Dict[str, Any]] = {          # the settings every deep-learning module shares
    "model_path": path("ONNX model (*.onnx);;All files (*)"), "backend": enum(*_dl.BACKENDS), "device": enum("cpu", "cuda"),
    "input_width": num(0, 8192, unit="px"), "input_height": num(0, 8192, unit="px"),
    "resize": enum("Auto", *_dl.RESIZE_MODES), "normalize": enum("Auto", *_dl.NORMALIZE_MODES), "roi": {"kind": "rect"},
}

SCHEMA: Dict[str, Dict[str, Dict[str, Any]]] = {
    "2D BCR Recognition": {"mode": enum("QR Code", "DataMatrix"), "polarity": enum("Any", "Dark on White", "White on Dark")},
    "BCR Recognition": {"window_size": num(1, 64), "symbology": enum("Auto", "Code128", "EAN13", "Code39"),
                        "expected_length": num(0, 128)},
    "BLOB Analysis": {"threshold": num(0, 255), "min_area": num(0, 100_000_000, unit="px"), "max_area": num(0, 100_000_000, unit="px"),
                      "min_circularity": num(0, 1, 0.05, decimals=2)},
    "Branch": {"mode": enum("Index by Value", "Index by Bit"), "target_value": num(-1_000_000, 1_000_000), "bit_index": num(0, 31),
               "target_branches": {"kind": "text", "hint": "comma-separated module ids"}},
    "Branch String": {"match_mode": enum("Exact", "Contains", "Prefix")},
    "Caliper": {"line_p1": {"kind": "point"}, "line_p2": {"kind": "point"}, "edge_threshold": num(0, 255, 1, decimals=1),
                "polarity": enum(*POLARITY), "caliper_mode": enum("Single Edge", "Edge Pair")},
    "Camera IO": {"pulse_duration_ms": num(1, 10_000, unit="ms")},
    "Circle Search": {"center_x": num(0, 100_000, unit="px"), "center_y": num(0, 100_000, unit="px"), "min_radius": num(1, 5000, unit="px"),
                      "max_radius": num(1, 5000, unit="px"), "caliper_rays": num(8, 360), "edge_polarity": enum(*POLARITY),
                      "edge_type": enum(*EDGE_TYPE), "edge_threshold": num(0, 255, 1, decimals=1)},
    "Circle/Line Fit": {"fit_type": enum("Circle Fit", "Ellipse Fit", "Line Fit"), "default_points": {"kind": "points"}},
    "Color Extraction": {"preset_color": enum("Green", "Red", "Blue", "Yellow", "Custom"), "h_min": num(0, 179), "h_max": num(0, 179),
                         "s_min": num(0, 255), "s_max": num(0, 255), "v_min": num(0, 255), "v_max": num(0, 255),
                         "min_ratio": num(0, 100, 0.5, "%", 1), "max_ratio": num(0, 100, 0.5, "%", 1),
                         "mask_output": enum("Color Keep", "Binary Mask", "Inverse")},
    "Color Measurement": {"roi": {"kind": "rect"}, "target_rgb": {"kind": "rgb"}, "max_color_distance": num(0, 442, 1, decimals=1)},
    "Condition Branch": {"operator": enum(">=", "<=", ">", "<", "==", "!=", "Between"), "threshold_low": {"decimals": 3},
                         "threshold_high": {"decimals": 3}},
    "Defect Detection": {"roi": {"kind": "rect"}, "method": enum("Classical (contrast)", "Deep learning (ONNX model)"),
                         "model_path": path("ONNX model (*.onnx);;All files (*)"), "model_task": enum("Segmentation", "Anomaly", "Detection"),
                         "dl_threshold": num(0, 1000, 0.05, decimals=3), "defect_type": combo("Dark / Scratch", "Bright / Burr", "Dirt / Stain", "Crack / Break"),
                         "sensitivity": num(1, 255), "min_defect_area": num(0, 10_000_000, unit="px"), "max_defect_area": num(0, 10_000_000, unit="px")},
    "Edge Distance": {"start_pt": {"kind": "point"}, "end_pt": {"kind": "point"}, "min_distance": num(0, 100_000, 1, "px", 1),
                      "max_distance": num(0, 100_000, 1, "px", 1), "edge_threshold": num(0, 255, 1, decimals=1)},
    "Edge Search": {"start_pt": {"kind": "point"}, "end_pt": {"kind": "point"}, "edge_type": enum(*EDGE_TYPE), "polarity": enum(*POLARITY),
                    "edge_threshold": num(0, 255, 1, decimals=1)},
    "Geometry Generation": {"geom_type": enum("Datum Cross", "Reference Line", "Pitch Circle"), "center_x": num(0, 100_000, 1, "px", 1), "center_y": num(0, 100_000, 1, "px", 1), "radius": num(0, 100_000, 1, "px", 1),
                            "line_p1": {"kind": "point"}, "line_p2": {"kind": "point"}},
    "Histogram": {"roi": {"kind": "rect"}},
    "If Module": {"judge_method": enum("All", "Any"), "condition_type": enum("Float", "Integer")},
    "Image Binarization": {"method": enum("Otsu", "Adaptive", "Manual"), "threshold": num(0, 255), "adaptive_block_size": num(3, 99),
                           "adaptive_c": num(-50, 50)},
    "Image Buffer": {"buffer_capacity": num(1, 1000), "buffer_condition": enum("All Images", "NG Only")},
    "Image Filter": {"filter_type": enum("Gaussian", "Box", "Median", "Sharpen", "Unsharp Mask", "Bilateral"), "kernel_size": num(1, 31), "sigma": num(0, 50, 0.1, decimals=2)},
    "Image Morphology": {"operation": enum("Open", "Close", "Dilate", "Erode", "Gradient", "Top Hat", "Black Hat"), "kernel_size": num(1, 51), "iterations": num(1, 50)},
    "Image Output": {"save_directory": {"kind": "dir"}, "file_format": enum("PNG", "JPEG", "BMP"),
                     "save_mode": enum("Always Save", "Only on NG", "Only on OK"), "image_quality": num(1, 100, unit="%")},
    "Image Source": {"source_type": enum("Synthetic", "File", "Camera", "Industrial GigE", "Industrial USB3", "Hikrobot MVS", "IP Stream"),
                     "file_path": path(IMAGE_FILES), "pattern_type": enum("Part with Defects", "Metal Surface (demo)", "Calibration Grid", "Circles & Holes", "Barcode Sample"),
                     "color_mode": enum("BGR", "Grayscale"), "camera_device": {"kind": "device"}, "camera_index": num(0, 16),
                     "exposure_time_us": num(10, 10_000_000, 100, "us", 1), "gain": num(0, 48, 0.1, "x", 1),
                     "trigger_mode": enum("Continuous", "Software Trigger", "Hardware Trigger (Line0)", "Hardware Trigger (Line1)"),
                     "mvs_config_file": path("Camera config (*.mfs);;All files (*)"), "mvs_trigger_source": enum("Software", "Line0", "Line1")},
    "Intensity Measure": {"roi": {"kind": "rect"}, "min_mean": num(0, 255, 1, decimals=1), "max_mean": num(0, 255, 1, decimals=1)},
    "L2L Measure": {"scale_factor": {"decimals": 4, "min": 0.000001, "max": 1_000_000}, "min_distance": num(0, 1e9, 1, decimals=2),
                    "max_distance": num(0, 1e9, 1, decimals=2), "default_l1": {"kind": "line"}, "default_l2": {"kind": "line"}},
    "Lens Distortion Calibration": {"mode": enum("Profile File", "Manual Coefficients", "Live Chessboard"),
                                    "calibration_file": path("Calibration profile (*.json *.npz *.yml *.yaml);;All files (*)"),
                                    "alpha": num(0, 1, 0.05, decimals=2), "manual_fx": num(1, 100_000, 1, decimals=2),
                                    "manual_fy": num(1, 100_000, 1, decimals=2), "manual_cx": num(0, 100_000, 1, decimals=2),
                                    "manual_cy": num(0, 100_000, 1, decimals=2)},
    "Line Search": {"start_pt": {"kind": "point"}, "end_pt": {"kind": "point"}, "caliper_rake_width": num(1, 1000, unit="px"),
                    "caliper_count": num(3, 200), "edge_polarity": enum(*POLARITY), "edge_type": enum(*EDGE_TYPE),
                    "edge_threshold": num(0, 255, 1, decimals=1)},
    "Linear Edge Defect": {"start_pt": {"kind": "point"}, "end_pt": {"kind": "point"}, "search_width": num(2, 200, unit="px"),
                           "edge_threshold": num(0, 255), "max_allowed_deviation": num(0, 10_000, 0.5, "px", 1)},
    "N-Point Calibration": {"calibration_mode": enum("9-Point Affine", "4-Point Homography", "2-Point Scaling"),
                            "pixel_points": {"kind": "points"}, "world_points": {"kind": "points"}},
    "OCR Recognition": {"roi": {"kind": "rect"}, "char_polarity": enum("White on Dark", "Dark on White"), "min_confidence": num(0, 100, 1, "%", 1),
                        "expected_pattern": {"kind": "text", "hint": "* matches any characters, e.g. SN-*"}},
    "Object Detection": {"model_path": path("YOLO models (*.onnx *.pt);;All files (*)"), "confidence": num(0, 1, 0.05, decimals=2),
                         "iou": num(0, 1, 0.05, decimals=2), "classes": {"kind": "text", "hint": "all, or comma-separated class names"},
                         "device": enum("cpu", "cuda", "auto"), "max_detections": num(1, 1000)},
    "P2P Measure": {"scale_factor": {"decimals": 4, "min": 0.000001, "max": 1_000_000}, "default_p1": {"kind": "point"},
                    "default_p2": {"kind": "point"}, "min_distance": num(0, 1e9, 1, decimals=2), "max_distance": num(0, 1e9, 1, decimals=2)},
    "PCB Board Layout": {"board_seed": num(0, 2_147_483_647), "image_width": num(64, 8192, unit="px"), "image_height": num(64, 8192, unit="px")},
    "PCB Defect Detection": {"variant": enum(*_PCB_VARIANTS), "confidence_threshold": num(0, 1, 0.05, decimals=2), "min_area": num(0, 1_000_000, unit="px"),
                             "dark_floor": num(0, 255), "max_detections": num(1, 1000)},
    "Pixel Count": {"roi": {"kind": "rect"}, "low_threshold": num(0, 255), "high_threshold": num(0, 255), "min_count": num(0, 1_000_000_000),
                    "max_count": num(0, 1_000_000_000)},
    "Position Correction": {"fiducial_angle": num(-360, 360, 0.5, "deg", 2)},
    "Script": {"code": {"kind": "code"}, "timeout_ms": num(100, 600_000, 100, "ms")},
    "TCP Send": {"mode": enum("Simulation (Loopback Log)", "TCP Client"), "server_ip": {"kind": "text", "hint": "IP address or host name"},
                 "server_port": num(1, 65535), "format": enum("CSV", "JSON", "Plain Text"), "connect_timeout_ms": num(50, 60_000, unit="ms")},
    "Template Match": {"min_score": num(0, 1, 0.05, decimals=2), "template_roi": {"kind": "rect"}, "start_angle": num(-180, 180, 1, "deg", 1),
                       "end_angle": num(-180, 180, 1, "deg", 1), "angle_step": num(0.1, 90, 0.5, "deg", 1), "max_matches": num(1, 100)},
    "Trigger": {"target_flow": {"kind": "flow"}},
    # ---- modules added after the first release
    # ---- deep learning
    "DL Classify": {**_DL_COMMON, "top_k": num(1, 20), "min_confidence": num(0, 1, 0.05, decimals=2)},
    "DL Segment": {**_DL_COMMON, "background_class": num(0, 255), "threshold": num(0, 1, 0.05, decimals=2),
                   "min_area": num(1, 100_000_000, unit="px"), "max_defect_count": num(0, 100_000),
                   "max_defect_ratio": num(0, 100, 0.1, "%", 2)},
    "DL Anomaly": {**{k: v for k, v in _DL_COMMON.items() if k != "labels"}, "output_type": enum("Auto (from the model)", "Anomaly map", "Reconstruction (autoencoder)"),
                   "map_threshold": num(0, 1_000_000, 0.01, decimals=3), "smoothing": num(0, 50, 0.5, decimals=1),
                   "min_area": num(1, 100_000_000, unit="px"), "max_defect_count": num(0, 100_000)},
    "Image Crop": {"roi": {"kind": "rect"}},
    "Image Transform": {"operation": enum("Resize", "Rotate", "Rotate 90 CW", "Rotate 90 CCW", "Rotate 180", "Flip Horizontal", "Flip Vertical"),
                        "scale": num(0.05, 16, 0.05, "x", 2), "angle": num(-360, 360, 1, "deg", 1)},
    "Color Convert": {"mode": enum("Grayscale", "Red channel", "Green channel", "Blue channel", "Hue", "Saturation", "Value", "HSV", "Lab")},
    "Brightness Contrast": {"mode": enum("Manual", "Auto Brighten", "Gamma", "Equalize", "CLAHE"), "brightness": num(-255, 255),
                            "contrast": num(0.1, 5, 0.1, "x", 2), "gamma": num(0.1, 5, 0.05, decimals=2),
                            "target_mean": num(1, 254), "clip_limit": num(0.5, 40, 0.5, decimals=1)},
    "Image Calculate": {"operation": enum("Absolute Difference", "Subtract (A - B)", "Add", "Multiply", "Average", "Maximum", "Minimum",
                                          "Bitwise AND", "Bitwise OR", "Bitwise XOR")},
    "Edge Detection": {"method": enum("Canny", "Sobel", "Scharr", "Laplacian"), "low_threshold": num(0, 1000),
                       "high_threshold": num(0, 1000), "blur_size": num(1, 31)},
    "Focus Measure": {"roi": {"kind": "rect"}, "min_sharpness": num(0, 1e9, 1, decimals=1)},
    "P2L Measure": {"scale_factor": {"decimals": 4, "min": 0.000001, "max": 1_000_000}, "default_point": {"kind": "point"},
                    "default_line": {"kind": "line"}, "min_distance": num(0, 1e9, 1, decimals=2), "max_distance": num(0, 1e9, 1, decimals=2)},
    "Angle Measure": {"default_a": {"kind": "point"}, "default_vertex": {"kind": "point"}, "default_c": {"kind": "point"},
                      "min_angle": num(0, 180, 1, "deg", 1), "max_angle": num(0, 180, 1, "deg", 1)},
    "Line Intersection": {"default_l1": {"kind": "line"}, "default_l2": {"kind": "line"}},
    "Hough Detect": {"mode": enum("Circles", "Lines"), "roi": {"kind": "rect"}, "min_radius": num(0, 5000, unit="px"),
                     "max_radius": num(1, 5000, unit="px"), "min_distance": num(1, 5000, unit="px"), "sensitivity": num(1, 200),
                     "line_threshold": num(1, 1000), "min_line_length": num(1, 10000, unit="px"), "max_line_gap": num(0, 1000, unit="px"),
                     "min_count": num(0, 1000)},
    "UDP Send": {"mode": enum("Simulation (Log Only)", "UDP"), "server_ip": {"kind": "text", "hint": "IP address or host name"},
                 "server_port": num(1, 65535), "format": enum("CSV", "JSON", "Plain Text")},
    "Serial Send": {"mode": enum("Simulation (Log Only)", "Serial Port"),
                    "port_name": combo("COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "COM10", "/dev/ttyUSB0", "/dev/ttyS0"),
                    "baud_rate": enum("1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"),
                    "parity": enum("None", "Even", "Odd"), "format": enum("CSV", "JSON", "Plain Text")},
    "Modbus TCP Write": {"mode": enum("Simulation (Log Only)", "Modbus TCP"), "server_ip": {"kind": "text", "hint": "IP address or host name"},
                         "server_port": num(1, 65535), "unit_id": num(0, 255), "function": enum("Write Single Register", "Write Multiple Registers", "Write Single Coil"),
                         "start_address": num(0, 65535), "value_scale": num(0.0001, 1_000_000, 1, decimals=4),
                         "connect_timeout_ms": num(50, 60_000, unit="ms")},
    "Data Log": {"file_path": path("CSV file (*.csv);;All files (*)")},
    "Variable Calculation": {"operation": enum("+", "-", "*", "/", "Scale"), "scale_factor": {"decimals": 4}},
}

_PATH_WORDS = ("path", "file")
_DIR_WORDS = ("directory", "folder", "dir")


def humanize(key: str) -> str:
    words = key.replace("_", " ").strip().split()
    out = [w.upper() if w.lower() in ("roi", "ip", "fx", "fy", "cx", "cy", "rgb", "iou", "p1", "p2", "l1", "l2", "pt", "us", "ms", "tcp") else w for w in words]
    return " ".join(out).capitalize() if out else key


def _numbers(value: Any, n: int) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == n and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def infer_kind(key: str, default: Any) -> Dict[str, Any]:
    """The editor kind implied by a default value alone."""
    if isinstance(default, bool):
        return {"kind": "bool"}
    if isinstance(default, int):
        return {"kind": "int"}
    if isinstance(default, float):
        return {"kind": "float"}
    if isinstance(default, str):
        low = key.lower()
        if any(low.endswith(w) for w in _DIR_WORDS):
            return {"kind": "dir"}
        if any(low.endswith(w) for w in _PATH_WORDS):
            return {"kind": "path", "filters": "All files (*)"}
        return {"kind": "text"}
    if isinstance(default, (list, tuple)):
        if _numbers(default, 4) and "roi" in key.lower():
            return {"kind": "rect"}
        if _numbers(default, 4):
            return {"kind": "line"}
        if _numbers(default, 2):
            return {"kind": "point"}
        if _numbers(default, 3) and "rgb" in key.lower():
            return {"kind": "rgb"}
        if default and all(_numbers(p, 2) for p in default):
            return {"kind": "points"}
    return {"kind": "json"}


#: parameters that hold a module's learned or embedded data (a model file's bytes, trained statistics): kept and saved, never shown for editing
HIDDEN_KEYS = {"model_data", "model", "embedded_model", "gallery"}


def spec_for(tool_name: str, key: str, default: Any) -> Dict[str, Any]:
    """Complete editor description for one parameter: kind plus choices / limits / unit / label."""
    if key in HIDDEN_KEYS:
        return {"kind": "hidden", "label": humanize(key), "key": key}
    spec = infer_kind(key, default)
    extra = SCHEMA.get(tool_name, {}).get(key, {})
    spec.update(extra)
    if "choices" in spec and "kind" not in extra:
        spec["kind"] = "enum"
    if "min" in spec or "max" in spec:
        if spec["kind"] in ("int", "float") and isinstance(default, float) and spec["kind"] == "int":
            spec["kind"] = "float"
        spec.setdefault("min", -1e12)
        spec.setdefault("max", 1e12)
    if spec["kind"] == "float":
        spec.setdefault("step", 0.1)
        spec.setdefault("decimals", 2)
    if spec["kind"] == "int":
        spec.setdefault("step", 1)
        spec["decimals"] = 0
    spec["label"] = humanize(key)
    spec["key"] = key
    return spec


def choices_for(tool_name: str, key: str) -> Optional[List[str]]:
    """The fixed set of values of an enum parameter (None for combo, which also takes typed text)."""
    spec = SCHEMA.get(tool_name, {}).get(key)
    return list(spec["choices"]) if spec and spec.get("kind", "enum") == "enum" and "choices" in spec else None


def problem(tool_name: str, key: str, default: Any, value: Any) -> Optional[str]:
    """Why ``value`` is not acceptable for this parameter (None when it is)."""
    spec = spec_for(tool_name, key, default)
    kind = spec["kind"]
    if kind == "bool":
        return None if isinstance(value, bool) else "must be true or false"
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return "must be a number"
        if kind == "int" and float(value) != int(value):
            return "must be a whole number"
        if "min" in spec and float(value) < spec["min"]:
            return f"must be at least {spec['min']:g}"
        if "max" in spec and float(value) > spec["max"]:
            return f"must be at most {spec['max']:g}"
        return None
    if kind == "enum":
        return None if value in spec["choices"] else f"must be one of {spec['choices']}"
    if kind in ("text", "combo", "path", "dir", "code", "device", "flow"):
        return None if isinstance(value, str) else "must be text"
    expect = {"rect": 4, "line": 4, "point": 2, "rgb": 3}.get(kind)
    if expect:
        if not _numbers(value, expect):
            return f"must be {expect} numbers"
        if kind == "rgb" and not all(0 <= v <= 255 for v in value):
            return "each colour channel must be 0-255"
        return None
    if kind == "points":
        return None if isinstance(value, (list, tuple)) and all(_numbers(p, 2) for p in value) else "must be a list of [x, y] points"
    return None


def clamp(spec: Dict[str, Any], value: Any) -> Any:
    """Bring a number into the parameter's limits (and to a whole number for ints)."""
    if spec["kind"] not in ("int", "float") or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return value
    v = min(max(float(value), spec.get("min", -1e12)), spec.get("max", 1e12))
    return int(round(v)) if spec["kind"] == "int" else v


# ---- the fuller option lists of the VisionMaster guide; the older names stay so existing solutions still open
def _fuller_options() -> None:
    SCHEMA["Image Binarization"].update({
        "method": enum("Otsu", "Adaptive", "Manual", "Hard Threshold", "Mean", "Gaussian", "Auto"), "low_threshold": num(0, 255), "high_threshold": num(0, 255),
        "kernel_width": num(1, 255, unit="px"), "kernel_height": num(1, 255, unit="px"), "gaussian_sigma": num(0, 100, 0.1, decimals=2),
        "comparison": enum("Greater or Equal", "Less or Equal", "Equal", "Not Equal"), "threshold_offset": num(-255, 255, 1, decimals=1)})
    SCHEMA["Image Filter"].update({
        "filter_type": enum("Gaussian", "Box", "Median", "Sharpen", "Unsharp Mask", "Bilateral", "Mean", "Inverse", "Edge Extraction"),
        "edge_low": num(0, 2000), "edge_high": num(0, 2000)})
    SCHEMA["Image Morphology"].update({
        "operation": enum("Open", "Close", "Dilate", "Erode", "Gradient", "Top Hat", "Black Hat", "Dilation", "Erosion", "Opening", "Closing"),
        "element": enum("Rect", "Ellipse", "Cross"), "element_width": num(0, 255, unit="px"), "element_height": num(0, 255, unit="px")})
    SCHEMA["Image Transform"].update({
        "operation": enum("Resize", "Rotate", "Rotate 90 CW", "Rotate 90 CCW", "Rotate 180", "Flip Horizontal", "Flip Vertical", "Mirror and Rotate"),
        "mirror": enum("None", "Horizontal", "Vertical", "Diagonal")})
    SCHEMA["Color Convert"].update({
        "mode": enum("Grayscale", "Red channel", "Green channel", "Blue channel", "Hue", "Saturation", "Value", "HSV", "Lab", "Gray: Average", "Gray: Minimum",
                     "Gray: Maximum", "Gray: User-defined", "HSI Channel 1", "HSI Channel 2", "HSI Channel 3", "YUV Channel 1", "YUV Channel 2", "YUV Channel 3"),
        "coeff_r": num(-10, 10, 0.01, decimals=3), "coeff_g": num(-10, 10, 0.01, decimals=3), "coeff_b": num(-10, 10, 0.01, decimals=3)})
    SCHEMA["Image Calculate"].update({
        "operation": enum("Absolute Difference", "Subtract (A - B)", "Add", "Multiply", "Average", "Maximum", "Minimum", "Bitwise AND", "Bitwise OR", "Bitwise XOR",
                          "k1*A + k2*B + c", "k1*A + c", "A + c"),
        "image_weight1": num(0, 10, 0.1, decimals=2), "image_weight2": num(0, 10, 0.1, decimals=2), "calc_weight1": num(-10, 10, 0.1, decimals=2),
        "calc_weight2": num(-10, 10, 0.1, decimals=2), "image_offset": num(-255, 255, 1, decimals=1)})
    SCHEMA.setdefault("Focus Measure", {}).update({
        "assess_mode": enum("Laplacian Variance", "Auto Correlation", "Gradient Squared"), "noise_level": num(0, 255)})


    SCHEMA.setdefault("BLOB Analysis", {}).update({
        "roi": {"kind": "rect"},
        "threshold_mode": enum("Single Threshold", "Double Threshold", "Auto Threshold", "Soft Threshold (Fixed)", "Soft Threshold (Relative)", "None (already binary)"),
        "high_threshold": num(0, 255), "min_circularity": num(0, 1, 0.05, decimals=2), "max_circularity": num(0, 1, 0.05, decimals=2),
        "min_rectangularity": num(0, 1, 0.05, decimals=2), "max_rectangularity": num(0, 1, 0.05, decimals=2), "min_axis_ratio": num(0, 1, 0.05, decimals=2),
        "max_axis_ratio": num(0, 1, 0.05, decimals=2), "min_perimeter": num(0, 1e7, 1, "px"), "max_perimeter": num(0, 1e7, 1, "px"),
        "min_rect_width": num(0, 1e7, 1, "px"), "max_rect_width": num(0, 1e7, 1, "px"), "min_rect_height": num(0, 1e7, 1, "px"), "max_rect_height": num(0, 1e7, 1, "px"),
        "min_major_axis": num(0, 1e7, 1, "px"), "max_major_axis": num(0, 1e7, 1, "px"), "min_minor_axis": num(0, 1e7, 1, "px"), "max_minor_axis": num(0, 1e7, 1, "px"),
        "max_barycenter_offset": num(0, 1e7, 1, "px"), "min_hole_area": num(0, 1e7, 1, "px"), "max_blobs": num(1, 100000),
        "connectivity": enum("8-connected", "4-connected"),
        "sort_feature": enum("Area", "Perimeter", "Circularity", "Rectangularity", "Center X", "Center Y", "Box Angle", "Box Width", "Box Height", "Box Left", "Box Top",
                             "Second-order Center Distance", "Principal Axis Angle", "Axis Ratio"),
        "sort_type": enum("No Sorting", "Ascending", "Descending"), "contour_output": {"kind": "bool"}})


_fuller_options()


# ---- which options apply: a setting that does not belong to the current choice is shown blank and cannot be edited
_CAMERA = ("Camera", "Industrial GigE", "Industrial USB3", "Hikrobot MVS")
_DL = ("Deep learning (ONNX model)",)
_WEIGHTED = ("k1*A + k2*B + c", "k1*A + c", "A + c")

#: tool -> parameter -> (controlling parameter, the values it applies to)
WHEN: Dict[str, Dict[str, tuple]] = {
    "Image Source": {
        "file_path": ("source_type", ("File",)), "pattern_type": ("source_type", ("Synthetic",)),
        "camera_device": ("source_type", _CAMERA), "camera_index": ("source_type", ("Camera",)),
        "stream_url": ("source_type", ("IP Stream",)),
        "auto_exposure": ("source_type", ("Camera",)),
        "exposure_time_us": ("source_type", _CAMERA), "gain": ("source_type", _CAMERA), "trigger_mode": ("source_type", _CAMERA),
        "mvs_config_file": ("source_type", ("Hikrobot MVS",)), "mvs_trigger_source": ("source_type", ("Hikrobot MVS",)),
    },
    "Image Binarization": {
        "threshold": ("method", ("Manual",)), "adaptive_block_size": ("method", ("Adaptive",)), "adaptive_c": ("method", ("Adaptive",)),
        "low_threshold": ("method", ("Hard Threshold",)), "high_threshold": ("method", ("Hard Threshold",)),
        "kernel_width": ("method", ("Mean", "Gaussian")), "kernel_height": ("method", ("Mean", "Gaussian")),
        "gaussian_sigma": ("method", ("Gaussian",)), "threshold_offset": ("method", ("Mean", "Gaussian")),
        "comparison": ("method", ("Hard Threshold", "Mean", "Gaussian")),
    },
    "Image Filter": {"sigma": ("filter_type", ("Gaussian", "Unsharp Mask", "Mean")),
                     "kernel_size": ("filter_type", ("Gaussian", "Box", "Median", "Mean")),
                     "edge_low": ("filter_type", ("Edge Extraction",)), "edge_high": ("filter_type", ("Edge Extraction",))},
    "Image Transform": {"scale": ("operation", ("Resize",)), "angle": ("operation", ("Rotate", "Mirror and Rotate")),
                        "expand": ("operation", ("Rotate", "Mirror and Rotate")), "mirror": ("operation", ("Mirror and Rotate",))},
    "Color Convert": {k: ("mode", ("Gray: User-defined",)) for k in ("coeff_r", "coeff_g", "coeff_b")},
    "Image Calculate": {k: ("operation", _WEIGHTED) for k in ("calc_weight1", "calc_weight2", "image_offset")},
    "Color Extraction": {k: ("preset_color", ("Custom",)) for k in ("h_min", "h_max", "s_min", "s_max", "v_min", "v_max")},
    "Image Output": {"image_quality": ("file_format", ("JPEG",))},
    "Condition Branch": {"threshold_high": ("operator", ("Between",))},
    "Branch": {"target_value": ("mode", ("Index by Value",)), "bit_index": ("mode", ("Index by Bit",))},
    "Defect Detection": {"model_path": ("method", _DL), "model_task": ("method", _DL), "dl_threshold": ("method", _DL),
                         "defect_type": ("method", ("Classical (contrast)",)), "sensitivity": ("method", ("Classical (contrast)",))},
    "Lens Distortion Calibration": {"calibration_file": ("mode", ("Profile File",)),
                                    **{k: ("mode", ("Manual Coefficients",)) for k in ("manual_fx", "manual_fy", "manual_cx", "manual_cy")}},
    "Geometry Generation": {"line_p1": ("geom_type", ("Reference Line",)), "line_p2": ("geom_type", ("Reference Line",)),
                            "center_x": ("geom_type", ("Datum Cross", "Pitch Circle")), "center_y": ("geom_type", ("Datum Cross", "Pitch Circle")),
                            "radius": ("geom_type", ("Pitch Circle",))},
}


def inactive(tool_name: str, params: Dict[str, Any]) -> Dict[str, str]:
    """The parameters that do not apply with the module's current settings, each with the reason (shown in the blank box)."""
    out: Dict[str, str] = {}
    for key, (ctrl, values) in WHEN.get(tool_name, {}).items():
        if key in params and ctrl in params and params[ctrl] not in values:
            out[key] = f"Not used with {params[ctrl]}"
    if tool_name == "Image Source" and params.get("source_type") == "Camera" and params.get("auto_exposure"):
        for key in ("exposure_time_us", "gain"):                 # the camera sets these itself
            out.setdefault(key, "Set by the camera (Auto exposure)")
    return out
