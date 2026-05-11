/*
 * hw/hls/sim/tb_spike_sppf.cpp — host_csim of layer_08 (sppf) against the A2
 * golden tensor and A1 INT8 weights L21/L22.
 *
 * Geometry from layer_08_sppf.meta.json + L21/L22 scalar:
 *   input  : int32 [1, 96, 16, 16]
 *   cv1    : L21  (48, 96, 1, 1)  C_in=96 -> C_mid=48,  k=1 pad=0 g=1
 *   cv2    : L22  (48, 192, 1, 1) C_cat=4*C_mid=192 -> C_out=48
 *   output : int32 [1, 48, 16, 16]
 *   k_pool : 5
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

extern "C" void sa_spike_sppf(
    const sa_i32_t *x_in, sa_i32_t *y_out,
    const sa_i8_t *cv1_w, const sa_i32_t *cv1_b, const sa_i8_t *cv1_s,
    const sa_i8_t *cv2_w, const sa_i32_t *cv2_b, const sa_i8_t *cv2_s,
          sa_i32_t *ping_buf,
          sa_i8_t  *spk_buf,
          sa_i8_t  *pool_buf1, sa_i8_t *pool_buf2, sa_i8_t *pool_buf3,
          sa_i8_t  *concat_buf,
          sa_i32_t *cat_i32_buf,
          sa_i8_t  *spike_buf, sa_i32_t *tmp_acc,
    int T, int C_in, int C_mid, int C_out, int H, int W, int k);


static const int T_IN  = 1;
static const int C_IN  = 96;
static const int C_MID = 48;
static const int C_OUT = 48;
static const int H_IN  = 16;
static const int W_IN  = 16;
static const int K_POOL = 5;


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
        "SA_GOLDEN_DIR", "tests/golden/exploded/layer_08_sppf");
    const std::string weight_dir = env_or(
        "SA_WEIGHT_DIR", "models/exploded");

    std::fprintf(stdout, "[layer_08] golden_dir = %s\n", golden_dir.c_str());
    std::fprintf(stdout, "[layer_08] weight_dir = %s\n", weight_dir.c_str());

    sa_npz::Tensor t_in, t_out_ref;
    sa_npz::Tensor cv1_w, cv1_b, cv1_s, cv2_w, cv2_b, cv2_s;
    try {
        t_in      = sa_npz::load_npy_member(golden_dir, "input");
        t_out_ref = sa_npz::load_npy_member(golden_dir, "output");
        cv1_w = sa_npz::load_npy(weight_dir + "/L21.w.npy");
        cv1_b = sa_npz::load_npy(weight_dir + "/L21.bias.npy");
        cv1_s = sa_npz::load_npy(weight_dir + "/L21.out_shift.npy");
        cv2_w = sa_npz::load_npy(weight_dir + "/L22.w.npy");
        cv2_b = sa_npz::load_npy(weight_dir + "/L22.bias.npy");
        cv2_s = sa_npz::load_npy(weight_dir + "/L22.out_shift.npy");
    } catch (const std::exception &e) {
        std::fprintf(stderr, "[layer_08] load FAILED: %s\n", e.what());
        return 2;
    }

    bool ok = true;
    ok &= check_shape("layer_08", "input",  t_in,      {T_IN, C_IN,  H_IN, W_IN});
    ok &= check_shape("layer_08", "output", t_out_ref, {T_IN, C_OUT, H_IN, W_IN});
    ok &= check_shape("layer_08", "cv1.w",  cv1_w,     {C_MID, C_IN,        1, 1});
    ok &= check_shape("layer_08", "cv2.w",  cv2_w,     {C_OUT, 4 * C_MID,   1, 1});
    if (!ok) { std::fprintf(stdout, "CSIM FAIL\n"); return 3; }

    /* ---- Allocate scratch ---- */
    const int n_out  = T_IN * C_OUT * H_IN * W_IN;
    const int n_mid  = T_IN * C_MID * H_IN * W_IN;
    const int n_spk  = T_IN * SA_MAX_SPIKE * C_MID * H_IN * W_IN;
    const int n_cat  = T_IN * SA_MAX_SPIKE * (4 * C_MID) * H_IN * W_IN;
    const int n_cati32 = T_IN * (4 * C_MID) * H_IN * W_IN;

    /* internal scratch for ms_standard_conv worst case (C_cat -> C_out at cv2) */
    const int C_max = (C_IN > 4 * C_MID) ? C_IN : (4 * C_MID);
    const int n_inner_spike = T_IN * SA_MAX_SPIKE * C_max * H_IN * W_IN;
    const int n_inner_acc   = T_IN * SA_MAX_SPIKE * C_max * H_IN * W_IN;

    std::vector<sa_i32_t> y_dut(n_out, 0);
    std::vector<sa_i32_t> ping_buf(n_mid, 0);
    std::vector<sa_i8_t>  spk_buf(n_spk, 0);
    std::vector<sa_i8_t>  pool_buf1(n_spk, 0);
    std::vector<sa_i8_t>  pool_buf2(n_spk, 0);
    std::vector<sa_i8_t>  pool_buf3(n_spk, 0);
    std::vector<sa_i8_t>  concat_buf(n_cat, 0);
    std::vector<sa_i32_t> cat_i32_buf(n_cati32, 0);
    std::vector<sa_i8_t>  inner_spike(n_inner_spike, 0);
    std::vector<sa_i32_t> inner_acc(n_inner_acc, 0);

    /* ---- DUT ---- */
    sa_spike_sppf(
        reinterpret_cast<const sa_i32_t *>(t_in.bytes.data()),
        y_dut.data(),
        cv1_w.as_i8(), cv1_b.as_i32(), cv1_s.as_i8(),
        cv2_w.as_i8(), cv2_b.as_i32(), cv2_s.as_i8(),
        ping_buf.data(),
        spk_buf.data(),
        pool_buf1.data(), pool_buf2.data(), pool_buf3.data(),
        concat_buf.data(),
        cat_i32_buf.data(),
        inner_spike.data(), inner_acc.data(),
        T_IN, C_IN, C_MID, C_OUT, H_IN, W_IN, K_POOL);

    /* ---- Reference ---- */
    sa_ref::ConvBnW cv1{cv1_w.as_i8(), cv1_b.as_i32(), cv1_s.as_i8(), 1, 1, 0, 1};
    sa_ref::ConvBnW cv2{cv2_w.as_i8(), cv2_b.as_i32(), cv2_s.as_i8(), 1, 1, 0, 1};

    auto y_ref = sa_ref::spike_sppf(
        reinterpret_cast<const int32_t *>(t_in.bytes.data()),
        cv1, cv2,
        T_IN, C_IN, C_MID, C_OUT, H_IN, W_IN, K_POOL);

    /* ---- DUT vs Reference ---- */
    int bad_dut_ref = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != y_ref[i]) {
            if (bad_dut_ref < 10) {
                std::fprintf(stderr,
                    "[layer_08][DUT vs REF] idx=%zu  dut=%d  ref=%d\n",
                    i, (int)y_dut[i], (int)y_ref[i]);
            }
            bad_dut_ref++;
        }
    }
    if (bad_dut_ref) {
        std::fprintf(stderr, "[layer_08] DUT vs REF FAILED: %d mismatches\n", bad_dut_ref);
        std::fprintf(stdout, "CSIM FAIL\n");
        return 1;
    }
    std::fprintf(stdout, "[layer_08] DUT vs REF OK (%zu elems)\n", y_ref.size());

    /* ---- DUT vs Golden ---- */
    const int32_t *gold = t_out_ref.as_i32();
    int bad_gold = 0;
    for (size_t i = 0; i < y_ref.size(); i++) {
        if ((int32_t)y_dut[i] != gold[i]) {
            if (bad_gold < 10) {
                std::fprintf(stderr,
                    "[layer_08][DUT vs GOLD] idx=%zu  dut=%d  gold=%d  diff=%d\n",
                    i, (int)y_dut[i], (int)gold[i],
                    (int)((int32_t)y_dut[i] - gold[i]));
            }
            bad_gold++;
        }
    }
    if (bad_gold) {
        std::fprintf(stderr,
            "[layer_08] DUT vs GOLDEN FAILED: %d / %zu mismatches\n",
            bad_gold, y_ref.size());
        std::fprintf(stdout, "CSIM FAIL_GOLDEN\n");
        return 1;
    }
    std::fprintf(stdout, "[layer_08] DUT vs GOLDEN OK (%zu elems)\n", y_ref.size());
    std::fprintf(stdout, "CSIM PASS\n");
    return 0;
}
