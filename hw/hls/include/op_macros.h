/*
 * hw/hls/include/op_macros.h — small inline helpers shared between W3 block-level
 * operators (sep_conv / ms_all_conv_block / spike_sppf).
 *
 * Each helper is a thin static-inline wrapper that funnels through the existing
 * extern "C" leaf kernels (sa_lif_expand + sa_conv2d_bn) so we do NOT duplicate
 * the int conv math. This keeps every block synthesisable as a sequence of
 * already-validated leaf kernels — M5 will inline them via dataflow once the PE
 * array lands.
 *
 * Helper #1: sa_ms_standard_conv_inplace — LIF expand + conv2d_bn (the
 *            "non-first-layer" path of ms_downsampling). Used by sep_conv,
 *            ms_all_conv_block, and spike_sppf cv1/cv2.
 *
 * Helper #2: sa_residual_add_i32 — element-wise int32 add for the two residual
 *            shortcuts inside ms_all_conv_block.
 */

#ifndef SA_HLS_OP_MACROS_H
#define SA_HLS_OP_MACROS_H

#include "dtypes.h"
#include "axi_iface.h"

/* Forward decl — leaf kernels live in their own .cpp and are linked in. */
extern "C" {

void sa_conv2d_bn(const sa_i8_t *x, sa_i32_t *y, const sa_i8_t *w,
                  const sa_i32_t *bias, const sa_i8_t *out_shift,
                  sa_i32_t *tmp_acc,
                  int T_in, int C_in, int C_out, int H, int W,
                  int K, int stride, int pad, int groups, int first_layer);

void sa_lif_expand(const sa_i32_t *x_in, sa_i8_t *spike_out,
                   int T, int C, int H, int W);

void sa_maxpool_or(const sa_i8_t *x_in, sa_i8_t *y_out,
                   int T, int C, int H, int W, int K);

}  /* extern "C" */


/* ms_standard_conv: int32 [T_in, C_in, H, W]  ->  int32 [T_in, C_out, H_o, W_o]
 *
 * Internally:
 *   sa_lif_expand    : x_i32 -> spike_buf int8 [T_in*MAX_SPIKE, C_in, H, W]
 *   sa_conv2d_bn     : spike_buf -> y int32 (collapses MAX_SPIKE substeps)
 *
 * Caller supplies spike_buf and tmp_acc large enough for the worst tile.
 */
static inline void sa_ms_standard_conv_inplace(
    const sa_i32_t *x_i32,
          sa_i32_t *y,
    const sa_i8_t  *w,
    const sa_i32_t *bias,
    const sa_i8_t  *out_shift,
          sa_i8_t  *spike_buf,
          sa_i32_t *tmp_acc,
    int T_in, int C_in, int C_out, int H, int W,
    int K, int stride, int pad, int groups)
{
    sa_lif_expand(x_i32, spike_buf, T_in, C_in, H, W);
    sa_conv2d_bn(spike_buf, y, w, bias, out_shift, tmp_acc,
                 T_in * SA_MAX_SPIKE, C_in, C_out, H, W,
                 K, stride, pad, groups, /*first_layer=*/0);
}


/* In-place int32 element-wise add (used by ms_all_conv_block residuals). */
static inline void sa_residual_add_i32(
          sa_i32_t *dst,
    const sa_i32_t *src,
    int n)
{
    for (int i = 0; i < n; i++) {
        SA_PIPELINE_II(1)
        dst[i] = (sa_i32_t)(dst[i] + src[i]);
    }
}

#endif  /* SA_HLS_OP_MACROS_H */
