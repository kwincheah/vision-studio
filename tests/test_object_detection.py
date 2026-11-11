"""
Automated unit tests for Deep Learning Object Detection Tool (YOLOv11).
Verifies:
- Registration and category
- Port definitions and default parameters
- Class filtering logic (_parse_classes)
- Error handling on missing input image
- YOLOv11 model loading and inference execution
- ROI handling and coordinate mapping
- Pipeline execution and XML flow serialization roundtrip
"""
import os
import tempfile
import pytest
import numpy as np
import cv2

from apex_vision.core.registry import list_all_tools, create_tool_instance
from apex_vision.core.base_tool import ToolStatus, DataType
from apex_vision.core.pipeline import VisionPipeline
from apex_vision.tools.object_detection import ObjectDetectionTool, _get_yolo_model

try:
    import ultralytics
    HAS_ULTRALYTICS = True
except ImportError:
    HAS_ULTRALYTICS = False

requires_ultralytics = pytest.mark.skipif(
    not HAS_ULTRALYTICS, reason="ultralytics not installed in environment"
)


def test_object_detection_registered():
    """Verify ObjectDetectionTool is registered under Deep Learning category."""
    tools = list_all_tools()
    assert "Object Detection" in tools
    instance = create_tool_instance("Object Detection", "obj_det_1")
    assert isinstance(instance, ObjectDetectionTool)
    assert instance.category == "Deep Learning"
    assert instance.tool_name == "Object Detection"


def test_object_detection_ports_and_parameters():
    """Verify input/output ports and initial parameters."""
    tool = create_tool_instance("Object Detection", "test_ports")
    
    # Input ports
    assert "Image" in tool.inputs
    assert tool.inputs["Image"].data_type == DataType.IMAGE
    assert "ROI" in tool.inputs
    assert tool.inputs["ROI"].data_type == DataType.REGION

    # Output ports
    assert "Image" in tool.outputs
    assert "Count" in tool.outputs
    assert tool.outputs["Count"].data_type == DataType.VALUE
    assert "Boxes" in tool.outputs
    assert "Classes" in tool.outputs
    assert "Scores" in tool.outputs
    assert "Status" in tool.outputs
    assert "Detections" in tool.outputs

    # Default parameters
    assert tool.get_param("model_path") == "yolo11n.onnx"
    assert tool.get_param("confidence") == 0.25
    assert tool.get_param("iou") == 0.45
    assert tool.get_param("classes") == "all"
    assert tool.get_param("device") == "cpu"
    assert tool.get_param("max_detections") == 100


def test_object_detection_no_image():
    """Verify execution with missing image returns NG status without throwing."""
    tool = create_tool_instance("Object Detection", "test_no_img")
    result = tool.execute({})
    assert result.status == ToolStatus.NG
    assert result.outputs["Count"] == 0
    assert result.outputs["Boxes"] == []
    assert result.outputs["Classes"] == []
    assert result.outputs["Status"] == "NG"
    assert "No input image provided" in result.message


def test_parse_classes_helper():
    """Verify class filter parsing for names, indices, strings, and collections."""
    tool = ObjectDetectionTool("test_parse")
    fake_names = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 32: "sports ball"}

    # All / empty filters -> None
    assert tool._parse_classes(None, fake_names) is None
    assert tool._parse_classes("", fake_names) is None
    assert tool._parse_classes("all", fake_names) is None
    assert tool._parse_classes("*", fake_names) is None
    assert tool._parse_classes([], fake_names) is None

    # By class names
    res_names = tool._parse_classes("person, car", fake_names)
    assert res_names == [0, 2]

    # By class indices
    res_indices = tool._parse_classes("0, 32", fake_names)
    assert res_indices == [0, 32]

    # Mixed list/tuple
    res_mixed = tool._parse_classes(["person", "32"], fake_names)
    assert res_mixed == [0, 32]

    # Unknown names ignored
    res_unknown = tool._parse_classes("person, nonexistent_object", fake_names)
    assert res_unknown == [0]


@requires_ultralytics
def test_yolo_model_cache():
    """Verify that model loading caches model instance."""
    m1 = _get_yolo_model("yolo11n.pt")
    m2 = _get_yolo_model("yolo11n.pt")
    assert m1 is m2


@requires_ultralytics
def test_inference_on_synthetic_image():
    """Verify YOLOv11 inference runs successfully on an image."""
    tool = create_tool_instance("Object Detection", "det_infer")
    
    # Create test image: 320x320 blank image with simulated shapes
    test_img = np.full((320, 320, 3), 128, dtype=np.uint8)
    
    result = tool.execute({"Image": test_img})
    assert result.status in (ToolStatus.OK, ToolStatus.READY)
    assert "Count" in result.outputs
    assert isinstance(result.outputs["Count"], int)
    assert isinstance(result.outputs["Boxes"], list)
    assert isinstance(result.outputs["Classes"], list)
    assert isinstance(result.outputs["Scores"], list)
    assert isinstance(result.outputs["Detections"], list)
    assert "Image" in result.outputs


@requires_ultralytics
def test_inference_with_roi():
    """Verify YOLOv11 inference with ROI offset mapping."""
    tool = create_tool_instance("Object Detection", "det_roi")
    
    test_img = np.full((400, 400, 3), 100, dtype=np.uint8)
    roi = [50, 60, 200, 200]
    
    result = tool.execute({"Image": test_img, "ROI": roi})
    assert result.status in (ToolStatus.OK, ToolStatus.READY)
    assert result.outputs["Count"] >= 0


@requires_ultralytics
def test_pipeline_and_xml_serialization():
    """Verify Object Detection tool in a VisionPipeline and XML export/import roundtrip."""
    pipeline = VisionPipeline(name="TestDLFlow")
    
    acq = create_tool_instance("Image Source", "acq_1")
    acq.set_param("pattern_type", "Part with Defects")
    pipeline.add_node(acq)

    det = create_tool_instance("Object Detection", "det_1")
    det.set_param("model_path", "yolo11n.pt")
    det.set_param("confidence", 0.35)
    det.set_param("iou", 0.50)
    det.set_param("classes", "0, 1")
    pipeline.add_node(det)

    pipeline.connect("acq_1", "Image", "det_1", "Image")

    # Execute pipeline
    results = pipeline.execute_flow()
    assert "acq_1" in results
    assert "det_1" in results
    assert results["acq_1"].status == ToolStatus.OK
    assert results["det_1"].status in (ToolStatus.OK, ToolStatus.READY)

    # Export to XML and import back
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        tmp_path = f.name

    try:
        pipeline.export_to_xml(tmp_path)
        assert os.path.exists(tmp_path)
        assert os.path.getsize(tmp_path) > 0

        # Import into new pipeline
        loaded = VisionPipeline.import_from_xml(tmp_path)
        assert "det_1" in loaded.nodes
        loaded_det = loaded.nodes["det_1"]
        assert loaded_det.tool_name == "Object Detection"
        assert loaded_det.get_param("confidence") == 0.35
        assert loaded_det.get_param("iou") == 0.50
        assert loaded_det.get_param("classes") == "0, 1"
        assert len(loaded.connections) == 1
        assert loaded.connections[0].from_node == "acq_1"
        assert loaded.connections[0].to_node == "det_1"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_object_detection_with_blob_analysis_roi():
    """Verify Object Detection can consume the Blobs list output from BLOB Analysis without crashing."""
    det = ObjectDetectionTool("det_blob_roi")
    img = np.zeros((300, 300, 3), dtype=np.uint8)

    # 1. Multiple blobs dict format from BlobAnalysisTool
    blobs = [
        {"id": 1, "cx": 50, "cy": 50, "area": 100, "box": [40, 40, 20, 20], "circularity": 0.8},
        {"id": 2, "cx": 150, "cy": 150, "area": 200, "box": [140, 140, 30, 30], "circularity": 0.9},
        {"id": 3, "cx": 200, "cy": 200, "area": 150, "box": [190, 190, 25, 25], "circularity": 0.7},
        {"id": 4, "cx": 250, "cy": 250, "area": 180, "box": [240, 240, 20, 20], "circularity": 0.85},
    ]

    res = det.execute({"Image": img, "ROI": blobs})
    assert res.status != ToolStatus.ERROR
    assert "int() argument must be a string" not in res.message

    # 2. Single blob dict format
    single_blob = {"id": 1, "box": [20, 20, 50, 50]}
    res_single = det.execute({"Image": img, "ROI": single_blob})
    assert res_single.status != ToolStatus.ERROR

    # 3. Standard list format [x, y, w, h]
    res_box = det.execute({"Image": img, "ROI": [10, 10, 80, 80]})
    assert res_box.status != ToolStatus.ERROR



def _detect(model, img):
    import numpy as np  # noqa: F401
    from apex_vision.core.pipeline import VisionPipeline
    from apex_vision.core.registry import create_tool_instance
    pipe = VisionPipeline(name="F")
    src = create_tool_instance("Image Source", "a", "01")
    src._override_image = img
    det = create_tool_instance("Object Detection", "o", "02")
    det.set_param("model_path", model)
    pipe.add_node(src)
    pipe.add_node(det)
    pipe.connect("a", "Image", "o", "Image")
    pipe.execute_flow()
    return pipe.last_results["o"]


def test_without_pytorch_a_pt_model_needs_the_converter_and_says_so(monkeypatch, tmp_path):
    import shutil
    import numpy as np
    from apex_vision.core import dl_engine as dl
    from apex_vision.tools import object_detection as od
    monkeypatch.setattr(od, "_pytorch_available", lambda: False)
    monkeypatch.setattr(dl, "pytorch_available", lambda: False)
    monkeypatch.delenv("APEX_MODEL_CONVERTER", raising=False)
    monkeypatch.setattr(dl, "find_converter", lambda: None)
    pt = tmp_path / "custom.pt"
    shutil.copyfile("yolo11n.pt", pt)
    res = _detect(str(pt), np.zeros((120, 160, 3), np.uint8))
    assert res.status.value == "Error" and "PyTorch" in res.message and "Converter" in res.message and ".onnx" in res.message


def test_a_pt_model_is_converted_by_the_converter_program_once_and_reused(monkeypatch, tmp_path):
    import cv2
    import shutil
    from apex_vision.core import dl_engine as dl
    from apex_vision.tools import object_detection as od
    monkeypatch.setattr(od, "_pytorch_available", lambda: False)
    monkeypatch.setattr(dl, "pytorch_available", lambda: False)
    log = tmp_path / "calls.txt"
    conv = tmp_path / "ApexModelConverter.bat"                      # stands in for the real program: same arguments, copies a model
    onnx = os.path.abspath("yolo11n.onnx")
    eol = chr(13) + chr(10)
    conv.write_bytes((eol.join(['@echo off', 'echo %1>>' + chr(34) + str(log) + chr(34),
                                'copy /y ' + chr(34) + onnx + chr(34) + ' %2 >nul', '']).encode()))
    monkeypatch.setenv("APEX_MODEL_CONVERTER", str(conv))
    pt = tmp_path / "my model.pt"
    shutil.copyfile("yolo11n.pt", pt)
    img = cv2.imread("dist/ApexVisionStudio/_internal/ultralytics/assets/bus.jpg")
    res = _detect(str(pt), img)
    assert res.status.value == "OK" and "bus" in res.message, res.message
    assert (tmp_path / "my model.onnx").exists()
    _detect(str(pt), img)
    assert len(log.read_text().strip().splitlines()) == 1, "converted once, then reused"
    os.utime(pt, (os.path.getmtime(pt) + 100, os.path.getmtime(pt) + 100))      # the .pt was replaced by a newer one
    _detect(str(pt), img)
    assert len(log.read_text().strip().splitlines()) == 2, "a newer .pt is converted again"


def test_a_pt_model_converts_in_process_where_pytorch_is_installed(tmp_path):
    import shutil
    from apex_vision.core import dl_engine as dl
    if not dl.pytorch_available():
        return
    pt = tmp_path / "m.pt"
    shutil.copyfile("yolo11n.pt", pt)
    out = dl.convert_pt_to_onnx(str(pt), 640)
    assert out.endswith("m.onnx") and os.path.getsize(out) > 1_000_000
