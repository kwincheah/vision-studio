"""Maps every vision tool in the Hikrobot VisionMaster user guide to the Apex Vision module that covers it, and writes
docs/VM_COVERAGE.md.  Run: python scripts/vm_coverage.py   (tests/test_vm_coverage.py keeps the map honest).

Each entry is  guide name -> (our module name | None, note).  None = not available yet.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# chapter -> [(guide tool, our module, note)]
GUIDE = {
    "Acquisition": [
        ("Image Source", "Image Source", ""), ("Multi-image Acquisition", "Multi-image Acquisition", ""), ("Image Output", "Image Output", ""),
        ("Image Buffer", "Image Buffer", ""), ("Light Source", "Light Source", "simulation, serial or TCP with your own command template; no vendor controller drivers"),
    ],
    "Location": [
        ("Template Match", "Template Match", ""), ("Mark Location", "Mark Location", ""), ("Matrix Circle Search", "Matrix Circle Search", ""),
        ("Circle Search", "Circle Search", ""), ("Line Search", "Line Search", ""), ("Ellipse Search", "Ellipse Search", ""),
        ("BLOB Analysis", "BLOB Analysis", ""), ("Caliper", "Caliper", ""), ("Edge Search", "Edge Search", ""),
        ("Position Correction", "Position Correction", ""), ("Rect Search", "Rect Search", ""), ("Peak Search", "Peak Search", ""),
        ("Edge Intersection", "Edge Intersection", ""), ("Parallel Lines Search", "Parallel Lines Search", ""), ("Quadrilateral Search", "Quadrilateral Search", ""),
        ("Line Group Search", "Line Group Search", ""), ("Multi-line Search", "Multi-line Search", ""), ("BLOB Label Analysis", "BLOB Label Analysis", ""),
        ("Path Extraction", "Path Extraction", ""), ("Find Angle Bisector", "Find Angle Bisector", ""), ("Find Median Line", "Find Median Line", ""),
        ("Calculate Parallel Lines", "Calculate Parallel Lines", ""), ("Find Vertical Line", "Find Vertical Line", ""), ("Target Tracking", "Target Tracking", ""),
    ],
    "Measurement": [
        ("L2C Measure", "L2C Measure", ""), ("L2L, C2C Measure", "L2L Measure", "line to line here; circle to circle is the separate C2C Measure module"), ("P2C, P2L, P2P Measure", "P2P Measure", "point to point here; P2L Measure and P2C Measure are separate modules"),
        ("Intensity Measure", "Intensity Measure", ""), ("Pixel Count", "Pixel Count", ""), ("Edge Distance", "Edge Distance", ""),
        ("Histogram", "Histogram", ""),
    ],
    "Image Generation": [("Circle Fit, Ellipse Fit, and Line Fit", "Circle/Line Fit", ""), ("Geometry Generation", "Geometry Generation", "")],
    "Recognition": [
        ("2D BCR Recognition", "2D BCR Recognition", ""), ("BCR Recognition", "BCR Recognition", ""), ("OCR Recognition", "OCR Recognition", ""),
        ("DL Character Recognition", "DL Character Recognition", "built-in reader for clean printed characters; your own ONNX text model (CTC) for anything harder. VisionMaster's trained default model is not available"), ("DL Code Reading", "DL Code Reading", "QR and the 1D codes OpenCV decodes; DataMatrix and ISO grading beyond a contrast grade are not included"), ("DL Character Location", "DL Character Location", "threshold-based finding, or an ONNX detector; no angle filter"),
        ("DL Single Character Recognition", "DL Single Character Recognition", "built-in reader, or an ONNX detector whose classes are the characters"), ("ML Classification", "ML Classification", "k-nearest-neighbour on shape and colour features that you teach it; VisionMaster model files are not read"),
    ],
    "Deep Learning": [
        ("DL Image Segmentation", "DL Segment", ""), ("DL Classification", "DL Classify", ""), ("DL Object Detection", "Object Detection", ""),
        ("Classification Registration", "Classification Registration", "built-in shape/colour description, so it tells apart clearly different looks"), ("DL Image Retrieval", "DL Image Retrieval", ""), ("DL Anomaly Detection", "DL Anomaly", ""),
        ("DL Instance Segment", "DL Instance Segment", "YOLO-seg style ONNX models"), ("DL Image Defect Prediction", "DL Image Defect Prediction", "reads any ONNX model that outputs a defect map"),
    ],
    "Calibration": [
        ("Camera Mapping", "Camera Mapping", ""), ("CalibBoard Calibration", "CalibBoard Calibration", ""), ("N-Point Calibration", "N-Point Calibration", ""),
        ("Translation and Rotation Calibration", "Translation and Rotation Calibration", ""), ("Distortion Calibration", "Lens Distortion Calibration", ""),
        ("Mapping Calibration", "Mapping Calibration", ""), ("N-Image Calibration", "N-Image Calibration", ""), ("Load Calibration", "Load Calibration", ""), ("Rotation Calibration", "Rotation Calibration", ""),
    ],
    "Calculation": [
        ("Single Point Alignment", "Single Point Alignment", ""), ("Single Point Grasp", "Single Point Grasp", ""), ("Single Point Mapping Alignment", "Single Point Mapping Alignment", ""),
        ("Single Point Rectification", "Single Point Rectification", ""), ("Calculate Rotation", "Calculate Rotation", ""), ("Point Set Alignment", "Point Set Alignment", ""),
        ("Calibration Transformation", "Calibration Transformation", ""), ("Scale Transformation", "Scale Transformation", ""), ("Line Alignment", "Line Alignment", ""),
        ("Variable Calculation", "Variable Calculation", ""), ("Coordinate Transformation", "Coordinate Transformation", ""),
    ],
    "Image Processing": [
        ("Image Combination", "Image Combination", ""), ("Image Morphology", "Image Morphology", ""), ("Image Binarization", "Image Binarization", ""),
        ("Image Filter", "Image Filter", ""), ("Image Enhancement", "Image Enhancement", ""), ("Image Computing", "Image Calculate", ""),
        ("Distortion Correction", "Distortion Correction", ""), ("Image Clarity", "Focus Measure", ""), ("Image Fixture", "Image Fixture", ""), ("Shade Correction", "Shade Correction", ""),
        ("Inverse Affine Transformation", "Inverse Affine Transformation", ""), ("Affine Transformation", "Affine Transformation", ""), ("Ring Expansion", "Ring Expansion", ""), ("Copy Fill", "Copy Fill", ""),
        ("Frame Mean", "Frame Mean", ""), ("Image Normalization", "Image Normalization", ""), ("Image Correction", "Image Correction", ""),
        ("Geometric Transformation", "Image Transform", ""), ("Image Stitch", "Image Stitch", ""), ("Multiple Images Fusion", "Multiple Images Fusion", ""),
    ],
    "Color Processing": [
        ("Color Extraction", "Color Extraction", ""), ("Color Measurement", "Color Measurement", ""),
        ("Color Transformation", "Color Convert", ""), ("Color Recognition", "Color Recognition", ""),
    ],
    "Division and Combination": [
        ("Image Division Tool", "Image Division Tool", ""), ("2D Array Correction", "2D Array Correction", ""), ("Pixel Transformation", "Pixel Transformation", ""),
        ("Box Merge", "Box Merge", ""), ("Box Overlap", "Box Overlap", ""), ("Box Filtering", "Box Filtering", ""),
    ],
    "Defect Detection": [
        ("OCV", "OCV", "statistical model of the whole print area; no per-character segmentation"), ("Surface Defect Filtering", "Surface Defect Filter", "oriented line-detector bank; same controls, different kernel"), ("Arc Edge Defect Detection", "Arc Edge Defect Detection", ""),
        ("Linear Edge Defect Detection", "Linear Edge Defect Detection", ""), ("Arc-Pair Defect Detection", "Arc-Pair Defect Detection", ""),
        ("Line-Pair Defect Detection", "Line-Pair Defect Detection", ""), ("Edge Group Defect Detection", "Edge Group Defect Detection", ""), ("Edge Pair Group Defect Detection", "Edge Pair Group Defect Detection", ""),
        ("Edge Model Defect Detection", "Edge Model Defect Detection", ""), ("Edge Pair Model Defect Detection", "Edge Pair Model Defect Detection", ""), ("Defect Contrast", "Defect Contrast", ""),
        ("Edge Position Trend Analysis", "Edge Position Trend Analysis", ""), ("Edge Pair Position Trend Analysis", "Edge Pair Trend Analysis", ""),
    ],
    "Logic Tools": [
        ("Condition Branch", "Condition Branch", ""), ("Condition Detection", "Condition Detection", ""), ("Branch", "Branch", ""),
        ("Branch String", "Branch String", ""), ("Save Text", "Save Text", ""), ("Logic Module", "If Module", ""), ("Format Module", "Format Module", ""),
        ("String Comparison", "String Comparison", ""), ("Script", "Script", ""), ("Group", "Group", "modules are put in with right-click, Add to group (not a separate sub-canvas); loop and break condition supported"), ("Point Set", "Point Set", ""),
        ("Time Consuming", "Time Consuming", ""), ("Data Set", "Data Set", ""), ("Trigger", "Trigger", ""), ("Graphic Collection", "Graphic Collection", ""),
    ],
    "Communication": [
        ("Receive Data", "Receive Data", ""), ("Send Data", "Send Data", "global variable and queue targets; TCP Send, UDP Send, Serial Send and Modbus TCP Write send to devices"), ("Camera IO Communication", "Camera IO", ""),
        ("Protocol Parsing", "Protocol Parsing", ""), ("Protocol Assembly", "Protocol Assembly", ""),
    ],
}


def build():
    import apex_vision.tools  # noqa: F401
    from apex_vision.core.registry import list_all_tools
    have = set(list_all_tools())
    rows, bad = [], []
    for chapter, items in GUIDE.items():
        for guide, ours, note in items:
            if ours is not None and ours not in have:
                bad.append((guide, ours))
            rows.append((chapter, guide, ours, note))
    return rows, bad


def render() -> str:
    rows, _ = build()
    total = len(rows)
    done = sum(1 for r in rows if r[2])
    out = [f"# Hikrobot VisionMaster guide: coverage\n",
           f"Every vision tool described in the VisionMaster user guide, and the Apex Vision module that covers it. "
           f"**{done} of {total}** are covered.\n",
           "This page is generated by `python scripts/vm_coverage.py` from the map in that file, and a test checks that every module it "
           "names exists. A module marked *partial* covers the main behaviour of the guide's tool but not every option.\n"]
    for chapter in GUIDE:
        items = [r for r in rows if r[0] == chapter]
        n = sum(1 for r in items if r[2])
        out.append(f"\n## {chapter} ({n} of {len(items)})\n\n| Guide tool | Apex Vision module | Note |\n|---|---|---|")
        for _c, guide, ours, note in items:
            out.append(f"| {guide} | {ours if ours else 'not yet'} | {note} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    rows, bad = build()
    path = os.path.join(ROOT, "docs", "VM_COVERAGE.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render())
    done = sum(1 for r in rows if r[2])
    print(f"{done} of {len(rows)} guide tools covered; wrote {path}")
    for g, o in bad:
        print("MAP ERROR:", g, "->", o)
    for chapter in GUIDE:
        items = [r for r in rows if r[0] == chapter]
        print(f"  {chapter:26s} {sum(1 for r in items if r[2]):2d}/{len(items)}")
