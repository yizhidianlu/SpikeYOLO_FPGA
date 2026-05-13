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

    /* R2 v3 (URGENT_ASK_13): ALLOCATION (v1+v2) had ZERO Vivado-side effect
     * on fu_658 in this Vitis HLS 2024.1 install. Per Remote breakdown,
     * fu_658 internal hierarchy shows `_429_1` sub-instance = 53261 LUT vs
     * sibling `_429_536_1` = 3436 LUT (15x difference, same source). Vitis
     * is specializing sa_conv2d_int per-caller, with one variant getting
     * full mul unroll into LUT shift-add.
     *
     * v3 multi-pronged fix:
     *  1. INLINE off forces shared single instance, no per-caller specialization
     *  2. BIND_OP impl=DSP forces mul to DSP block (saves 150 LUT/mul)
     *  3. ALLOCATION (kept) caps concurrent muls; defense-in-depth
     */
    SA_HLS_PRAGMA(HLS INLINE off)
    SA_HLS_PRAGMA(HLS ALLOCATION operation instances=mul limit=8)
    SA_HLS_PRAGMA(HLS ALLOCATION operation instances=add limit=8)

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
                                    /* v3 R2 fix: split MAC so we can BIND_OP the mul
                                     * to DSP48 instead of LUT shift-add. Z-7020 has
                                     * 220 DSPs, currently using 161 (59 free) - enough
                                     * room for the previously-LUT-mapped muls. */
                                    sa_i32_t prod = px * wt;
                                    SA_HLS_PRAGMA(HLS BIND_OP variable=prod op=mul impl=DSP latency=3)
                                    acc += prod;
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
