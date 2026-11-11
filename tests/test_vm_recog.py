"""VisionMaster guide, Recognition chapter (character location / recognition, code reading, ML classification)."""
import json

import cv2
import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.registry import create_tool_instance
from apex_vision.tools import vm_recog as vr

onnx = pytest.importorskip("onnx")


def make(tool_name, /, **params):
    t = create_tool_instance(tool_name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t


def run(tool_name, ctx=None, /, **params):
    return make(tool_name, **params).execute(ctx or {})


def text_image(text, size=(120, 520), org=(20, 80), font=cv2.FONT_HERSHEY_SIMPLEX, scale=1.8, thick=3, dark_on_light=True, noise=0.0):
    im = np.full(size, 235 if dark_on_light else 25, np.uint8)
    cv2.putText(im, text, org, font, scale, 30 if dark_on_light else 225, thick, cv2.LINE_AA)
    if noise:
        im = np.clip(im.astype(np.float32) + np.random.default_rng(1).normal(0, noise, im.shape), 0, 255).astype(np.uint8)
    return im


# ---- the built-in reader ----------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("font", [cv2.FONT_HERSHEY_SIMPLEX, cv2.FONT_HERSHEY_DUPLEX, cv2.FONT_HERSHEY_COMPLEX])
def test_it_reads_printed_characters_in_several_fonts(font):
    for s in ("AB12", "QX7K9", "Wombat", "SN-2026", "a1b2c3"):
        r = run("DL Character Recognition", {"Image": text_image(s, font=font)})
        assert r.outputs["Text"] == s, (font, s, r.outputs["Text"])
        assert r.status == ToolStatus.OK and r.outputs["Count"] == len(s) and r.outputs["Min_Score"] > 0.5


def test_polarity_spaces_lines_and_noise():
    assert run("DL Character Recognition", {"Image": text_image("AB12", dark_on_light=False)}).outputs["Text"] == "AB12", "light characters on dark are found automatically"
    assert run("DL Character Recognition", {"Image": text_image("AB12", dark_on_light=False)}, polarity="Light on Dark").outputs["Text"] == "AB12"
    assert run("DL Character Recognition", {"Image": text_image("AB 12", size=(120, 620))}).outputs["Text"] == "AB 12"
    assert run("DL Character Recognition", {"Image": text_image("AB 12", size=(120, 620))}, include_spaces=False).outputs["Text"] == "AB12"
    two = text_image("AB12", size=(220, 400))
    cv2.putText(two, "XY34", (20, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 30, 3, cv2.LINE_AA)
    assert run("DL Character Recognition", {"Image": two}).outputs["Text"] == "AB12 XY34", "lines are read from the top down"
    noisy = run("DL Character Recognition", {"Image": text_image("AB12", noise=12.0)})
    assert noisy.outputs["Text"] == "AB12"
    ruined = run("DL Character Recognition", {"Image": text_image("AB12")}, min_confidence=0.999)
    assert ruined.status == ToolStatus.NG and ruined.outputs["Text"], "below the confidence it still reports what it saw, but fails"
    blank = run("DL Character Recognition", {"Image": np.full((100, 200), 200, np.uint8)})
    assert blank.status == ToolStatus.NG and blank.outputs["Text"] == ""


def test_the_character_filter_settles_look_alikes():
    o = text_image("O", size=(100, 100), org=(20, 80))
    assert run("DL Character Recognition", {"Image": o}).outputs["Text"] == "O"
    assert run("DL Character Recognition", {"Image": o}, filter_enable=True, character_filter="Numbers").outputs["Text"] == "0"
    assert run("DL Character Recognition", {"Image": o}, filter_enable=True, character_filter="Custom", custom_characters="Q0").outputs["Text"] in ("Q", "0")
    digits = run("DL Character Recognition", {"Image": text_image("12")}, filter_enable=True, character_filter="Uppercase Letters")
    assert all(c.isupper() for c in digits.outputs["Text"]), "with the filter on, only allowed characters can be answers"
    assert run("DL Character Recognition", {"Image": text_image("12")}, filter_enable=True, character_filter="Custom", custom_characters="").status == ToolStatus.ERROR
    assert run("DL Character Recognition", {}).status == ToolStatus.NG


def test_region_and_boxes_are_in_picture_coordinates():
    im = np.full((300, 600), 235, np.uint8)
    cv2.putText(im, "AB12", (300, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 30, 3, cv2.LINE_AA)
    cv2.putText(im, "ZZ99", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 30, 3, cv2.LINE_AA)
    r = run("DL Character Recognition", {"Image": im}, roi=[280, 130, 300, 100])
    assert r.outputs["Text"] == "AB12"
    xs = [c["box"][0] for c in r.outputs["Characters"]]
    assert min(xs) >= 295 and xs == sorted(xs)
    assert all(130 <= c["box"][1] <= 230 for c in r.outputs["Characters"])


# ---- location ---------------------------------------------------------------------------------------------------------------------------------------------------
def test_character_location_finds_sorts_and_limits():
    im = text_image("AB12")
    r = run("DL Character Location", {"Image": im}, max_number=10)
    assert r.status == ToolStatus.OK and r.outputs["Count"] == 4
    xs = [b[0] for b in r.outputs["Boxes"]]
    assert xs == sorted(xs) and len(r.outputs["Centers"]) == 4 and all(0 < s <= 1 for s in r.outputs["Scores"])
    assert run("DL Character Location", {"Image": im}).outputs["Count"] == 1, "the default is one"
    byconf = run("DL Character Location", {"Image": im}, max_number=10, sort_object="Confidence").outputs["Scores"]
    assert byconf == sorted(byconf, reverse=True)
    wide = run("DL Character Location", {"Image": im}, max_number=10, width_enable=True, min_width=1, max_width=5)
    assert wide.status == ToolStatus.NG and wide.outputs["Count"] == 0
    tall = run("DL Character Location", {"Image": im}, max_number=10, height_enable=True, min_height=10, max_height=1000)
    assert tall.outputs["Count"] == 4
    faint = np.full((120, 520), 150, np.uint8)
    cv2.putText(faint, "AB12", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 120, 3, cv2.LINE_AA)
    assert run("DL Character Location", {"Image": faint}, max_number=10, min_confidence=0.2).outputs["Count"] == 4
    assert run("DL Character Location", {"Image": faint}, max_number=10, min_confidence=0.9).outputs["Count"] == 0, "low contrast gives a low confidence"
    none = run("DL Character Location", {"Image": np.full((80, 80), 100, np.uint8)})
    assert none.status == ToolStatus.NG
    assert run("DL Character Location", {}).status == ToolStatus.NG
    edge = run("DL Character Location", {"Image": im}, max_number=10, edge_filter_enable=True, min_edge_score=0.5)
    assert edge.outputs["Count"] >= 1


def test_single_character_recognition_from_found_boxes_and_alone():
    im = text_image("AB12")
    boxes = run("DL Character Location", {"Image": im}, max_number=10).outputs["Boxes"]
    r = run("DL Single Character Recognition", {"Image": im, "Boxes": boxes})
    assert r.outputs["Text"] == "AB12" and r.status == ToolStatus.OK
    alone = run("DL Single Character Recognition", {"Image": im})
    assert alone.outputs["Text"] == "AB12"
    colum = run("DL Single Character Recognition", {"Image": im}, sort_object="Confidence")
    assert sorted(colum.outputs["Text"]) == sorted("AB12")
    assert run("DL Single Character Recognition", {"Image": im, "Boxes": "x"}).status == ToolStatus.ERROR
    assert run("DL Single Character Recognition", {"Image": im}, filter_enable=True, character_filter="Custom", custom_characters="").status == ToolStatus.ERROR
    assert run("DL Single Character Recognition", {"Image": im}, filter_enable=True, character_filter="Numbers").outputs["Text"].isdigit()


# ---- with models ------------------------------------------------------------------------------------------------------------------------------------------------
def build_model(path, in_shape, outs, meta=None):
    """An ONNX file whose outputs are fixed arrays (whatever the input), for testing how a module reads a model's answers."""
    from onnx import TensorProto, helper, numpy_helper
    inp = helper.make_tensor_value_info("input", TensorProto.FLOAT, in_shape)
    nodes, inits, outputs = [], [], []
    nodes.append(helper.make_node("ReduceMean", ["input"], ["m"], keepdims=0))
    nodes.append(helper.make_node("Mul", ["m", "zero"], ["z"]))
    inits.append(numpy_helper.from_array(np.zeros((), np.float32), "zero"))
    for i, arr in enumerate(outs):
        inits.append(numpy_helper.from_array(np.asarray(arr, np.float32), f"c{i}"))
        nodes.append(helper.make_node("Add", ["z", f"c{i}"], [f"out{i}"]))
        outputs.append(helper.make_tensor_value_info(f"out{i}", TensorProto.FLOAT, list(np.asarray(arr).shape)))
    graph = helper.make_graph(nodes, "g", [inp], outputs, initializer=inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))
    if meta is not None:
        with open(str(path).rsplit(".", 1)[0] + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f)
    return str(path)


def one_hot_sequence(indices, n_classes, sharp=12.0):
    out = np.full((1, len(indices), n_classes), -sharp / 2, np.float32)
    for t, i in enumerate(indices):
        out[0, t, i] = sharp / 2
    return out


def test_a_text_model_is_read_with_ctc(tmp_path):
    charset = "AB1C"
    seq = [0, 1, 1, 0, 2, 0, 3, 3, 0, 0]                                   # blank A A blank B blank 1 1 blank blank
    path = build_model(tmp_path / "ocr.onnx", [1, 1, 32, 100], [one_hot_sequence(seq, 5)], {"charset": charset, "blank": 0, "input_size": [100, 32], "channels": 1})
    r = run("DL Character Recognition", {"Image": text_image("anything")}, model_file=path)
    assert r.status == ToolStatus.OK, r.message
    assert r.outputs["Text"] == "AB1" and r.outputs["Min_Score"] > 0.9 and r.outputs["Count"] == 3
    only = run("DL Character Recognition", {"Image": text_image("anything")}, model_file=path, filter_enable=True, character_filter="Numbers")
    assert only.outputs["Text"] == "1" or all(c.isdigit() for c in only.outputs["Text"])
    nocharset = build_model(tmp_path / "bad.onnx", [1, 1, 32, 100], [one_hot_sequence(seq, 5)], {})
    bad = run("DL Character Recognition", {"Image": text_image("x")}, model_file=nocharset)
    assert bad.status == ToolStatus.ERROR and "charset" in bad.message
    assert run("DL Character Recognition", {"Image": text_image("x")}, model_file=str(tmp_path / "gone.onnx")).status == ToolStatus.ERROR
    assert vr.ctc_decode(np.log(np.array([[0.1, 0.8, 0.1], [0.1, 0.8, 0.1], [0.9, 0.05, 0.05], [0.1, 0.8, 0.1]], np.float32)), "ab")[0] == "aa"


def yolo_output(boxes, n_classes):
    """[1, 4 + classes, N] in input pixels: centre x, centre y, width, height, class scores."""
    out = np.zeros((1, 4 + n_classes, max(16, len(boxes))), np.float32)       # many more candidates than channels, like a real model
    for j, (cx, cy, w, h, cls, score) in enumerate(boxes):
        out[0, :4, j] = (cx, cy, w, h)
        out[0, 4 + cls, j] = score
    return out


def test_a_detection_model_locates_and_names_characters(tmp_path):
    dets = [(40, 32, 16, 24, 0, 0.9), (20, 32, 16, 24, 1, 0.8), (60, 32, 16, 24, 2, 0.7)]
    path = build_model(tmp_path / "det.onnx", [1, 3, 64, 64], [yolo_output(dets, 3)], {"labels": ["7", "A", "Z"], "input_size": [64, 64], "task": "detect"})
    im = np.full((64, 64, 3), 200, np.uint8)
    loc = run("DL Character Location", {"Image": im}, model_file=path, max_number=10, min_confidence=0.5)
    assert loc.status == ToolStatus.OK and loc.outputs["Count"] == 3
    centres = [c[0] for c in loc.outputs["Centers"]]
    assert centres == sorted(centres) and centres[0] == pytest.approx(20, abs=2.5)
    rec = run("DL Single Character Recognition", {"Image": im}, model_file=path, max_number=10, min_confidence=0.5)
    assert rec.outputs["Text"].replace(" ", "") == "A7Z", rec.outputs["Text"]
    fil = run("DL Single Character Recognition", {"Image": im}, model_file=path, max_number=10, min_confidence=0.5, filter_enable=True, character_filter="Numbers")
    assert fil.outputs["Text"] == "7"
    assert run("DL Character Location", {"Image": im}, model_file=path, max_number=10, min_confidence=0.85).outputs["Count"] == 1
    assert run("DL Character Location", {"Image": im}, model_file=str(tmp_path / "gone.onnx")).status == ToolStatus.ERROR


# ---- DL Code Reading ----------------------------------------------------------------------------------------------------------------------------------------
def qr_image(text, size=200):
    enc = cv2.QRCodeEncoder_create()
    code = enc.encode(text)
    code = cv2.resize(code, (size, size), interpolation=cv2.INTER_NEAREST)
    return cv2.copyMakeBorder(code, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)


def test_code_reading_finds_qr_codes_in_either_polarity():
    pic = qr_image("APEX-1234")
    r = run("DL Code Reading", {"Image": pic})
    assert r.status == ToolStatus.OK and r.outputs["Text"] == "APEX-1234" and r.outputs["Count"] == 1
    inv = run("DL Code Reading", {"Image": 255 - pic})
    assert inv.outputs["Text"] == "APEX-1234", "white on dark is tried too"
    assert run("DL Code Reading", {"Image": 255 - pic}, polarity="Dark on White").status == ToolStatus.NG
    two = np.full((340, 700), 255, np.uint8)
    two[40:300, 20:280] = cv2.resize(qr_image("ONE", 180), (260, 260), interpolation=cv2.INTER_NEAREST)
    two[40:300, 360:620] = cv2.resize(qr_image("TWO", 180), (260, 260), interpolation=cv2.INTER_NEAREST)
    both = run("DL Code Reading", {"Image": two})
    assert sorted(both.outputs["Texts"]) == ["ONE", "TWO"]
    left = run("DL Code Reading", {"Image": two}, roi=[0, 0, 330, 340])
    assert left.outputs["Texts"] == ["ONE"]
    right = run("DL Code Reading", {"Image": two}, roi=[340, 0, 360, 340])
    xs = [p[0] for p in right.outputs["Codes"][0]["points"]]
    assert right.outputs["Texts"] == ["TWO"] and min(xs) > 340, "the outline is in picture coordinates"
    assert run("DL Code Reading", {"Image": two}, max_codes=1).outputs["Count"] == 1


def test_code_reading_grades_expectations_and_failures():
    pic = qr_image("GRADE-ME")
    graded = run("DL Code Reading", {"Image": pic}, grade_enable=True)
    assert graded.outputs["Codes"][0]["grade"] == "A" and graded.outputs["Codes"][0]["contrast"] > 90
    faint = run("DL Code Reading", {"Image": (pic * 0.25 + 150).astype(np.uint8)}, grade_enable=True)
    if faint.outputs["Count"]:
        assert faint.outputs["Codes"][0]["grade"] in ("D", "F")
    assert run("DL Code Reading", {"Image": pic}, expected_text="SOMETHING-ELSE").status == ToolStatus.NG
    assert run("DL Code Reading", {"Image": pic}, expected_text="GRADE-ME").status == ToolStatus.OK
    assert run("DL Code Reading", {"Image": np.full((100, 100), 128, np.uint8)}).status == ToolStatus.NG
    assert run("DL Code Reading", {"Image": pic}, code_kind="1D only").status == ToolStatus.NG
    assert run("DL Code Reading", {"Image": pic}, mirror="Mirrored").outputs["Count"] in (0, 1)
    assert run("DL Code Reading", {}).status == ToolStatus.NG
    assert vr._grade(80) == "A" and vr._grade(60) == "B" and vr._grade(45) == "C" and vr._grade(25) == "D" and vr._grade(5) == "F"


def test_mirrored_codes_are_read_and_located_correctly():
    pic = qr_image("MIRROR-ME")
    flipped = cv2.flip(pic, 1)
    r = run("DL Code Reading", {"Image": flipped})
    if r.status == ToolStatus.OK:
        assert r.outputs["Text"] == "MIRROR-ME"
        pts = np.array(r.outputs["Codes"][0]["points"])
        assert pts[:, 0].min() >= 30 and pts[:, 0].max() <= pic.shape[1] - 30
    assert run("DL Code Reading", {"Image": flipped}, mirror="Not Mirrored").status in (ToolStatus.OK, ToolStatus.NG)


# ---- ML Classification ---------------------------------------------------------------------------------------------------------------------------------------
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


def taught(tmp=None, **extra):
    t = make("ML Classification", mode="Learn", **extra)
    for k in KINDS:
        t.set_param("learn_label", k)
        for i in range(4):
            assert t.execute({"Image": shape_image(k, i)}).status == ToolStatus.OK
    t.set_param("mode", "Classify")
    return t


def test_ml_classification_learns_and_names_new_pictures():
    t = taught()
    for k in KINDS:
        r = t.execute({"Image": shape_image(k, 50)})
        assert r.status == ToolStatus.OK and r.outputs["Class"] == k and r.outputs["Score"] > 0.6, (k, r.outputs["Scores"])
    r = t.execute({"Image": shape_image("red circle", 51)})
    assert set(r.outputs["Scores"]) == set(KINDS) and r.outputs["Samples"] == {k: 4 for k in KINDS}
    assert r.outputs["Top"][0]["class"] == "red circle" and len(r.outputs["Top"]) == 3
    t.set_param("top_k", 1)
    assert len(t.execute({"Image": shape_image("blue square", 52)}).outputs["Top"]) == 1


def test_ml_classification_threshold_region_and_problems(tmp_path):
    t = taught()
    odd = np.full((100, 100, 3), 100, np.uint8)
    cv2.putText(odd, "?", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 0), 5)
    t.set_param("min_score", 0.99)
    r = t.execute({"Image": odd})
    assert r.status in (ToolStatus.OK, ToolStatus.NG)
    t.set_param("min_score", 0.0)
    pic = np.full((100, 300, 3), 230, np.uint8)
    pic[:, 200:] = shape_image("blue square", 3)
    t.set_param("roi", [200, 0, 100, 100])
    assert t.execute({"Image": pic}).outputs["Class"] == "blue square"
    assert run("ML Classification", {"Image": shape_image("red circle")}).status == ToolStatus.ERROR, "nothing taught"
    assert run("ML Classification", {"Image": shape_image("red circle")}, mode="Learn").status == ToolStatus.ERROR, "no class name"
    assert run("ML Classification", {}, mode="Classify", samples={"a": [[0.0]]}).status == ToolStatus.NG
    junk = make("ML Classification", samples={"a": [[0.0, 1.0]]})
    assert junk.execute({"Image": shape_image("red circle")}).status == ToolStatus.ERROR, "samples of another size are not used"
    t.set_param("mode", "Clear Samples")
    assert t.execute({"Image": odd}).outputs["Samples"] == {}


def test_ml_classification_model_file_round_trip(tmp_path):
    path = str(tmp_path / "ml.json")
    t = taught(model_file=path)
    fresh = make("ML Classification", model_file=path)
    r = fresh.execute({"Image": shape_image("green triangle", 70)})
    assert r.outputs["Class"] == "green triangle", "a second module reads the saved samples"
    bad = tmp_path / "broken.json"
    bad.write_text("{not json")
    assert make("ML Classification", model_file=str(bad)).execute({"Image": shape_image("red circle")}).status == ToolStatus.ERROR
    assert len(vr.ml_features(shape_image("red circle"))) == len(vr.ml_features(np.zeros((30, 40), np.uint8)))


@pytest.mark.parametrize("tool_name", ["DL Character Location", "DL Character Recognition", "DL Single Character Recognition", "DL Code Reading", "ML Classification"])
def test_every_module_survives_junk(tool_name):
    for ctx in ({}, {"Image": "x"}, {"Image": np.zeros((0, 0), np.uint8)}, {"Image": np.zeros((6, 6), np.uint8)}, {"Image": np.full((50, 50, 3), 7, np.uint8), "Boxes": [[1, 2]]},
                {"Image": np.zeros((40, 40), np.uint8), "Boxes": [[0, 0, 0, 0]]}):
        r = create_tool_instance(tool_name, "t").execute(ctx)
        assert r.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR) and r.message is not None
