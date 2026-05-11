/*
 * sw/app/src/preproc.cpp — preprocessing implementation.
 *
 * Reference: realtime_detect.py LetterBox + YUYV->RGB helpers.
 */

#include "preproc.h"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace sa_app {

Letterbox plan_letterbox(int src_h, int src_w, int dst_h, int dst_w)
{
    Letterbox lb;
    lb.src_h = src_h; lb.src_w = src_w;
    lb.dst_h = dst_h; lb.dst_w = dst_w;
    const float sy = static_cast<float>(dst_h) / static_cast<float>(src_h);
    const float sx = static_cast<float>(dst_w) / static_cast<float>(src_w);
    lb.scale = std::min(sy, sx);
    const int new_h = static_cast<int>(std::round(src_h * lb.scale));
    const int new_w = static_cast<int>(std::round(src_w * lb.scale));
    /* Ultralytics letterbox: centre the image and split the leftover padding
     * evenly. When the odd-pixel surplus exists, ultralytics floors at left/top.
     */
    lb.pad_x = (dst_w - new_w) / 2;
    lb.pad_y = (dst_h - new_h) / 2;
    return lb;
}


void letterbox_rgb_to_int8_chw(const uint8_t *rgb_in,
                               const Letterbox &lb,
                               int8_t *out_chw)
{
    const int dst_h = lb.dst_h, dst_w = lb.dst_w;
    const int src_h = lb.src_h, src_w = lb.src_w;
    const float inv_scale = 1.0f / lb.scale;

    /* For each output pixel, compute the source coordinate. Nearest-neighbour
     * keeps the kernel deterministic on FPGA-side too (no float interp). */
    auto fill_pixel = [&](int x, int y) {
        return (y >= lb.pad_y && y < lb.pad_y + static_cast<int>(std::round(src_h * lb.scale)) &&
                x >= lb.pad_x && x < lb.pad_x + static_cast<int>(std::round(src_w * lb.scale)));
    };

    const int H = dst_h, W = dst_w;
    /* Planar (CHW): R plane first, then G, then B. */
    for (int c = 0; c < 3; c++) {
        for (int y = 0; y < H; y++) {
            for (int x = 0; x < W; x++) {
                uint8_t v;
                if (fill_pixel(x, y)) {
                    /* map back to source */
                    int sx = static_cast<int>(std::round((x - lb.pad_x) * inv_scale));
                    int sy = static_cast<int>(std::round((y - lb.pad_y) * inv_scale));
                    if (sx >= src_w) sx = src_w - 1;
                    if (sy >= src_h) sy = src_h - 1;
                    if (sx < 0) sx = 0;
                    if (sy < 0) sy = 0;
                    v = rgb_in[(sy * src_w + sx) * 3 + c];
                } else {
                    switch (c) {
                    case 0: v = Letterbox::FILL_R; break;
                    case 1: v = Letterbox::FILL_G; break;
                    default: v = Letterbox::FILL_B; break;
                    }
                }
                /* INT8 quant: (uint8 - 128) keeps the centre of the
                 * uint8 range at zero, matching A1's stem first_layer scale. */
                out_chw[((c * H) + y) * W + x] = static_cast<int8_t>(static_cast<int>(v) - 128);
            }
        }
    }
}


void yuyv_to_rgb888(const uint8_t *yuyv,
                    int src_h, int src_w,
                    uint8_t *rgb)
{
    /* YUYV: each 4 bytes encode 2 pixels (Y0 U Y1 V). */
    for (int y = 0; y < src_h; y++) {
        const uint8_t *row = yuyv + y * src_w * 2;
        uint8_t *out_row = rgb + y * src_w * 3;
        for (int x = 0; x < src_w; x += 2) {
            int y0 = row[x * 2 + 0];
            int u  = row[x * 2 + 1];
            int y1 = row[x * 2 + 2];
            int v  = row[x * 2 + 3];
            /* BT.601 */
            int c0 = y0 - 16, c1 = y1 - 16;
            int d  = u - 128, e  = v - 128;
            auto clip = [](int v_) -> uint8_t {
                if (v_ < 0) return 0;
                if (v_ > 255) return 255;
                return static_cast<uint8_t>(v_);
            };
            int r0 = (298 * c0 + 409 * e + 128) >> 8;
            int g0 = (298 * c0 - 100 * d - 208 * e + 128) >> 8;
            int b0 = (298 * c0 + 516 * d + 128) >> 8;
            int r1 = (298 * c1 + 409 * e + 128) >> 8;
            int g1 = (298 * c1 - 100 * d - 208 * e + 128) >> 8;
            int b1 = (298 * c1 + 516 * d + 128) >> 8;
            out_row[x * 3 + 0] = clip(r0);
            out_row[x * 3 + 1] = clip(g0);
            out_row[x * 3 + 2] = clip(b0);
            out_row[(x + 1) * 3 + 0] = clip(r1);
            out_row[(x + 1) * 3 + 1] = clip(g1);
            out_row[(x + 1) * 3 + 2] = clip(b1);
        }
    }
}


void unletterbox_bbox(const Letterbox &lb,
                      float *x1, float *y1, float *x2, float *y2)
{
    const float inv = 1.0f / lb.scale;
    *x1 = (*x1 - lb.pad_x) * inv;
    *x2 = (*x2 - lb.pad_x) * inv;
    *y1 = (*y1 - lb.pad_y) * inv;
    *y2 = (*y2 - lb.pad_y) * inv;
    auto clip = [](float v, float lo, float hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    };
    *x1 = clip(*x1, 0.0f, static_cast<float>(lb.src_w - 1));
    *x2 = clip(*x2, 0.0f, static_cast<float>(lb.src_w - 1));
    *y1 = clip(*y1, 0.0f, static_cast<float>(lb.src_h - 1));
    *y2 = clip(*y2, 0.0f, static_cast<float>(lb.src_h - 1));
}

}  // namespace sa_app
