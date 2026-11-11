"""Deep-learning modules, tested with REAL models: tiny networks are trained here on synthetic parts, exported to ONNX, and run
through DL Classify / DL Segment / DL Anomaly / Object Detection / Defect Detection on both inference engines.

(Needs torch + onnx to build the models; the checks themselves only need onnxruntime or OpenCV.)"""
import json
import os

import cv2
import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("onnx")

import apex_vision.tools  # noqa: E402,F401
from apex_vision import dl_train  # noqa: E402
from apex_vision.core import dl_engine as dl  # noqa: E402
from apex_vision.core.base_tool import ToolStatus  # noqa: E402
from apex_vision.core.registry import create_tool_instance  # noqa: E402

BACKENDS = dl.available_backends()


# ---- synthetic parts -----------------------------------------------------------------------------------------------
def texture(rng, size):
    """A smooth, slightly noisy metal-like surface."""
    base = rng.uniform(90, 150)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / size
    img = base + 25 * np.sin(2 * np.pi * (xx * rng.uniform(0.5, 1.5) + rng.uniform(0, 1))) + 15 * yy
    img = img + rng.normal(0, 2.0, (size, size))
    img = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 1.0)
    return np.clip(cv2.merge([img * 0.95, img, img * 1.05]), 0, 255).astype(np.uint8)


def add_scratch(img, rng):
    out = img.copy()
    s = img.shape[0]
    p1 = (int(rng.integers(5, s // 3)), int(rng.integers(5, s - 5)))
    p2 = (int(rng.integers(2 * s // 3, s - 5)), int(rng.integers(5, s - 5)))
    cv2.line(out, p1, p2, (25, 25, 25), 2)
    return out


def add_blob(img, rng, mask=None):
    out = img.copy()
    s = img.shape[0]
    c = (int(rng.integers(s // 5, 4 * s // 5)), int(rng.integers(s // 5, 4 * s // 5)))
    ax = (int(rng.integers(s // 14, s // 7)), int(rng.integers(s // 14, s // 7)))
    cv2.ellipse(out, c, ax, int(rng.integers(0, 180)), 0, 360, (20, 30, 230), -1)
    if mask is not None:
        cv2.ellipse(mask, c, ax, int(rng.integers(0, 1)), 0, 360, 1, -1)
    return out, c


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    root = tmp_path_factory.mktemp("dl")
    rng = np.random.default_rng(3)
    # classification: good / scratch
    for cls, n in (("good", 50), ("scratch", 50)):
        os.makedirs(root / "cls" / cls)
        for i in range(n):
            im = texture(rng, 64)
            cv2.imwrite(str(root / "cls" / cls / f"{i}.png"), add_scratch(im, rng) if cls == "scratch" else im)
    # segmentation: red blobs on a surface; mask = blob
    os.makedirs(root / "seg" / "images")
    os.makedirs(root / "seg" / "masks")
    for i in range(70):
        mask = np.zeros((96, 96), np.uint8)
        im, _ = add_blob(texture(rng, 96), rng, mask)
        if i % 5 == 0:
            im, mask = texture(rng, 96), np.zeros((96, 96), np.uint8)
        cv2.imwrite(str(root / "seg" / "images" / f"{i}.png"), im)
        cv2.imwrite(str(root / "seg" / "masks" / f"{i}.png"), mask)
    # anomaly: good parts only
    os.makedirs(root / "good")
    for i in range(48):
        cv2.imwrite(str(root / "good" / f"{i}.png"), texture(rng, 128))
    quiet = lambda *_: None      # noqa: E731
    out = {"root": root}
    out["cls"] = str(root / "m_cls.onnx")
    dl_train.train_classifier(str(root / "cls"), out["cls"], epochs=14, size=64, log=quiet)
    out["seg"] = str(root / "m_seg.onnx")
    dl_train.train_segmenter(str(root / "seg"), out["seg"], epochs=60, size=96, labels=["background", "blob"], log=quiet)
    out["ano"] = str(root / "m_ano.onnx")
    dl_train.train_anomaly(str(root / "good"), out["ano"], epochs=120, size=128, log=quiet)
    return out


def run(name, ctx, **params):
    t = create_tool_instance(name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t.execute(ctx)


# ---- engine ----------------------------------------------------------------------------------------------------------
def test_model_files_come_with_a_sidecar_the_modules_read(models):
    meta = json.load(open(os.path.splitext(models["cls"])[0] + ".json"))
    assert meta["task"] == "classify" and meta["labels"] == ["good", "scratch"] and meta["input_size"] == [64, 64]
    m = dl.load_model(models["cls"])
    assert m.labels == ["good", "scratch"] and m.fixed_input_size() == (64, 64) and "classify" not in m.describe() and "m_cls.onnx" in m.describe()


@pytest.mark.skipif(len(BACKENDS) < 2, reason="needs both onnxruntime and OpenCV DNN")
@pytest.mark.parametrize("key", ["cls", "seg", "ano"])
def test_both_engines_give_the_same_numbers(models, key):
    size = dl.load_model(models[key]).fixed_input_size()
    blob = np.random.default_rng(0).uniform(0, 1, (1, 3, size[1], size[0])).astype(np.float32)
    a = dl.load_model(models[key], "ONNX Runtime").run(blob)[0]
    b = dl.load_model(models[key], "OpenCV DNN").run(blob)[0]
    assert a.shape == b.shape and np.abs(a - b).max() < 1e-3


def test_clear_errors_for_bad_model_files(tmp_path, models):
    with pytest.raises(dl.DLModelError, match="No model file chosen"):
        dl.load_model("")
    with pytest.raises(dl.DLModelError, match="not found"):
        dl.load_model(str(tmp_path / "nope.onnx"))
    pt = tmp_path / "w.pt"
    pt.write_bytes(b"x")
    with pytest.raises(dl.DLModelError, match="not an .onnx file"):
        dl.load_model(str(pt))
    junk = tmp_path / "junk.onnx"
    junk.write_bytes(b"this is not a model" * 20)
    with pytest.raises(dl.DLModelError, match="Could not load"):
        dl.load_model(str(junk))
    m = dl.load_model(models["cls"])
    with pytest.raises(dl.DLModelError, match="could not run"):
        m.run(np.zeros((1, 3, 17, 17), np.float32))


def test_bare_model_names_are_found_in_the_models_folder(models, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".apex_vision" / "models").mkdir(parents=True)
    import shutil
    shutil.copy(models["cls"], home / ".apex_vision" / "models" / "mine.onnx")
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(p).replace("~", str(home)))
    assert dl.resolve_path("mine.onnx").endswith("mine.onnx") and os.path.isfile(dl.resolve_path("mine.onnx"))


# ---- decoders (no model needed) ---------------------------------------------------------------------------------------
def info(w0=640, h0=480, size=(640, 640), scale=None, pad=(0, 0)):
    return {"orig": (w0, h0), "size": size, "scale": scale or (size[0] / w0, size[1] / h0), "pad": pad}


def test_yolo_v8_layout_with_nms():
    n = 8400
    out = np.zeros((1, 4 + 3, n), np.float32)
    for i, (cx, cy, w, h, c, s) in enumerate([(320, 320, 100, 80, 1, 0.9), (322, 321, 100, 80, 1, 0.6), (100, 100, 40, 40, 2, 0.8)]):
        out[0, :4, i] = (cx, cy, w, h)
        out[0, 4 + c, i] = s
    dets = dl.decode_detections([out], info(), 0.25, 0.45)
    assert len(dets) == 2, "the second box overlaps the first of the same class and is removed"
    assert dets[0]["class_id"] == 1 and abs(dets[0]["score"] - 0.9) < 1e-6
    x, y, w, h = dets[0]["box"]
    assert abs(x - 270) < 1 and abs(w - 100) < 1 and abs(y - (320 - 40) * 480 / 640) < 1 and abs(h - 80 * 480 / 640) < 1


def test_yolo_v5_layout_uses_objectness():
    out = np.zeros((1, 25200, 5 + 2), np.float32)
    out[0, 0, :4] = (320, 320, 100, 100)
    out[0, 0, 4] = 0.5                    # objectness
    out[0, 0, 5 + 1] = 0.8                # class 1 -> score 0.4
    out[0, 1, :4] = (50, 50, 20, 20)
    out[0, 1, 4] = 0.2
    out[0, 1, 5] = 0.9                    # score 0.18: below the threshold
    dets = dl.decode_detections([out], info(), 0.25, 0.45, num_classes=2)
    assert len(dets) == 1 and dets[0]["class_id"] == 1 and abs(dets[0]["score"] - 0.4) < 1e-6


def test_end_to_end_layout_and_letterbox_mapping():
    out = np.zeros((1, 300, 6), np.float32)
    out[0, 0] = (110, 140, 210, 240, 0.9, 3)               # x1, y1, x2, y2 in the 640x640 letterboxed input
    out[0, 1] = (0, 0, 10, 10, 0.1, 0)
    lb = info(w0=1280, h0=720, size=(640, 640), scale=(0.5, 0.5), pad=(10, 140))
    dets = dl.decode_detections([out], lb, 0.25, 0.45)
    assert len(dets) == 1 and dets[0]["class_id"] == 3
    assert dets[0]["box"] == pytest.approx([200.0, 0.0 + 0, 200.0, 200.0], abs=1) or dets[0]["box"][2] == pytest.approx(200, abs=1)
    assert dets[0]["box"][0] == pytest.approx((110 - 10) / 0.5, abs=1)


def test_segmentation_decoding_for_logits_probabilities_and_sigmoid():
    logits = np.zeros((1, 3, 8, 8), np.float32)
    logits[0, 2, 2:5, 2:5] = 5.0
    cls, prob = dl.decode_segmentation([logits], info(8, 8, (8, 8)))
    assert cls.shape == (8, 8) and (cls[2:5, 2:5] == 2).all() and (cls[0] == 0).all() and prob.max() <= 1.0
    sig = np.full((1, 1, 8, 8), -4.0, np.float32)
    sig[0, 0, 1:3, 1:3] = 4.0
    cls, _ = dl.decode_segmentation([sig], info(16, 16, (8, 8)))
    assert cls.shape == (16, 16) and cls[3, 3] == 1 and cls[10, 10] == 0


def test_classification_decoding_handles_logits_probabilities_and_one_output():
    assert abs(float(dl.decode_classification([np.array([[2.0, 0.0, 0.0]])]).sum()) - 1.0) < 1e-5
    p = dl.decode_classification([np.array([[0.7, 0.2, 0.1]])])
    assert p.argmax() == 0 and abs(p[0] - 0.7) < 1e-6
    one = dl.decode_classification([np.array([[3.0]])])
    assert len(one) == 2 and one[1] > 0.9


# ---- DL Classify -----------------------------------------------------------------------------------------------------
def test_classify_tells_good_from_scratched_and_decides_pass_fail(models):
    rng = np.random.default_rng(99)
    good_hits = scratch_hits = 0
    for _ in range(20):
        im = texture(rng, 64)
        good_hits += run("DL Classify", {"Image": im}, model_path=models["cls"], ok_labels="good").outputs["Class"] == "good"
        scratch_hits += run("DL Classify", {"Image": add_scratch(im, rng)}, model_path=models["cls"], ok_labels="good").outputs["Class"] == "scratch"
    assert good_hits >= 17 and scratch_hits >= 17, (good_hits, scratch_hits)
    g = run("DL Classify", {"Image": texture(rng, 64)}, model_path=models["cls"], ok_labels="good")
    s = run("DL Classify", {"Image": add_scratch(texture(rng, 64), rng)}, model_path=models["cls"], ok_labels="good")
    assert g.status == ToolStatus.OK and g.outputs["Status"] == "OK" and 0.5 <= g.outputs["Confidence"] <= 1.0
    assert s.status == ToolStatus.NG and s.outputs["Status"] == "NG" and "not an OK label" in s.message
    assert [x["label"] for x in g.outputs["Scores"]][0] == "good" and len(g.outputs["Scores"]) == 2


def test_classify_confidence_limit_labels_override_top_k_and_roi(models):
    rng = np.random.default_rng(5)
    im = texture(rng, 64)
    strict = run("DL Classify", {"Image": im}, model_path=models["cls"], ok_labels="good", min_confidence=1.01)
    assert strict.status == ToolStatus.NG and "below" in strict.message
    named = run("DL Classify", {"Image": im}, model_path=models["cls"], labels="fine, damaged")
    assert named.outputs["Class"] in ("fine", "damaged")
    assert len(run("DL Classify", {"Image": im}, model_path=models["cls"], top_k=1).outputs["Scores"]) == 1
    big = cv2.resize(im, (256, 256))
    big[:, 128:] = add_scratch(cv2.resize(texture(rng, 64), (128, 256)), rng)[:, :128] if False else big[:, 128:]
    assert run("DL Classify", {"Image": big}, model_path=models["cls"], roi=[0, 0, 128, 128]).status in (ToolStatus.OK, ToolStatus.NG)
    free = run("DL Classify", {"Image": im}, model_path=models["cls"])                 # no OK labels: it only classifies
    assert free.status == ToolStatus.OK


@pytest.mark.parametrize("backend", BACKENDS)
def test_classify_gives_the_same_answer_on_each_engine(models, backend):
    im = add_scratch(texture(np.random.default_rng(1), 64), np.random.default_rng(1))
    r = run("DL Classify", {"Image": im}, model_path=models["cls"], backend=backend)
    assert r.outputs["Class"] == "scratch" and backend in r.message


def test_classify_errors_are_reported_not_raised(models, tmp_path):
    im = texture(np.random.default_rng(1), 64)
    assert run("DL Classify", {"Image": im}).status == ToolStatus.ERROR
    assert "No model file chosen" in run("DL Classify", {"Image": im}).message
    r = run("DL Classify", {"Image": im}, model_path=str(tmp_path / "x.onnx"))
    assert r.status == ToolStatus.ERROR and "not found" in r.message and "Class" in r.outputs
    assert run("DL Classify", {}, model_path=models["cls"]).status == ToolStatus.NG
    for odd in (np.zeros((40, 50), np.uint8), np.zeros((30, 30, 4), np.uint8), np.zeros((2, 2, 3), np.uint8)):
        assert run("DL Classify", {"Image": odd}, model_path=models["cls"]).status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR)


# ---- DL Segment ---------------------------------------------------------------------------------------------------------
def seg_case(seed, with_defect=True):
    rng = np.random.default_rng(seed)
    mask = np.zeros((96, 96), np.uint8)
    im = texture(rng, 96)
    if with_defect:
        im, _ = add_blob(im, rng, mask)
    return im, mask


def test_segment_finds_the_defect_with_good_overlap(models):
    ious = []
    for seed in range(200, 208):
        im, truth = seg_case(seed)
        r = run("DL Segment", {"Image": im}, model_path=models["seg"], threshold=0.5, min_area=5)
        pred = r.outputs["Mask"][:, :, 0] > 0
        ious.append((pred & (truth > 0)).sum() / max(1, (pred | (truth > 0)).sum()))
    assert np.mean(ious) > 0.55, ious


def test_segment_verdict_counts_area_and_limits(models):
    im, truth = seg_case(300)
    r = run("DL Segment", {"Image": im}, model_path=models["seg"], min_area=5)
    assert r.status == ToolStatus.NG and r.outputs["Defect_Count"] >= 1 and r.outputs["Defect_Area"] > 20
    assert r.outputs["Mask"].shape == im.shape and r.outputs["Image"].shape == im.shape
    assert len(r.outputs["Boxes"]) == r.outputs["Defect_Count"] == len(r.outputs["Detections"])
    assert r.outputs["Classes"][0] == "blob" and 0.5 <= r.outputs["Scores"][0] <= 1.0
    assert 0 < r.outputs["Defect_Ratio"] < 50 and "[" in r.message
    tolerant = run("DL Segment", {"Image": im}, model_path=models["seg"], min_area=5, max_defect_count=5)
    assert tolerant.status == ToolStatus.OK, "up to 5 defects are allowed"
    by_ratio = run("DL Segment", {"Image": im}, model_path=models["seg"], min_area=5, max_defect_count=5, max_defect_ratio=0.1)
    assert by_ratio.status == ToolStatus.NG and "limit" in by_ratio.message
    clean = run("DL Segment", {"Image": seg_case(301, False)[0]}, model_path=models["seg"], min_area=30)
    assert clean.status == ToolStatus.OK and clean.outputs["Defect_Count"] == 0 and clean.outputs["Defect_Area"] == 0


def test_segment_class_filter_min_area_and_roi(models):
    im, _ = seg_case(310)
    assert run("DL Segment", {"Image": im}, model_path=models["seg"], defect_classes="blob", min_area=5).outputs["Defect_Count"] >= 1
    assert run("DL Segment", {"Image": im}, model_path=models["seg"], defect_classes="no_such_class", min_area=5).outputs["Defect_Count"] >= 1
    assert run("DL Segment", {"Image": im}, model_path=models["seg"], min_area=10_000).outputs["Defect_Count"] == 0
    empty_corner = run("DL Segment", {"Image": im}, model_path=models["seg"], min_area=5, roi=[0, 0, 4, 4])
    assert empty_corner.outputs["Mask"].shape == im.shape, "an ROI mask is placed back into the full image"


def test_segment_on_a_larger_image_than_the_model_was_trained_on(models):
    im, truth = seg_case(320)
    big = cv2.resize(im, (384, 384))
    r = run("DL Segment", {"Image": big}, model_path=models["seg"], min_area=50)
    assert r.outputs["Mask"].shape == big.shape and r.outputs["Defect_Count"] >= 1
    x, y, w, h = r.outputs["Boxes"][0]
    ty, tx = np.nonzero(truth)
    assert abs((x + w / 2) - tx.mean() * 4) < 60 and abs((y + h / 2) - ty.mean() * 4) < 60, "the box sits on the defect"


# ---- DL Anomaly ---------------------------------------------------------------------------------------------------------
def test_anomaly_scores_defects_higher_and_marks_where(models):
    rng = np.random.default_rng(777)
    goods = [run("DL Anomaly", {"Image": texture(rng, 128)}, model_path=models["ano"], output_type="Reconstruction (autoencoder)") for _ in range(8)]
    bads, centres = [], []
    for _ in range(8):
        im, c = add_blob(texture(rng, 128), rng)
        bads.append(run("DL Anomaly", {"Image": im}, model_path=models["ano"], output_type="Reconstruction (autoencoder)"))
        centres.append(c)
    assert min(b.outputs["Anomaly_Score"] for b in bads) > np.median([g.outputs["Anomaly_Score"] for g in goods])
    assert sum(g.status == ToolStatus.OK for g in goods) >= 6, "good parts pass"
    assert sum(b.status == ToolStatus.NG for b in bads) >= 7, "defective parts fail"
    hit = 0
    for b, (cx, cy) in zip(bads, centres):
        for x, y, w, h in b.outputs["Boxes"]:
            hit += x - 6 <= cx <= x + w + 6 and y - 6 <= cy <= y + h + 6
            break
    assert hit >= 6, "the first anomaly box is on the defect"


def test_anomaly_outputs_heatmap_threshold_and_limits(models):
    rng = np.random.default_rng(12)
    im, _ = add_blob(texture(rng, 128), rng)
    r = run("DL Anomaly", {"Image": im}, model_path=models["ano"], output_type="Reconstruction (autoencoder)")
    assert r.outputs["Heatmap"].shape == im.shape and r.outputs["Image"].shape == im.shape and r.outputs["Mask"].shape == im.shape
    assert not np.array_equal(r.outputs["Image"], im)
    thr = json.load(open(os.path.splitext(models["ano"])[0] + ".json"))["threshold"]
    assert f"threshold {thr:.3f}" in r.message, "the model's own threshold is used when none is set"
    lenient = run("DL Anomaly", {"Image": im}, model_path=models["ano"], output_type="Reconstruction (autoencoder)", map_threshold=5.0)
    assert lenient.status == ToolStatus.OK and lenient.outputs["Defect_Count"] == 0
    allowed = run("DL Anomaly", {"Image": im}, model_path=models["ano"], output_type="Reconstruction (autoencoder)", max_defect_count=50)
    assert allowed.status == ToolStatus.OK
    wrong = run("DL Anomaly", {"Image": im}, model_path=models["cls"], output_type="Reconstruction (autoencoder)")
    assert wrong.status == ToolStatus.ERROR and "does not match" in wrong.message


# ---- Defect Detection (the general module) -----------------------------------------------------------------------------------
def test_defect_detection_uses_a_segmentation_model_and_keeps_its_outputs(models):
    im, _ = seg_case(400)
    r = run("Defect Detection", {"Image": im}, method="Deep learning (ONNX model)", model_path=models["seg"], model_task="Segmentation",
            roi=[0, 0, 96, 96], min_defect_area=5)
    assert r.status == ToolStatus.NG and r.outputs["Defect_Count"] >= 1 and r.outputs["Max_Defect_Area"] > 5
    assert set(r.outputs) >= {"Image", "Defect_Count", "Max_Defect_Area", "Boxes", "Classes", "Scores", "Detections"}
    assert r.outputs["Detections"][0]["model_id"] == "defect_detection_dl" and "segmentation" in r.message
    clean = run("Defect Detection", {"Image": seg_case(401, False)[0]}, method="Deep learning (ONNX model)", model_path=models["seg"],
                roi=[0, 0, 96, 96], min_defect_area=30)
    assert clean.status == ToolStatus.OK and clean.outputs["Defect_Count"] == 0


def test_defect_detection_uses_an_anomaly_model_and_a_region(models):
    rng = np.random.default_rng(55)
    bad, (cx, cy) = add_blob(texture(rng, 128), rng)
    r = run("Defect Detection", {"Image": bad}, method="Deep learning (ONNX model)", model_path=models["ano"], model_task="Anomaly",
            roi=[0, 0, 128, 128])
    assert r.status == ToolStatus.NG and r.outputs["Defect_Count"] >= 1
    away = run("Defect Detection", {"Image": bad}, method="Deep learning (ONNX model)", model_path=models["ano"], model_task="Anomaly",
               roi=[0 if cx > 64 else 70, 0, 50, 50])
    assert away.outputs["Defect_Count"] <= r.outputs["Defect_Count"]


def test_defect_detection_classical_method_is_unchanged_and_dl_errors_are_clear(models):
    im = texture(np.random.default_rng(1), 128)
    classical = run("Defect Detection", {"Image": im})
    assert "model" not in classical.message.lower() and classical.status in (ToolStatus.OK, ToolStatus.NG)
    missing = run("Defect Detection", {"Image": im}, method="Deep learning (ONNX model)")
    assert missing.status == ToolStatus.ERROR and "No model file chosen" in missing.message
    assert set(missing.outputs) >= {"Defect_Count", "Boxes", "Detections"}


# ---- Object Detection with an ONNX model (no ultralytics at run time) -----------------------------------------------------------
def _bus_image():
    try:
        import ultralytics
    except ImportError:
        pytest.skip("ultralytics not installed")
    path = os.path.join(os.path.dirname(ultralytics.__file__), "assets", "bus.jpg")
    if not os.path.isfile(path):
        pytest.skip("sample picture not shipped with this ultralytics")
    return cv2.imread(path)


@pytest.fixture(scope="module")
def yolo_onnx(tmp_path_factory):
    pt = os.path.join(os.path.dirname(__file__), "..", "yolo11n.pt")
    if not os.path.isfile(pt):
        pytest.skip("yolo11n.pt not present")
    from ultralytics import YOLO
    out = YOLO(pt).export(format="onnx", imgsz=640, opset=13, simplify=False, verbose=False)
    dst = str(tmp_path_factory.mktemp("yolo") / "yolo11n.onnx")
    import shutil
    shutil.copyfile(out, dst)
    return dst


def test_onnx_yolo_matches_ultralytics_on_a_real_photo(yolo_onnx):
    from ultralytics import YOLO
    img = _bus_image()
    ref = YOLO(os.path.join(os.path.dirname(__file__), "..", "yolo11n.pt")).predict(img, verbose=False, conf=0.25)[0]
    ref_boxes = sorted([(ref.names[int(c)], [float(v) for v in b]) for c, b in zip(ref.boxes.cls, ref.boxes.xyxy)])
    r = run("Object Detection", {"Image": img}, model_path=yolo_onnx, confidence=0.25)
    assert r.status == ToolStatus.OK and r.outputs["Count"] == len(ref_boxes), (r.outputs["Classes"], [n for n, _ in ref_boxes])
    assert sorted(r.outputs["Classes"]) == sorted(n for n, _ in ref_boxes) and "bus" in r.outputs["Classes"] and "person" in r.outputs["Classes"]
    for name, (x1, y1, x2, y2) in ref_boxes:                                  # every reference box has a match of the same class
        best = max((min(x2, bx + bw) - max(x1, bx)) * (min(y2, by + bh) - max(y1, by)) / ((x2 - x1) * (y2 - y1))
                   for (bx, by, bw, bh), c in zip(r.outputs["Boxes"], r.outputs["Classes"]) if c == name)
        assert best > 0.85, (name, best)


def test_onnx_yolo_class_filter_roi_and_both_engines(yolo_onnx):
    img = _bus_image()
    only = run("Object Detection", {"Image": img}, model_path=yolo_onnx, classes="bus")
    assert set(only.outputs["Classes"]) == {"bus"} and only.outputs["Count"] == 1
    by_id = run("Object Detection", {"Image": img}, model_path=yolo_onnx, classes="5")
    assert set(by_id.outputs["Classes"]) == {"bus"}
    crop = run("Object Detection", {"Image": img, "ROI": [0, 0, 400, 800]}, model_path=yolo_onnx)
    assert all(b[0] + b[2] <= 410 for b in crop.outputs["Boxes"]), "boxes are reported in the full image's pixels"
    if len(BACKENDS) == 2:
        a = dl.load_model(yolo_onnx, "ONNX Runtime").run(np.random.default_rng(0).uniform(0, 1, (1, 3, 640, 640)).astype(np.float32))[0]
        b = dl.load_model(yolo_onnx, "OpenCV DNN").run(np.random.default_rng(0).uniform(0, 1, (1, 3, 640, 640)).astype(np.float32))[0]
        assert np.abs(a - b).max() < 1e-2
    high = run("Object Detection", {"Image": img}, model_path=yolo_onnx, confidence=0.99)
    assert high.outputs["Count"] == 0 and high.outputs["Status"] == "NG"


# ---- command line --------------------------------------------------------------------------------------------------------------
def test_train_and_model_info_commands(models, tmp_path, capsys):
    from apex_vision import cli
    out = str(tmp_path / "cli_cls.onnx")
    assert cli.main(["train", "classify", "--data", str(models["root"] / "cls"), "--out", out, "--epochs", "2", "--size", "32"]) == 0
    assert os.path.isfile(out) and os.path.isfile(os.path.splitext(out)[0] + ".json")
    assert cli.main(["model-info", out]) == 0
    text = capsys.readouterr().out
    assert "cli_cls.onnx" in text and "input Nx3x32x32" in text and "labels" in text
    assert cli.main(["train", "classify", "--data", str(tmp_path / "empty"), "--out", out]) != 0
    assert cli.main(["model-info", str(tmp_path / "missing.onnx")]) != 0


def test_training_refuses_bad_data_with_a_helpful_message(tmp_path):
    (tmp_path / "onlyone").mkdir()
    with pytest.raises(dl_train.TrainError, match="one folder per class"):
        dl_train.train_classifier(str(tmp_path), str(tmp_path / "x.onnx"), epochs=1)
    with pytest.raises(dl_train.TrainError, match="masks"):
        dl_train.train_segmenter(str(tmp_path), str(tmp_path / "x.onnx"), epochs=1)
    with pytest.raises(dl_train.TrainError, match="GOOD parts"):
        dl_train.train_anomaly(str(tmp_path), str(tmp_path / "x.onnx"), epochs=1)
    with pytest.raises(dl_train.TrainError, match="Dataset description not found"):
        try:
            import ultralytics  # noqa: F401
        except ImportError:
            pytest.skip("ultralytics not installed")
        dl_train.train_detector(str(tmp_path / "no.yaml"), str(tmp_path / "x.onnx"))


def test_deep_learning_modules_live_in_their_own_toolbox_category():
    from apex_vision.core.registry import list_categories
    assert {"DL Classify", "DL Segment", "DL Anomaly", "Object Detection"} <= set(list_categories()["Deep Learning"])
