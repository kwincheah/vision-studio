#pragma once

#include <array>
#include <cstdint>
#include <vector>

namespace apex_core {

struct DetectionBox {
    float x = 0.0f;
    float y = 0.0f;
    float w = 0.0f;
    float h = 0.0f;
    float score = 0.0f;
    int class_id = 0;
};

struct OpticalStats {
    double mean_brightness = 0.0;
    uint8_t min_val = 255;
    uint8_t max_val = 0;
    double saturated_ratio = 0.0;
    double dark_ratio = 0.0;
    double laplacian_variance = 0.0;
};

/// Class-aware Non-Maximum Suppression over `n` boxes in `[x, y, w, h]` format.
/// Returns indices kept, sorted by descending score, truncated to `max_det`.
std::vector<int> nms_batched(
    const float* boxes_xywh,
    const float* scores,
    const int32_t* classes,
    size_t n,
    float iou_thresh,
    int max_det
);

/// Decode a contiguous float32 YOLO detection matrix of shape (rows, cols)
/// into un-letterboxed detections in original image coordinates.
std::vector<DetectionBox> decode_yolo_matrix(
    const float* out,
    size_t rows,
    size_t cols,
    float conf_thresh,
    float iou_thresh,
    int max_det,
    int num_classes,  // <= 0 means unknown/auto (v8/v11 style)
    float scale_x,
    float scale_y,
    float pad_x,
    float pad_y,
    int orig_w,
    int orig_h
);

/// Compute optical quality diagnostics (brightness, saturation, dark ratio, Laplacian blur variance)
/// on an 8-bit grayscale or BGR/RGB/BGRA image in a single pass.
OpticalStats compute_optical_stats(
    const uint8_t* img_ptr,
    int height,
    int width,
    int channels,
    size_t row_stride_bytes
);

/// Compute enclosing bounding box [x, y, w, h] over a non-empty list of [x, y, w, h] boxes.
std::array<int, 4> compute_union_box(const std::vector<std::array<int, 4>>& boxes);

}  // namespace apex_core
