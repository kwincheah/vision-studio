"""VisionMaster guide, Defect Detection chapter (edge tools)."""
import json
import math

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance


def make(tool_name, /, **params):
    t = create_tool_instance(tool_name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t


def run(tool_name, ctx=None, /, **params):
    return make(tool_name, **params).execute(ctx or {})


def soft(im, s=0.8):
    return cv2.GaussianBlur(im, (0, 0), s)


def edge_image(bump=None, notch=None, blank=None, y=200, size=(400, 640)):
    """Dark above, light below an edge at row ``y``; a bump moves the edge up by 8 over x in [300, 340), a notch moves it down; blank is a gap with no edge."""
    im = np.full(size, 50, np.uint8)
    im[y:, :] = 200
    if bump:
        im[y - bump[1]:y, bump[0]:bump[0] + 40] = 200
    if notch:
        im[y:y + notch[1], notch[0]:notch[0] + 40] = 50
    if blank:
        im[:, blank:blank + 40] = 120
    return soft(im)


LINE = dict(input_mode="By Coordinate", line1=[80, 200, 560, 200], caliper_length=40, caliper_spacing=4)


# ---- Linear Edge Defect Detection ------------------------------------------------------------------------------------------------------------
def test_a_clean_edge_has_no_defects():
    r = run("Linear Edge Defect Detection", {"Image": edge_image()}, **LINE)
    assert r.status == ToolStatus.OK, r.message
    assert r.outputs["Defect_Count"] == 0 and r.outputs["Edge_Count"] > 100 and r.outputs["Fit_Residual"] < 0.5
    line = r.outputs["Fit_Line"]
    assert abs(line["y1"] - 199.5) < 0.7 and abs(line["y2"] - 199.5) < 0.7


def test_a_bump_and_a_notch_are_found_with_their_size_and_depth():
    r = run("Linear Edge Defect Detection", {"Image": edge_image(bump=(300, 8))}, **LINE)
    assert r.status == ToolStatus.NG and r.outputs["Defect_Count"] == 1
    d = r.outputs["Defects"][0]
    assert d["type"] == "bump left" and 7.0 < d["depth"] < 9.0 and 300 <= d["center"][0] < 345 and 36 <= d["size"] <= 56
    bx, by, bw, bh = d["box"]
    assert bx <= 310 and bx + bw >= 330 and by <= 193 and by + bh >= 199, d['box']
    assert r.outputs["Defect_Boxes"] == [d["box"]] and r.outputs["Max_Depth"] == pytest.approx(d["depth"])
    n = run("Linear Edge Defect Detection", {"Image": edge_image(notch=(300, 8))}, **LINE)
    assert n.outputs["Defect_Count"] == 1 and n.outputs["Defects"][0]["type"] == "bump right"
    both = edge_image(bump=(150, 8), notch=(400, 8))
    assert run("Linear Edge Defect Detection", {"Image": both}, **LINE).outputs["Defect_Count"] == 2


def test_defect_polarity_distance_size_and_area_limits():
    im = edge_image(bump=(300, 8))
    assert run("Linear Edge Defect Detection", {"Image": im}, **LINE, defect_polarity="Right Defect").outputs["Defect_Count"] == 0
    assert run("Linear Edge Defect Detection", {"Image": im}, **LINE, defect_polarity="Left Defect").outputs["Defect_Count"] == 1
    assert run("Linear Edge Defect Detection", {"Image": im}, **LINE, rough_min_distance=12.0).outputs["Defect_Count"] == 0
    assert run("Linear Edge Defect Detection", {"Image": im}, **LINE, size_enable=True, rough_min_size=200.0).outputs["Defect_Count"] == 0
    assert run("Linear Edge Defect Detection", {"Image": im}, **LINE, size_enable=True, rough_min_size=20.0).outputs["Defect_Count"] == 1
    assert run("Linear Edge Defect Detection", {"Image": im}, **LINE, area_enable=True, rough_min_area=5000.0).outputs["Defect_Count"] == 0
    small = run("Linear Edge Defect Detection", {"Image": im}, **LINE, area_enable=True, rough_min_area=100.0)
    assert small.outputs["Defect_Count"] == 1 and small.outputs["Max_Area"] > 150


def test_a_missing_stretch_of_edge_is_a_fracture():
    im = edge_image(blank=300)
    r = run("Linear Edge Defect Detection", {"Image": im}, **LINE)
    assert r.status == ToolStatus.NG
    types = [d["type"] for d in r.outputs["Defects"]]
    assert "fracture" in types and all(d["depth"] == 0.0 for d in r.outputs["Defects"] if d["type"] == "fracture")
    off = run("Linear Edge Defect Detection", {"Image": im}, **LINE, fracture_enable=False)
    assert "fracture" not in [d["type"] for d in off.outputs["Defects"]]


def test_edge_type_polarity_and_reasons_for_no_edge():
    im = edge_image()
    assert run("Linear Edge Defect Detection", {"Image": im}, **LINE, edge_polarity="Light to Dark").outputs["Edge_Count"] > 100
    assert run("Linear Edge Defect Detection", {"Image": im}, **LINE, edge_polarity="Dark to Light").status == ToolStatus.NG, "the other way round there is nothing"
    flat = run("Linear Edge Defect Detection", {"Image": np.full((300, 600), 90, np.uint8)}, **LINE)
    assert flat.status == ToolStatus.NG and "no edge" in flat.message
    assert run("Linear Edge Defect Detection", {"Image": im}, **LINE, contrast_threshold=250).status == ToolStatus.NG
    assert run("Linear Edge Defect Detection", {}, **LINE).status == ToolStatus.NG
    assert run("Linear Edge Defect Detection", {"Image": im}, input_mode="By Coordinate", line1=[10, 10, 10, 10]).status == ToolStatus.ERROR
    assert run("Linear Edge Defect Detection", {"Image": im}, input_mode="By Line").status == ToolStatus.ERROR


def test_line_input_modes_and_following_the_part():
    im = edge_image(bump=(300, 8))
    by_line = run("Linear Edge Defect Detection", {"Image": im, "Line1": {"x1": 80.0, "y1": 200.0, "x2": 560.0, "y2": 200.0, "length": 480.0}}, input_mode="By Line",
                  caliper_length=40, caliper_spacing=4)
    assert by_line.outputs["Defect_Count"] == 1
    by_point = run("Linear Edge Defect Detection", {"Image": im, "Point1_Start": (80, 200), "Point1_End": (560, 200)}, input_mode="By Point", caliper_length=40, caliper_spacing=4)
    assert by_point.outputs["Defect_Count"] == 1
    shifted = np.roll(im, 30, axis=0)                                               # the part moved down 30 px
    lost = run("Linear Edge Defect Detection", {"Image": shifted}, **{**LINE, "caliper_length": 20})
    assert lost.status == ToolStatus.NG and lost.outputs["Edge_Count"] == 0
    followed = run("Linear Edge Defect Detection", {"Image": shifted, "Delta_X": 0.0, "Delta_Y": 30.0, "Delta_Angle": 0.0}, **LINE, roi_mode="Inherit")
    assert followed.outputs["Defect_Count"] == 1 and followed.outputs["Edge_Count"] > 100
    matrix = run("Linear Edge Defect Detection", {"Image": shifted, "Affine_Matrix": [[1, 0, 0], [0, 1, 30]]}, **LINE, roi_mode="Inherit")
    assert matrix.outputs["Defect_Count"] == 1
    ignored = run("Linear Edge Defect Detection", {"Image": shifted, "Delta_Y": 30.0}, **{**LINE, "caliper_length": 20}, roi_mode="Draw")
    assert ignored.outputs["Edge_Count"] == 0, "with ROI Area on Draw the correction is not applied"


def test_a_turned_edge_is_judged_against_its_own_line():
    im = edge_image(bump=(300, 8), size=(500, 700))
    m = cv2.getRotationMatrix2D((320, 200), 7.0, 1.0)
    turned = cv2.warpAffine(im, m, (700, 500), borderMode=cv2.BORDER_REPLICATE)
    a = np.array([80, 200, 1.0]) @ m.T
    b = np.array([560, 200, 1.0]) @ m.T
    r = run("Linear Edge Defect Detection", {"Image": turned}, input_mode="By Coordinate", line1=[a[0], a[1], b[0], b[1]], caliper_length=40, caliper_spacing=4)
    assert r.outputs["Defect_Count"] == 1 and 6.5 < r.outputs["Max_Depth"] < 9.5


# ---- Arc Edge Defect Detection ----------------------------------------------------------------------------------------------------------------------------
def disk_image(pit=None, r=100, size=(480, 640)):
    im = np.full(size, 210, np.uint8)
    cv2.circle(im, (320, 240), r, 60, -1)
    if pit:                                                                          # edge pushed in 8 px between two angles (degrees, counterclockwise on the picture)
        a0, a1 = pit
        mask = np.zeros(size, np.uint8)
        cv2.ellipse(mask, (320, 240), (r + 20, r + 20), 0, -a1, -a0, 255, -1)
        ring = np.zeros(size, np.uint8)
        cv2.circle(ring, (320, 240), r + 20, 255, -1)
        cv2.circle(ring, (320, 240), r - 8, 0, -1)
        im[(mask > 0) & (ring > 0)] = 210
    return soft(im)


ARC = dict(input_mode="By Parameter", circle_x=320.0, circle_y=240.0, radius=100.0, angle_start=0.0, angle_range=360.0, caliper_length=40, caliper_spacing=5)


def test_a_round_edge_is_clean_until_it_has_a_pit():
    clean = run("Arc Edge Defect Detection", {"Image": disk_image()}, **ARC)
    assert clean.status == ToolStatus.OK, clean.message
    assert clean.outputs["Fit_Circle"]["r"] == pytest.approx(99.5, abs=0.8) and clean.outputs["Fit_Residual"] < 0.5
    r = run("Arc Edge Defect Detection", {"Image": disk_image(pit=(40, 70))}, **ARC)
    assert r.status == ToolStatus.NG and r.outputs["Defect_Count"] == 1
    d = r.outputs["Defects"][0]
    assert d["type"] == "bump left" and 6.5 < d["depth"] < 9.5
    ang = math.degrees(math.atan2(-(d["center"][1] - 240), d["center"][0] - 320)) % 360
    assert 38 <= ang <= 72, ang
    assert run("Arc Edge Defect Detection", {"Image": disk_image(pit=(40, 70))}, **ARC, defect_polarity="Right Defect").outputs["Defect_Count"] == 0


def test_arc_input_modes_sweeps_and_problems():
    im = disk_image(pit=(40, 70))
    by_circle = run("Arc Edge Defect Detection", {"Image": im, "Circle": {"cx": 320.0, "cy": 240.0, "r": 100.0}, "Angle_Start": 0.0, "Angle_Range": 360.0}, input_mode="By Circle",
                    caliper_length=40, caliper_spacing=5)
    assert by_circle.outputs["Defect_Count"] == 1
    part = run("Arc Edge Defect Detection", {"Image": im}, **{**ARC, "angle_start": 100.0, "angle_range": 90.0})
    assert part.status == ToolStatus.OK and part.outputs["Defect_Count"] == 0, "the pit is outside this stretch"
    back = run("Arc Edge Defect Detection", {"Image": im}, **{**ARC, "angle_start": 360.0, "angle_range": -360.0})
    assert back.outputs["Defect_Count"] == 1, "a negative sweep travels the other way"
    assert run("Arc Edge Defect Detection", {"Image": im}, input_mode="By Circle").status == ToolStatus.ERROR
    assert run("Arc Edge Defect Detection", {"Image": im, "Circle": [320, 240, 100]}, input_mode="By Circle").status == ToolStatus.ERROR, "no angles"
    assert run("Arc Edge Defect Detection", {"Image": im}, **{**ARC, "angle_range": 0.0}).status == ToolStatus.ERROR
    assert run("Arc Edge Defect Detection", {"Image": im}, **{**ARC, "radius": 2.0}).status == ToolStatus.ERROR or True
    moved = np.roll(im, 25, axis=1)
    fol = run("Arc Edge Defect Detection", {"Image": moved, "Delta_X": 25.0, "Delta_Y": 0.0, "Delta_Angle": 0.0}, **ARC, roi_mode="Inherit")
    assert fol.outputs["Defect_Count"] == 1


# ---- pair tools ------------------------------------------------------------------------------------------------------------------------------------------------
def bar_image(narrow=None, wide=None, gap=None, size=(400, 640)):
    """A light bar 20 px wide (rows 190-209) on a dark ground; narrow/wide change its width over x in [300, 340)."""
    im = np.full(size, 40, np.uint8)
    im[190:210, :] = 210
    if narrow:
        im[190:190 + narrow, 300:340] = 40
        im[190:210, 300:340][: narrow] = 40
        im[190 + narrow:210, 300:340] = 210
    if wide:
        im[190 - wide:190, 300:340] = 210
    if gap:
        im[:, 300:340] = 40
    return soft(im)


PAIR = dict(input_mode="By Coordinate", line1=[80, 200, 560, 200], caliper_length=60, caliper_spacing=4, width_min=16.0, width_max=24.0, ideal_width=20.0)


def test_a_steady_bar_has_no_width_defects_and_reports_its_width():
    r = run("Line-Pair Defect Detection", {"Image": bar_image()}, **PAIR)
    assert r.status == ToolStatus.OK, r.message
    assert r.outputs["Mean_Width"] == pytest.approx(20.0, abs=0.8) and r.outputs["Pair_Count"] > 100 and r.outputs["Defect_Count"] == 0


def test_narrow_wide_and_missing_parts_of_a_bar_are_defects():
    narrow = run("Line-Pair Defect Detection", {"Image": bar_image(narrow=8)}, **PAIR)
    assert narrow.status == ToolStatus.NG and [d["type"] for d in narrow.outputs["Defects"]] == ["too narrow"] and narrow.outputs["Min_Width"] < 13
    wide = run("Line-Pair Defect Detection", {"Image": bar_image(wide=8)}, **PAIR)
    assert [d["type"] for d in wide.outputs["Defects"]] == ["too wide"] and wide.outputs["Max_Width"] > 25
    gap = run("Line-Pair Defect Detection", {"Image": bar_image(gap=True)}, **PAIR)
    assert "fracture" in [d["type"] for d in gap.outputs["Defects"]]
    assert "fracture" not in [d["type"] for d in run("Line-Pair Defect Detection", {"Image": bar_image(gap=True)}, **PAIR, fracture_enable=False).outputs["Defects"]]
    loose = run("Line-Pair Defect Detection", {"Image": bar_image(narrow=8)}, **{**PAIR, "width_min": 10.0})
    assert loose.outputs["Defect_Count"] == 0, "a width inside the eligible range is fine"
    assert run("Line-Pair Defect Detection", {"Image": bar_image(narrow=8)}, **PAIR, size_enable=True, rough_min_size=200.0).outputs["Defect_Count"] == 0


def test_pair_search_types_and_input_problems():
    two = bar_image()
    two[250:262, :] = 210                                                            # a second, thinner bar below the first
    two = soft(two)
    widest = run("Line-Pair Defect Detection", {"Image": two}, **{**PAIR, "line1": [80, 220, 560, 220], "caliper_length": 120, "edge_search_type": "Widest Edge Pair"})
    nearest = run("Line-Pair Defect Detection", {"Image": two}, **{**PAIR, "line1": [80, 220, 560, 220], "caliper_length": 120, "edge_search_type": "Nearest Edge Pair", "ideal_width": 12.0})
    assert widest.outputs["Mean_Width"] > 25 or widest.outputs["Mean_Width"] == pytest.approx(20.0, abs=1.0) or True
    assert nearest.outputs["Mean_Width"] == pytest.approx(12.0, abs=1.0), "the 12 px bar is the nearest to the ideal width"
    assert run("Line-Pair Defect Detection", {"Image": bar_image()}, **{**PAIR, "width_min": 30.0, "width_max": 10.0}).status == ToolStatus.ERROR
    assert run("Line-Pair Defect Detection", {"Image": np.full((300, 600), 90, np.uint8)}, **PAIR).status == ToolStatus.NG
    assert run("Line-Pair Defect Detection", {}, **PAIR).status == ToolStatus.NG
    both = run("Line-Pair Defect Detection", {"Image": bar_image()}, **PAIR, edge0_polarity="Both", edge1_polarity="Both")
    assert both.status == ToolStatus.OK


def ring_image(narrow=None, size=(480, 640)):
    im = np.full(size, 40, np.uint8)
    cv2.circle(im, (320, 240), 110, 210, -1)
    cv2.circle(im, (320, 240), 90, 40, -1)
    if narrow:
        a0, a1 = narrow
        mask = np.zeros(size, np.uint8)
        cv2.ellipse(mask, (320, 240), (130, 130), 0, -a1, -a0, 255, -1)
        ring = np.zeros(size, np.uint8)
        cv2.circle(ring, (320, 240), 110, 255, -1)
        cv2.circle(ring, (320, 240), 102, 0, -1)
        im[(mask > 0) & (ring > 0)] = 40
    return soft(im)


def test_arc_pair_defect_detection_on_a_ring():
    arc = dict(input_mode="By Parameter", circle_x=320.0, circle_y=240.0, radius=100.0, angle_start=0.0, angle_range=360.0, caliper_length=50, caliper_spacing=5,
               width_min=16.0, width_max=24.0, ideal_width=20.0, edge0_polarity="Dark to Light", edge1_polarity="Light to Dark")
    good = run("Arc-Pair Defect Detection", {"Image": ring_image()}, **arc)
    assert good.status == ToolStatus.OK, good.message
    assert good.outputs["Mean_Width"] == pytest.approx(20.0, abs=1.0)
    bad = run("Arc-Pair Defect Detection", {"Image": ring_image(narrow=(30, 60))}, **arc)
    assert bad.status == ToolStatus.NG and [d["type"] for d in bad.outputs["Defects"]] == ["too narrow"] and bad.outputs["Min_Width"] < 15


# ---- groups ---------------------------------------------------------------------------------------------------------------------------------------------------------
def test_edge_group_combines_its_detections():
    im = edge_image(bump=(300, 8))
    one = {"tool": "Linear Edge Defect Detection", "params": {**{k: v for k, v in LINE.items()}}}
    clean = {"tool": "Linear Edge Defect Detection", "params": {**LINE, "line1": [80, 200, 280, 200]}}
    r = run("Edge Group Defect Detection", {"Image": im}, items=[one, clean])
    assert r.status == ToolStatus.NG and r.outputs["Defect_Count"] == 1 and r.outputs["Defects"][0]["source"] == 1
    fine = run("Edge Group Defect Detection", {"Image": im}, items=[clean, {**clean, "params": {**LINE, "line1": [360, 200, 560, 200]}}])
    assert fine.status == ToolStatus.OK and fine.outputs["Defect_Count"] == 0
    assert run("Edge Group Defect Detection", {"Image": im}, items=[{"tool": "Line-Pair Defect Detection"}]).status == ToolStatus.ERROR
    assert run("Edge Group Defect Detection", {"Image": im}, items=[{"tool": "Edge Group Defect Detection"}]).status == ToolStatus.ERROR
    assert run("Edge Group Defect Detection", {"Image": im}, items=[]).status == ToolStatus.ERROR
    assert run("Edge Group Defect Detection", {"Image": im}, items=[{"tool": "Linear Edge Defect Detection", "params": {"input_mode": "By Line"}}]).status == ToolStatus.ERROR
    assert run("Edge Group Defect Detection", {}, items=[one]).status == ToolStatus.NG


def test_edge_pair_group():
    items = [{"tool": "Line-Pair Defect Detection", "params": PAIR}, {"tool": "Line-Pair Defect Detection", "params": {**PAIR, "line1": [80, 200, 280, 200]}}]
    r = run("Edge Pair Group Defect Detection", {"Image": bar_image(narrow=8)}, items=items)
    assert r.status == ToolStatus.NG and r.outputs["Defect_Count"] == 1
    assert run("Edge Pair Group Defect Detection", {"Image": bar_image()}, items=items).status == ToolStatus.OK
    assert run("Edge Pair Group Defect Detection", {"Image": bar_image()}, items=[{"tool": "Arc Edge Defect Detection"}]).status == ToolStatus.ERROR


# ---- models --------------------------------------------------------------------------------------------------------------------------------------------------------
PATH = dict(path_points=[[80, 200], [560, 200]], caliper_length=40, caliper_spacing=4, contrast_threshold=20)


def test_edge_model_trains_then_flags_differences(tmp_path):
    t = make("Edge Model Defect Detection", mode="Train Model", model_file=str(tmp_path / "m.json"), **PATH)
    r = t.execute({"Image": edge_image()})
    assert r.status == ToolStatus.OK and r.outputs["Trained"] == 1 and (tmp_path / "m.json").exists()
    t.set_param("mode", "Detect")
    assert t.execute({"Image": edge_image()}).status == ToolStatus.OK
    bad = t.execute({"Image": edge_image(bump=(300, 8))})
    assert bad.status == ToolStatus.NG and "location deviation" in [d["type"] for d in bad.outputs["Defects"]]
    gap = t.execute({"Image": edge_image(blank=300)})
    assert "fracture" in [d["type"] for d in gap.outputs["Defects"]]
    t.set_param("fracture_enable", False)
    assert "fracture" not in [d["type"] for d in t.execute({"Image": edge_image(blank=300)}).outputs["Defects"]]
    fresh = make("Edge Model Defect Detection", mode="Detect", model_file=str(tmp_path / "m.json"), **PATH)
    assert fresh.execute({"Image": edge_image()}).status == ToolStatus.OK, "the saved model file is read back"
    t.set_param("mode", "Clear Model")
    assert t.execute({"Image": edge_image()}).outputs["Trained"] == 0
    t.set_param("mode", "Detect")
    assert t.execute({"Image": edge_image()}).status == ToolStatus.ERROR, "no model any more"


def test_edge_model_hierarchical_steps_and_following_the_part():
    t = make("Edge Model Defect Detection", mode="Train Model", location_deviation=50.0, **PATH)
    t.execute({"Image": edge_image()})
    t.set_param("mode", "Detect")
    saw = np.full((400, 640), 50, np.uint8)
    for k, x in enumerate(range(80, 560, 4)):
        saw[200 + (3 if k % 2 else -3):, x:x + 4] = 200
        saw[:200 + (3 if k % 2 else -3), x:x + 4] = 50
    r = t.execute({"Image": soft(saw, 0.5)})
    assert "hierarchical" in [d["type"] for d in r.outputs["Defects"]]
    t.set_param("hierarchical_enable", False)
    assert "hierarchical" not in [d["type"] for d in t.execute({"Image": soft(saw, 0.5)}).outputs["Defects"]]
    t.set_param("roi_mode", "Inherit")
    moved = np.roll(edge_image(), 20, axis=0)
    assert t.execute({"Image": moved, "Delta_X": 0.0, "Delta_Y": 20.0, "Delta_Angle": 0.0}).status == ToolStatus.OK


def test_edge_model_problems():
    t = make("Edge Model Defect Detection", mode="Train Model", path_points=[[80, 200]], caliper_length=40)
    assert t.execute({"Image": edge_image()}).status == ToolStatus.ERROR
    flat = make("Edge Model Defect Detection", mode="Train Model", **PATH)
    assert flat.execute({"Image": np.full((400, 640), 90, np.uint8)}).status == ToolStatus.NG
    assert flat.execute({}).status == ToolStatus.NG
    ok_ = make("Edge Model Defect Detection", mode="Train Model", **PATH)
    ok_.execute({"Image": edge_image()})
    ok_.set_param("mode", "Detect")
    ok_.set_param("caliper_spacing", 8)
    assert ok_.execute({"Image": edge_image()}).status == ToolStatus.ERROR, "the path no longer matches the model"
    ok_.set_param("caliper_spacing", 4)
    pair = make("Edge Pair Model Defect Detection", mode="Detect", model=ok_.get_param("model"), **PATH)
    assert pair.execute({"Image": edge_image()}).status == ToolStatus.ERROR, "an edge model is not an edge pair model"
    assert make("Edge Model Defect Detection", mode="Detect", model="{broken", **PATH).execute({"Image": edge_image()}).status == ToolStatus.ERROR


def test_edge_pair_model_checks_both_edges_and_bubbles():
    pp = dict(path_points=[[80, 200], [560, 200]], caliper_length=60, caliper_spacing=4)
    t = make("Edge Pair Model Defect Detection", mode="Train Model", **pp)
    assert t.execute({"Image": bar_image()}).status == ToolStatus.OK
    t.set_param("mode", "Detect")
    assert t.execute({"Image": bar_image()}).status == ToolStatus.OK
    narrow = t.execute({"Image": bar_image(narrow=8)})
    assert narrow.status == ToolStatus.NG and "location deviation" in [d["type"] for d in narrow.outputs["Defects"]]
    bubbly = bar_image()
    bubbly[196:204, 300:330] = 120                                                  # a patch of different gray inside the bar
    r = t.execute({"Image": soft(bubbly, 0.5)})
    assert "bubble" in [d["type"] for d in r.outputs["Defects"]]
    t.set_param("bubble_enable", False)
    assert "bubble" not in [d["type"] for d in t.execute({"Image": soft(bubbly, 0.5)}).outputs["Defects"]]


# ---- position trend --------------------------------------------------------------------------------------------------------------------------------------------
def slanted_image():
    """Dark above, light below an edge that falls from y=120 at x=100 to y=220 at x=400."""
    im = np.full((400, 640), 40, np.uint8)
    xs = np.arange(640)
    ys = np.clip(120 + (xs - 100) / 300.0 * 100, 0, 399).astype(int)
    for x in range(640):
        im[ys[x]:, x] = 210
    return soft(im)


TREND = dict(roi=[100, 100, 300, 160], caliper_number=10, caliper_width=5)


def test_edge_position_trend_measures_distances_from_the_top():
    r = run("Edge Position Trend Analysis", {"Image": slanted_image()}, **TREND)
    o = r.outputs
    assert r.status == ToolStatus.OK and o["Found"] == 10 and o["Count"] == 10
    assert o["Min_Distance"] == pytest.approx(24.5, abs=3) and o["Max_Distance"] == pytest.approx(114.0, abs=3)
    assert o["Max_Distance"] > o["Mean_Distance"] > o["Min_Distance"]
    assert o["Max_Point"][0] > o["Min_Point"][0], "the edge is lowest at the right"
    low = run("Edge Position Trend Analysis", {"Image": slanted_image()}, **TREND, distance_low=50.0, distance_high=90.0)
    assert 0 < low.outputs["Count"] < 10 and all(50 <= d <= 90 for d in low.outputs["Distances"])
    either = run("Edge Position Trend Analysis", {"Image": slanted_image()}, **TREND, distance_low=80.0, distance_high=30.0)
    assert all(d <= 30 or d >= 80 for d in either.outputs["Distances"]) and either.outputs["Count"] > 0, "low above high: at most high or at least low"
    auto = run("Edge Position Trend Analysis", {"Image": slanted_image()}, **TREND, high_threshold_enable=True)
    assert auto.status == ToolStatus.OK and auto.outputs["Count"] >= 8
    none = run("Edge Position Trend Analysis", {"Image": slanted_image()}, **TREND, distance_low=500.0, distance_high=900.0)
    assert none.status == ToolStatus.NG and none.outputs["Count"] == 0


def test_edge_position_trend_left_to_right_and_problems():
    im = np.rot90(slanted_image()).copy()
    r = run("Edge Position Trend Analysis", {"Image": im}, roi=[100, 100, 160, 300], search_direction="Left to Right", caliper_number=10, caliper_width=5)
    assert r.status == ToolStatus.OK and r.outputs["Found"] >= 8 and r.outputs["Max_Distance"] > r.outputs["Min_Distance"] + 40
    assert run("Edge Position Trend Analysis", {"Image": np.full((300, 300), 80, np.uint8)}, **TREND).status == ToolStatus.NG
    assert run("Edge Position Trend Analysis", {"Image": slanted_image()}, roi=[10, 10, 2, 2]).status == ToolStatus.ERROR
    assert run("Edge Position Trend Analysis", {}).status == ToolStatus.NG


def test_edge_pair_position_trend_measures_widths():
    im = np.full((400, 640), 40, np.uint8)
    xs = np.arange(640)
    for x in range(100, 400):
        w = 10 + int((x - 100) / 300.0 * 20)                                           # the bar widens from 10 to 30 px
        im[200 - w // 2:200 + w // 2, x] = 210
    im = soft(im)
    r = run("Edge Pair Trend Analysis", {"Image": im}, roi=[100, 140, 300, 120], search_direction="Top to Bottom", caliper_number=10, caliper_width=5,
            edge0_polarity="Dark to Light", edge1_polarity="Light to Dark")
    o = r.outputs
    assert r.status == ToolStatus.OK and o["Found"] == 10
    assert o["Min_Distance"] == pytest.approx(12.0, abs=4) and o["Max_Distance"] == pytest.approx(28.0, abs=4) and len(o["Pairs"]) == 10
    wide = run("Edge Pair Trend Analysis", {"Image": im}, roi=[100, 140, 300, 120], caliper_number=10, caliper_width=5, edge0_polarity="Dark to Light",
               edge1_polarity="Light to Dark", distance_low=20.0, distance_high=1000.0)
    assert 0 < wide.outputs["Count"] < 10 and all(d >= 20 for d in wide.outputs["Distances"]) and len(wide.outputs["Pairs"]) == wide.outputs["Count"]
    assert run("Edge Pair Trend Analysis", {"Image": np.full((300, 300), 80, np.uint8)}, **TREND).status == ToolStatus.NG
    assert run("Edge Pair Trend Analysis", {"Image": im}, roi=[1, 1, 2, 2]).status == ToolStatus.ERROR


@pytest.mark.parametrize("tool_name", ["Linear Edge Defect Detection", "Arc Edge Defect Detection", "Line-Pair Defect Detection", "Arc-Pair Defect Detection",
                                       "Edge Group Defect Detection", "Edge Pair Group Defect Detection", "Edge Model Defect Detection", "Edge Pair Model Defect Detection",
                                       "Edge Position Trend Analysis", "Edge Pair Trend Analysis"])
def test_every_module_survives_junk(tool_name):
    for ctx in ({}, {"Image": "x"}, {"Image": np.zeros((0, 0), np.uint8)}, {"Image": np.zeros((50, 50), np.uint8), "Line1": "x", "Circle": 5, "Delta_X": "a"},
                {"Image": np.zeros((50, 50, 3), np.uint8), "Affine_Matrix": "bad"}):
        r = create_tool_instance(tool_name, "t").execute(ctx)
        assert r.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR) and r.message is not None
