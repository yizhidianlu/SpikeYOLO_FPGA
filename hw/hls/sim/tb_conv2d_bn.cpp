/*
 * hw/hls/sim/tb_conv2d_bn.cpp — DUT vs reference for sa_conv2d_bn.
 */

#include "dtypes.h"
#include "reference.hpp"

#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

extern "C" void sa_conv2d_bn(
    const sa_i8_t  *x,
          sa_i32_t *y,
    const sa_i8_t  *w,
    const sa_i32_t *bias,
    const sa_i8_t  *out_shift,
          sa_i32_t *tmp_acc,
    int T_in, int C_in, int C_out, int H, int W,
    int K, int stride, int pad, int groups, int first_layer);


struct CaseCfg {
    const char *name;
    int T_in, C_in, C_out, H, W;
    int K, stride, pad, groups;
    bool first_layer;
};


static int run_case(const CaseCfg &c) {
    std::mt19937 rng(0xABCD ^ c.K ^ (c.C_in << 8) ^ (c.first_layer ? 1 : 0));
    std::uniform_int_distribution<int> w_d(-50, 50);
    std::uniform_int_distribution<int> x_d(-128, 127);
    std::uniform_int_distribution<int> b_d(-2000, 2000);
    std::uniform_int_distribution<int> s_d(2, 6);

    const int H_out = (c.H + 2 * c.pad - c.K) / c.stride + 1;
    const int W_out = (c.W + 2 * c.pad - c.K) / c.stride + 1;
    const int T_out = c.first_layer ? c.T_in : c.T_in / SA_MAX_SPIKE;

    std::vector<sa_i8_t>  x((size_t)c.T_in * c.C_in * c.H * c.W);
    std::vector<sa_i8_t>  w((size_t)c.C_out * (c.C_in / c.groups) * c.K * c.K);
    std::vector<sa_i32_t> bias(c.C_out);
    std::vector<sa_i8_t>  oshift(c.C_out);
    for (auto &v : x) v = (sa_i8_t)(c.first_layer ? x_d(rng) : (rng() & 1));
    for (auto &v : w) v = (sa_i8_t)w_d(rng);
    for (auto &v : bias) v = b_d(rng);
    for (auto &v : oshift) v = (sa_i8_t)s_d(rng);

    auto y_ref = sa_ref::conv2d_bn(
        reinterpret_cast<const int8_t *>(x.data()),
        reinterpret_cast<const int8_t *>(w.data()),
        reinterpret_cast<const int32_t *>(bias.data()),
        reinterpret_cast<const int8_t  *>(oshift.data()),
        c.T_in, c.C_in, c.C_out, c.H, c.W,
        c.K, c.stride, c.pad, c.groups,
        c.first_layer);

    std::vector<sa_i32_t> y_dut((size_t)T_out * c.C_out * H_out * W_out, 0);
    std::vector<sa_i32_t> tmp((size_t)c.T_in * c.C_out * H_out * W_out, 0);
    sa_conv2d_bn(x.data(), y_dut.data(), w.data(),
                 bias.data(), oshift.data(), tmp.data(),
                 c.T_in, c.C_in, c.C_out, c.H, c.W,
                 c.K, c.stride, c.pad, c.groups,
                 c.first_layer ? 1 : 0);

    int bad = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != y_ref[i]) {
            if (bad < 10) std::fprintf(stderr,
                "[%s] mismatch @ i=%zu  dut=%d  ref=%d\n",
                c.name, i, (int)y_dut[i], (int)y_ref[i]);
            bad++;
        }
    }
    if (bad) {
        std::fprintf(stderr, "[%s] FAILED with %d mismatches\n", c.name, bad);
        return 1;
    }
    std::fprintf(stdout, "[%s] OK\n", c.name);
    return 0;
}


int main()
{
    CaseCfg cases[] = {
        /* name              T_in C_in C_out H  W  K stride pad groups first_layer */
        {"first_stem",        1,  3,  24,  16, 16, 7, 4, 2, 1, true},
        {"acb_pw",            4, 24,  48,  16, 16, 1, 1, 0, 1, false},   /* 4 substeps */
        {"acb_dw",            4, 24,  24,  16, 16, 3, 1, 1, 24, false},  /* depth-wise */
        {"sppf_cv",           4, 16,  16,   8,  8, 1, 1, 0, 1, false},
    };
    int rc = 0;
    for (const auto &c : cases) rc |= run_case(c);
    if (rc) { std::fprintf(stdout, "CSIM FAIL\n"); return 1; }
    std::fprintf(stdout, "CSIM PASS\n");
    return 0;
}
