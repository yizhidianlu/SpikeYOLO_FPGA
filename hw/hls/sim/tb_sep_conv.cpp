/*
 * hw/hls/sim/tb_sep_conv.cpp — host_csim of layer_03 (acb2a) but ONLY exercising
 * the inner sep_conv stage of the MS_AllConvBlock.
 *
 * Why this exists: tests/golden/layer_03_acb2a.npz captures the FULL acb2a
 * block output (post residual #1 + conv1 + conv2 + residual #2). For B1 we
 * want a smaller per-stage smoke test that isolates sep_conv. The golden
 * tensor for that smoke is generated locally by re-running the NumPy reference
 * once and stored under hw/hls/sim/golden_local/sep_conv_smoke.npz (NOT part
 * of the contract-2 suite). This testbench reads that smoke directly.
 *
 * Generation script: tools/ci/gen_sep_conv_smoke.py (also new).
 *
 * Weight assignment for acb2a sep_conv (yaml node 4 sub 0, c=48, k_dw=7):
 *   pwconv1 : L08  (96, 48, 1, 1)        C 48 -> C_exp 96         k=1 pad=0 g=1
 *   dwconv2 : L09  (96, 1, 7, 7) g=96    depth-wise on 96         k=7 pad=3 g=96
 *   pwconv3 : L10  (48, 96, 1, 1)        96 -> 48                 k=1 pad=0 g=1
 *   dwconv4 : L11  (48, 1, 3, 3) g=48    depth-wise on 48         k=3 pad=1 g=48
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

extern "C" void sa_sep_conv(
    const sa_i32_t *x, sa_i32_t *y,
    const sa_i8_t *w0, const sa_i32_t *b0, const sa_i8_t *s0,
    const sa_i8_t *w1, const sa_i32_t *b1, const sa_i8_t *s1,
    const sa_i8_t *w2, const sa_i32_t *b2, const sa_i8_t *s2,
    const sa_i8_t *w3, const sa_i32_t *b3, const sa_i8_t *s3,
          sa_i32_t *ping_buf, sa_i32_t *pong_buf,
          sa_i8_t  *spike_buf, sa_i32_t *tmp_acc,
    int T, int C, int C_exp, int H, int W,
    int K_dw2, int K_dw4, int pad_dw2, int pad_dw4);


static const int T_IN     = 1;
static const int C_       = 48;
static const int C_EXP    = 96;
static const int H_IN     = 32;
static const int W_IN     = 32;
static const int K_DW2    = 7;
static const int K_DW4    = 3;
static const int PAD_DW2  = 3;
static const int PAD_DW4  = 1;


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
    /* Self-generated smoke directory under hw/hls/sim/golden_local/.
     * Created by tools/ci/gen_sep_conv_smoke.py (must be run before this tb).
     */
    const std::string golden_dir = env_or(
        "SA_SEP_GOLDEN_DIR", "hw/hls/sim/golden_local/sep_conv_smoke");
    const std::string weight_dir = env_or(
        "SA_WEIGHT_DIR", "models/exploded");

    std::fprintf(stdout, "[sep_conv] golden_dir = %s\n", golden_dir.c_str());
    std::fprintf(stdout, "[sep_conv] weight_dir = %s\n", weight_dir.c_str());

    sa_npz::Tensor t_in, t_out_ref;
    sa_npz::Tensor wL[4], bL[4], sL[4];
    static const char *L_NAMES[4] = {"L08","L09","L10","L11"};
    try {
        t_in      = sa_npz::load_npy_member(golden_dir, "input");
        t_out_ref = sa_npz::load_npy_member(golden_dir, "output");
        for (int i = 0; i < 4; i++) {
            wL[i] = sa_npz::load_npy(weight_dir + "/" + L_NAMES[i] + ".w.npy");
            bL[i] = sa_npz::load_npy(weight_dir + "/" + L_NAMES[i] + ".bias.npy");
            sL[i] = sa_npz::load_npy(weight_dir + "/" + L_NAMES[i] + ".out_shift.npy");
        }
    } catch (const std::exception &e) {
        std::fprintf(stderr, "[sep_conv] load FAILED: %s\n", e.what());
        std::fprintf(stderr,
            "[sep_conv] Hint: run 'python tools/ci/gen_sep_conv_smoke.py' first.\n");
        return 2;
    }

    bool ok = true;
    ok &= check_shape("sep_conv", "input",  t_in,      {T_IN, C_, H_IN, W_IN});
    ok &= check_shape("sep_conv", "output", t_out_ref, {T_IN, C_, H_IN, W_IN});
    ok &= check_shape("sep_conv", "L08.w",  wL[0],     {C_EXP, C_,    1, 1});
    ok &= check_shape("sep_conv", "L09.w",  wL[1],     {C_EXP, 1,     K_DW2, K_DW2});
    ok &= check_shape("sep_conv", "L10.w",  wL[2],     {C_,    C_EXP, 1, 1});
    ok &= check_shape("sep_conv", "L11.w",  wL[3],     {C_,    1,     K_DW4, K_DW4});
    if (!ok) { std::fprintf(stdout, "CSIM FAIL\n"); return 3; }

    /* ---- Allocate scratch ---- */
    const int n_elem = T_IN * C_ * H_IN * W_IN;
    const int n_ping = T_IN * C_EXP * H_IN * W_IN;
    const int n_spk  = T_IN * SA_MAX_SPIKE * C_EXP * H_IN * W_IN;
    const int n_acc  = T_IN * SA_MAX_SPIKE * C_EXP * H_IN * W_IN;

    std::vector<sa_i32_t> y_dut(n_elem, 0);
    std::vector<sa_i32_t> ping_buf(n_ping, 0);
    std::vector<sa_i32_t> pong_buf(n_ping, 0);
    std::vector<sa_i8_t>  spike_buf(n_spk, 0);
    std::vector<sa_i32_t> tmp_acc(n_acc, 0);

    /* ---- DUT ---- */
    sa_sep_conv(
        reinterpret_cast<const sa_i32_t *>(t_in.bytes.data()),
        y_dut.data(),
        wL[0].as_i8(), bL[0].as_i32(), sL[0].as_i8(),
        wL[1].as_i8(), bL[1].as_i32(), sL[1].as_i8(),
        wL[2].as_i8(), bL[2].as_i32(), sL[2].as_i8(),
        wL[3].as_i8(), bL[3].as_i32(), sL[3].as_i8(),
        ping_buf.data(), pong_buf.data(),
        spike_buf.data(), tmp_acc.data(),
        T_IN, C_, C_EXP, H_IN, W_IN,
        K_DW2, K_DW4, PAD_DW2, PAD_DW4);

    /* ---- Reference ---- */
    sa_ref::ConvBnW pwconv1{wL[0].as_i8(), bL[0].as_i32(), sL[0].as_i8(), 1,     1, 0,       1};
    sa_ref::ConvBnW dwconv2{wL[1].as_i8(), bL[1].as_i32(), sL[1].as_i8(), K_DW2, 1, PAD_DW2, C_EXP};
    sa_ref::ConvBnW pwconv3{wL[2].as_i8(), bL[2].as_i32(), sL[2].as_i8(), 1,     1, 0,       1};
    sa_ref::ConvBnW dwconv4{wL[3].as_i8(), bL[3].as_i32(), sL[3].as_i8(), K_DW4, 1, PAD_DW4, C_};

    auto y_ref = sa_ref::sep_conv(
        reinterpret_cast<const int32_t *>(t_in.bytes.data()),
        pwconv1, dwconv2, pwconv3, dwconv4,
        T_IN, C_, C_EXP, H_IN, W_IN);

    /* ---- DUT vs Reference ---- */
    int bad_dut_ref = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != y_ref[i]) {
            if (bad_dut_ref < 10) {
                std::fprintf(stderr,
                    "[sep_conv][DUT vs REF] idx=%zu  dut=%d  ref=%d\n",
                    i, (int)y_dut[i], (int)y_ref[i]);
            }
            bad_dut_ref++;
        }
    }
    if (bad_dut_ref) {
        std::fprintf(stderr, "[sep_conv] DUT vs REF FAILED: %d mismatches\n", bad_dut_ref);
        std::fprintf(stdout, "CSIM FAIL\n");
        return 1;
    }
    std::fprintf(stdout, "[sep_conv] DUT vs REF OK (%zu elems)\n", y_ref.size());

    /* ---- DUT vs Smoke Golden ---- */
    const int32_t *gold = t_out_ref.as_i32();
    int bad_gold = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != gold[i]) {
            if (bad_gold < 10) {
                std::fprintf(stderr,
                    "[sep_conv][DUT vs GOLD] idx=%zu  dut=%d  gold=%d  diff=%d\n",
                    i, (int)y_dut[i], (int)gold[i],
                    (int)((int32_t)y_dut[i] - gold[i]));
            }
            bad_gold++;
        }
    }
    if (bad_gold) {
        std::fprintf(stderr,
            "[sep_conv] DUT vs GOLDEN FAILED: %d / %zu mismatches\n",
            bad_gold, y_ref.size());
        std::fprintf(stdout, "CSIM FAIL_GOLDEN\n");
        return 1;
    }
    std::fprintf(stdout, "[sep_conv] DUT vs GOLDEN OK (%zu elems)\n", y_ref.size());
    std::fprintf(stdout, "CSIM PASS\n");
    return 0;
}
