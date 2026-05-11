/*
 * sw/app/src/fps_meter.h — exponential moving-average FPS counter + jitter.
 */

#ifndef SA_APP_FPS_METER_H
#define SA_APP_FPS_METER_H

#include <chrono>
#include <deque>
#include <cstdint>

namespace sa_app {

class FpsMeter {
public:
    /* @param ema_alpha    smoothing factor in (0, 1]; 0.1 ≈ ~10-frame window */
    explicit FpsMeter(float ema_alpha = 0.1f, size_t window = 120)
        : alpha_(ema_alpha), window_(window) {}

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
};

}  // namespace sa_app

#endif  // SA_APP_FPS_METER_H
