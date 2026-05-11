/*
 * layer_isolation.c -- v1.1.0 single-layer debug walkthrough.
 *
 * Demonstrates sa_set_layer_id for layer-by-layer bisection: run each of the
 * 12 layers in isolation and compare against the full-pipeline run. Useful
 * when a quality regression points at a specific layer (golden-vs-actual
 * mismatch in tests/test_bit_exact.py).
 */

#include "spike_accel.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IMG_BYTES   (3 * 256 * 256)
#define OUT_BYTES   (84 * 16 * 16)

static int prepare(sa_handle_t *out_h)
{
    if (sa_open(out_h) != SA_OK) return 1;
    FILE *f = fopen("_layer_iso.bin", "wb");
    if (!f) return 1;
    char z[1024] = {0}; fwrite(z, 1, sizeof(z), f); fclose(f);
    int rc = sa_load_weights(*out_h, "_layer_iso.bin");
    remove("_layer_iso.bin");
    return rc != SA_OK;
}

int main(void)
{
    sa_handle_t h = NULL;
    if (prepare(&h)) { fprintf(stderr, "setup failed\n"); return 1; }

    int8_t *img = calloc(1, IMG_BYTES);
    int8_t *out = calloc(1, OUT_BYTES);
    for (int i = 0; i < IMG_BYTES; i++) img[i] = (int8_t)(i & 0x3F);

    /* Sweep layer 0..11 in isolation. */
    for (int lid = 0; lid < 12; lid++) {
        if (sa_set_layer_id(h, lid) != SA_OK) {
            fprintf(stderr, "set_layer_id(%d) rejected\n", lid); break;
        }
        if (sa_infer(h, img, out, 100) != SA_OK) {
            fprintf(stderr, "infer layer=%d failed\n", lid); break;
        }
        sa_perf_t p; sa_get_perf(h, &p);
        long sum = 0;
        for (int i = 0; i < OUT_BYTES; i++) sum += out[i];
        printf("layer=%2d echo=%2d sum=%ld\n", lid, p.last_layer_id, sum);
    }

    /* Full pipeline reference. */
    sa_set_layer_id(h, -1);
    sa_infer(h, img, out, 100);
    sa_perf_t p; sa_get_perf(h, &p);
    printf("full    echo=%d mask=0x%03x\n", p.last_layer_id, p.last_layer_mask);

    free(img); free(out); sa_close(h);
    return 0;
}
