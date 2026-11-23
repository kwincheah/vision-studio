#pragma once

#include <cstdint>
#include <mutex>
#include <vector>

namespace apex_core {

struct FrameSlot {
    std::vector<uint8_t> data;
    int height = 0;
    int width = 0;
    int channels = 0;
    uint64_t frame_id = 0;
    double timestamp_s = 0.0;
    bool valid = false;
};

struct RingBufferStats {
    size_t capacity = 0;
    size_t count = 0;
    uint64_t total_pushed = 0;
    uint64_t dropped = 0;
};

/// Thread-safe fixed-capacity ring buffer for camera frames.
/// Pre-allocates/reuses slot vectors so continuous high-FPS acquisition avoids
/// repeated heap allocations in steady state.
class FrameRingBuffer {
public:
    explicit FrameRingBuffer(size_t capacity = 4, size_t reserve_bytes = 0);

    /// Push a raw contiguous frame into the ring buffer.
    /// Overwrites the oldest unconsumed slot if full (incrementing `dropped`).
    void push(
        const uint8_t* ptr,
        size_t nbytes,
        int height,
        int width,
        int channels,
        uint64_t frame_id,
        double timestamp_s
    );

    /// Copy out the newest frame (returns false if empty).
    bool copy_latest(FrameSlot& out) const;

    /// Pop the oldest unconsumed frame (returns false if empty).
    bool pop_oldest(FrameSlot& out);

    void clear();
    RingBufferStats stats() const;

private:
    mutable std::mutex mutex_;
    std::vector<FrameSlot> slots_;
    size_t capacity_ = 0;
    size_t head_ = 0;   // next write index
    size_t count_ = 0;  // unread items
    size_t latest_idx_ = 0;
    bool has_latest_ = false;
    uint64_t total_pushed_ = 0;
    uint64_t dropped_ = 0;
};

}  // namespace apex_core
