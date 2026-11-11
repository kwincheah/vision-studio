"""VisionMaster guide, Image Processing chapter: each missing module, checked against a picture whose right answer is known."""
import json
import math

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance
from apex_vision.tools import vm_image as vi


def run(name, ctx, **params):
    t = create_tool_instance(name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t, t.execute(ctx)


def featureful(h=300, w=520, seed=0):
    """A picture full of corners and edges (random boxes, discs and lines on a soft background), easy to match."""
    rng = np.random.default_rng(seed)
    im = textured(h, w, seed)
    for _ in range(140):
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        kind = rng.integers(0, 3)
        if kind == 0:
            cv2.rectangle(im, (x, y), (x + int(rng.integers(6, 30)), y + int(rng.integers(6, 30))), c, -1)
        elif kind == 1:
            cv2.circle(im, (x, y), int(rng.integers(3, 14)), c, -1)
        else:
            cv2.line(im, (x, y), (x + int(rng.integers(-40, 40)), y + int(rng.integers(-40, 40))), c, 2)
    return im


def textured(h=240, w=320, seed=0):
    """A busy picture (smooth noise blobs) with plenty of detail for matching."""
    rng = np.random.default_rng(seed)
    g = cv2.GaussianBlur(rng.normal(128, 60, (h, w)).astype(np.float32), (0, 0), 3)
    return cv2.cvtColor(np.clip(g, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def ncc(a, b):
    a, b = a.astype(np.float64).ravel(), b.astype(np.float64).ravel()
    a, b = a - a.mean(), b - b.mean()
    return float((a @ b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


NEW = ["Image Combination", "Distortion Correction", "Image Fixture", "Shade Correction", "Affine Transformation",
       "Inverse Affine Transformation", "Ring Expansion", "Copy Fill", "Frame Mean", "Image Normalization", "Image Correction",
       "Image Stitch", "Multiple Images Fusion"]


@pytest.mark.parametrize("name", NEW)
def test_every_module_refuses_a_missing_picture_politely(name):
    _, r = run(name, {})
    assert r.status in (ToolStatus.NG, ToolStatus.ERROR) and r.message


# ---- Image Combination ----------------------------------------------------------------------------------------------------
def test_image_combination_runs_only_the_steps_that_are_on_and_in_the_chosen_order():
    a = textured()
    a = np.clip(a.astype(np.int16) + np.random.default_rng(3).integers(-60, 60, a.shape), 0, 255).astype(np.uint8)       # noisy, so the order matters
    _, none = run("Image Combination", {"Image": a})
    assert np.array_equal(none.outputs["Image"], a) and "nothing" in none.message
    _, b_then_f = run("Image Combination", {"Image": a}, enable_binarization=True, bin_type="Auto", enable_filter=True,
                      filter_type="Median", filter_kernel=7, order="Binarization,Filter")
    _, f_then_b = run("Image Combination", {"Image": a}, enable_binarization=True, bin_type="Auto", enable_filter=True,
                      filter_type="Median", filter_kernel=7, order="Filter,Binarization")
    assert b_then_f.message == "Ran: Binarization, Filter" and f_then_b.message == "Ran: Filter, Binarization"
    assert not np.array_equal(b_then_f.outputs["Image"], f_then_b.outputs["Image"]), "the order matters"
    expect = cv2.medianBlur(vi.binarize(a, "Auto"), 7)
    assert np.array_equal(b_then_f.outputs["Image"], expect)
    _, all_on = run("Image Combination", {"Image": a}, enable_morphology=True, enable_binarization=True, enable_filter=True,
                    enable_enhancement=True, enable_shade=True)
    assert all_on.status == ToolStatus.OK and all_on.message.count(",") == 4


@pytest.mark.parametrize("kind", ["Hard Threshold", "Mean", "Gaussian", "Auto"])
def test_binarize_types_give_a_two_level_picture(kind):
    a = textured()
    out = vi.binarize(a, kind, 120, 140, 15, 15, 2.0, "Greater or Equal", 0.0)
    assert set(np.unique(out)) <= {0, 255} and out.shape == a.shape[:2]
    assert (out == 255).any() and (out == 0).any()


def test_binarize_hard_threshold_keeps_only_the_band_and_comparison_types_differ():
    g = np.tile(np.arange(256, dtype=np.uint8), (4, 1))
    band = vi.binarize(g, "Hard Threshold", 100, 150)
    assert band[0, 99] == 0 and band[0, 100] == 255 and band[0, 150] == 255 and band[0, 151] == 0
    ge = vi.binarize(g, "Mean", kw=31, kh=1, compare="Greater or Equal")
    le = vi.binarize(g, "Mean", kw=31, kh=1, compare="Less or Equal", offset=0)
    assert not np.array_equal(ge, le)


def test_filter_enhance_morphology_shade_functions():
    a = textured()
    assert np.array_equal(vi.filter_image(a, "Inverse"), 255 - a)
    edges = vi.filter_image(a, "Edge Extraction", edge_low=5, edge_high=1000)
    assert set(np.unique(edges)) <= {0, 255}
    flat = np.full((20, 20), 100, np.uint8)
    assert np.all(vi.enhance(flat, contrast=100, gamma=1, gain=0, offset=20) == 120), "curdst = offset + cursrc * gain(0)"
    assert vi.enhance(flat, gamma=0.5).mean() > 100 and vi.enhance(flat, gamma=2.0).mean() < 100
    sq = np.zeros((40, 40), np.uint8)
    sq[15:25, 15:25] = 255
    assert vi.morphology(sq, "Dilation", "Rect", 5, 5, 1).sum() > sq.sum() > vi.morphology(sq, "Erosion", "Rect", 5, 5, 1).sum()
    assert vi.morphology(sq, "Opening", "Ellipse", 3, 3, 1).sum() <= sq.sum()


# ---- Distortion Correction ------------------------------------------------------------------------------------------------
def _calibration_file(tmp_path, k1=-0.3, homography=None):
    k = np.array([[400, 0, 320], [0, 400, 240], [0, 0, 1]], float)
    data = {"camera_matrix": k.tolist(), "dist_coeffs": [k1, 0.1, 0, 0, 0], "image_size": [640, 480], "rms_error": 0.1}
    if homography is not None:
        data["homography"] = np.array(homography).tolist()
    p = tmp_path / "calib.json"
    p.write_text(json.dumps(data))
    return str(p), k, np.array(data["dist_coeffs"])


def _distorted_line(k, d, y_norm=0.5):
    xs = np.linspace(-0.7, 0.7, 500)
    obj = np.stack([xs, np.full_like(xs, y_norm), np.ones_like(xs)], axis=1)
    px, _ = cv2.projectPoints(obj, np.zeros(3), np.zeros(3), k, d)
    im = np.zeros((480, 640), np.uint8)
    cv2.polylines(im, [np.round(px.reshape(-1, 2)).astype(np.int32)], False, 255, 1)
    return im


def _line_wobble(gray):
    ys = [np.mean(np.nonzero(gray[:, x] > 100)[0]) for x in range(100, 540, 8) if (gray[:, x] > 100).any()]
    return float(np.std(ys)), len(ys)


def test_distortion_correction_straightens_a_bent_line(tmp_path):
    f, k, d = _calibration_file(tmp_path)
    bent = _distorted_line(k, d)
    before, _ = _line_wobble(bent)
    _, r = run("Distortion Correction", {"Image": bent}, calibration_file=f, correction_mode="Radial Distortion")
    assert r.status == ToolStatus.OK
    after, n = _line_wobble(cv2.threshold(as_gray(r.outputs["Image"]), 60, 255, cv2.THRESH_BINARY)[1])
    assert n > 20 and before > 5 and after < before * 0.35, (before, after)


def as_gray(a):
    return a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)


def test_distortion_correction_modes_and_errors(tmp_path):
    f, _, _ = _calibration_file(tmp_path)
    a = textured(480, 640)
    assert run("Distortion Correction", {"Image": a})[1].status == ToolStatus.ERROR
    assert "not found" in run("Distortion Correction", {"Image": a}, calibration_file=str(tmp_path / "no.json"))[1].message
    assert "perspective" in run("Distortion Correction", {"Image": a}, calibration_file=f, correction_mode="Perspective Distortion")[1].message.lower()
    fh, _, _ = _calibration_file(tmp_path, homography=[[1, 0, 25], [0, 1, 10], [0, 0, 1]])
    r = run("Distortion Correction", {"Image": a}, calibration_file=fh, correction_mode="Perspective Distortion")[1]
    assert r.status == ToolStatus.OK and np.array_equal(r.outputs["Image"][10:, 25:], a[:-10, :-25])
    both = run("Distortion Correction", {"Image": a}, calibration_file=fh, correction_mode="Radial Perspective Distortion")[1]
    assert both.status == ToolStatus.OK and both.outputs["Image"].shape == a.shape
    t = create_tool_instance("Distortion Correction", "t")
    t.set_param("calibration_file", f)
    assert t.execute({"Image": as_gray(a)}).outputs["Image"].ndim in (2, 3), "grey pictures work too"


# ---- Image Fixture ----------------------------------------------------------------------------------------------------------
def _moved(img, dx, dy, ang, about):
    m = cv2.getRotationMatrix2D(about, ang, 1.0)
    m[0, 2] += dx
    m[1, 2] += dy
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]))


def test_image_fixture_puts_a_shifted_and_turned_part_back_on_the_reference():
    ref = textured(300, 400, 4)
    ref[100:200, 150:260] = 255
    ref[130:150, 170:240] = 0
    moved = _moved(ref, 12, -8, 6.0, (200, 150))
    before = ncc(moved, ref)
    # By Point: the part was found at (212, 142), turned 6 degrees; the reference is (200, 150), 0 degrees
    t, r = run("Image Fixture", {"Image": moved, "Run_Point": (212, 142), "Run_Angle": 6.0}, mode="By Point",
               ref_point=[200, 150], ref_angle=0.0)
    assert r.status == ToolStatus.OK and r.outputs["Matrix"] and np.array(r.outputs["Matrix"]).shape == (2, 3)
    core = (slice(100, 200), slice(150, 260))
    assert ncc(r.outputs["Image"][core], ref[core]) > 0.95 > before + 0.05 or ncc(r.outputs["Image"][core], ref[core]) > 0.9
    # By Info: the Position Correction numbers
    _, info = run("Image Fixture", {"Image": moved, "Delta_X": 12.0, "Delta_Y": -8.0, "Delta_Angle": 6.0}, mode="By Info",
                  ref_point=[200, 150], ref_angle=0.0)
    assert np.array_equal(info.outputs["Image"], r.outputs["Image"]) or ncc(info.outputs["Image"][core], ref[core]) > 0.9
    assert run("Image Fixture", {"Image": moved}, mode="By Info")[1].status == ToolStatus.NG
    # By Coordinate: typed values
    _, c = run("Image Fixture", {"Image": moved}, mode="By Coordinate", ref_point=[200, 150], run_point=[212, 142], ref_angle=0.0, run_angle=6.0)
    assert ncc(c.outputs["Image"][core], ref[core]) > 0.9
    _, same = run("Image Fixture", {"Image": ref}, mode="By Coordinate", ref_point=[200, 150], run_point=[200, 150])
    assert np.array_equal(same.outputs["Image"], ref), "nothing moved: nothing changes"


# ---- Shade Correction -------------------------------------------------------------------------------------------------------
def test_shade_correction_removes_a_lighting_gradient_but_keeps_the_detail():
    rng = np.random.default_rng(1)
    ramp = np.tile(np.linspace(40, 200, 300, dtype=np.float32), (200, 1))
    detail = np.zeros((200, 300), np.float32)
    detail[90:110, 140:160] = 40
    a = np.clip(ramp + detail + rng.normal(0, 1, ramp.shape), 0, 255).astype(np.uint8)
    _, r = run("Shade Correction", {"Image": a}, kernel_size=20, gain=10.0, compensation=128, direction="XY")
    out = r.outputs["Image"].astype(np.float32)
    assert np.std(a[20:60, :].mean(axis=0)) > 40, "the input varies strongly left to right"
    assert np.std(out[20:60, 30:270].mean(axis=0)) < 8, "the lighting gradient is gone"
    assert out[100, 150] - out[40, 150] > 20 and out[95:105, 142:158].mean() > out[20:40, 142:158].mean() + 15, "the feature is still there"
    noisy = run("Shade Correction", {"Image": a}, kernel_size=20, noise=250)[1].outputs["Image"]
    assert np.all(noisy == 128), "everything weaker than the noise level is flattened to the compensation value"
    assert run("Shade Correction", {"Image": a}, direction="X")[1].status == ToolStatus.OK


# ---- Affine Transformation / Inverse ------------------------------------------------------------------------------------------
def test_affine_transformation_cuts_and_scales_a_region():
    a = textured(300, 400, 2)
    _, r = run("Affine Transformation", {"Image": a}, roi=[50, 60, 120, 80], roi_angle=0.0, scale=1.0, aspect_ratio=1.0)
    assert r.outputs["Width"] == 120 and r.outputs["Height"] == 80
    assert np.abs(r.outputs["Image"].astype(int) - a[60:140, 50:170].astype(int)).max() <= 1
    _, big = run("Affine Transformation", {"Image": a}, roi=[50, 60, 120, 80], scale=2.0, aspect_ratio=0.5)
    assert big.outputs["Width"] == 240 and big.outputs["Height"] == 80
    _, nn = run("Affine Transformation", {"Image": a}, roi=[50, 60, 120, 80], scale=2.0, interpolation="Nearest Neighbor")
    assert len(np.unique(nn.outputs["Image"][:, :, 0])) <= len(np.unique(a[60:140, 50:170, 0]))
    # a turned region: draw a pattern in a turned rectangle, then cut it straight
    pattern = textured(80, 140, 9)
    canvas = np.zeros((300, 400, 3), np.uint8)
    corners = vi.roi_corners([130, 110, 140, 80], 25.0)
    m = cv2.getAffineTransform(np.array([[0, 0], [140, 0], [140, 80]], np.float32), corners[:3])
    canvas = cv2.warpAffine(pattern, m, (400, 300))
    _, turned = run("Affine Transformation", {"Image": canvas}, roi=[130, 110, 140, 80], roi_angle=25.0)
    assert turned.outputs["Image"].shape[:2] == (80, 140) and ncc(turned.outputs["Image"][5:-5, 5:-5], pattern[5:-5, 5:-5]) > 0.97
    _, edge = run("Affine Transformation", {"Image": a}, roi=[350, 250, 100, 100], fill_mode="Copy Nearby")
    assert edge.outputs["Image"][-1, -1].tolist() == a[-1, -1].tolist(), "'copy nearby' repeats the border"
    _, const = run("Affine Transformation", {"Image": a}, roi=[350, 250, 100, 100], fill_mode="Constant", fill_value=7)
    assert const.outputs["Image"][-1, -1].tolist() == [7, 7, 7]
    assert run("Affine Transformation", {"Image": a}, roi=[10, 10, 0, 0])[1].status == ToolStatus.ERROR


def test_inverse_affine_puts_a_cut_region_back_where_it_came_from():
    a = textured(300, 400, 6)
    roi, ang = [120, 90, 140, 90], 20.0
    _, cut = run("Affine Transformation", {"Image": a}, roi=roi, roi_angle=ang)
    base = np.full((300, 400, 3), 33, np.uint8)
    _, back = run("Inverse Affine Transformation", {"Image": cut.outputs["Image"], "Base_Image": base}, roi=roi, roi_angle=ang)
    out = back.outputs["Image"]
    corners = vi.roi_corners(roi, ang)
    mask = np.zeros((300, 400), np.uint8)
    cv2.fillConvexPoly(mask, np.round(corners).astype(np.int32), 255)
    inner = cv2.erode(mask, np.ones((9, 9), np.uint8)) > 0
    assert ncc(out[inner], a[inner]) > 0.95, "inside the region it is the original picture again"
    assert np.all(out[cv2.dilate(mask, np.ones((9, 9), np.uint8)) == 0] == 33), "outside the region the base is untouched"
    _, blank = run("Inverse Affine Transformation", {"Image": cut.outputs["Image"]}, roi=roi, roi_angle=ang, base_width=200, base_height=150, base_fill=9)
    assert blank.outputs["Image"].shape[:2] == (150, 200) and blank.outputs["Image"][0, 0].tolist() == [9, 9, 9]


# ---- Ring Expansion ------------------------------------------------------------------------------------------------------------
def test_ring_expansion_unrolls_a_ring_and_the_directions_work():
    a = np.zeros((300, 300, 3), np.uint8)
    cx, cy = 150, 150
    for ang in (0, 90):                                                           # radial marks at 0 deg (right) and 90 deg (up)
        x, y = cx + 100 * math.cos(math.radians(ang)), cy - 100 * math.sin(math.radians(ang))
        cv2.circle(a, (int(round(x)), int(round(y))), 6, (255, 255, 255), -1)
    params = dict(center=[cx, cy], inner_radius=80.0, outer_radius=120.0, start_angle=0.0, arc_angle=360.0)
    _, r = run("Ring Expansion", {"Image": a}, direction="Counterclockwise", **params)
    out = r.outputs["Image"]
    w, h = r.outputs["Width"], r.outputs["Height"]
    assert h == 40 and abs(w - int(round(2 * math.pi * 100))) <= 2
    cols = np.nonzero(out[:, :, 0].max(axis=0) > 128)[0]
    first, second = cols[cols < w * 0.1].mean(), cols[(cols > w * 0.15) & (cols < w * 0.35)].mean()
    assert abs(second / w - 0.25) < 0.02, "the 90 degree mark is a quarter of the way along"
    rows = np.nonzero(out[:, :, 0].max(axis=1) > 128)[0]
    assert abs(rows.mean() - 20) < 3, "the marks sit mid-way between the inner and outer radius"
    _, cw = run("Ring Expansion", {"Image": a}, direction="Clockwise", **params)
    cols_cw = np.nonzero(cw.outputs["Image"][:, :, 0].max(axis=0) > 128)[0]
    assert abs(cols_cw[(cols_cw > w * 0.6) & (cols_cw < w * 0.9)].mean() / w - 0.75) < 0.02
    _, flipped = run("Ring Expansion", {"Image": a}, radial_direction="Outside to Inside", direction="Counterclockwise", **params)
    assert np.array_equal(flipped.outputs["Image"], out[::-1])
    _, narrow = run("Ring Expansion", {"Image": a}, output_width=100, **params)
    assert narrow.outputs["Width"] == 100 and narrow.outputs["Image"].shape[1] == 100
    assert run("Ring Expansion", {"Image": a}, center=[150, 150], inner_radius=50.0, outer_radius=40.0)[1].status == ToolStatus.ERROR


# ---- Copy Fill ----------------------------------------------------------------------------------------------------------------------
def test_copy_fill_fills_inside_and_outside_or_copies_the_edge_outwards():
    a = textured(200, 300, 3)
    _, f = run("Copy Fill", {"Image": a}, process_type="Fill", roi=[100, 60, 80, 60], fill_outside=10, fill_inside=250)
    out = f.outputs["Image"]
    assert np.all(out[60:120, 100:180] == 250) and np.all(out[:60] == 10) and np.all(out[:, :100] == 10)
    _, c = run("Copy Fill", {"Image": a}, process_type="Copy", roi=[100, 60, 80, 60], roi_shape="Ellipse", fill_outside=0)
    out = c.outputs["Image"]
    assert np.array_equal(out[90, 140], a[90, 140]), "the region keeps its own pixels"
    corner = out[61, 101]                                                        # in the rectangle, outside the ellipse
    assert corner.tolist() != [0, 0, 0] and np.all(out[:60] == 0) and np.all(out[:, :100] == 0), "corners are filled from the region, the rest is outside"
    ys, xs = np.nonzero(cv2.ellipse(np.zeros((200, 300), np.uint8), (140, 90), (40, 30), 0, 0, 360, 255, -1))
    assert any(np.array_equal(corner, a[y, x]) for y, x in zip(ys[::7], xs[::7])), "a copied corner is an existing region pixel"


# ---- Frame Mean ---------------------------------------------------------------------------------------------------------------------
def test_frame_mean_reduces_noise_and_honours_ignore_clear_and_the_roi():
    rng = np.random.default_rng(0)
    base = np.full((60, 80), 120, np.float32)
    t = create_tool_instance("Frame Mean", "t")
    t.set_param("max_frames", 100)
    stds = []
    for i in range(16):
        frame = np.clip(base + rng.normal(0, 20, base.shape), 0, 255).astype(np.uint8)
        r = t.execute({"Image": frame})
        stds.append(float(r.outputs["Image"].astype(np.float32).std()))
    assert r.outputs["Count"] == 16 and stds[0] > 15 and stds[-1] < stds[0] / 3, stds
    n = r.outputs["Count"]
    assert t.execute({"Image": frame, "Ignore": True}).outputs["Count"] == n, "an ignored picture is not added"
    assert t.execute({"Image": frame, "Clear": True}).outputs["Count"] == 1, "clear starts over (with the current picture)"
    t.set_param("max_frames", 3)
    for _ in range(6):
        r = t.execute({"Image": frame})
    assert r.outputs["Count"] == 3, "only the last 3 are kept"
    t2 = create_tool_instance("Frame Mean", "t2")
    t2.set_param("roi", [10, 10, 20, 20])
    f1, f2 = np.full((60, 80), 100, np.uint8), np.full((60, 80), 200, np.uint8)
    t2.execute({"Image": f1})
    out = t2.execute({"Image": f2}).outputs["Image"]
    assert out[15, 15] == 150 and out[50, 70] == 200, "only the region is averaged"


# ---- Image Normalization ------------------------------------------------------------------------------------------------------------
def test_image_normalization_three_ways():
    rng = np.random.default_rng(5)
    low = np.clip(rng.normal(100, 6, (120, 160)), 0, 255).astype(np.uint8)
    _, eq = run("Image Normalization", {"Image": low}, normalization_type="Histogram Equalization")
    assert eq.outputs["Image"].std() > low.std() * 3
    _, hn = run("Image Normalization", {"Image": low}, normalization_type="Histogram Normalization", left_ratio=1.0, right_ratio=1.0, min_gray=10, max_gray=240)
    out = hn.outputs["Image"]
    assert 5 <= int(out.min()) <= 12 and out.max() == 240 or out.max() >= 235
    assert 8 <= np.percentile(out, 1) <= 40 and np.percentile(out, 99) >= 200
    _, sd = run("Image Normalization", {"Image": low}, normalization_type="Standard Deviation Normalization", target_mean=140, target_std=30.0)
    o = sd.outputs["Image"].astype(np.float32)
    assert abs(o.mean() - 140) < 2 and abs(o.std() - 30) < 3
    colour = cv2.cvtColor(low, cv2.COLOR_GRAY2BGR)
    colour[:, :80, 2] = 200
    _, cn = run("Image Normalization", {"Image": colour}, normalization_type="Histogram Equalization")
    assert cn.outputs["Image"].shape == colour.shape and cn.outputs["Image"][:, :80, 2].mean() > cn.outputs["Image"][:, 80:, 2].mean() * 0.9
    flat = np.full((20, 20), 90, np.uint8)
    assert run("Image Normalization", {"Image": flat}, normalization_type="Standard Deviation Normalization", target_mean=77)[1].outputs["Image"].min() == 77


# ---- Image Correction -----------------------------------------------------------------------------------------------------------------
def test_image_correction_is_neutral_at_zero_and_acts_on_the_edges_not_the_middle():
    a = textured(240, 320, 8)
    _, neutral = run("Image Correction", {"Image": a}, expansion_amount=0.0, scaling_amount=0.0)
    assert np.abs(neutral.outputs["Image"].astype(int) - a.astype(int)).max() <= 1
    _, barrel = run("Image Correction", {"Image": a}, expansion_amount=40.0, scaling_amount=0.0)
    o = barrel.outputs["Image"]
    centre = (slice(100, 140), slice(140, 180))
    assert np.abs(o[centre].astype(int) - a[centre].astype(int)).mean() < 2, "the middle hardly moves"
    assert np.abs(o[:30, :40].astype(int) - a[:30, :40].astype(int)).mean() > 3, "the corners move a lot"
    _, pin = run("Image Correction", {"Image": a}, expansion_amount=-40.0)
    assert not np.array_equal(pin.outputs["Image"], o)
    _, zoom = run("Image Correction", {"Image": a}, expansion_amount=0.0, scaling_amount=100.0)
    z = zoom.outputs["Image"]
    assert ncc(z[100:140, 140:180], cv2.resize(a[110:130, 150:170], (40, 40), interpolation=cv2.INTER_LINEAR)) > 0.97, "+100% doubles the size"


# ---- Image Stitch ---------------------------------------------------------------------------------------------------------------------
def test_hard_stitch_lays_pictures_in_a_grid_in_either_direction():
    tiles = [np.full((40, 60, 3), 40 * (i + 1), np.uint8) for i in range(4)]
    ctx = {f"Image_{i}": tiles[i] for i in range(4)}
    _, x = run("Image Stitch", ctx, stitch_number=4, rows=2, columns=2, stitch_direction="X")
    o = x.outputs["Image"]
    assert o.shape == (80, 120, 3) and o[0, 0, 0] == 40 and o[0, 60, 0] == 80 and o[40, 0, 0] == 120 and o[40, 60, 0] == 160
    _, y = run("Image Stitch", ctx, stitch_number=4, rows=2, columns=2, stitch_direction="Y")
    o = y.outputs["Image"]
    assert o[0, 0, 0] == 40 and o[40, 0, 0] == 80 and o[0, 60, 0] == 120
    assert run("Image Stitch", {"Image_0": tiles[0]}, stitch_number=2)[1].status == ToolStatus.NG
    _, fill = run("Image Stitch", {"Image_0": tiles[0]}, stitch_number=2, auto_fill=True)
    assert fill.status == ToolStatus.OK and fill.outputs["Image"].shape == (40, 120, 3) and fill.outputs["Image"][0, 70, 0] == 0
    assert run("Image Stitch", ctx, stitch_number=4, rows=1, columns=2)[1].status == ToolStatus.ERROR
    _, cut = run("Image Stitch", ctx, stitch_number=4, rows=2, columns=2, cut_ratio=10)
    assert cut.outputs["Image"].shape[0] < 80


def test_single_source_collects_pictures_over_several_runs():
    t = create_tool_instance("Image Stitch", "t")
    t.set_param("input_mode", "Single Source")
    t.set_param("stitch_number", 3)
    t.set_param("columns", 3)
    for i in range(2):
        r = t.execute({"Image_0": np.full((20, 30, 3), 50 * (i + 1), np.uint8)})
        assert r.status == ToolStatus.NG and r.outputs["Count"] == i + 1
    r = t.execute({"Image_0": np.full((20, 30, 3), 150, np.uint8)})
    assert r.status == ToolStatus.OK and r.outputs["Image"].shape == (20, 90, 3)
    assert t.execute({"Image_0": np.full((20, 30, 3), 9, np.uint8)}).status == ToolStatus.NG, "auto clear: it starts collecting again"


@pytest.mark.parametrize("merge", ["Merge Mean", "Merge Min", "Merge Max", "Merge Uncover"])
def test_model_stitch_rebuilds_a_scene_from_overlapping_pictures(merge):
    scene = featureful(300, 520, 11)
    a, b = scene[:, :300].copy(), scene[:, 220:].copy()                           # 80 px of overlap
    _, r = run("Image Stitch", {"Image_0": a, "Image_1": b}, stitch_type="Model Stitch", stitch_number=2, merge_type=merge)
    assert r.status == ToolStatus.OK, r.message
    out = r.outputs["Image"]
    assert abs(out.shape[1] - 520) <= 6 and abs(out.shape[0] - 300) <= 6, out.shape
    h, w = min(out.shape[0], 300), min(out.shape[1], 520)
    assert ncc(out[:h, :w], scene[:h, :w]) > 0.97, "the stitched picture is the original scene again"
    right = (slice(20, h - 20), slice(330, w - 20))                                # the part that came only from the second picture
    assert ncc(out[right], scene[right]) > 0.97


def test_model_stitch_reports_pictures_that_do_not_overlap():
    a = featureful(200, 200, 1)
    b = featureful(200, 200, 99)
    r = run("Image Stitch", {"Image_0": a, "Image_1": b}, stitch_type="Model Stitch", stitch_number=2)[1]
    assert r.status == ToolStatus.NG and "overlap" in r.message


def test_merge_types_order_in_an_overlap():
    lo, hi = np.full((20, 20, 3), 50, np.uint8), np.full((20, 20, 3), 150, np.uint8)
    masks = [np.ones((20, 20), bool)] * 2
    assert vi._merge([lo, hi], masks, "Merge Min")[0, 0, 0] == 50 and vi._merge([lo, hi], masks, "Merge Max")[0, 0, 0] == 150
    assert vi._merge([lo, hi], masks, "Merge Mean")[0, 0, 0] == 100 and vi._merge([lo, hi], masks, "Merge Uncover")[0, 0, 0] == 50


# ---- Multiple Images Fusion -----------------------------------------------------------------------------------------------------------
def test_multiple_images_fusion_finds_relief_that_flat_lighting_hides():
    h, w = 120, 160
    base = np.full((h, w), 120, np.float32)
    pics = []
    for k, (sx, sy) in enumerate([(1, 0), (-1, 0), (0, 1), (0, -1)]):             # a bump lit from four sides throws shadows
        im = base.copy()
        yy, xx = np.mgrid[0:h, 0:w]
        bump = ((xx - 80) ** 2 + (yy - 60) ** 2) < 18 ** 2
        im[np.roll(bump, (sy * 6, sx * 6), axis=(0, 1)) & ~bump] = 50                # the shadow falls on one side
        im[bump] += 20
        pics.append(np.clip(im, 0, 255).astype(np.uint8))
    ctx = {f"Image_{i}": p for i, p in enumerate(pics)}
    _, r = run("Multiple Images Fusion", ctx, halo_removal=1, filter_size=3)
    assert r.status == ToolStatus.OK and r.outputs["Reflection"].shape == (h, w) and r.outputs["Shadow"].shape == (h, w)
    shadow = r.outputs["Shadow"].astype(int)
    ring = np.zeros((h, w), bool)
    yy, xx = np.mgrid[0:h, 0:w]
    ring[(((xx - 80) ** 2 + (yy - 60) ** 2) > 19 ** 2) & (((xx - 80) ** 2 + (yy - 60) ** 2) < 26 ** 2)] = True
    far = ((xx < 30) | (xx > 130))
    assert shadow[ring].mean() < shadow[far].mean() - 8, "the relief shows up dark; flat areas stay light"
    for kind, key in (("Reflection", "Reflection"), ("Shadow", "Shadow"), ("All", "Reflection")):
        picked = run("Multiple Images Fusion", ctx, output_type=kind, halo_removal=1, filter_size=3)[1].outputs["Image"]
        assert np.array_equal(picked, r.outputs[key]), f"output type {kind} gives the {key} picture"
    bright = run("Multiple Images Fusion", ctx, enhancement=True, background_brightness=230, contrast_coefficient=100)[1].outputs["Shadow"]
    dark = run("Multiple Images Fusion", ctx, enhancement=True, background_brightness=60, contrast_coefficient=100)[1].outputs["Shadow"]
    assert bright[far].mean() > dark[far].mean() + 100, "the background brightness setting moves the background level"
    strong = run("Multiple Images Fusion", ctx, enhancement=True, background_brightness=230, contrast_coefficient=400)[1].outputs["Shadow"]
    assert (230 - strong[ring].mean()) > (230 - bright[ring].mean()), "a higher contrast coefficient darkens the shadows more"
    assert run("Multiple Images Fusion", {"Image_0": pics[0], "Image_1": pics[1]})[1].status == ToolStatus.NG
    assert run("Multiple Images Fusion", {"Image_0": pics[0], "Image_1": pics[1], "Image_2": pics[2][:50]})[1].status == ToolStatus.ERROR
    dirx = run("Multiple Images Fusion", ctx, direction_enhancement="X Direction", direction_grade=8)[1]
    assert not np.array_equal(dirx.outputs["Shadow"], r.outputs["Shadow"])
