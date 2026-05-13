/*
 * spike_accel_w9_smoke.c — Hardware smoke test for the W9 PTQ INT8 firmware
 * (`models/tiny_fpga_int8_real.bin`) running on the M2-W1 bitstream.
 *
 * Owner: shared between C2 (SDK) and the algorithm team (A1). Provides a
 * minimum-viable end-to-end path:
 *
 *   1. sa_open() over UIO + CMA buffers
 *   2. sa_load_weights() from `/lib/firmware/tiny_fpga_int8.bin`
 *   3. sa_get_model_info() consistency check (256x256 RGB, 80 classes)
 *   4. Feed a deterministic input (zero, ramp, or a `.bin` file) through sa_infer()
 *   5. Hash the int8 output tensor (xxh32 / fnv1a) and compare to a golden hash
 *      OR dump the raw bytes to a path so the host can diff against the
 *      numpy_reference.py output produced from the matching `.npz`.
 *
 * Pure-C, links only libspike_accel + libc. Intended as a board-side bring-up
 * tool; the full demo (spike_accel_demo) keeps owning the V4L2 + DRM stack.
 *
 * Build: see CMakeLists.txt for the `spike_accel_w9_smoke` target.
 * Run on board:
 *     ./spike_accel_w9_smoke \
 *         --weights /lib/firmware/tiny_fpga_int8.bin \
 *         --input   /tmp/input_256_256_rgb_int8.bin \
 *         --output  /tmp/feat_out_int8.bin
 *
 * Exit codes:
 *   0  smoke passed (FNV-1a hash matches golden if --golden-hash given,
 *                    otherwise just successful inference + dump)
 *   1  CLI error
 *   2  SDK error (see stderr for sa_strerror)
 *   3  hash mismatch (output diverged from golden)
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "spike_accel.h"

/* ---------- Geometry (Contract 1) ----------
 * Input is INT8 [1, 3, 256, 256] in CHW order, RGB pre-normalised by the
 * PTQ pipeline (tools/quant/ptq_int8.py).
 * Output is INT8 [1, 48, 16, 16] (3 anchors * (4 reg + 80 cls + 4 obj?) packed
 * — exact decoding done by sw/app/src/postproc_nms.cpp; for this smoke test we
 * only care about byte-for-byte determinism, not semantics).
 */
#define INPUT_H            256
#define INPUT_W            256
#define INPUT_C              3
#define INPUT_NBYTES   (INPUT_H * INPUT_W * INPUT_C)        /* 196608        */

#define OUTPUT_H            16
#define OUTPUT_W            16
#define OUTPUT_C            48
#define OUTPUT_NBYTES  (OUTPUT_H * OUTPUT_W * OUTPUT_C)     /*  12288        */


/* ---------- 32-bit FNV-1a, no allocations, deterministic ---------- */
static uint32_t fnv1a32(const void *buf, size_t n) {
    const uint8_t *p = (const uint8_t *)buf;
    uint32_t h = 0x811C9DC5u;
    for (size_t i = 0; i < n; i++) {
        h ^= p[i];
        h *= 0x01000193u;
    }
    return h;
}

/* ---------- Helpers ---------- */
static int read_all(const char *path, void *buf, size_t want, size_t *got) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "[w9-smoke] cannot open %s: %s\n", path, strerror(errno));
        return -1;
    }
    size_t n = fread(buf, 1, want, f);
    if (got) *got = n;
    int rc = (n == want) ? 0 : -1;
    if (rc) {
        fprintf(stderr, "[w9-smoke] short read on %s: got %zu, want %zu\n",
                path, n, want);
    }
    fclose(f);
    return rc;
}

static int write_all(const char *path, const void *buf, size_t n) {
    FILE *f = fopen(path, "wb");
    if (!f) {
        fprintf(stderr, "[w9-smoke] cannot open %s for write: %s\n",
                path, strerror(errno));
        return -1;
    }
    size_t w = fwrite(buf, 1, n, f);
    fclose(f);
    if (w != n) {
        fprintf(stderr, "[w9-smoke] short write on %s: wrote %zu, want %zu\n",
                path, w, n);
        return -1;
    }
    return 0;
}

static void fill_ramp(int8_t *buf, size_t n) {
    /* Deterministic non-trivial pattern: 0, 1, 2, ..., 127, -128, -127, ... */
    for (size_t i = 0; i < n; i++) {
        buf[i] = (int8_t)(i & 0xff);
    }
}

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1.0e6;
}

/* ---------- CLI ---------- */
static const char *USAGE =
    "Usage: spike_accel_w9_smoke [OPTIONS]\n"
    "  --weights PATH       Firmware .bin (default /lib/firmware/tiny_fpga_int8.bin)\n"
    "  --input PATH         INT8 [1,3,256,256] CHW raw bytes (default: ramp pattern)\n"
    "  --output PATH        Dump INT8 feat_out (default /tmp/feat_out_int8.bin)\n"
    "  --golden-hash HEX    Expected FNV-1a32 of feat_out (8 hex digits)\n"
    "  --layer-id N         Single-layer dispatch (default -1 = run all 11)\n"
    "  --timeout-ms MS      sa_infer timeout (default 5000)\n"
    "  --repeat N           Run N iterations for perf measurement (default 1)\n"
    "  --quiet              Suppress per-iter progress\n"
    "  --help\n";

int main(int argc, char **argv) {
    const char *weights_path = "/lib/firmware/tiny_fpga_int8.bin";
    const char *input_path   = NULL;
    const char *output_path  = "/tmp/feat_out_int8.bin";
    const char *golden_hex   = NULL;
    int   layer_id   = -1;
    int   timeout_ms = 5000;
    int   repeat     = 1;
    int   quiet      = 0;

    static struct option longopts[] = {
        {"weights",      required_argument, 0, 'w'},
        {"input",        required_argument, 0, 'i'},
        {"output",       required_argument, 0, 'o'},
        {"golden-hash",  required_argument, 0, 'g'},
        {"layer-id",     required_argument, 0, 'l'},
        {"timeout-ms",   required_argument, 0, 't'},
        {"repeat",       required_argument, 0, 'r'},
        {"quiet",        no_argument,       0, 'q'},
        {"help",         no_argument,       0, 'h'},
        {0, 0, 0, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "w:i:o:g:l:t:r:qh", longopts, NULL)) != -1) {
        switch (opt) {
            case 'w': weights_path = optarg; break;
            case 'i': input_path   = optarg; break;
            case 'o': output_path  = optarg; break;
            case 'g': golden_hex   = optarg; break;
            case 'l': layer_id     = atoi(optarg); break;
            case 't': timeout_ms   = atoi(optarg); break;
            case 'r': repeat       = atoi(optarg); break;
            case 'q': quiet        = 1; break;
            case 'h': fputs(USAGE, stdout); return 0;
            default:  fputs(USAGE, stderr); return 1;
        }
    }

    fprintf(stderr, "[w9-smoke] libspike_accel %s\n", sa_version());
    fprintf(stderr, "[w9-smoke] weights = %s\n", weights_path);
    fprintf(stderr, "[w9-smoke] layer_id = %d, timeout = %d ms, repeat = %d\n",
            layer_id, timeout_ms, repeat);

    sa_handle_t h = NULL;
    sa_status_t rc;

    rc = sa_open(&h);
    if (rc != SA_OK) {
        fprintf(stderr, "[w9-smoke] sa_open failed: %s\n", sa_strerror(rc));
        return 2;
    }

    rc = sa_load_weights(h, weights_path);
    if (rc != SA_OK) {
        fprintf(stderr, "[w9-smoke] sa_load_weights(%s) failed: %s\n",
                weights_path, sa_strerror(rc));
        sa_close(h);
        return 2;
    }

    sa_model_info_t info;
    rc = sa_get_model_info(h, &info);
    if (rc != SA_OK) {
        fprintf(stderr, "[w9-smoke] sa_get_model_info failed: %s\n", sa_strerror(rc));
        sa_close(h);
        return 2;
    }
    fprintf(stderr, "[w9-smoke] model: %ux%u RGB%u, %u classes, out %ux%u stride %u\n",
            info.input_w, info.input_h, info.input_c, info.num_classes,
            info.output_w, info.output_h, info.output_stride);
    if (info.input_h != INPUT_H || info.input_w != INPUT_W || info.input_c != INPUT_C) {
        fprintf(stderr, "[w9-smoke] WARN: model dims differ from compiled-in geometry\n");
    }

    if (layer_id >= 0) {
        rc = sa_set_layer_id(h, layer_id);
        if (rc != SA_OK) {
            fprintf(stderr, "[w9-smoke] sa_set_layer_id(%d) failed: %s\n",
                    layer_id, sa_strerror(rc));
            sa_close(h);
            return 2;
        }
    }

    int8_t *img_in   = (int8_t *)malloc(INPUT_NBYTES);
    int8_t *feat_out = (int8_t *)malloc(OUTPUT_NBYTES);
    if (!img_in || !feat_out) {
        fprintf(stderr, "[w9-smoke] OOM on host-side scratch buffers\n");
        free(img_in); free(feat_out); sa_close(h);
        return 2;
    }

    if (input_path) {
        if (read_all(input_path, img_in, INPUT_NBYTES, NULL) < 0) {
            free(img_in); free(feat_out); sa_close(h);
            return 1;
        }
        fprintf(stderr, "[w9-smoke] input loaded from %s (%d bytes)\n",
                input_path, INPUT_NBYTES);
    } else {
        fill_ramp(img_in, INPUT_NBYTES);
        fprintf(stderr, "[w9-smoke] input = deterministic ramp pattern\n");
    }

    /* Hash input so logs let host compare what's being fed. */
    fprintf(stderr, "[w9-smoke] input fnv1a32  = 0x%08" PRIx32 "\n",
            fnv1a32(img_in, INPUT_NBYTES));

    uint32_t out_hash = 0;
    double total_ms  = 0.0;
    for (int it = 0; it < repeat; it++) {
        double t0 = now_ms();
        rc = sa_infer(h, img_in, feat_out, timeout_ms);
        double dt = now_ms() - t0;
        total_ms += dt;
        if (rc != SA_OK) {
            fprintf(stderr, "[w9-smoke] sa_infer iter %d failed: %s\n",
                    it, sa_strerror(rc));
            free(img_in); free(feat_out); sa_close(h);
            return 2;
        }
        out_hash = fnv1a32(feat_out, OUTPUT_NBYTES);
        if (!quiet) {
            fprintf(stderr, "[w9-smoke] iter %3d: %7.2f ms, out fnv1a32 = 0x%08" PRIx32 "\n",
                    it, dt, out_hash);
        }
    }

    if (output_path && write_all(output_path, feat_out, OUTPUT_NBYTES) == 0) {
        fprintf(stderr, "[w9-smoke] feat_out dumped to %s (%d bytes)\n",
                output_path, OUTPUT_NBYTES);
    }

    sa_perf_t perf;
    if (sa_get_perf(h, &perf) == SA_OK) {
        fprintf(stderr, "[w9-smoke] perf: compute=%" PRIu64 " dma_in=%" PRIu64
                " dma_out=%" PRIu64 " frames=%u dropped=%u\n",
                perf.cycles_compute, perf.cycles_dma_in, perf.cycles_dma_out,
                perf.frames_completed, perf.frames_dropped);
    }

    fprintf(stderr, "[w9-smoke] avg latency = %.2f ms over %d iter\n",
            total_ms / (repeat ? repeat : 1), repeat);

    free(img_in);
    free(feat_out);
    sa_close(h);

    /* Golden hash gate. Format: 8-hex-digit FNV-1a32 (lowercase, no 0x). */
    if (golden_hex) {
        uint32_t expected = (uint32_t)strtoul(golden_hex, NULL, 16);
        if (out_hash != expected) {
            fprintf(stderr, "[w9-smoke] ✗ GOLDEN MISMATCH: got 0x%08" PRIx32
                    ", expected 0x%08" PRIx32 "\n", out_hash, expected);
            return 3;
        }
        fprintf(stderr, "[w9-smoke] ✓ golden hash matched (0x%08" PRIx32 ")\n",
                out_hash);
    } else {
        fprintf(stderr, "[w9-smoke] ✓ end-to-end inference OK "
                "(no golden hash provided; baseline = 0x%08" PRIx32 ")\n",
                out_hash);
    }
    return 0;
}
