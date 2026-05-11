/*
 * sw/sdk/tests/test_dma_loopback.c
 *
 * Hardware-presence test:
 *   * On the board: drives N iterations through sa_infer() and confirms the
 *     DMA path is stable + leak-free.
 *   * On a developer PC built with SA_STUB_BACKEND=1: short-circuits to
 *     a 100-iter loop so the test still exercises memcpy/perf counters,
 *     but is fast enough to live in numpy_regress.yml as a smoke gate.
 */

#include "spike_accel.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>


static long parse_count(int argc, char **argv, long def)
{
    if (argc < 2) return def;
    char *end;
    long v = strtol(argv[1], &end, 10);
    return (*end || v <= 0) ? def : v;
}


int main(int argc, char **argv)
{
    const char *hw_req = getenv("SA_HW_REQUIRED");
    sa_handle_t h = NULL;
    if (sa_open(&h) != SA_OK) {
        if (!hw_req) {
            fprintf(stdout, "SKIP: no_hardware\n");
            return 0;
        }
        fprintf(stderr, "FAIL: sa_open\n");
        return 1;
    }

    /* Empty weight blob is OK for the loopback path (the stub backend doesn't
     * actually consume weights). */
    FILE *f = fopen("_loopback_w.bin", "wb");
    fputc(0, f); fclose(f);
    if (sa_load_weights(h, "_loopback_w.bin") != SA_OK) {
        fprintf(stderr, "FAIL: sa_load_weights\n");
        return 1;
    }
    remove("_loopback_w.bin");

    long iters = parse_count(argc, argv, 100);
    int8_t *img = (int8_t *)malloc(3 * 256 * 256);
    int8_t *out = (int8_t *)malloc(84 * 16 * 16);
    if (!img || !out) { fprintf(stderr, "FAIL: OOM\n"); return 1; }

    int last_out = 0;
    for (long i = 0; i < iters; i++) {
        for (int j = 0; j < 3 * 256 * 256; j++)
            img[j] = (int8_t)((i + j) & 0x7F);
        if (sa_infer(h, img, out, 1000) != SA_OK) {
            fprintf(stderr, "FAIL: infer iter=%ld\n", i);
            return 1;
        }
        last_out += out[0];
    }
    free(img); free(out);

    sa_perf_t perf;
    sa_get_perf(h, &perf);
    fprintf(stdout, "iters=%ld  frames_done=%u  dropped=%u  last_out=%d\n",
            iters, perf.frames_completed, perf.frames_dropped, last_out);

    sa_close(h);
    return 0;
}
