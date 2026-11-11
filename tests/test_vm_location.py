"""VisionMaster guide, Location chapter: the shared edge/fit library and nine modules, each checked on a drawn shape with a known answer."""
import math

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance
from apex_vision.tools import vm_geom as g


def run(name, ctx, **params):
    t = create_tool_instance(name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t, t.execute(ctx)


def canvas(h=300, w=420, bg=200):
    return np.full((h, w), bg, np.uint8)


def soften(im):
    return cv2.GaussianBlur(im, (0, 0), 1.0)


def bgr(im):
    return cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)


# ---- the shared library ---------------------------------------------------------------------------------------------------
def test_caliper_finds_the_edge_to_sub_pixel_accuracy_with_polarity_and_type():
    im = canvas(60, 200, 40)
    im[:, 100:] = 180                                                # dark -> light step at x = 100 (boundary between 99 and 100)
    im = soften(im)
    x, y, strength, sign = g.caliper(im, (10, 30), (190, 30), width=5, polarity="Any", threshold=20, filter_size=3)
    assert abs(x - 99.5) < 0.3 and sign == 1 and 90 < strength < 150
    assert g.caliper(im, (10, 30), (190, 30), polarity="Light to Dark") is None, "wrong polarity: nothing"
    r = g.caliper(im, (190, 30), (10, 30), polarity="Light to Dark")
    assert r is not None and r[3] == -1 and abs(r[0] - 99.5) < 0.6, "travelling the other way the same step reads light-to-dark"
    assert g.caliper(im, (10, 30), (190, 30), threshold=200) is None, "too weak for the threshold"
    two = canvas(60, 200, 40)
    two[:, 60:90] = 120
    two[:, 140:] = 220
    two = soften(two)
    first = g.caliper(two, (5, 30), (195, 30), polarity="Dark to Light", edge_type="First Edge", threshold=20)
    last = g.caliper(two, (5, 30), (195, 30), polarity="Dark to Light", edge_type="Last Edge", threshold=20)
    strongest = g.caliper(two, (5, 30), (195, 30), polarity="Dark to Light", edge_type="Strongest Edge", threshold=20)
    assert abs(first[0] - 59.5) < 1 and abs(last[0] - 139.5) < 1 and abs(strongest[0] - 139.5) < 1, "the last step (+100) is stronger than the first (+80)"
    assert g.caliper(im, (10, 30), (11, 30)) is None, "a strip too short to hold an edge"


def test_robust_line_fits_ignore_outliers_that_least_squares_cannot():
    rng = np.random.default_rng(0)
    xs = np.linspace(0, 200, 40)
    pts = np.column_stack([xs, 0.5 * xs + 10 + rng.normal(0, 0.3, 40)])
    bad = pts.copy()
    bad[[34, 36, 38, 39]] += (0, -30)                                     # four outliers at one end tilt a plain fit
    ls = g.fit_line(bad, "Least Squares")
    hub = g.fit_line(bad, "Huber")
    tuk = g.fit_line(bad, "Tukey")
    err = lambda f: abs(f["angle"] - math.degrees(math.atan(0.5)))                                    # noqa: E731
    assert err(tuk) < 0.5 and err(hub) < err(ls) and err(ls) > 1.0, (err(ls), err(hub), err(tuk))
    assert g.fit_line(bad, "Least Squares", reject=4)["residual"] < ls["residual"] / 3, "reject number drops the worst points"
    assert g.fit_line(bad, "Least Squares", dist=5.0)["inliers"] >= 33, "distance to remove drops points farther than that"
    assert g.fit_line(pts[:1]) is None
    clean = g.fit_line(pts, "Least Squares")
    assert clean["length"] == pytest.approx(math.hypot(200, 100), rel=0.02) and abs(clean["angle"] - 26.565) < 0.3


def test_robust_circle_and_ellipse_fits():
    th = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    pts = np.column_stack([150 + 40 * np.cos(th), 100 + 40 * np.sin(th)])
    bad = pts.copy()
    bad[::15] += 18
    ls, tk = g.fit_circle(bad, "Least Squares"), g.fit_circle(bad, "Tukey")
    assert abs(tk["r"] - 40) < 1.0 and abs(tk["cx"] - 150) < 1.0 and abs(ls["r"] - 40) > abs(tk["r"] - 40)
    assert g.fit_circle(bad, dist=6.0)["inliers"] <= 56 and g.fit_circle(pts[:2]) is None
    ell = np.column_stack([100 + 60 * np.cos(th) * math.cos(0.4) - 30 * np.sin(th) * math.sin(0.4),
                           80 + 60 * np.cos(th) * math.sin(0.4) + 30 * np.sin(th) * math.cos(0.4)])
    f = g.fit_ellipse(ell)
    assert abs(f["a"] - 120) < 1 and abs(f["b"] - 60) < 1 and abs(f["angle"] - math.degrees(0.4)) < 1.5
    noisy = ell.copy()
    noisy[::12] += 25
    assert abs(g.fit_ellipse(noisy, dist=4.0)["a"] - 120) < 6


def test_line_helpers():
    a, b = g.line_to_dict(0, 0, 10, 0), g.line_to_dict(5, -5, 5, 5)
    assert g.intersect(a, b) == pytest.approx((5.0, 0.0)) and g.intersect(a, g.line_to_dict(0, 3, 10, 3)) is None
    assert g.angle_between(a, b) == pytest.approx(90.0) and g.angle_between(a, g.line_to_dict(0, 0, 10, 10)) == pytest.approx(45.0)
    assert g.point_line_foot((3, 7), a) == pytest.approx((3.0, 0.0))
    assert g.line_angle(g.line_to_dict(0, 0, 1, 1)) == pytest.approx(45.0) and g.line_angle(g.line_to_dict(0, 0, -1, 0)) == pytest.approx(0.0)


# ---- Matrix Circle Search ---------------------------------------------------------------------------------------------------------
def test_matrix_circle_search_finds_a_grid_of_circles():
    im = canvas(260, 420, 210)
    truth = []
    for r in range(2):
        for c in range(3):
            cx, cy = 90 + c * 120, 80 + r * 100
            cv2.circle(im, (cx, cy), 24, 50, -1, cv2.LINE_AA)
            truth.append((cx, cy))
    im = soften(im)
    _, r = run("Matrix Circle Search", {"Image": bgr(im)}, roi=[20, 20, 380, 220], array_rows=2, array_columns=3, min_radius=10.0, max_radius=45.0)
    assert r.status == ToolStatus.OK and r.outputs["Count"] == 6
    got = sorted((round(c["cx"]), round(c["cy"])) for c in r.outputs["Circles"])
    assert all(abs(a - b) <= 1 for pa, pb in zip(got, sorted(truth)) for a, b in zip(pa, pb))
    assert all(abs(c["r"] - 24) < 1.2 for c in r.outputs["Circles"]) and {(c["row"], c["column"]) for c in r.outputs["Circles"]} == {(i, j) for i in range(2) for j in range(3)}
    im2 = im.copy()
    cv2.circle(im2, (210, 80), 40, 210, -1)                                  # rub one circle out
    _, miss = run("Matrix Circle Search", {"Image": bgr(im2)}, roi=[20, 20, 380, 220], array_rows=2, array_columns=3, min_radius=10.0, max_radius=45.0)
    assert miss.outputs["Count"] == 5 and "5 of 6" in miss.message
    assert run("Matrix Circle Search", {"Image": bgr(im)}, min_radius=30.0, max_radius=20.0)[1].status == ToolStatus.ERROR
    assert run("Matrix Circle Search", {"Image": bgr(canvas())}, roi=[20, 20, 380, 220])[1].status == ToolStatus.NG


# ---- Ellipse Search ----------------------------------------------------------------------------------------------------------------
def test_ellipse_search_finds_a_tilted_ellipse():
    im = canvas(300, 420, 210)
    cv2.ellipse(im, (210, 150), (80, 45), 25, 0, 360, 50, -1, cv2.LINE_AA)
    im = soften(im)
    _, r = run("Ellipse Search", {"Image": bgr(im)}, roi=[110, 90, 200, 120], inner_scale=0.4, outer_scale=1.4)
    o = r.outputs
    assert r.status == ToolStatus.OK and abs(o["Center_X"] - 210) < 1 and abs(o["Center_Y"] - 150) < 1
    assert abs(o["Axis_A"] - 160) < 2.5 and abs(o["Axis_B"] - 90) < 2.5 and abs(o["Angle_Deg"] - 25) < 2
    assert run("Ellipse Search", {"Image": bgr(canvas())}, roi=[110, 90, 200, 120])[1].status == ToolStatus.NG
    assert run("Ellipse Search", {"Image": bgr(im)}, inner_scale=0.9, outer_scale=0.5)[1].status == ToolStatus.ERROR


# ---- Rect Search and Quadrilateral Search -----------------------------------------------------------------------------------------------
def test_rect_search_measures_a_turned_rectangle_even_with_noise():
    im = canvas(320, 460, 200)
    box = cv2.boxPoints(((230, 160), (200, 110), 20.0))
    cv2.fillConvexPoly(im, np.round(box).astype(np.int32), 60, cv2.LINE_AA)
    im = np.clip(soften(im).astype(np.int16) + np.random.default_rng(0).normal(0, 4, im.shape), 0, 255).astype(np.uint8)
    _, r = run("Rect Search", {"Image": bgr(im)}, roi=[130, 105, 200, 110], roi_angle=-20.0, search_margin=30.0, fit_mode="Huber")
    o = r.outputs
    assert r.status == ToolStatus.OK, r.message
    mask = (im < 130).astype(np.uint8)
    (tx, ty), (tw, th), _ = cv2.minAreaRect(cv2.findNonZero(mask))                    # the drawn rectangle's true size, from its pixels
    assert abs(o["Center_X"] - tx) < 1.0 and abs(o["Center_Y"] - ty) < 1.0
    assert abs(sorted([o["Width"], o["Height"]])[0] - min(tw, th)) < 1.5 and abs(sorted([o["Width"], o["Height"]])[1] - max(tw, th)) < 1.5, (o["Width"], o["Height"], tw, th)
    assert len(o["Corners"]) == 4 and len([l for l in o["Lines"] if l]) == 4
    far = run("Rect Search", {"Image": bgr(canvas())}, roi=[130, 105, 200, 110])[1]
    assert far.status == ToolStatus.NG and "side" in far.message


def test_quadrilateral_search_finds_the_corners_of_an_irregular_shape():
    im = canvas(320, 460, 205)
    quad = np.array([[110, 70], [350, 90], [330, 250], [90, 230]], np.int32)
    cv2.fillConvexPoly(im, quad, 55, cv2.LINE_AA)
    im = soften(im)
    _, r = run("Quadrilateral Search", {"Image": bgr(im)}, quad_points=[[115, 75], [345, 95], [325, 245], [95, 225]], search_margin=22.0)
    assert r.status == ToolStatus.OK, r.message
    got = sorted(map(tuple, np.round(r.outputs["Corners"]).astype(int).tolist()))
    for (gx, gy), (qx, qy) in zip(got, sorted(map(tuple, quad.tolist()))):
        assert abs(gx - qx) <= 2 and abs(gy - qy) <= 2
    assert run("Quadrilateral Search", {"Image": bgr(im)}, quad_points=[[0, 0], [10, 0], [10, 10]])[1].status == ToolStatus.ERROR


# ---- Peak Search -----------------------------------------------------------------------------------------------------------------------------
def test_peak_search_finds_the_tip_nearest_the_start_side():
    im = canvas(300, 420, 210)
    tri = np.array([[210, 90], [150, 230], [270, 230]], np.int32)               # a triangle pointing up, tip at (210, 90)
    cv2.fillConvexPoly(im, tri, 50, cv2.LINE_AA)
    im = soften(im)
    _, r = run("Peak Search", {"Image": bgr(im)}, roi=[130, 60, 160, 180], search_direction="Top to Bottom", scan_width=4, edge_type="First Edge")
    o = r.outputs
    assert r.status == ToolStatus.OK and abs(o["Peak_X"] - 210) <= 4 and abs(o["Peak_Y"] - 90) <= 2
    assert o["Peak_Polarity"] == "Light to Dark" and o["Peak_Score"] > 40 and abs(o["Peak_Distance"] - 30) <= 2 and o["Edge_Number"] > 10
    _, up = run("Peak Search", {"Image": bgr(im)}, roi=[130, 60, 160, 180], search_direction="Bottom to Top", scan_width=4, edge_type="First Edge")
    assert up.outputs["Peak_Y"] > 200, "from the bottom the nearest edge is the flat base"
    assert run("Peak Search", {"Image": bgr(canvas())}, roi=[130, 60, 160, 180])[1].status == ToolStatus.NG


# ---- Edge Intersection ---------------------------------------------------------------------------------------------------------------------------
def test_edge_intersection_finds_a_corner_with_one_roi_or_two():
    im = canvas(300, 420, 210)
    im[100:, 150:] = 50                                                          # a dark block whose corner is at (150, 100)
    im = soften(im)
    _, one = run("Edge Intersection", {"Image": bgr(im)}, roi_count=1, roi1=[100, 60, 160, 140], direction1="Left to Right", direction2="Top to Bottom")
    assert one.status == ToolStatus.OK and abs(one.outputs["Intersection_X"] - 149.5) < 1 and abs(one.outputs["Intersection_Y"] - 99.5) < 1
    assert abs(abs(one.outputs["Line_0_Angle"]) - 90) < 1.5 and abs(one.outputs["Line_1_Angle"]) < 1.5
    _, two = run("Edge Intersection", {"Image": bgr(im)}, roi_count=2, roi1=[100, 120, 100, 100], roi2=[170, 60, 120, 80], direction1="Left to Right", direction2="Top to Bottom")
    assert abs(two.outputs["Intersection_X"] - 149.5) < 1 and abs(two.outputs["Intersection_Y"] - 99.5) < 1
    skew = canvas(300, 420, 210)
    skew[130:, :] = 50
    skew = soften(skew)
    far = run("Edge Intersection", {"Image": bgr(skew)}, roi_count=2, roi1=[20, 100, 150, 60], roi2=[220, 100, 150, 60], direction1="Top to Bottom", direction2="Top to Bottom")[1]
    assert far.status == ToolStatus.NG and "parallel" in far.message
    assert run("Edge Intersection", {"Image": bgr(canvas())})[1].status == ToolStatus.NG


# ---- Parallel Lines Search --------------------------------------------------------------------------------------------------------------------------
def test_parallel_lines_search_measures_a_bar_and_rejects_a_wedge():
    im = canvas(300, 420, 210)
    pts = cv2.boxPoints(((210, 150), (320, 50), 3.0))
    cv2.fillConvexPoly(im, np.round(pts).astype(np.int32), 50, cv2.LINE_AA)
    im = soften(im)
    _, r = run("Parallel Lines Search", {"Image": bgr(im)}, roi=[80, 80, 260, 140], search_direction="Top to Bottom")
    assert r.status == ToolStatus.OK, r.message
    bar = (im < 130).astype(np.uint8)
    thickness = float(bar.sum(axis=0)[100:320].mean()) * math.cos(math.radians(3.0))      # the drawn bar's true thickness, from its pixels
    assert abs(r.outputs["Distance"] - thickness) < 1.0 and abs(r.outputs["Angle_Deg"] - 3.0) < 0.6, (r.outputs["Distance"], thickness)
    cl = r.outputs["Center_Line"]
    assert abs((cl["y1"] + cl["y2"]) / 2 - 150) < 1.5
    wedge = canvas(300, 420, 210)
    cv2.fillConvexPoly(wedge, np.array([[60, 130], [360, 100], [360, 200], [60, 170]], np.int32), 50, cv2.LINE_AA)
    wedge = soften(wedge)
    bad = run("Parallel Lines Search", {"Image": bgr(wedge)}, roi=[80, 60, 260, 180], search_direction="Top to Bottom", max_angle_tolerance=3.0)[1]
    assert bad.status == ToolStatus.NG and "apart" in bad.message
    ok2 = run("Parallel Lines Search", {"Image": bgr(wedge)}, roi=[80, 60, 260, 180], search_direction="Top to Bottom", max_angle_tolerance=15.0)[1]
    assert ok2.status == ToolStatus.OK
    for pair in ("First Pair", "Last Pair"):
        assert run("Parallel Lines Search", {"Image": bgr(im)}, roi=[80, 80, 260, 140], edge_pair_type=pair)[1].status == ToolStatus.OK
    assert run("Parallel Lines Search", {"Image": bgr(canvas())}, roi=[80, 80, 260, 140])[1].status == ToolStatus.NG


# ---- Line Group Search ---------------------------------------------------------------------------------------------------------------------------------
def test_line_group_search_joins_separate_stretches_into_one_line():
    im = canvas(300, 520, 210)
    for x in range(60, 460):
        y = int(round(150 + 0.05 * (x - 60)))
        im[y:, x] = 50 if not (230 < x < 290) else 210                       # a gap in the middle: no edge there
    im = soften(im)
    segs = [[60, 153, 220, 161], [300, 167, 460, 175]]
    _, r = run("Line Group Search", {"Image": bgr(im)}, segments=segs, search_band=14.0, caliper_number=12)
    assert r.status == ToolStatus.OK and r.outputs["Segment_Counts"] == [12, 12] and r.outputs["Point_Count"] == 24
    assert abs(r.outputs["Angle_Deg"] - math.degrees(math.atan(0.05))) < 0.4
    assert r.outputs["Line"]["length"] > 380, "the one line spans both stretches"
    broken = create_tool_instance("Line Group Search", "t")
    broken.parameters["segments"] = "oops"                                      # e.g. a hand-edited project file
    assert broken.execute({"Image": bgr(im)}).status == ToolStatus.ERROR
    assert run("Line Group Search", {"Image": bgr(canvas())}, segments=segs)[1].status == ToolStatus.NG


# ---- Multi-line Search ---------------------------------------------------------------------------------------------------------------------------------------
def test_multi_line_search_finds_several_lines_and_their_angles():
    im = canvas(320, 480, 40)
    cv2.line(im, (30, 60), (440, 60), 210, 3, cv2.LINE_AA)
    cv2.line(im, (30, 160), (440, 190), 210, 3, cv2.LINE_AA)
    cv2.line(im, (60, 30), (80, 300), 210, 3, cv2.LINE_AA)
    im = soften(im)
    _, r = run("Multi-line Search", {"Image": bgr(im)}, max_lines=6, edge_threshold=20.0, min_line_length=100.0, edge_distance_tolerance=3.0, coverage_rate=40.0,
               search_direction_angle=0.0, linear_rotation_tolerance=90.0)
    assert r.status == ToolStatus.OK and r.outputs["Count"] >= 3, r.message
    angles = sorted(round(a) for a in r.outputs["Angles"])
    expect = [0, round(math.degrees(math.atan2(30, 410))), round(math.degrees(math.atan2(270, 20)))]
    for want in expect:
        assert any(abs(((a - want + 90) % 180) - 90) <= 3 for a in angles), (want, angles)
    assert all(0.3 <= l["coverage"] <= 1 and l["inliers"] > 10 for l in r.outputs["Lines"])
    one = run("Multi-line Search", {"Image": bgr(im)}, max_lines=1, min_line_length=100.0, edge_distance_tolerance=3.0)[1]
    assert one.outputs["Count"] == 1
    roi_only = run("Multi-line Search", {"Image": bgr(im)}, roi=[0, 120, 480, 100], max_lines=6, min_line_length=100.0, edge_distance_tolerance=3.0)[1]
    assert roi_only.outputs["Count"] >= 1 and all(110 < (l["y1"] + l["y2"]) / 2 < 230 for l in roi_only.outputs["Lines"]), "only lines inside the region"
    assert run("Multi-line Search", {"Image": bgr(canvas())})[1].status == ToolStatus.NG
    bw = run("Multi-line Search", {"Image": bgr(im)}, edge_polarity="Black to White", search_direction_angle=90.0, linear_rotation_tolerance=10.0,
             min_line_length=100.0, edge_distance_tolerance=3.0)[1]
    assert all(abs(l["angle"]) < 15 for l in bw.outputs["Lines"]), "the rotation tolerance keeps only lines across the search direction"


@pytest.mark.parametrize("name", ["Matrix Circle Search", "Ellipse Search", "Rect Search", "Quadrilateral Search", "Peak Search", "Edge Intersection",
                                  "Parallel Lines Search", "Line Group Search", "Multi-line Search"])
def test_every_search_module_refuses_a_missing_picture_and_survives_a_flat_one(name):
    assert run(name, {})[1].status in (ToolStatus.NG, ToolStatus.ERROR)
    flat = run(name, {"Image": bgr(canvas())})[1]
    assert flat.status in (ToolStatus.NG, ToolStatus.OK) and flat.message
