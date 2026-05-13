/*
 * hw/hls/src/conv2d_bn.cpp — fused Conv2d_bn (post-PTQ).
 *
 * Mirrors tools/fpga/numpy_reference.conv2d_bn line-for-line:
 *
 *     y_i32 = conv2d_int(spike_i8, w_i8)                       // T_in batch
 *     if not first_layer:
 *         y_i32 = y_i32.reshape(MAX_SPIKE, T_out, ...).sum(0)   // collapse substeps
 *     y_i32 = (y_i32 + bias) >> out_shift                       // per-channel BN
 *
 * Output is int32 (pre-LIF). LIF + clamp + binary expansion lives in lif_expand.cpp.
 *
 * For simplicity we delegate the conv itself to sa_conv2d_int (the M1 kernel).
 * M5 inlines the two into a single dataflow when the PE array is in place.
 */

#include "dtypes.h"
#include "axi_iface.h"

#include <cstring>

extern "C" {

void sa_conv2d_int(const sa_i8_t *x, sa_i32_t *y, const sa_i8_t *w,
                   int N, int C_in, int C_out, int H, int W,
                   int K, int stride, int pad, int groups);


/* @param x          spike input,  int8 [T_in, C_in,  H,     W]
 * @param y          pre-LIF out,  int32 [T_out, C_out, H_out, W_out]
 * @param w          weights,      int8 [C_out, C_in/groups, K, K]
 * @param bias       per-channel,  int32 [C_out]
 * @param out_shift  per-channel,  int8  [C_out]
 * @param tmp_acc    scratch,      int32 [T_in, C_out, H_out, W_out]
 *                   (caller-supplied; lives in DDR3)
 */
void sa_conv2d_bn(
    const sa_i8_t  *x,
          sa_i32_t *y,
    const sa_i8_t  *w,
    const sa_i32_t *bias,
    const sa_i8_t  *out_shift,
          sa_i32_t *tmp_acc,
    int T_in,
    int C_in,
    int C_out,
    int H,
    int W,
    int K,
    int stride,
    int pad,
    int groups,
    int first_layer)
{
    SA_AXI_MM(x,         gmem0, 16777216)
    SA_AXI_MM(y,         gmem1, 16777216)
    SA_AXI_MM(w,         gmem2, 1048576)
    SA_AXI_MM(bias,      gmem3, 4096)
    SA_AXI_MM(out_shift, gmem4, 4096)
    SA_AXI_MM(tmp_acc,   gmem5, 16777216)
    SA_AXI_LITE(T_in)       SA_AXI_LITE(C_in)
    SA_AXI_LITE(C_out)      SA_AXI_LITE(H)
    SA_AXI_LITE(W)          SA_AXI_LITE(K)
    SA_AXI_LITE(stride)     SA_AXI_LITE(pad)
    SA_AXI_LITE(groups)     SA_AXI_LITE(first_layer)
    SA_AXI_LITE_RETURN

    /* R2 (Z-7020 LUT budget) fix v2 per URGENT_ASK_12 (2026-05-13).
     * v1 added ALLOCATION to conv2d_int.cpp but had ZERO effect on fu_658,
     * because Vitis HLS 2024.1 inlines sa_conv2d_int *into* sa_conv2d_bn
     * before applying ALLOCATION scope - the pragma in the inlined-away
     * function gets dropped. Per Remote diagnosis, fu_658 IS sa_conv2d_bn
     * (`grp_sa_conv2d_bn_40_71_118_240_333_426_1`), so the pragma must live
     * in *this* function body to bind. */
    SA_HLS_PRAGMA(HLS ALLOCATION operation instances=mul limit=16)
    SA_HLS_PRAGMA(HLS ALLOCATION operation instances=add limit=16)

    /* Stage 1: integer conv. Output is [T_in, C_out, H_out, W_out] int32. */
    sa_conv2d_int(x, tmp_acc, w,
                  T_in, C_in, C_out, H, W,
                  K, stride, pad, groups);

    const int H_out = (H + 2 * pad - K) / stride + 1;
    const int W_out = (W + 2 * pad - K) / stride + 1;
    const int spatial = H_out * W_out;

    /* Stage 2: collapse 4 binary substeps if this is not the first layer. */
    int T_out;
    if (first_layer) {
        T_out = T_in;       /* image input: 1 substep direct */
    } else {
        T_out = T_in / SA_MAX_SPIKE;
        /* Sum SA_MAX_SPIKE substeps into one frame per time step. */
        for (int t_out = 0; t_out < T_out; t_out++) {
            for (int co = 0; co < C_out; co++) {
                for (int sp = 0; sp < spatial; sp++) {
                    SA_PIPELINE_II(1)
                    sa_i32_t acc = 0;
                    for (int sub = 0; sub < SA_MAX_SPIKE; sub++) {
                        const int t_src = sub * T_out + t_out;
                        acc += tmp_acc[((t_src * C_out + co) * H_out + sp / W_out) *
                                       W_out + (sp % W_out)];
                    }
                    tmp_acc[((t_out * C_out + co) * H_out + sp / W_out) *
                            W_out + (sp % W_out)] = acc;
                }
            }
        }
    }

    /* Stage 3: add bias, shift, write to y. */
    for (int t = 0; t < T_out; t++) {
        for (int co = 0; co < C_out; co++) {
            const sa_i32_t b = bias[co];
            const int shift = (int)out_shift[co];
            for (int sp = 0; sp < spatial; sp++) {
                SA_PIPELINE_II(1)
                const int off = ((t * C_out + co) * H_out + sp / W_out) *
                                W_out + (sp % W_out);
                sa_i32_t v = tmp_acc[off] + b;
                /* arithmetic shift right; HLS preserves sign for ap_int<32> */
                v = v >> shift;
                y[off] = v;
            }
        }
    }
}

}  /* extern "C" */
