/*
 * hw/hls/sim/npz_reader.h — minimal .npy loader for HLS host-csim testbenches.
 *
 * The companion `tools/ci/explode_npz.py` script unpacks each
 * tests/golden/(asterisk).npz archive into individual .npy files under
 * tests/golden/exploded/<stem>/.
 * This header (+ npz_reader.cpp) reads those .npy files. Supported dtypes:
 *
 *     - int8   ('|i1', '<i1', '>i1')   stored verbatim
 *     - int32  ('<i4')                 native little-endian (we are x86)
 *
 * The reader is intentionally side-effect free and host-only: it never touches
 * AXI / DDR / Vitis APIs and is excluded from synthesis.
 */

#ifndef SA_HLS_SIM_NPZ_READER_H
#define SA_HLS_SIM_NPZ_READER_H

#include <cstdint>
#include <string>
#include <vector>

namespace sa_npz {

enum class DType {
    INT8,
    INT32,
    UNKNOWN,
};

/* Return-value type. The caller owns `data` (a std::vector keeps the storage
 * alive). For scalar tensors `shape` is empty.
 */
struct Tensor {
    DType                dtype = DType::UNKNOWN;
    std::vector<int64_t> shape;
    /* Raw byte buffer; size = element_count * element_bytes. */
    std::vector<uint8_t> bytes;

    int64_t numel() const {
        int64_t n = 1;
        for (int64_t d : shape) n *= d;
        return shape.empty() ? 1 : n;
    }
    const int8_t  *as_i8()  const { return reinterpret_cast<const int8_t  *>(bytes.data()); }
    const int32_t *as_i32() const { return reinterpret_cast<const int32_t *>(bytes.data()); }
};

/* Load a single .npy file from disk. Throws std::runtime_error on parse errors
 * (malformed magic, unsupported dtype, fortran_order=True, header overrun).
 */
Tensor load_npy(const std::string &path);

/* Convenience: explode_dir is the directory created by explode_npz.py
 * (e.g. "tests/golden/exploded/layer_00_stem"); member is "input"/"output"/...
 */
inline Tensor load_npy_member(const std::string &explode_dir,
                              const std::string &member)
{
    return load_npy(explode_dir + "/" + member + ".npy");
}

}  /* namespace sa_npz */

#endif  /* SA_HLS_SIM_NPZ_READER_H */
