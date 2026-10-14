"""
Aggregates and registers all Vision Master tools across all industrial categories.
"""
from vm_clone.tools.acquisition import ImageSourceTool
from vm_clone.tools.image_output import ImageOutputTool, ImageBufferTool
from vm_clone.tools.location import (
    TemplateMatchTool,
    PositionCorrectionTool,
    CircleSearchTool,
    LineSearchTool,
    BlobAnalysisTool,
    CaliperTool,
    EdgeSearchTool
)
from vm_clone.tools.measurement import (
    L2LMeasureTool,
    P2PMeasureTool,
    IntensityMeasureTool,
    PixelCountTool,
    EdgeDistanceTool,
    HistogramTool
)
from vm_clone.tools.image_generation import (
    GeometryFitTool,
    GeometryGenerationTool
)
from vm_clone.tools.image_processing import (
    ImageBinarizationTool,
    ImageFilterTool,
    ImageMorphologyTool
)
from vm_clone.tools.recognition import (
    CodeRecognitionTool,
    Barcode1DTool,
    OCRRecognitionTool,
    DefectDetectionTool,
    LinearEdgeDefectTool
)
from vm_clone.tools.object_detection import ObjectDetectionTool
from vm_clone.tools.color_processing import (
    ColorExtractionTool,
    ColorMeasurementTool
)
# PCB-specific inspection node.  Defined under `samples` because it is paired with the
# synthetic dataset generator and the reference detector it wraps; importing it here is
# what registers it on the toolbox like any other node.
from vm_clone.samples.pcb_defect_tool import (
    PCBBoardLayoutTool, PCBDefectDetectionTool,
)
from vm_clone.tools.calibration import (
    NPointCalibrationTool
)
from vm_clone.tools.communication import (
    TCPSendTool,
    CameraIOTool
)
from vm_clone.tools.logic import (
    ConditionBranchTool,
    VariableCalculationTool,
    BranchTool,
    IfModuleTool,
    BranchStringTool,
    TriggerTool
)
from vm_clone.tools.script_tool import (
    ScriptTool
)

ALL_TOOLS = [
    # Acquisition
    ImageSourceTool,
    ImageOutputTool,
    ImageBufferTool,
    # Location
    TemplateMatchTool,
    PositionCorrectionTool,
    CircleSearchTool,
    LineSearchTool,
    BlobAnalysisTool,
    CaliperTool,
    EdgeSearchTool,
    # Measurement
    L2LMeasureTool,
    P2PMeasureTool,
    IntensityMeasureTool,
    PixelCountTool,
    EdgeDistanceTool,
    HistogramTool,
    # Image Generation
    GeometryFitTool,
    GeometryGenerationTool,
    # Image Processing
    ImageBinarizationTool,
    ImageFilterTool,
    ImageMorphologyTool,
    # Color Processing
    ColorExtractionTool,
    ColorMeasurementTool,
    # Recognition
    CodeRecognitionTool,
    Barcode1DTool,
    OCRRecognitionTool,
    ObjectDetectionTool,
    # Defect Detection
    DefectDetectionTool,
    LinearEdgeDefectTool,
    PCBBoardLayoutTool,
    PCBDefectDetectionTool,
    # Calibration
    NPointCalibrationTool,
    # Communication
    TCPSendTool,
    CameraIOTool,
    # Logic Tools
    ConditionBranchTool,
    VariableCalculationTool,
    BranchTool,
    IfModuleTool,
    BranchStringTool,
    TriggerTool,
    ScriptTool
]
