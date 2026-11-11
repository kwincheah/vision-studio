"""VisionMaster guide, Deep Learning chapter: Classification Registration, DL Image Retrieval, DL Instance Segment, DL Image Defect Prediction."""
import json
import os

import cv2
import numpy as np
import pytest

onnx = pytest.importorskip("onnx")

import apex_vision.tools  # noqa: E402,F401
from apex_vision.core import dl_engine as dl  # noqa: E402
from apex_vision.core.base_tool import ToolStatus  # noqa: E402
from apex_vision.core.registry import create_tool_instance  # noqa: E402
from apex_vision.tools import vm_dl2 as v2  # noqa: E402


def make(tool_name, /, **params):
    t = create_tool_instance(tool_name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t


def run(tool_name, ctx=None, /, **params):
    return make(tool_name, **params).execute(ctx or {})


def save_model(path, in_shape, build, outputs_spec, meta=None):
    from onnx import TensorProto, helper
    inp = helper.make_tensor_value_info("input", TensorProto.FLOAT, in_shape)
    nodes, inits = build(helper)
    graph = helper.make_graph(nodes, "g", [inp], [helper.make_tensor_value_info(n, TensorProto.FLOAT, s) for n, s in outputs_spec], initializer=inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))
    if meta is not None:
        with open(str(path).rsplit(".", 1)[0] + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f)
    return str(path)


def constant_outputs(path, in_shape, arrays, meta=None):
    from onnx import numpy_helper

    def build(helper):
        nodes = [helper.make_node("ReduceMean", ["input"], ["m"], keepdims=0), helper.make_node("Mul", ["m", "zero"], ["z"])]
        inits = [numpy_helper.from_array(np.zeros((), np.float32), "zero")]
        for i, arr in enumerate(arrays):
            inits.append(numpy_helper.from_array(np.asarray(arr, np.float32), f"c{i}"))
            nodes.append(helper.make_node("Add", ["z", f"c{i}"], [f"out{i}"]))
        return nodes, inits
    return save_model(path, in_shape, build, [(f"out{i}", list(np.asarray(a).shape)) for i, a in enumerate(arrays)], meta)


def shape_image(kind, seed=0):
    rng = np.random.default_rng(seed)
    im = np.full((100, 100, 3), 230, np.uint8)
    c = (50 + int(rng.integers(-5, 6)), 50 + int(rng.integers(-5, 6)))
    if kind == "red circle":
        cv2.circle(im, c, 28 + int(rng.integers(-3, 4)), (30, 30, 220), -1)
    elif kind == "blue square":
        s = 26 + int(rng.integers(-3, 4))
        cv2.rectangle(im, (c[0] - s, c[1] - s), (c[0] + s, c[1] + s), (220, 60, 30), -1)
    else:
        pts = np.array([[c[0], c[1] - 30], [c[0] - 30, c[1] + 25], [c[0] + 30, c[1] + 25]])
        cv2.fillPoly(im, [pts], (40, 200, 40))
    return np.clip(im.astype(np.float32) + rng.normal(0, 4, im.shape), 0, 255).astype(np.uint8)


KINDS = ["red circle", "blue square", "green triangle"]


# ---- Classification Registration --------------------------------------------------------------------------------------------------------------------------
def registered(**extra):
    t = make("Classification Registration", mode="Register Image", **extra)
    for k in KINDS:
        t.set_param("category", k)
        for i in range(3):
            assert t.execute({"Image": shape_image(k, i)}).status == ToolStatus.OK
    t.set_param("mode", "Search")
    return t


def test_register_then_search():
    t = registered()
    for k in KINDS:
        r = t.execute({"Image": shape_image(k, 40)})
        assert r.status == ToolStatus.OK and r.outputs["Class"] == k and r.outputs["Similarity"] > 0.8, (k, r.outputs["Top"])
    r = t.execute({"Image": shape_image("red circle", 41)})
    assert r.outputs["Categories"] == {k: 3 for k in KINDS} and len(r.outputs["Top"]) <= 3
    sims = [x["similarity"] for x in r.outputs["Top"]]
    assert sims == sorted(sims, reverse=True)
    t.set_param("top_k", 1)
    assert len(t.execute({"Image": shape_image("blue square", 42)}).outputs["Top"]) == 1


def test_similarity_floor_and_unknown_pictures():
    t = registered(min_similarity=0.99)
    r = t.execute({"Image": shape_image("red circle", 50)})
    assert r.status in (ToolStatus.OK, ToolStatus.NG)
    t.set_param("min_similarity", 0.999999)
    far = t.execute({"Image": np.full((100, 100, 3), 90, np.uint8)})
    assert far.status == ToolStatus.NG and far.outputs["Class"] == "" and "closest" in far.message and far.outputs["Top"] == []


def test_registering_part_of_a_picture_and_whole_folders(tmp_path):
    sheet = np.full((100, 300, 3), 230, np.uint8)
    sheet[:, :100] = shape_image("red circle", 1)
    sheet[:, 200:] = shape_image("blue square", 2)
    t = make("Classification Registration", mode="Register Image", category="sq", roi=[200, 0, 100, 100])
    assert t.execute({"Image": sheet}).status == ToolStatus.OK
    t.set_param("mode", "Search")
    t.set_param("roi", [0, 0, 0, 0])
    assert t.execute({"Image": shape_image("blue square", 9)}).outputs["Class"] == "sq"
    for k in KINDS[:2]:
        os.makedirs(tmp_path / "set" / k.replace(" ", "_"))
        for i in range(3):
            cv2.imwrite(str(tmp_path / "set" / k.replace(" ", "_") / f"{i}.png"), shape_image(k, i))
    f = make("Classification Registration", mode="Register Folder", register_folder=str(tmp_path / "set"))
    r = f.execute({})
    assert r.status == ToolStatus.OK and r.outputs["Categories"] == {"red_circle": 3, "blue_square": 3}
    f.set_param("mode", "Search")
    assert f.execute({"Image": shape_image("red circle", 30)}).outputs["Class"] == "red_circle"
    flat = tmp_path / "flat"
    flat.mkdir()
    for k in KINDS[:2]:
        for i in range(2):
            cv2.imwrite(str(flat / f"{k.split()[0]}_{i + 1}.png"), shape_image(k, i))
    g = make("Classification Registration", mode="Register Folder", register_folder=str(flat))
    assert g.execute({}).outputs["Categories"] == {"red": 2, "blue": 2}, "files named after their category"
    assert make("Classification Registration", mode="Register Folder", register_folder=str(tmp_path / "none")).execute({}).status == ToolStatus.ERROR
    empty = tmp_path / "empty"
    empty.mkdir()
    assert make("Classification Registration", mode="Register Folder", register_folder=str(empty)).execute({}).status == ToolStatus.NG


def test_gallery_management_and_file(tmp_path):
    path = str(tmp_path / "gal.json")
    t = registered(gallery_file=path)
    assert os.path.isfile(path)
    fresh = make("Classification Registration", gallery_file=path)
    assert fresh.execute({"Image": shape_image("green triangle", 60)}).outputs["Class"] == "green triangle", "a second module reads the saved gallery"
    t.set_param("mode", "Delete Category")
    t.set_param("category", "green triangle")
    r = t.execute({"Image": shape_image("red circle")})
    assert r.status == ToolStatus.OK and "green triangle" not in r.outputs["Categories"]
    assert t.execute({"Image": shape_image("red circle")}).status == ToolStatus.NG, "already deleted"
    t.set_param("mode", "Clear Gallery")
    assert t.execute({"Image": shape_image("red circle")}).outputs["Categories"] == {}
    t.set_param("mode", "Search")
    assert t.execute({"Image": shape_image("red circle")}).status == ToolStatus.ERROR, "empty gallery"
    assert make("Classification Registration", mode="Register Image").execute({"Image": shape_image("red circle")}).status == ToolStatus.ERROR, "no category"
    assert make("Classification Registration", mode="Register Image", category="x", roi=[0, 0, 2, 2]).execute({"Image": shape_image("red circle")}).status in (ToolStatus.ERROR, ToolStatus.OK)
    assert make("Classification Registration", mode="Search").execute({}).status == ToolStatus.NG
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    assert make("Classification Registration", gallery_file=str(bad)).execute({"Image": shape_image("red circle")}).status == ToolStatus.ERROR
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"hello": 1}))
    assert make("Classification Registration", gallery_file=str(wrong)).execute({"Image": shape_image("red circle")}).status == ToolStatus.ERROR
    blocker = tmp_path / "file"
    blocker.write_text("x")
    cant = make("Classification Registration", mode="Register Image", category="c", gallery_file=str(blocker / "sub" / "g.json"))
    assert cant.execute({"Image": shape_image("red circle")}).status == ToolStatus.ERROR


# ---- DL Image Retrieval ---------------------------------------------------------------------------------------------------------------------------------------
def colour_embedder(path):
    """A feature model: the mean of each colour channel (what a real network's embedding would be, in miniature)."""
    from onnx import helper

    def build(h):
        node = h.make_node("ReduceMean", ["input"], ["out"], axes=[2, 3], keepdims=0)
        return [node], []
    return save_model(path, [1, 3, 32, 32], build, [("out", [1, 3])], {"input_size": [32, 32], "normalize": "0 to 1", "rgb": False})


def test_retrieval_with_a_feature_model(tmp_path):
    model = colour_embedder(tmp_path / "embed.onnx")
    t = make("DL Image Retrieval", model_file=model, mode="Register Image", min_similarity=0.0)
    swatches = {"reddish": (30, 30, 220), "greenish": (40, 200, 40), "bluish": (220, 60, 30)}
    for name, col in swatches.items():
        t.set_param("category", name)
        for i in range(2):
            im = np.full((50, 50, 3), col, np.uint8)
            im = np.clip(im.astype(int) + i * 8, 0, 255).astype(np.uint8)
            assert t.execute({"Image": im}).status == ToolStatus.OK
    t.set_param("mode", "Search")
    for name, col in swatches.items():
        r = t.execute({"Image": np.full((80, 80, 3), col, np.uint8)})
        assert r.outputs["Class"] == name and r.outputs["Similarity"] > 0.98
        assert r.outputs["Top"][0]["class"] == name
    assert t.parameters["gallery"]["kind"] == "model" and t.parameters["gallery"]["dim"] == 3
    assert make("DL Image Retrieval", mode="Search").execute({"Image": np.zeros((20, 20, 3), np.uint8)}).status == ToolStatus.ERROR, "no model chosen"
    assert make("DL Image Retrieval", model_file=str(tmp_path / "gone.onnx")).execute({"Image": np.zeros((20, 20, 3), np.uint8)}).status == ToolStatus.ERROR


def test_a_gallery_made_with_another_description_is_refused(tmp_path):
    builtin = registered()
    gal = builtin.parameters["gallery"]
    model = colour_embedder(tmp_path / "embed.onnx")
    t = make("DL Image Retrieval", model_file=model)
    t.parameters["gallery"] = gal
    r = t.execute({"Image": np.full((50, 50, 3), 90, np.uint8)})
    assert r.status == ToolStatus.ERROR and "feature model" in r.message
    t.set_param("mode", "Register Image")
    t.set_param("category", "x")
    assert t.execute({"Image": np.full((50, 50, 3), 90, np.uint8)}).status == ToolStatus.ERROR


# ---- DL Instance Segment ---------------------------------------------------------------------------------------------------------------------------------------
def seg_model(path, dets, labels=("cat", "dog"), nm=4, n_anchor=16):
    """A YOLO-seg style file: detections (1, 4 + classes + nm, N) and prototypes (1, nm, 16, 16): channel 0 lights the left half, channel 1 the right."""
    nc = len(labels)
    out = np.zeros((1, 4 + nc + nm, n_anchor), np.float32)
    for j, (cx, cy, w, h, cls, score, coef) in enumerate(dets):
        out[0, :4, j] = (cx, cy, w, h)
        out[0, 4 + cls, j] = score
        out[0, 4 + nc:, j] = coef
    proto = np.full((1, nm, 16, 16), -10.0, np.float32)
    proto[0, 0, :, :8] = 10.0
    proto[0, 1, :, 8:] = 10.0
    return constant_outputs(path, [1, 3, 64, 64], [out, proto], {"labels": list(labels), "input_size": [64, 64], "task": "segment"})


A = (16, 32, 24, 40, 0, 0.9, [1, 0, 0, 0])
B = (48, 32, 24, 40, 1, 0.8, [0, 1, 0, 0])


def test_instances_get_their_own_masks(tmp_path):
    path = seg_model(tmp_path / "seg.onnx", [A, B])
    pic = np.full((64, 64, 3), 120, np.uint8)
    r = run("DL Instance Segment", {"Image": pic}, model_file=path)
    assert r.status == ToolStatus.OK, r.message
    o = r.outputs
    assert o["Count"] == 2 and o["Classes"] == ["cat", "dog"] and o["Scores"] == pytest.approx([0.9, 0.8])
    b0, b1 = o["Boxes"]
    assert b0 == pytest.approx([4, 12, 24, 40], abs=2) and b1 == pytest.approx([36, 12, 24, 40], abs=2)
    m0, m1 = o["Masks"]
    assert m0[:, :32].any() and not m0[:, 36:].any(), "the first object's mask is the left half"
    assert m1[:, 32:].any() and not m1[:, :30].any()
    assert 400 < int(np.count_nonzero(m0)) <= 24 * 40 and 400 < int(np.count_nonzero(m1)) <= 24 * 40
    lab = o["Mask_Image"]
    assert set(np.unique(lab)) == {0, 1, 2} and lab[30, 10] == 1 and lab[30, 50] == 2
    assert not np.array_equal(o["Image"], pic), "rendered"
    plain = run("DL Instance Segment", {"Image": pic}, model_file=path, render=False)
    assert np.array_equal(plain.outputs["Image"], pic)


def test_instance_filters(tmp_path):
    close = (18, 32, 24, 40, 0, 0.5, [1, 0, 0, 0])
    path = seg_model(tmp_path / "seg.onnx", [A, B, close])
    pic = np.full((64, 64, 3), 120, np.uint8)
    assert run("DL Instance Segment", {"Image": pic}, model_file=path).outputs["Count"] == 2, "the box overlap rule drops the weaker twin"
    both = run("DL Instance Segment", {"Image": pic}, model_file=path, overlap_threshold=1.0, max_mask_overlap=1.0)
    assert both.outputs["Count"] == 3
    masks = run("DL Instance Segment", {"Image": pic}, model_file=path, overlap_threshold=1.0, max_mask_overlap=0.5)
    assert masks.outputs["Count"] == 2, "the mask overlap rule drops it when the boxes were kept"
    assert run("DL Instance Segment", {"Image": pic}, model_file=path, min_confidence=0.85).outputs["Count"] == 1
    assert run("DL Instance Segment", {"Image": pic}, model_file=path, max_number=1).outputs["Count"] == 1
    assert run("DL Instance Segment", {"Image": pic}, model_file=path, min_confidence=0.95).status == ToolStatus.NG
    assert run("DL Instance Segment", {"Image": pic}, model_file=path, labels="mouse, rat").outputs["Classes"] == ["mouse", "rat"]
    assert run("DL Instance Segment", {"Image": pic}, model_file=path, mask_threshold=0.9999).outputs["Count"] >= 0
    roi = run("DL Instance Segment", {"Image": np.full((100, 100, 3), 120, np.uint8)}, model_file=path, roi=[20, 20, 64, 64])
    assert roi.outputs["Boxes"][0][0] >= 20 and roi.outputs["Masks"][0].shape == (100, 100), "boxes and masks are in the picture's own coordinates"


def test_instance_segment_problems(tmp_path):
    pic = np.full((64, 64, 3), 120, np.uint8)
    assert run("DL Instance Segment", {"Image": pic}).status == ToolStatus.ERROR
    assert run("DL Instance Segment", {"Image": pic}, model_file=str(tmp_path / "gone.onnx")).status == ToolStatus.ERROR
    one = constant_outputs(tmp_path / "one.onnx", [1, 3, 64, 64], [np.zeros((1, 10, 16), np.float32)])
    r = run("DL Instance Segment", {"Image": pic}, model_file=one)
    assert r.status == ToolStatus.ERROR and "two outputs" in r.message
    wrong = constant_outputs(tmp_path / "wrong.onnx", [1, 3, 64, 64], [np.zeros((1, 6, 16), np.float32), np.zeros((1, 4, 16, 16), np.float32)])
    assert run("DL Instance Segment", {"Image": pic}, model_file=wrong).status == ToolStatus.ERROR
    assert run("DL Instance Segment", {}, model_file=one).status == ToolStatus.NG


# ---- DL Image Defect Prediction --------------------------------------------------------------------------------------------------------------------------
def test_defect_prediction_gives_a_probability_map(tmp_path):
    amap = np.zeros((1, 1, 16, 16), np.float32)
    amap[0, 0, 4:8, 10:14] = 0.9
    path = constant_outputs(tmp_path / "pred.onnx", [1, 3, 64, 64], [amap], {"input_size": [64, 64]})
    pic = np.full((64, 64, 3), 100, np.uint8)
    r = run("DL Image Defect Prediction", {"Image": pic}, model_file=path, smoothing=0.0)
    o = r.outputs
    assert r.status == ToolStatus.NG and o["Defect_Count"] == 1, r.message
    assert o["Max_Probability"] == pytest.approx(0.9, abs=0.05) and o["Probability_Map"].dtype == np.uint8 and o["Probability_Map"].max() >= 220
    x, y, w, h = o["Boxes"][0]
    assert 36 <= x <= 44 and 12 <= y <= 20 and w >= 12
    assert o["Probability_Map"][:8, :8].max() == 0, "no defect elsewhere"
    assert run("DL Image Defect Prediction", {"Image": pic}, model_file=path, smoothing=0.0, max_defects=1).status == ToolStatus.OK
    assert run("DL Image Defect Prediction", {"Image": pic}, model_file=path, smoothing=0.0, probability_threshold=0.95).outputs["Defect_Count"] == 0
    clean = constant_outputs(tmp_path / "clean.onnx", [1, 3, 64, 64], [np.zeros((1, 1, 16, 16), np.float32)], {"input_size": [64, 64]})
    c = run("DL Image Defect Prediction", {"Image": pic}, model_file=clean)
    assert c.status == ToolStatus.OK and c.outputs["Max_Probability"] == 0.0 and c.outputs["Defect_Count"] == 0


def test_defect_prediction_roi_autoencoder_and_problems(tmp_path):
    amap = np.zeros((1, 1, 16, 16), np.float32)
    amap[0, 0, 8:12, 8:12] = 1.0
    path = constant_outputs(tmp_path / "pred.onnx", [1, 3, 64, 64], [amap], {"input_size": [64, 64]})
    big = np.full((200, 200, 3), 100, np.uint8)
    r = run("DL Image Defect Prediction", {"Image": big}, model_file=path, roi=[100, 100, 64, 64], smoothing=0.0)
    x, y, w, h = r.outputs["Boxes"][0]
    assert x >= 100 and y >= 100 and r.outputs["Probability_Map"].shape == (200, 200) and r.outputs["Probability_Map"][:90].max() == 0
    assert run("DL Image Defect Prediction", {"Image": big}, model_file=path, output_type="Reconstruction (autoencoder)").status == ToolStatus.ERROR
    assert run("DL Image Defect Prediction", {"Image": big}).status == ToolStatus.ERROR
    assert run("DL Image Defect Prediction", {}, model_file=path).status == ToolStatus.NG
    recon = constant_outputs(tmp_path / "recon.onnx", [1, 3, 64, 64], [np.zeros((1, 3, 64, 64), np.float32)], {"input_size": [64, 64], "threshold": 0.1, "normalize": "0 to 1"})
    rr = run("DL Image Defect Prediction", {"Image": np.full((64, 64, 3), 255, np.uint8)}, model_file=recon, output_type="Reconstruction (autoencoder)", smoothing=0.0)
    assert rr.status == ToolStatus.NG and rr.outputs["Max_Probability"] == pytest.approx(1.0), "a picture the model cannot rebuild is all defect"


def test_saving_the_model_in_the_solution_works_for_these_modules(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    dl.clear_cache()
    path = seg_model(tmp_path / "seg.onnx", [A, B])
    t = make("DL Instance Segment", model_file=path, save_in_solution=True)
    pic = np.full((64, 64, 3), 120, np.uint8)
    assert t.execute({"Image": pic}).outputs["Count"] == 2
    os.remove(path)
    os.remove(path.rsplit(".", 1)[0] + ".json")
    dl.clear_cache()
    assert t.execute({"Image": pic}).outputs["Count"] == 2 and t.outputs["Classes"] is not None


@pytest.mark.parametrize("tool_name", ["Classification Registration", "DL Image Retrieval", "DL Instance Segment", "DL Image Defect Prediction"])
def test_every_module_survives_junk(tool_name):
    for ctx in ({}, {"Image": "x"}, {"Image": np.zeros((0, 0), np.uint8)}, {"Image": np.zeros((6, 6), np.uint8)}, {"Image": np.full((50, 50, 3), 7, np.uint8)}):
        for mode in ("Search", "Register Image", "Register Folder", "Delete Category", "Clear Gallery"):
            t = create_tool_instance(tool_name, "t")
            try:
                t.set_param("mode", mode)
            except Exception:
                pass
            r = t.execute(ctx)
            assert r.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR) and r.message is not None
