/*
 * spike_accel.h — Contract 5 SDK API (C2 -> C3).
 *
 * This header is the *ABI baseline* for libspike_accel.so.1.
 * Any breaking change requires bumping SA_API_VERSION_MAJOR and updating
 * sw/sdk/baseline/libspike_accel.abi via abidw + signed-off PR.
 *
 * See docs/CONTRACTS.md "Contract 5" and docs/AGENT_PLAYBOOKS/C2_driver_sdk.md
 * for the matching implementation contract.
 */

#ifndef SPIKE_ACCEL_H
#define SPIKE_ACCEL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SA_API_VERSION_MAJOR 1
#define SA_API_VERSION_MINOR 0
#define SA_API_VERSION_PATCH 0

/* Public, opaque handle. */
struct sa_handle_s;
typedef struct sa_handle_s *sa_handle_t;

/* Status codes — keep in sync with sw/sdk/src/accel_drv.c. */
typedef enum sa_status_e {
    SA_OK              =  0,
    SA_ERR_OPEN        = -1,    /* /dev/uio0 mmap failed                       */
    SA_ERR_NO_DEVICE   = -2,    /* device node missing                         */
    SA_ERR_WEIGHT_LOAD = -3,    /* .bin malformed or too large                 */
    SA_ERR_DMA         = -4,    /* DMA engine reported error                   */
    SA_ERR_TIMEOUT     = -5,    /* sa_infer timed out                          */
    SA_ERR_INVALID_ARG = -6,    /* NULL pointer / bad size                     */
    SA_ERR_BUSY        = -7,    /* another thread holds the handle             */
} sa_status_t;

/* Static model info baked into the accelerator IP. */
typedef struct sa_model_info_s {
    uint16_t input_h;          /* expected 256                                  */
    uint16_t input_w;          /* expected 256                                  */
    uint8_t  input_c;          /* expected 3 (RGB INT8)                         */
    uint8_t  num_classes;      /* expected 80 (COCO)                            */
    uint16_t output_h;         /* expected 16                                   */
    uint16_t output_w;         /* expected 16                                   */
    uint8_t  output_stride;    /* expected 16                                   */
    uint8_t  _pad[3];
} sa_model_info_t;

/* Runtime performance counters (cumulative since last sa_open). */
typedef struct sa_perf_s {
    uint64_t cycles_compute;   /* PL fabric cycles spent in compute             */
    uint64_t cycles_dma_in;    /* feature/weight DMA-in cycles                  */
    uint64_t cycles_dma_out;   /* output DMA-out cycles                         */
    uint32_t frames_completed;
    uint32_t frames_dropped;
} sa_perf_t;

/* ---------- Core lifecycle ---------- */

/**
 * Open the accelerator. Allocates CMA buffers and mmaps the AXI-Lite
 * register file. Must be matched by sa_close().
 */
sa_status_t sa_open(sa_handle_t *out_handle);

/**
 * Release every resource acquired in sa_open(). Calling sa_close on a NULL
 * handle is a no-op and returns SA_OK.
 */
sa_status_t sa_close(sa_handle_t handle);

/**
 * Load weights from a board-local path (.bin file written by
 * tools/quant/weight_packer.py to-bin). Streams to PL weight pool over DMA.
 */
sa_status_t sa_load_weights(sa_handle_t handle, const char *bin_path);

/**
 * Query the static model info reported by the IP.
 */
sa_status_t sa_get_model_info(sa_handle_t handle, sa_model_info_t *out_info);

/* ---------- Inference ---------- */

/**
 * Blocking single-frame inference.
 *
 * @param img_in      INT8 RGB NCHW [-128, 127]; size must equal 3*256*256.
 * @param feat_out    INT8 raw detect head output; size must equal (nc+4)*16*16.
 * @param timeout_ms  0   = blocking forever
 *                    >0  = abort with SA_ERR_TIMEOUT after N milliseconds
 *                    -1  = non-blocking (returns SA_ERR_BUSY if engine busy)
 */
sa_status_t sa_infer(sa_handle_t handle,
                     const int8_t *img_in,
                     int8_t       *feat_out,
                     int           timeout_ms);

/* ---------- Async API (M5+) ---------- */

/**
 * Completion callback for sa_infer_async.
 * Called from the SDK worker thread; do not block inside.
 */
typedef void (*sa_callback_t)(sa_handle_t handle,
                              sa_status_t status,
                              void       *user);

sa_status_t sa_infer_async(sa_handle_t   handle,
                           const int8_t *img_in,
                           int8_t       *feat_out,
                           sa_callback_t callback,
                           void         *user);

/* ---------- Telemetry ---------- */

sa_status_t sa_get_perf(sa_handle_t handle, sa_perf_t *out_perf);

/* Reset cumulative perf counters to zero. */
sa_status_t sa_reset_perf(sa_handle_t handle);

/* ---------- Diagnostics ---------- */

/**
 * Returns a static, null-terminated string for the given status code.
 * Never NULL.
 */
const char *sa_strerror(sa_status_t status);

/**
 * Returns the linked-library version as "MAJOR.MINOR.PATCH".
 */
const char *sa_version(void);

#ifdef __cplusplus
}  /* extern "C" */
#endif

#endif  /* SPIKE_ACCEL_H */
