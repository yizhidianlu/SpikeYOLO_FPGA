/*
 * hw/hls/include/dtypes.h — fixed-width types + constants shared by all
 * HLS kernels in this project.
 *
 * Falls back to <cstdint> when not compiled under Vitis HLS so the same
 * sources can be unit-tested with a plain g++ tool-chain (testbench mode).
 */

#ifndef SA_HLS_DTYPES_H
#define SA_HLS_DTYPES_H

#if defined(__SYNTHESIS__) || defined(SA_USE_HLS)
    #include <ap_int.h>
    typedef ap_int<8>   sa_i8_t;
    typedef ap_int<32>  sa_i32_t;
    typedef ap_uint<8>  sa_u8_t;
    typedef ap_uint<32> sa_u32_t;
#else
    #include <cstdint>
    typedef std::int8_t   sa_i8_t;
    typedef std::int32_t  sa_i32_t;
    typedef std::uint8_t  sa_u8_t;
    typedef std::uint32_t sa_u32_t;
#endif

/* Constants — must stay in sync with tools/fpga/numpy_reference.py */
#define SA_T_STEPS    1     /* tiny_fpga T = 1                                */
#define SA_MAX_SPIKE  4     /* MultiSpike4 — clamp(mem, 0, 4)                 */
#define SA_CO_TILE    16    /* PE array C_out tile                            */
#define SA_CI_TILE    8     /* PE array C_in  tile                            */

/* tiny_fpga model dimensions (must match snn_yolov8_tiny_fpga.yaml) */
#define SA_IMG_H      256
#define SA_IMG_W      256
#define SA_IMG_C      3
#define SA_DETECT_H   16
#define SA_DETECT_W   16
#define SA_NC         80
#define SA_DETECT_C   (SA_NC + 4)   /* class + bbox channels                  */

/* Layer kind enum — same numeric values as KIND_TO_ENUM in
 * tools/quant/weight_packer.py. Kept in lock-step by tests/test_layer_enum.py
 * (TODO: enforce by parsing the python file in CI).
 */
#define SA_KIND_CONV2D_BN    0
#define SA_KIND_MS_DOWN      1
#define SA_KIND_SEP_CONV     2
#define SA_KIND_MS_STANDARD  3
#define SA_KIND_MAXPOOL      4
#define SA_KIND_SPPF         5
#define SA_KIND_DETECT       6

#endif  /* SA_HLS_DTYPES_H */
