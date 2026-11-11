"""Writes projects/DeepLearning_Demo.apex: one synthetic part inspected three ways with the bundled demo models.

    python scripts/make_dl_demo_project.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import apex_vision.tools  # noqa: E402,F401
from apex_vision.core.pipeline import SolutionManager  # noqa: E402
from apex_vision.core.registry import create_tool_instance  # noqa: E402

OUT = os.path.join(ROOT, "projects", "DeepLearning_Demo.apex")


def build() -> SolutionManager:
    sol = SolutionManager(name="DeepLearning_Demo")
    flow = sol.add_flow("DeepLearning_Flow")
    for name in [n for n in sol.flows if n != flow.name]:      # a new solution starts with an empty Flow1: not wanted here
        del sol.flows[name]
    sol.active_flow_name = flow.name
    sol.trigger_flow_name = flow.name

    src = create_tool_instance("Image Source", "node_source", "01_MetalSurface")
    src.set_param("source_type", "Synthetic")
    src.set_param("pattern_type", "Metal Surface (demo)")
    cls = create_tool_instance("DL Classify", "node_classify", "02_Classify_GoodOrDefective")
    cls.set_param("model_path", "demo_defect_classifier.onnx")
    cls.set_param("ok_labels", "good")
    seg = create_tool_instance("DL Segment", "node_segment", "03_Segment_DefectPixels")
    seg.set_param("model_path", "demo_defect_segmenter.onnx")
    seg.set_param("min_area", 40)
    ano = create_tool_instance("DL Anomaly", "node_anomaly", "04_Anomaly_NotLikeAGoodPart")
    ano.set_param("model_path", "demo_anomaly.onnx")
    ano.set_param("min_area", 40)

    for node, xy in ((src, (40, 260)), (cls, (380, 40)), (seg, (380, 290)), (ano, (380, 540))):
        flow.add_node(node)
        flow.node_positions[node.instance_id] = list(xy)
    for dst in ("node_classify", "node_segment", "node_anomaly"):
        assert flow.connect("node_source", "Image", dst, "Image")
    return sol


if __name__ == "__main__":
    build().save_to_file(OUT)
    back = SolutionManager.load_from_file(OUT)
    print("saved", os.path.relpath(OUT, ROOT), [(n.name, n.tool_name) for n in back.get_active_flow().nodes.values()])
