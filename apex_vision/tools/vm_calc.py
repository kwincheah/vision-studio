"""VisionMaster guide, chapter "Calculation": calibration conversion and the alignment / grasp calculations.

Angles are in degrees, counterclockwise positive in the physical frame (a physical Y axis that points up). In picture coordinates (Y down)
"counterclockwise" is what you see on the screen.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import define, err, ng, ok, port, val
from apex_vision.tools.vm_calib import RESULT_PORTS, apply_matrix, as_points, calibration_for, calibration_matrix, decompose, local_scale

CAT = "Calculation"
MODES = ["By Point", "By Coordinate"]
CAL_FILE = {"kind": "path", "filters": "Calibration files (*.json);;All files (*)"}


def wrap180(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def rot(deg: float) -> np.ndarray:
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def map_angle(m: np.ndarray, p: Tuple[float, float], deg: float) -> float:
    """The direction ``deg`` at point ``p``, as it points after the matrix is applied."""
    a = math.radians(deg)
    q = apply_matrix(m, np.array([[p[0], p[1]], [p[0] + math.cos(a), p[1] + math.sin(a)]]))
    return math.degrees(math.atan2(q[1][1] - q[0][1], q[1][0] - q[0][0]))


def _num(t, name: str) -> float:
    return float(t.get_param(name))


def _pt(t, ctx, port_name: str, px: str, py: str, mode_param: str = "input_mode") -> Optional[Tuple[float, float]]:
    if str(t.get_param(mode_param)) == "By Point":
        p = t.as_point(ctx.get(port_name))
    else:
        p = (_num(t, px), _num(t, py))
    if p is None or not all(math.isfinite(v) for v in p):
        return None
    return float(p[0]), float(p[1])


def _ang(t, ctx, port_name: str, name: str) -> float:
    v = ctx.get(port_name) if str(t.get_param("input_mode")) == "By Point" else None
    if v is None:
        return _num(t, name)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _num(t, name)
    return f if math.isfinite(f) else _num(t, name)


def _cal(t, ctx):
    cal, why = calibration_for(t, ctx)
    if cal is None:
        return None, None, err(why)
    return cal, calibration_matrix(cal), None


NUM3 = lambda unit="": num(-1e9, 1e9, 1, unit, 3)  # noqa: E731


# ---------------------------------------------------------------------------------------------------------------------------
# Calibration Transformation
# ---------------------------------------------------------------------------------------------------------------------------
@define("Calibration Transformation", CAT,
        "Turns picture coordinates into physical ones (or the other way) with a calibration: a point, its angle, or a list of points. Also "
        "gives the calibration's pixel size, scale, shift, rotation, skew and aspect ratio.",
        inputs=[port("Point", "pt", "Point to convert"), port("Angle", "val", "Angle to convert (deg)"), port("Points", "any", "List of points to convert"),
                port("Calibration", "dict", "Calibration to use"), port("Refresh", "val", "Reload the calibration file when not 0")],
        outputs=[val("X"), val("Y"), port("Point", "pt"), val("Angle", "Converted angle (deg)"), port("Points", "any", "The converted list")] + RESULT_PORTS,
        params={"input_mode": "By Coordinate", "x": 100.0, "y": 100.0, "angle": 0.0, "coordinate_type": "Image to Physical", "calibration_file": ""},
        schema={"input_mode": enum(*MODES), "x": NUM3("px"), "y": NUM3("px"), "angle": num(-360, 360, 1, "deg", 3),
                "coordinate_type": enum("Image to Physical", "Physical to Image"), "calibration_file": CAL_FILE})
def calibration_transformation(t, ctx):
    cal, m, bad = _cal(t, ctx)
    if bad:
        return bad
    forward = str(t.get_param("coordinate_type")).startswith("Image")
    mm = m if forward else np.linalg.inv(m)
    d = decompose(m)
    common = {"Calibration": cal, "Matrix": m.tolist(), "Scale": d["scale"], "Pixel_Accuracy": d["pixel_accuracy"], "Translation_X": d["translate_x"],
              "Translation_Y": d["translate_y"], "Rotation": d["rotation"], "Skew": d["skew"], "Aspect_Ratio": d["aspect"]}
    if ctx.get("Points") is not None:
        pts = as_points(ctx.get("Points"))
        if pts is None:
            return err("the list of points is not a list of (x, y) pairs")
        q = apply_matrix(mm, pts)
        return ok(f"{len(q)} points converted", Points=q.tolist(), X=float(q[0][0]), Y=float(q[0][1]), Point=(float(q[0][0]), float(q[0][1])), Angle=None, **common)
    p = _pt(t, ctx, "Point", "x", "y")
    if p is None:
        return err("no point to convert: connect one, or type its coordinates")
    a = _ang(t, ctx, "Angle", "angle")
    q = apply_matrix(mm, np.array([p]))[0]
    qa = wrap180(map_angle(mm, p, a))
    return ok(f"({p[0]:.3f}, {p[1]:.3f}) -> ({q[0]:.4f}, {q[1]:.4f}); angle {a:.2f} -> {qa:.2f}", [g.cross_overlay(p[0], p[1], (0, 255, 255), 6)] if forward else [],
              X=float(q[0]), Y=float(q[1]), Point=(float(q[0]), float(q[1])), Angle=qa, Points=[[float(q[0]), float(q[1])]], **common)


# ---------------------------------------------------------------------------------------------------------------------------
# Scale Transformation
# ---------------------------------------------------------------------------------------------------------------------------
@define("Scale Transformation", CAT,
        "Turns a length measured in pixels into a physical length (or back) using a calibration's pixel size.",
        inputs=[port("Distance", "val", "Length (a number or a list)"), port("Calibration", "dict", "Calibration to use"), port("Refresh", "val", "Reload the calibration file when not 0")],
        outputs=[val("Result", "The converted length"), port("Results", "any", "All converted lengths")] + RESULT_PORTS,
        params={"input_mode": "By Coordinate", "distance": 100.0, "direction": "Pixel to Physical", "calibration_file": ""},
        schema={"input_mode": enum("By Port", "By Coordinate"), "distance": num(-1e12, 1e12, 1, decimals=4), "direction": enum("Pixel to Physical", "Physical to Pixel"),
                "calibration_file": CAL_FILE})
def scale_transformation(t, ctx):
    cal, m, bad = _cal(t, ctx)
    if bad:
        return bad
    raw = ctx.get("Distance") if str(t.get_param("input_mode")) == "By Port" else t.get_param("distance")
    try:
        arr = np.atleast_1d(np.asarray(raw, float)).ravel()
    except (TypeError, ValueError):
        return err("the length must be a number or a list of numbers")
    if arr.size == 0 or not np.all(np.isfinite(arr)):
        return err("no length to convert: connect one, or type it")
    k = cal["pixel_accuracy"]
    out = arr * k if str(t.get_param("direction")).startswith("Pixel") else arr / k
    d = decompose(m)
    common = {"Calibration": cal, "Matrix": m.tolist(), "Scale": d["scale"], "Pixel_Accuracy": d["pixel_accuracy"], "Translation_X": d["translate_x"],
              "Translation_Y": d["translate_y"], "Rotation": d["rotation"], "Skew": d["skew"], "Aspect_Ratio": d["aspect"]}
    return ok(f"{arr[0]:g} -> {out[0]:.6g}" + (f" (and {arr.size - 1} more)" if arr.size > 1 else ""), Result=float(out[0]), Results=out.tolist(), **common)


# ---------------------------------------------------------------------------------------------------------------------------
# Coordinate Transformation
# ---------------------------------------------------------------------------------------------------------------------------
@define("Coordinate Transformation", CAT,
        "Finds where a point in a cut-out piece lies in the original big picture, given the piece's centre in the big picture and its size "
        "(use with Image Division). With the conversion off, points pass through unchanged.",
        inputs=[port("Center", "pt", "Centre of the piece in the big picture"), port("Point", "pt", "Point in the piece"), port("Points", "any", "List of points in the piece")],
        outputs=[val("X"), val("Y"), port("Point", "pt"), port("Points", "any", "All converted points")],
        params={"enable": True, "center_mode": "By Coordinate", "center_x": 320.0, "center_y": 240.0, "piece_width": 200, "piece_height": 200, "point_mode": "By Coordinate",
                "point_x": 100.0, "point_y": 100.0},
        schema={"enable": {"kind": "bool"}, "center_mode": enum(*MODES), "center_x": NUM3("px"), "center_y": NUM3("px"), "piece_width": num(1, 1_000_000, unit="px"),
                "piece_height": num(1, 1_000_000, unit="px"), "point_mode": enum(*MODES), "point_x": NUM3("px"), "point_y": NUM3("px")})
def coordinate_transformation(t, ctx):
    enabled = bool(t.get_param("enable"))
    c = _pt(t, ctx, "Center", "center_x", "center_y", "center_mode")
    if enabled and c is None:
        return err("no centre of the piece: connect it, or type its coordinates")
    w, h = _num(t, "piece_width"), _num(t, "piece_height")
    off = np.array([(c[0] - w / 2.0), (c[1] - h / 2.0)]) if enabled else np.zeros(2)
    if ctx.get("Points") is not None:
        pts = as_points(ctx.get("Points"))
        if pts is None:
            return err("the list of points is not a list of (x, y) pairs")
        q = pts + off
        return ok(f"{len(q)} points moved by ({off[0]:g}, {off[1]:g})", Points=q.tolist(), X=float(q[0][0]), Y=float(q[0][1]), Point=(float(q[0][0]), float(q[0][1])))
    p = _pt(t, ctx, "Point", "point_x", "point_y", "point_mode")
    if p is None:
        return err("no point: connect one, or type its coordinates")
    q = np.array(p) + off
    return ok(f"({p[0]:.2f}, {p[1]:.2f}) -> ({q[0]:.2f}, {q[1]:.2f})", [g.cross_overlay(q[0], q[1], (0, 255, 255), 6)], X=float(q[0]), Y=float(q[1]), Point=(float(q[0]), float(q[1])),
              Points=[[float(q[0]), float(q[1])]])


# ---------------------------------------------------------------------------------------------------------------------------
# Calculate Rotation
# ---------------------------------------------------------------------------------------------------------------------------
@define("Calculate Rotation", CAT,
        "Turns a point or a line about a centre point by an angle (counterclockwise or clockwise as seen on the picture) and gives the point or "
        "line after the turn.",
        inputs=[port("Point", "pt", "Point to turn"), port("Line", "line", "Line to turn"), port("Center", "pt", "Centre of the turn"), port("Angle", "val", "Angle to turn by (deg)")],
        outputs=[port("Point", "pt", "The turned point"), val("X"), val("Y"), port("Line", "line", "The turned line"), val("Line_Angle", "Direction of the turned line (deg)")],
        params={"input_method": "By Point", "input_mode": "By Coordinate", "x": 200.0, "y": 100.0, "line": [100, 100, 300, 100], "center_x": 100.0, "center_y": 100.0,
                "angle": 30.0, "direction": "Counterclockwise"},
        schema={"input_method": enum("By Point", "By Line"), "input_mode": enum("By Port", "By Coordinate"), "x": NUM3("px"), "y": NUM3("px"), "line": {"kind": "line"},
                "center_x": NUM3("px"), "center_y": NUM3("px"), "angle": num(-360, 360, 1, "deg", 3), "direction": enum("Counterclockwise", "Clockwise")})
def calculate_rotation(t, ctx):
    ported = str(t.get_param("input_mode")) == "By Port"
    c = t.as_point(ctx.get("Center")) if ported else (_num(t, "center_x"), _num(t, "center_y"))
    if c is None:
        return err("no centre of rotation: connect one, or type its coordinates")
    try:
        a = float(ctx.get("Angle")) if ported and ctx.get("Angle") is not None else _num(t, "angle")
    except (TypeError, ValueError):
        return err("the angle must be a number")
    if not (math.isfinite(a) and all(math.isfinite(v) for v in c)):
        return err("the angle and the centre must be numbers")
    # on the picture (Y down) a counterclockwise turn has the opposite sign in the usual formula
    r = rot(-a if str(t.get_param("direction")).startswith("Counter") else a)
    cc = np.array(c)
    if str(t.get_param("input_method")) == "By Line":
        raw = ctx.get("Line") if ported else t.get_param("line")
        l = t.as_line(raw)
        if l is None:
            return err("no line to turn: connect one, or type its coordinates")
        p = np.array([[l[0], l[1]], [l[2], l[3]]], float)
        q = (p - cc) @ r.T + cc
        nl = g.line_to_dict(q[0][0], q[0][1], q[1][0], q[1][1])
        ang = math.degrees(math.atan2(q[1][1] - q[0][1], q[1][0] - q[0][0]))
        return ok(f"line turned {a:g} deg; now at {ang:.2f} deg", [g.line_overlay(nl), g.cross_overlay(*c, (0, 0, 255), 6)], Line=nl, Line_Angle=ang, Point=None)
    pt = t.as_point(ctx.get("Point")) if ported else (_num(t, "x"), _num(t, "y"))
    if pt is None or not all(math.isfinite(v) for v in pt):
        return err("no point to turn: connect one, or type its coordinates")
    q = (np.array(pt) - cc) @ r.T + cc
    return ok(f"({pt[0]:.2f}, {pt[1]:.2f}) -> ({q[0]:.2f}, {q[1]:.2f})", [g.cross_overlay(q[0], q[1], (0, 255, 0), 6), g.cross_overlay(*c, (0, 0, 255), 6)],
              Point=(float(q[0]), float(q[1])), X=float(q[0]), Y=float(q[1]), Line=None)


# ---------------------------------------------------------------------------------------------------------------------------
# Single Point Alignment
# ---------------------------------------------------------------------------------------------------------------------------
MOVE_PORTS = [val("Delta_X", "Move needed in X"), val("Delta_Y", "Move needed in Y"), val("Delta_Angle", "Turn needed (deg)"), port("Move", "any", "[dx, dy, turn]")]


@define("Single Point Alignment", CAT,
        "Works out the move that brings an object to a target, from the target's physical position and angle and the object's: how far to "
        "shift and how much to turn. If the object turns about a fixed centre (a rotation stage) give it, and the shift allows for the turn. "
        "Needs physical coordinates, so use it after Calibration Transformation.",
        inputs=[port("Target", "pt", "Target position"), port("Target_Angle", "val"), port("Object", "pt", "Object position"), port("Object_Angle", "val"),
                port("Center", "pt", "Centre the stage turns about (optional)")],
        outputs=MOVE_PORTS + [port("Aligned_Point", "pt", "Where the object ends up (the target)")],
        params={"input_mode": "By Coordinate", "target_x": 100.0, "target_y": 100.0, "target_angle": 0.0, "object_x": 95.0, "object_y": 103.0, "object_angle": 5.0,
                "turn_about": "The Object", "center_x": 0.0, "center_y": 0.0},
        schema={"input_mode": enum(*MODES), "target_x": NUM3(), "target_y": NUM3(), "target_angle": num(-360, 360, 1, "deg", 3), "object_x": NUM3(), "object_y": NUM3(),
                "object_angle": num(-360, 360, 1, "deg", 3), "turn_about": enum("The Object", "A Fixed Centre"), "center_x": NUM3(), "center_y": NUM3()})
def single_point_alignment(t, ctx):
    tp, op = _pt(t, ctx, "Target", "target_x", "target_y"), _pt(t, ctx, "Object", "object_x", "object_y")
    if tp is None or op is None:
        return err("both the target and the object need a position")
    ta, oa = _ang(t, ctx, "Target_Angle", "target_angle"), _ang(t, ctx, "Object_Angle", "object_angle")
    turn = wrap180(ta - oa)
    if str(t.get_param("turn_about")).startswith("A Fixed"):
        c = t.as_point(ctx.get("Center")) if str(t.get_param("input_mode")) == "By Point" and ctx.get("Center") is not None else (_num(t, "center_x"), _num(t, "center_y"))
    else:
        c = op
    moved = np.array(c) + rot(turn) @ (np.array(op) - np.array(c))
    d = np.array(tp) - moved
    return ok(f"move ({d[0]:.4f}, {d[1]:.4f}), turn {turn:.3f} deg", [g.cross_overlay(*op, (0, 255, 255), 6), g.cross_overlay(*tp, (0, 255, 0), 6)],
              Delta_X=float(d[0]), Delta_Y=float(d[1]), Delta_Angle=turn, Move=[float(d[0]), float(d[1]), turn], Aligned_Point=tp)


# ---------------------------------------------------------------------------------------------------------------------------
# Single Point Grasp / Rectification / Mapping Alignment
# ---------------------------------------------------------------------------------------------------------------------------
SP_PORTS = [val("Status", "1 when worked out"), val("Relative_X"), val("Relative_Y"), val("Relative_R", "Relative turn (deg)"),
            val("Absolute_X"), val("Absolute_Y"), val("Absolute_R"), port("Relative", "any", "[x, y, r]"), port("Absolute", "any", "[x, y, r]")]
SP_PARAMS = {"input_mode": "By Coordinate", "calibration_file": "", "ref_x": 320.0, "ref_y": 240.0, "ref_angle": 0.0, "create_reference": False, "run_x": 330.0, "run_y": 250.0,
             "run_angle": 3.0, "demo_x": 0.0, "demo_y": 0.0, "demo_angle": 0.0, "reference_set": False}
SP_SCHEMA = {"input_mode": enum(*MODES), "calibration_file": CAL_FILE, "ref_x": NUM3("px"), "ref_y": NUM3("px"), "ref_angle": num(-360, 360, 1, "deg", 3), "create_reference": {"kind": "bool"}, "reference_set": {"kind": "bool"},
             "run_x": NUM3("px"), "run_y": NUM3("px"), "run_angle": num(-360, 360, 1, "deg", 3), "demo_x": NUM3("mm"), "demo_y": NUM3("mm"),
             "demo_angle": num(-360, 360, 1, "deg", 3)}
SP_INPUTS = [port("Reference", "pt", "Reference point in the picture"), port("Reference_Angle", "val"), port("Run", "pt", "Running point in the picture"), port("Run_Angle", "val"),
             port("Calibration", "dict", "Image to physical calibration"), port("Demo_Pose", "any", "Robot pose [x, y, r] when the part was at the reference"),
             port("Set_Reference", "bool", "Take this picture's point as the reference"), port("Refresh", "val", "Reload the calibration file when not 0")]


def _single_point(t, ctx, mode: str):
    cal, m, bad = _cal(t, ctx)
    if bad:
        return bad
    by_point = str(t.get_param("input_mode")) == "By Point"
    run = _pt(t, ctx, "Run", "run_x", "run_y")
    if run is None:
        return err("no running point: connect one, or type its coordinates")
    run_a = _ang(t, ctx, "Run_Angle", "run_angle")
    if bool(t.get_param("create_reference")) or ctx.get("Set_Reference"):                  # "Create Reference Point": remember this picture's point
        t.set_param("ref_x", run[0])
        t.set_param("ref_y", run[1])
        t.set_param("ref_angle", run_a)
        t.set_param("create_reference", False)
        t.set_param("reference_set", True)
        ref, ref_a = run, run_a
    else:
        ref = _pt(t, ctx, "Reference", "ref_x", "ref_y")
        ref_a = _ang(t, ctx, "Reference_Angle", "ref_angle")
        if ref is None and bool(t.get_param("reference_set")):                           # nothing connected: use the one created earlier
            ref, ref_a = (_num(t, "ref_x"), _num(t, "ref_y")), _num(t, "ref_angle")
        if ref is None:
            return err("no reference point: connect one, or create it from a picture with Create Reference Point")
    pose = ctx.get("Demo_Pose")
    if pose is not None:
        try:
            demo = [float(v) for v in list(pose)[:3]] + [0.0] * (3 - len(list(pose)[:3]))
        except (TypeError, ValueError):
            return err("the demonstration pose must be [x, y, r]")
    else:
        demo = [_num(t, "demo_x"), _num(t, "demo_y"), _num(t, "demo_angle")]
    shift = (_num(t, "run_capture_x") - _num(t, "capture_x"), _num(t, "run_capture_y") - _num(t, "capture_y")) if mode == "grasp" else (0.0, 0.0)
    extra_turn = _num(t, "rotation_capture_angle") if mode == "grasp" and bool(t.get_param("enable_rotation_capture")) else 0.0
    return _sp_compute(cal, m, ref, ref_a, run, run_a, demo, mode, shift, extra_turn)


def _sp_compute(cal, m, ref, ref_a, run, run_a, demo, mode, shift=(0.0, 0.0), extra_turn=0.0):
    pr = apply_matrix(m, np.array([ref]))[0]
    pn = apply_matrix(m, np.array([run]))[0] + np.array(shift)
    ar, an = map_angle(m, ref, ref_a), map_angle(m, run, run_a)
    centre = np.array(cal["rotation_center_world"]) if cal.get("rotation_center_world") else pr
    if mode == "grasp":                                                                     # turn the tool to the part, then move it onto the part
        turn = wrap180(an - ar + extra_turn)
        tip = centre + rot(turn) @ (pr - centre)
        rel = pn - tip
    else:                                                                                   # turn the part back to the reference, then move it there
        turn = wrap180(ar - an)
        moved = centre + rot(turn) @ (pn - centre)
        rel = pr - moved
    ab = (demo[0] + rel[0], demo[1] + rel[1], wrap180(demo[2] + turn))
    over = [g.cross_overlay(*ref, (0, 255, 0), 6), g.cross_overlay(*run, (0, 255, 255), 6),
            {"type": "line", "pt1": (int(ref[0]), int(ref[1])), "pt2": (int(run[0]), int(run[1])), "color": (255, 180, 0), "thickness": 1}]
    return ok(f"relative ({rel[0]:.4f}, {rel[1]:.4f}, {turn:.3f}); absolute ({ab[0]:.4f}, {ab[1]:.4f}, {ab[2]:.3f})", over, Status=1, Relative_X=float(rel[0]),
              Relative_Y=float(rel[1]), Relative_R=turn, Absolute_X=float(ab[0]), Absolute_Y=float(ab[1]), Absolute_R=ab[2], Relative=[float(rel[0]), float(rel[1]), turn],
              Absolute=[float(ab[0]), float(ab[1]), ab[2]])


@define("Single Point Grasp", CAT,
        "Works out where a grasping tool must go to pick up a part: from the part's reference position (where the tool picked it in the "
        "demonstration) and where it is now, in the picture, it gives the move relative to the demonstration and the absolute robot position. "
        "Takes a calibration; if the calibration holds a rotation centre the move allows for the tool turning about it. Press Create Reference "
        "Point (or send Set_Reference) in the demonstration run.",
        inputs=SP_INPUTS, outputs=SP_PORTS,
        params={**SP_PARAMS, "capture_x": 0.0, "capture_y": 0.0, "run_capture_x": 0.0, "run_capture_y": 0.0, "enable_rotation_capture": False, "rotation_capture_angle": 0.0},
        schema={**SP_SCHEMA, "capture_x": NUM3("mm"), "capture_y": NUM3("mm"), "run_capture_x": NUM3("mm"), "run_capture_y": NUM3("mm"),
                "enable_rotation_capture": {"kind": "bool"}, "rotation_capture_angle": num(-360, 360, 1, "deg", 3)})
def single_point_grasp(t, ctx):
    return _single_point(t, ctx, "grasp")


@define("Single Point Rectification", CAT,
        "Works out how to move a part so it sits where it did in the demonstration: from its reference position and its position now in the "
        "picture it gives the shift and turn to apply (relative), and with the demonstration pose added, the absolute robot position.",
        inputs=SP_INPUTS, outputs=SP_PORTS, params=dict(SP_PARAMS), schema=dict(SP_SCHEMA))
def single_point_rectification(t, ctx):
    return _single_point(t, ctx, "rectify")


@define("Single Point Mapping Alignment", CAT,
        "Aligns a part seen by one camera to a target seen by another: the target's picture point is carried into the part camera's picture "
        "with a Mapping Calibration, then the move that brings the part onto it is worked out like Single Point Rectification.",
        inputs=[port("Target", "pt", "Target point in the target camera's picture"), port("Target_Angle", "val"), port("Object", "pt", "Object point in the object camera's picture"),
                port("Object_Angle", "val"), port("Mapping", "dict", "Mapping Calibration: target camera picture -> object camera picture"),
                port("Calibration", "dict", "Object camera's image to physical calibration"), port("Demo_Pose", "any", "Robot pose [x, y, r] in the demonstration"),
                port("Refresh", "val")],
        outputs=SP_PORTS,
        params={"input_mode": "By Coordinate", "calibration_file": "", "target_x": 320.0, "target_y": 240.0, "target_angle": 0.0, "object_x": 330.0, "object_y": 250.0,
                "object_angle": 3.0, "mapping_file": "", "demo_x": 0.0, "demo_y": 0.0, "demo_angle": 0.0},
        schema={"input_mode": enum(*MODES), "calibration_file": CAL_FILE, "target_x": NUM3("px"), "target_y": NUM3("px"), "target_angle": num(-360, 360, 1, "deg", 3),
                "object_x": NUM3("px"), "object_y": NUM3("px"), "object_angle": num(-360, 360, 1, "deg", 3), "mapping_file": CAL_FILE, "demo_x": NUM3("mm"),
                "demo_y": NUM3("mm"), "demo_angle": num(-360, 360, 1, "deg", 3)})
def single_point_mapping_alignment(t, ctx):
    mp, why = calibration_for(t, ctx, "Mapping", "mapping_file")
    if mp is None:
        return err("no mapping: " + why)
    cal, m, bad = _cal(t, ctx)
    if bad:
        return bad
    mm = calibration_matrix(mp)
    tgt, obj = _pt(t, ctx, "Target", "target_x", "target_y"), _pt(t, ctx, "Object", "object_x", "object_y")
    if tgt is None or obj is None:
        return err("both the target and the object need a position")
    ta, oa = _ang(t, ctx, "Target_Angle", "target_angle"), _ang(t, ctx, "Object_Angle", "object_angle")
    ref = apply_matrix(mm, np.array([tgt]))[0]
    pose = ctx.get("Demo_Pose")
    try:
        demo = [float(v) for v in list(pose)[:3]] if pose is not None else [_num(t, "demo_x"), _num(t, "demo_y"), _num(t, "demo_angle")]
        demo += [0.0] * (3 - len(demo))
    except (TypeError, ValueError):
        return err("the demonstration pose must be [x, y, r]")
    return _sp_compute(cal, m, (float(ref[0]), float(ref[1])), map_angle(mm, tgt, ta), obj, oa, demo, "rectify")


# ---------------------------------------------------------------------------------------------------------------------------
# Point Set Alignment
# ---------------------------------------------------------------------------------------------------------------------------
def rigid_fit(obj: np.ndarray, tgt: np.ndarray) -> Tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    """Turn (deg) and shift that carry ``obj`` onto ``tgt``: tgt ~ R (obj - c) + c + d with c the centroid of obj. Returns (turn, d, c, residuals)."""
    co, ct = obj.mean(axis=0), tgt.mean(axis=0)
    h = (obj - co).T @ (tgt - ct)
    u, _, vt = np.linalg.svd(h)
    dd = np.diag([1.0, np.sign(np.linalg.det(vt.T @ u.T)) or 1.0])
    r = vt.T @ dd @ u.T
    turn = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    d = ct - co
    res = np.hypot(*(((obj - co) @ r.T + ct) - tgt).T)
    return turn, d, co, res


@define("Point Set Alignment", CAT,
        "Works out the move that brings a set of object points onto the matching target points (2 or more pairs, in the same order): the "
        "turn about the object points' centre and the shift of that centre, plus how well they fit afterwards. Use physical coordinates.",
        inputs=[port("Target_Points", "any", "[[x, y], ...]"), port("Object_Points", "any", "[[x, y], ...] in the same order")],
        outputs=MOVE_PORTS + [val("Error", "Mean distance left between the points after the move"), port("Center", "pt", "Centre of the object points"),
                              port("Matrix", "any", "3 x 3 matrix that carries the object points onto the target")],
        params={"input_mode": "By Coordinate", "target_points": [[100, 100], [200, 100], [200, 200]], "object_points": [[104, 98], [204, 99], [205, 199]]},
        schema={"input_mode": enum("By Point", "By Coordinate"), "target_points": {"kind": "points"}, "object_points": {"kind": "points"}})
def point_set_alignment(t, ctx):
    ported = str(t.get_param("input_mode")) == "By Point"
    tgt = as_points(ctx.get("Target_Points") if ported else t.get_param("target_points"))
    obj = as_points(ctx.get("Object_Points") if ported else t.get_param("object_points"))
    if tgt is None or obj is None:
        return err("both point sets are needed: connect them, or type the points")
    if len(tgt) != len(obj):
        return err(f"the sets must pair up: {len(obj)} object points but {len(tgt)} target points")
    if len(tgt) < 2:
        return err("at least 2 pairs of points are needed")
    turn, d, co, res = rigid_fit(obj, tgt)
    r = rot(turn)
    mat = np.eye(3)
    mat[:2, :2] = r
    mat[:2, 2] = (tgt.mean(axis=0) - r @ co)
    over = [g.cross_overlay(x, y, (0, 255, 255), 5) for x, y in obj] + [g.cross_overlay(x, y, (0, 255, 0), 5) for x, y in tgt]
    return ok(f"move ({d[0]:.4f}, {d[1]:.4f}), turn {turn:.3f} deg, {float(res.mean()):.4f} left over", over, Delta_X=float(d[0]), Delta_Y=float(d[1]), Delta_Angle=turn,
              Move=[float(d[0]), float(d[1]), turn], Error=float(res.mean()), Center=(float(co[0]), float(co[1])), Matrix=mat.tolist())


# ---------------------------------------------------------------------------------------------------------------------------
# Line Alignment
# ---------------------------------------------------------------------------------------------------------------------------
def _lines(v) -> Optional[np.ndarray]:
    if v is None:
        return None
    out = []
    try:
        for l in v:
            if isinstance(l, dict):
                out.append([float(l["x1"]), float(l["y1"]), float(l["x2"]), float(l["y2"])])
            else:
                a = [float(x) for x in l]
                if len(a) < 4:
                    return None
                out.append(a[:4])
    except (TypeError, ValueError, KeyError):
        return None
    a = np.array(out, float)
    if a.ndim != 2 or a.shape[0] == 0 or not np.all(np.isfinite(a)):
        return None
    return a


def _align_lines(obj: np.ndarray, tgt: np.ndarray):
    """Turn (deg) then shift d (about the object's centroid) that bring each object line onto its target line."""
    dirs_o = np.arctan2(obj[:, 3] - obj[:, 1], obj[:, 2] - obj[:, 0])
    dirs_t = np.arctan2(tgt[:, 3] - tgt[:, 1], tgt[:, 2] - tgt[:, 0])
    wlen = np.hypot(obj[:, 2] - obj[:, 0], obj[:, 3] - obj[:, 1]) + 1e-12
    diff = dirs_t - dirs_o
    theta = math.atan2(float((wlen * np.sin(diff)).sum()), float((wlen * np.cos(diff)).sum()))
    r = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    ends = np.vstack([obj[:, :2], obj[:, 2:]])
    c = ends.mean(axis=0)
    rows, rhs = [], []
    for i in range(len(obj)):
        dx, dy = tgt[i, 2] - tgt[i, 0], tgt[i, 3] - tgt[i, 1]
        n = np.array([-dy, dx]) / (math.hypot(dx, dy) + 1e-12)
        k = n @ tgt[i, :2]
        for q in (obj[i, :2], obj[i, 2:]):
            rows.append(n)
            rhs.append(k - n @ (r @ (q - c) + c))
    d, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    resid = []
    for i in range(len(obj)):
        dx, dy = tgt[i, 2] - tgt[i, 0], tgt[i, 3] - tgt[i, 1]
        n = np.array([-dy, dx]) / (math.hypot(dx, dy) + 1e-12)
        for q in (obj[i, :2], obj[i, 2:]):
            resid.append(abs(n @ (r @ (q - c) + c + d) - n @ tgt[i, :2]))
    return math.degrees(theta), d, c, float(np.mean(resid))


@define("Line Alignment", CAT,
        "Works out the move that brings a set of object lines onto the matching target lines (in the same order): the turn from the lines' "
        "directions and the shift that puts each object line on its target. For a closed outline the lines may start at any of its sides. "
        "Use physical coordinates.",
        inputs=[port("Target_Lines", "any", "[[x1, y1, x2, y2], ...]"), port("Object_Lines", "any", "Lines in the same order")],
        outputs=MOVE_PORTS + [val("Error", "Mean distance left from the lines after the move"), port("Center", "pt", "Centre of the object lines' end points"), val("Shift", "Sides the closed outline was turned by")],
        params={"input_mode": "By Coordinate", "alignment_shape": "Open", "target_lines": [[100, 100, 300, 100], [300, 100, 300, 250]],
                "object_lines": [[102, 104, 302, 107], [301, 105, 298, 255]]},
        schema={"input_mode": enum("By Point", "By Coordinate"), "alignment_shape": enum("Open", "Closed"), "target_lines": {"kind": "json"}, "object_lines": {"kind": "json"}})
def line_alignment(t, ctx):
    ported = str(t.get_param("input_mode")) == "By Point"
    tgt = _lines(ctx.get("Target_Lines") if ported else t.get_param("target_lines"))
    obj = _lines(ctx.get("Object_Lines") if ported else t.get_param("object_lines"))
    if tgt is None or obj is None:
        return err("both line sets are needed: connect them, or type the lines as [[x1, y1, x2, y2], ...]")
    if len(tgt) != len(obj):
        return err(f"the sets must pair up: {len(obj)} object lines but {len(tgt)} target lines")
    if np.any(np.hypot(tgt[:, 2] - tgt[:, 0], tgt[:, 3] - tgt[:, 1]) < 1e-9) or np.any(np.hypot(obj[:, 2] - obj[:, 0], obj[:, 3] - obj[:, 1]) < 1e-9):
        return err("a line has no length")
    best = None
    shifts = range(len(obj)) if str(t.get_param("alignment_shape")) == "Closed" else [0]
    for s in shifts:
        o = np.roll(obj, -s, axis=0)
        theta, d, c, e = _align_lines(o, tgt)
        score = e + 1e-4 * abs(theta)                                                     # equally good fits (a symmetric outline): take the smaller turn
        if best is None or score < best[0]:
            best = (score, e, theta, d, c, s)
    _, e, theta, d, c, s = best
    over = [g.line_overlay(g.line_to_dict(*l), (0, 255, 0)) for l in tgt] + [g.line_overlay(g.line_to_dict(*l), (0, 255, 255)) for l in obj]
    return ok(f"move ({d[0]:.4f}, {d[1]:.4f}), turn {theta:.3f} deg, {e:.4f} left over", over, Delta_X=float(d[0]), Delta_Y=float(d[1]), Delta_Angle=theta,
              Move=[float(d[0]), float(d[1]), theta], Error=e, Center=(float(c[0]), float(c[1])), Shift=int(s))
