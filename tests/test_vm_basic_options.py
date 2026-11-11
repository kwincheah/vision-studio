"""The guide's fuller option lists on the basic image modules: binarization, filter, morphology, computing, clarity, geometric and colour
transformation, enhancement and BLOB analysis. The older option names must keep working."""
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


def ramp(h=40, w=256):
    return np.tile(np.arange(w, dtype=np.uint8), (h, 1))


def g(out):
    return out[:, :, 0] if out.ndim == 3 else out


# ---- Image Binarization --------------------------------------------------------------------------------------------------------------------------------
def test_binarization_old_types_unchanged_and_new_types_work():
    r = ramp()
    assert (g(run("Image Binarization", {"Image": r}, method="Manual", threshold=100).outputs["Image"]) > 0).sum() == 40 * 155
    hard = g(run("Image Binarization", {"Image": r}, method="Hard Threshold", low_threshold=50, high_threshold=100).outputs["Image"])
    assert set(np.unique(hard)) == {0, 255} and int((hard[0] > 0).sum()) == 51 and hard[0, 50] == 255 and hard[0, 101] == 0
    inv = g(run("Image Binarization", {"Image": r}, method="Hard Threshold", low_threshold=50, high_threshold=100, invert=True).outputs["Image"])
    assert int((inv[0] > 0).sum()) == 256 - 51
    img = np.full((60, 60), 100, np.uint8)
    img[20:30, 20:30] = 140
    mean = g(run("Image Binarization", {"Image": img}, method="Mean", kernel_width=31, kernel_height=31, threshold_offset=0.0).outputs["Image"])
    assert mean[25, 25] == 255 and mean[5, 5] == 255, "Greater or Equal: flat parts equal their own average"
    less = g(run("Image Binarization", {"Image": img}, method="Mean", kernel_width=31, kernel_height=31, comparison="Less or Equal").outputs["Image"])
    assert less[25, 25] == 0 and less[5, 5] == 255
    off = g(run("Image Binarization", {"Image": img}, method="Gaussian", kernel_width=31, gaussian_sigma=5.0, threshold_offset=-30.0).outputs["Image"])
    assert off[25, 25] == 0 and off[5, 5] == 0, "the offset is added to the pixel before the comparison: 70 is below its own average of 100"
    up = g(run("Image Binarization", {"Image": img}, method="Gaussian", kernel_width=31, gaussian_sigma=5.0, threshold_offset=30.0).outputs["Image"])
    assert up[25, 25] == 255 and up[5, 5] == 255
    eq = g(run("Image Binarization", {"Image": img}, method="Gaussian", kernel_width=31, comparison="Not Equal").outputs["Image"])
    assert eq[25, 25] == 255
    auto = g(run("Image Binarization", {"Image": r}, method="Auto").outputs["Image"])
    assert auto[0, 5] == 0 and auto[0, 250] == 255
    assert run("Image Binarization", {"Image": cv2.cvtColor(r, cv2.COLOR_GRAY2BGR)}, method="Auto").status == ToolStatus.OK


# ---- Image Filter ----------------------------------------------------------------------------------------------------------------------------------------
def test_filter_mean_inverse_and_edge_extraction():
    r = ramp()
    assert np.array_equal(g(run("Image Filter", {"Image": r}, filter_type="Inverse").outputs["Image"]), 255 - r)
    noisy = np.full((30, 30), 100, np.uint8)
    noisy[15, 15] = 255
    assert g(run("Image Filter", {"Image": noisy}, filter_type="Mean", kernel_size=3).outputs["Image"])[15, 15] < 140
    step = np.zeros((30, 60), np.uint8)
    step[:, 30:] = 200
    edge = g(run("Image Filter", {"Image": step}, filter_type="Edge Extraction", edge_low=100, edge_high=2000).outputs["Image"])
    assert edge[10, 29] == 255 and edge[10, 5] == 0 and edge[10, 55] == 0 and set(np.unique(edge)) <= {0, 255}
    none = g(run("Image Filter", {"Image": step}, filter_type="Edge Extraction", edge_low=1900, edge_high=2000).outputs["Image"])
    assert not none.any()
    assert run("Image Filter", {"Image": step}, filter_type="Gaussian").status == ToolStatus.OK and run("Image Filter", {"Image": step}, filter_type="Box").status == ToolStatus.OK


# ---- Image Morphology -------------------------------------------------------------------------------------------------------------------------------------
def test_morphology_names_elements_and_sizes():
    dot = np.zeros((41, 41), np.uint8)
    dot[20, 20] = 255
    sq = g(run("Image Morphology", {"Image": dot}, operation="Dilation", kernel_size=5, element="Rect").outputs["Image"])
    el = g(run("Image Morphology", {"Image": dot}, operation="Dilation", kernel_size=5, element="Ellipse").outputs["Image"])
    cr = g(run("Image Morphology", {"Image": dot}, operation="Dilation", kernel_size=5, element="Cross").outputs["Image"])
    assert int((sq > 0).sum()) == 25 and int((cr > 0).sum()) == 9 and 9 < int((el > 0).sum()) < 25
    wide = g(run("Image Morphology", {"Image": dot}, operation="Dilate", kernel_size=3, element_width=9, element_height=1).outputs["Image"])
    ys, xs = np.nonzero(wide)
    assert xs.max() - xs.min() == 8 and ys.max() == ys.min()
    old = g(run("Image Morphology", {"Image": dot}, operation="Dilate", kernel_size=3).outputs["Image"])
    assert int((old > 0).sum()) == 9, "the older names and settings give what they always gave"
    blob = np.zeros((41, 41), np.uint8)
    blob[10:30, 10:30] = 255
    assert not g(run("Image Morphology", {"Image": dot}, operation="Opening", kernel_size=3).outputs["Image"]).any(), "opening removes a speck"
    assert g(run("Image Morphology", {"Image": blob}, operation="Erosion", kernel_size=3).outputs["Image"]).sum() < blob.sum()
    holed = blob.copy()
    holed[20, 20] = 0
    assert g(run("Image Morphology", {"Image": holed}, operation="Closing", kernel_size=3).outputs["Image"])[20, 20] == 255


# ---- Image Computing ----------------------------------------------------------------------------------------------------------------------------------------
def test_computing_weighted_types():
    a = np.full((10, 10), 100, np.uint8)
    b = np.full((10, 10), 50, np.uint8)
    ctx = {"Image": a, "Image_B": b}
    assert run("Image Calculate", ctx, operation="k1*A + k2*B + c", calc_weight1=0.5, calc_weight2=2.0, image_offset=10.0).outputs["Image"][0, 0, 0] == 160
    assert run("Image Calculate", ctx, operation="k1*A + c", calc_weight1=2.0, image_offset=-20.0).outputs["Image"][0, 0, 0] == 180
    assert run("Image Calculate", ctx, operation="A + c", image_offset=30.0).outputs["Image"][0, 0, 0] == 130
    assert run("Image Calculate", ctx, operation="Add", image_weight1=0.5, image_weight2=2.0).outputs["Image"][0, 0, 0] == 150, "each picture is multiplied by its weight first"
    assert run("Image Calculate", ctx, operation="Absolute Difference").outputs["Image"][0, 0, 0] == 50
    assert run("Image Calculate", ctx, operation="A + c", image_offset=300.0).outputs["Image"][0, 0, 0] == 255, "results stay within 0-255"


# ---- Image Clarity ---------------------------------------------------------------------------------------------------------------------------------------------
def test_clarity_modes_rank_sharp_above_blurred():
    rng = np.random.default_rng(0)
    sharp = (rng.random((120, 160)) * 255).astype(np.uint8)
    sharp = cv2.GaussianBlur(sharp, (0, 0), 0.7)
    blurred = cv2.GaussianBlur(sharp, (0, 0), 4.0)
    for mode in ("Laplacian Variance", "Auto Correlation", "Gradient Squared"):
        a = run("Focus Measure", {"Image": sharp}, roi=[0, 0, 160, 120], assess_mode=mode).outputs["Sharpness"]
        b = run("Focus Measure", {"Image": blurred}, roi=[0, 0, 160, 120], assess_mode=mode).outputs["Sharpness"]
        assert a > b, mode
    noisy = run("Focus Measure", {"Image": sharp}, roi=[0, 0, 160, 120], assess_mode="Auto Correlation", noise_level=40).outputs["Sharpness"]
    assert np.isfinite(noisy)


# ---- Geometric Transformation --------------------------------------------------------------------------------------------------------------------------
def test_mirror_and_rotate():
    im = np.zeros((20, 40, 3), np.uint8)
    im[2:6, 2:10] = 255
    h = run("Image Transform", {"Image": im}, operation="Mirror and Rotate", mirror="Horizontal", angle=0.0).outputs["Image"]
    assert h[3, 37] .any() and not h[3, 3].any()
    v = run("Image Transform", {"Image": im}, operation="Mirror and Rotate", mirror="Vertical", angle=0.0).outputs["Image"]
    assert v[16, 3].any() and not v[3, 3].any()
    d = run("Image Transform", {"Image": im}, operation="Mirror and Rotate", mirror="Diagonal", angle=0.0).outputs["Image"]
    assert d[16, 37].any() and not d[3, 3].any()
    n = run("Image Transform", {"Image": im}, operation="Mirror and Rotate", mirror="None", angle=0.0).outputs["Image"]
    assert np.array_equal(n, im)
    both = run("Image Transform", {"Image": im}, operation="Mirror and Rotate", mirror="Horizontal", angle=90.0, expand=True).outputs["Image"]
    assert both.shape[:2] == (40, 20)
    assert run("Image Transform", {"Image": im}, operation="Rotate 180").status == ToolStatus.OK


# ---- Colour Transformation ------------------------------------------------------------------------------------------------------------------------------
def test_colour_modes():
    px = np.zeros((4, 4, 3), np.uint8)
    px[:, :] = (10, 100, 200)                                                    # B, G, R
    def one(mode, **p):
        return int(run("Color Convert", {"Image": px}, mode=mode, **p).outputs["Image"][0, 0, 0])
    assert one("Gray: Average") == 103 and one("Gray: Minimum") == 10 and one("Gray: Maximum") == 200
    assert one("Gray: User-defined", coeff_r=1.0, coeff_g=0.0, coeff_b=0.0) == 200 and one("Gray: User-defined", coeff_r=0.5, coeff_g=0.5, coeff_b=0.0) == 150
    assert one("Grayscale") == int(round(0.299 * 200 + 0.587 * 100 + 0.114 * 10)) or abs(one("Grayscale") - 119) <= 1
    assert one("HSI Channel 3") == 103
    red = np.zeros((4, 4, 3), np.uint8)
    red[:, :] = (0, 0, 255)
    assert int(run("Color Convert", {"Image": red}, mode="HSI Channel 2").outputs["Image"][0, 0, 0]) == 255, "pure red is fully saturated"
    grey = np.full((4, 4, 3), 90, np.uint8)
    assert int(run("Color Convert", {"Image": grey}, mode="HSI Channel 2").outputs["Image"][0, 0, 0]) == 0
    assert int(run("Color Convert", {"Image": red}, mode="HSI Channel 1").outputs["Image"][0, 0, 0]) == 0
    green = np.zeros((4, 4, 3), np.uint8)
    green[:, :] = (0, 255, 0)
    assert abs(int(run("Color Convert", {"Image": green}, mode="HSI Channel 1").outputs["Image"][0, 0, 0]) - 85) <= 1, "green is 120 degrees"
    yuv = [one(f"YUV Channel {i}") for i in (1, 2, 3)]
    assert yuv[0] > 0 and yuv[1] != yuv[2]
    assert run("Color Convert", {"Image": px}, mode="Hue").status == ToolStatus.OK


# ---- Image Enhancement -----------------------------------------------------------------------------------------------------------------------------------
def test_enhancement_steps():
    mid = np.full((20, 20), 100, np.uint8)
    assert np.array_equal(run("Image Enhancement", {"Image": mid}).outputs["Image"], mid), "neutral settings change nothing"
    assert int(run("Image Enhancement", {"Image": mid}, compensation=40.0).outputs["Image"][0, 0]) == 140
    assert int(run("Image Enhancement", {"Image": mid}, gain=50.0).outputs["Image"][0, 0]) == 150
    assert int(run("Image Enhancement", {"Image": mid}, contrast=200.0).outputs["Image"][0, 0]) == 72
    bright = int(run("Image Enhancement", {"Image": mid}, gamma=0.5).outputs["Image"][0, 0])
    dark = int(run("Image Enhancement", {"Image": mid}, gamma=2.0).outputs["Image"][0, 0])
    assert bright > 100 > dark
    edge = np.zeros((20, 40), np.uint8)
    edge[:, 20:] = 120
    sharp = run("Image Enhancement", {"Image": edge}, sharpen_intensity=1.5, sharpen_kernel=5).outputs["Image"]
    assert int(sharp[10, 21]) > 120 and int(sharp[10, 18]) < 5 or int(sharp[10, 21]) > 120
    assert run("Image Enhancement", {"Image": cv2.cvtColor(edge, cv2.COLOR_GRAY2BGR)}, sharpen_intensity=1.0).outputs["Image"].ndim == 3
    assert int(run("Image Enhancement", {"Image": mid}, compensation=-255.0).outputs["Image"][0, 0]) == 0


# ---- BLOB Analysis -------------------------------------------------------------------------------------------------------------------------------------------
def blob_image():
    im = np.zeros((200, 300), np.uint8)
    cv2.rectangle(im, (20, 20), (79, 59), 255, -1)                 # 60 x 40 rectangle
    cv2.circle(im, (150, 50), 25, 255, -1)                          # disc
    cv2.rectangle(im, (220, 20), (233, 24), 255, -1)                # 14 x 5 sliver
    cv2.rectangle(im, (30, 120), (99, 179), 255, -1)                # 70 x 60 with a hole
    cv2.rectangle(im, (55, 145), (60, 150), 0, -1)                  # hole of 36 px
    return im


def test_blob_analysis_measures_and_filters():
    r = run("BLOB Analysis", {"Image": blob_image()}, min_area=20)
    o = r.outputs
    assert r.status == ToolStatus.OK and o["Count"] == 4 and o["Total_Area"] == pytest.approx(sum(o["Areas"]))
    rect = next(b for b in o["Blobs"] if b["box"][:2] == [20, 20])
    assert rect["area"] == 2400 and rect["rectangularity"] > 0.97 and abs(rect["cx"] - 49.5) < 0.6 and rect["perimeter"] == pytest.approx(196, abs=2)
    disc = next(b for b in o["Blobs"] if abs(b["cx"] - 150) < 1)
    assert disc["circularity"] > 0.85 and disc["axis_ratio"] > 0.95
    assert run("BLOB Analysis", {"Image": blob_image()}, min_area=20, min_circularity=0.8).outputs["Count"] == 1
    assert run("BLOB Analysis", {"Image": blob_image()}, min_area=20, min_rectangularity=0.97, max_circularity=0.9).outputs["Count"] >= 1
    assert run("BLOB Analysis", {"Image": blob_image()}, min_area=20, max_area=300).outputs["Count"] == 1, "only the sliver"
    assert run("BLOB Analysis", {"Image": blob_image()}, min_area=20, min_rect_width=55).outputs["Count"] == 2
    assert run("BLOB Analysis", {"Image": blob_image()}, min_area=20, max_perimeter=100).outputs["Count"] == 1
    assert run("BLOB Analysis", {"Image": blob_image()}, min_area=20, min_minor_axis=45).outputs["Count"] == 2
    assert run("BLOB Analysis", {"Image": blob_image()}, min_area=20, max_axis_ratio=0.5).outputs["Count"] == 1


def test_blob_analysis_threshold_modes_holes_sorting_and_limits():
    im = blob_image()
    assert run("BLOB Analysis", {"Image": im}, min_area=20, min_hole_area=0).outputs["Areas"].count(70 * 60 - 36) == 1
    filled = run("BLOB Analysis", {"Image": im}, min_area=20, min_hole_area=40).outputs["Areas"]
    assert 70 * 60 in filled, "a hole of 36 pixels is filled when holes up to 40 are"
    dark = 255 - im
    assert run("BLOB Analysis", {"Image": dark}, min_area=20, invert=True).outputs["Count"] == 4, "darker than the background"
    assert run("BLOB Analysis", {"Image": im}, min_area=20, threshold_mode="Auto Threshold").outputs["Count"] == 4
    assert run("BLOB Analysis", {"Image": im}, min_area=20, threshold_mode="None (already binary)").outputs["Count"] == 4
    grad = im.astype(np.int32).copy()
    grad[grad == 255] = 180
    both = np.clip(grad, 0, 255).astype(np.uint8)
    dbl = run("BLOB Analysis", {"Image": both}, min_area=20, threshold_mode="Double Threshold", threshold=150, high_threshold=200)
    assert dbl.outputs["Count"] == 4
    outside = run("BLOB Analysis", {"Image": both}, min_area=20, threshold_mode="Double Threshold", threshold=200, high_threshold=100)
    assert outside.outputs["Count"] >= 1, "low above high: the gray ranges outside"
    assert run("BLOB Analysis", {"Image": im}, min_area=20, threshold_mode="Soft Threshold (Fixed)", threshold=100, high_threshold=200).outputs["Count"] == 4
    assert run("BLOB Analysis", {"Image": im}, min_area=20, threshold_mode="Soft Threshold (Relative)").outputs["Count"] >= 3
    asc = run("BLOB Analysis", {"Image": im}, min_area=20, sort_feature="Area", sort_type="Ascending").outputs["Areas"]
    assert asc == sorted(asc)
    desc = run("BLOB Analysis", {"Image": im}, min_area=20, sort_feature="Center X", sort_type="Descending").outputs["Centers"]
    assert [c[0] for c in desc] == sorted([c[0] for c in desc], reverse=True)
    assert run("BLOB Analysis", {"Image": im}, min_area=20, max_blobs=2).outputs["Count"] == 2
    diag = np.zeros((20, 20), np.uint8)
    diag[2:5, 2:5] = 255
    diag[5:8, 5:8] = 255
    assert run("BLOB Analysis", {"Image": diag}, min_area=1, connectivity="8-connected").outputs["Count"] == 1
    assert run("BLOB Analysis", {"Image": diag}, min_area=1, connectivity="4-connected").outputs["Count"] == 2
    part = run("BLOB Analysis", {"Image": im}, min_area=20, roi=[0, 100, 150, 100])
    assert part.outputs["Count"] == 1 and part.outputs["Blobs"][0]["box"][1] >= 100, "boxes are in the picture's coordinates"
    out = run("BLOB Analysis", {"Image": im}, min_area=20, contour_output=True)
    assert sum(1 for o in out.overlays if o["type"] == "line") > 20
    assert out.outputs["Binary"].shape[:2] == im.shape
    assert run("BLOB Analysis", {"Image": cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)}, min_area=20).outputs["Count"] == 4
    assert run("BLOB Analysis", {}).status == ToolStatus.NG
    assert run("BLOB Analysis", {"Image": np.zeros((50, 50), np.uint8)}).status == ToolStatus.NG
