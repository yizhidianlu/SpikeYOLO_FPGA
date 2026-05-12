/*
 * hw/hls/src/tiny_fpga_top.cpp — Top-level kernel that chains the 11 layers
 * of `tools/fpga/numpy_reference.TinyFpgaNet` end-to-end.
 *
 * This is the M1 Week 4 "string things together" version: layers run
 * SERIALLY through DDR-resident scratch buffers — no DATAFLOW pragma yet.
 * M5 will swap the static buffers for ping-pong streams + pipelined
 * dataflow once the algorithmic layout is locked.
 *
 * Layer schedule (matches tools/verify/extract_golden.py):
 *
 *   id  | role                              | weight slots | shape transform
 *   ----|-----------------------------------|--------------|--------------------------
 *    0  | stem ms_downsampling (first=1)    | L00          | int8 [1,3,256,256]   -> int32 [1, 24, 64, 64]
 *    1  | acb1 ms_all_conv_block            | L01..L06     | [1, 24, 64, 64]      -> [1, 24, 64, 64]
 *    2  | ds1 ms_downsampling               | L07          | [1, 24, 64, 64]      -> [1, 48, 32, 32]
 *    3  | acb2a ms_all_conv_block           | L08..L13     | [1, 48, 32, 32]      -> [1, 48, 32, 32]
 *    4  | acb2b ms_all_conv_block           | L08..L13 (re-used) | [1, 48, 32, 32]      -> [1, 48, 32, 32]
 *    5  | ds2 ms_downsampling               | L14          | [1, 48, 32, 32]      -> [1, 96, 16, 16]
 *    6  | acb3a ms_all_conv_block           | L15..L20     | [1, 96, 16, 16]      -> [1, 96, 16, 16]
 *    7  | acb3b ms_all_conv_block           | L15..L20 (re-used) | [1, 96, 16, 16]      -> [1, 96, 16, 16]
 *    8  | sppf spike_sppf                   | L21..L22     | [1, 96, 16, 16]      -> [1, 48, 16, 16]
 *    9  | head_reduce ms_standard_conv      | L23          | [1, 48, 16, 16]      -> [1, 48, 16, 16]
 *   10  | head_refine ms_all_conv_block     | L24..L29     | [1, 48, 16, 16]      -> [1, 48, 16, 16]
 *   11  | detect (PL stub: int32 -> int8)   | (none)       | [1, 48, 16, 16] i32  -> [1, 48, 16, 16] i8
 *
 * Weights layout (`weights_blob`): caller arranges the .bin so each LNN entry
 * has its `w`, `bias`, and `out_shift` arrays packed contiguously and laid
 * out at `offsets[NN].{w,bias,out_shift}`. This mirrors A1's published
 * `tiny_fpga_int8.bin` schema (Contract 1).
 *
 * Caller is responsible for sizing the four scratch buffers below big enough
 * for the worst layer (layer 0 stem output = 1*24*64*64 i32 = 384 KB; layer 1
 * acb conv1 expansion = 1*96*64*64 i32 = 1.5 MB; reduce-by-stride after that).
 *
 * === Resource estimate (paper) ===
 * Top is a pure dispatcher — its own footprint is FSM + offset arithmetic;
 * the synthesised .xo total equals the per-layer sum (single PE array, serial
 * schedule) so the numbers below are *dispatcher only*, not the chip total.
 * DSP48:    0       (no MAC in the dispatcher itself; peak == any leaf <= 64)
 * BRAM 36K: ~4 KB   (scratch buffers are AXI-MM/DDR3; only the FSM regs +
 *                    sa_layer_weights_t[30] cache live on-chip)
 * LUT:      ~6 K    (FSM + offset arithmetic across the 12 if-branches)
 * FF:       ~3 K    (per-layer geometry constants + AXI-MM addr registers)
 * estimated cycles per call (run_all): sum of per-layer cycles, dominated by
 *   stem (~1.6 M) + acb1/acb2a/acb2b (~600 K each) ~= 4.5 M cycles total.
 */

#include "dtypes.h"
#include "axi_iface.h"
#include "op_macros.h"

#include <cstring>

extern "C" {

/* ---- Forward decls of every leaf / block kernel we dispatch into. ---- */

void sa_ms_downsampling(
    const sa_i8_t  *x_i8, const sa_i32_t *x_i32, sa_i32_t *y,
    const sa_i8_t  *w, const sa_i32_t *bias, const sa_i8_t *out_shift,
          sa_i8_t  *spike_buf, sa_i32_t *tmp_acc,
    int T_in, int C_in, int C_out, int H, int W,
    int K, int stride, int pad, int groups, int first_layer);

void sa_ms_all_conv_block(
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

void sa_spike_sppf(
    const sa_i32_t *x_in, sa_i32_t *y_out,
    const sa_i8_t *cv1_w, const sa_i32_t *cv1_b, const sa_i8_t *cv1_s,
    const sa_i8_t *cv2_w, const sa_i32_t *cv2_b, const sa_i8_t *cv2_s,
          sa_i32_t *ping_buf, sa_i8_t *spk_buf,
          sa_i8_t  *pool_buf1, sa_i8_t *pool_buf2, sa_i8_t *pool_buf3,
          sa_i8_t  *concat_buf, sa_i32_t *cat_i32_buf,
          sa_i8_t  *spike_buf, sa_i32_t *tmp_acc,
    int T, int C_in, int C_mid, int C_out, int H, int W, int k);

void sa_detect_head(
    const sa_i32_t *x_in, sa_i8_t *y_out,
    int N, int C, int H, int W);


/* ----------------------------------------------------------------------------
 * sa_layer_weights_t — one entry per Conv2d_bn weight bank in the .bin blob.
 *
 * tiny_fpga has 30 such banks (L00..L29). The host (sw/runtime/) computes
 * these pointers once at boot from the contiguous /lib/firmware blob and
 * passes the array in via AXI-MM. From PL's perspective, each entry is just
 * three DDR3 base addresses.
 *
 * Vitis HLS supports passing struct-of-pointer arrays through s_axilite IF
 * the struct fits in 64 bits per field — we aggregate {w, bias, out_shift}
 * into one bundle so the dispatcher can index L<NN> with a single load.
 * (Alternative: 30 individual m_axi ports — explodes the IP regmap to >100
 * AXI registers. We pick the array form; M5 might shard if PE pipelining
 * needs per-bank locality.)
 * -------------------------------------------------------------------------- */
typedef struct {
    const sa_i8_t  *w;
    const sa_i32_t *bias;
    const sa_i8_t  *out_shift;
} sa_layer_weights_t;


/* ----------------------------------------------------------------------------
 * sa_tiny_fpga_top — main entry. Chained execution of layers 0..11.
 *
 * @param img_in       int8 [1, 3, H_IMG, W_IMG]   raw RGB
 * @param feat_out     int8 [1, 48, H_DET, W_DET]  to PS for SpikeDetect
 * @param layer_id     -1: run all 11 layers; 0..11: dispatch single layer
 * @param L            sa_layer_weights_t[30] (L00..L29)
 * @param scratch_*    scratch buffers (DDR-resident, see comment up top)
 *
 * Geometry params are fixed for tiny_fpga (H_IMG=256, NC=80) and read from
 * dtypes.h at compile time — no runtime configurability needed.
 * -------------------------------------------------------------------------- */
void sa_tiny_fpga_top(
    const sa_i8_t  *img_in,
          sa_i8_t  *feat_out,
    int             layer_id,
    const sa_layer_weights_t *L,        /* L[30]                              */
          sa_i32_t *scratch_a,          /* large enough for biggest layer out */
          sa_i32_t *scratch_b,          /* same                                */
          sa_i32_t *scratch_c,          /* sppf cv1 mid + acb r_buf            */
          sa_i32_t *scratch_d,          /* acb sep_y_buf                       */
          sa_i32_t *scratch_e,          /* acb ping/pong  (and sppf cat_i32)   */
          sa_i32_t *scratch_f,          /* acb pong_buf   (and sppf scratch)   */
          sa_i8_t  *scratch_spike,      /* shared spike_buf                    */
          sa_i32_t *scratch_acc,        /* shared tmp_acc                      */
          sa_i8_t  *scratch_spk_a,      /* sppf spk_buf                        */
          sa_i8_t  *scratch_spk_b,      /* sppf pool_buf1                      */
          sa_i8_t  *scratch_spk_c,      /* sppf pool_buf2                      */
          sa_i8_t  *scratch_spk_d,      /* sppf pool_buf3                      */
          sa_i8_t  *scratch_spk_e)      /* sppf concat_buf                     */
{
    SA_AXI_MM(img_in,        gmem0, 196608)
    SA_AXI_MM(feat_out,      gmem1, 21504)
    SA_AXI_MM(L,             gmem2, 240)             /* 30 entries * 8 bytes/ptr * 3   */
    SA_AXI_MM(scratch_a,     gmem3, 16777216)
    SA_AXI_MM(scratch_b,     gmem3, 16777216)
    SA_AXI_MM(scratch_c,     gmem3, 16777216)
    SA_AXI_MM(scratch_d,     gmem3, 16777216)
    SA_AXI_MM(scratch_e,     gmem3, 16777216)
    SA_AXI_MM(scratch_f,     gmem3, 16777216)
    SA_AXI_MM(scratch_spike, gmem4, 16777216)
    SA_AXI_MM(scratch_acc,   gmem4, 16777216)
    SA_AXI_MM(scratch_spk_a, gmem4, 16777216)
    SA_AXI_MM(scratch_spk_b, gmem4, 16777216)
    SA_AXI_MM(scratch_spk_c, gmem4, 16777216)
    SA_AXI_MM(scratch_spk_d, gmem4, 16777216)
    SA_AXI_MM(scratch_spk_e, gmem4, 16777216)
    SA_AXI_LITE(layer_id)
    SA_AXI_LITE_RETURN

    /* Tiny_fpga geometry constants (mirrors snn_yolov8_tiny_fpga.yaml). */
    const int T = SA_T_STEPS;          /* 1 */
    const int H_STEM_IN = SA_IMG_H;    /* 256 */
    const int W_STEM_IN = SA_IMG_W;    /* 256 */
    const int C_RGB     = SA_IMG_C;    /* 3 */
    const int H_L1 = 64,  W_L1 = 64,  C_L1 = 24;
    const int H_L3 = 32,  W_L3 = 32,  C_L3 = 48;
    const int H_L6 = 16,  W_L6 = 16,  C_L6 = 96;
    const int H_DET = SA_DETECT_H, W_DET = SA_DETECT_W, C_HEAD = 48;

    const bool run_all = (layer_id < 0);

    /* ----------------- Layer 0: stem ms_downsampling ------------------ */
    if (run_all || layer_id == 0) {
        sa_ms_downsampling(
            img_in, /*x_i32=*/(const sa_i32_t *)0,
            scratch_a,
            L[0].w, L[0].bias, L[0].out_shift,
            scratch_spike, scratch_acc,
            T, C_RGB, C_L1, H_STEM_IN, W_STEM_IN,
            /*K=*/7, /*stride=*/4, /*pad=*/2, /*groups=*/1, /*first_layer=*/1);
        if (!run_all) return;
    }

    /* ----------------- Layer 1: acb1 ms_all_conv_block ---------------- */
    if (run_all || layer_id == 1) {
        sa_ms_all_conv_block(
            scratch_a, scratch_b,
            L[1].w, L[1].bias, L[1].out_shift,
            L[2].w, L[2].bias, L[2].out_shift,
            L[3].w, L[3].bias, L[3].out_shift,
            L[4].w, L[4].bias, L[4].out_shift,
            L[5].w, L[5].bias, L[5].out_shift,
            L[6].w, L[6].bias, L[6].out_shift,
            scratch_c, scratch_d, scratch_e, scratch_f,
            scratch_spike, scratch_acc,
            T, C_L1, /*C_exp=*/48, /*C_mid=*/96, H_L1, W_L1,
            /*K_dw2=*/7, /*K_dw4=*/3, /*pad_dw2=*/3, /*pad_dw4=*/1,
            /*K_c1=*/3, /*pad_c1=*/1, /*K_c2=*/3, /*pad_c2=*/1);
        if (!run_all) return;
    }

    /* ----------------- Layer 2: ds1 ms_downsampling ------------------- */
    if (run_all || layer_id == 2) {
        sa_ms_downsampling(
            (const sa_i8_t *)0, /*x_i32=*/scratch_b,
            scratch_a,
            L[7].w, L[7].bias, L[7].out_shift,
            scratch_spike, scratch_acc,
            T, C_L1, C_L3, H_L1, W_L1,
            /*K=*/3, /*stride=*/2, /*pad=*/1, /*groups=*/1, /*first_layer=*/0);
        if (!run_all) return;
    }

    /* ----------------- Layer 3: acb2a ms_all_conv_block --------------- */
    if (run_all || layer_id == 3) {
        sa_ms_all_conv_block(
            scratch_a, scratch_b,
            L[8].w,  L[8].bias,  L[8].out_shift,
            L[9].w,  L[9].bias,  L[9].out_shift,
            L[10].w, L[10].bias, L[10].out_shift,
            L[11].w, L[11].bias, L[11].out_shift,
            L[12].w, L[12].bias, L[12].out_shift,
            L[13].w, L[13].bias, L[13].out_shift,
            scratch_c, scratch_d, scratch_e, scratch_f,
            scratch_spike, scratch_acc,
            T, C_L3, /*C_exp=*/96, /*C_mid=*/192, H_L3, W_L3,
            /*K_dw2=*/7, /*K_dw4=*/3, /*pad_dw2=*/3, /*pad_dw4=*/1,
            /*K_c1=*/3, /*pad_c1=*/1, /*K_c2=*/3, /*pad_c2=*/1);
        if (!run_all) return;
    }

    /* ----------------- Layer 4: acb2b ms_all_conv_block (re-uses L08..L13) */
    if (run_all || layer_id == 4) {
        sa_ms_all_conv_block(
            scratch_b, scratch_a,                           /* swap in/out */
            L[8].w,  L[8].bias,  L[8].out_shift,
            L[9].w,  L[9].bias,  L[9].out_shift,
            L[10].w, L[10].bias, L[10].out_shift,
            L[11].w, L[11].bias, L[11].out_shift,
            L[12].w, L[12].bias, L[12].out_shift,
            L[13].w, L[13].bias, L[13].out_shift,
            scratch_c, scratch_d, scratch_e, scratch_f,
            scratch_spike, scratch_acc,
            T, C_L3, 96, 192, H_L3, W_L3,
            7, 3, 3, 1,
            3, 1, 3, 1);
        if (!run_all) return;
    }

    /* ----------------- Layer 5: ds2 ms_downsampling ------------------- */
    if (run_all || layer_id == 5) {
        sa_ms_downsampling(
            (const sa_i8_t *)0, scratch_a,
            scratch_b,
            L[14].w, L[14].bias, L[14].out_shift,
            scratch_spike, scratch_acc,
            T, C_L3, C_L6, H_L3, W_L3,
            /*K=*/3, /*stride=*/2, /*pad=*/1, /*groups=*/1, /*first_layer=*/0);
        if (!run_all) return;
    }

    /* ----------------- Layer 6: acb3a ms_all_conv_block --------------- */
    if (run_all || layer_id == 6) {
        sa_ms_all_conv_block(
            scratch_b, scratch_a,
            L[15].w, L[15].bias, L[15].out_shift,
            L[16].w, L[16].bias, L[16].out_shift,
            L[17].w, L[17].bias, L[17].out_shift,
            L[18].w, L[18].bias, L[18].out_shift,
            L[19].w, L[19].bias, L[19].out_shift,
            L[20].w, L[20].bias, L[20].out_shift,
            scratch_c, scratch_d, scratch_e, scratch_f,
            scratch_spike, scratch_acc,
            T, C_L6, /*C_exp=*/192, /*C_mid=*/288, H_L6, W_L6,
            /*K_dw2=*/7, /*K_dw4=*/3, /*pad_dw2=*/3, /*pad_dw4=*/1,
            /*K_c1=*/3, /*pad_c1=*/1, /*K_c2=*/3, /*pad_c2=*/1);
        if (!run_all) return;
    }

    /* ----------------- Layer 7: acb3b ms_all_conv_block (re-uses L15..L20) */
    if (run_all || layer_id == 7) {
        sa_ms_all_conv_block(
            scratch_a, scratch_b,
            L[15].w, L[15].bias, L[15].out_shift,
            L[16].w, L[16].bias, L[16].out_shift,
            L[17].w, L[17].bias, L[17].out_shift,
            L[18].w, L[18].bias, L[18].out_shift,
            L[19].w, L[19].bias, L[19].out_shift,
            L[20].w, L[20].bias, L[20].out_shift,
            scratch_c, scratch_d, scratch_e, scratch_f,
            scratch_spike, scratch_acc,
            T, C_L6, 192, 288, H_L6, W_L6,
            7, 3, 3, 1,
            3, 1, 3, 1);
        if (!run_all) return;
    }

    /* ----------------- Layer 8: sppf spike_sppf ----------------------- */
    if (run_all || layer_id == 8) {
        sa_spike_sppf(
            scratch_b, scratch_a,
            L[21].w, L[21].bias, L[21].out_shift,
            L[22].w, L[22].bias, L[22].out_shift,
            scratch_c,                /* ping_buf  (cv1 mid: T*48*16*16)     */
            scratch_spk_a,            /* spk_buf                              */
            scratch_spk_b,            /* pool_buf1                            */
            scratch_spk_c,            /* pool_buf2                            */
            scratch_spk_d,            /* pool_buf3                            */
            scratch_spk_e,            /* concat_buf                           */
            scratch_e,                /* cat_i32_buf                          */
            scratch_spike, scratch_acc,
            T, C_L6, /*C_mid=*/48, /*C_out=*/C_HEAD, H_DET, W_DET, /*k=*/5);
        if (!run_all) return;
    }

    /* ----------------- Layer 9: head_reduce ms_standard_conv ---------- */
    if (run_all || layer_id == 9) {
        sa_ms_standard_conv_inplace(
            scratch_a, scratch_b,
            L[23].w, L[23].bias, L[23].out_shift,
            scratch_spike, scratch_acc,
            T, C_HEAD, C_HEAD, H_DET, W_DET,
            /*K=*/1, /*stride=*/1, /*pad=*/0, /*groups=*/1);
        if (!run_all) return;
    }

    /* ----------------- Layer 10: head_refine ms_all_conv_block --------- */
    if (run_all || layer_id == 10) {
        sa_ms_all_conv_block(
            scratch_b, scratch_a,
            L[24].w, L[24].bias, L[24].out_shift,
            L[25].w, L[25].bias, L[25].out_shift,
            L[26].w, L[26].bias, L[26].out_shift,
            L[27].w, L[27].bias, L[27].out_shift,
            L[28].w, L[28].bias, L[28].out_shift,
            L[29].w, L[29].bias, L[29].out_shift,
            scratch_c, scratch_d, scratch_e, scratch_f,
            scratch_spike, scratch_acc,
            T, C_HEAD, /*C_exp=*/96, /*C_mid=*/144, H_DET, W_DET,
            /*K_dw2=*/7, /*K_dw4=*/3, /*pad_dw2=*/3, /*pad_dw4=*/1,
            /*K_c1=*/3, /*pad_c1=*/1, /*K_c2=*/3, /*pad_c2=*/1);
        if (!run_all) return;
    }

    /* ----------------- Layer 11: detect (int32 -> int8 cast) ---------- */
    if (run_all || layer_id == 11) {
        sa_detect_head(
            scratch_a, feat_out,
            T, C_HEAD, H_DET, W_DET);
        /* Done — feat_out now holds the int8 head_refine output for PS. */
    }
}

}  /* extern "C" */
