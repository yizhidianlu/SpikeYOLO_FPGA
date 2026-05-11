/*
 * sw/app/src/postproc_nms.cpp — single-scale NMS + bbox decode.
 */

#include "postproc_nms.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <vector>

namespace sa_app {

float sigmoid(float x)
{
    if (x >= 0.0f) {
        const float ex = std::exp(-x);
        return 1.0f / (1.0f + ex);
    }
    const float ex = std::exp(x);
    return ex / (1.0f + ex);
}


static float iou_xyxy(const Detection &a, const Detection &b)
{
    const float xa = std::max(a.x1, b.x1);
    const float ya = std::max(a.y1, b.y1);
    const float xb = std::min(a.x2, b.x2);
    const float yb = std::min(a.y2, b.y2);
    const float inter_w = std::max(0.0f, xb - xa);
    const float inter_h = std::max(0.0f, yb - ya);
    const float inter = inter_w * inter_h;
    const float area_a = std::max(0.0f, a.x2 - a.x1) * std::max(0.0f, a.y2 - a.y1);
    const float area_b = std::max(0.0f, b.x2 - b.x1) * std::max(0.0f, b.y2 - b.y1);
    const float uni = area_a + area_b - inter;
    return uni > 0.0f ? (inter / uni) : 0.0f;
}


std::vector<Detection> nms(std::vector<Detection> boxes, float iou_thresh)
{
    std::sort(boxes.begin(), boxes.end(),
              [](const Detection &a, const Detection &b) { return a.conf > b.conf; });
    std::vector<Detection> kept;
    kept.reserve(boxes.size());
    std::vector<bool> suppressed(boxes.size(), false);
    for (size_t i = 0; i < boxes.size(); i++) {
        if (suppressed[i]) continue;
        kept.push_back(boxes[i]);
        for (size_t j = i + 1; j < boxes.size(); j++) {
            if (suppressed[j]) continue;
            /* Class-aware: only suppress same-class boxes. */
            if (boxes[j].cls != boxes[i].cls) continue;
            if (iou_xyxy(boxes[i], boxes[j]) >= iou_thresh) {
                suppressed[j] = true;
            }
        }
    }
    return kept;
}


std::vector<Detection> decode_and_nms(const int8_t *feat,
                                      int nc,
                                      int grid_h, int grid_w, int stride,
                                      float conf_thresh,
                                      float iou_thresh,
                                      float scale_factor)
{
    std::vector<Detection> raw;
    raw.reserve(static_cast<size_t>(grid_h) * grid_w);
    const int CH = nc + 4;
    for (int y = 0; y < grid_h; y++) {
        for (int x = 0; x < grid_w; x++) {
            /* Find argmax of class scores at this cell. */
            int   best_cls = 0;
            float best_score = -1e9f;
            for (int c = 0; c < nc; c++) {
                const float s = feat[((c + 4) * grid_h + y) * grid_w + x] * scale_factor;
                if (s > best_score) {
                    best_score = s;
                    best_cls = c;
                }
            }
            const float conf = sigmoid(best_score);
            if (conf < conf_thresh) continue;

            /* Decode (dx, dy, log_w, log_h). */
            const float dx     = feat[(0 * grid_h + y) * grid_w + x] * scale_factor;
            const float dy     = feat[(1 * grid_h + y) * grid_w + x] * scale_factor;
            const float log_w  = feat[(2 * grid_h + y) * grid_w + x] * scale_factor;
            const float log_h  = feat[(3 * grid_h + y) * grid_w + x] * scale_factor;

            const float cx = (x + sigmoid(dx)) * stride;
            const float cy = (y + sigmoid(dy)) * stride;
            const float w  = std::exp(log_w) * stride;
            const float h  = std::exp(log_h) * stride;

            Detection d;
            d.x1 = cx - 0.5f * w;
            d.y1 = cy - 0.5f * h;
            d.x2 = cx + 0.5f * w;
            d.y2 = cy + 0.5f * h;
            d.conf = conf;
            d.cls = best_cls;
            raw.push_back(d);
            (void)CH;
        }
    }
    return nms(std::move(raw), iou_thresh);
}

}  // namespace sa_app
