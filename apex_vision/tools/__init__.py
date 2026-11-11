"""
Aggregates and registers all Apex Vision tools across all industrial categories.
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
from apex_vision.tools.deep_learning import DLClassifyTool, DLSegmentTool, DLAnomalyTool
from apex_vision.tools import vm_image, vm_boxes, vm_color, vm_location, vm_lines, vm_location2, vm_measure, vm_calib, vm_calc, vm_logic, vm_defect, vm_defect2, vm_acquire, vm_recog, vm_dl2, vm_group  # noqa: F401  (modules from the VisionMaster guide)
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

from apex_vision.tools.image_processing_ext import (
    ImageCropTool, ImageTransformTool, ColorConvertTool, BrightnessContrastTool,
    ImageCalculateTool, EdgeDetectionTool, FocusMeasureTool
)
from apex_vision.tools.measurement_ext import (
    P2LMeasureTool, AngleMeasureTool, LineIntersectionTool
)
from apex_vision.tools.location_ext import HoughDetectTool
from apex_vision.tools.communication_ext import (
    UDPSendTool, SerialSendTool, ModbusWriteTool, DataLogTool
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
    ScriptTool,
    # Added after the first release
    ImageCropTool, ImageTransformTool, ColorConvertTool, BrightnessContrastTool,
    ImageCalculateTool, EdgeDetectionTool, FocusMeasureTool,
    P2LMeasureTool, AngleMeasureTool, LineIntersectionTool,
    HoughDetectTool,
    UDPSendTool, SerialSendTool, ModbusWriteTool, DataLogTool,
    DLClassifyTool, DLSegmentTool, DLAnomalyTool,
]


# ---- a drawable region of interest for the modules that work on the whole picture (all zero = the whole image)
def _give_roi() -> None:
    from apex_vision.core.registry import get_tool_class
    from apex_vision.core.roi_support import add_roi
    for name in ("Image Filter", "Image Binarization", "Image Morphology", "Image Enhancement", "Brightness Contrast", "Edge Detection",
                 "Image Normalization", "Image Correction", "Shade Correction", "Color Convert", "Color Extraction",
                 "BCR Recognition", "2D BCR Recognition"):
        add_roi(get_tool_class(name))


_give_roi()


# ---- regions that used to start as a box fitted to the test picture now start as the whole image
def _whole_image_defaults() -> None:
    from apex_vision.core.registry import get_tool_class
    from apex_vision.core.roi_support import WHOLE_IMAGE_DEFAULTS, start_with_whole_image
    for name, keys in WHOLE_IMAGE_DEFAULTS.items():
        start_with_whole_image(get_tool_class(name), keys)


_whole_image_defaults()
