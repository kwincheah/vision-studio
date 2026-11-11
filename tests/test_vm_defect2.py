"""VisionMaster guide, Defect Detection chapter (Surface Defect Filter, OCV, Defect Contrast)."""
import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance
from apex_vision.tools import vm_defect2 as vd


def make(tool_name, /, **params):
    t = create_tool_instance(tool_name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t


def run(tool_name, ctx=None, /, **params):
    return make(tool_name, **params).execute(ctx or {})


# ---- Surface Defect Filter ---------------------------------------------------------------------------------------------------------------------------------
def surface(scratch=None, speck=None, noise=0.0, seed=1):
    im = np.full((240, 320), 120, np.float32)
    if scratch == "vertical":
        im[60:140, 160:162] = 60
    elif scratch == "horizontal":
        im[100:102, 100:200] = 60
    elif scratch == "diagonal":
        cv2.line(im, (100, 60), (180, 140), 60, 2)
    if speck:
        im[speck[1] - 2:speck[1] + 2, speck[0] - 2:speck[0] + 2] = 190
    if noise:
        im += np.random.default_rng(seed).normal(0, noise, im.shape).astype(np.float32)
    return np.clip(im, 0, 255).astype(np.uint8)


def test_a_clean_surface_gives_no_response_and_defects_stand_out():
    clean = run("Surface Defect Filter", {"Image": surface()})
    assert clean.status == ToolStatus.OK and clean.outputs["Max_Response"] == 0.0 and not clean.outputs["Image"].any()
    noisy = run("Surface Defect Filter", {"Image": surface(noise=2.0)})
    assert noisy.outputs["Max_Response"] < 8.0, "ordinary sensor noise stays under the offset"
    for kind in ("vertical", "horizontal", "diagonal"):
        r = run("Surface Defect Filter", {"Image": surface(scratch=kind, noise=2.0)})
        assert r.outputs["Max_Response"] > 30.0, kind
        assert r.outputs["Image"].max() > 100
    sp = run("Surface Defect Filter", {"Image": surface(speck=(200, 120), noise=2.0)})
    ys, xs = np.nonzero(sp.outputs["Image"] > 60)
    assert len(xs) > 0 and abs(xs.mean() - 200) < 6 and abs(ys.mean() - 120) < 6, "the response sits on the speck"
    both = run("Surface Defect Filter", {"Image": surface(scratch="vertical", speck=(250, 200))})
    assert both.outputs["Image"][100, 160:163].max() > 100 and both.outputs["Image"][200, 250] > 60


def test_direction_weights_count_and_region():
    vert = surface(scratch="vertical", noise=1.0)
    full = run("Surface Defect Filter", {"Image": vert}).outputs["Max_Response"]
    suppressed = run("Surface Defect Filter", {"Image": vert}, weight_90=-10, weight_60=-10, weight_120=-10, weight_30=-10, weight_150=-10).outputs["Max_Response"]
    assert suppressed < 0.3 * full, "vertical scratches are ignored when the directions that see them are switched off"
    boosted = run("Surface Defect Filter", {"Image": vert}, weight_90=10).outputs["Max_Response"]
    assert boosted > full
    one = run("Surface Defect Filter", {"Image": surface(scratch="horizontal")}, kernel_count=1).outputs["Max_Response"]
    other = run("Surface Defect Filter", {"Image": surface(scratch="vertical")}, kernel_count=1).outputs["Max_Response"]
    assert one > 3 * other, "a single horizontal detector sees horizontal scratches far better than vertical ones"
    inside = run("Surface Defect Filter", {"Image": vert}, roi=[100, 40, 120, 120])
    outside = run("Surface Defect Filter", {"Image": vert}, roi=[0, 180, 100, 50])
    assert inside.outputs["Max_Response"] > 30 and outside.outputs["Max_Response"] == 0.0
    assert not inside.outputs["Image"][:30].any() and inside.overlays
    big_offset = run("Surface Defect Filter", {"Image": vert}, offset=250.0)
    assert big_offset.outputs["Max_Response"] == 0.0
    colour = run("Surface Defect Filter", {"Image": cv2.cvtColor(vert, cv2.COLOR_GRAY2BGR)})
    assert colour.outputs["Image"].ndim == 2 and colour.outputs["Max_Response"] > 30
    assert run("Surface Defect Filter", {}).status == ToolStatus.NG


def test_ridge_kernel_is_zero_mean_and_turns():
    for ang in (0, 30, 90, 150):
        k = vd.ridge_kernel(ang, 21, 9, 1.5)
        assert abs(k.sum()) < 1e-4 and k.max() > 0 and k.min() < 0
    horiz, vert = vd.ridge_kernel(0, 21, 9, 1.5), vd.ridge_kernel(90, 21, 9, 1.5)
    assert horiz.shape == vert.shape
    assert np.allclose(horiz, vert.T, atol=1e-4), "turning by 90 degrees transposes it"
    assert vd._angle_weight(0, [1, 2, 3, 4, 5, 6]) == 1 and vd._angle_weight(15, [0, 10, 0, 0, 0, 0]) == pytest.approx(5.0) and vd._angle_weight(165, [6, 0, 0, 0, 0, 0]) == pytest.approx(3.0)


# ---- OCV ------------------------------------------------------------------------------------------------------------------------------------------------------------
def print_image(text="AB12", pos=(60, 90), noise=1.5, seed=0, erase=None, extra=None, angle=0.0, shift=(0, 0), size=(220, 360)):
    im = np.full(size, 235, np.uint8)
    cv2.putText(im, text, (pos[0] + shift[0], pos[1] + shift[1]), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 20, 4, cv2.LINE_AA)
    if erase:
        x, y, w, h = erase
        im[y:y + h, x:x + w] = 235
    if extra:
        x, y, w, h = extra
        im[y:y + h, x:x + w] = 20
    if angle:
        m = cv2.getRotationMatrix2D((size[1] / 2, size[0] / 2), angle, 1.0)
        im = cv2.warpAffine(im, m, (size[1], size[0]), borderValue=235)
    if noise:
        im = np.clip(im.astype(np.float32) + np.random.default_rng(seed).normal(0, noise, im.shape), 0, 255).astype(np.uint8)
    return im


OCV_ROI = [45, 50, 180, 60]


def trained(n=6, **extra):
    t = make("OCV", mode="Train", roi=OCV_ROI, **extra)
    for i in range(n):
        r = t.execute({"Image": print_image(seed=i, shift=(i % 3 - 1, (i // 2) % 3 - 1))})
        assert r.status == ToolStatus.OK, r.message
    t.set_param("mode", "Detect")
    return t


def test_ocv_trains_then_accepts_good_prints():
    t = trained()
    assert t.parameters["model"]["n"] == 6
    r = t.execute({"Image": print_image(seed=99)})
    assert r.status == ToolStatus.OK, r.message
    assert r.outputs["Defect_Count"] == 0 and r.outputs["Score"] > 0.85 and r.outputs["Trained"] == 6
    shifted = t.execute({"Image": print_image(seed=98, shift=(12, -9))})
    assert shifted.status == ToolStatus.OK and shifted.outputs["Pose"][0] > 0
    turned = t.execute({"Image": print_image(seed=97, angle=4.0)})
    assert turned.status == ToolStatus.OK, turned.message
    assert abs(abs(turned.outputs["Pose"][2]) - 4.0) <= 2.1


def test_ocv_finds_missing_extra_and_smeared_strokes():
    t = trained()
    missing = t.execute({"Image": print_image(seed=5, erase=(60, 70, 22, 30))})
    assert missing.status == ToolStatus.NG and missing.outputs["Defect_Count"] >= 1
    bx, by, bw, bh = missing.outputs["Defect_Boxes"][0]
    assert bx < 82 and bx + bw > 62 and by < 100 and by + bh > 72, "the box sits where the stroke was erased"
    extra = t.execute({"Image": print_image(seed=6, extra=(150, 55, 12, 12))})
    assert extra.status == ToolStatus.NG and extra.outputs["Defect_Count"] >= 1
    hits = [b for b in extra.outputs["Defect_Boxes"] if b[0] < 165 and b[0] + b[2] > 148]
    assert hits, extra.outputs["Defect_Boxes"]
    moved = t.execute({"Image": print_image(seed=7, erase=(60, 70, 22, 30), shift=(14, 6))})
    assert moved.outputs["Defect_Count"] >= 1, "found and judged where the print really is"
    bx2 = moved.outputs["Defect_Boxes"][0][0]
    assert abs(bx2 - (bx + 14)) < 12 or any(abs(b[0] - (bx + 14)) < 12 for b in moved.outputs["Defect_Boxes"])


def test_ocv_defect_types_tolerances_and_the_difference_picture():
    t = trained()
    missing = print_image(seed=5, erase=(60, 70, 22, 30))
    extra = print_image(seed=6, extra=(150, 55, 12, 12))
    assert run("OCV", {"Image": missing}, mode="Detect", roi=OCV_ROI, model=t.parameters["model"], defect_type="Dark").outputs["Defect_Count"] == 0, "a missing stroke is a bright spot"
    assert run("OCV", {"Image": missing}, mode="Detect", roi=OCV_ROI, model=t.parameters["model"], defect_type="Bright").outputs["Defect_Count"] >= 1
    assert run("OCV", {"Image": extra}, mode="Detect", roi=OCV_ROI, model=t.parameters["model"], defect_type="Bright").outputs["Defect_Count"] == 0
    assert run("OCV", {"Image": extra}, mode="Detect", roi=OCV_ROI, model=t.parameters["model"], defect_type="Dark").outputs["Defect_Count"] >= 1
    big = run("OCV", {"Image": extra}, mode="Detect", roi=OCV_ROI, model=t.parameters["model"], area_tolerance=5000)
    assert big.outputs["Defect_Count"] == 0, "defects under the area tolerance are ignored"
    loose = run("OCV", {"Image": extra}, mode="Detect", roi=OCV_ROI, model=t.parameters["model"], dark_threshold=250, dark_scale=20.0)
    assert loose.outputs["Defect_Count"] == 0, "thresholds above any difference forgive everything"
    r = t.execute({"Image": missing})
    assert r.outputs["Image"].dtype == np.uint8 and r.outputs["Image"].max() > 100 and r.outputs["Max_Difference"] > 100
    assert any(o["type"] == "rect" and o.get("label") == "defect" for o in r.overlays)


def test_ocv_edge_tolerance_forgives_small_shifts_of_strokes():
    t = trained()
    nudged = print_image(seed=11)
    nudged = np.roll(nudged, 2, axis=1)
    none = run("OCV", {"Image": nudged}, mode="Detect", roi=OCV_ROI, model=t.parameters["model"], edge_tolerance=0, correct_position=False, search_roi=[40, 45, 190, 70])
    some = run("OCV", {"Image": nudged}, mode="Detect", roi=OCV_ROI, model=t.parameters["model"], edge_tolerance=3, search_roi=[40, 45, 190, 70])
    assert some.outputs["Defect_Count"] <= none.outputs["Defect_Count"]
    assert some.status == ToolStatus.OK, some.message


def test_ocv_reports_what_is_wrong():
    t = trained(n=3)
    assert t.execute({"Image": np.full((220, 360), 128, np.uint8)}).status == ToolStatus.NG
    wrong = t.execute({"Image": print_image(text="ZQ9K", seed=3)})
    assert wrong.status == ToolStatus.NG and wrong.outputs["Score"] < 0.8 or wrong.outputs["Defect_Count"] > 0
    assert run("OCV", {"Image": print_image()}, mode="Detect").status == ToolStatus.ERROR
    assert run("OCV", {"Image": print_image()}, mode="Train", roi=[10, 10, 3, 3]).status == ToolStatus.ERROR
    assert run("OCV", {}, mode="Detect").status == ToolStatus.NG
    off_page = make("OCV", mode="Train", roi=OCV_ROI)
    off_page.execute({"Image": print_image()})
    blank = off_page.execute({"Image": np.full((220, 360), 235, np.uint8)})
    assert blank.status == ToolStatus.NG and off_page.parameters["model"]["n"] == 1, "a picture without the print is not added"
    bad = make("OCV", mode="Detect", model={"n": 1, "w": 10, "h": 10, "sum": {"shape": [3], "data": "!!"}, "sumsq": {}})
    assert bad.execute({"Image": print_image()}).status == ToolStatus.ERROR
    cleared = trained(n=2)
    cleared.set_param("mode", "Clear Model")
    assert cleared.execute({"Image": print_image()}).outputs["Trained"] == 0 and cleared.parameters["model"] == {}


def test_ocv_model_survives_saving_the_solution():
    from apex_vision.core.pipeline import VisionPipeline
    t = trained(n=4)
    flow = VisionPipeline("f")
    flow.add_node(t)
    back = VisionPipeline.from_xml(flow.to_xml()) if hasattr(flow, "to_xml") else None
    if back is None:
        pytest.skip("no flow-level XML here")
    again = list(back.nodes.values())[0]
    assert again.parameters["model"]["n"] == 4
    assert again.execute({"Image": print_image(seed=77)}).status == ToolStatus.OK


# ---- Defect Contrast ----------------------------------------------------------------------------------------------------------------------------------------
def part(kind="ok", seed=0, size=(160, 200)):
    rng = np.random.default_rng(seed)
    im = np.full(size, 200, np.float32)
    cv2.circle(im, (100, 80), 50, 80, -1)
    if kind == "ng":
        cv2.line(im, (60, 50), (140, 110), 210, 6)
        im[30:50, 120:150] = 20
    elif kind == "other":
        im = np.tile(np.linspace(30, 220, size[1], dtype=np.float32), (size[0], 1))
        im += rng.normal(0, 30, im.shape).astype(np.float32)
    im = im + rng.normal(0, 4, im.shape).astype(np.float32)
    return np.clip(im, 0, 255).astype(np.uint8)


ROI = [40, 20, 120, 120]


def learned(n_ok=5, n_ng=5):
    t = make("Defect Contrast", roi=ROI)
    t.set_param("mode", "Learn OK")
    for i in range(n_ok):
        assert t.execute({"Image": part("ok", i)}).status == ToolStatus.OK
    t.set_param("mode", "Learn NG")
    for i in range(n_ng):
        assert t.execute({"Image": part("ng", 100 + i)}).status == ToolStatus.OK
    t.set_param("mode", "Detect")
    return t


def test_defect_contrast_separates_ok_from_ng():
    t = learned()
    good = t.execute({"Image": part("ok", 50)})
    bad = t.execute({"Image": part("ng", 150)})
    assert good.status == ToolStatus.OK and good.outputs["Result"] == 1 and good.outputs["Score"] > 0.9
    assert bad.status == ToolStatus.NG and bad.outputs["Result"] == 0 and bad.outputs["Score"] < 0.1
    assert good.outputs["OK_Samples"] == 5 and good.outputs["NG_Samples"] == 5
    assert good.overlays[0]["color"] == (0, 255, 0) and bad.overlays[0]["color"] == (0, 0, 255)
    t.set_param("score_threshold", 0.99999)
    assert t.execute({"Image": part("ok", 51)}).status in (ToolStatus.OK, ToolStatus.NG)


def test_defect_contrast_with_only_ok_examples_scores_likeness():
    t = learned(n_ng=0)
    same = t.execute({"Image": part("ok", 60)})
    odd = t.execute({"Image": part("other", 61)})
    assert same.outputs["Score"] > 0.85 and same.status == ToolStatus.OK
    assert odd.outputs["Score"] < same.outputs["Score"] - 0.2 and odd.status == ToolStatus.NG
    assert odd.outputs["NG_Samples"] == 0


def test_defect_contrast_limits_modes_and_problems():
    t = make("Defect Contrast", roi=ROI, mode="Learn OK")
    for i in range(vd.MAX_PER_CLASS):
        assert t.execute({"Image": part("ok", i)}).status == ToolStatus.OK
    full = t.execute({"Image": part("ok", 99)})
    assert full.status == ToolStatus.NG and full.outputs["OK_Samples"] == 20 and "20 OK" in full.message
    t.set_param("mode", "Learn NG")
    assert t.execute({"Image": part("ng", 1)}).outputs["NG_Samples"] == 1, "NG examples have their own 20"
    t.set_param("mode", "Clear Model")
    r = t.execute({"Image": part("ok", 1)})
    assert r.outputs["OK_Samples"] == 0 and r.outputs["NG_Samples"] == 0
    t.set_param("mode", "Detect")
    assert t.execute({"Image": part("ok", 1)}).status == ToolStatus.ERROR
    assert run("Defect Contrast", {"Image": part("ok")}, roi=[5, 5, 3, 3], mode="Learn OK").status == ToolStatus.ERROR
    assert run("Defect Contrast", {}, mode="Detect").status == ToolStatus.NG
    broken = make("Defect Contrast", roi=ROI, mode="Detect")
    broken.parameters["samples"] = "junk"
    assert broken.execute({"Image": part("ok")}).status == ToolStatus.ERROR
    f = vd.features(as_gray := cv2.cvtColor(part("ok"), cv2.COLOR_GRAY2BGR)[:, :, 0])
    assert abs(float(np.linalg.norm(f)) - 1.0) < 1e-6
    bright = vd.features(np.clip(part("ok").astype(int) + 40, 0, 255).astype(np.uint8))
    assert float(np.dot(f, bright)) > 0.98, "a uniform brightness change hardly alters it"


@pytest.mark.parametrize("tool_name", ["Surface Defect Filter", "OCV", "Defect Contrast"])
def test_every_module_survives_junk(tool_name):
    for ctx in ({}, {"Image": "x"}, {"Image": np.zeros((0, 0), np.uint8)}, {"Image": np.zeros((20, 20), np.uint8)}, {"Image": np.zeros((50, 50, 3), np.uint8)}):
        for mode in ("Detect", "Train", "Learn OK", "Learn NG", "Clear Model"):
            t = create_tool_instance(tool_name, "t")
            t.set_param("mode", mode)
            r = t.execute(ctx)
            assert r.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR) and r.message is not None
