/*
 * hw/hls/sim/tb_lif_expand.cpp — DUT vs reference for sa_lif_expand.
 */

#include "dtypes.h"
#include "reference.hpp"

#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

extern "C" void sa_lif_expand(
    const sa_i32_t *x_in,
          sa_i8_t  *spike_out,
    int T, int C, int H, int W);


struct CaseCfg {
    const char *name;
    int T, C, H, W;
};


static int run_case(const CaseCfg &c) {
    std::mt19937 rng(0xDEAD ^ c.C ^ (c.H << 8));
    std::uniform_int_distribution<int> x_d(-10, 10);    /* span both saturation rails */

    std::vector<sa_i32_t> x((size_t)c.T * c.C * c.H * c.W);
    for (auto &v : x) v = x_d(rng);

    auto out_ref = sa_ref::lif_expand(
        reinterpret_cast<const int32_t *>(x.data()),
        c.T, c.C, c.H, c.W);

    std::vector<sa_i8_t> out_dut((size_t)SA_MAX_SPIKE * c.C * c.H * c.W, 0);
    sa_lif_expand(x.data(), out_dut.data(),
                  c.T, c.C, c.H, c.W);

    int bad = 0;
    for (size_t i = 0; i < out_ref.size(); i++) {
        if (out_dut[i] != out_ref[i]) {
            if (bad < 10) std::fprintf(stderr,
                "[%s] mismatch @ i=%zu  dut=%d  ref=%d\n",
                c.name, i, (int)out_dut[i], (int)out_ref[i]);
            bad++;
        }
    }
    if (bad) {
        std::fprintf(stderr, "[%s] FAILED with %d mismatches\n", c.name, bad);
        return 1;
    }
    std::fprintf(stdout, "[%s] OK shape=(%d, %d, %d, %d)\n", c.name,
                 SA_MAX_SPIKE, c.C, c.H, c.W);
    return 0;
}


int main()
{
    CaseCfg cases[] = {
        /* name        T  C   H   W */
        {"stem_post",   1, 24, 16, 16},
        {"acb_post",    1, 48,  8,  8},
        {"sppf_post",   1, 16,  4,  4},
    };
    int rc = 0;
    for (const auto &c : cases) rc |= run_case(c);
    if (rc) { std::fprintf(stdout, "CSIM FAIL\n"); return 1; }
    std::fprintf(stdout, "CSIM PASS\n");
    return 0;
}
