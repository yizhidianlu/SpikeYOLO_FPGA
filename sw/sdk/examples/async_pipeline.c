/*
 * async_pipeline.c -- sa_infer_async + double-buffer pattern.
 *
 * Two ping-pong frame slots feed sa_infer_async. The completion callback
 * signals a condvar that the producer waits on before re-filling the slot.
 * This is the reference pattern C3's three-thread main loop should mirror:
 *   producer (camera) -> A/B slot -> SDK -> consumer (post-proc).
 *
 * Note: in M1 the SDK runs the callback inline on the calling thread (M5
 * will spin up a worker), so this example still serialises in practice.
 * The control flow / synchronisation primitives are what matters.
 */

#include "spike_accel.h"

#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IMG_BYTES   (3 * 256 * 256)
#define OUT_BYTES   (84 * 16 * 16)
#define N_FRAMES    8

typedef struct {
    int8_t *out;
    atomic_int done;
    sa_status_t status;
} slot_t;

static void on_done(sa_handle_t h, sa_status_t st, void *user) {
    (void)h;
    slot_t *s = (slot_t *)user;
    s->status = st;
    atomic_store(&s->done, 1);
}

int main(void)
{
    sa_handle_t h = NULL;
    if (sa_open(&h) != SA_OK) return 1;
    FILE *f = fopen("_async.bin", "wb"); char z[1024]={0};
    fwrite(z,1,sizeof(z),f); fclose(f);
    sa_load_weights(h, "_async.bin"); remove("_async.bin");

    int8_t *img = calloc(1, IMG_BYTES);
    slot_t A = {calloc(1, OUT_BYTES), 0, SA_OK};
    slot_t B = {calloc(1, OUT_BYTES), 0, SA_OK};

    int submitted = 0, completed = 0;
    slot_t *next = &A;
    while (completed < N_FRAMES) {
        if (submitted < N_FRAMES && atomic_load(&next->done) == 0) {
            for (int i = 0; i < 4096; i++) img[i] = (int8_t)(submitted + i);
            atomic_store(&next->done, 0);
            sa_infer_async(h, img, next->out, on_done, next);
            submitted++;
            printf("submit %d (slot=%c)\n", submitted, (next == &A) ? 'A':'B');
            next = (next == &A) ? &B : &A;
        }
        /* Drain whichever slot finished first. */
        for (slot_t *s = &A; ; s = &B) {
            if (atomic_exchange(&s->done, 0) == 1) {
                completed++;
                printf("  drain %d status=%s\n",
                       completed, sa_strerror(s->status));
            }
            if (s == &B) break;
        }
    }

    printf("done submitted=%d completed=%d\n", submitted, completed);
    free(img); free(A.out); free(B.out); sa_close(h);
    return 0;
}
