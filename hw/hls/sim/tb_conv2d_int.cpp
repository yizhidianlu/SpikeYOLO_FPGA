/*
 * hw/hls/sim/tb_conv2d_int.cpp — DUT vs reference testbench for sa_conv2d_int.
 *
 * Build modes:
 *   - native g++ smoke (no Vitis):   g++ -std=c++17 -O2 -I../include -Isim \
 *                                       sim/tb_conv2d_int.cpp src/conv2d_int.cpp
 *   - Vitis HLS C-sim:               vitis_hls -f run_csim.tcl
 *
 * On success prints "CSIM PASS" to stdout. Failure prints the first 10
 * mismatch indices and exits with code 1.
 */

#include "dtypes.h"
#include "reference.hpp"
#include "npz_reader.h"

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>

extern "C" void sa_conv2d_int(
    const sa_i8_t  *x,
          sa_i32_t *y,
    const sa_i8_t  *w,
    int N, int C_in, int C_out, int H, int W,
    int K, int stride, int pad, int groups);


struct CaseCfg {
    const char *name;
    int N, C_in, C_out, H, W, K, stride, pad, groups;
};

static int run_case(const CaseCfg &c) {
    std::mt19937 rng(0xC0FFEE ^ c.K ^ (c.C_in << 8));
    std::uniform_int_distribution<int> w_dist(-100, 100);
    std::uniform_int_distribution<int> x_dist(-128, 127);

    const int H_out = (c.H + 2 * c.pad - c.K) / c.stride + 1;
    const int W_out = (c.W + 2 * c.pad - c.K) / c.stride + 1;

    std::vector<sa_i8_t> x((size_t)c.N * c.C_in * c.H * c.W);
    std::vector<sa_i8_t> w((size_t)c.C_out * (c.C_in / c.groups) * c.K * c.K);
    for (auto &v : x) v = (sa_i8_t)x_dist(rng);
    for (auto &v : w) v = (sa_i8_t)w_dist(rng);

    /* Reference using header-only impl */
    auto y_ref = sa_ref::conv2d_int(
        reinterpret_cast<const int8_t *>(x.data()),
        reinterpret_cast<const int8_t *>(w.data()),
        c.N, c.C_in, c.C_out, c.H, c.W,
        c.K, c.stride, c.pad, c.groups);

    /* DUT */
    std::vector<sa_i32_t> y_dut((size_t)c.N * c.C_out * H_out * W_out, 0);
    sa_conv2d_int(x.data(), y_dut.data(), w.data(),
                  c.N, c.C_in, c.C_out, c.H, c.W,
                  c.K, c.stride, c.pad, c.groups);

    /* Compare */
    int mismatches = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        sa_i32_t a = y_dut[i];
        int32_t  b = y_ref[i];
        if ((int32_t)a != b) {
            if (mismatches < 10) {
                std::fprintf(stderr,
                    "[%s] mismatch @ i=%zu  dut=%d  ref=%d\n",
                    c.name, i, (int)a, (int)b);
            }
            mismatches++;
        }
    }
    if (mismatches != 0) {
        std::fprintf(stderr, "[%s] FAILED with %d mismatches (out of %zu)\n",
                     c.name, mismatches, y_ref.size());
        return 1;
    }
    std::fprintf(stdout, "[%s] OK  shape=(%d,%d,%d,%d) -> (%d,%d,%d,%d)\n",
                 c.name, c.N, c.C_in, c.H, c.W, c.N, c.C_out, H_out, W_out);
    return 0;
}


/* Run the conv portion of layer_00 (stem) using A1 INT8 weights and the A2
 * input tensor. We compare DUT to the header-only reference implementation —
 * NOT to the golden output because the golden also has bias + shift applied.
 * That end-to-end compare lives in tb_ms_downsampling.cpp.
 */
static int run_layer_00_stem_conv()
{
    const std::string golden_dir = "tests/golden/exploded/layer_00_stem";
    const std::string weight_dir = "models/exploded";
    sa_npz::Tensor t_in, t_w;
    try {
        t_in = sa_npz::load_npy_member(golden_dir, "input");
        t_w  = sa_npz::load_npy(weight_dir + "/L00.w.npy");
    } catch (const std::exception &e) {
        std::fprintf(stderr,
            "[stem_real] skipping (load failed: %s) — run "
            "tools/ci/explode_npz.py first\n", e.what());
        return 0;     /* not a hard fail; allows random-only smoke runs */
    }
    const int N = 1, C_in = 3, C_out = 24;
    const int H = 256, W = 256, K = 7, stride = 4, pad = 2, groups = 1;
    const int H_out = (H + 2 * pad - K) / stride + 1;
    const int W_out = (W + 2 * pad - K) / stride + 1;
    if ((int)t_in.shape.size() != 4 || (int)t_w.shape.size() != 4 ||
        t_in.shape[1]  != C_in || t_in.shape[2]  != H || t_in.shape[3]  != W ||
        t_w.shape[0]   != C_out || t_w.shape[1] != C_in ||
        t_w.shape[2]   != K     || t_w.shape[3] != K) {
        std::fprintf(stderr, "[stem_real] unexpected shapes\n");
        return 1;
    }

    auto y_ref = sa_ref::conv2d_int(
        t_in.as_i8(), t_w.as_i8(),
        N, C_in, C_out, H, W, K, stride, pad, groups);

    std::vector<sa_i32_t> y_dut((size_t)N * C_out * H_out * W_out, 0);
    sa_conv2d_int(
        reinterpret_cast<const sa_i8_t *>(t_in.bytes.data()),
        y_dut.data(),
        reinterpret_cast<const sa_i8_t *>(t_w.bytes.data()),
        N, C_in, C_out, H, W, K, stride, pad, groups);

    int bad = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != y_ref[i]) {
            if (bad < 10) std::fprintf(stderr,
                "[stem_real] mismatch @ i=%zu  dut=%d  ref=%d\n",
                i, (int)y_dut[i], (int)y_ref[i]);
            bad++;
        }
    }
    if (bad) {
        std::fprintf(stderr, "[stem_real] FAILED with %d mismatches\n", bad);
        return 1;
    }
    std::fprintf(stdout, "[stem_real] OK  (%zu elems via real golden + A1 weights)\n",
                 y_ref.size());
    return 0;
}


int main() {
    /* A few sizes spanning the tiny_fpga topology */
    CaseCfg cases[] = {
        /* name           N C_in C_out H  W  K stride pad groups */
        {"stem_3to24",    1,  3,  24,  32, 32, 7, 4, 2, 1},   /* downsampled stem-ish */
        {"pw_24to48",     1, 24,  48,  16, 16, 1, 1, 0, 1},
        {"dw_48to48",     1, 48,  48,  16, 16, 3, 1, 1, 48},  /* depth-wise */
        {"head_1x1",      1, 96,  84,   8,  8, 1, 1, 0, 1},
    };
    int rc = 0;
    for (const auto &c : cases) rc |= run_case(c);
    rc |= run_layer_00_stem_conv();
    if (rc) {
        std::fprintf(stdout, "CSIM FAIL\n");
        return 1;
    }
    std::fprintf(stdout, "CSIM PASS\n");
    return 0;
}
