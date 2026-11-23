#include "ring_buffer.hpp"

#include <algorithm>
#include <cstring>
#include <stdexcept>

namespace apex_core {

FrameRingBuffer::FrameRingBuffer(size_t capacity, size_t reserve_bytes)
    : slots_(std::max<size_t>(1, capacity)), capacity_(std::max<size_t>(1, capacity)) {
    if (reserve_bytes > 0) {
        for (auto& slot : slots_) {
            slot.data.reserve(reserve_bytes);
        }
    }
}

void FrameRingBuffer::push(
    const uint8_t* ptr,
    size_t nbytes,
    int height,
    int width,
    int channels,
    uint64_t frame_id,
    double timestamp_s
) {
    if (ptr == nullptr && nbytes > 0) {
        throw std::invalid_argument("Null frame pointer with non-zero byte count");
    }

    std::lock_guard<std::mutex> lock(mutex_);
    FrameSlot& slot = slots_[head_];
    slot.data.resize(nbytes);
    if (nbytes > 0) {
        std::memcpy(slot.data.data(), ptr, nbytes);
    }
    slot.height = height;
    slot.width = width;
    slot.channels = channels;
    slot.frame_id = frame_id;
    slot.timestamp_s = timestamp_s;
    slot.valid = true;

    latest_idx_ = head_;
    has_latest_ = true;
    head_ = (head_ + 1) % capacity_;
    total_pushed_ += 1;

    if (count_ == capacity_) {
        dropped_ += 1;
    } else {
        count_ += 1;
    }
}

bool FrameRingBuffer::copy_latest(FrameSlot& out) const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!has_latest_ || !slots_[latest_idx_].valid) {
        return false;
    }
    out = slots_[latest_idx_];
    return true;
}

bool FrameRingBuffer::pop_oldest(FrameSlot& out) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (count_ == 0) {
        return false;
    }
    size_t tail = (head_ + capacity_ - count_) % capacity_;
    out = slots_[tail];
    slots_[tail].valid = false;
    count_ -= 1;
    return out.valid;
}

void FrameRingBuffer::clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& slot : slots_) {
        slot.valid = false;
    }
    head_ = 0;
    count_ = 0;
    latest_idx_ = 0;
    has_latest_ = false;
}

RingBufferStats FrameRingBuffer::stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return RingBufferStats{capacity_, count_, total_pushed_, dropped_};
}

}  // namespace apex_core
