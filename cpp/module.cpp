#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstring>
#include <stdexcept>
#include <thread>

#include "dag_engine.hpp"
#include "ring_buffer.hpp"
#include "vision_ops.hpp"

namespace py = pybind11;

namespace {

py::array_t<uint8_t> slot_to_numpy(const apex_core::FrameSlot& slot) {
    if (slot.channels <= 1) {
        py::array_t<uint8_t> arr({slot.height, slot.width});
        if (!slot.data.empty()) {
            std::memcpy(arr.mutable_data(), slot.data.data(), slot.data.size());
        }
        return arr;
    }
    py::array_t<uint8_t> arr({slot.height, slot.width, slot.channels});
    if (!slot.data.empty()) {
        std::memcpy(arr.mutable_data(), slot.data.data(), slot.data.size());
    }
    return arr;
}

const char* compiler_name() {
#if defined(_MSC_VER)
    return "MSVC";
#elif defined(__clang__)
    return "Clang";
#elif defined(__GNUC__)
    return "GCC";
#else
    return "Unknown";
#endif
}

}  // namespace

PYBIND11_MODULE(_apex_core, m) {
    m.doc() = "Apex Industrial Vision Studio - Hybrid C++17 Core Engine";

    m.def("build_info", []() {
        py::dict d;
        d["version"] = "1.0.0";
        d["compiler"] = compiler_name();
        d["cpp_std"] = static_cast<long>(__cplusplus);
        d["hardware_concurrency"] = std::thread::hardware_concurrency();
        return d;
    });

    // ---- DAG scheduling & validation ----
    m.def("kahn_sort", &apex_core::kahn_sort,
          py::arg("ids"), py::arg("edges"),
          "Deterministic Kahn topological sort preserving input order on ties.");

    m.def("find_cycle_nodes", &apex_core::find_cycle_nodes,
          py::arg("ids"), py::arg("edges"),
          "Iterative 3-color DFS returning node IDs involved in cycles.");

    m.def("compute_execution_waves", &apex_core::compute_execution_waves,
          py::arg("order"), py::arg("edges"),
          "Group ordered DAG nodes into dependency-free parallel execution waves.");

    // ---- Pre-allocated thread-safe camera frame ring buffer ----
    py::class_<apex_core::FrameRingBuffer>(m, "FrameRingBuffer")
        .def(py::init<size_t, size_t>(),
             py::arg("capacity") = 4,
             py::arg("reserve_bytes") = 0)
        .def("push", [](apex_core::FrameRingBuffer& self,
                        py::array_t<uint8_t, py::array::c_style | py::array::forcecast> frame,
                        uint64_t frame_id,
                        double timestamp_s) {
            py::buffer_info info = frame.request();
            if (info.ndim != 2 && info.ndim != 3) {
                throw std::invalid_argument("Frame must be 2D (H,W) or 3D (H,W,C) uint8 array");
            }
            int h = static_cast<int>(info.shape[0]);
            int w = static_cast<int>(info.shape[1]);
            int c = (info.ndim == 3) ? static_cast<int>(info.shape[2]) : 1;
            size_t nbytes = static_cast<size_t>(info.size);
            const uint8_t* ptr = static_cast<const uint8_t*>(info.ptr);
            py::gil_scoped_release release;
            self.push(ptr, nbytes, h, w, c, frame_id, timestamp_s);
        }, py::arg("frame"), py::arg("frame_id") = 0, py::arg("timestamp_s") = 0.0)
        .def("latest", [](const apex_core::FrameRingBuffer& self) -> py::object {
            apex_core::FrameSlot slot;
            bool ok = false;
            {
                py::gil_scoped_release release;
                ok = self.copy_latest(slot);
            }
            if (!ok) {
                return py::none();
            }
            py::dict meta;
            meta["frame_id"] = slot.frame_id;
            meta["timestamp_s"] = slot.timestamp_s;
            return py::make_tuple(slot_to_numpy(slot), meta);
        })
        .def("pop", [](apex_core::FrameRingBuffer& self) -> py::object {
            apex_core::FrameSlot slot;
            bool ok = false;
            {
                py::gil_scoped_release release;
                ok = self.pop_oldest(slot);
            }
            if (!ok) {
                return py::none();
            }
            py::dict meta;
            meta["frame_id"] = slot.frame_id;
            meta["timestamp_s"] = slot.timestamp_s;
            return py::make_tuple(slot_to_numpy(slot), meta);
        })
        .def("clear", &apex_core::FrameRingBuffer::clear)
        .def("stats", [](const apex_core::FrameRingBuffer& self) {
            auto st = self.stats();
            py::dict d;
            d["capacity"] = st.capacity;
            d["count"] = st.count;
            d["total_pushed"] = st.total_pushed;
            d["dropped"] = st.dropped;
            return d;
        });

    // ---- GIL-free vision & deep learning post-processing ----
    m.def("nms_batched", [](
        py::array_t<float, py::array::c_style | py::array::forcecast> boxes_xywh,
        py::array_t<float, py::array::c_style | py::array::forcecast> scores,
        py::array_t<int32_t, py::array::c_style | py::array::forcecast> classes,
        float iou_thresh,
        int max_det
    ) {
        py::buffer_info b_info = boxes_xywh.request();
        py::buffer_info s_info = scores.request();
        py::buffer_info c_info = classes.request();

        if (b_info.ndim != 2 || b_info.shape[1] != 4) {
            throw std::invalid_argument("boxes_xywh must have shape (N, 4)");
        }
        size_t n = static_cast<size_t>(b_info.shape[0]);
        if (static_cast<size_t>(s_info.size) != n || static_cast<size_t>(c_info.size) != n) {
            throw std::invalid_argument("scores and classes lengths must match boxes count N");
        }

        const float* b_ptr = static_cast<const float*>(b_info.ptr);
        const float* s_ptr = static_cast<const float*>(s_info.ptr);
        const int32_t* c_ptr = static_cast<const int32_t*>(c_info.ptr);

        py::gil_scoped_release release;
        return apex_core::nms_batched(b_ptr, s_ptr, c_ptr, n, iou_thresh, max_det);
    }, py::arg("boxes_xywh"), py::arg("scores"), py::arg("classes"),
       py::arg("iou_thresh"), py::arg("max_det"));

    m.def("decode_yolo_matrix", [](
        py::array_t<float, py::array::c_style | py::array::forcecast> out,
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
        py::buffer_info info = out.request();
        if (info.ndim != 2) {
            throw std::invalid_argument("YOLO output matrix must be 2D (rows, cols)");
        }
        size_t rows = static_cast<size_t>(info.shape[0]);
        size_t cols = static_cast<size_t>(info.shape[1]);
        const float* ptr = static_cast<const float*>(info.ptr);

        std::vector<apex_core::DetectionBox> dets;
        {
            py::gil_scoped_release release;
            dets = apex_core::decode_yolo_matrix(
                ptr, rows, cols, conf_thresh, iou_thresh, max_det,
                num_classes, scale_x, scale_y, pad_x, pad_y, orig_w, orig_h
            );
        }

        py::list out_list(dets.size());
        for (size_t i = 0; i < dets.size(); ++i) {
            const auto& d = dets[i];
            py::list box_list(4);
            box_list[0] = static_cast<double>(d.x);
            box_list[1] = static_cast<double>(d.y);
            box_list[2] = static_cast<double>(d.w);
            box_list[3] = static_cast<double>(d.h);

            py::dict rec;
            rec["box"] = box_list;
            rec["score"] = static_cast<double>(d.score);
            rec["class_id"] = d.class_id;
            out_list[i] = rec;
        }
        return out_list;
    }, py::arg("out"), py::arg("conf_thresh"), py::arg("iou_thresh"),
       py::arg("max_det") = 100, py::arg("num_classes") = 0,
       py::arg("scale_x") = 1.0f, py::arg("scale_y") = 1.0f,
       py::arg("pad_x") = 0.0f, py::arg("pad_y") = 0.0f,
       py::arg("orig_w") = 640, py::arg("orig_h") = 640);

    m.def("compute_optical_stats", [](
        py::array_t<uint8_t, py::array::c_style | py::array::forcecast> img
    ) {
        py::buffer_info info = img.request();
        if (info.ndim != 2 && info.ndim != 3) {
            throw std::invalid_argument("Image must be 2D (H,W) or 3D (H,W,C) uint8 array");
        }
        int h = static_cast<int>(info.shape[0]);
        int w = static_cast<int>(info.shape[1]);
        int c = (info.ndim == 3) ? static_cast<int>(info.shape[2]) : 1;
        size_t stride = static_cast<size_t>(info.strides[0]);
        const uint8_t* ptr = static_cast<const uint8_t*>(info.ptr);

        apex_core::OpticalStats st;
        {
            py::gil_scoped_release release;
            st = apex_core::compute_optical_stats(ptr, h, w, c, stride);
        }

        py::dict d;
        d["mean_brightness"] = st.mean_brightness;
        d["min_val"] = st.min_val;
        d["max_val"] = st.max_val;
        d["saturated_ratio"] = st.saturated_ratio;
        d["dark_ratio"] = st.dark_ratio;
        d["laplacian_variance"] = st.laplacian_variance;
        return d;
    }, py::arg("img"));

    m.def("compute_union_box", &apex_core::compute_union_box, py::arg("boxes"));
}
