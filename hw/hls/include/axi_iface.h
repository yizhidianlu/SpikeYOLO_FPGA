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

/*
 * URGENT_ASK_9 + URGENT_ASK_10 root cause (2026-05-13):
 * The original macros named their formal parameters `port`, `bundle`, `depth`,
 * `dim`, `factor` -- the *same identifiers* used as pragma keywords on the RHS
 * of `=`. The C preprocessor blindly substitutes every matching token, so e.g.
 *   SA_AXI_MM(img_in, gmem0, 196608)
 * expanded to
 *   #pragma HLS INTERFACE m_axi img_in=img_in offset=slave gmem0=gmem0 196608=196608
 * instead of the intended
 *   #pragma HLS INTERFACE m_axi port=img_in offset=slave bundle=gmem0 depth=196608
 * Vitis then emitted [HLS 207-5569] "unexpected pragma parameter 'img_in'" and
 * fell back to default scalar/ap_memory inference -> 0 m_axi in component.xml
 * across V1.0..V1.4. This was NOT a Vitis 2024.1 syntax change; the bare
 * `m_axi` form has been correct all along. The earlier ASK_9 fix (adding
 * `mode=`) made it worse by introducing an additionally invalid keyword.
 *
 * Fix: prefix every macro formal with `_` so it cannot shadow a pragma keyword.
 */

/* AXI-MM master on a named bundle, with `offset=slave` so the runtime can
 * pass DDR3 physical addresses via AXI-Lite.
 */
#define SA_AXI_MM(_port, _bundle, _depth) \
    SA_HLS_PRAGMA(HLS INTERFACE m_axi port=_port offset=slave bundle=_bundle depth=_depth)

/* AXI-Lite register slot. */
#define SA_AXI_LITE(_port) \
    SA_HLS_PRAGMA(HLS INTERFACE s_axilite port=_port bundle=control)

#define SA_AXI_LITE_RETURN \
    SA_HLS_PRAGMA(HLS INTERFACE s_axilite port=return bundle=control)

/* Common pragmas used inside kernels. */
#define SA_PIPELINE_II(_N)   SA_HLS_PRAGMA(HLS PIPELINE II=_N)
#define SA_UNROLL_F(_F)      SA_HLS_PRAGMA(HLS UNROLL factor=_F)
#define SA_UNROLL_FULL       SA_HLS_PRAGMA(HLS UNROLL)
#define SA_INLINE_OFF        SA_HLS_PRAGMA(HLS INLINE off)
#define SA_PART_C(_arr, _dim, _factor) \
    SA_HLS_PRAGMA(HLS ARRAY_PARTITION variable=_arr dim=_dim cyclic factor=_factor)
#define SA_PART_CMPLT(_arr, _dim) \
    SA_HLS_PRAGMA(HLS ARRAY_PARTITION variable=_arr dim=_dim complete)

#endif  /* SA_HLS_AXI_IFACE_H */
