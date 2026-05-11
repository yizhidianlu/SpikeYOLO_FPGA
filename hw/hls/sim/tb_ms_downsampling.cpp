/*
 * hw/hls/sim/tb_ms_downsampling.cpp — host_csim of layer_00 (stem) against the
 * A2-produced golden tensors and the A1-produced INT8 weights.
 *
 * Inputs the test loader needs:
 *   tests/golden/exploded/layer_00_stem/{input,output}.npy   (from A2)
 *   models/exploded/L00.{w,bias,out_shift}.npy               (from A1)
 *
 * Both produced by `tools/ci/explode_npz.py` which the Makefile runs
 * automatically before linking this binary.
 *
 * On success prints "CSIM PASS"; on mismatch prints the first 10 (idx,
 * expected, actual) tuples and exits 1.
 */

#include "dtypes.h"
#include "reference.hpp"
#include "npz_reader.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" void sa_ms_downsampling(
    const sa_i8_t  *x_i8,
    const sa_i32_t *x_i32,
          sa_i32_t *y,
    const sa_i8_t  *w,
    const sa_i32_t *bias,
    const sa_i8_t  *out_shift,
          sa_i8_t  *spike_buf,
          sa_i32_t *tmp_acc,
    int T_in, int C_in, int C_out, int H, int W,
    int K, int stride, int pad, int groups, int first_layer);


/* Layer_00 stem geometry (must match snn_yolov8_tiny_fpga.yaml + golden meta). */
static const int K       = 7;
static const int STRIDE  = 4;
static const int PAD     = 2;
static const int GROUPS  = 1;
static const int T_IN    = 1;
static const int C_IN    = 3;
static const int C_OUT   = 24;
static const int H_IN    = 256;
static const int W_IN    = 256;
static const int H_OUT   = (H_IN + 2 * PAD - K) / STRIDE + 1;   /* = 64 */
static const int W_OUT   = (W_IN + 2 * PAD - K) / STRIDE + 1;   /* = 64 */


static std::string env_or(const char *name, const char *fallback)
{
    const char *v = std::getenv(name);
    return v ? std::string(v) : std::string(fallback);
}


int main()
{
    /* Resolve directories. SA_GOLDEN_DIR / SA_WEIGHT_DIR override the
     * defaults so CI can relocate without recompiling.
     */
    const std::string golden_dir = env_or(
        "SA_GOLDEN_DIR",
        "tests/golden/exploded/layer_00_stem");
    const std::string weight_dir = env_or(
        "SA_WEIGHT_DIR",
        "models/exploded");

    std::fprintf(stdout, "[layer_00] golden_dir = %s\n", golden_dir.c_str());
    std::fprintf(stdout, "[layer_00] weight_dir = %s\n", weight_dir.c_str());

    sa_npz::Tensor t_in, t_out_ref, t_w, t_bias, t_shift;
    try {
        t_in       = sa_npz::load_npy_member(golden_dir, "input");
        t_out_ref  = sa_npz::load_npy_member(golden_dir, "output");
        t_w        = sa_npz::load_npy(weight_dir + "/L00.w.npy");
        t_bias     = sa_npz::load_npy(weight_dir + "/L00.bias.npy");
        t_shift    = sa_npz::load_npy(weight_dir + "/L00.out_shift.npy");
    } catch (const std::exception &e) {
        std::fprintf(stderr, "[layer_00] load FAILED: %s\n", e.what());
        std::fprintf(stderr,
            "[layer_00] Hint: run 'python tools/ci/explode_npz.py --all' and\n"
            "[layer_00]       'python tools/ci/explode_npz.py models/tiny_fpga_int8.npz \\\n"
            "[layer_00]            --out-dir models/exploded' first.\n");
        return 2;
    }

    /* ---- shape sanity ---- */
    auto check_shape = [](const char *name, const sa_npz::Tensor &t,
                          std::initializer_list<int> expect) {
        if ((int)t.shape.size() != (int)expect.size()) {
            std::fprintf(stderr, "[layer_00] %s rank %zu != %zu\n",
                         name, t.shape.size(), expect.size());
            return false;
        }
        int i = 0;
        for (int e : expect) {
            if ((int)t.shape[i] != e) {
                std::fprintf(stderr, "[layer_00] %s shape[%d] = %lld != %d\n",
                             name, i, (long long)t.shape[i], e);
                return false;
            }
            i++;
        }
        return true;
    };

    bool shapes_ok = true;
    shapes_ok &= check_shape("input",     t_in,      {T_IN, C_IN, H_IN, W_IN});
    shapes_ok &= check_shape("output",    t_out_ref, {T_IN, C_OUT, H_OUT, W_OUT});
    shapes_ok &= check_shape("weight",    t_w,       {C_OUT, C_IN, K, K});
    shapes_ok &= check_shape("bias",      t_bias,    {C_OUT});
    shapes_ok &= check_shape("out_shift", t_shift,   {C_OUT});
    if (!shapes_ok) return 3;
    if (t_in.dtype     != sa_npz::DType::INT8 ||
        t_out_ref.dtype != sa_npz::DType::INT32 ||
        t_w.dtype       != sa_npz::DType::INT8 ||
        t_bias.dtype    != sa_npz::DType::INT32 ||
        t_shift.dtype   != sa_npz::DType::INT8) {
        std::fprintf(stderr, "[layer_00] dtype mismatch\n");
        return 4;
    }

    /* ---- DUT ---- */
    std::vector<sa_i32_t> y_dut((size_t)T_IN * C_OUT * H_OUT * W_OUT, 0);
    /* tmp_acc only needs T_in frames here because first_layer=1 skips collapse */
    std::vector<sa_i32_t> tmp_acc((size_t)T_IN * C_OUT * H_OUT * W_OUT, 0);
    /* spike_buf is unused on the stem path but the DUT signature still
     * dereferences it during pragma binding — give it a 1-byte placeholder.
     */
    std::vector<sa_i8_t>  spike_buf(1, 0);

    sa_ms_downsampling(
        reinterpret_cast<const sa_i8_t  *>(t_in.bytes.data()),
        /*x_i32=*/nullptr,
        y_dut.data(),
        reinterpret_cast<const sa_i8_t  *>(t_w.bytes.data()),
        reinterpret_cast<const sa_i32_t *>(t_bias.bytes.data()),
        reinterpret_cast<const sa_i8_t  *>(t_shift.bytes.data()),
        spike_buf.data(),
        tmp_acc.data(),
        T_IN, C_IN, C_OUT, H_IN, W_IN,
        K, STRIDE, PAD, GROUPS, /*first_layer=*/1);

    /* ---- Reference (header-only) ---- */
    auto y_ref = sa_ref::ms_downsampling(
        reinterpret_cast<const int8_t  *>(t_in.bytes.data()),
        /*x_i32=*/nullptr,
        reinterpret_cast<const int8_t  *>(t_w.bytes.data()),
        reinterpret_cast<const int32_t *>(t_bias.bytes.data()),
        reinterpret_cast<const int8_t  *>(t_shift.bytes.data()),
        T_IN, C_IN, C_OUT, H_IN, W_IN,
        K, STRIDE, PAD, GROUPS, /*first_layer=*/true);

    /* ---- Compare DUT vs Reference (sanity) ---- */
    int bad_dut_ref = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != y_ref[i]) {
            if (bad_dut_ref < 10) {
                std::fprintf(stderr,
                    "[layer_00][DUT vs REF] idx=%zu  dut=%d  ref=%d\n",
                    i, (int)y_dut[i], (int)y_ref[i]);
            }
            bad_dut_ref++;
        }
    }
    if (bad_dut_ref) {
        std::fprintf(stderr, "[layer_00] DUT vs REF FAILED: %d mismatches\n",
                     bad_dut_ref);
        std::fprintf(stdout, "CSIM FAIL\n");
        return 1;
    }
    std::fprintf(stdout, "[layer_00] DUT vs REF OK (%zu elems)\n", y_ref.size());

    /* ---- Compare DUT vs A2 golden output ---- */
    const int32_t *gold = t_out_ref.as_i32();
    int bad_gold = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != gold[i]) {
            if (bad_gold < 10) {
                std::fprintf(stderr,
                    "[layer_00][DUT vs GOLD] idx=%zu  dut=%d  gold=%d  diff=%d\n",
                    i, (int)y_dut[i], (int)gold[i],
                    (int)((int32_t)y_dut[i] - gold[i]));
            }
            bad_gold++;
        }
    }
    if (bad_gold) {
        std::fprintf(stderr,
            "[layer_00] DUT vs GOLDEN FAILED: %d / %zu mismatches "
            "(weights mismatch between A1 npz and the synthetic golden — "
            "expected at this M1 stage if A2 used different RNG)\n",
            bad_gold, y_ref.size());
        std::fprintf(stdout, "CSIM FAIL_GOLDEN\n");
        return 1;
    }
    std::fprintf(stdout, "[layer_00] DUT vs GOLDEN OK (%zu elems)\n",
                 y_ref.size());
    std::fprintf(stdout, "CSIM PASS\n");
    return 0;
}
