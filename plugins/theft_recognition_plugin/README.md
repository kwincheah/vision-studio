# Modular Vision Tracking & VLM Suite (`v3.0.0`)

Loosely coupled plugin tools designed to compose with Apex Vision's built-in **Script**, **Object Detection**, **Condition Branch**, **Data Log**, and **Image Output** modules:

1. **ROI Zone Manager** (`roi_zone_tool.py`)
   - Add, rename, draw, and delete multiple named ROIs directly on the viewport.
   - Each ROI name automatically becomes its own `REGION` output port (`[x, y, w, h]`) plus a `Named_ROIs` dict output. Removing or renaming an ROI auto-disconnects stale links.
2. **YOLO Pose** (`pose_detector_tool.py`)
   - Stateless per-frame YOLOv11-Pose estimator outputting `Detections` and 17 COCO `Keypoints`.
3. **BoT-SORT Tracker** (`botsort_tool.py`)
   - Pure Ultralytics `BOTSORT` / `BYTETracker` module operating on any upstream `Detections` (+ optional `Keypoints`), outputting persistent `Tracks` and trails.
4. **VLM** (`vlm_module_tool.py`)
   - Generic OpenAI-compatible / Anthropic Vision-Language Model caller focused solely on provider/model/API config, taking `Image`, `Prompt`, `System_Prompt`, and `Trigger`, and outputting `Response_Text`, `Response_JSON`, and `Has_Response`.
