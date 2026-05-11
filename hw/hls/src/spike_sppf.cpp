/*
 * hw/hls/src/spike_sppf.cpp — composite SpikeSPPF, mirrors
 * tools/fpga/numpy_reference.spike_sppf line-for-line.
 *
 * Algorithm:
 *
 *   x_in [T, C_in, H, W]                              (int32 pre-LIF)
 *   x   <- ms_standard_conv(x_in, cv1)               [T, C_mid, H, W]
 *   spk <- mem_update(x)                             int8 [T*MAX_SPIKE, C_mid, H, W]
 *   y1  <- maxpool2d_spike(spk, k)                   int8 (same shape)
 *   y2  <- maxpool2d_spike(y1,  k)                   int8 (same shape)
 *   y3  <- maxpool2d_spike(y2,  k)                   int8 (same shape)
 *   cat <- concat([spk, y1, y2, y3], axis=C)         int8 [T*MAX_SPIKE, 4*C_mid, H, W]
 *   cat_i32 <- collapse MAX_SPIKE substeps -> int32 [T, 4*C_mid, H, W]
 *   y_out <- ms_standard_conv(cat_i32, cv2)          [T, C_out, H, W]
 *
 * For tiny_fpga we expect: C_mid = C_in / 2 (cv1 halves), C_cat = 4*C_mid,
 * cv2: C_cat -> C_out (typically restores C_out = C_mid, or to user-defined).
 *
 * --- resource budget ---
 * estimated DSP:  shared with leaf sa_conv2d_int — 64 (16x8 packed); maxpool
 *                 stages add zero DSP (binary OR-tree only).
 * estimated BRAM: spk + y1..y3 = 4 * (T*MAX_SPIKE * C_mid * H * W) bytes int8.
 *                 Worst case here (layer_08): T=1, MAX_SPIKE=4, C_mid=48,
 *                 H=W=16 -> 4*4*48*16*16 = 49152 bytes = 48 KB total spike
 *                 staging. concat scratch is the same 48 KB. caller-owned.
 * pe_array_dim:   16x8 unrolled (inherited).
 */

#include "dtypes.h"
#include "axi_iface.h"
#include "op_macros.h"

#include <cstring>

extern "C" {

/* @param x_in        int32 [T, C_in, H, W]
 * @param y_out       int32 [T, C_out, H, W]
 * @param cv1_w/b/s   ConvBnParams for the half-channel 1x1 reduce
 * @param cv2_w/b/s   ConvBnParams for the post-concat 1x1 mix
 * @param ping_buf    scratch int32 [T, C_mid, H, W]   (cv1 output)
 * @param spk_buf     scratch int8  [T*MAX_SPIKE, C_mid, H, W]  (mem_update out)
 * @param pool_buf1   scratch int8  [T*MAX_SPIKE, C_mid, H, W]
 * @param pool_buf2   scratch int8  [T*MAX_SPIKE, C_mid, H, W]
 * @param pool_buf3   scratch int8  [T*MAX_SPIKE, C_mid, H, W]
 * @param concat_buf  scratch int8  [T*MAX_SPIKE, 4*C_mid, H, W]
 * @param cat_i32_buf scratch int32 [T, 4*C_mid, H, W]   (post-collapse)
 * @param spike_buf   scratch int8  for ms_standard_conv internal
 * @param tmp_acc     scratch int32 for ms_standard_conv internal
 *
 * @param T, C_in, C_mid, C_out, H, W   geometry
 * @param k                             kernel for the pool branch (5 in YAML)
 */
void sa_spike_sppf(
    const sa_i32_t *x_in,
          sa_i32_t *y_out,
    const sa_i8_t  *cv1_w, const sa_i32_t *cv1_b, const sa_i8_t *cv1_s,
    const sa_i8_t  *cv2_w, const sa_i32_t *cv2_b, const sa_i8_t *cv2_s,
          sa_i32_t *ping_buf,
          sa_i8_t  *spk_buf,
          sa_i8_t  *pool_buf1,
          sa_i8_t  *pool_buf2,
          sa_i8_t  *pool_buf3,
          sa_i8_t  *concat_buf,
          sa_i32_t *cat_i32_buf,
          sa_i8_t  *spike_buf,
          sa_i32_t *tmp_acc,
    int T,
    int C_in,
    int C_mid,
    int C_out,
    int H,
    int W,
    int k)
{
    SA_AXI_MM(x_in,        gmem0, 16777216)
    SA_AXI_MM(y_out,       gmem1, 16777216)
    SA_AXI_MM(cv1_w,       gmem2, 1048576)  SA_AXI_MM(cv1_b, gmem3, 4096)  SA_AXI_MM(cv1_s, gmem4, 4096)
    SA_AXI_MM(cv2_w,       gmem2, 1048576)  SA_AXI_MM(cv2_b, gmem3, 4096)  SA_AXI_MM(cv2_s, gmem4, 4096)
    SA_AXI_MM(ping_buf,    gmem5, 16777216)
    SA_AXI_MM(spk_buf,     gmem5, 16777216)
    SA_AXI_MM(pool_buf1,   gmem5, 16777216)
    SA_AXI_MM(pool_buf2,   gmem5, 16777216)
    SA_AXI_MM(pool_buf3,   gmem5, 16777216)
    SA_AXI_MM(concat_buf,  gmem5, 16777216)
    SA_AXI_MM(cat_i32_buf, gmem5, 16777216)
    SA_AXI_MM(spike_buf,   gmem5, 16777216)
    SA_AXI_MM(tmp_acc,     gmem5, 16777216)
    SA_AXI_LITE(T)        SA_AXI_LITE(C_in)
    SA_AXI_LITE(C_mid)    SA_AXI_LITE(C_out)
    SA_AXI_LITE(H)        SA_AXI_LITE(W)
    SA_AXI_LITE(k)
    SA_AXI_LITE_RETURN

    const int spatial = H * W;

    /* Stage 1: cv1 (1x1, C_in -> C_mid). ping_buf = ms_standard_conv(x_in, cv1). */
    sa_ms_standard_conv_inplace(x_in, ping_buf,
                                cv1_w, cv1_b, cv1_s,
                                spike_buf, tmp_acc,
                                T, C_in, C_mid, H, W,
                                /*K=*/1, /*stride=*/1, /*pad=*/0, /*groups=*/1);

    /* Stage 2: spk = mem_update(ping_buf) — produces T*MAX_SPIKE binary frames.
     * Reuse sa_lif_expand. T_spk = T*MAX_SPIKE. */
    sa_lif_expand(ping_buf, spk_buf, T, C_mid, H, W);
    const int T_spk = T * SA_MAX_SPIKE;

    /* Stage 3: cascaded MaxPool branches. */
    sa_maxpool_or(spk_buf,    pool_buf1, T_spk, C_mid, H, W, k);
    sa_maxpool_or(pool_buf1,  pool_buf2, T_spk, C_mid, H, W, k);
    sa_maxpool_or(pool_buf2,  pool_buf3, T_spk, C_mid, H, W, k);

    /* Stage 4: concat([spk, y1, y2, y3], axis=C). Output channel = 4*C_mid.
     * Layout pattern per (t, h, w):  [C_mid spk] || [C_mid y1] || [C_mid y2] || [C_mid y3]
     *
     * Source layout : pool_bufN[(((t * C_mid + c) * H + hy) * W) + wx]
     * Dest layout   : concat_buf[(((t * (4*C_mid) + c_dst) * H + hy) * W) + wx]
     *                  with c_dst = branch * C_mid + c
     */
    const int C_cat = 4 * C_mid;
    for (int t = 0; t < T_spk; t++) {
        for (int branch = 0; branch < 4; branch++) {
            const sa_i8_t *src;
            switch (branch) {
                case 0: src = spk_buf;   break;
                case 1: src = pool_buf1; break;
                case 2: src = pool_buf2; break;
                default: src = pool_buf3; break;
            }
            const int c_dst_base = branch * C_mid;
            for (int c = 0; c < C_mid; c++) {
                for (int sp = 0; sp < spatial; sp++) {
                    SA_PIPELINE_II(1)
                    const int src_off = ((t * C_mid + c)            * H + sp / W) * W + (sp % W);
                    const int dst_off = ((t * C_cat + c_dst_base + c) * H + sp / W) * W + (sp % W);
                    concat_buf[dst_off] = src[src_off];
                }
            }
        }
    }

    /* Stage 5: collapse MAX_SPIKE substeps in concat_buf back to int32 frame.
     * cat_i32_buf[t, c, h, w] = sum_{sub=0..MAX_SPIKE-1} concat_buf[sub*T + t, c, h, w]
     * Layout: concat_buf treats T_spk as the leading axis, so substep s of
     * timestep t lives at index (s * T + t) along that axis.
     */
    for (int t = 0; t < T; t++) {
        for (int c = 0; c < C_cat; c++) {
            for (int sp = 0; sp < spatial; sp++) {
                SA_PIPELINE_II(1)
                sa_i32_t acc = 0;
                for (int s = 0; s < SA_MAX_SPIKE; s++) {
                    const int src_t = s * T + t;
                    acc += (sa_i32_t)concat_buf[((src_t * C_cat + c) * H + sp / W) * W + (sp % W)];
                }
                cat_i32_buf[((t * C_cat + c) * H + sp / W) * W + (sp % W)] = acc;
            }
        }
    }

    /* Stage 6: cv2 (1x1, C_cat -> C_out). y_out = ms_standard_conv(cat_i32_buf, cv2). */
    sa_ms_standard_conv_inplace(cat_i32_buf, y_out,
                                cv2_w, cv2_b, cv2_s,
                                spike_buf, tmp_acc,
                                T, C_cat, C_out, H, W,
                                /*K=*/1, /*stride=*/1, /*pad=*/0, /*groups=*/1);
}

}  /* extern "C" */
