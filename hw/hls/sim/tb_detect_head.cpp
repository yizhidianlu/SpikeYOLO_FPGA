/*
 * hw/hls/sim/tb_detect_head.cpp — host_csim of layer_11 (detect) against the
 * A2 v1.0.2 golden tensor.
 *
 * Geometry from layer_11_detect.meta.json:
 *   input  : int32 [1, 48, 16, 16]   (head_refine output)
 *   output : int8  [1, 48, 16, 16]   (NumPy astype(int8) modular truncation)
 *
 * No weights are consumed — the PL stub is a pure cast (the real Detect head
 * cv2/cv3/DFL runs on PS, see C3's pipeline).
 */

#include "dtypes.h"
#include "reference.hpp"
#include "npz_reader.h"

#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" void sa_detect_head(
    const sa_i32_t *x_in,
          sa_i8_t  *y_out,
    int N, int C, int H, int W);


static const int N_IN = 1;
static const int C_IN = 48;
static const int H_IN = 16;
static const int W_IN = 16;


static std::string env_or(const char *name, const char *fallback)
{
    const char *v = std::getenv(name);
    return v ? std::string(v) : std::string(fallback);
}

static bool check_shape(const char *tag, const char *name,
                        const sa_npz::Tensor &t,
                        std::initializer_list<int> expect)
{
    if ((int)t.shape.size() != (int)expect.size()) {
        std::fprintf(stderr, "[%s] %s rank %zu != %zu\n",
                     tag, name, t.shape.size(), expect.size());
        return false;
    }
    int i = 0;
    for (int e : expect) {
        if ((int)t.shape[i] != e) {
            std::fprintf(stderr, "[%s] %s shape[%d] = %lld != %d\n",
                         tag, name, i, (long long)t.shape[i], e);
            return false;
        }
        i++;
    }
    return true;
}


int main()
{
    const std::string golden_dir = env_or(
        "SA_GOLDEN_DIR", "tests/golden/exploded/layer_11_detect");

    std::fprintf(stdout, "[layer_11] golden_dir = %s\n", golden_dir.c_str());

    sa_npz::Tensor t_in, t_out_ref;
    try {
        t_in      = sa_npz::load_npy_member(golden_dir, "input");
        t_out_ref = sa_npz::load_npy_member(golden_dir, "output");
    } catch (const std::exception &e) {
        std::fprintf(stderr, "[layer_11] load FAILED: %s\n", e.what());
        return 2;
    }

    bool ok = true;
    ok &= check_shape("layer_11", "input",  t_in,      {N_IN, C_IN, H_IN, W_IN});
    ok &= check_shape("layer_11", "output", t_out_ref, {N_IN, C_IN, H_IN, W_IN});
    if (!ok) { std::fprintf(stdout, "CSIM FAIL\n"); return 3; }

    const int n_total = N_IN * C_IN * H_IN * W_IN;

    /* ---- DUT ---- */
    std::vector<sa_i8_t> y_dut(n_total, 0);
    sa_detect_head(
        reinterpret_cast<const sa_i32_t *>(t_in.bytes.data()),
        y_dut.data(),
        N_IN, C_IN, H_IN, W_IN);

    /* ---- Reference ---- */
    auto y_ref = sa_ref::detect_head(
        reinterpret_cast<const int32_t *>(t_in.bytes.data()),
        N_IN, C_IN, H_IN, W_IN);

    /* ---- DUT vs Reference ---- */
    int bad_dut_ref = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int8_t)y_dut[i] != y_ref[i]) {
            if (bad_dut_ref < 10) {
                std::fprintf(stderr,
                    "[layer_11][DUT vs REF] idx=%zu  dut=%d  ref=%d\n",
                    i, (int)y_dut[i], (int)y_ref[i]);
            }
            bad_dut_ref++;
        }
    }
    if (bad_dut_ref) {
        std::fprintf(stderr, "[layer_11] DUT vs REF FAILED: %d mismatches\n", bad_dut_ref);
        std::fprintf(stdout, "CSIM FAIL\n");
        return 1;
    }
    std::fprintf(stdout, "[layer_11] DUT vs REF OK (%zu elems)\n", y_ref.size());

    /* ---- DUT vs Golden ---- */
    const int8_t *gold = t_out_ref.as_i8();
    int bad_gold = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int8_t)y_dut[i] != gold[i]) {
            if (bad_gold < 10) {
                std::fprintf(stderr,
                    "[layer_11][DUT vs GOLD] idx=%zu  dut=%d  gold=%d  diff=%d\n",
                    i, (int)y_dut[i], (int)gold[i],
                    (int)((int8_t)y_dut[i] - gold[i]));
            }
            bad_gold++;
        }
    }
    if (bad_gold) {
        std::fprintf(stderr,
            "[layer_11] DUT vs GOLDEN FAILED: %d / %zu mismatches\n",
            bad_gold, y_ref.size());
        std::fprintf(stdout, "CSIM FAIL_GOLDEN\n");
        return 1;
    }
    std::fprintf(stdout, "[layer_11] DUT vs GOLDEN OK (%zu elems)\n", y_ref.size());
    std::fprintf(stdout, "CSIM PASS\n");
    return 0;
}
