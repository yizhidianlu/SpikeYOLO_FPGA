/*
 * hw/hls/sim/test_op_macros.cpp — W6 host-side unit test for include/op_macros.h.
 *
 * Covers the two static-inline helpers shared between the W3 block-level
 * kernels (sep_conv / ms_all_conv_block / spike_sppf):
 *
 *   1. sa_ms_standard_conv_inplace — LIF expand + conv2d_bn fused path.
 *   2. sa_residual_add_i32         — element-wise int32 add.
 *
 * Hard-coded inputs, no .npz dependency. Prints PASS / FAIL and returns
 * 0 / 1 so the Makefile `host_csim_macros` target can check exit status.
 *
 * Build via `mingw32-make -C hw/hls host_csim_macros` — links in
 * src/{conv2d_bn,conv2d_int,lif_expand}.cpp because the macros funnel
 * through their extern "C" entry points.
 */

#include "dtypes.h"
#include "op_macros.h"

#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>

/* ---------------------------------------------------------------------------
 * Test 1: sa_ms_standard_conv_inplace
 *
 * Geometry: T_in=1, C_in=2, C_out=1, H=W=2, K=1 (1x1 conv), stride=1, pad=0.
 *
 * Input  x_i32 [1,2,2,2] = all 4 (each spatial cell on each channel is 4 -> LIF
 * clamps to MAX_SPIKE=4 -> expand_cumulative yields 4 binary substeps all = 1).
 * Weight w [1,2,1,1] = {1, 1}.  Bias = 0. out_shift = 0 -> >>0 = identity.
 *
 * Expected (matches numpy_reference + the W3 sep_conv host_csim flow):
 *   conv accum per cell = sum over substep (4) * sum over C_in (2) * w (1) = 8.
 * So y_i32 [1,1,2,2] = all 8 on every cell.
 * ------------------------------------------------------------------------- */
static int test_ms_standard_conv_inplace()
{
    const int T_in  = 1;
    const int C_in  = 2;
    const int C_out = 1;
    const int H = 2, W = 2;
    const int K = 1, stride = 1, pad = 0, groups = 1;

    const int n_in  = T_in * C_in  * H * W;       /* 8           */
    const int n_out = T_in * C_out * H * W;       /* 4           */
    const int n_spk = T_in * SA_MAX_SPIKE * C_in * H * W;  /* 32 */
    const int n_w   = C_out * C_in * K * K;       /* 2           */

    std::vector<sa_i32_t> x(n_in,  4);            /* clamp to MAX_SPIKE=4 */
    std::vector<sa_i32_t> y(n_out, 0);
    std::vector<sa_i8_t>  w(n_w,   1);
    std::vector<sa_i32_t> bias(C_out, 0);
    std::vector<sa_i8_t>  out_shift(C_out, 0);
    std::vector<sa_i8_t>  spike_buf(n_spk, 0);
    std::vector<sa_i32_t> tmp_acc(T_in * SA_MAX_SPIKE * C_out * H * W, 0);

    sa_ms_standard_conv_inplace(
        x.data(), y.data(), w.data(), bias.data(), out_shift.data(),
        spike_buf.data(), tmp_acc.data(),
        T_in, C_in, C_out, H, W, K, stride, pad, groups);

    /* Each output cell = sum_substep(4) * sum_C_in(2) * w(1) = 8 */
    int fails = 0;
    for (int i = 0; i < n_out; i++) {
        if (y[i] != 8) {
            printf("  cell[%d] expected 8 got %d\n", i, (int)y[i]);
            fails++;
        }
    }

    /* Sanity: spike_buf is binary-expanded -> at MAX_SPIKE=4, every cell == 1. */
    for (int i = 0; i < n_spk; i++) {
        if (spike_buf[i] != 1) {
            printf("  spike_buf[%d] expected 1 got %d\n", i, (int)spike_buf[i]);
            fails++;
            if (fails > 4) break;
        }
    }
    return fails;
}


/* ---------------------------------------------------------------------------
 * Test 2: sa_residual_add_i32
 *
 * dst[0..N-1] := dst + src element-wise, in place. N=16 to cover the typical
 * residual buffer length per spatial tile.
 * ------------------------------------------------------------------------- */
static int test_residual_add_i32()
{
    const int N = 16;
    std::vector<sa_i32_t> dst(N), src(N), gold(N);

    for (int i = 0; i < N; i++) {
        dst[i]  = i;             /* 0, 1, 2, ...                              */
        src[i]  = N - i;         /* 16, 15, 14, ... 1                          */
        gold[i] = dst[i] + src[i];  /* constant N (= 16) on every cell        */
    }

    sa_residual_add_i32(dst.data(), src.data(), N);

    int fails = 0;
    for (int i = 0; i < N; i++) {
        if (dst[i] != gold[i]) {
            printf("  dst[%d] expected %d got %d\n", i, (int)gold[i], (int)dst[i]);
            fails++;
        }
    }
    /* Spot-check a couple of edge cells. */
    assert(dst[0]  == N);
    assert(dst[N-1] == N);
    return fails;
}


int main()
{
    int fails = 0;

    printf("[test_op_macros] sa_ms_standard_conv_inplace ... ");
    int f1 = test_ms_standard_conv_inplace();
    printf("%s\n", f1 == 0 ? "PASS" : "FAIL");
    fails += f1;

    printf("[test_op_macros] sa_residual_add_i32        ... ");
    int f2 = test_residual_add_i32();
    printf("%s\n", f2 == 0 ? "PASS" : "FAIL");
    fails += f2;

    if (fails == 0) {
        printf("[test_op_macros] ALL PASS\n");
        return 0;
    }
    printf("[test_op_macros] %d failure(s)\n", fails);
    return 1;
}
