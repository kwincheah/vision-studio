"""VisionMaster guide, chapter "Image Processing": the modules that were missing.

Image Combination, Distortion Correction, Image Fixture, Shade Correction, Inverse Affine Transformation, Affine Transformation
(cut and zoom), Ring Expansion, Copy Fill, Frame Mean, Image Normalization, Image Correction, Image Stitch, Multiple Images Fusion.

The plain image functions at the top (morphology, binarize, filter, enhance, shade) are shared with Image Combination and with the
existing Image Morphology / Binarization / Filter / Enhancement modules.
"""
import math
import os
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core.param_schema import combo, enum, num, path
from apex_vision.tools._spec import (as_bgr, as_gray, define, err, get_image, img, like_input, ng, no_image, ok, port, val)

CAT = "Image Processing"
ELEMENTS = {"Rect": cv2.MORPH_RECT, "Ellipse": cv2.MORPH_ELLIPSE, "Cross": cv2.MORPH_CROSS}
CMP = ["Greater or Equal", "Less or Equal", "Equal", "Not Equal"]


# ---------------------------------------------------------------------------------------------------------------------------
# plain image functions
# ---------------------------------------------------------------------------------------------------------------------------
def morphology(a: np.ndarray, kind: str, element: str, w: int, h: int, iters: int) -> np.ndarray:
    k = cv2.getStructuringElement(ELEMENTS.get(element, cv2.MORPH_RECT), (max(1, int(w)), max(1, int(h))))
    ops = {"Dilation": cv2.MORPH_DILATE, "Erosion": cv2.MORPH_ERODE, "Opening": cv2.MORPH_OPEN, "Closing": cv2.MORPH_CLOSE}
    return cv2.morphologyEx(a, ops.get(kind, cv2.MORPH_OPEN), k, iterations=max(1, int(iters)))


def _compare(a: np.ndarray, b: np.ndarray, how: str) -> np.ndarray:
    return {"Greater or Equal": a >= b, "Less or Equal": a <= b, "Equal": a == b, "Not Equal": a != b}.get(how, a >= b)


def binarize(a: np.ndarray, kind: str, low: int = 100, high: int = 255, kw: int = 15, kh: int = 15, sigma: float = 0.0,
             compare: str = "Greater or Equal", offset: float = 0.0) -> np.ndarray:
    g = as_gray(a)
    if kind == "Auto":
        _, out = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        return out
    if kind == "Mean":
        ref = cv2.blur(g, (max(1, int(kw)), max(1, int(kh)))).astype(np.float32)
        return (_compare(g.astype(np.float32) + float(offset), ref, compare) * 255).astype(np.uint8)
    if kind == "Gaussian":
        k = max(1, int(kw)) | 1
        ref = cv2.GaussianBlur(g, (k, k), float(sigma)).astype(np.float32)
        return (_compare(g.astype(np.float32) + float(offset), ref, compare) * 255).astype(np.uint8)
    return (((g >= low) & (g <= high)) * 255).astype(np.uint8)                  # hard threshold: white inside [low, high]


def filter_image(a: np.ndarray, kind: str, k: int = 5, sigma: float = 0.0, edge_low: int = 40, edge_high: int = 120) -> np.ndarray:
    k = max(1, int(k)) | 1
    if kind == "Median":
        return cv2.medianBlur(a, k)
    if kind == "Mean":
        return cv2.blur(a, (k, k))
    if kind == "Inverse":
        return 255 - a
    if kind == "Edge Extraction":
        g = as_gray(a)
        gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        return ((mag >= edge_low) & (mag <= edge_high)).astype(np.uint8) * 255
    return cv2.GaussianBlur(a, (k, k), float(sigma))


def enhance(a: np.ndarray, sharpen: float = 0.0, sharpen_kernel: int = 5, contrast: float = 100.0, gamma: float = 1.0,
            gain: float = 0.0, offset: float = 0.0) -> np.ndarray:
    out = a.astype(np.float32)
    if sharpen > 0:
        k = max(1, int(sharpen_kernel)) | 1
        blur = cv2.GaussianBlur(out, (k, k), 0)
        out = out + float(sharpen) * (out - blur)                                # unsharp mask: intensity scales the added detail
    if contrast != 100:
        out = (out - 128.0) * (float(contrast) / 100.0) + 128.0
    if gamma != 1:
        out = 255.0 * np.power(np.clip(out, 0, 255) / 255.0, float(gamma))
    out = float(offset) + out * (1.0 + float(gain) / 100.0)                      # curdst = offset + cursrc * gain
    return np.clip(out, 0, 255).astype(np.uint8)


def shade(a: np.ndarray, kernel: int = 15, gain: float = 10.0, compensation: float = 128.0, noise: int = 0, direction: str = "XY") -> np.ndarray:
    k = 2 * max(1, int(kernel)) + 1
    size = {"X": (k, 1), "Y": (1, k)}.get(direction, (k, k))
    f = a.astype(np.float32)
    residual = f - cv2.blur(f, size)
    residual[np.abs(residual) < float(noise)] = 0.0
    return np.clip(float(compensation) + residual * (float(gain) / 10.0), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------------------------------
# Image Combination
# ---------------------------------------------------------------------------------------------------------------------------
STEPS = ["Morphology", "Binarization", "Filter", "Enhancement", "Shade Correction"]


@define("Image Combination", CAT,
        "Runs several image processing steps in one module: morphology, binarization, filter, enhancement and shade correction. "
        "Switch each step on or off and set the order.",
        inputs=[img()], outputs=[img()],
        params={
            "order": "Morphology,Binarization,Filter,Enhancement,Shade Correction",
            "enable_morphology": False, "morph_type": "Opening", "morph_element": "Rect", "morph_width": 3, "morph_height": 3, "morph_iterations": 1,
            "enable_binarization": False, "bin_type": "Auto", "bin_low": 100, "bin_high": 255,
            "enable_filter": False, "filter_type": "Gaussian", "filter_kernel": 5,
            "enable_enhancement": False, "enh_contrast": 100, "enh_gamma": 1.0, "enh_gain": 0, "enh_offset": 0, "enh_sharpen": 0.0,
            "enable_shade": False, "shade_kernel": 15, "shade_gain": 10.0, "shade_compensation": 128,
        },
        schema={
            "order": {"kind": "text", "hint": "the five step names, comma separated, in the order to run them"},
            "morph_type": enum("Dilation", "Erosion", "Opening", "Closing"), "morph_element": enum("Rect", "Ellipse", "Cross"),
            "morph_width": num(1, 255), "morph_height": num(1, 255), "morph_iterations": num(1, 50),
            "bin_type": enum("Hard Threshold", "Mean", "Gaussian", "Auto"), "bin_low": num(0, 255), "bin_high": num(0, 255),
            "filter_type": enum("Gaussian", "Median", "Mean", "Inverse", "Edge Extraction"), "filter_kernel": num(1, 99),
            "enh_contrast": num(0, 1000), "enh_gamma": num(0.05, 8, 0.05, decimals=2), "enh_gain": num(0, 100), "enh_offset": num(-255, 255),
            "enh_sharpen": num(0, 20, 0.1, decimals=1), "shade_kernel": num(1, 50), "shade_gain": num(0, 100, 0.5, decimals=1),
            "shade_compensation": num(0, 255)})
def image_combination(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    order = [s.strip() for s in str(t.get_param("order", "")).split(",") if s.strip() in STEPS] or STEPS
    ran = []
    g = lambda k, d=None: t.get_param(k, d)                                       # noqa: E731
    for step in order:
        if step == "Morphology" and g("enable_morphology"):
            a = morphology(a, g("morph_type"), g("morph_element"), g("morph_width"), g("morph_height"), g("morph_iterations"))
        elif step == "Binarization" and g("enable_binarization"):
            a = binarize(a, g("bin_type"), g("bin_low"), g("bin_high"))
        elif step == "Filter" and g("enable_filter"):
            a = filter_image(a, g("filter_type"), g("filter_kernel"))
        elif step == "Enhancement" and g("enable_enhancement"):
            a = enhance(a, g("enh_sharpen"), 5, g("enh_contrast"), g("enh_gamma"), g("enh_gain"), g("enh_offset"))
        elif step == "Shade Correction" and g("enable_shade"):
            a = shade(a, g("shade_kernel"), g("shade_gain"), g("shade_compensation"))
        else:
            continue
        ran.append(step)
    return ok("Ran: " + (", ".join(ran) if ran else "nothing (all steps are switched off)"), Image=a)


# ---------------------------------------------------------------------------------------------------------------------------
# Distortion Correction
# ---------------------------------------------------------------------------------------------------------------------------
_CALIB_CACHE: Dict[str, Tuple[float, Any]] = {}


def _load_calibration(path_: str):
    from apex_vision.core.lens_calibration import LensCalibrationModel
    stamp = os.path.getmtime(path_)
    hit = _CALIB_CACHE.get(path_)
    if hit and hit[0] == stamp:
        return hit[1]
    model = LensCalibrationModel()
    if not model.load_json(path_):
        raise ValueError(f"could not read the calibration file {os.path.basename(path_)}")
    homography = None
    try:
        import json
        with open(path_, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if "homography" in data:
            homography = np.array(data["homography"], np.float64).reshape(3, 3)
    except (OSError, ValueError):
        pass
    _CALIB_CACHE[path_] = (stamp, (model, homography))
    return _CALIB_CACHE[path_][1]


@define("Distortion Correction", CAT,
        "Corrects lens and perspective distortion with a calibration file (radial, perspective, or both).",
        inputs=[img()], outputs=[img()],
        params={"calibration_file": "", "refresh_signal": 0, "correction_mode": "Radial Distortion"},
        schema={"calibration_file": path("Calibration file (*.json *.xml *.mvs);;All files (*)"), "refresh_signal": num(0, 1_000_000),
                "correction_mode": enum("Perspective Distortion", "Radial Distortion", "Radial Perspective Distortion")})
def distortion_correction(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    f = str(t.get_param("calibration_file", "")).strip().strip('"')
    if not f:
        return err("Distortion Correction: no calibration file chosen")
    if not os.path.isfile(f):
        return err(f"Distortion Correction: calibration file not found: {f}")
    if int(t.get_param("refresh_signal", 0)) != 0:
        _CALIB_CACHE.pop(f, None)                                                # re-read the file on this run
    model, homography = _load_calibration(f)
    mode = str(t.get_param("correction_mode", "Radial Distortion"))
    out = a
    if "Radial" in mode:
        out = model.undistort(out, alpha=0.0)
    if "Perspective" in mode:
        if homography is None:
            return err("Distortion Correction: the calibration file has no perspective data ('homography')")
        out = cv2.warpPerspective(out, homography, (out.shape[1], out.shape[0]))
    return ok(f"{mode} corrected", Image=out)


# ---------------------------------------------------------------------------------------------------------------------------
# Image Fixture
# ---------------------------------------------------------------------------------------------------------------------------
def fixture_matrix(ref_pt, ref_ang, run_pt, run_ang) -> np.ndarray:
    """2x3 matrix that brings the content at the running pose (point + angle) onto the reference pose. Angles in degrees, counterclockwise."""
    m = cv2.getRotationMatrix2D((float(run_pt[0]), float(run_pt[1])), float(ref_ang) - float(run_ang), 1.0)
    m[0, 2] += float(ref_pt[0]) - float(run_pt[0])
    m[1, 2] += float(ref_pt[1]) - float(run_pt[1])
    return m


@define("Image Fixture", CAT,
        "Moves and turns the picture so a part that shifted in the field of view lands on the reference position again. "
        "Use the correction from Position Correction ('By Info'), two points and angles ('By Point'), or typed coordinates ('By Coordinate').",
        inputs=[img(), val("Delta_X", "How far the part moved in X"), val("Delta_Y", "How far the part moved in Y"),
                val("Delta_Angle", "How far the part turned (degrees)"), port("Ref_Point", "pt", "Reference point"),
                port("Run_Point", "pt", "Point found now"), val("Ref_Angle", "Reference angle"), val("Run_Angle", "Angle found now")],
        outputs=[img(), port("Matrix", "any", "The 2x3 matrix that was applied")],
        params={"mode": "By Info", "ref_point": [320, 240], "run_point": [320, 240], "ref_angle": 0.0, "run_angle": 0.0, "fill_value": 0},
        schema={"mode": enum("By Info", "By Point", "By Coordinate"), "ref_point": {"kind": "point"}, "run_point": {"kind": "point"},
                "ref_angle": num(-360, 360, 0.5, "deg", 2), "run_angle": num(-360, 360, 0.5, "deg", 2), "fill_value": num(0, 255)})
def image_fixture(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    mode = str(t.get_param("mode", "By Info"))
    ref_pt, ref_ang = t.get_param("ref_point"), t.as_float(t.get_param("ref_angle", 0.0))
    if mode == "By Point":
        rp, ra = ctx.get("Run_Point"), ctx.get("Run_Angle")
        ref_pt = ctx.get("Ref_Point") if ctx.get("Ref_Point") is not None else ref_pt
        ref_ang = t.as_float(ctx.get("Ref_Angle"), ref_ang) if ctx.get("Ref_Angle") is not None else ref_ang
        run_pt, run_ang = (rp if rp is not None else t.get_param("run_point")), t.as_float(ra, t.get_param("run_angle", 0.0))
    elif mode == "By Info":
        if ctx.get("Delta_X") is None and ctx.get("Delta_Y") is None and ctx.get("Delta_Angle") is None:
            return ng("By Info needs Delta_X / Delta_Y / Delta_Angle from a Position Correction module")
        run_pt = (ref_pt[0] + t.as_float(ctx.get("Delta_X")), ref_pt[1] + t.as_float(ctx.get("Delta_Y")))
        run_ang = ref_ang + t.as_float(ctx.get("Delta_Angle"))
    else:
        run_pt, run_ang = t.get_param("run_point"), t.as_float(t.get_param("run_angle", 0.0))
    rp_, qp_ = point_of(ref_pt), point_of(run_pt)
    if rp_ is None or qp_ is None:
        return err("the reference or running point is not a valid x, y pair")
    m = fixture_matrix(rp_, ref_ang, qp_, run_ang)
    fill = float(t.get_param("fill_value", 0))
    out = cv2.warpAffine(a, m, (a.shape[1], a.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                         borderValue=(fill, fill, fill, fill))
    return ok(f"moved by ({rp_[0] - qp_[0]:+.1f}, {rp_[1] - qp_[1]:+.1f}) and turned {ref_ang - run_ang:+.2f} deg", Image=out, Matrix=m.tolist())


def point_of(v):
    from apex_vision.tools._spec import point
    return point(v)


# ---------------------------------------------------------------------------------------------------------------------------
# Shade Correction
# ---------------------------------------------------------------------------------------------------------------------------
@define("Shade Correction", CAT,
        "Evens out uneven lighting: compares the picture with a smoothed copy of itself and rebuilds it around a fixed brightness.",
        inputs=[img()], outputs=[img()],
        params={"kernel_size": 15, "gain": 10.0, "compensation": 128, "noise": 0, "direction": "XY"},
        schema={"kernel_size": num(1, 50), "gain": num(0, 100, 0.5, decimals=1), "compensation": num(0, 255), "noise": num(0, 255),
                "direction": enum("X", "Y", "XY")})
def shade_correction(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    out = shade(a, t.get_param("kernel_size"), t.get_param("gain"), t.get_param("compensation"), t.get_param("noise"), t.get_param("direction"))
    return ok(f"Shade corrected ({t.get_param('direction')}, kernel {t.get_param('kernel_size')})", Image=out)


# ---------------------------------------------------------------------------------------------------------------------------
# Affine Transformation (cut and zoom) and Inverse Affine Transformation
# ---------------------------------------------------------------------------------------------------------------------------
def roi_corners(roi, angle_deg: float) -> np.ndarray:
    """The four corners (top-left, top-right, bottom-right, bottom-left) of a rectangle turned about its centre."""
    x, y, w, h = [float(v) for v in roi[:4]]
    cx, cy = x + w / 2.0, y + h / 2.0
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    out = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        out.append((cx + dx * c + dy * s, cy - dx * s + dy * c))                 # positive angle = counterclockwise on screen
    return np.array(out, np.float32)


@define("Affine Transformation", CAT,
        "Cuts a (turned) rectangle out of the picture and resizes it. Set the region, its angle, the scale and the aspect ratio.",
        inputs=[img()], outputs=[img(), val("Width"), val("Height")],
        params={"roi": [100, 100, 200, 150], "roi_angle": 0.0, "scale": 1.0, "aspect_ratio": 1.0, "interpolation": "Bilinear",
                "fill_mode": "Constant", "fill_value": 0},
        schema={"roi": {"kind": "rect"}, "roi_angle": num(-360, 360, 0.5, "deg", 2), "scale": num(0.01, 20, 0.05, decimals=2),
                "aspect_ratio": num(0.05, 20, 0.05, decimals=2), "interpolation": enum("Nearest Neighbor", "Bilinear"),
                "fill_mode": enum("Constant", "Copy Nearby"), "fill_value": num(0, 255)})
def affine_transformation(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    roi = t.get_param("roi")
    if roi[2] <= 0 or roi[3] <= 0:
        return err("draw the region first: it is empty")
    scale, aspect = t.as_float(t.get_param("scale", 1.0), 1.0), t.as_float(t.get_param("aspect_ratio", 1.0), 1.0)
    ow, oh = max(1, int(round(roi[2] * scale))), max(1, int(round(roi[3] * scale * aspect)))
    if max(ow, oh) > 16384:
        return err("the result would be larger than 16384 pixels")
    src = roi_corners(roi, t.as_float(t.get_param("roi_angle", 0.0)))
    dst = np.array([[0, 0], [ow, 0], [ow, oh]], np.float32)
    m = cv2.getAffineTransform(src[:3], dst)
    interp = cv2.INTER_NEAREST if str(t.get_param("interpolation")) == "Nearest Neighbor" else cv2.INTER_LINEAR
    border = cv2.BORDER_REPLICATE if str(t.get_param("fill_mode")) == "Copy Nearby" else cv2.BORDER_CONSTANT
    fill = float(t.get_param("fill_value", 0))
    out = cv2.warpAffine(a, m, (ow, oh), flags=interp, borderMode=border, borderValue=(fill, fill, fill, fill))
    return ok(f"cut {ow} x {oh}", [{"type": "line", "pt1": tuple(int(v) for v in src[i]), "pt2": tuple(int(v) for v in src[(i + 1) % 4]),
                                      "color": (0, 200, 255), "thickness": 2} for i in range(4)], Image=out, Width=ow, Height=oh)


@define("Inverse Affine Transformation", CAT,
        "Puts a picture back into a (turned) region of a base picture: the picture is scaled to the region and turned to its angle. "
        "Use it after Affine Transformation to show the result at the original place.",
        inputs=[img("Image", "The picture to put back"), img("Base_Image", "The picture to put it onto (optional)")],
        outputs=[img()],
        params={"roi": [100, 100, 200, 150], "roi_angle": 0.0, "base_width": 640, "base_height": 480, "base_fill": 0},
        schema={"roi": {"kind": "rect"}, "roi_angle": num(-360, 360, 0.5, "deg", 2), "base_width": num(1, 16384, unit="px"),
                "base_height": num(1, 16384, unit="px"), "base_fill": num(0, 255)})
def inverse_affine(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    base = get_image(ctx, "Base_Image")
    if base is None:
        base = np.full((int(t.get_param("base_height")), int(t.get_param("base_width")), 3), int(t.get_param("base_fill")), np.uint8)
    base = like_input(a, base) if a.ndim == base.ndim else (as_bgr(base) if a.ndim == 3 else as_gray(base))
    roi = t.get_param("roi")
    if roi[2] <= 0 or roi[3] <= 0:
        return err("draw the region first: it is empty")
    dst = roi_corners(roi, t.as_float(t.get_param("roi_angle", 0.0)))
    h, w = a.shape[:2]
    m = cv2.getAffineTransform(np.array([[0, 0], [w, 0], [w, h]], np.float32), dst[:3])
    warped = cv2.warpAffine(a, m, (base.shape[1], base.shape[0]), flags=cv2.INTER_LINEAR)
    mask = cv2.warpAffine(np.full((h, w), 255, np.uint8), m, (base.shape[1], base.shape[0]), flags=cv2.INTER_NEAREST)
    out = base.copy()
    out[mask > 0] = warped[mask > 0]
    return ok("put back into the region", Image=out)


# ---------------------------------------------------------------------------------------------------------------------------
# Ring Expansion
# ---------------------------------------------------------------------------------------------------------------------------
@define("Ring Expansion", CAT,
        "Unrolls a ring (or a part of one) into a straight strip, for reading text printed around a circle or checking a round part.",
        inputs=[img()], outputs=[img(), val("Width"), val("Height")],
        params={"center": [320, 240], "inner_radius": 60.0, "outer_radius": 140.0, "start_angle": 0.0, "arc_angle": 360.0,
                "direction": "Counterclockwise", "radial_direction": "Inside to Outside", "output_width": 0},
        schema={"center": {"kind": "point"}, "inner_radius": num(0, 20000, 1, "px", 1), "outer_radius": num(1, 20000, 1, "px", 1),
                "start_angle": num(-360, 360, 1, "deg", 1), "arc_angle": num(1, 360, 1, "deg", 1),
                "direction": enum("Counterclockwise", "Clockwise"), "radial_direction": enum("Inside to Outside", "Outside to Inside"),
                "output_width": num(0, 16384, unit="px")})
def ring_expansion(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    cx, cy = [float(v) for v in t.get_param("center")]
    r0, r1 = float(t.get_param("inner_radius")), float(t.get_param("outer_radius"))
    if r1 <= r0:
        return err("the outer radius must be larger than the inner radius")
    span, start = float(t.get_param("arc_angle")), float(t.get_param("start_angle"))
    ccw = str(t.get_param("direction")) == "Counterclockwise"
    height = max(2, int(round(r1 - r0)))
    width = int(t.get_param("output_width")) or max(2, int(round(math.radians(span) * (r0 + r1) / 2.0)))
    if width > 16384:
        return err("the strip would be wider than 16384 pixels")
    u = np.linspace(0.0, 1.0, width, dtype=np.float32)
    v = np.linspace(0.0, 1.0, height, dtype=np.float32)
    if str(t.get_param("radial_direction")) == "Outside to Inside":
        v = v[::-1]
    theta = np.radians(start + (span * u if ccw else -span * u))
    radius = r0 + v * (r1 - r0)
    mapx = (cx + radius[:, None] * np.cos(theta)[None, :]).astype(np.float32)
    mapy = (cy - radius[:, None] * np.sin(theta)[None, :]).astype(np.float32)       # screen y points down: counterclockwise = up
    out = cv2.remap(a, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return ok(f"unrolled {width} x {height}", [{"type": "circle", "center": (int(cx), int(cy)), "radius": int(r0), "color": (0, 200, 255)},
                                              {"type": "circle", "center": (int(cx), int(cy)), "radius": int(r1), "color": (0, 200, 255)}],
              Image=out, Width=width, Height=height)


# ---------------------------------------------------------------------------------------------------------------------------
# Copy Fill
# ---------------------------------------------------------------------------------------------------------------------------
@define("Copy Fill", CAT,
        "Fill: paints inside and outside a region with fixed grey values. Copy: keeps the region and spreads its own edge pixels over "
        "the rest of its bounding rectangle, so a round region can be processed as a clean rectangle.",
        inputs=[img()], outputs=[img()],
        params={"process_type": "Fill", "roi": [100, 100, 200, 150], "roi_shape": "Rectangle", "fill_outside": 0, "fill_inside": 255},
        schema={"process_type": enum("Fill", "Copy"), "roi": {"kind": "rect"}, "roi_shape": enum("Rectangle", "Ellipse"),
                "fill_outside": num(0, 255), "fill_inside": num(0, 255)})
def copy_fill(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    x, y, w, h = t.get_roi("roi", [100, 100, 200, 150], img_shape=a.shape)
    mask = np.zeros(a.shape[:2], np.uint8)
    if str(t.get_param("roi_shape")) == "Ellipse":
        cv2.ellipse(mask, (x + w // 2, y + h // 2), (max(1, w // 2), max(1, h // 2)), 0, 0, 360, 255, -1)
    else:
        mask[y:y + h, x:x + w] = 255
    out = a.copy()
    if str(t.get_param("process_type")) == "Fill":
        out[mask == 0] = int(t.get_param("fill_outside"))
        out[mask > 0] = int(t.get_param("fill_inside"))
        return ok("filled", Image=out)
    box = np.zeros_like(mask)
    box[y:y + h, x:x + w] = 255
    need = (box > 0) & (mask == 0)
    if need.any():
        # every pixel of the rectangle that is outside the region takes the value of the nearest pixel inside it
        _, labels = cv2.distanceTransformWithLabels((mask == 0).astype(np.uint8), cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
        ys, xs = np.nonzero(mask > 0)
        nearest = np.zeros((int(labels.max()) + 1, 2), np.int32)
        nearest[labels[mask > 0]] = np.stack([ys, xs], axis=1)
        ny, nx = nearest[labels[need]].T
        out[need] = a[ny, nx]
    out[box == 0] = int(t.get_param("fill_outside"))
    return ok("copied", Image=out)


# ---------------------------------------------------------------------------------------------------------------------------
# Frame Mean
# ---------------------------------------------------------------------------------------------------------------------------
@define("Frame Mean", CAT,
        "Averages the same region over many pictures (up to 100) to cut noise. Each run adds one picture; 'Ignore' skips it and 'Clear' starts over.",
        inputs=[img(), port("Ignore", "bool", "Skip this picture"), port("Clear", "bool", "Throw away the pictures collected so far")],
        outputs=[img(), val("Count", "Pictures averaged so far")],
        params={"roi": [0, 0, 0, 0], "max_frames": 10},
        schema={"roi": {"kind": "rect"}, "max_frames": num(1, 100)})
def frame_mean(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    frames: deque = getattr(t, "_frames", None)
    limit = int(t.get_param("max_frames", 10))
    if frames is None or frames.maxlen != limit:
        frames = deque(list(frames or [])[-limit:], maxlen=limit)
        t._frames = frames
    if ctx.get("Clear"):
        frames.clear()
    if frames and frames[0].shape != a.shape:
        frames.clear()                                                           # the picture size changed: start again
    if not ctx.get("Ignore"):
        frames.append(a.astype(np.float32))
    if not frames:
        return ng("no pictures collected yet", Image=a, Count=0)
    mean = np.mean(np.stack(list(frames)), axis=0)
    x, y, w, h = [int(v) for v in t.get_param("roi")]
    out = a.copy()
    if w > 0 and h > 0:
        x, y, w, h = t.get_roi("roi", [0, 0, 1, 1], img_shape=a.shape)
        out[y:y + h, x:x + w] = np.clip(mean[y:y + h, x:x + w], 0, 255).astype(np.uint8)
    else:
        out = np.clip(mean, 0, 255).astype(np.uint8)
    return ok(f"averaged {len(frames)} picture(s)", Image=out, Count=len(frames))


# ---------------------------------------------------------------------------------------------------------------------------
# Image Normalization
# ---------------------------------------------------------------------------------------------------------------------------
@define("Image Normalization", CAT,
        "Re-maps grey levels: histogram equalization, histogram normalization (stretch between chosen levels after trimming the ends), or "
        "standard deviation normalization (a target average and spread).",
        inputs=[img()], outputs=[img()],
        params={"normalization_type": "Histogram Equalization", "left_ratio": 1.0, "right_ratio": 1.0, "min_gray": 0, "max_gray": 255,
                "target_mean": 128, "target_std": 40.0},
        schema={"normalization_type": enum("Histogram Equalization", "Histogram Normalization", "Standard Deviation Normalization"),
                "left_ratio": num(0, 49, 0.1, "%", 1), "right_ratio": num(0, 49, 0.1, "%", 1), "min_gray": num(0, 254), "max_gray": num(1, 255),
                "target_mean": num(0, 255), "target_std": num(0.1, 128, 0.5, decimals=1)})
def image_normalization(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    kind = str(t.get_param("normalization_type"))
    chans = [a] if a.ndim == 2 else None
    if chans is None:
        hsv = cv2.cvtColor(as_bgr(a), cv2.COLOR_BGR2HSV)
        v = hsv[:, :, 2]
    else:
        v = a

    def apply(g: np.ndarray) -> np.ndarray:
        if kind == "Histogram Equalization":
            return cv2.equalizeHist(g)
        if kind == "Histogram Normalization":
            lo = np.percentile(g, float(t.get_param("left_ratio")))
            hi = np.percentile(g, 100.0 - float(t.get_param("right_ratio")))
            lo_t, hi_t = float(t.get_param("min_gray")), float(t.get_param("max_gray"))
            if hi <= lo:
                return g
            return np.clip((g.astype(np.float32) - lo) / (hi - lo) * (hi_t - lo_t) + lo_t, 0, 255).astype(np.uint8)
        mean, std = float(g.mean()), float(g.std())
        if std < 1e-6:
            return np.full_like(g, int(t.get_param("target_mean")))
        return np.clip((g.astype(np.float32) - mean) / std * float(t.get_param("target_std")) + float(t.get_param("target_mean")), 0, 255).astype(np.uint8)

    nv = apply(v)
    if chans is not None:
        return ok(kind, Image=nv)
    hsv[:, :, 2] = nv
    return ok(kind, Image=cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))


# ---------------------------------------------------------------------------------------------------------------------------
# Image Correction (barrel / pincushion)
# ---------------------------------------------------------------------------------------------------------------------------
@define("Image Correction", CAT,
        "Straightens barrel (bulging) or pincushion (pinched) lens distortion. A positive expansion corrects barrel distortion, a negative "
        "one corrects pincushion; the scaling amount zooms the result.",
        inputs=[img()], outputs=[img()],
        params={"expansion_amount": 10.0, "scaling_amount": 0.0},
        schema={"expansion_amount": num(-100, 100, 0.5, decimals=1), "scaling_amount": num(-90, 500, 1, "%", 1)})
def image_correction(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    h, w = a.shape[:2]
    k = float(t.get_param("expansion_amount")) / 100.0
    s = max(0.05, 1.0 + float(t.get_param("scaling_amount")) / 100.0)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    half_diag = math.hypot(cx, cy)
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    dx, dy = (xs - cx) / s, (ys - cy) / s
    r2 = (dx * dx + dy * dy) / (half_diag * half_diag)
    factor = 1.0 - k * r2
    out = cv2.remap(a, (cx + dx * factor).astype(np.float32), (cy + dy * factor).astype(np.float32), cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return ok(f"expansion {k * 100:+.1f}, scale {s:.2f}", Image=out)


# ---------------------------------------------------------------------------------------------------------------------------
# Image Stitch
# ---------------------------------------------------------------------------------------------------------------------------
STITCH_PORTS = [img(f"Image_{i}", f"Picture {i}") for i in range(9)]


def _register_translation(base: np.ndarray, moving: np.ndarray) -> Optional[np.ndarray]:
    """Similarity transform that maps ``moving`` onto ``base`` (ORB features + RANSAC), or None if they do not share enough detail."""
    sift = cv2.SIFT_create(4000)
    k1, d1 = sift.detectAndCompute(as_gray(base), None)
    k2, d2 = sift.detectAndCompute(as_gray(moving), None)
    if d1 is None or d2 is None or len(k1) < 12 or len(k2) < 12:
        return None
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(d2, d1, k=2)
    matches = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]       # Lowe's ratio test
    if len(matches) < 12:
        return None
    src = np.float32([k2[m.queryIdx].pt for m in matches])
    dst = np.float32([k1[m.trainIdx].pt for m in matches])
    m, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if m is None or inliers is None or int(inliers.sum()) < 10:
        return None
    return m


def _merge(layers: List[np.ndarray], masks: List[np.ndarray], how: str) -> np.ndarray:
    h, w = layers[0].shape[:2]
    chans = 1 if layers[0].ndim == 2 else layers[0].shape[2]
    shape = (h, w) if chans == 1 else (h, w, chans)
    if how == "Merge Max":
        out = np.zeros(shape, np.uint8)
        for l, m in zip(layers, masks):
            out = np.where(m[..., None] if chans > 1 else m, np.maximum(out, l), out)
        return out
    if how == "Merge Min":
        out = np.full(shape, 255, np.uint8)
        seen = np.zeros((h, w), bool)
        for l, m in zip(layers, masks):
            out = np.where(m[..., None] if chans > 1 else m, np.minimum(out, l), out)
            seen |= m
        out[~seen] = 0
        return out
    if how == "Merge Uncover":                                                    # later pictures only fill what is still empty
        out = np.zeros(shape, np.uint8)
        seen = np.zeros((h, w), bool)
        for l, m in zip(layers, masks):
            fresh = m & ~seen
            out[fresh] = l[fresh]
            seen |= m
        return out
    acc = np.zeros(shape, np.float32)
    cnt = np.zeros((h, w), np.float32)
    for l, m in zip(layers, masks):
        acc += l.astype(np.float32) * (m[..., None] if chans > 1 else m)
        cnt += m
    cnt[cnt == 0] = 1
    return np.clip(acc / (cnt[..., None] if chans > 1 else cnt), 0, 255).astype(np.uint8)


@define("Image Stitch", CAT,
        "Joins several pictures into one. Hard stitch lays them side by side in a grid; model stitch finds where they overlap and blends them "
        "(mean, min, max or uncover). One camera moved several times, or several cameras at once.",
        inputs=[img("Image_0")] + [img(f"Image_{i}") for i in range(1, 9)], outputs=[img(), val("Count", "Pictures joined")],
        params={"input_mode": "Multiple Source", "stitch_type": "Hard Stitch", "stitch_number": 2, "rows": 1, "columns": 2,
                "stitch_direction": "X", "merge_type": "Merge Mean", "cut_ratio": 0, "auto_clear": True, "auto_fill": False},
        schema={"input_mode": enum("Multiple Source", "Single Source"), "stitch_type": enum("Hard Stitch", "Model Stitch"),
                "stitch_number": num(2, 9), "rows": num(1, 9), "columns": num(1, 9), "stitch_direction": enum("X", "Y"),
                "merge_type": enum("Merge Mean", "Merge Min", "Merge Max", "Merge Uncover"), "cut_ratio": num(0, 25, 1, "%", 0)})
def image_stitch(t, ctx):
    n = int(t.get_param("stitch_number"))
    single = str(t.get_param("input_mode")) == "Single Source"
    if single:                                                                   # one camera, several runs: collect the pictures
        buf: List[np.ndarray] = getattr(t, "_stitch_buf", None) or []
        a = get_image(ctx, "Image_0")
        if a is not None:
            if len(buf) >= n:
                buf.pop(0)
            buf.append(a)
        t._stitch_buf = buf
        pics = list(buf)
    else:
        pics = [get_image(ctx, f"Image_{i}") for i in range(n)]
        pics = [p for p in pics if p is not None]
    hard = str(t.get_param("stitch_type")) == "Hard Stitch"
    if len(pics) < n:
        if hard and t.get_param("auto_fill") and pics:
            pics += [np.zeros_like(pics[0])] * (n - len(pics))
        else:
            return ng(f"waiting for pictures: {len(pics)} of {n}", Count=len(pics))
    pics = pics[:n]
    cut = float(t.get_param("cut_ratio")) / 100.0
    if hard:
        rows, cols = int(t.get_param("rows")), int(t.get_param("columns"))
        if rows * cols < n:
            return err(f"a {rows} x {cols} grid cannot hold {n} pictures")
        pics = [as_bgr(p) if pics[0].ndim == 3 else as_gray(p) for p in pics]
        ch, cw = max(p.shape[0] for p in pics), max(p.shape[1] for p in pics)
        if cut > 0:
            pics = [p[int(p.shape[0] * cut):p.shape[0] - int(p.shape[0] * cut), int(p.shape[1] * cut):p.shape[1] - int(p.shape[1] * cut)] for p in pics]
            ch, cw = max(p.shape[0] for p in pics), max(p.shape[1] for p in pics)
        canvas = np.zeros((rows * ch, cols * cw) + pics[0].shape[2:], np.uint8)
        for i, p in enumerate(pics):
            r, c = (i // cols, i % cols) if str(t.get_param("stitch_direction")) == "X" else (i % rows, i // rows)
            canvas[r * ch:r * ch + p.shape[0], c * cw:c * cw + p.shape[1]] = p
        out = canvas
    else:
        pics = [as_bgr(p) if pics[0].ndim == 3 else as_gray(p) for p in pics]
        transforms = [np.array([[1, 0, 0], [0, 1, 0]], np.float64)]
        for i in range(1, len(pics)):
            m = None
            for j in range(i - 1, -1, -1):                                       # register against the nearest earlier picture that overlaps
                rel = _register_translation(pics[j], pics[i])
                if rel is not None:
                    full = np.vstack([transforms[j], [0, 0, 1]]) @ np.vstack([rel, [0, 0, 1]])
                    m = full[:2]
                    break
            if m is None:
                return ng(f"picture {i} does not overlap the others enough to be placed", Count=len(pics))
            transforms.append(m)
        corners = []
        for p, m in zip(pics, transforms):
            h, w = p.shape[:2]
            c = np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]], np.float64) @ m.T
            corners.append(c)
        allc = np.vstack(corners)
        x0, y0 = np.floor(allc.min(axis=0)).astype(int)
        x1, y1 = np.ceil(allc.max(axis=0)).astype(int)
        if (x1 - x0) * (y1 - y0) > 120_000_000:
            return err("the stitched picture would be too large")
        shift = np.array([[1, 0, -x0], [0, 1, -y0]], np.float64)
        layers, masks = [], []
        for p, m in zip(pics, transforms):
            mm = (np.vstack([shift, [0, 0, 1]]) @ np.vstack([m, [0, 0, 1]]))[:2]
            layers.append(cv2.warpAffine(p, mm, (int(x1 - x0), int(y1 - y0))))
            masks.append(cv2.warpAffine(np.full(p.shape[:2], 255, np.uint8), mm, (int(x1 - x0), int(y1 - y0)), flags=cv2.INTER_NEAREST) > 0)
        out = _merge(layers, masks, str(t.get_param("merge_type")))
    if single and t.get_param("auto_clear"):
        t._stitch_buf = []
    return ok(f"stitched {len(pics)} pictures ({'hard' if hard else 'model'}): {out.shape[1]} x {out.shape[0]}", Image=out, Count=len(pics))


# ---------------------------------------------------------------------------------------------------------------------------
# Multiple Images Fusion
# ---------------------------------------------------------------------------------------------------------------------------
@define("Multiple Images Fusion", CAT,
        "Combines pictures of one part lit from different directions (3 to 8) into a reflection (surface colour / texture) picture and a "
        "shadow (shape / relief) picture, to show dents, scratches and raised or engraved characters. Halo removal drops that many of the "
        "brightest readings per pixel (specular glare), always keeping at least two.",
        inputs=[img(f"Image_{i}") for i in range(8)], outputs=[img(), img("Reflection"), img("Shadow")],
        params={"output_type": "All", "filter_size": 3, "enhancement": False, "background_brightness": 128, "contrast_coefficient": 100,
                "direction_enhancement": "None", "direction_grade": 5, "halo_removal": 3},
        schema={"output_type": enum("All", "Reflection", "Shadow"), "filter_size": num(1, 50), "background_brightness": num(0, 255),
                "contrast_coefficient": num(1, 1000), "direction_enhancement": enum("None", "X Direction", "Y Direction"),
                "direction_grade": num(0, 10), "halo_removal": num(1, 8)})
def multiple_images_fusion(t, ctx):
    pics = [get_image(ctx, f"Image_{i}") for i in range(8)]
    pics = [as_gray(p) for p in pics if p is not None]
    if len(pics) < 3:
        return ng(f"needs at least 3 pictures, got {len(pics)}")
    if any(p.shape != pics[0].shape for p in pics):
        return err("the pictures are not all the same size")
    k = max(0, min(int(t.get_param("halo_removal")), len(pics) - 2))                 # at least two pictures always remain
    stack = np.sort(np.stack([p.astype(np.float32) for p in pics]), axis=0)          # per pixel, darkest first
    kept = stack[: len(pics) - k] if k > 0 else stack                                  # drop the k brightest (specular highlights)
    reflection = kept.mean(axis=0)
    relief = (kept.max(axis=0) - kept.min(axis=0))
    fs = int(t.get_param("filter_size")) | 1
    shadow = cv2.GaussianBlur(relief, (fs, fs), 0) if fs > 1 else relief
    if str(t.get_param("direction_enhancement")) != "None":
        axis = 1 if str(t.get_param("direction_enhancement")).startswith("X") else 0
        grad = np.abs(np.gradient(stack.mean(axis=0), axis=axis))
        shadow = shadow + float(t.get_param("direction_grade")) * cv2.GaussianBlur(grad, (fs, fs), 0)
    if t.get_param("enhancement"):
        shadow_img = float(t.get_param("background_brightness")) - shadow * (float(t.get_param("contrast_coefficient")) / 100.0)
    else:
        peak = max(1.0, float(shadow.max()))
        shadow_img = 255.0 - shadow * (255.0 / peak)                                    # automatic: darkest where the relief is strongest
    refl = np.clip(reflection, 0, 255).astype(np.uint8)
    shad = np.clip(shadow_img, 0, 255).astype(np.uint8)
    chosen = {"Reflection": refl, "Shadow": shad}.get(str(t.get_param("output_type")), refl)
    return ok(f"fused {len(pics)} pictures", Image=chosen, Reflection=refl, Shadow=shad)


# ---------------------------------------------------------------------------------------------------------------------------
# Image Enhancement
# ---------------------------------------------------------------------------------------------------------------------------
@define("Image Enhancement", CAT,
        "Sharpens, adjusts contrast and gamma, and corrects brightness: sharpening (intensity and kernel size), a contrast coefficient (100 = no "
        "change), gamma (1 = no change; under 1 brightens the dark parts, over 1 darkens them) and brightness as offset + pixel * gain. All the "
        "steps are applied in that order, and each is skipped at its neutral setting.",
        inputs=[img()], outputs=[img()],
        params={"sharpen_intensity": 0.0, "sharpen_kernel": 5, "contrast": 100.0, "gamma": 1.0, "gain": 0.0, "compensation": 0.0},
        schema={"sharpen_intensity": num(0, 20, 0.1, decimals=1), "sharpen_kernel": num(1, 51), "contrast": num(0, 1000, 5, decimals=0), "gamma": num(0.05, 4, 0.05, decimals=2),
                "gain": num(0, 100, 1, decimals=0), "compensation": num(-255, 255, 1, decimals=0)})
def image_enhancement(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    out = enhance(as_bgr(a) if a.ndim == 3 else a, float(t.get_param("sharpen_intensity")), int(t.get_param("sharpen_kernel")), float(t.get_param("contrast")),
                  float(t.get_param("gamma")), float(t.get_param("gain")), float(t.get_param("compensation")))
    return ok("enhanced", Image=out)
