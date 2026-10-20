pragma Singleton
import QtQuick 2.15

/*
 * Design-time sample data, so every screen renders in Qt Design Studio without the
 * Python backend.  When the app runs live (python qml_main.py) the backend replaces it.
 */
QtObject {
    readonly property string solutionName: "PCB_Inspection_Demo"
    readonly property var projects: [
        { name: "PCB_Inspection_Demo", path: "C:/Users/you/Downloads/VMClone/projects/PCB_Inspection_Demo.vmp", when: "2026-10-15 07:12" },
        { name: "Precision_Measurement_Demo", path: "C:/Users/you/Downloads/VMClone/projects/Precision_Measurement_Demo.vmp", when: "2026-10-15 06:43" },
        { name: "YOLO_ObjectDetection_Demo", path: "C:/Users/you/Downloads/VMClone/projects/YOLO_ObjectDetection_Demo.vmp", when: "2026-10-15 05:33" }
    ]

    readonly property var nodes: [
        { id: "src", title: "01 ImageAcquisition", status: "PASS", ms: 2.6, x: 50, y: 50,
          inputs: [], outputs: [ {name: "Image", type: "image"}, {name: "Width", type: "value"}, {name: "Height", type: "value"} ] },
        { id: "tpl", title: "02 IC Alignment", status: "PASS", ms: 136.9, x: 310, y: 50,
          inputs: [ {name: "Image", type: "image"} ],
          outputs: [ {name: "Image", type: "image"}, {name: "Score", type: "value"}, {name: "Center_X", type: "value"}, {name: "Center_Y", type: "value"}, {name: "Angle", type: "value"}, {name: "Box", type: "region"} ] },
        { id: "hole", title: "03 MountingHole", status: "PASS", ms: 1.8, x: 310, y: 215,
          inputs: [ {name: "Image", type: "image"} ],
          outputs: [ {name: "Image", type: "image"}, {name: "Center_X", type: "value"}, {name: "Center_Y", type: "value"}, {name: "Radius", type: "value"} ] },
        { id: "cal", title: "04 TraceWidthCaliper", status: "PASS", ms: 0.2, x: 310, y: 360,
          inputs: [ {name: "Image", type: "image"} ],
          outputs: [ {name: "Distance", type: "value"}, {name: "Edge1", type: "value"}, {name: "Edge2", type: "value"} ] },
        { id: "def", title: "05 SurfaceScratchCheck", status: "FAIL", ms: 0.6, x: 310, y: 490,
          inputs: [ {name: "Image", type: "image"} ],
          outputs: [ {name: "Image", type: "image"}, {name: "Defect_Count", type: "value"}, {name: "Boxes", type: "region"} ] },
        { id: "jdg", title: "06 QualityJudge", status: "FAIL", ms: 0.0, x: 590, y: 520,
          inputs: [ {name: "Val_In", type: "value"} ],
          outputs: [ {name: "Branch_Result", type: "value"}, {name: "Status", type: "string"} ] },
        { id: "plc", title: "07 SendToPLC", status: "PASS", ms: 0.0, x: 590, y: 380,
          inputs: [ {name: "Data", type: "string"}, {name: "Trigger", type: "value"} ],
          outputs: [ {name: "Sent_Bytes", type: "value"} ] }
    ]
    readonly property var connections: [
        { from: "src", fromPort: 0, to: "tpl", toPort: 0 },
        { from: "src", fromPort: 0, to: "hole", toPort: 0 },
        { from: "src", fromPort: 0, to: "cal", toPort: 0 },
        { from: "src", fromPort: 0, to: "def", toPort: 0 },
        { from: "def", fromPort: 1, to: "jdg", toPort: 0 },
        { from: "jdg", fromPort: 1, to: "plc", toPort: 0 }
    ]
    readonly property var results: [
        { name: "Width", value: "800" },
        { name: "Height", value: "600" }
    ]
    readonly property var imagePool: [
        { name: "pcb_sample.png", url: "../images/sample_pcb.png" },
        { name: "pcb_sample_defect.png", url: "../images/sample_pcb.png" }
    ]
    readonly property var scopes: ["Run all", "Run selected", "Single step"]

    // ---- tool box ----------------------------------------------------------------------
    readonly property var toolCategories: [
        { name: "Acquisition", icon: "camera", tools: ["Image Source", "Image Output", "Image Buffer", "PCB Board Layout"] },
        { name: "Location", icon: "target", tools: ["Template Match", "Position Correction", "Circle Search", "Line Search", "Caliper", "Edge Search", "BLOB Analysis"] },
        { name: "Measurement", icon: "measure", tools: ["L2L Measure", "P2P Measure", "Intensity Measure", "Pixel Count", "Edge Distance", "Histogram"] },
        { name: "Image Generation", icon: "roi", tools: ["Circle/Line Fit", "Geometry Generation"] },
        { name: "Image Processing", icon: "grid", tools: ["Image Binarization", "Image Filter", "Image Morphology"] },
        { name: "Recognition", icon: "text", tools: ["2D BCR Recognition", "BCR Recognition", "OCR Recognition", "Object Detection", "PCB Defect Detection"] },
        { name: "Defect Detection", icon: "shield", tools: ["Defect Detection", "Linear Edge Defect"] },
        { name: "Color Processing", icon: "palette", tools: ["Color Extraction", "Color Measurement"] },
        { name: "Calibration", icon: "grid", tools: ["N-Point Calibration", "Lens Distortion Calibration"] },
        { name: "Communication", icon: "comm", tools: ["TCP Send", "Camera IO"] },
        { name: "Logic Tools", icon: "logic", tools: ["Condition Branch", "Variable Calculation", "Branch", "If Module", "Branch String", "Trigger", "Script"] }
    ]

    // ---- menu bar ----------------------------------------------------------------------
    readonly property var menus: [
        { title: "File", items: [
            { text: "Start Page...", key: "startPage", shortcut: "Ctrl+H" }, { sep: true },
            { text: "New Solution...", key: "newSolution", shortcut: "Ctrl+N" },
            { text: "Open Solution...", key: "openSolution", shortcut: "Ctrl+O" },
            { text: "Save Solution", key: "save", shortcut: "Ctrl+S" },
            { text: "Save Solution As...", key: "saveAs", shortcut: "Ctrl+Shift+S" }, { sep: true },
            { text: "Load Image File...", key: "loadImage", shortcut: "Ctrl+I" },
            { text: "Load Image Folder...", key: "loadFolder" }, { sep: true },
            { text: "Load Example Solution", sub: [
                { text: "PCB Inspection & Defect Analysis", key: "example0" },
                { text: "Precision Dimensional Measurement", key: "example1" },
                { text: "Deep Learning Object Detection (YOLOv11)", key: "example2" },
                { text: "Color Extraction & Robot Calibration", key: "example3" } ] },
            { text: "Export Results to CSV...", key: "exportCsv" },
            { text: "Export Flow as XML...", key: "exportXml" },
            { text: "Import Flow from XML...", key: "importXml" }, { sep: true },
            { text: "Exit", key: "exit", shortcut: "Alt+F4" } ] },
        { title: "Settings", items: [
            { text: "Global Variables...", key: "globalVars" },
            { text: "Hardware Trigger Settings", key: "hwTrigger" },
            { text: "Communication Configuration", key: "comm" } ] },
        { title: "Tools", items: [
            { text: "AI Gen - Build a Flow from a Description...", key: "aiGen", shortcut: "Ctrl+G" }, { sep: true },
            { text: "Camera Lens Distortion Calibration Wizard...", key: "lensCal" },
            { text: "N-Point Spatial Calibration Wizard", key: "npoint" },
            { text: "Calibration Target Generator...", key: "targetGen" },
            { text: "Module Generator...", key: "pluginCreate" },
            { text: "Plugin Manager...", key: "plugins" },
            { text: "Plugin Marketplace...", key: "pluginMarket" },
            { text: "Create Vision Plugin...", key: "pluginCreate" }, { sep: true },
            { text: "Validate Active Flow", key: "validate" },
            { text: "Arrange Modules Hierarchically", key: "arrange" } ] },
        { title: "System", items: [
            { text: "Camera Set", key: "cameraSet" },
            { text: "Controller Management", key: "controller" },
            { text: "Log Viewer", key: "logViewer" }, { sep: true },
            { text: "Performance Options", key: "performance" } ] },
        { title: "Inspection", items: [
            { text: "Dataset Evaluation...", key: "inspect0" },
            { text: "Evaluation Results", key: "inspect1" },
            { text: "Failure Analysis...", key: "inspect2" },
            { text: "Experiments...", key: "inspect3" },
            { text: "Compare Experiments...", key: "inspect4" }, { sep: true },
            { text: "Generate PCB Defect Dataset...", key: "genDataset" },
            { text: "Explainability (Grad-CAM)...", key: "gradcam" }, { sep: true },
            { text: "Open Experiment Folder", key: "openExperiments" } ] },
        { title: "View", items: [
            { text: "Flow Diagram", key: "viewFlow", shortcut: "Ctrl+1" },
            { text: "Operation Interface", key: "viewOperation", shortcut: "Ctrl+2" },
            { text: "Multi-Flow Overview", key: "viewMulti", shortcut: "Ctrl+3" }, { sep: true },
            { text: "Fit Modules to View", key: "fit", shortcut: "Ctrl+0" },
            { text: "Auto-Arrange Modules", key: "arrange" }, { sep: true },
            { text: "Show Canvas Alignment Grid", key: "toggleGrid", checked: true } ] },
        { title: "Help", items: [
            { text: "User Manual", key: "manual", shortcut: "F1" },
            { text: "Keyboard Shortcuts", key: "shortcuts" },
            { text: "Language / 语言", key: "language" }, { sep: true },
            { text: "Version Information", key: "version" },
            { text: "About Apex Industrial Vision Studio", key: "about" } ] }
    ]

    readonly property var aiProviders: [
        { id: "anthropic", label: "Anthropic (Claude)", needsKey: true, baseUrl: "https://api.anthropic.com", editableUrl: false, keyPlaceholder: "sk-ant-...", keyUrl: "https://console.anthropic.com/settings/keys",
          models: [ { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5 (balanced)" } ] },
        { id: "openai", label: "OpenAI", needsKey: true, baseUrl: "https://api.openai.com/v1", editableUrl: true, keyPlaceholder: "sk-...", keyUrl: "https://platform.openai.com/api-keys",
          models: [ { id: "gpt-4.1", label: "GPT-4.1" } ] }
    ]
    readonly property var aiMessages: [
        { role: "user", text: "Measure the width between two edges and pass if it is 20 to 60 px", tools: [], flowIndex: -1, error: "" },
        { role: "assistant", text: "I used a Caliper in edge-pair mode and a Condition Branch for the tolerance. Adjust the caliper line to sit across the feature.",
          tools: [ { summary: "Searched the reference for 'measure width'", ok: true }, { summary: "Validated the flow: no errors", ok: true } ],
          flowIndex: 0, error: "",
          flow: { summary: "Width check with tolerance.", modules: 3, links: 2, names: ["Image Source", "Caliper", "Condition Branch"],
                  warnings: [], sideEffects: [], applied: false } }
    ]

    // ---- dialogs -----------------------------------------------------------------------
    readonly property var globalVariables: [
        { name: "g_CountOK", type: "int", value: "0" },
        { name: "g_CountNG", type: "int", value: "0" },
        { name: "g_LotNumber", type: "str", value: "LOT-2026-A1" },
        { name: "g_TriggerEnable", type: "bool", value: "True" }
    ]
    readonly property var flowSettings: ({ runIntervalMs: 50, timeoutMs: 5000, stopOnNg: false, enabled: true })
    readonly property var validationIssues: [
        { severity: "warning", node: "04 TraceWidthCaliper", message: "Output 'Distance' is not connected to any module." },
        { severity: "info", node: "Flow", message: "7 modules, 6 connections, no cycles." }
    ]
    readonly property var moduleInputs: [ { name: "Image", type: "Image", source: "01_ImageAcquisition [Image]" } ]
    readonly property var moduleParams: [
        { name: "template_roi", label: "Template ROI", kind: "rect", type: "list", native: [300, 250, 200, 100], value: "[300, 250, 200, 100]" },
        { name: "min_score", label: "Min score", kind: "float", type: "float", native: 0.65, value: "0.65", min: 0, max: 1, step: 0.05, decimals: 2 },
        { name: "polarity", label: "Polarity", kind: "enum", type: "str", native: "Any", value: "Any", choices: ["Any", "Dark to light", "Light to dark"] },
        { name: "use_pyramid", label: "Use pyramid", kind: "bool", type: "bool", native: true, value: "true" }
    ]
    readonly property var cameras: [
        { name: "Hikrobot MV-CA013-GigE", type: "Hikrobot MVS GigE", serial: "DA12345678", iface: "Hikrobot MVS" },
        { name: "Hikrobot MV-CA016-USB3", type: "Hikrobot MVS USB3", serial: "UC98765432", iface: "Hikrobot MVS" },
        { name: "Industrial GigE Camera", type: "Industrial GigE", serial: "DA12345678", iface: "GigE Vision" },
        { name: "Basler dart daA1280", type: "Industrial USB3", serial: "21894561", iface: "USB3 Vision" },
        { name: "Standard USB Webcam", type: "USB/Webcam", serial: "USB-VID-CAM0", iface: "USB Video Class" },
        { name: "IP / RTSP Stream", type: "IP/RTSP Stream", serial: "NET-RTSP-01", iface: "Ethernet RTSP" }
    ]
    readonly property var plugins: [
        { name: "Adaptive Blur Filter", version: "1.0.0", category: "Custom Filters", status: "Loaded" }
    ]
    readonly property var marketplace: [
        { name: "Surface Roughness Analyzer", author: "community", version: "0.9.2", status: "Available" },
        { name: "Weld Seam Tracker", author: "community", version: "1.3.0", status: "Available" },
        { name: "Label Verifier", author: "community", version: "2.0.1", status: "Installed" }
    ]
    readonly property var calibrationViews: [
        { name: "Synthetic View 1 (+5 deg)", ok: true, corners: 54 },
        { name: "Synthetic View 2 (-8 deg)", ok: true, corners: 54 },
        { name: "Synthetic View 3 (+12 deg)", ok: false, corners: 0 }
    ]
    readonly property var failures: [
        { image: "board_014.png", cls: "scratch", reason: "missed", score: "0.00" },
        { image: "board_021.png", cls: "open", reason: "false positive", score: "0.71" },
        { image: "board_033.png", cls: "short", reason: "localisation", score: "0.48" }
    ]
    readonly property var experiments: [
        { name: "baseline-reference", when: "2026-10-14 16:20", map: "0.812", f1: "0.874" },
        { name: "conservative-op", when: "2026-10-15 09:02", map: "0.790", f1: "0.861" }
    ]
}
