/*
 * hw/hls/src/ms_downsampling.cpp — Block-level operator for stem and inner
 * downsampling layers, mirroring tools/fpga/numpy_reference.ms_downsampling.
 *
 * For tiny_fpga the stem (layer_00) is the only `first_layer=1` instance:
 *
 *     int8 [1, 3, 256, 256]      (RGB image, normalised to [-128, 127])
 *  -> conv 7x7 stride 4 pad 2    int32 [1, 24, 64, 64]
 *  -> + bias                     int32
 *  -> >> per-channel out_shift   int32  (stored in the golden tensor)
 *
 * Inner downsampling layers (e.g. layer_02, layer_05) take int32 pre-LIF
 * input and run mem_update + expand_cumulative + conv2d_bn, exactly as the
 * NumPy reference does.
 *
 * Implementation note: rather than re-derive the math, we delegate to the
 * already-validated sa_conv2d_bn (and sa_lif_expand on the inner path) — the
 * fused PE-array variant lands in a later sprint (M5 dataflow phase).
 */

#include "dtypes.h"
#include "axi_iface.h"

#include <cstring>

extern "C" {

void sa_conv2d_bn(const sa_i8_t *x, sa_i32_t *y, const sa_i8_t *w,
                  const sa_i32_t *bias, const sa_i8_t *out_shift,
                  sa_i32_t *tmp_acc,
                  int T_in, int C_in, int C_out, int H, int W,
                  int K, int stride, int pad, int groups, int first_layer);

void sa_lif_expand(const sa_i32_t *x_in, sa_i8_t *spike_out,
                   int T, int C, int H, int W);


/* @param x_i8        stem input,         int8 [T_in, C_in, H, W]   (first_layer=1)
 * @param x_i32       inner input,        int32 [T_in, C_in, H, W]  (first_layer=0)
 * @param y           pre-next-layer out, int32 [T_out, C_out, H_out, W_out]
 *                    where T_out = T_in if first_layer else T_in
 *                    (sa_conv2d_bn already collapses MAX_SPIKE substeps)
 * @param w           weights,            int8  [C_out, C_in/groups, K, K]
 * @param bias        per-channel,        int32 [C_out]
 * @param out_shift   per-channel,        int8  [C_out]
 * @param spike_buf   scratch,            int8  [T_in*MAX_SPIKE, C_in, H, W]
 *                    (only touched when first_layer=0)
 * @param tmp_acc     scratch,            int32 [T_in*MAX_SPIKE, C_out, H_out, W_out]
 */
void sa_ms_downsampling(
    const sa_i8_t  *x_i8,
    const sa_i32_t *x_i32,
          sa_i32_t *y,
    const sa_i8_t  *w,
    const sa_i32_t *bias,
    const sa_i8_t  *out_shift,
          sa_i8_t  *spike_buf,
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
    SA_AXI_MM(x_i8,      gmem0, 1048576)
    SA_AXI_MM(x_i32,     gmem0, 4194304)
    SA_AXI_MM(y,         gmem1, 16777216)
    SA_AXI_MM(w,         gmem2, 1048576)
    SA_AXI_MM(bias,      gmem3, 4096)
    SA_AXI_MM(out_shift, gmem4, 4096)
    SA_AXI_MM(spike_buf, gmem5, 16777216)
    SA_AXI_MM(tmp_acc,   gmem5, 16777216)
    SA_AXI_LITE(T_in)         SA_AXI_LITE(C_in)
    SA_AXI_LITE(C_out)        SA_AXI_LITE(H)
    SA_AXI_LITE(W)            SA_AXI_LITE(K)
    SA_AXI_LITE(stride)       SA_AXI_LITE(pad)
    SA_AXI_LITE(groups)       SA_AXI_LITE(first_layer)
    SA_AXI_LITE_RETURN

    if (first_layer) {
        /* Stem: input is INT8 RGB, no LIF, single substep. */
        sa_conv2d_bn(x_i8, y, w, bias, out_shift, tmp_acc,
                     T_in, C_in, C_out, H, W,
                     K, stride, pad, groups, /*first_layer=*/1);
    } else {
        /* Inner downsample: LIF expand to MAX_SPIKE binary substeps, then
         * conv2d_bn collapses them back to T_in time steps.
         */
        sa_lif_expand(x_i32, spike_buf, T_in, C_in, H, W);
        sa_conv2d_bn(spike_buf, y, w, bias, out_shift, tmp_acc,
                     T_in * SA_MAX_SPIKE, C_in, C_out, H, W,
                     K, stride, pad, groups, /*first_layer=*/0);
    }
}

}  /* extern "C" */
