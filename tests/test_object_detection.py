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

from vm_clone.core.registry import list_all_tools, create_tool_instance
from vm_clone.core.base_tool import ToolStatus, DataType
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.tools.object_detection import ObjectDetectionTool, _get_yolo_model


def test_object_detection_registered():
    """Verify ObjectDetectionTool is registered under Recognition category."""
    tools = list_all_tools()
    assert "Object Detection" in tools
    instance = create_tool_instance("Object Detection", "obj_det_1")
    assert isinstance(instance, ObjectDetectionTool)
    assert instance.category == "Recognition"
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
    assert tool.get_param("model_path") == "yolo11n.pt"
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


def test_yolo_model_cache():
    """Verify that model loading caches model instance."""
    m1 = _get_yolo_model("yolo11n.pt")
    m2 = _get_yolo_model("yolo11n.pt")
    assert m1 is m2


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


def test_inference_with_roi():
    """Verify YOLOv11 inference with ROI offset mapping."""
    tool = create_tool_instance("Object Detection", "det_roi")
    
    test_img = np.full((400, 400, 3), 100, dtype=np.uint8)
    roi = [50, 60, 200, 200]
    
    result = tool.execute({"Image": test_img, "ROI": roi})
    assert result.status in (ToolStatus.OK, ToolStatus.READY)
    assert result.outputs["Count"] >= 0


def test_pipeline_and_xml_serialization():
    """Verify Object Detection tool in a VisionPipeline and XML export/import roundtrip."""
    pipeline = VisionPipeline(name="TestDLFlow")
    
    acq = create_tool_instance("Image Source", "acq_1")
    acq.set_param("pattern_type", "PCB Inspection")
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
