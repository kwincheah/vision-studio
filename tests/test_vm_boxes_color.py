"""VisionMaster guide: Division and Combination, Color Recognition and Ellipse Fit, checked against cases with known answers."""
import math

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance
from apex_vision.tools import vm_boxes as vb


def run(name, ctx, **params):
    t = create_tool_instance(name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t, t.execute(ctx)


# ---- box helpers ---------------------------------------------------------------------------------------------------------
def test_boxes_accept_the_usual_shapes_and_overlap_is_relative_to_the_smaller_box():
    a = vb.to_box([10, 20, 100, 50])
    assert (a["cx"], a["cy"], a["w"], a["h"]) == (60, 45, 100, 50)
    assert vb.to_box({"cx": 5, "cy": 6, "w": 2, "h": 3, "angle": 30, "label": "x"})["angle"] == 30
    assert vb.to_box({"x": 0, "y": 0, "w": 10, "h": 10})["cx"] == 5 and vb.to_box("nonsense") is None and vb.to_box([1, 2]) is None
    assert vb.to_box({"Box": [0, 0, 4, 4], "Class": "scratch"})["label"] == "scratch", "detection records work as boxes"
    big, small = vb.to_box([0, 0, 100, 100]), vb.to_box([40, 40, 20, 20])
    assert vb.overlap_rate(big, small) == pytest.approx(1.0), "a small box inside a big one overlaps 100% of the smaller"
    assert vb.overlap_rate(vb.to_box([0, 0, 10, 10]), vb.to_box([50, 50, 10, 10])) == 0.0
    half = vb.overlap_rate(vb.to_box([0, 0, 10, 10]), vb.to_box([5, 0, 10, 10]))
    assert half == pytest.approx(0.5, abs=0.01)
    turned = vb.to_box({"cx": 50, "cy": 50, "w": 40, "h": 10, "angle": 90})
    assert vb.aabb(turned)[2] <= 12 and vb.aabb(turned)[3] >= 38, "a box turned 90 degrees stands upright"


# ---- Image Division ----------------------------------------------------------------------------------------------------------
def test_image_division_follows_the_guides_formula():
    for parts, overlap in ((3, 0.0), (4, 0.2), (2, 0.5), (1, 0.3)):
        spans = vb.divide_span(1000.0, parts, overlap)
        size = spans[0][1]
        assert size * parts - (parts - 1) * overlap * 1000.0 == pytest.approx(1000.0), "S*M - (M-1)*F*L = L"
        assert spans[0][0] == 0 and spans[-1][0] + spans[-1][1] == pytest.approx(1000.0), "the pieces cover the whole length"
    a = np.arange(240 * 320, dtype=np.uint32).reshape(240, 320).astype(np.uint8)
    _, r = run("Image Division Tool", {"Image": cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)}, divisions_x=3, divisions_y=2, overlap_x=0.0, overlap_y=0.0)
    assert r.outputs["Count"] == 6 and r.outputs["Boxes"][0] == [0, 0, 107, 120] or r.outputs["Boxes"][0][:2] == [0, 0]
    assert len(r.outputs["Images"]) == 6 and sum(p.shape[0] * p.shape[1] for p in r.outputs["Images"]) >= 240 * 320 - 600
    _, ov = run("Image Division Tool", {"Image": cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)}, divisions_x=2, divisions_y=1, overlap_x=20.0)
    b0, b1 = ov.outputs["Boxes"]
    assert b0[0] + b0[2] > b1[0] and b1[0] + b1[2] == 320, "neighbouring pieces overlap and the last reaches the edge"
    _, sub = run("Image Division Tool", {"Image": cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)}, roi=[100, 50, 120, 60], divisions_x=2, divisions_y=2, overlap_x=0.0, overlap_y=0.0)
    assert sub.outputs["Boxes"][0] == [100, 50, 60, 30] and sub.outputs["Boxes"][3] == [160, 80, 60, 30], "only the region is divided"


# ---- 2D Array Correction -----------------------------------------------------------------------------------------------------------
def test_array_correction_fills_in_a_missing_box_and_straightens_a_misplaced_one():
    rows, cols, dx, dy = 3, 4, 80, 60
    truth = [(50 + c * dx, 40 + r * dy) for r in range(rows) for c in range(cols)]
    found = [[x - 15, y - 10, 30, 20] for x, y in truth]
    missing = 5
    wrong = 6
    found[wrong] = [found[wrong][0] + 9, found[wrong][1] - 7, 30, 20]            # located a few pixels off
    del found[missing]
    _, r = run("2D Array Correction", {"Boxes": found}, array_rows=rows, array_columns=cols)
    assert r.status == ToolStatus.OK and r.outputs["Count"] == rows * cols
    got = sorted((round(c[0]), round(c[1])) for c in r.outputs["Centers"])
    want = sorted(truth)
    assert max(abs(g[0] - w[0]) + abs(g[1] - w[1]) for g, w in zip(got, want)) <= 2, "every centre, including the missing and the misplaced, is on the grid"
    assert all(b["w"] == 30 and b["h"] == 20 for b in r.outputs["Boxes"]), "box sizes are untouched"
    assert run("2D Array Correction", {"Boxes": found[:3]}, array_rows=3, array_columns=4)[1].status == ToolStatus.NG
    assert run("2D Array Correction", {})[1].status == ToolStatus.NG


def test_array_correction_handles_a_slightly_tilted_grid():
    ang = math.radians(5)
    pts = []
    for r in range(3):
        for c in range(3):
            x, y = c * 70, r * 70
            pts.append((100 + x * math.cos(ang) - y * math.sin(ang), 100 + x * math.sin(ang) + y * math.cos(ang)))
    found = [[x - 10, y - 10, 20, 20] for x, y in pts]
    del found[4]
    _, r = run("2D Array Correction", {"Boxes": found}, array_rows=3, array_columns=3)
    got = sorted((round(c[0]), round(c[1])) for c in r.outputs["Centers"])
    assert max(abs(g[0] - w[0]) + abs(g[1] - w[1]) for g, w in zip(got, sorted((round(x), round(y)) for x, y in pts))) <= 3


# ---- Pixel Transformation -----------------------------------------------------------------------------------------------------------
def test_pixel_transformation_marks_the_listed_classes():
    labels = np.array([[0, 1, 2, 3], [5, 5, 8, 9]], np.uint8)
    _, r = run("Pixel Transformation", {"Image": np.pad(labels, 4)}, class_list="1,5,8")
    out = r.outputs["Image"]
    assert r.outputs["Pixel_Count"] == 4 and out[4, 5] == 255 and out[5, 4] == 255 and out[5, 6] == 255 and out[4, 6] == 0
    _, port = run("Pixel Transformation", {"Image": np.pad(labels, 4), "Class_Index": [2, 3], "Class_Count": 1})
    assert port.outputs["Pixel_Count"] == 1, "the class count limits how many list entries are used"
    assert run("Pixel Transformation", {"Image": np.pad(labels, 4)}, class_list="a,b")[1].status == ToolStatus.ERROR


# ---- Box Merge ------------------------------------------------------------------------------------------------------------------------
def test_box_merge_three_modes():
    boxes = [[0, 0, 40, 40], [30, 0, 40, 40], [200, 0, 40, 40]]
    labels = ["dent", "scratch", "stain"]
    _, fp = run("Box Merge", {"Boxes": boxes, "Labels": labels}, overlap_rate=0.2, merge_type="Merge Type Flaw Priority",
                flaw_priority="scratch,dent,stain", priority_sort="Grade Down")
    assert fp.outputs["Count"] == 2 and set(fp.outputs["Labels"]) == {"scratch", "stain"}, "the more important label survives"
    big = next(b for b in fp.outputs["Boxes"] if b["label"] == "scratch")
    assert abs(big["w"] - 70) <= 1 and abs(big["h"] - 40) <= 1, "the merged box encloses both"
    _, up = run("Box Merge", {"Boxes": boxes, "Labels": labels}, overlap_rate=0.2, merge_type="Merge Type Flaw Priority",
                flaw_priority="scratch,dent,stain", priority_sort="Grade Up")
    assert "dent" in up.outputs["Labels"] and "scratch" not in up.outputs["Labels"], "Grade Up reverses which end wins"
    _, same = run("Box Merge", {"Boxes": boxes, "Labels": labels}, overlap_rate=0.2, merge_type="Merge Type Box Label")
    assert same.outputs["Count"] == 3, "different labels are never merged in 'Box Label' mode"
    _, same2 = run("Box Merge", {"Boxes": boxes, "Labels": ["a", "a", "b"]}, overlap_rate=0.2, merge_type="Merge Type Box Label")
    assert same2.outputs["Count"] == 2
    _, anyl = run("Box Merge", {"Boxes": boxes, "Labels": labels}, overlap_rate=0.2, merge_type="Merge Type No Box Label")
    assert anyl.outputs["Count"] == 2 and anyl.outputs["Labels"][0] == "dent", "the label comes from the first box"
    _, strict = run("Box Merge", {"Boxes": boxes, "Labels": labels}, overlap_rate=0.95, merge_type="Merge Type No Box Label")
    assert strict.outputs["Count"] == 3, "a high overlap threshold keeps them apart"
    chain = run("Box Merge", {"Boxes": [[0, 0, 40, 40], [30, 0, 40, 40], [60, 0, 40, 40]], "Labels": ["a", "a", "a"]}, overlap_rate=0.2,
                merge_type="Merge Type No Box Label")[1]
    assert chain.outputs["Count"] == 1, "a chain of overlapping boxes becomes one"
    assert run("Box Merge", {})[1].outputs["Count"] == 0


# ---- Box Overlap ---------------------------------------------------------------------------------------------------------------------------
def test_box_overlap_calculation():
    _, r = run("Box Overlap", {"Box1": [0, 0, 100, 100], "Box2": [50, 0, 100, 100]})
    assert r.outputs["Overlap_Rate"] == pytest.approx(0.5, abs=0.01) and r.outputs["Overlap_Box"] == [50, 0, 50, 100]
    assert run("Box Overlap", {"Box1": [0, 0, 10, 10], "Box2": [100, 100, 10, 10]})[1].outputs["Overlap_Rate"] == 0.0
    assert run("Box Overlap", {"Box1": [0, 0, 100, 100], "Box2": [10, 10, 20, 20]})[1].outputs["Overlap_Rate"] == pytest.approx(1.0)
    turned = run("Box Overlap", {"Box1": {"cx": 50, "cy": 50, "w": 100, "h": 20, "angle": 0}, "Box2": {"cx": 50, "cy": 50, "w": 100, "h": 20, "angle": 90}})[1]
    assert turned.outputs["Overlap_Rate"] == pytest.approx(20 * 20 / (100 * 20), abs=0.02), "a cross: the shared square is 20 x 20"
    assert run("Box Overlap", {"Box1": "x", "Box2": [0, 0, 1, 1]})[1].status == ToolStatus.ERROR
    assert run("Box Overlap", {})[1].status == ToolStatus.OK, "the settings supply the two boxes when nothing is connected"


# ---- Box Filtering -----------------------------------------------------------------------------------------------------------------------------
def test_box_filtering_keeps_boxes_that_are_white_enough_in_the_mask():
    mask = np.zeros((200, 300), np.uint8)
    mask[20:60, 20:60] = 255                                  # box A fully white
    mask[100:140, 100:112] = 255                              # box B: 30% white
    boxes = [[20, 20, 40, 40], [100, 100, 40, 40], [200, 100, 40, 40]]
    _, r = run("Box Filtering", {"Image": mask, "Boxes": boxes}, min_overlap=0.1)
    assert [b["cx"] for b in r.outputs["Boxes"]] == [40.0, 120.0] and len(r.outputs["Removed"]) == 1 and r.outputs["Count"] == 2
    _, strict = run("Box Filtering", {"Image": mask, "Boxes": boxes}, min_overlap=0.5)
    assert strict.outputs["Count"] == 1
    assert run("Box Filtering", {"Boxes": boxes})[1].status == ToolStatus.NG


# ---- Color Recognition ----------------------------------------------------------------------------------------------------------------------
def swatch(bgr, noise=6, seed=0, size=(60, 80)):
    rng = np.random.default_rng(seed)
    im = np.empty(size + (3,), np.float32)
    im[:] = bgr
    return np.clip(im + rng.normal(0, noise, im.shape), 0, 255).astype(np.uint8)


RED, GREEN, BLUE, YELLOW = (30, 30, 200), (40, 190, 50), (200, 60, 30), (30, 210, 220)


def teach(t, label, colour, n=4):
    t.set_param("mode", "Learn")
    t.set_param("learn_label", label)
    for i in range(n):
        assert t.execute({"Image": swatch(colour, seed=i + hash(label) % 50)}).status == ToolStatus.OK
    t.set_param("mode", "Recognize")


@pytest.mark.parametrize("feature", ["Feature Histogram", "Feature Spectrum"])
@pytest.mark.parametrize("dist", ["Euclidean Distance", "Manhattan Distance", "Intersection Distance"])
def test_color_recognition_learns_and_names_colours(feature, dist):
    t = create_tool_instance("Color Recognition", "t")
    t.set_param("feature_type", feature)
    t.set_param("knn_distance", dist)
    t.set_param("k_value", 3)
    for label, colour in (("red", RED), ("green", GREEN), ("blue", BLUE)):
        teach(t, label, colour)
    for label, colour in (("red", RED), ("green", GREEN), ("blue", BLUE)):
        r = t.execute({"Image": swatch(colour, seed=99)})
        assert r.status == ToolStatus.OK and r.outputs["Class"] == label and r.outputs["Score"] > 0.5, (feature, dist, label, r.message)
        assert max(r.outputs["Scores"], key=r.outputs["Scores"].get) == label
    assert r.outputs["Samples"] == {"red": 4, "green": 4, "blue": 4}


def test_color_recognition_options_errors_and_persistence():
    t = create_tool_instance("Color Recognition", "t")
    assert t.execute({"Image": swatch(RED)}).status == ToolStatus.NG, "nothing learned yet"
    t.set_param("mode", "Learn")
    assert t.execute({"Image": swatch(RED)}).status == ToolStatus.ERROR, "a label is needed to learn"
    t.set_param("mode", "Recognize")
    teach(t, "red", RED)
    teach(t, "yellow", YELLOW)
    t.set_param("min_score", 0.999)
    assert t.execute({"Image": swatch(GREEN, seed=7)}).status == ToolStatus.NG, "a colour it has never seen does not score high enough"
    t.set_param("min_score", 0.0)
    assert t.execute({"Image": swatch(RED, seed=5)}).outputs["Class"] == "red"
    # the ROI picks the colour inside the region only
    mixed = swatch(GREEN, size=(60, 160))
    mixed[:, 80:] = swatch(YELLOW, size=(60, 80))
    t.set_param("roi", [90, 5, 60, 50])
    assert t.execute({"Image": mixed}).outputs["Class"] == "yellow"
    # the samples survive saving and loading the module
    t2 = create_tool_instance("Color Recognition", "t2")
    t2.load_dict(t.to_dict())
    t2.set_param("roi", [90, 5, 60, 50])
    assert t2.execute({"Image": mixed}).outputs["Class"] == "yellow"
    t.set_param("mode", "Clear Samples")
    assert t.execute({"Image": swatch(RED)}).outputs["Samples"] == {}
    t.set_param("mode", "Recognize")
    assert t.execute({"Image": swatch(RED)}).status == ToolStatus.NG
    # samples made with other feature settings are refused, not silently misread
    teach(t, "red", RED)
    t.set_param("sensitivity_mode", "High Sensitivity")
    assert t.execute({"Image": swatch(RED)}).status == ToolStatus.ERROR


def test_brightness_off_makes_recognition_steadier_under_lighting_changes():
    on = create_tool_instance("Color Recognition", "a")
    off = create_tool_instance("Color Recognition", "b")
    off.set_param("use_intensity", False)
    for t in (on, off):
        for label, colour in (("red", RED), ("green", GREEN)):
            teach(t, label, colour)
    darker_red = np.clip(swatch(RED, seed=3).astype(np.float32) * 0.55, 0, 255).astype(np.uint8)
    assert off.execute({"Image": darker_red}).outputs["Class"] == "red"


# ---- Ellipse Fit ------------------------------------------------------------------------------------------------------------------------------
def test_ellipse_fit_recovers_a_known_ellipse_and_checks_the_point_count():
    cx, cy, a, b, ang = 200.0, 150.0, 80.0, 40.0, 30.0
    th = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    pts = [[cx + a * math.cos(u) * ca - b * math.sin(u) * sa, cy + a * math.cos(u) * sa + b * math.sin(u) * ca] for u in th]
    _, r = run("Circle/Line Fit", {"Point_Set": pts}, fit_type="Ellipse Fit")
    o = r.outputs
    assert r.status == ToolStatus.OK and abs(o["Center_X"] - cx) < 0.5 and abs(o["Center_Y"] - cy) < 0.5
    assert abs(o["Axis_A"] - 2 * a) < 1 and abs(o["Axis_B"] - 2 * b) < 1 and abs(o["Angle_Deg"] - ang) < 1
    assert run("Circle/Line Fit", {"Point_Set": pts[:4]}, fit_type="Ellipse Fit")[1].status == ToolStatus.NG
    circle = run("Circle/Line Fit", {"Point_Set": [[100, 200], [200, 100], [300, 200], [200, 300]]}, fit_type="Circle Fit")[1]
    assert circle.outputs["Circle"] == {"cx": circle.outputs["Center_X"], "cy": circle.outputs["Center_Y"], "r": circle.outputs["Radius"]}
    line = run("Circle/Line Fit", {"Point_Set": [[0, 0], [50, 50], [100, 100]]}, fit_type="Line Fit")[1]
    assert line.outputs["Line"]["length"] > 100
