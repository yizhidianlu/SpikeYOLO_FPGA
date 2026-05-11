/*
 * sw/app/src/ringbuf.h — single-producer single-consumer lock-free ring buffer.
 *
 * Used by the capture/infer/display thread pipeline. Power-of-two depth keeps
 * the modulo a bitwise AND.
 */

#ifndef SA_APP_RINGBUF_H
#define SA_APP_RINGBUF_H

#include <atomic>
#include <cstddef>
#include <cstdint>

namespace sa_app {

template <typename T, size_t N>
class Ringbuf {
    static_assert((N & (N - 1)) == 0, "depth must be a power of two");
public:
    bool push(const T& v) {
        const size_t h = head_.load(std::memory_order_relaxed);
        const size_t next = (h + 1) & (N - 1);
        if (next == tail_.load(std::memory_order_acquire)) return false;  // full
        buf_[h] = v;
        head_.store(next, std::memory_order_release);
        return true;
    }

    bool pop(T& out) {
        const size_t t = tail_.load(std::memory_order_relaxed);
        if (t == head_.load(std::memory_order_acquire)) return false;     // empty
        out = buf_[t];
        tail_.store((t + 1) & (N - 1), std::memory_order_release);
        return true;
    }

    size_t size() const {
        return (head_.load() - tail_.load()) & (N - 1);
    }

    bool empty() const { return head_.load() == tail_.load(); }
    static constexpr size_t capacity() { return N - 1; }

private:
    T   buf_[N];
    std::atomic<size_t> head_{0};
    std::atomic<size_t> tail_{0};
};

}  // namespace sa_app

#endif  // SA_APP_RINGBUF_H
