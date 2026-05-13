/*
 * hw/hls/src/conv2d_int.cpp — int8 conv2d, line-for-line port of
 * tools/fpga/numpy_reference.py::conv2d_int.
 *
 * Algorithm (per kernel position (ky, kx), per group g):
 *   y[g_out, h_out, w_out] += sum_{ci} x[g_in, h_in, w_in] * w[g_out, ci, ky, kx]
 *
 * This M1 version is a flattened triple-nested loop with a single PIPELINE
 * pragma on the innermost stage. It is the bit-exact reference; M5 RTL
 * tuning (B3) will replace this with the 16×8 systolic PE array.
 */

#include "dtypes.h"
#include "axi_iface.h"

#include <cstring>

extern "C" {

/* sa_conv2d_int — drop-in for numpy_reference.conv2d_int(x, w, stride, pad).
 *
 * Inputs are passed as flat arrays in C-order:
 *   x  : int8  [N, C_in,  H,     W]
 *   w  : int8  [C_out, C_in/groups, K, K]
 *   y  : int32 [N, C_out, H_out, W_out]
 *
 * Shape parameters are passed via AXI-Lite registers, not baked in,
 * so a single IP instance handles every conv layer in tiny_fpga.
 */
void sa_conv2d_int(
    const sa_i8_t  *x,
          sa_i32_t *y,
    const sa_i8_t  *w,
    int   N,
    int   C_in,
    int   C_out,
    int   H,
    int   W,
    int   K,
    int   stride,
    int   pad,
    int   groups)
{
    SA_AXI_MM(x, gmem0, 4194304)
    SA_AXI_MM(y, gmem1, 4194304)
    SA_AXI_MM(w, gmem2, 1048576)
    SA_AXI_LITE(N)
    SA_AXI_LITE(C_in)
    SA_AXI_LITE(C_out)
    SA_AXI_LITE(H)
    SA_AXI_LITE(W)
    SA_AXI_LITE(K)
    SA_AXI_LITE(stride)
    SA_AXI_LITE(pad)
    SA_AXI_LITE(groups)
    SA_AXI_LITE_RETURN

    /* R2 (Z-7020 LUT budget) fix per step5_util_breakdown.md 2026-05-13.
     * One inlined instance of this kernel (fu_658) was costing 28K LUT and
     * only 2 DSPs - Vitis was unrolling the inner mul into LUT-based shift-add
     * for that caller's parameter range. Cap concurrent muls/adds via
     * ALLOCATION so Vitis must time-multiplex DSP MAC instead. csim is
     * unaffected (ALLOCATION only constrains RTL scheduling, not C semantics).
     * Limit chosen as 16 (one per PE-tile column) - matches the original
     * SA_CO_TILE=16 documentation intent. Throughput drops by ~9x worst case
     * (3x3xCi inner reduction now serialized across 16 mul units), acceptable
     * for M2 fitting milestone. */
    SA_HLS_PRAGMA(HLS ALLOCATION operation instances=mul limit=16)
    SA_HLS_PRAGMA(HLS ALLOCATION operation instances=add limit=16)

    const int C_in_g  = C_in  / groups;
    const int C_out_g = C_out / groups;
    const int H_out   = (H + 2 * pad - K) / stride + 1;
    const int W_out   = (W + 2 * pad - K) / stride + 1;

    /* Pre-zero output. */
    for (int n = 0; n < N; n++) {
        for (int co = 0; co < C_out; co++) {
            for (int hy = 0; hy < H_out; hy++) {
                for (int wx = 0; wx < W_out; wx++) {
                    y[((n * C_out + co) * H_out + hy) * W_out + wx] = 0;
                }
            }
        }
    }

    /* Conv accumulation. */
    for (int n = 0; n < N; n++) {
        for (int g = 0; g < groups; g++) {
            const int co_lo = g * C_out_g;
            const int co_hi = co_lo + C_out_g;
            const int ci_lo = g * C_in_g;

            for (int co = co_lo; co < co_hi; co++) {
                for (int hy = 0; hy < H_out; hy++) {
                    for (int wx = 0; wx < W_out; wx++) {
                        SA_PIPELINE_II(1)
                        sa_i32_t acc = 0;
                        for (int ci = 0; ci < C_in_g; ci++) {
                            for (int ky = 0; ky < K; ky++) {
                                for (int kx = 0; kx < K; kx++) {
                                    const int h_in = hy * stride + ky - pad;
                                    const int w_in = wx * stride + kx - pad;
                                    sa_i32_t px = 0;
                                    if (h_in >= 0 && h_in < H && w_in >= 0 && w_in < W) {
                                        const int x_off = ((n * C_in + ci_lo + ci) * H + h_in) * W + w_in;
                                        px = (sa_i32_t)x[x_off];
                                    }
                                    /* w shape: [C_out, C_in/groups, K, K]
                                     *   index = ((co * C_in_g) + ci) * K * K + ky * K + kx
                                     */
                                    const int w_idx = ((co * C_in_g) + ci) * K * K + ky * K + kx;
                                    sa_i32_t wt = (sa_i32_t)w[w_idx];
                                    acc += px * wt;
                                }
                            }
                        }
                        const int y_off = ((n * C_out + co) * H_out + hy) * W_out + wx;
                        y[y_off] = acc;
                    }
                }
            }
        }
    }
}

}  /* extern "C" */
