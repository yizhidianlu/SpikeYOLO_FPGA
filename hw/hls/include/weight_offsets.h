/* hw/hls/include/weight_offsets.h
 *
 * Compile-time weight pool offsets for tiny_fpga (30 weight banks L00..L29).
 * Generated from models/exploded/L*.{w,bias,out_shift}.npy by
 *   tools/ci/gen_weight_offsets.py
 *
 * V1.3 (per URGENT_ASK_6 STOP_step3_summary, 6/6 csynth fail):
 * Vitis HLS 2024.1 demotes any top-arg pointer that the body does
 * pointer-arithmetic on (cast / +offset). Compile-time const arrays
 * sidestep that — kernel uses w_pool[SA_W_OFF[i]] with i and SA_W_OFF[i]
 * both compile-time, so Vitis sees a simple m_axi array read.
 *
 * Pool layout (no header prefix; layer i data starts at SA_*_OFF[i]):
 *   w_pool[ ~982 KB] = [L00.w | L01.w | ... | L29.w]
 *   bias_pool[~10 KB i32] = [L00.bias | ...]
 *   shift_pool[~2.5 KB] = [L00.out_shift | ...]
 *
 * Regenerate (if A1 .npz layout changes):
 *   python tools/ci/gen_weight_offsets.py > hw/hls/include/weight_offsets.h
 */
#ifndef SA_WEIGHT_OFFSETS_H
#define SA_WEIGHT_OFFSETS_H

#define SA_NUM_WEIGHT_BANKS 30

#define SA_W_POOL_BYTES   981648   /* total w bytes across L00..L29 */
#define SA_B_POOL_I32     2544     /* total bias int32 elems across L00..L29 */
#define SA_S_POOL_BYTES   2544     /* total out_shift bytes across L00..L29 */

static const int SA_W_OFF[30] = {
    0,      3528,   4680,   7032,   8184,   8400,   29136,  49872,
    60240,  64848,  69552,  74160,  74592,  157536, 240480, 281952,
    300384, 309792, 328224, 329088, 577920, 826752, 831360, 840576,
    842880, 847488, 852192, 856800, 857232, 919440
};

static const int SA_B_OFF[30] = {
    0,    24,   72,   120,  144,  168,  264,  288,
    336,  432,  528,  576,  624,  816,  864,  960,
    1152, 1344, 1440, 1536, 1824, 1920, 1968, 2016,
    2064, 2160, 2256, 2304, 2352, 2496
};

static const int SA_S_OFF[30] = {
    0,    24,   72,   120,  144,  168,  264,  288,
    336,  432,  528,  576,  624,  816,  864,  960,
    1152, 1344, 1440, 1536, 1824, 1920, 1968, 2016,
    2064, 2160, 2256, 2304, 2352, 2496
};

#endif /* SA_WEIGHT_OFFSETS_H */
