/*
 * hw/hls/sim/reference.hpp — header-only NumPy-equivalent reference for
 * every HLS algorithm in this project.
 *
 * Each function is paired with a DUT in src/(name).cpp. Testbenches in
 * sim/tb_(name).cpp
 * generate randomized inputs, run the DUT, then call the matching sa_ref::
 * helper here to produce the golden output, and assert byte equality.
 */

#ifndef SA_HLS_SIM_REFERENCE_HPP
#define SA_HLS_SIM_REFERENCE_HPP

#include <cstdint>
#include <vector>
/* Intentionally NOT including <algorithm> — m2w64-gcc 5.3.0 ICEs on the
 * <limits> chain pulled in transitively. Tiny inline helpers below replace
 * the only std::min / std::max we need (clamp). */

#include "dtypes.h"

namespace sa_ref {

/* --------------------------------------------------------------------------
 * conv2d_int — numpy_reference.conv2d_int line-for-line.
 * -------------------------------------------------------------------------- */
inline std::vector<int32_t> conv2d_int(
    const int8_t *x,
    const int8_t *w,
    int N, int C_in, int C_out, int H, int W,
    int K, int stride, int pad, int groups)
{
    const int C_in_g  = C_in  / groups;
    const int C_out_g = C_out / groups;
    const int H_out   = (H + 2 * pad - K) / stride + 1;
    const int W_out   = (W + 2 * pad - K) / stride + 1;
    std::vector<int32_t> y((size_t)N * C_out * H_out * W_out, 0);

    for (int n = 0; n < N; n++) {
        for (int g = 0; g < groups; g++) {
            const int co_lo = g * C_out_g;
            const int co_hi = co_lo + C_out_g;
            const int ci_lo = g * C_in_g;
            for (int co = co_lo; co < co_hi; co++) {
                for (int hy = 0; hy < H_out; hy++) {
                    for (int wx = 0; wx < W_out; wx++) {
                        int32_t acc = 0;
                        for (int ci = 0; ci < C_in_g; ci++) {
                            for (int ky = 0; ky < K; ky++) {
                                for (int kx = 0; kx < K; kx++) {
                                    const int h_in = hy * stride + ky - pad;
                                    const int w_in = wx * stride + kx - pad;
                                    int32_t px = 0;
                                    if (h_in >= 0 && h_in < H && w_in >= 0 && w_in < W) {
                                        px = x[((n * C_in + ci_lo + ci) * H + h_in) * W + w_in];
                                    }
                                    const int32_t wt = w[((co * C_in_g) + ci) * K * K + ky * K + kx];
                                    acc += px * wt;
                                }
                            }
                        }
                        y[((n * C_out + co) * H_out + hy) * W_out + wx] = acc;
                    }
                }
            }
        }
    }
    return y;
}


/* --------------------------------------------------------------------------
 * conv2d_bn — numpy_reference.conv2d_bn line-for-line.
 *
 * Returns the int32 pre-LIF feature map of shape [T_out, C_out, H_out, W_out].
 * `first_layer = true` keeps T_in unchanged; otherwise T_out = T_in / MAX_SPIKE.
 * -------------------------------------------------------------------------- */
inline std::vector<int32_t> conv2d_bn(
    const int8_t  *x,
    const int8_t  *w,
    const int32_t *bias,
    const int8_t  *out_shift,
    int T_in, int C_in, int C_out, int H, int W,
    int K, int stride, int pad, int groups,
    bool first_layer)
{
    auto acc = conv2d_int(x, w, T_in, C_in, C_out, H, W,
                          K, stride, pad, groups);
    const int H_out = (H + 2 * pad - K) / stride + 1;
    const int W_out = (W + 2 * pad - K) / stride + 1;

    int T_out;
    if (first_layer) {
        T_out = T_in;
    } else {
        T_out = T_in / SA_MAX_SPIKE;
        std::vector<int32_t> collapsed((size_t)T_out * C_out * H_out * W_out, 0);
        for (int sub = 0; sub < SA_MAX_SPIKE; sub++) {
            for (int t = 0; t < T_out; t++) {
                const int src_t = sub * T_out + t;
                for (int co = 0; co < C_out; co++) {
                    for (int hw_ = 0; hw_ < H_out * W_out; hw_++) {
                        collapsed[((t * C_out + co) * H_out * W_out) + hw_] +=
                            acc[((src_t * C_out + co) * H_out * W_out) + hw_];
                    }
                }
            }
        }
        acc.swap(collapsed);
    }

    /* Bias + per-channel right-shift. */
    for (int t = 0; t < T_out; t++) {
        for (int co = 0; co < C_out; co++) {
            const int32_t b = bias[co];
            const int s = (int)out_shift[co];
            for (int hw_ = 0; hw_ < H_out * W_out; hw_++) {
                const int idx = ((t * C_out + co) * H_out * W_out) + hw_;
                int32_t v = acc[idx] + b;
                /* C++ right-shift on negatives is implementation-defined for
                 * standard ints but matches arithmetic shift on x86/ARM (GCC + clang). */
                v = v >> s;
                acc[idx] = v;
            }
        }
    }
    return acc;
}


/* --------------------------------------------------------------------------
 * lif_expand — numpy_reference.mem_update + expand_cumulative.
 *
 * Input  : int32 [T, C, H, W]
 * Output : int8  [MAX_SPIKE, C, H, W]  values in {0, 1}
 * (MAX_SPIKE * T_in for multi-step models; tiny_fpga has T=1 so output T=4.)
 * -------------------------------------------------------------------------- */
inline std::vector<int8_t> lif_expand(
    const int32_t *x, int T, int C, int H, int W)
{
    std::vector<int8_t> out((size_t)SA_MAX_SPIKE * C * H * W, 0);
    for (int c = 0; c < C; c++) {
        for (int sp = 0; sp < H * W; sp++) {
            int32_t mem = 0;
            for (int t = 0; t < T; t++) {
                mem += x[((t * C + c) * H * W) + sp];
            }
            int32_t v = (mem < 0) ? 0
                       : (mem > (int32_t)SA_MAX_SPIKE) ? (int32_t)SA_MAX_SPIKE
                       : mem;
            for (int s = 0; s < SA_MAX_SPIKE; s++) {
                out[((s * C + c) * H * W) + sp] = (s < v) ? 1 : 0;
            }
        }
    }
    return out;
}

/* --------------------------------------------------------------------------
 * ms_downsampling — numpy_reference.ms_downsampling line-for-line.
 *
 * This is the composite operator the HLS top calls for stem-style layers.
 *
 *   first_layer = true   (stem):
 *      input  : int8  [T_in=1, C_in, H, W]    (raw INT8 RGB)
 *      output : int32 [T_in,   C_out, H/stride, W/stride]
 *
 *   first_layer = false  (inner downsampling):
 *      input  : int32 [T,      C_in, H, W]    (pre-LIF)
 *      output : int32 [T,      C_out, H/stride, W/stride]
 *
 * The HLS golden tensors in tests/golden/layer_*.npz store the *post-shift*
 * int32 feature map for the stem (no following LIF), matching this output.
 * -------------------------------------------------------------------------- */
inline std::vector<int32_t> ms_downsampling(
    const int8_t  *x_i8,                   /* used iff first_layer */
    const int32_t *x_i32,                  /* used iff !first_layer */
    const int8_t  *w,
    const int32_t *bias,
    const int8_t  *out_shift,
    int T_in, int C_in, int C_out, int H, int W,
    int K, int stride, int pad, int groups,
    bool first_layer)
{
    if (first_layer) {
        return conv2d_bn(x_i8, w, bias, out_shift,
                         T_in, C_in, C_out, H, W,
                         K, stride, pad, groups, /*first_layer=*/true);
    }
    /* Non-stem path: run LIF first to expand T_in -> T_in*MAX_SPIKE binary
     * spikes, then run conv2d_bn with first_layer=false (which collapses the
     * 4 substeps back to T_in time steps before bias+shift).
     */
    auto spk = lif_expand(x_i32, T_in, C_in, H, W);   /* int8 [MAX_SPIKE, C, H, W] */
    return conv2d_bn(spk.data(), w, bias, out_shift,
                     SA_MAX_SPIKE * T_in, C_in, C_out, H, W,
                     K, stride, pad, groups, /*first_layer=*/false);
}

/* --------------------------------------------------------------------------
 * ms_standard_conv — numpy_reference.ms_standard_conv. Always non-first-layer:
 *   spk = mem_update(x_i32)
 *   y   = conv2d_bn(spk, params)
 * -------------------------------------------------------------------------- */
inline std::vector<int32_t> ms_standard_conv(
    const int32_t *x_i32,
    const int8_t  *w,
    const int32_t *bias,
    const int8_t  *out_shift,
    int T_in, int C_in, int C_out, int H, int W,
    int K, int stride, int pad, int groups)
{
    auto spk = lif_expand(x_i32, T_in, C_in, H, W);
    return conv2d_bn(spk.data(), w, bias, out_shift,
                     SA_MAX_SPIKE * T_in, C_in, C_out, H, W,
                     K, stride, pad, groups, /*first_layer=*/false);
}


/* --------------------------------------------------------------------------
 * sep_conv — numpy_reference.sep_conv (4 sequential ms_standard_conv stages).
 *
 * Channel pattern: C -> C_exp -> C_exp -> C -> C  (spatial preserved).
 * -------------------------------------------------------------------------- */
struct ConvBnW {
    const int8_t  *w;
    const int32_t *bias;
    const int8_t  *out_shift;
    int K;
    int stride;
    int pad;
    int groups;
};

inline std::vector<int32_t> sep_conv(
    const int32_t *x,
    const ConvBnW &pwconv1,   /* 1x1, C -> C_exp,  g=1                 */
    const ConvBnW &dwconv2,   /* k_dw x k_dw, depth-wise on C_exp      */
    const ConvBnW &pwconv3,   /* 1x1, C_exp -> C, g=1                  */
    const ConvBnW &dwconv4,   /* 3x3 (typically), depth-wise on C      */
    int T, int C, int C_exp, int H, int W)
{
    auto y1 = ms_standard_conv(x, pwconv1.w, pwconv1.bias, pwconv1.out_shift,
                               T, C, C_exp, H, W,
                               pwconv1.K, pwconv1.stride, pwconv1.pad, pwconv1.groups);
    auto y2 = ms_standard_conv(y1.data(), dwconv2.w, dwconv2.bias, dwconv2.out_shift,
                               T, C_exp, C_exp, H, W,
                               dwconv2.K, dwconv2.stride, dwconv2.pad, dwconv2.groups);
    auto y3 = ms_standard_conv(y2.data(), pwconv3.w, pwconv3.bias, pwconv3.out_shift,
                               T, C_exp, C, H, W,
                               pwconv3.K, pwconv3.stride, pwconv3.pad, pwconv3.groups);
    auto y4 = ms_standard_conv(y3.data(), dwconv4.w, dwconv4.bias, dwconv4.out_shift,
                               T, C, C, H, W,
                               dwconv4.K, dwconv4.stride, dwconv4.pad, dwconv4.groups);
    return y4;
}


/* --------------------------------------------------------------------------
 * ms_all_conv_block — numpy_reference.ms_all_conv_block:
 *
 *   x  <- sep_conv(x, sep) + x          // residual 1
 *   xf <- x  (saved)
 *   x  <- ms_standard_conv(x, conv1)
 *   x  <- ms_standard_conv(x, conv2)
 *   y  <- x + xf                        // residual 2
 *
 * conv1 / conv2 in tiny_fpga are 1x1 stride 1 pad 0 groups 1, channel C->C.
 * -------------------------------------------------------------------------- */
inline std::vector<int32_t> ms_all_conv_block(
    const int32_t *x_in,
    const ConvBnW &pwconv1, const ConvBnW &dwconv2,
    const ConvBnW &pwconv3, const ConvBnW &dwconv4,
    const ConvBnW &conv1,   const ConvBnW &conv2,
    int T, int C, int C_exp, int C_mid, int H, int W)
{
    const size_t n_elem = (size_t)T * C * H * W;

    /* x = sep_conv(x_in) + x_in   (residual 1) */
    auto x = sep_conv(x_in, pwconv1, dwconv2, pwconv3, dwconv4, T, C, C_exp, H, W);
    for (size_t i = 0; i < n_elem; i++) x[i] += x_in[i];

    /* xf = x */
    std::vector<int32_t> x_feat(x);

    /* conv1: C -> C_mid */
    auto a = ms_standard_conv(x.data(), conv1.w, conv1.bias, conv1.out_shift,
                              T, C, C_mid, H, W,
                              conv1.K, conv1.stride, conv1.pad, conv1.groups);
    /* conv2: C_mid -> C */
    auto b = ms_standard_conv(a.data(), conv2.w, conv2.bias, conv2.out_shift,
                              T, C_mid, C, H, W,
                              conv2.K, conv2.stride, conv2.pad, conv2.groups);

    /* y = b + xf */
    for (size_t i = 0; i < n_elem; i++) b[i] += x_feat[i];
    return b;
}


/* --------------------------------------------------------------------------
 * maxpool_or — numpy_reference.maxpool2d_spike (binary {0,1}, k x k, stride 1,
 * same-padding). For 0/1 input this is equivalent to k x k max.
 * -------------------------------------------------------------------------- */
inline std::vector<int8_t> maxpool_or(
    const int8_t *x, int T, int C, int H, int W, int K)
{
    const int pad = K / 2;
    std::vector<int8_t> y((size_t)T * C * H * W, 0);
    for (int t = 0; t < T; t++) {
        for (int c = 0; c < C; c++) {
            for (int hy = 0; hy < H; hy++) {
                for (int wx = 0; wx < W; wx++) {
                    int8_t acc = 0;
                    for (int ky = 0; ky < K; ky++) {
                        for (int kx = 0; kx < K; kx++) {
                            const int hi = hy + ky - pad;
                            const int wi = wx + kx - pad;
                            if (hi >= 0 && hi < H && wi >= 0 && wi < W) {
                                int8_t v = x[((t * C + c) * H + hi) * W + wi];
                                if (v > acc) acc = v;
                            }
                        }
                    }
                    y[((t * C + c) * H + hy) * W + wx] = acc;
                }
            }
        }
    }
    return y;
}


/* --------------------------------------------------------------------------
 * spike_sppf — numpy_reference.spike_sppf:
 *   x   = ms_standard_conv(x_in, cv1)        [T, C_mid, H, W]  int32
 *   spk = mem_update(x)                      int8 [T*MAX_SPIKE, C_mid, H, W]
 *   y1..y3 = cascaded maxpool(spk, k)
 *   cat   = concat([spk, y1, y2, y3], axis=C)  int8 [T*MAX_SPIKE, 4*C_mid, H, W]
 *   cat_i32 = collapse MAX_SPIKE substeps     int32 [T, 4*C_mid, H, W]
 *   y_out  = ms_standard_conv(cat_i32, cv2)   [T, C_out, H, W]
 * -------------------------------------------------------------------------- */
inline std::vector<int32_t> spike_sppf(
    const int32_t *x_in,
    const ConvBnW &cv1, const ConvBnW &cv2,
    int T, int C_in, int C_mid, int C_out, int H, int W, int k)
{
    auto cv1_out = ms_standard_conv(x_in, cv1.w, cv1.bias, cv1.out_shift,
                                    T, C_in, C_mid, H, W,
                                    cv1.K, cv1.stride, cv1.pad, cv1.groups);

    /* spk = mem_update(cv1_out): int8 [T*MAX_SPIKE, C_mid, H, W] */
    auto spk = lif_expand(cv1_out.data(), T, C_mid, H, W);
    const int T_spk = T * SA_MAX_SPIKE;

    auto y1 = maxpool_or(spk.data(), T_spk, C_mid, H, W, k);
    auto y2 = maxpool_or(y1.data(),  T_spk, C_mid, H, W, k);
    auto y3 = maxpool_or(y2.data(),  T_spk, C_mid, H, W, k);

    /* concat along channel axis */
    const int C_cat = 4 * C_mid;
    const int spatial = H * W;
    std::vector<int8_t> cat((size_t)T_spk * C_cat * spatial, 0);
    const int8_t *srcs[4] = { spk.data(), y1.data(), y2.data(), y3.data() };
    for (int t = 0; t < T_spk; t++) {
        for (int b = 0; b < 4; b++) {
            for (int c = 0; c < C_mid; c++) {
                for (int sp = 0; sp < spatial; sp++) {
                    cat[((t * C_cat + b * C_mid + c) * spatial) + sp] =
                        srcs[b][((t * C_mid + c) * spatial) + sp];
                }
            }
        }
    }

    /* collapse MAX_SPIKE substeps: cat layout is [sub * T + t, c, sp]. */
    std::vector<int32_t> cat_i32((size_t)T * C_cat * spatial, 0);
    for (int t = 0; t < T; t++) {
        for (int c = 0; c < C_cat; c++) {
            for (int sp = 0; sp < spatial; sp++) {
                int32_t acc = 0;
                for (int s = 0; s < SA_MAX_SPIKE; s++) {
                    const int src_t = s * T + t;
                    acc += (int32_t)cat[((src_t * C_cat + c) * spatial) + sp];
                }
                cat_i32[((t * C_cat + c) * spatial) + sp] = acc;
            }
        }
    }

    return ms_standard_conv(cat_i32.data(), cv2.w, cv2.bias, cv2.out_shift,
                            T, C_cat, C_out, H, W,
                            cv2.K, cv2.stride, cv2.pad, cv2.groups);
}

}  /* namespace sa_ref */

#endif
