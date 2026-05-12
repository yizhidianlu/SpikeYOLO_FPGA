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
    /* Per Remote Claude URGENT_ASK_3 Plan β: HLS 2024.1 rejects struct-of-
     * pointers as top arg (HLS 214-298, fires in source analysis before
     * DISAGGREGATE pragma can apply). Replace L with 3 pointer-to-pointer
     * args; in-memory layout is still struct-of-pointer arrays on the
     * host side (A1 Contract 1 unchanged), only the IP signature differs. */
    const sa_i8_t  *const *L_w,         /* L_w[30]     each -> per-layer weights      */
    const sa_i32_t *const *L_bias,      /* L_bias[30]  each -> per-layer bias         */
    const sa_i8_t  *const *L_shift,     /* L_shift[30] each -> per-layer out_shift    */
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
    /* Plan β: 3 individual m_axi for pointer arrays (was struct-of-ptr L).
     * Each L_w/L_bias/L_shift is a 30-entry array of pointers (240 B each). */
    SA_AXI_MM(L_w,           gmem2, 30)
    SA_AXI_MM(L_bias,        gmem2, 30)
    SA_AXI_MM(L_shift,       gmem2, 30)
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
            L_w[0], L_bias[0], L_shift[0],
            scratch_spike, scratch_acc,
            T, C_RGB, C_L1, H_STEM_IN, W_STEM_IN,
            /*K=*/7, /*stride=*/4, /*pad=*/2, /*groups=*/1, /*first_layer=*/1);
        if (!run_all) return;
    }

    /* ----------------- Layer 1: acb1 ms_all_conv_block ---------------- */
    if (run_all || layer_id == 1) {
        sa_ms_all_conv_block(
            scratch_a, scratch_b,
            L_w[1], L_bias[1], L_shift[1],
            L_w[2], L_bias[2], L_shift[2],
            L_w[3], L_bias[3], L_shift[3],
            L_w[4], L_bias[4], L_shift[4],
            L_w[5], L_bias[5], L_shift[5],
            L_w[6], L_bias[6], L_shift[6],
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
            L_w[7], L_bias[7], L_shift[7],
            scratch_spike, scratch_acc,
            T, C_L1, C_L3, H_L1, W_L1,
            /*K=*/3, /*stride=*/2, /*pad=*/1, /*groups=*/1, /*first_layer=*/0);
        if (!run_all) return;
    }

    /* ----------------- Layer 3: acb2a ms_all_conv_block --------------- */
    if (run_all || layer_id == 3) {
        sa_ms_all_conv_block(
            scratch_a, scratch_b,
            L_w[8],  L_bias[8],  L_shift[8],
            L_w[9],  L_bias[9],  L_shift[9],
            L_w[10], L_bias[10], L_shift[10],
            L_w[11], L_bias[11], L_shift[11],
            L_w[12], L_bias[12], L_shift[12],
            L_w[13], L_bias[13], L_shift[13],
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
            L_w[8],  L_bias[8],  L_shift[8],
            L_w[9],  L_bias[9],  L_shift[9],
            L_w[10], L_bias[10], L_shift[10],
            L_w[11], L_bias[11], L_shift[11],
            L_w[12], L_bias[12], L_shift[12],
            L_w[13], L_bias[13], L_shift[13],
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
            L_w[14], L_bias[14], L_shift[14],
            scratch_spike, scratch_acc,
            T, C_L3, C_L6, H_L3, W_L3,
            /*K=*/3, /*stride=*/2, /*pad=*/1, /*groups=*/1, /*first_layer=*/0);
        if (!run_all) return;
    }

    /* ----------------- Layer 6: acb3a ms_all_conv_block --------------- */
    if (run_all || layer_id == 6) {
        sa_ms_all_conv_block(
            scratch_b, scratch_a,
            L_w[15], L_bias[15], L_shift[15],
            L_w[16], L_bias[16], L_shift[16],
            L_w[17], L_bias[17], L_shift[17],
            L_w[18], L_bias[18], L_shift[18],
            L_w[19], L_bias[19], L_shift[19],
            L_w[20], L_bias[20], L_shift[20],
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
            L_w[15], L_bias[15], L_shift[15],
            L_w[16], L_bias[16], L_shift[16],
            L_w[17], L_bias[17], L_shift[17],
            L_w[18], L_bias[18], L_shift[18],
            L_w[19], L_bias[19], L_shift[19],
            L_w[20], L_bias[20], L_shift[20],
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
            L_w[21], L_bias[21], L_shift[21],
            L_w[22], L_bias[22], L_shift[22],
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
            L_w[23], L_bias[23], L_shift[23],
            scratch_spike, scratch_acc,
            T, C_HEAD, C_HEAD, H_DET, W_DET,
            /*K=*/1, /*stride=*/1, /*pad=*/0, /*groups=*/1);
        if (!run_all) return;
    }

    /* ----------------- Layer 10: head_refine ms_all_conv_block --------- */
    if (run_all || layer_id == 10) {
        sa_ms_all_conv_block(
            scratch_b, scratch_a,
            L_w[24], L_bias[24], L_shift[24],
            L_w[25], L_bias[25], L_shift[25],
            L_w[26], L_bias[26], L_shift[26],
            L_w[27], L_bias[27], L_shift[27],
            L_w[28], L_bias[28], L_shift[28],
            L_w[29], L_bias[29], L_shift[29],
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
