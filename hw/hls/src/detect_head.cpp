/*
 * hw/hls/src/detect_head.cpp — Layer 11 "detect" PL stub.
 *
 * Per A2 v1.0.2 contract (and tools/verify/extract_golden.py L259-262, plus
 * tools/fpga/numpy_reference.py:TinyFpgaNet.forward_head comment "Final
 * SpikeDetect runs on PS, not here"), the PL side of the detect head is just
 * a memcpy that truncates the head_refine int32 output down to int8 with
 * NumPy's `arr.astype(np.int8)` semantics (modular wrap on overflow).
 *
 * The real Detect head (cv2 reg / cv3 cls / DFL / sigmoid / NMS) runs on PS:
 *   - reg branch  : L30 (48->64) -> L31 (64->64) -> L32 (64->64,1x1)
 *   - cls branch  : L33 (48->80) -> L34 (80->80) -> L35 (80->80,1x1)
 *   - DFL kernel  : L36 (16->1, 1x1, applied to 4 reg sub-bins)
 * C3's post-processing pipeline owns those, see docs/CONTRACTS.md L122-127
 * (v1.0.2). PL just hands back the [1, 48, 16, 16] int8 feature map.
 *
 * Why a separate kernel and not a memcpy in tiny_fpga_top? Because B2's IP
 * stitcher needs every layer to be a discrete schedulable IP block (one
 * AXI-MM master per port, one s_axilite control reg). Wrapping the cast as
 * sa_detect_head keeps the per-layer dispatch in tiny_fpga_top uniform.
 *
 * === Resource estimate (paper) ===
 * DSP48:    0       (no MAC; pure int32 -> int8 truncation)
 * BRAM 36K: 0       (streamed memcpy, no on-chip scratch)
 * LUT:      ~80     (loop counter + AXI burst FSM)
 * FF:       ~120    (AXI-MM addr regs + 32-bit input flop)
 * estimated cycles per call: N*C*H*W (1*48*16*16 = ~12 K, II=1 inner loop)
 */

#include "dtypes.h"
#include "axi_iface.h"

extern "C" {

/* @param x_in  int32 [N, C, H, W]   (typically [1, 48, 16, 16] from head_refine)
 * @param y_out int8  [N, C, H, W]   astype(int8) (NumPy modular wrap)
 * @param N, C, H, W   geometry; N is the batch axis (T=1 for tiny_fpga).
 *
 * Truncation is the same as NumPy's int32 -> int8 cast: keep the low 8 bits.
 * This matches `tools/verify/extract_golden.py` line 262 exactly:
 *     dump(11, "detect", "detect", in_arr=x, out_arr=x.astype(np.int8))
 */
void sa_detect_head(
    const sa_i32_t *x_in,
          sa_i8_t  *y_out,
    int N,
    int C,
    int H,
    int W)
{
    SA_AXI_MM(x_in,  gmem0, 16777216)
    SA_AXI_MM(y_out, gmem1, 16777216)
    SA_AXI_LITE(N) SA_AXI_LITE(C) SA_AXI_LITE(H) SA_AXI_LITE(W)
    SA_AXI_LITE_RETURN

    const int n_total = N * C * H * W;
    for (int i = 0; i < n_total; i++) {
        SA_PIPELINE_II(1)
        /* NumPy astype(int8): keep low 8 bits, sign-extend on read.
         * Casting (int32 -> int8) in C++ is implementation-defined for
         * out-of-range values, but on every supported toolchain (gcc / clang
         * / msvc / Vitis HLS) it is the obvious 2's-complement truncation
         * that NumPy also uses. */
        const sa_i32_t v = x_in[i];
        y_out[i] = (sa_i8_t)(v & 0xFF);
    }
}

}  /* extern "C" */
