/*
 * sw/app/src/postproc_nms_cli.cpp — tiny CLI wrapper around postproc_nms.
 *
 * Reads a raw INT8 detect-head buffer ((nc+4)*H*W) from --input, runs
 * decode_and_nms() with the given --iou / --conf, and writes the kept
 * detections as JSON to --out. Used by tests/test_postproc_nms_consistency.py
 * to compare the C++ NMS impl against the Python reference bit-by-bit.
 *
 * Argv:
 *   --input  <int8.bin>     mandatory; size = (nc+4)*grid_h*grid_w
 *   --out    <json>         mandatory
 *   --iou    <float>        default 0.45
 *   --conf   <float>        default 0.25
 *   --nc     <int>          default 80
 *   --grid   <int>          default 16 (square grid)
 *   --stride <int>          default 16
 *   --allow-class <int>     repeatable; restrict argmax to these class ids.
 *                           Used for PBT demo (only emit person/bus/train).
 *
 * Output JSON shape:
 *   {"detections": [{"x1":F,"y1":F,"x2":F,"y2":F,"conf":F,"cls":I}, ...]}
 */

#include "postproc_nms.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

int main(int argc, char **argv)
{
    std::string in_path, out_path;
    float iou = 0.45f, conf = 0.25f;
    int nc = 80, grid = 16, stride = 16;
    std::vector<int> allow;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if      (a == "--input"        && i + 1 < argc) in_path  = argv[++i];
        else if (a == "--out"          && i + 1 < argc) out_path = argv[++i];
        else if (a == "--iou"          && i + 1 < argc) iou      = (float)std::atof(argv[++i]);
        else if (a == "--conf"         && i + 1 < argc) conf     = (float)std::atof(argv[++i]);
        else if (a == "--nc"           && i + 1 < argc) nc       = std::atoi(argv[++i]);
        else if (a == "--grid"         && i + 1 < argc) grid     = std::atoi(argv[++i]);
        else if (a == "--stride"       && i + 1 < argc) stride   = std::atoi(argv[++i]);
        else if (a == "--allow-class"  && i + 1 < argc) allow.push_back(std::atoi(argv[++i]));
    }
    if (in_path.empty() || out_path.empty()) {
        std::fprintf(stderr, "usage: postproc_nms_cli --input <bin> --out <json>"
                             " [--iou F] [--conf F] [--nc N] [--grid N] [--stride N]"
                             " [--allow-class N ...]\n");
        return 2;
    }
    const size_t expected = (size_t)(nc + 4) * grid * grid;
    std::ifstream f(in_path, std::ios::binary);
    if (!f) { std::fprintf(stderr, "cannot open %s\n", in_path.c_str()); return 1; }
    std::vector<int8_t> buf(expected);
    f.read(reinterpret_cast<char *>(buf.data()), expected);
    if ((size_t)f.gcount() != expected) {
        std::fprintf(stderr, "short read: got %lld, want %zu\n",
                     (long long)f.gcount(), expected);
        return 1;
    }
    auto dets = sa_app::decode_and_nms(buf.data(), nc, grid, grid, stride, conf, iou,
                                       1.0f / 64.0f, allow.empty() ? nullptr : &allow);

    std::FILE *o = std::fopen(out_path.c_str(), "wb");
    if (!o) { std::fprintf(stderr, "cannot write %s\n", out_path.c_str()); return 1; }
    std::fprintf(o, "{\"detections\":[");
    for (size_t k = 0; k < dets.size(); ++k) {
        const auto &d = dets[k];
        std::fprintf(o, "%s{\"x1\":%.6f,\"y1\":%.6f,\"x2\":%.6f,\"y2\":%.6f,"
                        "\"conf\":%.6f,\"cls\":%d}",
                     k ? "," : "", d.x1, d.y1, d.x2, d.y2, d.conf, d.cls);
    }
    std::fprintf(o, "]}\n");
    std::fclose(o);
    return 0;
}
