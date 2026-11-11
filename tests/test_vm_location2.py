"""VisionMaster guide, Location chapter (second half): line geometry, Mark Location, BLOB Label Analysis, Path Extraction, Target Tracking."""
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


def L(x1, y1, x2, y2):
    return g.line_to_dict(x1, y1, x2, y2)


# ---- Find Angle Bisector ------------------------------------------------------------------------------------------------------
def test_angle_bisector_splits_the_angle_in_every_input_mode():
    # a horizontal line and a vertical line crossing at (100, 100): the bisector runs at 45 degrees through that point
    _, r = run("Find Angle Bisector", {"Line1": L(100, 100, 200, 100), "Line2": L(100, 100, 100, 200)}, input_mode="By Line")
    o = r.outputs
    assert r.status == ToolStatus.OK and o["Intersection"] == pytest.approx((100.0, 100.0)) and o["Angle_Deg"] == pytest.approx(90.0)
    assert abs(abs(o["Bisector_Angle"]) - 45) < 0.01
    b = o["Bisector"]
    assert (b["x1"] + b["x2"]) / 2 == pytest.approx(100.0) and (b["y1"] + b["y2"]) / 2 == pytest.approx(100.0)
    assert o["Bisector"]["x2"] > 100 and o["Bisector"]["y2"] > 100 or o["Bisector"]["x1"] > 100 and o["Bisector"]["y1"] > 100, "it points between the arms (down-right)"
    assert abs(g.angle_between(o["Bisector"], o["Bisector_2"]) - 90) < 0.01
    # By Point and By Coordinate give the same answer
    _, p = run("Find Angle Bisector", {"Point1_Start": (100, 100), "Point1_End": (200, 100), "Point2_Start": (100, 100), "Point2_End": (100, 200)}, input_mode="By Point")
    assert p.outputs["Bisector_Angle"] == pytest.approx(o["Bisector_Angle"])
    _, c = run("Find Angle Bisector", {}, input_mode="By Coordinate", line1=[100, 100, 200, 100], line2=[100, 100, 100, 200])
    assert c.outputs["Bisector_Angle"] == pytest.approx(o["Bisector_Angle"])
    # an unequal angle: lines at 0 and 30 degrees -> bisector at 15 degrees
    _, a30 = run("Find Angle Bisector", {}, input_mode="By Coordinate", line1=[0, 0, 100, 0], line2=[0, 0, 100 * math.cos(math.radians(30)), 100 * math.sin(math.radians(30))])
    assert a30.outputs["Angle_Deg"] == pytest.approx(30.0) and a30.outputs["Bisector_Angle"] == pytest.approx(15.0, abs=0.01)
    assert run("Find Angle Bisector", {}, input_mode="By Coordinate", line1=[0, 0, 100, 0], line2=[0, 50, 100, 50])[1].status == ToolStatus.NG
    assert run("Find Angle Bisector", {}, input_mode="By Line")[1].status == ToolStatus.ERROR
    assert run("Find Angle Bisector", {}, input_mode="By Coordinate", line1=[5, 5, 5, 5])[1].status == ToolStatus.ERROR


# ---- Find Median Line ---------------------------------------------------------------------------------------------------------------
def test_median_line_joins_the_midpoints_of_the_starts_and_ends():
    _, r = run("Find Median Line", {"Line1": L(0, 0, 100, 0), "Line2": L(0, 40, 100, 80)}, input_mode="By Line")
    m = r.outputs["Median_Line"]
    assert r.outputs["Start_Midpoint"] == (0.0, 20.0) and r.outputs["End_Midpoint"] == (100.0, 40.0)
    assert (m["x1"], m["y1"], m["x2"], m["y2"]) == (0.0, 20.0, 100.0, 40.0) and r.outputs["Angle_Deg"] == pytest.approx(math.degrees(math.atan2(20, 100)))
    _, c = run("Find Median Line", {}, input_mode="By Coordinate", line1=[0, 0, 100, 0], line2=[0, 40, 100, 80])
    assert c.outputs["Median_Line"] == m
    assert run("Find Median Line", {}, input_mode="By Coordinate", line1=[0, 0, 10, 0], line2=[0, 0, 10, 0])[1].status == ToolStatus.OK
    assert run("Find Median Line", {}, input_mode="By Coordinate", line1=[0, 0, 10, 0], line2=[10, 0, 0, 0])[1].status == ToolStatus.NG, "midpoints coincide: no line"


# ---- Calculate Parallel Lines -----------------------------------------------------------------------------------------------------------
def test_parallel_lines_by_point_and_by_distance():
    _, d = run("Calculate Parallel Lines", {"Line1": L(0, 0, 100, 0)}, method="A Distance from the Line", input_mode="By Line", distance=25.0)
    a, b = d.outputs["Line_A"], d.outputs["Line_B"]
    assert {a["y1"], b["y1"]} == {25.0, -25.0} and a["x1"] == 0 and a["x2"] == 100 and g.angle_between(a, L(0, 0, 100, 0)) < 1e-9
    _, p = run("Calculate Parallel Lines", {"Line1": L(0, 0, 100, 100), "Point": (60, 20)}, method="A Point Outside the Line", input_mode="By Line")
    pl = p.outputs["Line_A"]
    assert g.angle_between(pl, L(0, 0, 100, 100)) < 1e-6 and g.point_line_foot((60, 20), pl) == pytest.approx((60.0, 20.0))
    assert p.outputs["Distance"] == pytest.approx(40 / math.sqrt(2), abs=0.01)
    assert p.outputs["Line_B"] is None
    _, pt = run("Calculate Parallel Lines", {"Point1_Start": (0, 0), "Point1_End": (100, 0)}, method="A Distance from the Line", input_mode="By Point", distance=10.0)
    assert pt.status == ToolStatus.OK
    assert run("Calculate Parallel Lines", {}, method="A Point Outside the Line", input_mode="By Coordinate", point="x")[1].status in (ToolStatus.OK, ToolStatus.ERROR)
    assert run("Calculate Parallel Lines", {"Point": "bad"}, method="A Point Outside the Line", input_mode="By Coordinate")[1].status == ToolStatus.ERROR


# ---- Find Vertical Line ----------------------------------------------------------------------------------------------------------------------
def test_vertical_line_through_a_point_and_the_perpendicular_bisector():
    _, r = run("Find Vertical Line", {"Line1": L(0, 0, 100, 0), "Point": (30, 50)}, method="Point Perpendicular", input_mode="By Line")
    v = r.outputs["Vertical_Line"]
    assert r.outputs["Foot"] == pytest.approx((30.0, 0.0)) and r.outputs["Distance"] == pytest.approx(50.0)
    assert abs(g.angle_between(v, L(0, 0, 100, 0)) - 90) < 1e-9 and {(v["x1"], v["y1"]), (v["x2"], v["y2"])} == {(30.0, 50.0), (30.0, 0.0)}
    _, on = run("Find Vertical Line", {"Line1": L(0, 0, 100, 0), "Point": (30, 0)}, method="Point Perpendicular", input_mode="By Line")
    assert on.outputs["Distance"] == 0 and abs(g.angle_between(on.outputs["Vertical_Line"], L(0, 0, 1, 0)) - 90) < 1e-9, "a point on the line still gets a perpendicular"
    _, b = run("Find Vertical Line", {"Line1": L(10, 10, 110, 10)}, method="Perpendicular Bisector", input_mode="By Line")
    bl = b.outputs["Vertical_Line"]
    assert b.outputs["Foot"] == (60.0, 10.0) and bl["x1"] == bl["x2"] == 60.0 and bl["length"] == pytest.approx(100.0)
    _, tilt = run("Find Vertical Line", {}, method="Perpendicular Bisector", input_mode="By Coordinate", line1=[0, 0, 100, 100])
    assert abs(g.angle_between(tilt.outputs["Vertical_Line"], L(0, 0, 100, 100)) - 90) < 1e-9 and tilt.outputs["Foot"] == (50.0, 50.0)
    assert run("Find Vertical Line", {}, input_mode="By Line")[1].status == ToolStatus.ERROR


# ---- Mark Location ---------------------------------------------------------------------------------------------------------------------------------
def _cross(im, cx, cy, size=40, arm=8, angle=0.0, value=40, hollow=False):
    c = np.zeros(im.shape[:2], np.uint8)
    cv2.rectangle(c, (cx - size // 2, cy - arm // 2), (cx + size // 2, cy + arm // 2), 255, -1)
    cv2.rectangle(c, (cx - arm // 2, cy - size // 2), (cx + arm // 2, cy + size // 2), 255, -1)
    m = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    c = cv2.warpAffine(c, m, (im.shape[1], im.shape[0]))
    im[c > 127] = value
    return im


def test_mark_location_finds_crosses_and_rectangles_at_a_turned_angle():
    im = np.full((240, 360), 215, np.uint8)
    _cross(im, 200, 120, angle=6.0)
    im = cv2.GaussianBlur(im, (0, 0), 0.8)
    _, r = run("Mark Location", {"Image": cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)}, mark_type="Solid Cross", mark_width=40, mark_height=40, arm_width=8,
               angle_min=-12.0, angle_max=12.0, angle_step=2.0, min_score=0.6)
    o = r.outputs
    assert r.status == ToolStatus.OK and abs(o["Center_X"] - 200) <= 2 and abs(o["Center_Y"] - 120) <= 2, r.message
    assert abs(o["Angle_Deg"] - 6.0) <= 2.0 and o["Score"] > 0.8
    rect = np.full((240, 360), 215, np.uint8)
    cv2.rectangle(rect, (60, 60), (130, 100), 50, -1)
    _, rr = run("Mark Location", {"Image": cv2.cvtColor(cv2.GaussianBlur(rect, (0, 0), 0.8), cv2.COLOR_GRAY2BGR)}, mark_type="Rectangle", mark_width=71, mark_height=41,
                angle_min=0.0, angle_max=0.0, min_score=0.7)
    assert abs(rr.outputs["Center_X"] - 95) <= 2 and abs(rr.outputs["Center_Y"] - 80) <= 2
    light = 255 - im
    assert run("Mark Location", {"Image": cv2.cvtColor(light, cv2.COLOR_GRAY2BGR)}, mark_type="Solid Cross", mark_polarity="Dark on Light", angle_min=-10.0, angle_max=10.0,
               angle_step=2.0, min_score=0.6)[1].status == ToolStatus.NG, "the mark is light here but the module was told it is dark"
    ign = run("Mark Location", {"Image": cv2.cvtColor(light, cv2.COLOR_GRAY2BGR)}, mark_type="Solid Cross", mark_polarity="Dark on Light", match_polarity="Ignored",
              angle_min=-10.0, angle_max=10.0, angle_step=2.0, min_score=0.6)[1]
    assert ign.status == ToolStatus.OK and abs(ign.outputs["Center_X"] - 200) <= 2, "with polarity ignored it is found either way"


def test_mark_location_finds_several_marks_and_reports_problems():
    im = np.full((240, 420), 215, np.uint8)
    for cx in (80, 210, 340):
        _cross(im, cx, 120)
    im = cv2.GaussianBlur(im, (0, 0), 0.8)
    _, r = run("Mark Location", {"Image": cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)}, mark_type="Solid Cross", max_matches=5, angle_min=0.0, angle_max=0.0, min_score=0.7)
    assert r.outputs["Count"] == 3 and sorted(round(m["x"]) for m in r.outputs["Matches"]) == pytest.approx([80, 210, 340], abs=2)
    assert [m["score"] for m in r.outputs["Matches"]] == sorted((m["score"] for m in r.outputs["Matches"]), reverse=True)
    assert run("Mark Location", {"Image": cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)}, mark_width=400, mark_height=400)[1].status == ToolStatus.ERROR
    assert run("Mark Location", {"Image": cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)}, angle_min=10.0, angle_max=-10.0)[1].status == ToolStatus.ERROR
    assert run("Mark Location", {"Image": cv2.cvtColor(np.full((240, 420), 215, np.uint8), cv2.COLOR_GRAY2BGR)}, angle_min=0.0, angle_max=0.0)[1].status == ToolStatus.NG
    roi = run("Mark Location", {"Image": cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)}, mark_type="Solid Cross", max_matches=5, angle_min=0.0, angle_max=0.0, min_score=0.7, roi=[150, 40, 120, 160])[1]
    assert roi.outputs["Count"] == 1 and abs(roi.outputs["Center_X"] - 210) <= 2


# ---- BLOB Label Analysis ----------------------------------------------------------------------------------------------------------------------------
def _label_picture():
    lab = np.zeros((200, 300), np.uint8)
    cv2.rectangle(lab, (20, 20), (80, 60), 1, -1)            # class 1: 61 x 41
    cv2.circle(lab, (150, 50), 20, 1, -1)                    # class 1: a disc
    cv2.rectangle(lab, (30, 120), (50, 130), 2, -1)          # class 2: small
    cv2.rectangle(lab, (120, 110), (240, 170), 2, -1)        # class 2: big
    cv2.rectangle(lab, (250, 10), (252, 12), 3, -1)          # class 3: tiny
    return lab


def test_blob_label_analysis_names_regions_by_class_and_measures_them():
    lab = _label_picture()
    _, r = run("BLOB Label Analysis", {"Image": lab}, label_names="scratch,dent,dot", gray_values="1,2,3", global_min_area=1)
    assert r.status == ToolStatus.OK and r.outputs["Count"] == 5
    by = {}
    for b in r.outputs["Blobs"]:
        by.setdefault(b["label"], []).append(b)
    assert len(by["scratch"]) == 2 and len(by["dent"]) == 2 and len(by["dot"]) == 1
    rect = next(b for b in by["scratch"] if b["area"] == 61 * 41)
    assert rect["box"] == [20, 20, 61, 41] and rect["rectangularity"] > 0.98 and abs(rect["cx"] - 50) < 0.5
    disc = next(b for b in by["scratch"] if b["area"] != 61 * 41)
    assert disc["circularity"] > 0.8 and abs(disc["cx"] - 150) < 0.5 and 0.9 < disc["axis_ratio"] <= 1.0
    assert r.outputs["Areas"] == sorted(r.outputs["Areas"], reverse=True), "default order: largest first"
    assert r.outputs["Image"].shape == lab.shape and np.count_nonzero(r.outputs["Image"]) == sum(r.outputs["Areas"])
    assert sorted(set(r.outputs["Label_Values"])) == [1, 2, 3]


def test_blob_label_analysis_filters_sorts_and_limits():
    lab = _label_picture()
    only = run("BLOB Label Analysis", {"Image": lab}, label_names="a,b,c", gray_values="1,2,3", global_min_area=100)[1]
    assert only.outputs["Count"] == 4 and "c" not in only.outputs["Labels"], "the 3x3 dot is under 100 px"
    label_level = run("BLOB Label Analysis", {"Image": lab}, gray_values="2", label_names="dent", label_level_area=True, global_area=True, label_min_area=500, label_max_area=100000)[1]
    assert label_level.outputs["Count"] == 1 and label_level.outputs["Areas"] == [121 * 61], "label-level area wins when both are on"
    inv = run("BLOB Label Analysis", {"Image": lab}, gray_values="2", label_level_area=True, label_min_area=500, label_max_area=100000, invert_area_filter=True)[1]
    assert inv.outputs["Areas"] == [21 * 11], "the inverse keeps what the range would have dropped"
    srt = run("BLOB Label Analysis", {"Image": lab}, gray_values="1,2,3", global_min_area=1, sort_feature="Center X", sort_type="Ascending")[1]
    xs = [c[0] for c in srt.outputs["Centers"]]
    assert xs == sorted(xs)
    none = run("BLOB Label Analysis", {"Image": lab}, gray_values="1,2,3", global_min_area=1, sort_type="No Sorting")[1]
    assert none.outputs["Count"] == 5
    assert run("BLOB Label Analysis", {"Image": lab}, gray_values="1,2,3", global_min_area=1, max_blobs=2)[1].outputs["Count"] == 2
    ports = run("BLOB Label Analysis", {"Image": lab, "Label_Names": ["x", "y", "z"], "Gray_Values": [3, 2, 1]}, global_min_area=1)[1]
    assert set(ports.outputs["Labels"]) == {"x", "y", "z"} and next(b for b in ports.outputs["Blobs"] if b["gray"] == 3)["label"] == "x"
    auto = run("BLOB Label Analysis", {"Image": lab}, global_min_area=1)[1]
    assert sorted(set(auto.outputs["Label_Values"])) == [1, 2, 3] and auto.outputs["Labels"][0].startswith("class_"), "with no list, every value in the picture is a class"
    axis = run("BLOB Label Analysis", {"Image": lab}, gray_values="1", global_min_area=1, min_axis_ratio=0.9)[1]
    assert axis.outputs["Count"] == 1 and axis.outputs["Blobs"][0]["circularity"] > 0.8
    assert run("BLOB Label Analysis", {"Image": lab}, gray_values="x")[1].status == ToolStatus.ERROR
    assert run("BLOB Label Analysis", {"Image": np.zeros((50, 50), np.uint8)}, gray_values="1")[1].status == ToolStatus.NG


def test_blob_label_analysis_roi_overlap_and_connectivity():
    lab = np.zeros((100, 200), np.uint8)
    lab[20:60, 20:80] = 1                                    # fully inside the region
    lab[20:60, 150:190] = 1                                  # a quarter inside
    base = dict(gray_values="1", global_min_area=1, roi=[0, 0, 100, 100])
    assert run("BLOB Label Analysis", {"Image": lab}, **base)[1].outputs["Count"] == 1
    lab2 = lab.copy()
    lab2[20:60, 95:140] = 1                                  # straddles the region's edge: 5 of 45 columns inside
    assert run("BLOB Label Analysis", {"Image": lab2}, **base, min_overlap_rate=50.0)[1].outputs["Count"] == 1
    assert run("BLOB Label Analysis", {"Image": lab2}, **base, min_overlap_rate=0.0)[1].outputs["Count"] == 2
    diag = np.zeros((20, 20), np.uint8)
    diag[2:5, 2:5] = 1
    diag[5:8, 5:8] = 1                                       # touch only at a corner
    assert run("BLOB Label Analysis", {"Image": diag}, gray_values="1", global_min_area=1, connectivity="8-connected")[1].outputs["Count"] == 1
    assert run("BLOB Label Analysis", {"Image": diag}, gray_values="1", global_min_area=1, connectivity="4-connected")[1].outputs["Count"] == 2


# ---- Path Extraction -----------------------------------------------------------------------------------------------------------------------------------
def test_path_extraction_takes_equally_spaced_points_and_follows_the_part():
    pic = np.zeros((300, 500), np.uint8)
    _, r = run("Path Extraction", {"Image": pic}, path_type="Polyline", path_points=[[50, 100], [150, 100], [150, 200]], point_count=11)
    pts = np.array(r.outputs["Points"])
    assert r.outputs["Count"] == 11 and r.outputs["Path_Length"] == pytest.approx(200.0)
    steps = np.hypot(*np.diff(pts, axis=0).T)
    assert pts[0].tolist() == [50.0, 100.0] and pts[-1].tolist() == [150.0, 200.0] and np.all(np.abs(steps - 20.0) < 1e-6), "equal 20 px spacing along the path"
    assert pts[5].tolist() == pytest.approx([150.0, 100.0]), "the corner is exactly half-way"
    shifted = run("Path Extraction", {"Image": pic, "Delta_X": 10.0, "Delta_Y": -5.0, "Delta_Angle": 0.0}, path_points=[[50, 100], [150, 100]], point_count=3)[1]
    assert np.allclose(shifted.outputs["Points"], [[60.0, 95.0], [110.0, 95.0], [160.0, 95.0]])
    mat = run("Path Extraction", {"Image": pic, "Affine_Matrix": [[1, 0, 0], [0, 1, 20]]}, path_points=[[0, 0], [10, 0]], point_count=2)[1]
    assert np.allclose(mat.outputs["Points"], [[0.0, 20.0], [10.0, 20.0]])
    turned = run("Path Extraction", {"Image": pic, "Delta_X": 0.0, "Delta_Y": 0.0, "Delta_Angle": 90.0}, path_points=[[110, 100], [210, 100]], point_count=2, reference_point=[100, 100])[1]
    assert np.allclose(turned.outputs["Points"], [[100.0, 90.0], [100.0, -10.0]], atol=1e-6), "turned 90 degrees (counterclockwise) about the reference point"
    off = run("Path Extraction", {"Image": pic}, path_points=[[50, 100], [150, 100]], point_count=2, position_offset=7.0)[1]
    assert abs(off.outputs["Points"][0][1] - 100.0) == pytest.approx(7.0), "the position offset moves the points sideways"
    assert run("Path Extraction", {"Image": pic}, path_points=[[5, 5], [5, 5]])[1].status == ToolStatus.ERROR


def test_path_extraction_arc_and_edge_finding():
    pic = np.zeros((300, 500), np.uint8)
    _, a = run("Path Extraction", {"Image": pic}, path_type="Arc", arc_center=[250, 200], arc_radius=100.0, arc_start_angle=0.0, arc_end_angle=90.0, point_count=10)
    pts = np.array(a.outputs["Points"])
    assert pts[0].tolist() == pytest.approx([350.0, 200.0]) and pts[-1].tolist() == pytest.approx([250.0, 100.0]) and np.allclose(np.hypot(*(pts - [250, 200]).T), 100)
    assert a.outputs["Arc_Center"] == (250.0, 200.0) and a.outputs["Arc_Angle"] == 90.0
    # find the real edge near the planned path: a bright band whose upper edge is 6 px below the plan
    img = np.zeros((200, 400), np.uint8)
    img[106:, :] = 200
    img = cv2.GaussianBlur(img, (0, 0), 1.0)
    _, e = run("Path Extraction", {"Image": img}, path_points=[[40, 100], [360, 100]], point_count=9, extraction_method="Find Edge Points", caliper_height=30,
               edge_threshold=30)
    assert e.status == ToolStatus.OK and e.outputs["Count"] == 9
    assert all(abs(p[1] - 105.5) < 0.8 for p in e.outputs["Points"]), "every point moved onto the edge"
    flat = run("Path Extraction", {"Image": np.zeros((200, 400), np.uint8)}, path_points=[[40, 100], [360, 100]], extraction_method="Find Edge Points")[1]
    assert flat.status == ToolStatus.NG


# ---- Target Tracking ----------------------------------------------------------------------------------------------------------------------------------------
def test_target_tracking_counts_each_target_once_as_it_crosses_the_line():
    t = create_tool_instance("Target Tracking", "t")
    t.set_param("roi", [0, 50, 400, 100])
    t.set_param("direction", "Left to Right")
    counts = []
    for f in range(60):
        boxes = []
        for start in (-40, -160, -280):                                         # three items, 120 px apart, moving 10 px per picture
            x = start + f * 10
            if -20 <= x + 20 <= 440:
                boxes.append([x, 80, 40, 40])
        counts.append(t.execute({"Boxes": boxes}).outputs["Count"])
    assert counts[-1] == 3, counts
    assert all(b - a in (0, 1) for a, b in zip(counts, counts[1:])), "the count only goes up, one at a time"
    r = t.execute({"Boxes": [], "Clear": True})
    assert r.outputs["Count"] == 0 and r.outputs["Active"] == 0


def test_target_tracking_direction_lost_frames_and_overlap():
    def feed(direction, boxes_per_frame, **params):
        t = create_tool_instance("Target Tracking", "t")
        t.set_param("roi", [0, 0, 300, 300])
        t.set_param("direction", direction)
        for k, v in params.items():
            t.set_param(k, v)
        r = t.execute({"Boxes": []})
        for boxes in boxes_per_frame:
            r = t.execute({"Boxes": boxes})
        return r.outputs["Count"]
    right = [[[x, 130, 30, 30]] for x in range(0, 270, 10)]
    assert feed("Left to Right", right) == 1 and feed("Right to Left", right) == 0, "moving right is not counted when counting leftwards"
    down = [[[130, y, 30, 30]] for y in range(0, 270, 10)]
    assert feed("Top to Bottom", down) == 1 and feed("Bottom to Top", down) == 0
    assert feed("Bottom to Top", list(reversed(down))) == 1
    gap = [b for i, b in enumerate(right) if i not in (12, 13)]                  # two pictures where the detector missed the item
    assert feed("Left to Right", gap, max_lost_frames=3) == 1, "a short gap does not make a second target"
    assert feed("Left to Right", gap, max_lost_frames=0) >= 1
    two = [[[x, 100, 30, 30], [x, 200, 30, 30]] for x in range(0, 270, 10)]
    assert feed("Left to Right", two) == 2, "two parallel targets are two counts"
    far = [[[x, 130, 30, 30]] for x in range(0, 270, 40)]                         # 40 px jumps: no overlap with the previous place
    assert feed("Left to Right", far, track_overlap=30) <= 3
    assert feed("Left to Right", []) == 0
    junk = create_tool_instance("Target Tracking", "t").execute({"Boxes": "nonsense"})
    assert junk.status == ToolStatus.OK and junk.outputs["Count"] == 0


@pytest.mark.parametrize("name", ["Find Angle Bisector", "Find Median Line", "Calculate Parallel Lines", "Find Vertical Line", "Mark Location", "BLOB Label Analysis",
                                  "Path Extraction", "Target Tracking"])
def test_every_module_handles_missing_or_junk_input_without_crashing(name):
    for ctx in ({}, {"Image": None}, {"Image": "x"}, {"Image": np.zeros((0, 0), np.uint8)}, {"Boxes": 5}, {"Line1": "x", "Line2": [1]}):
        r = create_tool_instance(name, "t").execute(ctx)
        assert r.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR) and r.message is not None
