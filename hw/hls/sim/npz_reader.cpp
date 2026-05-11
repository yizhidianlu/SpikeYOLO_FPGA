/*
 * hw/hls/sim/npz_reader.cpp — implementation of the minimal .npy loader.
 *
 * Format (NumPy v1.0):
 *   off 0   : 6 bytes  magic   "\x93NUMPY"
 *   off 6   : u8       major   (1)
 *   off 7   : u8       minor   (0)
 *   off 8   : u16 LE   header_len
 *   off 10  : ASCII    header dict  (length = header_len, padded with spaces + final \n)
 *   off ... : raw data, C-order, native byteorder
 *
 * We parse the header dict by hand (no Python interpreter, no eval) — it is
 * always a single-line dict with keys 'descr', 'fortran_order', 'shape'.
 * Whitespace is permitted but the only structure we need is:
 *
 *     'descr':     '<dtype>'        e.g. '|i1', '<i4'
 *     'fortran_order': True | False
 *     'shape':     (D0, D1, ...)
 */

#include "npz_reader.h"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace sa_npz {

namespace {

/* Slurp the entire file into a byte buffer. */
std::vector<uint8_t> read_all(const std::string &path)
{
    std::ifstream f(path, std::ios::binary);
    if (!f) {
        throw std::runtime_error("npz_reader: cannot open " + path);
    }
    f.seekg(0, std::ios::end);
    const auto sz = f.tellg();
    if (sz < 0) {
        throw std::runtime_error("npz_reader: tellg failed for " + path);
    }
    f.seekg(0, std::ios::beg);
    std::vector<uint8_t> buf((size_t)sz);
    if (sz > 0) {
        f.read(reinterpret_cast<char *>(buf.data()), sz);
    }
    return buf;
}

/* Find the value associated with `key` in a Python-dict-literal header.
 * Returns the index into `header` of the first non-space byte after the
 * opening quote/colon for that key. Throws if the key is absent.
 */
size_t find_value(const std::string &header, const std::string &key)
{
    /* Look for "'<key>'". The header is small (<=128 bytes typically). */
    const std::string needle = "'" + key + "'";
    size_t pos = header.find(needle);
    if (pos == std::string::npos) {
        throw std::runtime_error("npz_reader: missing key '" + key + "' in npy header");
    }
    pos += needle.size();
    /* Skip whitespace + ':' */
    while (pos < header.size() && (header[pos] == ' ' || header[pos] == ':')) pos++;
    return pos;
}

DType parse_descr(const std::string &header)
{
    size_t pos = find_value(header, "descr");
    if (pos >= header.size() || header[pos] != '\'') {
        throw std::runtime_error("npz_reader: malformed descr");
    }
    size_t end = header.find('\'', pos + 1);
    if (end == std::string::npos) {
        throw std::runtime_error("npz_reader: unterminated descr string");
    }
    const std::string d = header.substr(pos + 1, end - pos - 1);
    /* Accept '|i1', '<i1', '>i1' as INT8. We are on a little-endian host. */
    if (d == "|i1" || d == "<i1" || d == ">i1") return DType::INT8;
    if (d == "<i4" || d == "=i4")               return DType::INT32;
    throw std::runtime_error("npz_reader: unsupported dtype '" + d + "'");
}

bool parse_fortran(const std::string &header)
{
    size_t pos = find_value(header, "fortran_order");
    /* Compare to True/False */
    if (header.compare(pos, 4, "True") == 0)  return true;
    if (header.compare(pos, 5, "False") == 0) return false;
    throw std::runtime_error("npz_reader: malformed fortran_order");
}

std::vector<int64_t> parse_shape(const std::string &header)
{
    size_t pos = find_value(header, "shape");
    if (pos >= header.size() || header[pos] != '(') {
        throw std::runtime_error("npz_reader: malformed shape (no '(')");
    }
    size_t end = header.find(')', pos + 1);
    if (end == std::string::npos) {
        throw std::runtime_error("npz_reader: unterminated shape");
    }
    std::string body = header.substr(pos + 1, end - pos - 1);
    /* tokenise on commas, trim whitespace, ignore empty trailing tokens */
    std::vector<int64_t> dims;
    size_t i = 0;
    while (i < body.size()) {
        while (i < body.size() && (body[i] == ' ' || body[i] == '\t')) i++;
        size_t j = i;
        while (j < body.size() && body[j] != ',') j++;
        std::string tok = body.substr(i, j - i);
        /* trim trailing space */
        while (!tok.empty() && (tok.back() == ' ' || tok.back() == '\t')) tok.pop_back();
        if (!tok.empty()) {
            try {
                dims.push_back((int64_t)std::stoll(tok));
            } catch (...) {
                throw std::runtime_error("npz_reader: bad shape token '" + tok + "'");
            }
        }
        i = j + 1;
    }
    return dims;
}

size_t dtype_bytes(DType d)
{
    switch (d) {
        case DType::INT8:  return 1;
        case DType::INT32: return 4;
        default:           return 0;
    }
}

}  /* anonymous namespace */


Tensor load_npy(const std::string &path)
{
    std::vector<uint8_t> buf = read_all(path);
    if (buf.size() < 10) {
        throw std::runtime_error("npz_reader: file too short: " + path);
    }
    static const uint8_t MAGIC[6] = {0x93, 'N', 'U', 'M', 'P', 'Y'};
    if (std::memcmp(buf.data(), MAGIC, 6) != 0) {
        throw std::runtime_error("npz_reader: bad magic in " + path);
    }
    const uint8_t major = buf[6];
    const uint8_t minor = buf[7];
    if (!(major == 1 && minor == 0)) {
        /* v2.0 uses u32 header_len at offset 8; v3.0 too. We add support
         * later if needed -- explode_npz.py emits v1.0 by default.
         */
        char tmp[64];
        std::snprintf(tmp, sizeof tmp,
                      "npz_reader: only v1.0 supported, got v%u.%u",
                      (unsigned)major, (unsigned)minor);
        throw std::runtime_error(tmp);
    }
    const uint16_t header_len = (uint16_t)buf[8] | ((uint16_t)buf[9] << 8);
    const size_t hdr_start = 10;
    const size_t data_start = hdr_start + header_len;
    if (data_start > buf.size()) {
        throw std::runtime_error("npz_reader: truncated header in " + path);
    }
    std::string header(reinterpret_cast<const char *>(buf.data() + hdr_start),
                       header_len);

    Tensor t;
    t.dtype = parse_descr(header);
    if (parse_fortran(header)) {
        throw std::runtime_error("npz_reader: fortran_order=True not supported (" + path + ")");
    }
    t.shape = parse_shape(header);

    const size_t elem_bytes = dtype_bytes(t.dtype);
    const int64_t numel = t.numel();
    const size_t need = (size_t)numel * elem_bytes;
    if (data_start + need > buf.size()) {
        throw std::runtime_error("npz_reader: data shorter than header claims (" + path + ")");
    }
    t.bytes.assign(buf.data() + data_start, buf.data() + data_start + need);
    return t;
}

}  /* namespace sa_npz */
