/*
 * infer_one_frame.c -- end-to-end single-frame inference.
 *
 * Generates a deterministic INT8 input pattern, runs one sa_infer with a
 * 33 ms timeout (~30 FPS budget), prints output min/max/mean stats. Uses a
 * scratch weight blob so the stub backend has something to load.
 */

#include "spike_accel.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IMG_BYTES   (3 * 256 * 256)
#define OUT_BYTES   (84 * 16 * 16)
#define WEIGHT_BLOB "_infer_one_frame_weights.bin"

int main(void)
{
    sa_handle_t h = NULL;
    if (sa_open(&h) != SA_OK) { perror("sa_open"); return 1; }

    /* Fake weight blob -- 4 KB of zeros is enough for the stub backend. */
    FILE *f = fopen(WEIGHT_BLOB, "wb");
    if (!f) { sa_close(h); return 1; }
    char zeros[4096] = {0};
    fwrite(zeros, 1, sizeof(zeros), f);
    fclose(f);
    if (sa_load_weights(h, WEIGHT_BLOB) != SA_OK) {
        fprintf(stderr, "load_weights failed\n");
        remove(WEIGHT_BLOB); sa_close(h); return 1;
    }
    remove(WEIGHT_BLOB);

    int8_t *img = malloc(IMG_BYTES);
    int8_t *out = malloc(OUT_BYTES);
    if (!img || !out) { free(img); free(out); sa_close(h); return 1; }
    for (int i = 0; i < IMG_BYTES; i++) img[i] = (int8_t)((i * 13) & 0x7F);

    sa_status_t rc = sa_infer(h, img, out, /*timeout_ms=*/33);
    if (rc != SA_OK) {
        fprintf(stderr, "sa_infer: %s\n", sa_strerror(rc));
        free(img); free(out); sa_close(h); return 1;
    }

    int mn = 127, mx = -128;
    long sum = 0;
    for (int i = 0; i < OUT_BYTES; i++) {
        if (out[i] < mn) mn = out[i];
        if (out[i] > mx) mx = out[i];
        sum += out[i];
    }
    printf("infer ok: out min=%d max=%d mean=%.2f\n",
           mn, mx, (double)sum / OUT_BYTES);

    free(img); free(out); sa_close(h);
    return 0;
}
