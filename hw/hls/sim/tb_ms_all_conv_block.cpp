/*
 * hw/hls/sim/tb_ms_all_conv_block.cpp — host_csim of layer_01 (acb1) against
 * the A2 golden tensor and A1 INT8 weights.
 *
 * NOTE on naming: the golden npz's `kind` field is labelled "sep_conv" for
 * historical reasons in tools/verify/extract_golden.py, but the actual tensor
 * is the FULL ms_all_conv_block output (sep_conv -> +residual -> conv1 -> conv2
 * -> +residual). See extract_golden.trace_forward layer 2 (idx=1, name=acb1).
 *
 * Weight assignment for layer_01 (yaml node 2 = acb1, c=24, k_dw=7):
 *   pwconv1 : L01  (48, 24, 1, 1)        C 24 -> 48                k=1 pad=0 g=1
 *   dwconv2 : L02  (48,  1, 7, 7) g=48   depth-wise on 48          k=7 pad=3 g=48
 *   pwconv3 : L03  (24, 48, 1, 1)        48 -> 24                  k=1 pad=0 g=1
 *   dwconv4 : L04  (24,  1, 3, 3) g=24   depth-wise on 24          k=3 pad=1 g=24 (pad-autocorrected from 0)
 *   conv1   : L05  (96, 24, 3, 3)        C 24 -> C_mid 96          k=3 pad=1 g=1
 *   conv2   : L06  (24, 96, 3, 3)        96 -> 24                  k=3 pad=1 g=1
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

extern "C" void sa_ms_all_conv_block(
    const sa_i32_t *x_in, sa_i32_t *y,
    const sa_i8_t *sep_w0, const sa_i32_t *sep_b0, const sa_i8_t *sep_s0,
    const sa_i8_t *sep_w1, const sa_i32_t *sep_b1, const sa_i8_t *sep_s1,
    const sa_i8_t *sep_w2, const sa_i32_t *sep_b2, const sa_i8_t *sep_s2,
    const sa_i8_t *sep_w3, const sa_i32_t *sep_b3, const sa_i8_t *sep_s3,
    const sa_i8_t *c1_w,   const sa_i32_t *c1_b,   const sa_i8_t *c1_s,
    const sa_i8_t *c2_w,   const sa_i32_t *c2_b,   const sa_i8_t *c2_s,
          sa_i32_t *r_buf, sa_i32_t *sep_y_buf,
          sa_i32_t *ping_buf, sa_i32_t *pong_buf,
          sa_i8_t  *spike_buf, sa_i32_t *tmp_acc,
    int T, int C, int C_exp, int C_mid, int H, int W,
    int K_dw2, int K_dw4, int pad_dw2, int pad_dw4,
    int K_c1, int pad_c1, int K_c2, int pad_c2);


/* layer_01 acb1 geometry — matches snn_yolov8_tiny_fpga.yaml node 2 + A1 weights. */
static const int T_IN     = 1;
static const int C_       = 24;     /* block in/out channel               */
static const int C_EXP    = 48;     /* sep_conv expansion                 */
static const int C_MID    = 96;     /* conv1 expansion                    */
static const int H_IN     = 64;
static const int W_IN     = 64;
static const int K_DW2    = 7;
static const int K_DW4    = 3;
static const int PAD_DW2  = 3;      /* k_dw2 // 2 (matches A1 meta L02)   */
static const int PAD_DW4  = 1;      /* k_dw4 // 2 (autocorrected from 0)  */
static const int K_C1     = 3;
static const int PAD_C1   = 1;
static const int K_C2     = 3;
static const int PAD_C2   = 1;


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
        "SA_GOLDEN_DIR", "tests/golden/exploded/layer_01_acb1");
    const std::string weight_dir = env_or(
        "SA_WEIGHT_DIR", "models/exploded");

    std::fprintf(stdout, "[layer_01] golden_dir = %s\n", golden_dir.c_str());
    std::fprintf(stdout, "[layer_01] weight_dir = %s\n", weight_dir.c_str());

    sa_npz::Tensor t_in, t_out_ref;
    sa_npz::Tensor wL[6], bL[6], sL[6];
    static const char *L_NAMES[6] = {"L01","L02","L03","L04","L05","L06"};
    try {
        t_in      = sa_npz::load_npy_member(golden_dir, "input");
        t_out_ref = sa_npz::load_npy_member(golden_dir, "output");
        for (int i = 0; i < 6; i++) {
            wL[i] = sa_npz::load_npy(weight_dir + "/" + L_NAMES[i] + ".w.npy");
            bL[i] = sa_npz::load_npy(weight_dir + "/" + L_NAMES[i] + ".bias.npy");
            sL[i] = sa_npz::load_npy(weight_dir + "/" + L_NAMES[i] + ".out_shift.npy");
        }
    } catch (const std::exception &e) {
        std::fprintf(stderr, "[layer_01] load FAILED: %s\n", e.what());
        return 2;
    }

    bool ok = true;
    ok &= check_shape("layer_01", "input",  t_in,      {T_IN, C_, H_IN, W_IN});
    ok &= check_shape("layer_01", "output", t_out_ref, {T_IN, C_, H_IN, W_IN});
    ok &= check_shape("layer_01", "L01.w",  wL[0],     {C_EXP, C_,    1, 1});
    ok &= check_shape("layer_01", "L02.w",  wL[1],     {C_EXP, 1,     K_DW2, K_DW2});
    ok &= check_shape("layer_01", "L03.w",  wL[2],     {C_,    C_EXP, 1, 1});
    ok &= check_shape("layer_01", "L04.w",  wL[3],     {C_,    1,     K_DW4, K_DW4});
    ok &= check_shape("layer_01", "L05.w",  wL[4],     {C_MID, C_,    K_C1,  K_C1});
    ok &= check_shape("layer_01", "L06.w",  wL[5],     {C_,    C_MID, K_C2,  K_C2});
    if (!ok) { std::fprintf(stdout, "CSIM FAIL\n"); return 3; }

    /* ---- Allocate scratch ---- */
    const int n_elem    = T_IN * C_ * H_IN * W_IN;
    const int C_max_int = (C_EXP > C_MID ? C_EXP : C_MID);
    const int n_ping    = T_IN * C_max_int * H_IN * W_IN;
    const int n_spk     = T_IN * SA_MAX_SPIKE * C_max_int * H_IN * W_IN;
    const int n_acc     = T_IN * SA_MAX_SPIKE * C_max_int * H_IN * W_IN;

    std::vector<sa_i32_t> y_dut(n_elem, 0);
    std::vector<sa_i32_t> r_buf(n_elem, 0);
    std::vector<sa_i32_t> sep_y_buf(n_elem, 0);
    std::vector<sa_i32_t> ping_buf(n_ping, 0);
    std::vector<sa_i32_t> pong_buf(n_ping, 0);
    std::vector<sa_i8_t>  spike_buf(n_spk, 0);
    std::vector<sa_i32_t> tmp_acc(n_acc, 0);

    /* ---- DUT ---- */
    sa_ms_all_conv_block(
        reinterpret_cast<const sa_i32_t *>(t_in.bytes.data()),
        y_dut.data(),
        wL[0].as_i8(), bL[0].as_i32(), sL[0].as_i8(),
        wL[1].as_i8(), bL[1].as_i32(), sL[1].as_i8(),
        wL[2].as_i8(), bL[2].as_i32(), sL[2].as_i8(),
        wL[3].as_i8(), bL[3].as_i32(), sL[3].as_i8(),
        wL[4].as_i8(), bL[4].as_i32(), sL[4].as_i8(),
        wL[5].as_i8(), bL[5].as_i32(), sL[5].as_i8(),
        r_buf.data(), sep_y_buf.data(),
        ping_buf.data(), pong_buf.data(),
        spike_buf.data(), tmp_acc.data(),
        T_IN, C_, C_EXP, C_MID, H_IN, W_IN,
        K_DW2, K_DW4, PAD_DW2, PAD_DW4,
        K_C1, PAD_C1, K_C2, PAD_C2);

    /* ---- Reference ---- */
    sa_ref::ConvBnW pwconv1{wL[0].as_i8(), bL[0].as_i32(), sL[0].as_i8(), 1,     1, 0,       1};
    sa_ref::ConvBnW dwconv2{wL[1].as_i8(), bL[1].as_i32(), sL[1].as_i8(), K_DW2, 1, PAD_DW2, C_EXP};
    sa_ref::ConvBnW pwconv3{wL[2].as_i8(), bL[2].as_i32(), sL[2].as_i8(), 1,     1, 0,       1};
    sa_ref::ConvBnW dwconv4{wL[3].as_i8(), bL[3].as_i32(), sL[3].as_i8(), K_DW4, 1, PAD_DW4, C_};
    sa_ref::ConvBnW conv1  {wL[4].as_i8(), bL[4].as_i32(), sL[4].as_i8(), K_C1,  1, PAD_C1,  1};
    sa_ref::ConvBnW conv2  {wL[5].as_i8(), bL[5].as_i32(), sL[5].as_i8(), K_C2,  1, PAD_C2,  1};

    auto y_ref = sa_ref::ms_all_conv_block(
        reinterpret_cast<const int32_t *>(t_in.bytes.data()),
        pwconv1, dwconv2, pwconv3, dwconv4,
        conv1, conv2,
        T_IN, C_, C_EXP, C_MID, H_IN, W_IN);

    /* ---- DUT vs Reference ---- */
    int bad_dut_ref = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != y_ref[i]) {
            if (bad_dut_ref < 10) {
                std::fprintf(stderr,
                    "[layer_01][DUT vs REF] idx=%zu  dut=%d  ref=%d\n",
                    i, (int)y_dut[i], (int)y_ref[i]);
            }
            bad_dut_ref++;
        }
    }
    if (bad_dut_ref) {
        std::fprintf(stderr, "[layer_01] DUT vs REF FAILED: %d mismatches\n", bad_dut_ref);
        std::fprintf(stdout, "CSIM FAIL\n");
        return 1;
    }
    std::fprintf(stdout, "[layer_01] DUT vs REF OK (%zu elems)\n", y_ref.size());

    /* ---- DUT vs Golden ---- */
    const int32_t *gold = t_out_ref.as_i32();
    int bad_gold = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != gold[i]) {
            if (bad_gold < 10) {
                std::fprintf(stderr,
                    "[layer_01][DUT vs GOLD] idx=%zu  dut=%d  gold=%d  diff=%d\n",
                    i, (int)y_dut[i], (int)gold[i],
                    (int)((int32_t)y_dut[i] - gold[i]));
            }
            bad_gold++;
        }
    }
    if (bad_gold) {
        std::fprintf(stderr,
            "[layer_01] DUT vs GOLDEN FAILED: %d / %zu mismatches\n",
            bad_gold, y_ref.size());
        std::fprintf(stdout, "CSIM FAIL_GOLDEN\n");
        return 1;
    }
    std::fprintf(stdout, "[layer_01] DUT vs GOLDEN OK (%zu elems)\n", y_ref.size());
    std::fprintf(stdout, "CSIM PASS\n");
    return 0;
}
