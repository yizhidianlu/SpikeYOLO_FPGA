/*
 * sw/app/src/preproc.h — letterbox + YUV→RGB + INT8 quant.
 *
 * The algorithm mirrors `realtime_detect.py` line-for-line so the board
 * sees the same tensor the model was trained on. Reference / test coverage
 * lives in `tests/test_preproc_letterbox.py`.
 */

#ifndef SA_APP_PREPROC_H
#define SA_APP_PREPROC_H

#include <cstdint>
#include <vector>

namespace sa_app {

/* Letterbox metadata — needed to invert bbox coordinates back to the
 * original image after inference. */
struct Letterbox {
    int src_h;      /* original image height                                 */
    int src_w;      /* original image width                                  */
    int dst_h;      /* always 256 for tiny_fpga                              */
    int dst_w;      /* always 256                                            */
    float scale;    /* uniform shrink factor: min(dst_h/src_h, dst_w/src_w)  */
    int   pad_x;    /* horizontal padding on each side (left == right)       */
    int   pad_y;    /* vertical padding (top == bottom)                       */
    /* fill colour for the letterbox border. Matches ultralytics default. */
    static constexpr uint8_t FILL_R = 114;
    static constexpr uint8_t FILL_G = 114;
    static constexpr uint8_t FILL_B = 114;
};


/* Compute letterbox layout for a given source resolution. Pure metadata,
 * no allocation, no copy. */
Letterbox plan_letterbox(int src_h, int src_w, int dst_h = 256, int dst_w = 256);


/* Run letterbox on a packed-RGB888 buffer. Output is INT8 in NCHW layout
 * with values in [-128, 127] (i.e. uint8 - 128, no further scaling).
 *
 * @param rgb_in    src_h * src_w * 3 bytes, row-major RGB888
 * @param out_chw   dst_h * dst_w * 3 int8 elements, NCHW (C, H, W)
 */
void letterbox_rgb_to_int8_chw(const uint8_t *rgb_in,
                               const Letterbox &lb,
                               int8_t *out_chw);


/* YUYV (4:2:2) -> RGB888 packed. Common UVC camera capture format.
 * @param yuyv  src_h * src_w * 2 bytes
 * @param rgb   src_h * src_w * 3 bytes (caller-allocated)
 *
 * Uses the standard BT.601 conversion matrix.
 */
void yuyv_to_rgb888(const uint8_t *yuyv,
                    int src_h, int src_w,
                    uint8_t *rgb);


/* Inverse-letterbox a single bounding box back to the source image.
 * Operates on box edges in (x1, y1, x2, y2) form. */
void unletterbox_bbox(const Letterbox &lb,
                      float *x1, float *y1, float *x2, float *y2);

}  // namespace sa_app

#endif  // SA_APP_PREPROC_H
