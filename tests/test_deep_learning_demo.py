"""The deep-learning demo that ships with the app: three small models, a project that uses them, and the packaging that carries them.
These checks need no PyTorch (the models are already built), so they run everywhere the app does."""
import json
import os

import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core import dl_engine as dl
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.pipeline import SolutionManager
from apex_vision.core.registry import create_tool_instance
from apex_vision.samples import demo_parts

ROOT = os.path.join(os.path.dirname(__file__), "..")
MODELS = os.path.join(ROOT, "apex_vision", "samples", "models")
PROJECT = os.path.join(ROOT, "projects", "DeepLearning_Demo.apex")
BACKENDS = dl.available_backends()


def test_demo_models_and_their_json_files_are_present_and_small():
    for name, task in (("demo_defect_classifier", "classify"), ("demo_defect_segmenter", "segment"), ("demo_anomaly", "anomaly")):
        onnx, js = os.path.join(MODELS, name + ".onnx"), os.path.join(MODELS, name + ".json")
        assert os.path.isfile(onnx) and os.path.isfile(js)
        assert os.path.getsize(onnx) < 2_000_000
        assert json.load(open(js))["task"] == task


def test_bare_demo_model_names_are_found_without_a_path():
    for name in ("demo_defect_classifier.onnx", "demo_defect_segmenter.onnx", "demo_anomaly.onnx"):
        assert os.path.isfile(dl.resolve_path(name))


@pytest.mark.parametrize("backend", BACKENDS)
def test_demo_flow_tells_good_parts_from_defective_ones_with_every_module(backend):
    sol = SolutionManager.load_from_file(PROJECT)
    flow = sol.get_active_flow()
    for node in flow.nodes.values():
        if node.tool_name.startswith("DL "):
            node.set_param("backend", backend)
    seen = []
    for i in range(12):
        res = flow.execute_flow(global_vars=sol.global_variables)
        kind = demo_parts.make_part(i)[1]
        c, s, a = res["node_classify"], res["node_segment"], res["node_anomaly"]
        want = ToolStatus.OK if kind == "good" else ToolStatus.NG
        assert (c.status, s.status, a.status) == (want, want, want), (i, kind, c.message, s.message, a.message)
        assert c.outputs["Class"] == kind, (i, kind, c.outputs["Class"])
        seen.append(kind)
    assert set(seen) == {"good", "scratch", "blotch"}


def test_demo_modules_report_what_they_found():
    sol = SolutionManager.load_from_file(PROJECT)
    flow = sol.get_active_flow()
    flow.execute_flow(global_vars=sol.global_variables)                     # part 0: good
    res = flow.execute_flow(global_vars=sol.global_variables)               # part 1: a scratch
    seg, ano, cls = res["node_segment"].outputs, res["node_anomaly"].outputs, res["node_classify"].outputs
    assert seg["Defect_Count"] == 1 and seg["Defect_Area"] > 100 and seg["Boxes"][0][2] > 20
    assert ano["Anomaly_Score"] > 0.2 and ano["Defect_Count"] >= 1 and ano["Heatmap"].shape == (256, 256, 3)
    assert cls["Class"] == "scratch" and cls["Confidence"] > 0.8 and cls["Scores"][0]["label"] == "scratch"


def test_anomaly_picks_how_to_read_the_model_from_its_json_by_default():
    t = create_tool_instance("DL Anomaly", "t")
    assert t.get_param("output_type") == "Auto (from the model)"
    t.set_param("model_path", "demo_anomaly.onnx")
    r = t.execute({"Image": demo_parts.make_part(0)[0]})
    assert r.status == ToolStatus.OK and r.outputs["Anomaly_Score"] < 0.2


def test_demo_project_starts_with_an_empty_image_strip():
    from apex_vision.qml_backend import AppBackend
    assert not AppBackend.uses_sample_images(SolutionManager.load_from_file(PROJECT))


def test_the_demo_part_generator_is_deterministic_and_alternates():
    a, ka = demo_parts.make_part(7)
    b, kb = demo_parts.make_part(7)
    assert ka == kb and np.array_equal(a, b)
    assert [demo_parts.make_part(i)[1] for i in range(8)] == ["good", "scratch", "good", "blotch", "good", "scratch", "good", "blotch"]
    t = create_tool_instance("Image Source", "t")
    t.set_param("pattern_type", "Metal Surface (demo)")
    first, second = t.execute({}).outputs["Image"], t.execute({}).outputs["Image"]
    assert first.shape == (256, 256, 3) and not np.array_equal(first, second)


def test_the_installer_ships_the_demo_models_and_only_the_demo_projects_and_public_plugin():
    spec = open(os.path.join(ROOT, "ApexVisionStudio.spec"), encoding="utf-8").read()
    assert "apex_vision/samples/models" in spec
    assert "('plugins', 'plugins')" not in spec and "plugins/sample_sobel_edge_plugin" in spec, "private plugins must not be packed"
    assert "_Demo.apex" in spec and "datas.append(('projects', 'projects'))" not in spec, "other projects must not be packed"


def test_demo_project_has_exactly_one_flow():
    sol = SolutionManager.load_from_file(PROJECT)
    assert list(sol.flows) == ["DeepLearning_Flow"] and sol.active_flow_name == "DeepLearning_Flow"
