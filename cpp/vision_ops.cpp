#include "vision_ops.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>

namespace apex_core {

namespace {

inline float box_iou_xywh(const float* a, const float* b) {
    const float ax1 = a[0], ay1 = a[1], ax2 = a[0] + a[2], ay2 = a[1] + a[3];
    const float bx1 = b[0], by1 = b[1], bx2 = b[0] + b[2], by2 = b[1] + b[3];

    const float ix1 = std::max(ax1, bx1);
    const float iy1 = std::max(ay1, by1);
    const float ix2 = std::min(ax2, bx2);
    const float iy2 = std::min(ay2, by2);

    const float iw = std::max(0.0f, ix2 - ix1);
    const float ih = std::max(0.0f, iy2 - iy1);
    const float inter = iw * ih;
    if (inter <= 0.0f) {
        return 0.0f;
    }
    const float area_a = std::max(0.0f, a[2]) * std::max(0.0f, a[3]);
    const float area_b = std::max(0.0f, b[2]) * std::max(0.0f, b[3]);
    const float denom = area_a + area_b - inter;
    return denom > 0.0f ? (inter / denom) : 0.0f;
}

inline void map_xyxy_to_original(
    float x1,
    float y1,
    float x2,
    float y2,
    float scale_x,
    float scale_y,
    float pad_x,
    float pad_y,
    int orig_w,
    int orig_h,
    float& out_x,
    float& out_y,
    float& out_w,
    float& out_h
) {
    const float sx = (scale_x > 1e-12f) ? scale_x : 1.0f;
    const float sy = (scale_y > 1e-12f) ? scale_y : 1.0f;
    float ox1 = (x1 - pad_x) / sx;
    float ox2 = (x2 - pad_x) / sx;
    float oy1 = (y1 - pad_y) / sy;
    float oy2 = (y2 - pad_y) / sy;

    const float max_x = static_cast<float>(std::max(0, orig_w - 1));
    const float max_y = static_cast<float>(std::max(0, orig_h - 1));
    const float w_lim = static_cast<float>(std::max(1, orig_w));
    const float h_lim = static_cast<float>(std::max(1, orig_h));

    ox1 = std::clamp(ox1, 0.0f, max_x);
    oy1 = std::clamp(oy1, 0.0f, max_y);
    ox2 = std::clamp(ox2, 0.0f, w_lim);
    oy2 = std::clamp(oy2, 0.0f, h_lim);

    out_x = ox1;
    out_y = oy1;
    out_w = std::max(1.0f, ox2 - ox1);
    out_h = std::max(1.0f, oy2 - oy1);
}

}  // namespace

std::vector<int> nms_batched(
    const float* boxes_xywh,
    const float* scores,
    const int32_t* classes,
    size_t n,
    float iou_thresh,
    int max_det
) {
    std::vector<int> kept;
    if (n == 0 || boxes_xywh == nullptr || scores == nullptr || classes == nullptr || max_det <= 0) {
        return kept;
    }

    std::vector<int> order(n);
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
        return scores[a] > scores[b];
    });

    std::vector<uint8_t> suppressed(n, 0);
    kept.reserve(std::min(n, static_cast<size_t>(max_det)));

    for (size_t idx_i = 0; idx_i < n; ++idx_i) {
        const int i = order[idx_i];
        if (suppressed[i]) {
            continue;
        }
        kept.push_back(i);
        if (static_cast<int>(kept.size()) >= max_det) {
            break;
        }
        const float* box_i = boxes_xywh + static_cast<size_t>(i) * 4;
        const int32_t cls_i = classes[i];
        for (size_t idx_j = idx_i + 1; idx_j < n; ++idx_j) {
            const int j = order[idx_j];
            if (suppressed[j] || classes[j] != cls_i) {
                continue;
            }
            const float* box_j = boxes_xywh + static_cast<size_t>(j) * 4;
            if (box_iou_xywh(box_i, box_j) > iou_thresh) {
                suppressed[j] = 1;
            }
        }
    }
    return kept;
}

std::vector<DetectionBox> decode_yolo_matrix(
    const float* out,
    size_t rows,
    size_t cols,
    float conf_thresh,
    float iou_thresh,
    int max_det,
    int num_classes,
    float scale_x,
    float scale_y,
    float pad_x,
    float pad_y,
    int orig_w,
    int orig_h
) {
    std::vector<DetectionBox> result;
    if (out == nullptr || rows == 0 || cols == 0 || max_det <= 0) {
        return result;
    }

    // End-to-end YOLO format: (N, 6) = [x1, y1, x2, y2, score, class_id]
    if (cols == 6 && rows <= 1000) {
        std::vector<DetectionBox> filtered;
        for (size_t r = 0; r < rows; ++r) {
            const float* row = out + r * 6;
            const float sc = row[4];
            if (sc >= conf_thresh) {
                DetectionBox d;
                map_xyxy_to_original(row[0], row[1], row[2], row[3],
                                     scale_x, scale_y, pad_x, pad_y, orig_w, orig_h,
                                     d.x, d.y, d.w, d.h);
                d.score = sc;
                d.class_id = static_cast<int>(row[5]);
                filtered.push_back(d);
            }
        }
        std::stable_sort(filtered.begin(), filtered.end(), [](const DetectionBox& a, const DetectionBox& b) {
            return a.score > b.score;
        });
        if (static_cast<int>(filtered.size()) > max_det) {
            filtered.resize(static_cast<size_t>(max_det));
        }
        return filtered;
    }

    // Layout check: short axis is channels (4 + C or 5 + C)
    const bool transposed = (rows < cols);
    const size_t n = transposed ? cols : rows;
    const size_t c = transposed ? rows : cols;
    if (c < 5) {
        return result;
    }

    const bool has_obj = (num_classes > 0 && static_cast<size_t>(5 + num_classes) == c);
    const size_t cls_start = has_obj ? 5 : 4;

    auto at = [&](size_t det_idx, size_t ch_idx) -> float {
        return transposed ? out[ch_idx * cols + det_idx] : out[det_idx * cols + ch_idx];
    };

    std::vector<float> boxes_xywh;
    std::vector<float> scores;
    std::vector<int32_t> classes;

    for (size_t i = 0; i < n; ++i) {
        const float obj = has_obj ? at(i, 4) : 1.0f;
        float best_score = -std::numeric_limits<float>::infinity();
        int best_cls = 0;
        for (size_t ch = cls_start; ch < c; ++ch) {
            float sc = at(i, ch) * obj;
            if (sc > best_score) {
                best_score = sc;
                best_cls = static_cast<int>(ch - cls_start);
            }
        }
        if (best_score < conf_thresh) {
            continue;
        }
        const float cx = at(i, 0);
        const float cy = at(i, 1);
        const float bw = at(i, 2);
        const float bh = at(i, 3);
        float ox, oy, ow, oh;
        map_xyxy_to_original(cx - bw * 0.5f, cy - bh * 0.5f, cx + bw * 0.5f, cy + bh * 0.5f,
                             scale_x, scale_y, pad_x, pad_y, orig_w, orig_h,
                             ox, oy, ow, oh);
        boxes_xywh.push_back(ox);
        boxes_xywh.push_back(oy);
        boxes_xywh.push_back(ow);
        boxes_xywh.push_back(oh);
        scores.push_back(best_score);
        classes.push_back(best_cls);
    }

    if (scores.empty()) {
        return result;
    }

    const std::vector<int> keep = nms_batched(
        boxes_xywh.data(), scores.data(), classes.data(), scores.size(), iou_thresh, max_det
    );
    result.reserve(keep.size());
    for (int idx : keep) {
        const size_t base = static_cast<size_t>(idx) * 4;
        result.push_back(DetectionBox{
            boxes_xywh[base], boxes_xywh[base + 1], boxes_xywh[base + 2], boxes_xywh[base + 3],
            scores[idx], classes[idx]
        });
    }
    return result;
}

OpticalStats compute_optical_stats(
    const uint8_t* img_ptr,
    int height,
    int width,
    int channels,
    size_t row_stride_bytes
) {
    OpticalStats stats;
    if (img_ptr == nullptr || height <= 0 || width <= 0 || channels <= 0) {
        stats.min_val = 0;
        return stats;
    }

    const size_t total_pixels = static_cast<size_t>(height) * static_cast<size_t>(width);
    std::vector<uint8_t> gray(total_pixels);

    uint64_t sum = 0;
    uint64_t saturated = 0;
    uint64_t dark = 0;
    uint8_t min_v = 255;
    uint8_t max_v = 0;

    for (int y = 0; y < height; ++y) {
        const uint8_t* row = img_ptr + static_cast<size_t>(y) * row_stride_bytes;
        uint8_t* g_row = gray.data() + static_cast<size_t>(y) * static_cast<size_t>(width);
        if (channels == 1) {
            for (int x = 0; x < width; ++x) {
                uint8_t v = row[x];
                g_row[x] = v;
                sum += v;
                if (v < min_v) min_v = v;
                if (v > max_v) max_v = v;
                if (v >= 250) saturated += 1;
                if (v <= 10) dark += 1;
            }
        } else {
            // BGR luminance approximation (integers, matches OpenCV BT.601 weights)
            for (int x = 0; x < width; ++x) {
                const uint8_t* px = row + static_cast<size_t>(x) * static_cast<size_t>(channels);
                uint32_t lum = (29u * px[0] + 150u * px[1] + 77u * px[2] + 128u) >> 8;
                uint8_t v = static_cast<uint8_t>(std::min<uint32_t>(255u, lum));
                g_row[x] = v;
                sum += v;
                if (v < min_v) min_v = v;
                if (v > max_v) max_v = v;
                if (v >= 250) saturated += 1;
                if (v <= 10) dark += 1;
            }
        }
    }

    stats.mean_brightness = static_cast<double>(sum) / static_cast<double>(total_pixels);
    stats.min_val = min_v;
    stats.max_val = max_v;
    stats.saturated_ratio = static_cast<double>(saturated) / static_cast<double>(total_pixels);
    stats.dark_ratio = static_cast<double>(dark) / static_cast<double>(total_pixels);

    // 4-neighbor Laplacian variance (focus / sharpness metric)
    if (height >= 3 && width >= 3) {
        const size_t lap_count = static_cast<size_t>(height - 2) * static_cast<size_t>(width - 2);
        double lap_sum = 0.0;
        double lap_sq_sum = 0.0;
        for (int y = 1; y < height - 1; ++y) {
            const uint8_t* up = gray.data() + static_cast<size_t>(y - 1) * width;
            const uint8_t* cur = gray.data() + static_cast<size_t>(y) * width;
            const uint8_t* dn = gray.data() + static_cast<size_t>(y + 1) * width;
            for (int x = 1; x < width - 1; ++x) {
                int lap = static_cast<int>(up[x]) + static_cast<int>(dn[x]) +
                          static_cast<int>(cur[x - 1]) + static_cast<int>(cur[x + 1]) -
                          4 * static_cast<int>(cur[x]);
                double d = static_cast<double>(lap);
                lap_sum += d;
                lap_sq_sum += d * d;
            }
        }
        double mean_lap = lap_sum / static_cast<double>(lap_count);
        double var = (lap_sq_sum / static_cast<double>(lap_count)) - (mean_lap * mean_lap);
        stats.laplacian_variance = std::max(0.0, var);
    }

    return stats;
}

std::array<int, 4> compute_union_box(const std::vector<std::array<int, 4>>& boxes) {
    if (boxes.empty()) {
        return {0, 0, 0, 0};
    }
    int min_x = std::numeric_limits<int>::max();
    int min_y = std::numeric_limits<int>::max();
    int max_x = std::numeric_limits<int>::min();
    int max_y = std::numeric_limits<int>::min();
    for (const auto& b : boxes) {
        min_x = std::min(min_x, b[0]);
        min_y = std::min(min_y, b[1]);
        max_x = std::max(max_x, b[0] + b[2]);
        max_y = std::max(max_y, b[1] + b[3]);
    }
    return {min_x, min_y, std::max(0, max_x - min_x), std::max(0, max_y - min_y)};
}

}  // namespace apex_core
