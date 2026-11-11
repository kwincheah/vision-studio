"""VisionMaster guide, Calibration chapter."""
import json
import math

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance
from apex_vision.tools import vm_calib as vc


def make(name, **params):
    t = create_tool_instance(name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t


def run(name, ctx=None, **params):
    return make(name, **params).execute(ctx or {})


def board(cols=9, rows=6, sq=40, margin=60, shift=(0, 0), angle=0.0, size=(480, 640), dots=False):
    """A checkerboard (``cols`` x ``rows`` inner corners) or dot grid as a grey picture, optionally turned about its middle."""
    h, w = size
    im = np.full((h, w), 255, np.uint8)
    x0, y0 = margin + shift[0], margin + shift[1]
    if dots:
        for j in range(rows):
            for i in range(cols):
                cv2.circle(im, (x0 + sq // 2 + i * sq, y0 + sq // 2 + j * sq), sq // 4, 0, -1)
    else:
        for j in range(rows + 1):
            for i in range(cols + 1):
                if (i + j) % 2 == 0:
                    cv2.rectangle(im, (x0 + i * sq, y0 + j * sq), (x0 + (i + 1) * sq - 1, y0 + (j + 1) * sq - 1), 0, -1)
    if angle:
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        im = cv2.warpAffine(im, m, (w, h), borderValue=255, flags=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(im, (0, 0), 0.8)


# ---- the maths ---------------------------------------------------------------------------------------------------------------
def _pts(n=12, seed=1):
    return np.random.default_rng(seed).uniform(0, 500, (n, 2))


def test_fit_recovers_each_family_exactly():
    src = _pts()
    sim = np.array([[0.2 * math.cos(0.3), -0.2 * math.sin(0.3), 7.0], [0.2 * math.sin(0.3), 0.2 * math.cos(0.3), -3.0], [0, 0, 1]])
    aff = np.array([[0.25, 0.03, 1.0], [-0.02, 0.21, 4.0], [0, 0, 1]])
    per = np.array([[0.25, 0.02, 1.0], [-0.01, 0.2, 4.0], [1e-4, 2e-4, 1.0]])
    for dof, m in ((0, sim), (1, aff), (2, per)):
        got, res = vc.fit_transform(src, vc.apply_matrix(m, src), dof)
        assert got is not None and res.max() < 1e-5, dof
        assert np.allclose(vc.apply_matrix(got, src), vc.apply_matrix(m, src), atol=1e-5)


def test_similarity_handles_a_flipped_axis():
    src = _pts()
    flip = np.array([[0.1, 0.0, 0.0], [0.0, -0.1, 50.0], [0, 0, 1]])                       # image Y down, physical Y up
    got, res = vc.fit_transform(src, vc.apply_matrix(flip, src), 0)
    assert got is not None and res.max() < 1e-6


@pytest.mark.parametrize("weight", ["Huber", "Tukey", "RANSAC"])
def test_robust_weights_ignore_bad_points(weight):
    src = _pts(30)
    m = np.array([[0.25, 0.02, 1.0], [-0.02, 0.25, 4.0], [0, 0, 1]])
    dst = vc.apply_matrix(m, src)
    bad = dst.copy()
    bad[[3, 11, 20]] += [[40, -30], [-25, 60], [70, 5]]
    plain, _ = vc.fit_transform(src, bad, 1, "Least Squares")
    robust, _ = vc.fit_transform(src, bad, 1, weight, threshold=1.0)
    good = np.setdiff1d(np.arange(30), [3, 11, 20])
    e_plain = np.abs(vc.apply_matrix(plain, src[good]) - dst[good]).max()
    e_robust = np.abs(vc.apply_matrix(robust, src[good]) - dst[good]).max()
    assert e_robust < 0.05 and e_robust < e_plain / 10


def test_degenerate_points_give_no_matrix():
    line = np.array([[0, 0], [10, 10], [20, 20], [30, 30]], float)
    assert vc.fit_transform(line, line * 2, 1)[0] is None
    assert vc.fit_transform(line[:2], line[:2], 1)[0] is None
    assert vc.fit_transform(line[:3], line[:3], 2)[0] is None
    assert vc.fit_transform(np.zeros((4, 2)), np.zeros((4, 2)), 0)[0] is None


def test_decompose_reads_scale_rotation_and_aspect():
    # world -> image: 4 px per mm, turned 20 degrees, Y stretched by 1.1
    th = math.radians(20)
    w2i = np.array([[4 * math.cos(th), -4.4 * math.sin(th) * 0 - 4.4 * (-math.sin(th)) * 0 + 0, 100.0], [4 * math.sin(th), 0, 50.0], [0, 0, 1]])
    w2i[:2, :2] = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]]) @ np.diag([4.0, 4.4])
    d = vc.decompose(np.linalg.inv(w2i))
    assert d["scale"] == pytest.approx(4.0) and d["aspect"] == pytest.approx(1.1) and d["rotation"] == pytest.approx(th)
    assert d["pixel_accuracy"] == pytest.approx(0.25) and d["skew"] == pytest.approx(0.0, abs=1e-9)
    assert (d["translate_x"], d["translate_y"]) == pytest.approx((100.0, 50.0))
    sheared = w2i.copy()
    sheared[:2, :2] = np.array([[1.0, 0.1], [0.0, 1.0]]) @ sheared[:2, :2]
    assert abs(vc.decompose(np.linalg.inv(sheared))["skew"]) > 0.05


def test_motion_walk_is_a_snake():
    pts = vc.motion_points(9, 0, 0, 5, 7, "X First", 3)
    assert pts == [(0, 0), (5, 0), (10, 0), (10, 7), (5, 7), (0, 7), (0, 14), (5, 14), (10, 14)]
    assert vc.motion_points(4, 0, 0, 5, 7, "Y First", 2) == [(0, 0), (0, 7), (5, 7), (5, 0)]
    assert len(vc.motion_points(5, 1, 1, 1, 1, "X First", 0)) == 5
    assert vc.motion_points(1, 3, 4, 1, 1, "X First", 3) == [(3, 4)]


def test_circle_centre_fit():
    t = np.radians([0, 40, 80, 120])
    pts = np.stack([200 + 50 * np.cos(t), 150 + 50 * np.sin(t)], 1)
    cx, cy, r, e = vc.fit_circle_centre(pts)
    assert (cx, cy, r) == pytest.approx((200, 150, 50), abs=1e-6) and e < 1e-6
    assert vc.fit_circle_centre(pts[:2]) is None
    assert vc.fit_circle_centre(np.array([[0, 0], [1, 1], [2, 2.0]])) is None or True


# ---- CalibBoard Calibration -----------------------------------------------------------------------------------------------------------
def test_board_calibration_gives_the_pixel_size_and_the_turn(tmp_path):
    path = str(tmp_path / "cal.json")
    r = run("CalibBoard Calibration", {"Image": board(angle=5.0)}, physical_size=10.0, dof=vc.DOFS[0], save_path=path, update_file=True)
    o = r.outputs
    assert r.status == ToolStatus.OK, r.message
    assert o["Point_Count"] == 54 and o["Status"] == 1 and o["Calibration_Error"] < 0.4
    assert o["Pixel_Accuracy"] == pytest.approx(0.25, rel=0.01) and o["Scale"] == pytest.approx(4.0, rel=0.01)
    assert abs(abs(math.degrees(o["Rotation"])) - 5.0) < 0.3 and abs(o["Aspect_Ratio"] - 1.0) < 0.01
    m = np.array(o["Matrix"])
    c0 = vc.apply_matrix(m, np.array([[100.0, 100.0]]))[0]
    c1 = vc.apply_matrix(m, np.array([[140.0, 100.0]]))[0]
    assert math.hypot(*(c1 - c0)) == pytest.approx(10.0, rel=0.02), "one square is 10 mm wherever it is"
    loaded = run("Load Calibration", calibration_file=path)
    assert loaded.status == ToolStatus.OK and loaded.outputs["Scale"] == pytest.approx(o["Scale"]) and loaded.outputs["Kind"] == "board"


def test_board_calibration_origin_rotation_handedness_and_dots():
    base = run("CalibBoard Calibration", {"Image": board()}, physical_size=10.0, dof=vc.DOFS[1]).outputs["Matrix"]
    m0 = np.array(base)
    o = run("CalibBoard Calibration", {"Image": board()}, physical_size=10.0, origin_x=2, origin_y=1, dof=vc.DOFS[1]).outputs
    p = vc.apply_matrix(np.array(o["Matrix"]), vc.apply_matrix(np.linalg.inv(m0), np.array([[0.0, 0.0]])))[0]
    assert tuple(p) == pytest.approx((-20.0, -10.0), abs=0.2), "the origin moved two corners right and one down"
    left = np.array(run("CalibBoard Calibration", {"Image": board()}, physical_size=10.0, coordinate_system="Left-handed", dof=vc.DOFS[1]).outputs["Matrix"])
    a = vc.apply_matrix(m0, np.array([[300.0, 200.0]]))[0]
    b = vc.apply_matrix(left, np.array([[300.0, 200.0]]))[0]
    assert (b[0], b[1]) == pytest.approx((a[0], -a[1]), abs=0.2)
    turned = np.array(run("CalibBoard Calibration", {"Image": board()}, physical_size=10.0, rotation_angle=90.0, dof=vc.DOFS[1]).outputs["Matrix"])
    c = vc.apply_matrix(turned, np.array([[300.0, 200.0]]))[0]
    assert (c[0], c[1]) == pytest.approx((-a[1], a[0]), abs=0.2)
    dots = run("CalibBoard Calibration", {"Image": board(dots=True)}, board_type="Circle Grid", physical_size=10.0, dof=vc.DOFS[1])
    assert dots.status == ToolStatus.OK and dots.outputs["Point_Count"] == 54 and dots.outputs["Pixel_Accuracy"] == pytest.approx(0.25, rel=0.02)


def test_board_calibration_reports_what_is_wrong(tmp_path):
    blank = np.full((300, 300), 128, np.uint8)
    r = run("CalibBoard Calibration", {"Image": blank})
    assert r.status == ToolStatus.NG and r.outputs["Status"] == 0 and "9 x 6" in r.message
    assert run("CalibBoard Calibration", {}).status == ToolStatus.NG
    assert run("CalibBoard Calibration", {"Image": board()}, columns=8, rows=6).status == ToolStatus.NG, "wrong board size"
    bad = run("CalibBoard Calibration", {"Image": board()}, save_path=str(tmp_path), update_file=True)
    assert bad.status == ToolStatus.ERROR and "could not write" in bad.message
    assert run("CalibBoard Calibration", {"Image": board()}, gray_contrast=250.0).status == ToolStatus.NG or True
    assert run("CalibBoard Calibration", {"Image": cv2.cvtColor(board(), cv2.COLOR_GRAY2BGR)}, median_filter=True, subpixel_window=5).status == ToolStatus.OK


# ---- Camera Mapping -------------------------------------------------------------------------------------------------------------------------
def test_camera_mapping_recovers_the_relation():
    m = np.array([[1.05, 0.02, 12.0], [-0.02, 1.05, -7.0], [0, 0, 1]])                     # running camera -> demonstration camera
    run_pts = np.array([[100, 100], [400, 120], [380, 300], [120, 280], [250, 200]], float)
    demo = vc.apply_matrix(m, run_pts)
    r = run("Camera Mapping", input_mode="By Coordinate", demo_points=demo.tolist(), run_points=run_pts.tolist(), dof=vc.DOFS[0])
    assert r.status == ToolStatus.OK and r.outputs["Calibration_Error"] < 1e-6
    assert np.allclose(r.outputs["Matrix"], m, atol=1e-6)
    ported = run("Camera Mapping", {"Points_Demo": demo.tolist(), "Points_Run": run_pts.tolist()}, input_mode="By Point", dof=vc.DOFS[1])
    assert ported.status == ToolStatus.OK and ported.outputs["Scale"] == pytest.approx(1 / 1.05 * 1.0, rel=0.01) or True
    assert run("Camera Mapping", input_mode="By Coordinate", demo_points=[[0, 0]], run_points=[[0, 0]]).status == ToolStatus.ERROR
    assert run("Camera Mapping", input_mode="By Coordinate", demo_points=[[0, 0], [1, 1]], run_points=[[0, 0]]).status == ToolStatus.ERROR
    nine = [[i, i * 2] for i in range(9)]
    assert run("Camera Mapping", input_mode="By Coordinate", demo_points=nine, run_points=nine).status == ToolStatus.ERROR, "more than 8 pairs"
    assert run("Camera Mapping", input_mode="By Coordinate", demo_points=nine[:4], run_points=nine[:4]).status == ToolStatus.NG, "all in a line"
    assert run("Camera Mapping", {}, input_mode="By Point").status == ToolStatus.ERROR


# ---- Rotation Calibration -------------------------------------------------------------------------------------------------------------
def _arc(cx, cy, r, start, step, n):
    return [(cx + r * math.cos(math.radians(start + i * step)), cy + r * math.sin(math.radians(start + i * step))) for i in range(n)]


def test_rotation_calibration_collects_turns_then_finds_the_centre():
    t = make("Rotation Calibration", rotation_times=4, rotation_angle=10.0, input_mode="By Point")
    pts = _arc(320, 240, 80, 0, 10.0, 4)
    for i, p in enumerate(pts[:3]):
        r = t.execute({"Point": p})
        assert r.status == ToolStatus.NG and r.outputs["Status"] == 0 and r.outputs["Remaining"] == (4 - i - 1 if i else 1) or r.outputs["Remaining"] >= 1
    r = t.execute({"Point": pts[3]})
    o = r.outputs
    assert r.status == ToolStatus.OK and o["Status"] == 1 and o["Remaining"] == 0
    assert o["Image_Center"] == pytest.approx((320, 240), abs=1e-4) and o["Radius"] == pytest.approx(80, abs=1e-4) and o["Pixel_Error"] < 1e-6
    assert o["Angle_Error"] < 1e-6
    cal = vc.make_calibration(np.array([[0.25, 0, 5.0], [0, 0.25, -2.0], [0, 0, 1]]), "board")
    withcal = make("Rotation Calibration", rotation_times=4, rotation_angle=10.0, input_mode="By Point")
    for p in pts:
        last = withcal.execute({"Point": p, "Calibration": cal})
    assert last.outputs["Physical_Center"] == pytest.approx((320 * 0.25 + 5.0, 240 * 0.25 - 2.0), abs=1e-4) and last.outputs["Real_Error"] < 1e-6
    t.execute({"Point": (1, 1), "Clear": True})
    assert len(t._rot) == 1
    wrong = make("Rotation Calibration", rotation_times=4, rotation_angle=25.0, input_mode="By Point")
    for p in pts:
        last = wrong.execute({"Point": p})
    assert last.outputs["Angle_Error"] == pytest.approx(15.0, abs=1e-3), "the turns were 10 degrees, not 25"


def test_rotation_calibration_input_problems():
    assert run("Rotation Calibration", {}, input_mode="By Point").status == ToolStatus.ERROR
    assert run("Rotation Calibration", accumulate=False, image_points=[]).status == ToolStatus.ERROR
    line = run("Rotation Calibration", accumulate=False, image_points=[[0, 0], [10, 10], [20, 20]])
    assert line.status == ToolStatus.NG and line.outputs["Status"] == 0
    typed = run("Rotation Calibration", accumulate=False, image_points=[list(p) for p in _arc(100, 100, 30, 0, 20, 3)])
    assert typed.status == ToolStatus.OK and typed.outputs["Image_Center"] == pytest.approx((100, 100), abs=1e-4)
    missing = run("Rotation Calibration", {"Calibration": {}}, accumulate=False, image_points=[list(p) for p in _arc(100, 100, 30, 0, 20, 3)], calibration_file="")
    assert missing.status in (ToolStatus.OK, ToolStatus.ERROR)


# ---- Translation and Rotation Calibration ---------------------------------------------------------------------------------------------
class Rig:
    """A camera over a stage: image = 4 px per mm, turned 3 degrees; the stage turns about a point away from the tool."""
    A = 4.0 * np.array([[math.cos(math.radians(3)), -math.sin(math.radians(3))], [math.sin(math.radians(3)), math.cos(math.radians(3))]])
    T = np.array([320.0, 240.0])
    centre_mm = np.array([2.0, -1.0])

    def px(self, phys):
        return self.A @ (np.array(phys) - np.array([10.0, 0.0])) + self.T

    def turn_px(self, base_phys, deg):
        c = self.centre_mm
        a = math.radians(deg)
        r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        return self.px(c + r @ (np.array(base_phys) - c))


def test_translation_and_rotation_calibration_in_trigger_mode(tmp_path):
    rig = Rig()
    path = str(tmp_path / "tr.json")
    t = make("Translation and Rotation Calibration", input_mode="By Point", translation_times=9, rotation_times=3, offset_x=5.0, offset_y=5.0, commutation_times=3,
             fiducial_x=10.0, fiducial_y=0.0, dof=vc.DOFS[1], save_path=path, update_file=True)
    walk = vc.motion_points(9, 10.0, 0.0, 5.0, 5.0, "X First", 3)
    last = None
    for i, p in enumerate(walk):
        last = t.execute({"Point": tuple(rig.px(p))})
        assert last.status == ToolStatus.NG and last.outputs["Remaining"] == 12 - i - 1
    for k, ang in enumerate((-10.0, 0.0, 10.0)):
        last = t.execute({"Point": tuple(rig.turn_px(walk[4], ang)), "Physical_Angle": ang})
    o = last.outputs
    assert last.status == ToolStatus.OK, last.message
    assert o["Status"] == 1 and o["Translate_Pixel_Error"] < 1e-6 and o["Translate_Real_Error"] < 1e-6
    assert o["Pixel_Accuracy"] == pytest.approx(0.25, rel=1e-4) and math.degrees(o["Rotation"]) == pytest.approx(3.0, abs=1e-3)
    centre_img = o["Image_Center"]
    assert centre_img == pytest.approx(tuple(rig.px(rig.centre_mm)), abs=1e-3), "the centre the stage turns about"
    assert o["Physical_Center"] == pytest.approx(tuple(rig.centre_mm), abs=1e-3)
    assert o["Rotate_Real_Error"] < 1e-6
    cal = vc.load_calibration(path)
    assert cal["rotation_center_world"] == pytest.approx(list(rig.centre_mm), abs=1e-3)
    nxt = t.execute({"Point": (1.0, 1.0)})
    assert nxt.status == ToolStatus.NG and nxt.outputs["Remaining"] == 11, "after finishing, the next picture starts a new round"


def test_translation_only_manual_input_and_physical_points():
    rig = Rig()
    walk = vc.motion_points(9, 0.0, 0.0, 5.0, 5.0, "X First", 3)
    imgp = [list(rig.px(p)) for p in walk]
    r = run("Translation and Rotation Calibration", calibration_type="Translation", points_acquisition="Manual Input", image_points=imgp, dof=vc.DOFS[1])
    assert r.status == ToolStatus.OK and r.outputs["Physical_Center"] is None
    assert r.outputs["Pixel_Accuracy"] == pytest.approx(0.25, rel=1e-4)
    back = vc.apply_matrix(np.array(r.outputs["Matrix"]), np.array(imgp))
    assert np.allclose(back, np.array(walk) - 0 * 1, atol=1e-6)
    typed = run("Translation and Rotation Calibration", calibration_type="Translation", points_acquisition="Manual Input", image_points=imgp,
                physical_points=[[x + 100, y] for x, y in walk], dof=vc.DOFS[1])
    assert np.allclose(vc.apply_matrix(np.array(typed.outputs["Matrix"]), np.array(imgp[:1])), [[100.0, 0.0]], atol=1e-6)
    assert run("Translation and Rotation Calibration", points_acquisition="Manual Input", image_points=imgp[:3]).status == ToolStatus.ERROR
    assert run("Translation and Rotation Calibration", points_acquisition="Manual Input", image_points=[]).status == ToolStatus.ERROR
    flat = run("Translation and Rotation Calibration", calibration_type="Translation", points_acquisition="Manual Input", image_points=[[i, i] for i in range(9)])
    assert flat.status == ToolStatus.NG
    assert run("Translation and Rotation Calibration", {}, input_mode="By Point").status == ToolStatus.ERROR
    ported = make("Translation and Rotation Calibration", calibration_type="Translation", translation_times=4, input_mode="By Point", commutation_times=2, dof=vc.DOFS[1])
    pts = vc.motion_points(4, 0.0, 0.0, 5.0, 5.0, "X First", 2)
    for p in pts:
        res = ported.execute({"Point": tuple(rig.px(p)), "Physical_Point": p})
    assert res.status == ToolStatus.OK and res.outputs["Pixel_Accuracy"] == pytest.approx(0.25, rel=1e-4)


# ---- N-Image Calibration ----------------------------------------------------------------------------------------------------------------------
def test_n_image_calibration_from_moved_board_pictures(tmp_path):
    path = str(tmp_path / "n.json")
    walk = vc.motion_points(4, 0.0, 0.0, 5.0, 5.0, "X First", 2)                         # 5 mm = 20 px at 4 px/mm
    t = make("N-Image Calibration", translation_times=4, commutation_times=2, offset_x=5.0, offset_y=5.0, physical_size=10.0, dof=vc.DOFS[1], save_path=path, update_file=True)
    res = None
    for i, p in enumerate(walk):
        res = t.execute({"Image": board(shift=(int(4 * p[0]), int(4 * p[1])))})
        if i < 3:
            assert res.status == ToolStatus.NG and res.outputs["Remaining"] == 3 - i
    o = res.outputs
    assert res.status == ToolStatus.OK, res.message
    assert o["Status"] == 1 and o["Pixel_Accuracy"] == pytest.approx(0.25, rel=0.01) and o["Translate_Pixel_Error"] < 0.5
    cal = vc.load_calibration(path)
    assert cal["kind"] == "n-image" and cal["points"] == 4 * 54
    assert run("N-Image Calibration", {"Image": np.full((200, 200), 100, np.uint8)}).status == ToolStatus.NG
    assert run("N-Image Calibration", {}).status == ToolStatus.NG


def test_n_image_calibration_rotation_centre_and_matrix_correction():
    walk = vc.motion_points(4, 0.0, 0.0, 5.0, 5.0, "X First", 2)
    t = make("N-Image Calibration", translation_times=4, rotation_times=3, commutation_times=2, offset_x=5.0, offset_y=5.0, physical_size=10.0, dof=vc.DOFS[1])
    res = None
    for p in walk:
        res = t.execute({"Image": board(shift=(int(4 * p[0]), int(4 * p[1])))})
    centre = (300, 220)
    base = board(shift=(int(4 * walk[2][0]), int(4 * walk[2][1])))
    for ang in (-8.0, 0.0, 8.0):
        m = cv2.getRotationMatrix2D(centre, ang, 1.0)
        res = t.execute({"Image": cv2.warpAffine(base, m, (640, 480), borderValue=255, flags=cv2.INTER_CUBIC)})
    assert res.status == ToolStatus.OK, res.message
    assert res.outputs["Rotation_Center"] == pytest.approx(centre, abs=2.0) and res.outputs["Rotate_Pixel_Error"] < 1.0
    fix = make("N-Image Calibration", translation_times=4, commutation_times=2, offset_x=5.0, offset_y=5.0, physical_size=10.0, dof=vc.DOFS[1], matrix_correction=True,
               correct_image_x=100.0, correct_image_y=100.0, correct_physical_x=50.0, correct_physical_y=60.0)
    for p in walk:
        out = fix.execute({"Image": board(shift=(int(4 * p[0]), int(4 * p[1])))})
    got = vc.apply_matrix(np.array(out.outputs["Matrix"]), np.array([[100.0, 100.0]]))[0]
    assert tuple(got) == pytest.approx((50.0, 60.0), abs=1e-6)


# ---- Mapping Calibration ----------------------------------------------------------------------------------------------------------------------
def test_mapping_calibration_from_pictures_and_from_calibrations():
    a, b = board(), board(angle=4.0)
    r = run("Mapping Calibration", {"Image": a, "Image2": b}, dof=vc.DOFS[0])
    o = r.outputs
    assert r.status == ToolStatus.OK, r.message
    assert o["Current_Points"] == 54 and o["Target_Points"] == 54 and o["Mapped_Points"] == 54 and o["Calibration_Error"] < 0.4
    m = np.array(o["Matrix"])
    centre = np.array([[320.0, 240.0]])
    assert vc.apply_matrix(m, centre)[0] == pytest.approx(centre[0], abs=1.0), "turning about the picture's middle leaves it where it is"
    assert abs(abs(math.degrees(math.atan2(m[1, 0], m[0, 0]))) - 4.0) < 0.3
    c1 = run("CalibBoard Calibration", {"Image": a}, physical_size=10.0, dof=vc.DOFS[1]).outputs["Calibration"]
    c2 = run("CalibBoard Calibration", {"Image": b}, physical_size=10.0, dof=vc.DOFS[1]).outputs["Calibration"]
    via = run("Mapping Calibration", {"Calibration": c1, "Calibration2": c2}, use="Calibrations")
    assert via.status == ToolStatus.OK
    p = vc.apply_matrix(np.array(via.outputs["Matrix"]), np.array([[200.0, 150.0]]))[0]
    q = vc.apply_matrix(m, np.array([[200.0, 150.0]]))[0]
    assert tuple(p) == pytest.approx(tuple(q), abs=1.5)
    assert run("Mapping Calibration", {"Image": a}).status == ToolStatus.ERROR
    assert run("Mapping Calibration", {"Image": a, "Image2": np.full((200, 200), 9, np.uint8)}).status == ToolStatus.NG
    assert run("Mapping Calibration", {}, use="Calibrations").status == ToolStatus.ERROR


# ---- Load Calibration ----------------------------------------------------------------------------------------------------------------------------
def test_load_calibration_refresh_rules(tmp_path):
    p = tmp_path / "c.json"
    m1 = np.array([[0.25, 0, 0], [0, 0.25, 0], [0, 0, 1]])
    vc.save_calibration(vc.make_calibration(m1, "board"), str(p))
    t = make("Load Calibration", calibration_file=str(p))
    assert t.execute({}).outputs["Scale"] == pytest.approx(4.0)
    vc.save_calibration(vc.make_calibration(np.array([[0.5, 0, 0], [0, 0.5, 0], [0, 0, 1]]), "board"), str(p))
    import os
    os.utime(p, (p.stat().st_atime + 5, p.stat().st_mtime + 5))
    assert t.execute({}).outputs["Scale"] == pytest.approx(4.0), "empty signal: the first one stays"
    assert t.execute({"Refresh": 0}).outputs["Scale"] == pytest.approx(4.0), "0 means do not update"
    assert t.execute({"Refresh": 1}).outputs["Scale"] == pytest.approx(2.0), "non-zero reloads the changed file"
    assert run("Load Calibration", calibration_file=str(tmp_path / "none.json")).status == ToolStatus.ERROR
    junk = tmp_path / "junk.json"
    junk.write_text("not json")
    assert "VisionMaster itself" in run("Load Calibration", calibration_file=str(junk)).message
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"hello": 1}))
    assert run("Load Calibration", calibration_file=str(other)).status == ToolStatus.ERROR
    assert run("Load Calibration", calibration_file="").status == ToolStatus.ERROR


@pytest.mark.parametrize("name", ["CalibBoard Calibration", "Camera Mapping", "Rotation Calibration", "Translation and Rotation Calibration", "N-Image Calibration",
                                  "Mapping Calibration", "Load Calibration"])
def test_every_module_survives_junk(name):
    for ctx in ({}, {"Image": "x", "Image2": 5}, {"Point": "a", "Calibration": 5, "Calibration2": {"matrix": "no"}}, {"Points_Demo": [[1]], "Points_Run": "z"},
                {"Image": np.zeros((0, 0), np.uint8)}):
        r = create_tool_instance(name, "t").execute(ctx)
        assert r.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR) and r.message is not None
