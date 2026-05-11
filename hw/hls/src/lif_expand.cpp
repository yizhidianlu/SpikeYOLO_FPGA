/*
 * hw/hls/src/lif_expand.cpp — I-LIF + MultiSpike4 + cumulative binary expansion.
 *
 * Mirrors numpy_reference.py::mem_update + expand_cumulative line-for-line:
 *
 *   mem = x.sum(axis=0)                             # collapse T
 *   spike = clip(mem, 0, MAX_SPIKE)                 # int8 in [0, 4]
 *   binary = expand_cumulative(spike)               # MAX_SPIKE binary substeps
 *
 * Input  : int32 [T, C, H, W]
 * Output : int8  [T * MAX_SPIKE, C, H, W]   values in {0, 1}
 */

#include "dtypes.h"
#include "axi_iface.h"

#include <cstdint>

extern "C" {

void sa_lif_expand(
    const sa_i32_t *x_in,
          sa_i8_t  *spike_out,
    int T,
    int C,
    int H,
    int W)
{
    SA_AXI_MM(x_in,      gmem0, 16777216)
    SA_AXI_MM(spike_out, gmem1, 16777216)
    SA_AXI_LITE(T)  SA_AXI_LITE(C)  SA_AXI_LITE(H)  SA_AXI_LITE(W)
    SA_AXI_LITE_RETURN

    const int spatial = H * W;

    for (int c = 0; c < C; c++) {
        for (int sp = 0; sp < spatial; sp++) {
            SA_PIPELINE_II(1)

            /* Sum over time axis. */
            sa_i32_t mem = 0;
            for (int t = 0; t < T; t++) {
                mem += x_in[((t * C + c) * H + sp / W) * W + (sp % W)];
            }
            /* Clamp to [0, MAX_SPIKE]. */
            sa_i32_t v = mem;
            if (v < 0)            v = 0;
            else if (v > SA_MAX_SPIKE) v = SA_MAX_SPIKE;
            const int n = (int)v;

            /* Cumulative expansion: first n substeps = 1, rest = 0.
             * Output layout: [substep, C, H, W] (substep is the new outer T axis).
             */
            for (int s = 0; s < SA_MAX_SPIKE; s++) {
                spike_out[((s * C + c) * H + sp / W) * W + (sp % W)] =
                    (s < n) ? (sa_i8_t)1 : (sa_i8_t)0;
            }
        }
    }
}

}  /* extern "C" */
