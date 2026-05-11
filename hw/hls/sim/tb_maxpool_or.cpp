/*
 * hw/hls/sim/tb_maxpool_or.cpp — DUT vs reference for sa_maxpool_or.
 */

#include "dtypes.h"
#include "reference.hpp"

#include <algorithm>
#include <cstdio>
#include <random>
#include <vector>

extern "C" void sa_maxpool_or(
    const sa_i8_t *x_in, sa_i8_t *y_out,
    int T, int C, int H, int W, int K);


namespace sa_ref {

/* Mirrors numpy_reference.maxpool2d_spike (k×k, stride 1, same padding). */
inline std::vector<int8_t> maxpool2d_spike(const int8_t *x, int T, int C,
                                           int H, int W, int K)
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
                            const int h_in = hy + ky - pad;
                            const int w_in = wx + kx - pad;
                            if (h_in >= 0 && h_in < H && w_in >= 0 && w_in < W) {
                                const int8_t v = x[((t * C + c) * H + h_in) * W + w_in];
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

}


struct CaseCfg {
    const char *name;
    int T, C, H, W, K;
};


static int run_case(const CaseCfg &c) {
    std::mt19937 rng(0xBEEF ^ c.K ^ (c.C << 4));
    std::bernoulli_distribution bit(0.3);

    std::vector<sa_i8_t> x((size_t)c.T * c.C * c.H * c.W);
    for (auto &v : x) v = bit(rng) ? 1 : 0;

    auto y_ref = sa_ref::maxpool2d_spike(
        reinterpret_cast<const int8_t *>(x.data()),
        c.T, c.C, c.H, c.W, c.K);

    std::vector<sa_i8_t> y_dut(y_ref.size(), 0);
    sa_maxpool_or(x.data(), y_dut.data(), c.T, c.C, c.H, c.W, c.K);

    int bad = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if (y_dut[i] != y_ref[i]) {
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
    std::fprintf(stdout, "[%s] OK  shape=(%d,%d,%d,%d)  K=%d\n",
                 c.name, c.T, c.C, c.H, c.W, c.K);
    return 0;
}


int main()
{
    CaseCfg cases[] = {
        /* name        T  C   H   W   K */
        {"sppf_k5",     4, 48, 16, 16, 5},
        {"small_k3",    1, 16,  8,  8, 3},
        {"big_k7",      4, 32, 32, 32, 7},
    };
    int rc = 0;
    for (const auto &c : cases) rc |= run_case(c);
    if (rc) { std::fprintf(stdout, "CSIM FAIL\n"); return 1; }
    std::fprintf(stdout, "CSIM PASS\n");
    return 0;
}
