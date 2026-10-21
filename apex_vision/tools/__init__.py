"""
Aggregates and registers all Vision Master tools across all industrial categories.
"""
from apex_vision.tools.acquisition import ImageSourceTool
from apex_vision.tools.image_output import ImageOutputTool, ImageBufferTool
from apex_vision.tools.location import (
    TemplateMatchTool,
    PositionCorrectionTool,
    CircleSearchTool,
    LineSearchTool,
    BlobAnalysisTool,
    CaliperTool,
    EdgeSearchTool
)
from apex_vision.tools.measurement import (
    L2LMeasureTool,
    P2PMeasureTool,
    IntensityMeasureTool,
    PixelCountTool,
    EdgeDistanceTool,
    HistogramTool
)
from apex_vision.tools.image_generation import (
    GeometryFitTool,
    GeometryGenerationTool
)
from apex_vision.tools.image_processing import (
    ImageBinarizationTool,
    ImageFilterTool,
    ImageMorphologyTool
)
from apex_vision.tools.recognition import (
    CodeRecognitionTool,
    Barcode1DTool,
    OCRRecognitionTool,
    DefectDetectionTool,
    LinearEdgeDefectTool
)
from apex_vision.tools.object_detection import ObjectDetectionTool
from apex_vision.tools.color_processing import (
    ColorExtractionTool,
    ColorMeasurementTool
)
# PCB-specific inspection node.  Defined under `samples` because it is paired with the
# synthetic dataset generator and the reference detector it wraps; importing it here is
# what registers it on the toolbox like any other node.
from apex_vision.samples.pcb_defect_tool import (
    PCBBoardLayoutTool, PCBDefectDetectionTool,
)
from apex_vision.tools.calibration import (
    NPointCalibrationTool
)
from apex_vision.tools.communication import (
    TCPSendTool,
    CameraIOTool
)
from apex_vision.tools.logic import (
    ConditionBranchTool,
    VariableCalculationTool,
    BranchTool,
    IfModuleTool,
    BranchStringTool,
    TriggerTool
)
from apex_vision.tools.script_tool import (
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
