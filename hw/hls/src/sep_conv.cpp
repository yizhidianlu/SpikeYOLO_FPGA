/*
 * hw/hls/src/sep_conv.cpp — composite SepConv block, mirrors
 * tools/fpga/numpy_reference.sep_conv line-for-line.
 *
 * Structure (4 sequential ms_standard_conv stages, all stride=1, channels stay
 * within {C, expand, C}):
 *
 *   x_i32 [T, C, H, W]
 *      -> ms_standard_conv (pwconv1, 1x1, C -> C_exp)
 *      -> ms_standard_conv (dwconv2, k_dw x k_dw, depth-wise on C_exp)
 *      -> ms_standard_conv (pwconv3, 1x1, C_exp -> C)
 *      -> ms_standard_conv (dwconv4, 3x3, depth-wise on C)
 *   -> y_i32 [T, C, H, W]   (channel + spatial preserved)
 *
 * NOTE on dwconv4 padding: the A1 PTQ packer historically emits pad=0 for the
 * SepRepConv 3x3 inner depth-wise (LayerEntry idx 4 / 11 / 18 / 27). The host
 * testbench applies a pad-autocorrect (pad <- k//2) before invoking us. The
 * DUT itself just trusts whatever pad the caller passes in.
 *
 * --- resource budget (per sep_conv invocation, 4 leaf convs) ---
 * estimated DSP:  shared with leaf sa_conv2d_int — at most ONE conv stage live
 *                 at a time => ceil(SA_CO_TILE * SA_CI_TILE / 2) = 64 (16x8/2
 *                 since INT8 DSP packing) — well under the 154 budget.
 * estimated BRAM: spike_buf ~ T*MAX_SPIKE*C_max*H*W = 4*48*32*32 / 1024 = 6 KB
 *                 tmp_acc   ~ T_in*C_max*H*W*4    = 4*48*32*32*4 / 1024 = 24 KB
 *                 (caller-allocated; no internal arrays in this wrapper)
 * pe_array_dim:   16x8 unrolled (inherited from sa_conv2d_int)
 */

#include "dtypes.h"
#include "axi_iface.h"
#include "op_macros.h"

#include <cstring>


extern "C" {

/* Per-stage parameter aggregate. Pass arrays of length 4: [pwconv1, dwconv2,
 * pwconv3, dwconv4] where the dwconv channel == groups == feature channel.
 *
 * @param x          in,    int32 [T, C, H, W]
 * @param y          out,   int32 [T, C, H, W]   (same C, same H, same W)
 * @param w_ptrs     [4]    weight base addresses (int8)
 * @param bias_ptrs  [4]    bias base addresses (int32)
 * @param shift_ptrs [4]    out_shift base addresses (int8)
 * @param C_arr      [4]    channel widths per stage (in_ch == prev_out_ch)
 *                          C_arr[0] = C  (in for pwconv1)
 *                          C_arr[1] = expanded C
 *                          C_arr[2] = expanded C
 *                          C_arr[3] = C  (out from pwconv3 == in for dwconv4)
 *                          C_out_arr[3] must equal C_arr[0] (residual-friendly).
 * @param C_out_arr  [4]    output channel per stage (mirror of C_arr after
 *                          shift; both arrays are passed for symmetry with
 *                          conv2d_bn, no internal coupling assumed).
 * @param K_arr      [4]    kernel sizes per stage (1 or k_dw or 3)
 * @param pad_arr    [4]    pad per stage
 * @param groups_arr [4]    groups per stage (1 for PW, C for DW)
 *
 * @param ping_buf / pong_buf  scratch int32 buffers, each large enough for
 *                              T * max(C_out_arr) * H * W elements.
 * @param spike_buf            scratch int8, T*MAX_SPIKE * max(C_arr) * H * W.
 * @param tmp_acc              scratch int32, T*MAX_SPIKE * max(C_out_arr) * H * W.
 *                              (reused across stages; conv2d_bn writes pre-
 *                              collapse accumulators here.)
 */
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
    int T,
    int C,             /* in/out channel (same for residual)           */
    int C_exp,         /* expansion channel between pwconv1/3          */
    int H,             /* spatial dims preserved across all 4 stages   */
    int W,
    int K_dw2,         /* kernel size for dwconv2 (e.g. 7)             */
    int K_dw4,         /* kernel size for dwconv4 (always 3 in YAML)   */
    int pad_dw2,
    int pad_dw4)
{
    SA_AXI_MM(x,         gmem0, 16777216)
    SA_AXI_MM(y,         gmem1, 16777216)
    SA_AXI_MM(w0,        gmem2, 1048576)  SA_AXI_MM(bias0, gmem3, 4096)  SA_AXI_MM(shift0, gmem4, 4096)
    SA_AXI_MM(w1,        gmem2, 1048576)  SA_AXI_MM(bias1, gmem3, 4096)  SA_AXI_MM(shift1, gmem4, 4096)
    SA_AXI_MM(w2,        gmem2, 1048576)  SA_AXI_MM(bias2, gmem3, 4096)  SA_AXI_MM(shift2, gmem4, 4096)
    SA_AXI_MM(w3,        gmem2, 1048576)  SA_AXI_MM(bias3, gmem3, 4096)  SA_AXI_MM(shift3, gmem4, 4096)
    SA_AXI_MM(ping_buf,  gmem5, 16777216)
    SA_AXI_MM(pong_buf,  gmem5, 16777216)
    SA_AXI_MM(spike_buf, gmem5, 16777216)
    SA_AXI_MM(tmp_acc,   gmem5, 16777216)
    SA_AXI_LITE(T)        SA_AXI_LITE(C)       SA_AXI_LITE(C_exp)
    SA_AXI_LITE(H)        SA_AXI_LITE(W)
    SA_AXI_LITE(K_dw2)    SA_AXI_LITE(K_dw4)
    SA_AXI_LITE(pad_dw2)  SA_AXI_LITE(pad_dw4)
    SA_AXI_LITE_RETURN

    /* Stage 1: pwconv1  (1x1)  C -> C_exp, groups=1 */
    sa_ms_standard_conv_inplace(x, ping_buf,
                                w0, bias0, shift0,
                                spike_buf, tmp_acc,
                                T, C, C_exp, H, W,
                                /*K=*/1, /*stride=*/1, /*pad=*/0, /*groups=*/1);

    /* Stage 2: dwconv2 (KxK)  C_exp -> C_exp, groups=C_exp (depth-wise) */
    sa_ms_standard_conv_inplace(ping_buf, pong_buf,
                                w1, bias1, shift1,
                                spike_buf, tmp_acc,
                                T, C_exp, C_exp, H, W,
                                /*K=*/K_dw2, /*stride=*/1,
                                /*pad=*/pad_dw2, /*groups=*/C_exp);

    /* Stage 3: pwconv3 (1x1) C_exp -> C, groups=1 */
    sa_ms_standard_conv_inplace(pong_buf, ping_buf,
                                w2, bias2, shift2,
                                spike_buf, tmp_acc,
                                T, C_exp, C, H, W,
                                /*K=*/1, /*stride=*/1, /*pad=*/0, /*groups=*/1);

    /* Stage 4: dwconv4 (3x3) C -> C, groups=C (depth-wise). Output goes to y. */
    sa_ms_standard_conv_inplace(ping_buf, y,
                                w3, bias3, shift3,
                                spike_buf, tmp_acc,
                                T, C, C, H, W,
                                /*K=*/K_dw4, /*stride=*/1,
                                /*pad=*/pad_dw4, /*groups=*/C);
}

}  /* extern "C" */
