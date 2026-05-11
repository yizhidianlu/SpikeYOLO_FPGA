/*
 * sw/app/src/fps_meter.h — exponential moving-average FPS counter + jitter
 *                          + per-stage latency tracker (M1 W5).
 *
 * Stage latency design (added M1 W5, three-stage threaded mode):
 *   Each producer/worker thread (capture / preproc / infer / postproc /
 *   display) records its per-frame work duration through tick_stage().
 *   Storage is six std::atomic<uint64_t> nanosecond accumulators + a frame
 *   counter — wait-free for both writer threads and the readout (no mutex).
 *   The mean is computed on read by dividing the accumulator by frames_
 *   (last-write-wins for frames_, accepted as a small statistical noise vs
 *   the mutex cost on a Cortex-A9 dual-core).
 *
 * "effective_fps" is the inverse of the total wall-clock per-frame interval
 * measured at the *display* stage (the consumer side). In sequential mode
 * this equals 1 / sum(stage latencies); in three-stage mode it can be
 * noticeably higher because capture / infer / display overlap.
 */

#ifndef SA_APP_FPS_METER_H
#define SA_APP_FPS_METER_H

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <deque>

namespace sa_app {

/* Aggregated readout, sampled from the live FpsMeter for logging. All values
 * are means over the run so far. effective_fps is the EMA reported by the
 * display stage and *does* reflect thread overlap. */
struct PerStageLat {
    double capture_ms{0.0};
    double preproc_ms{0.0};
    double infer_ms{0.0};
    double postproc_ms{0.0};
    double display_ms{0.0};
    double total_ms{0.0};         /* sum of stage means; sequential ≈ 1/fps  */
    double effective_fps{0.0};    /* EMA of inter-display intervals          */
};

enum class Stage : int {
    CAPTURE   = 0,
    PREPROC   = 1,
    INFER     = 2,
    POSTPROC  = 3,
    DISPLAY   = 4,
    _COUNT    = 5,
};

class FpsMeter {
public:
    /* @param ema_alpha    smoothing factor in (0, 1]; 0.1 ≈ ~10-frame window */
    explicit FpsMeter(float ema_alpha = 0.1f, size_t window = 120)
        : alpha_(ema_alpha), window_(window) {
        for (int i = 0; i < (int)Stage::_COUNT; ++i) {
            stage_ns_[i].store(0, std::memory_order_relaxed);
            stage_n_[i].store(0,  std::memory_order_relaxed);
        }
    }

    /* Frame-boundary tick (called by the *consumer* / display thread). */
    void tick() {
        const auto now = std::chrono::steady_clock::now();
        if (last_.time_since_epoch().count() != 0) {
            const auto dt = std::chrono::duration<float>(now - last_).count();
            if (dt > 0.0f) {
                const float inst_fps = 1.0f / dt;
                history_.push_back(inst_fps);
                if (history_.size() > window_) history_.pop_front();
                if (ema_ == 0.0f) ema_ = inst_fps;
                else              ema_ = (1.0f - alpha_) * ema_ + alpha_ * inst_fps;
            }
        }
        last_ = now;
        frames_++;
    }

    /* Record a single stage's per-frame latency. Wait-free; safe to call
     * concurrently from any thread for any stage. */
    void tick_stage(Stage s, double ms) {
        const int i = (int)s;
        if (i < 0 || i >= (int)Stage::_COUNT) return;
        const uint64_t ns = (uint64_t)(ms * 1.0e6);
        stage_ns_[i].fetch_add(ns, std::memory_order_relaxed);
        stage_n_[i].fetch_add(1,   std::memory_order_relaxed);
    }

    /* Snapshot the per-stage means + effective_fps. Safe to call at any time. */
    PerStageLat stage_breakdown() const {
        PerStageLat o;
        auto mean_ms = [&](Stage s) -> double {
            const int i = (int)s;
            const uint64_t n  = stage_n_[i].load(std::memory_order_relaxed);
            const uint64_t ns = stage_ns_[i].load(std::memory_order_relaxed);
            return (n == 0) ? 0.0 : (double)ns / (double)n / 1.0e6;
        };
        o.capture_ms   = mean_ms(Stage::CAPTURE);
        o.preproc_ms   = mean_ms(Stage::PREPROC);
        o.infer_ms     = mean_ms(Stage::INFER);
        o.postproc_ms  = mean_ms(Stage::POSTPROC);
        o.display_ms   = mean_ms(Stage::DISPLAY);
        o.total_ms     = o.capture_ms + o.preproc_ms + o.infer_ms
                       + o.postproc_ms + o.display_ms;
        o.effective_fps = ema_;
        return o;
    }

    float fps_ema()    const { return ema_; }
    uint64_t frames()  const { return frames_; }

    /* Coefficient of variation of FPS over the last `window_` samples. */
    float fps_cv() const {
        if (history_.size() < 2) return 0.0f;
        float mean = 0.0f;
        for (float f : history_) mean += f;
        mean /= history_.size();
        if (mean == 0.0f) return 0.0f;
        float var = 0.0f;
        for (float f : history_) var += (f - mean) * (f - mean);
        var /= history_.size();
        return std::sqrt(var) / mean;
    }

private:
    float alpha_, ema_{0.0f};
    size_t window_;
    std::deque<float> history_;
    std::chrono::steady_clock::time_point last_{};
    uint64_t frames_{0};

    /* Per-stage wait-free accumulators. */
    std::atomic<uint64_t> stage_ns_[(int)Stage::_COUNT];
    std::atomic<uint64_t> stage_n_ [(int)Stage::_COUNT];
};

}  // namespace sa_app

#endif  // SA_APP_FPS_METER_H
