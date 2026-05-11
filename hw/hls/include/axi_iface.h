/*
 * hw/hls/include/axi_iface.h — Helpers for declaring AXI interfaces.
 *
 * When compiled under Vitis HLS we emit real #pragma HLS INTERFACE lines.
 * Under native g++ (testbench), the macros expand to nothing so the same
 * sources compile.
 */

#ifndef SA_HLS_AXI_IFACE_H
#define SA_HLS_AXI_IFACE_H

#if defined(__SYNTHESIS__) || defined(SA_USE_HLS)
    #define SA_HLS_PRAGMA(x) _Pragma(#x)
#else
    #define SA_HLS_PRAGMA(x)
#endif

/* AXI-MM master on a named bundle, with `offset=slave` so the runtime can
 * pass DDR3 physical addresses via AXI-Lite.
 */
#define SA_AXI_MM(port, bundle, depth) \
    SA_HLS_PRAGMA(HLS INTERFACE m_axi port=port offset=slave bundle=bundle depth=depth)

/* AXI-Lite register slot. */
#define SA_AXI_LITE(port) \
    SA_HLS_PRAGMA(HLS INTERFACE s_axilite port=port bundle=control)

#define SA_AXI_LITE_RETURN \
    SA_HLS_PRAGMA(HLS INTERFACE s_axilite port=return bundle=control)

/* Common pragmas used inside kernels. */
#define SA_PIPELINE_II(N)   SA_HLS_PRAGMA(HLS PIPELINE II=N)
#define SA_UNROLL_F(F)      SA_HLS_PRAGMA(HLS UNROLL factor=F)
#define SA_UNROLL_FULL      SA_HLS_PRAGMA(HLS UNROLL)
#define SA_INLINE_OFF       SA_HLS_PRAGMA(HLS INLINE off)
#define SA_PART_C(arr, dim, factor) \
    SA_HLS_PRAGMA(HLS ARRAY_PARTITION variable=arr dim=dim cyclic factor=factor)
#define SA_PART_CMPLT(arr, dim) \
    SA_HLS_PRAGMA(HLS ARRAY_PARTITION variable=arr dim=dim complete)

#endif  /* SA_HLS_AXI_IFACE_H */
