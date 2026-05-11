/*
 * sw/sdk/src/accel_drv.c — Contract 5 implementation entry point.
 *
 * Real backend: talks to /dev/uio0 + udmabuf* through AXI-Lite registers
 * documented in hw/hls/build/tiny_fpga_regmap.yaml.
 *
 * Stub backend (SA_STUB_BACKEND=1): no hardware needed. Inference becomes a
 * deterministic identity-ish transform of the input so C3's application
 * code and the test suite can be exercised end-to-end on a developer PC.
 */

#include "internal.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifndef SA_STUB_BACKEND
#  include <sys/mman.h>
#  include <unistd.h>
#endif

int sa_dma_alloc(struct sa_handle_s *h);   /* dma_buf.c */
void sa_dma_free(struct sa_handle_s *h);


#define SA_VISIBILITY __attribute__((visibility("default")))


/* --------------------------------------------------------------------------
 * Helpers
 * -------------------------------------------------------------------------- */

static inline void _reg_write(struct sa_handle_s *h, uint32_t off, uint32_t v)
{
    if (!h->regs) return;
    volatile uint32_t *p = (volatile uint32_t *)((uint8_t *)h->regs + off);
    *p = v;
}

static inline uint32_t _reg_read(struct sa_handle_s *h, uint32_t off)
{
    if (!h->regs) return 0;
    volatile uint32_t *p = (volatile uint32_t *)((uint8_t *)h->regs + off);
    return *p;
}

static uint64_t _now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}


/* --------------------------------------------------------------------------
 * Public API
 * -------------------------------------------------------------------------- */

SA_VISIBILITY
sa_status_t sa_open(sa_handle_t *out_handle)
{
    if (!out_handle) return SA_ERR_INVALID_ARG;
    *out_handle = NULL;

    struct sa_handle_s *h = (struct sa_handle_s *)calloc(1, sizeof(*h));
    if (!h) return SA_ERR_OPEN;
    h->uio_fd = -1;
    h->dma_fd = -1;
    /* v1.0.3 dispatch defaults: full pipeline, all 12 layers on. */
    h->layer_id   = SA_LAYER_ID_DEFAULT;
    h->layer_mask = SA_LAYER_MASK_DEFAULT;
    pthread_mutex_init(&h->lock, NULL);

#if defined(SA_STUB_BACKEND)
    h->has_hw = false;
#else
    h->uio_fd = open("/dev/uio0", O_RDWR);
    if (h->uio_fd < 0) {
        SA_LOG("/dev/uio0: %s", strerror(errno));
        free(h);
        return SA_ERR_NO_DEVICE;
    }
    h->regs = mmap(NULL, 0x10000, PROT_READ | PROT_WRITE,
                   MAP_SHARED, h->uio_fd, 0);
    if (h->regs == MAP_FAILED) {
        close(h->uio_fd);
        free(h);
        return SA_ERR_OPEN;
    }
    h->has_hw = true;
#endif

    int rc = sa_dma_alloc(h);
    if (rc != 0) {
        sa_close((sa_handle_t)h);
        return SA_ERR_OPEN;
    }

    *out_handle = (sa_handle_t)h;
    return SA_OK;
}

SA_VISIBILITY
sa_status_t sa_close(sa_handle_t handle)
{
    if (!handle) return SA_OK;
    struct sa_handle_s *h = (struct sa_handle_s *)handle;
    sa_dma_free(h);
#ifndef SA_STUB_BACKEND
    if (h->regs && h->regs != MAP_FAILED) munmap(h->regs, 0x10000);
    if (h->uio_fd >= 0) close(h->uio_fd);
#endif
    pthread_mutex_destroy(&h->lock);
    free(h);
    return SA_OK;
}

SA_VISIBILITY
sa_status_t sa_load_weights(sa_handle_t handle, const char *bin_path)
{
    if (!handle || !bin_path) return SA_ERR_INVALID_ARG;
    struct sa_handle_s *h = (struct sa_handle_s *)handle;

    FILE *f = fopen(bin_path, "rb");
    if (!f) {
        SA_LOG("sa_load_weights: cannot open %s: %s",
               bin_path, strerror(errno));
        return SA_ERR_WEIGHT_LOAD;
    }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (size < 0 || (size_t)size > SA_WEIGHT_POOL_SIZE) {
        SA_LOG("sa_load_weights: bad size %ld (max %d)",
               size, SA_WEIGHT_POOL_SIZE);
        fclose(f);
        return SA_ERR_WEIGHT_LOAD;
    }
    size_t got = fread(h->weight_pool, 1, (size_t)size, f);
    fclose(f);
    if (got != (size_t)size) {
        SA_LOG("sa_load_weights: short read %zu/%ld", got, size);
        return SA_ERR_WEIGHT_LOAD;
    }
    /* Tell the IP where the weight pool lives. */
    _reg_write(h, SA_REG_W_PTR_LO, (uint32_t)(h->weight_pa & 0xFFFFFFFFu));
    _reg_write(h, SA_REG_W_PTR_HI, (uint32_t)(h->weight_pa >> 32));
    h->weights_loaded = true;
    return SA_OK;
}

SA_VISIBILITY
sa_status_t sa_get_model_info(sa_handle_t handle, sa_model_info_t *out_info)
{
    if (!handle || !out_info) return SA_ERR_INVALID_ARG;
    out_info->input_h = 256;
    out_info->input_w = 256;
    out_info->input_c = 3;
    out_info->num_classes = 80;
    out_info->output_h = 16;
    out_info->output_w = 16;
    out_info->output_stride = 16;
    memset(out_info->_pad, 0, sizeof(out_info->_pad));
    return SA_OK;
}

/* Poll the CTRL register for ap_done. Returns SA_OK / SA_ERR_BUSY /
 * SA_ERR_TIMEOUT depending on the timeout mode. Only used by the real
 * backend; SA_STUB_BACKEND short-circuits this entirely. */
#ifndef SA_STUB_BACKEND
static sa_status_t _wait_ap_done(struct sa_handle_s *h, int timeout_ms)
{
    /* Bit 1 of CTRL == ap_done (per Contract 3 regmap). */
    const uint32_t AP_DONE_BIT = 0x2u;

    if (timeout_ms == 0) {
        /* Non-blocking try: one register read, no waiting. */
        return (_reg_read(h, SA_REG_CTRL) & AP_DONE_BIT) ? SA_OK : SA_ERR_BUSY;
    }

    /* timeout_ms < 0: wait forever (POSIX poll/select convention).
     * timeout_ms > 0: wait up to N ms, then SA_ERR_TIMEOUT. */
    const uint64_t deadline_ns =
        (timeout_ms > 0) ? _now_ns() + (uint64_t)timeout_ms * 1000000ULL : 0;

    /* 100 us poll cadence — keeps host CPU off the AXI bus while still
     * reacting to typical few-ms inference latency. UIO IRQ path lands in
     * M5; until then poll is the contract-clean answer. */
    const struct timespec slack = {0, 100 * 1000};
    for (;;) {
        if (_reg_read(h, SA_REG_CTRL) & AP_DONE_BIT) return SA_OK;
        if (timeout_ms > 0 && _now_ns() >= deadline_ns) return SA_ERR_TIMEOUT;
        nanosleep(&slack, NULL);
    }
}
#endif

SA_VISIBILITY
sa_status_t sa_infer(sa_handle_t handle,
                     const int8_t *img_in,
                     int8_t       *feat_out,
                     int           timeout_ms)
{
    if (!handle || !img_in || !feat_out) return SA_ERR_INVALID_ARG;
    struct sa_handle_s *h = (struct sa_handle_s *)handle;
    if (!h->weights_loaded) return SA_ERR_WEIGHT_LOAD;

    /* Lock acquisition mirrors timeout_ms semantics so a "non-blocking try"
     * doesn't accidentally block on a contended handle. */
    if (timeout_ms == 0) {
        if (pthread_mutex_trylock(&h->lock) != 0) return SA_ERR_BUSY;
    } else {
        /* Both -1 (wait forever) and >0 (bounded wait) acquire blockingly;
         * the >0 budget is enforced inside _wait_ap_done below. */
        pthread_mutex_lock(&h->lock);
    }

    const uint64_t t0 = _now_ns();

    /* Stage 1: copy input into the CMA buffer. */
    memcpy(h->in_buf, img_in, SA_INPUT_BUF_SIZE);
    const uint64_t t1 = _now_ns();

    /* Stage 2: configure registers + kick. v1.0.3 adds LAYER_MASK. */
    _reg_write(h, SA_REG_IN_PTR_LO,  (uint32_t)(h->in_pa  & 0xFFFFFFFFu));
    _reg_write(h, SA_REG_IN_PTR_HI,  (uint32_t)(h->in_pa  >> 32));
    _reg_write(h, SA_REG_OUT_PTR_LO, (uint32_t)(h->out_pa & 0xFFFFFFFFu));
    _reg_write(h, SA_REG_OUT_PTR_HI, (uint32_t)(h->out_pa >> 32));
    _reg_write(h, SA_REG_LAYER_ID,   (uint32_t)h->layer_id);   /* signed cast */
    _reg_write(h, SA_REG_LAYER_MASK, h->layer_mask);
    _reg_write(h, SA_REG_CTRL,       0x1u);                    /* ap_start    */

    sa_status_t status = SA_OK;

#if defined(SA_STUB_BACKEND)
    /* Stub backend timeout semantics (matches header):
     *   timeout_ms == 0  -> immediate "success" (we already trylock'd the
     *                       mutex above, so the engine is by definition idle).
     *   timeout_ms != 0  -> sleep ~5 ms to mimic real-board inference latency.
     */
    if (timeout_ms != 0) {
        struct timespec ts = {0, 5 * 1000 * 1000};   /* 5 ms */
        nanosleep(&ts, NULL);
    }

    /* Synthesise a deterministic output. Multiply the centre-of-image by
     * per-class biases so different inputs produce different outputs. */
    int8_t *out = h->out_buf;
    const int OUT_C = 84, OUT_H = 16, OUT_W = 16;
    int32_t pixel_sum = 0;
    for (int i = 0; i < SA_INPUT_BUF_SIZE; i += 64) pixel_sum += img_in[i];
    for (int c = 0; c < OUT_C; c++) {
        for (int y = 0; y < OUT_H; y++) {
            for (int x = 0; x < OUT_W; x++) {
                int32_t v = (pixel_sum + c * 7 + y * 3 - x * 2) % 251 - 125;
                out[(c * OUT_H + y) * OUT_W + x] = (int8_t)v;
            }
        }
    }
#else
    /* Real path: poll ap_done with the requested timeout policy. The legacy
     * uio_fd read() interrupt path will be re-enabled in M5 once the kernel
     * driver lands; until then we go through AXI-Lite directly. */
    status = _wait_ap_done(h, timeout_ms);
    if (status != SA_OK && status != SA_ERR_BUSY && status != SA_ERR_TIMEOUT) {
        SA_LOG("sa_infer: unexpected wait status %d", (int)status);
    }
#endif

    const uint64_t t2 = _now_ns();

    /* Stage 3: copy output out of CMA only when the engine actually
     * produced one this round. */
    if (status == SA_OK) {
        memcpy(feat_out, h->out_buf, SA_OUTPUT_BUF_SIZE);
    }
    const uint64_t t3 = _now_ns();

    /* Stash performance counters (cycles ≈ ns at 1 GHz; we report ns and let
     * the caller convert). */
    h->perf.cycles_dma_in  += (t1 - t0);
    h->perf.cycles_compute += (t2 - t1);
    h->perf.cycles_dma_out += (t3 - t2);
    if (status == SA_OK)        h->perf.frames_completed++;
    else                        h->perf.frames_dropped++;

    /* v1.1.0 echo: surface the dispatch control that this sa_infer applied
     * so callers can verify it round-tripped without snooping AXI. */
    h->perf.last_layer_id   = h->layer_id;
    h->perf.last_layer_mask = h->layer_mask;

    pthread_mutex_unlock(&h->lock);
    return status;
}

SA_VISIBILITY
sa_status_t sa_set_layer_id(sa_handle_t handle, int32_t layer_id)
{
    if (!handle) return SA_ERR_INVALID_ARG;
    /* Contract 3 v1.0.3: -1 = run all 12 layers, 0..11 = single-layer debug. */
    if (layer_id != -1 && (layer_id < 0 || layer_id > 11))
        return SA_ERR_INVALID_ARG;

    struct sa_handle_s *h = (struct sa_handle_s *)handle;
    pthread_mutex_lock(&h->lock);
    h->layer_id = layer_id;
#if !defined(SA_STUB_BACKEND)
    /* Push to the IP eagerly so a follow-up sa_get_perf reflects the live
     * register state even before the next sa_infer kick. */
    _reg_write(h, SA_REG_LAYER_ID, (uint32_t)layer_id);
#endif
    pthread_mutex_unlock(&h->lock);
    return SA_OK;
}

SA_VISIBILITY
sa_status_t sa_set_layer_mask(sa_handle_t handle, uint32_t mask)
{
    if (!handle) return SA_ERR_INVALID_ARG;
    /* mask == 0 would idle the accelerator silently; refuse it. */
    if (mask == 0u) return SA_ERR_INVALID_ARG;

    struct sa_handle_s *h = (struct sa_handle_s *)handle;
    pthread_mutex_lock(&h->lock);
    h->layer_mask = mask;
#if !defined(SA_STUB_BACKEND)
    _reg_write(h, SA_REG_LAYER_MASK, mask);
#endif
    pthread_mutex_unlock(&h->lock);
    return SA_OK;
}

SA_VISIBILITY
sa_status_t sa_infer_async(sa_handle_t   handle,
                           const int8_t *img_in,
                           int8_t       *feat_out,
                           sa_callback_t callback,
                           void         *user)
{
    /* M5 work: spin up a worker thread + epoll on h->uio_fd. For now we
     * fall back to the synchronous path and invoke the callback inline so
     * C3 can wire it up unmodified.
     *
     * timeout_ms=-1 == "wait forever" under the v1.0.3 semantics, which is
     * the right policy for an async-style call: the callback is contractually
     * the only way the caller learns completion, so we must not bail early. */
    sa_status_t rc = sa_infer(handle, img_in, feat_out, /*timeout_ms=*/-1);
    if (callback) callback(handle, rc, user);
    return rc;
}

SA_VISIBILITY
sa_status_t sa_get_perf(sa_handle_t handle, sa_perf_t *out_perf)
{
    if (!handle || !out_perf) return SA_ERR_INVALID_ARG;
    struct sa_handle_s *h = (struct sa_handle_s *)handle;
    pthread_mutex_lock(&h->lock);
    *out_perf = h->perf;
    pthread_mutex_unlock(&h->lock);
    return SA_OK;
}

SA_VISIBILITY
sa_status_t sa_reset_perf(sa_handle_t handle)
{
    if (!handle) return SA_ERR_INVALID_ARG;
    struct sa_handle_s *h = (struct sa_handle_s *)handle;
    pthread_mutex_lock(&h->lock);
    memset(&h->perf, 0, sizeof(h->perf));
    pthread_mutex_unlock(&h->lock);
    return SA_OK;
}
