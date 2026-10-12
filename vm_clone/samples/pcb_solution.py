"""
Additional comprehensive industrial machine vision solutions:
1. PCB Inspection & Defect Analysis
2. Precision Dimensional Measurement & Hole Caliper
3. Color Verification & Robot N-Point Calibration
"""
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.core.registry import create_tool_instance
import vm_clone.tools  # Ensure registered


def create_pcb_inspection_solution() -> VisionPipeline:
    """Standard PCB Optical Inspection Solution."""
    pipe = VisionPipeline(name="PCB_AOI_Solution")

    src = create_tool_instance("Image Source", "node_source", "01_ImageAcquisition")
    src.set_param("pattern_type", "PCB Inspection")
    pipe.add_node(src)

    tm = create_tool_instance("Template Match", "node_template", "02_IC_Alignment")
    tm.set_param("template_roi", [260, 240, 180, 120])
    tm.set_param("min_score", 0.70)
    pipe.add_node(tm)
    pipe.connect("node_source", "Image", "node_template", "Image")

    cs = create_tool_instance("Circle Search", "node_circle", "03_MountingHole")
    cs.set_param("min_radius", 25)
    cs.set_param("max_radius", 60)
    pipe.add_node(cs)
    pipe.connect("node_source", "Image", "node_circle", "Image")

    cal = create_tool_instance("Caliper", "node_caliper", "04_TraceWidthCaliper")
    cal.set_param("line_p1", [50, 150])
    cal.set_param("line_p2", [450, 150])
    pipe.add_node(cal)
    pipe.connect("node_source", "Image", "node_caliper", "Image")

    def_tool = create_tool_instance("Defect Detection", "node_defect", "05_SurfaceScratchCheck")
    def_tool.set_param("roi", [260, 240, 180, 120])
    def_tool.set_param("sensitivity", 30)
    pipe.add_node(def_tool)
    pipe.connect("node_source", "Image", "node_defect", "Image")

    cond = create_tool_instance("Condition Branch", "node_branch", "06_QualityJudge")
    cond.set_param("operator", "<=")
    cond.set_param("threshold_low", 0.0)
    pipe.add_node(cond)
    pipe.connect("node_defect", "Defect_Count", "node_branch", "Val_In")

    tcp = create_tool_instance("TCP Send", "node_tcp", "07_SendToPLC")
    pipe.add_node(tcp)
    pipe.connect("node_branch", "Status", "node_tcp", "Data")

    return pipe


def create_calibration_robot_solution() -> VisionPipeline:
    """Robot guidance & Color extraction solution."""
    pipe = VisionPipeline(name="Robot_Calibration_Solution")

    src = create_tool_instance("Image Source", "node_source", "01_ColorAcquisition")
    src.set_param("pattern_type", "PCB Inspection")
    pipe.add_node(src)

    col = create_tool_instance("Color Extraction", "node_color", "02_ExtractTargetColor")
    col.set_param("preset_color", "Green")
    pipe.add_node(col)
    pipe.connect("node_source", "Image", "node_color", "Image")

    blob = create_tool_instance("BLOB Analysis", "node_blob", "03_TargetCentroid")
    blob.set_param("threshold", 40)
    pipe.add_node(blob)
    pipe.connect("node_color", "Image", "node_blob", "Image")

    calib = create_tool_instance("N-Point Calibration", "node_calib", "04_PixelToRobotWorld")
    pipe.add_node(calib)

    tcp = create_tool_instance("TCP Send", "node_tcp", "05_TransmitRobotOffset")
    pipe.add_node(tcp)
    pipe.connect("node_calib", "World_X", "node_tcp", "Data")

    return pipe


def create_precision_measurement_solution() -> VisionPipeline:
    """Precision hole diameter, line-to-line distance, and edge alignment."""
    pipe = VisionPipeline(name="Precision_Measurement_Solution")

    src = create_tool_instance("Image Source", "node_source", "01_Acquisition")
    src.set_param("pattern_type", "Circles & Holes")
    pipe.add_node(src)

    cs = create_tool_instance("Circle Search", "node_circle1", "02_InnerHoleFit")
    cs.set_param("min_radius", 15)
    cs.set_param("max_radius", 80)
    pipe.add_node(cs)
    pipe.connect("node_source", "Image", "node_circle1", "Image")

    p2p = create_tool_instance("P2P Measure", "node_p2p", "03_HoleDistance")
    pipe.add_node(p2p)
    pipe.connect("node_circle1", "Center_X", "node_p2p", "Point1")

    intensity = create_tool_instance("Intensity Measure", "node_intensity", "04_IlluminationCheck")
    pipe.add_node(intensity)
    pipe.connect("node_source", "Image", "node_intensity", "Image")

    return pipe


def create_object_detection_solution() -> VisionPipeline:
    """Deep learning neural detection using Ultralytics YOLOv11."""
    pipe = VisionPipeline(name="YOLO_Detection_Solution")

    src = create_tool_instance("Image Source", "node_source", "01_Acquisition")
    src.set_param("pattern_type", "PCB Inspection")
    pipe.add_node(src)

    det = create_tool_instance("Object Detection", "node_yolo", "02_YOLOv11_Detector")
    det.set_param("model_path", "yolo11n.pt")
    det.set_param("confidence", 0.25)
    det.set_param("iou", 0.45)
    det.set_param("classes", "all")
    pipe.add_node(det)
    pipe.connect("node_source", "Image", "node_yolo", "Image")

    return pipe

