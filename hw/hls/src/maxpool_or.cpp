/*
 * hw/hls/src/maxpool_or.cpp — k×k max-pool on a binary spike tensor.
 *
 * Mirrors tools/fpga/numpy_reference.maxpool2d_spike. For binary {0,1}
 * inputs, max-pool reduces to a bitwise OR over the kxk receptive field.
 * On the FPGA this avoids any DSP multiply and synthesises into a simple
 * OR-reduction tree.
 *
 * Padding: same-padding (pad = k // 2) — matches the PyTorch reference.
 */

#include "dtypes.h"
#include "axi_iface.h"

extern "C" {

void sa_maxpool_or(
    const sa_i8_t *x_in,
          sa_i8_t *y_out,
    int T,
    int C,
    int H,
    int W,
    int K)
{
    SA_AXI_MM(x_in,  gmem0, 4194304)
    SA_AXI_MM(y_out, gmem1, 4194304)
    SA_AXI_LITE(T)  SA_AXI_LITE(C)  SA_AXI_LITE(H)  SA_AXI_LITE(W)
    SA_AXI_LITE(K)
    SA_AXI_LITE_RETURN

    const int pad = K / 2;

    for (int t = 0; t < T; t++) {
        for (int c = 0; c < C; c++) {
            for (int hy = 0; hy < H; hy++) {
                for (int wx = 0; wx < W; wx++) {
                    SA_PIPELINE_II(1)
                    sa_i8_t acc = 0;
                    for (int ky = 0; ky < K; ky++) {
                        for (int kx = 0; kx < K; kx++) {
                            const int h_in = hy + ky - pad;
                            const int w_in = wx + kx - pad;
                            if (h_in >= 0 && h_in < H && w_in >= 0 && w_in < W) {
                                const sa_i8_t v =
                                    x_in[((t * C + c) * H + h_in) * W + w_in];
                                if (v > acc) acc = v;
                            }
                        }
                    }
                    y_out[((t * C + c) * H + hy) * W + wx] = acc;
                }
            }
        }
    }
}

}  /* extern "C" */
