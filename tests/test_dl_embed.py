"""'Save model in solution': a model file travels inside the solution, so a solution opens on a computer that does not have the file."""
import os

import numpy as np
import pytest

onnx = pytest.importorskip("onnx")

import apex_vision.tools  # noqa: E402,F401
from apex_vision.core import dl_engine as dl  # noqa: E402
from apex_vision.core import param_schema  # noqa: E402
from apex_vision.core.base_tool import ToolStatus  # noqa: E402
from apex_vision.core.pipeline import VisionPipeline  # noqa: E402
from apex_vision.core.registry import create_tool_instance  # noqa: E402


def build_classifier(path, probs=(0.1, 0.8, 0.1), labels=("good", "scratch", "dent")):
    import json
    from onnx import TensorProto, helper, numpy_helper
    inp = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 32, 32])
    nodes = [helper.make_node("ReduceMean", ["input"], ["m"], keepdims=0), helper.make_node("Mul", ["m", "zero"], ["z"]), helper.make_node("Add", ["z", "c"], ["out"])]
    inits = [numpy_helper.from_array(np.zeros((), np.float32), "zero"), numpy_helper.from_array(np.asarray([probs], np.float32), "c")]
    graph = helper.make_graph(nodes, "g", [inp], [helper.make_tensor_value_info("out", TensorProto.FLOAT, [1, len(probs)])], initializer=inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))
    with open(str(path).rsplit(".", 1)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({"labels": list(labels), "input_size": [32, 32], "task": "classify"}, f)
    return str(path)


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    dl.clear_cache()
    return h


def make(path, save=True):
    t = create_tool_instance("DL Classify", "n1")
    t.set_param("model_path", path)
    t.set_param("save_in_solution", save)
    return t


PIC = np.full((64, 64, 3), 120, np.uint8)


def test_the_model_is_packed_when_asked_and_not_otherwise(tmp_path, home):
    path = build_classifier(tmp_path / "net.onnx")
    off = make(path, save=False)
    assert off.execute({"Image": PIC}).outputs["Class"] == "scratch" and not off.parameters["model_data"]
    on = make(path)
    r = on.execute({"Image": PIC})
    assert r.status in (ToolStatus.OK, ToolStatus.NG) and r.outputs["Class"] == "scratch"
    data = on.parameters["model_data"]
    assert data["name"] == "net.onnx" and data["onnx"] and data["sha1"] and "scratch" in data["meta"]


def test_a_solution_runs_without_the_file(tmp_path, home):
    path = build_classifier(tmp_path / "net.onnx")
    t = make(path)
    t.execute({"Image": PIC})
    flow = VisionPipeline("F")
    flow.add_node(t)
    xml = flow.to_xml()
    os.remove(path)
    os.remove(path.rsplit(".", 1)[0] + ".json")
    dl.clear_cache()
    back = VisionPipeline.from_xml(xml)
    t2 = back.nodes["n1"]
    assert t2.parameters["model_data"]["sha1"] == t.parameters["model_data"]["sha1"]
    r = t2.execute({"Image": PIC})
    assert r.outputs["Class"] == "scratch", r.message
    assert os.path.isdir(home / ".apex_vision" / "embedded") and len(os.listdir(home / ".apex_vision" / "embedded")) == 2, "the model and its settings were unpacked"
    again = t2.execute({"Image": PIC})
    assert again.outputs["Class"] == "scratch"


def test_a_copy_is_used_even_when_the_save_option_is_off_but_the_file_is_gone(tmp_path, home):
    path = build_classifier(tmp_path / "net.onnx")
    t = make(path)
    t.execute({"Image": PIC})
    os.remove(path)
    t.set_param("save_in_solution", False)
    dl.clear_cache()
    assert t.execute({"Image": PIC}).outputs["Class"] == "scratch"


def test_a_changed_file_is_packed_again(tmp_path, home):
    path = build_classifier(tmp_path / "net.onnx")
    t = make(path)
    t.execute({"Image": PIC})
    first = t.parameters["model_data"]["sha1"]
    build_classifier(tmp_path / "net.onnx", probs=(0.7, 0.2, 0.1))
    dl.clear_cache()
    r = t.execute({"Image": PIC})
    assert r.outputs["Class"] == "good" and t.parameters["model_data"]["sha1"] != first


def test_a_model_over_the_limit_is_refused(tmp_path, home, monkeypatch):
    path = build_classifier(tmp_path / "net.onnx")
    monkeypatch.setattr(dl, "MAX_EMBED_BYTES", 10)
    t = make(path)
    r = t.execute({"Image": PIC})
    assert r.status == ToolStatus.ERROR and "500 MB" in r.message
    assert dl.embed_file(path) is None
    assert dl.embed_file(str(tmp_path / "missing.onnx")) is None
    t.set_param("save_in_solution", False)
    assert t.execute({"Image": PIC}).outputs["Class"] == "scratch", "with the option off the file is simply used"


def test_the_packed_model_is_kept_out_of_the_inspector():
    assert param_schema.spec_for("DL Classify", "model_data", {})["kind"] == "hidden"
    assert param_schema.spec_for("OCV", "model", {})["kind"] == "hidden"
    assert param_schema.spec_for("DL Classify", "save_in_solution", False)["kind"] == "bool"
    from apex_vision.qml_backend import AppBackend  # noqa: F401  (imports cleanly with the hidden kind in place)


def test_a_damaged_copy_is_ignored(tmp_path, home):
    assert dl.materialize({"onnx": "!!not base64!!", "name": "x.onnx", "sha1": "abc"}) is None
    assert dl.materialize({}) is None
    t = create_tool_instance("DL Classify", "n1")
    t.set_param("model_path", str(tmp_path / "gone.onnx"))
    t.parameters["model_data"] = {"onnx": "AAAA", "sha1": "z", "name": "q.onnx"}
    assert t.execute({"Image": PIC}).status == ToolStatus.ERROR


def test_object_detection_and_the_character_modules_use_it_too(tmp_path, home):
    for tool_name in ("Object Detection", "DL Character Recognition", "DL Character Location", "DL Single Character Recognition"):
        t = create_tool_instance(tool_name, "n")
        assert "model_data" in t.parameters and "save_in_solution" in t.parameters, tool_name
