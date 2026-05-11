/*
 * hello_open.c -- minimal libspike_accel walkthrough.
 *
 * Opens the accelerator, prints SDK version + static model info, closes
 * cleanly. Expected output (stub backend):
 *
 *     SDK version: 1.1.0
 *     model: 256x256x3 -> 16x16 (nc=80, stride=16)
 *
 * Build (host stub):
 *     gcc -DSA_STUB_BACKEND=1 -I../include hello_open.c \
 *         ../src/accel_drv.c ../src/dma_buf.c \
 *         ../src/sa_strerror.c ../src/sa_version.c \
 *         -lpthread -o hello_open
 */

#include "spike_accel.h"

#include <stdio.h>

int main(void)
{
    printf("SDK version: %s\n", sa_version());

    sa_handle_t h = NULL;
    sa_status_t rc = sa_open(&h);
    if (rc != SA_OK) {
        fprintf(stderr, "sa_open failed: %s (%d)\n", sa_strerror(rc), rc);
        return 1;
    }

    sa_model_info_t info;
    rc = sa_get_model_info(h, &info);
    if (rc != SA_OK) {
        fprintf(stderr, "sa_get_model_info: %s\n", sa_strerror(rc));
        sa_close(h);
        return 1;
    }
    printf("model: %ux%ux%u -> %ux%u (nc=%u, stride=%u)\n",
           info.input_w, info.input_h, info.input_c,
           info.output_w, info.output_h,
           info.num_classes, info.output_stride);

    sa_close(h);
    return 0;
}
