/*
 * hw/hls/src/ms_all_conv_block.cpp — composite MS_AllConvBlock, mirrors
 * tools/fpga/numpy_reference.ms_all_conv_block line-for-line.
 *
 * Algorithm:
 *
 *   x_in     [T, C, H, W]                              (int32 pre-LIF)
 *   r1   <- x_in
 *   x    <- sep_conv(x_in, sep_params)                [T, C, H, W]
 *   x    <- x + r1                                    // residual 1 (in-place)
 *   r2   <- x  (saved as feature)
 *   x    <- ms_standard_conv(x,    conv1)             [T, C_mid, H, W]
 *   x    <- ms_standard_conv(x,    conv2)             [T, C, H, W]   (C must match for r2)
 *   y    <- x + r2                                    // residual 2
 *
 * Channel widths are NOT all C — conv1 expands to C_mid (e.g. 96 for acb1) and
 * conv2 reduces back to C. K_c1 / K_c2 are typically 3x3 in the YAML (not the
 * 1x1 we initially assumed). Spatial dims are preserved throughout.
 *
 * --- resource budget ---
 * estimated DSP:  shared with sep_conv (max 1 conv stage live at a time);
 *                 worst single conv is conv1 with k=3 g=1 -> 64 (16x8 packed).
 * estimated BRAM: residual r2 + sep_y_buf each T*C*H*W*4 bytes.
 *                 Worst case (layer_07 acb3b T=1, C=96, H=W=16): 24 KB each.
 *                 plus per-stage spike_buf / tmp_acc reused by sep_conv.
 * pe_array_dim:   16x8 unrolled (inherited from sa_conv2d_int).
 */

#include "dtypes.h"
#include "axi_iface.h"
#include "op_macros.h"

#include <cstring>

extern "C" {

void sa_sep_conv(
    const sa_i32_t *x,
          sa_i32_t *y,
    const sa_i8_t  *w0, const sa_i32_t *bias0, const sa_i8_t *shift0,
    const sa_i8_t  *w1, const sa_i32_t *bias1, const sa_i8_t *shift1,
    const sa_i8_t  *w2, const sa_i32_t *bias2, const sa_i8_t *shift2,
    const sa_i8_t  *w3, const sa_i32_t *bias3, const sa_i8_t *shift3,
          sa_i32_t *ping_buf,
          sa_i32_t *pong_buf,
          sa_i8_t  *spike_buf,
          sa_i32_t *tmp_acc,
    int T, int C, int C_exp, int H, int W,
    int K_dw2, int K_dw4, int pad_dw2, int pad_dw4);


void sa_ms_all_conv_block(
    const sa_i32_t *x_in,
          sa_i32_t *y,
    /* sep_conv weights x4 */
    const sa_i8_t  *sep_w0, const sa_i32_t *sep_b0, const sa_i8_t *sep_s0,
    const sa_i8_t  *sep_w1, const sa_i32_t *sep_b1, const sa_i8_t *sep_s1,
    const sa_i8_t  *sep_w2, const sa_i32_t *sep_b2, const sa_i8_t *sep_s2,
    const sa_i8_t  *sep_w3, const sa_i32_t *sep_b3, const sa_i8_t *sep_s3,
    /* conv1 weights : C -> C_mid, KxK, g=1 */
    const sa_i8_t  *c1_w,   const sa_i32_t *c1_b,   const sa_i8_t *c1_s,
    /* conv2 weights : C_mid -> C, KxK, g=1 */
    const sa_i8_t  *c2_w,   const sa_i32_t *c2_b,   const sa_i8_t *c2_s,
    /* scratch buffers */
          sa_i32_t *r_buf,        /* T*C*H*W                     */
          sa_i32_t *sep_y_buf,    /* T*C*H*W                     */
          sa_i32_t *ping_buf,     /* T*max(C_exp,C_mid)*H*W      */
          sa_i32_t *pong_buf,     /* T*max(C_exp,C_mid)*H*W      */
          sa_i8_t  *spike_buf,    /* T*MAX_SPIKE*max(C_exp,C_mid,C)*H*W */
          sa_i32_t *tmp_acc,      /* T*MAX_SPIKE*max(C_exp,C_mid,C)*H*W */
    int T,
    int C,             /* in/out channel of the block (residual axis)        */
    int C_exp,         /* sep_conv expansion channel                          */
    int C_mid,         /* conv1 output channel == conv2 input channel        */
    int H,
    int W,
    int K_dw2,         /* sep_conv dwconv2 kernel size                        */
    int K_dw4,         /* sep_conv dwconv4 kernel size                        */
    int pad_dw2,
    int pad_dw4,
    int K_c1,          /* conv1 kernel (typ 3)                                */
    int pad_c1,
    int K_c2,          /* conv2 kernel (typ 3)                                */
    int pad_c2)
{
    SA_AXI_MM(x_in,      gmem0, 16777216)
    SA_AXI_MM(y,         gmem1, 16777216)
    SA_AXI_MM(sep_w0,    gmem2, 1048576)  SA_AXI_MM(sep_b0, gmem3, 4096)  SA_AXI_MM(sep_s0, gmem4, 4096)
    SA_AXI_MM(sep_w1,    gmem2, 1048576)  SA_AXI_MM(sep_b1, gmem3, 4096)  SA_AXI_MM(sep_s1, gmem4, 4096)
    SA_AXI_MM(sep_w2,    gmem2, 1048576)  SA_AXI_MM(sep_b2, gmem3, 4096)  SA_AXI_MM(sep_s2, gmem4, 4096)
    SA_AXI_MM(sep_w3,    gmem2, 1048576)  SA_AXI_MM(sep_b3, gmem3, 4096)  SA_AXI_MM(sep_s3, gmem4, 4096)
    SA_AXI_MM(c1_w,      gmem2, 1048576)  SA_AXI_MM(c1_b,   gmem3, 4096)  SA_AXI_MM(c1_s,   gmem4, 4096)
    SA_AXI_MM(c2_w,      gmem2, 1048576)  SA_AXI_MM(c2_b,   gmem3, 4096)  SA_AXI_MM(c2_s,   gmem4, 4096)
    SA_AXI_MM(r_buf,     gmem5, 16777216) SA_AXI_MM(sep_y_buf, gmem5, 16777216)
    SA_AXI_MM(ping_buf,  gmem5, 16777216) SA_AXI_MM(pong_buf,  gmem5, 16777216)
    SA_AXI_MM(spike_buf, gmem5, 16777216) SA_AXI_MM(tmp_acc,   gmem5, 16777216)
    SA_AXI_LITE(T)        SA_AXI_LITE(C)       SA_AXI_LITE(C_exp)   SA_AXI_LITE(C_mid)
    SA_AXI_LITE(H)        SA_AXI_LITE(W)
    SA_AXI_LITE(K_dw2)    SA_AXI_LITE(K_dw4)
    SA_AXI_LITE(pad_dw2)  SA_AXI_LITE(pad_dw4)
    SA_AXI_LITE(K_c1)     SA_AXI_LITE(pad_c1)
    SA_AXI_LITE(K_c2)     SA_AXI_LITE(pad_c2)
    SA_AXI_LITE_RETURN

    const int n_elem = T * C * H * W;

    /* sep_conv(x_in, sep_y_buf) */
    sa_sep_conv(x_in, sep_y_buf,
                sep_w0, sep_b0, sep_s0,
                sep_w1, sep_b1, sep_s1,
                sep_w2, sep_b2, sep_s2,
                sep_w3, sep_b3, sep_s3,
                ping_buf, pong_buf, spike_buf, tmp_acc,
                T, C, C_exp, H, W,
                K_dw2, K_dw4, pad_dw2, pad_dw4);

    /* Residual #1: sep_y_buf += x_in */
    sa_residual_add_i32(sep_y_buf, x_in, n_elem);

    /* Save x_feat (= sep_conv result + x_in) into r_buf for residual #2. */
    for (int i = 0; i < n_elem; i++) {
        SA_PIPELINE_II(1)
        r_buf[i] = sep_y_buf[i];
    }

    /* conv1: ms_standard_conv (C -> C_mid). Output -> ping_buf [T, C_mid, H, W]. */
    sa_ms_standard_conv_inplace(sep_y_buf, ping_buf,
                                c1_w, c1_b, c1_s,
                                spike_buf, tmp_acc,
                                T, C, C_mid, H, W,
                                /*K=*/K_c1, /*stride=*/1, /*pad=*/pad_c1, /*groups=*/1);

    /* conv2: ms_standard_conv (C_mid -> C). Output -> y. */
    sa_ms_standard_conv_inplace(ping_buf, y,
                                c2_w, c2_b, c2_s,
                                spike_buf, tmp_acc,
                                T, C_mid, C, H, W,
                                /*K=*/K_c2, /*stride=*/1, /*pad=*/pad_c2, /*groups=*/1);

    /* Residual #2: y += r_buf */
    sa_residual_add_i32(y, r_buf, n_elem);
}

}  /* extern "C" */
