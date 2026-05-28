/*
 * sw/app/src/postproc_nms.h — single-class NMS + bbox decode.
 *
 * tiny_fpga emits a single-scale P4 grid:
 *     (nc + 4) channels × 16 × 16 INT8
 *
 * Channels:
 *     0..3                 dx, dy, log_w, log_h  (anchor-free deltas, INT8 scaled)
 *     4..(nc+3)            per-class scores  (INT8 saturated logits)
 *
 * stride = 16 (the model's only detection level for tiny_fpga).
 *
 * Reference implementation cross-checked in tests/test_postproc_nms.py
 * against a NumPy NMS golden.
 */

#ifndef SA_APP_POSTPROC_NMS_H
#define SA_APP_POSTPROC_NMS_H

#include <cstdint>
#include <vector>

namespace sa_app {

struct Detection {
    float x1, y1, x2, y2;      /* in 256x256 input coordinates              */
    float conf;                /* max class score in [0, 1]                 */
    int   cls;                 /* class index                                */
};


/* Decode the raw INT8 head output then run NMS.
 *
 * @param feat        (nc+4) * H * W INT8 buffer
 * @param nc          number of classes (80 for COCO)
 * @param grid_h, grid_w, stride   model layout
 * @param conf_thresh keep boxes with score >= this (in [0,1])
 * @param iou_thresh  NMS IoU threshold (in [0,1])
 * @param scale_factor   dequantize factor for the INT8 logits (model-dependent)
 */
std::vector<Detection> decode_and_nms(const int8_t *feat,
                                      int nc,
                                      int grid_h, int grid_w, int stride,
                                      float conf_thresh,
                                      float iou_thresh,
                                      float scale_factor = 1.0f / 64.0f);

/* Decode + NMS with class allowlist.  When `class_allowlist` is non-null and
 * non-empty, argmax is restricted to these class ids so noise from unused
 * channels (PBT model: only 0/5/6 trained) cannot win.  Pass nullptr or an
 * empty vector to behave identically to the 7-arg form.
 *
 * (Separate overload instead of a defaulted parameter to avoid an MSYS2
 *  g++ 5.3 ICE that triggers on two consecutive defaulted args.)
 */
std::vector<Detection> decode_and_nms(const int8_t *feat,
                                      int nc,
                                      int grid_h, int grid_w, int stride,
                                      float conf_thresh,
                                      float iou_thresh,
                                      float scale_factor,
                                      const std::vector<int> *class_allowlist);


/* Standalone NMS (operates on a pre-decoded list). Sorts by confidence and
 * suppresses overlapping boxes greedily. Public so tests can compare against
 * a NumPy reference. */
std::vector<Detection> nms(std::vector<Detection> boxes, float iou_thresh);


/* Sigmoid helper (used by decode_and_nms for class scores). */
float sigmoid(float x);

}  // namespace sa_app

#endif  // SA_APP_POSTPROC_NMS_H
