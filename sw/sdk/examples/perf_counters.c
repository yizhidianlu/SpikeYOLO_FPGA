/*
 * perf_counters.c -- 100-frame perf sweep + periodic sa_get_perf dump.
 *
 * Prints a header line then one row per 10 frames containing cumulative
 * cycle counters and the rolling FPS estimate. Demonstrates sa_reset_perf
 * + the v1.1.0 last_layer_id / last_layer_mask telemetry fields.
 */

#include "spike_accel.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define IMG_BYTES   (3 * 256 * 256)
#define OUT_BYTES   (84 * 16 * 16)

/* Wall-clock helper in microseconds. Integer math only -- MinGW gcc 5.3
 * ICEs on `tv_sec + tv_nsec*1e-9` style double promotion in this file. */
static long long now_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000LL + (long long)ts.tv_nsec / 1000LL;
}

int main(void)
{
    sa_handle_t h = NULL;
    if (sa_open(&h) != SA_OK) return 1;
    FILE *f = fopen("_perf.bin", "wb"); char z[1024]={0};
    fwrite(z,1,sizeof(z),f); fclose(f);
    sa_load_weights(h, "_perf.bin"); remove("_perf.bin");
    sa_reset_perf(h);

    int8_t *img = calloc(1, IMG_BYTES);
    int8_t *out = calloc(1, OUT_BYTES);
    if (!img || !out) { sa_close(h); return 1; }

    printf("%-6s %-12s %-12s %-12s %-7s %-7s %-6s\n",
           "frame", "cyc_compute", "cyc_dma_in", "cyc_dma_out",
           "done", "drop", "fps");

    long long t_start = now_us();
    for (int i = 1; i <= 100; i++) {
        img[i % IMG_BYTES] = (int8_t)i;            /* vary input slightly */
        if (sa_infer(h, img, out, 200) != SA_OK) {
            fprintf(stderr, "infer frame %d failed\n", i);
        }
        if (i % 10 == 0) {
            sa_perf_t p; sa_get_perf(h, &p);
            long long el_us = now_us() - t_start;
            unsigned long long fps_x10 =
                (el_us > 0) ? (unsigned long long)i * 10000000ULL
                                 / (unsigned long long)el_us
                            : 0ULL;
            printf("%-6d %-12llu %-12llu %-12llu %-7u %-7u %llu.%llu\n",
                   i, (unsigned long long)p.cycles_compute,
                   (unsigned long long)p.cycles_dma_in,
                   (unsigned long long)p.cycles_dma_out,
                   p.frames_completed, p.frames_dropped,
                   fps_x10 / 10, fps_x10 % 10);
        }
    }

    sa_perf_t p; sa_get_perf(h, &p);
    printf("final: layer_id=%d mask=0x%03x done=%u drop=%u\n",
           p.last_layer_id, p.last_layer_mask,
           p.frames_completed, p.frames_dropped);

    free(img); free(out); sa_close(h);
    return 0;
}
