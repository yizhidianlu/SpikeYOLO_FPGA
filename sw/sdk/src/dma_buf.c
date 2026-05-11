/*
 * sw/sdk/src/dma_buf.c — CMA buffer allocator.
 *
 * Two backends:
 *   * Real (Linux):  open /dev/udmabufN, mmap into user space, query the
 *                    physical address from sysfs
 *                    (/sys/class/u-dma-buf/udmabufN/phys_addr).
 *   * Stub (PC):     plain malloc(); physical address is set to the user-space
 *                    pointer so register-writes still receive deterministic values.
 *
 * The accelerator only cares about the physical addresses for AXI-MM bursts,
 * so the stub backend lets the SDK be unit-tested without /dev/uio0 by
 * exercising every code path except the actual DMA hand-off.
 */

#include "internal.h"

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>

#ifndef SA_STUB_BACKEND
#  include <sys/mman.h>
#  include <unistd.h>
#endif

#if defined(SA_STUB_BACKEND)

int sa_dma_alloc(struct sa_handle_s *h)
{
    h->weight_pool = (uint8_t *)calloc(1, SA_WEIGHT_POOL_SIZE);
    h->in_buf      = (int8_t  *)calloc(1, SA_INPUT_BUF_SIZE);
    h->out_buf     = (int8_t  *)calloc(1, SA_OUTPUT_BUF_SIZE);
    if (!h->weight_pool || !h->in_buf || !h->out_buf) {
        SA_LOG("stub dma_alloc OOM");
        return -ENOMEM;
    }
    /* Bogus but stable "physical" addresses so register writes are testable. */
    h->weight_pa = (uintptr_t)h->weight_pool;
    h->in_pa     = (uintptr_t)h->in_buf;
    h->out_pa    = (uintptr_t)h->out_buf;
    return 0;
}

void sa_dma_free(struct sa_handle_s *h)
{
    free(h->weight_pool); h->weight_pool = NULL;
    free(h->in_buf);      h->in_buf      = NULL;
    free(h->out_buf);     h->out_buf     = NULL;
}

#else   /* Real Linux backend */

#include <stdio.h>

static int _read_phys_addr(const char *path, uint64_t *out)
{
    FILE *f = fopen(path, "r");
    if (!f) return -errno;
    int n = fscanf(f, "%lx", (unsigned long *)out);
    fclose(f);
    return (n == 1) ? 0 : -EIO;
}

static int _alloc_one(const char *node, size_t size, void **mapped, uint64_t *pa)
{
    int fd = open(node, O_RDWR);
    if (fd < 0) return -errno;
    void *m = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (m == MAP_FAILED) return -errno;
    *mapped = m;
    /* Path convention: /dev/udmabufN <-> /sys/class/u-dma-buf/udmabufN/phys_addr */
    char sysfs[160];
    const char *base = strrchr(node, '/');
    base = base ? base + 1 : node;
    snprintf(sysfs, sizeof(sysfs), "/sys/class/u-dma-buf/%s/phys_addr", base);
    int rc = _read_phys_addr(sysfs, pa);
    if (rc != 0) {
        munmap(m, size);
        return rc;
    }
    return 0;
}

int sa_dma_alloc(struct sa_handle_s *h)
{
    int rc;
    void *m;
    rc = _alloc_one("/dev/udmabuf0", SA_WEIGHT_POOL_SIZE, &m, &h->weight_pa);
    if (rc) return rc;
    h->weight_pool = (uint8_t *)m;

    rc = _alloc_one("/dev/udmabuf1", SA_INPUT_BUF_SIZE, &m, &h->in_pa);
    if (rc) { sa_dma_free(h); return rc; }
    h->in_buf = (int8_t *)m;

    rc = _alloc_one("/dev/udmabuf2", SA_OUTPUT_BUF_SIZE, &m, &h->out_pa);
    if (rc) { sa_dma_free(h); return rc; }
    h->out_buf = (int8_t *)m;
    return 0;
}

void sa_dma_free(struct sa_handle_s *h)
{
    if (h->weight_pool) munmap(h->weight_pool, SA_WEIGHT_POOL_SIZE);
    if (h->in_buf)      munmap(h->in_buf,      SA_INPUT_BUF_SIZE);
    if (h->out_buf)     munmap(h->out_buf,     SA_OUTPUT_BUF_SIZE);
    h->weight_pool = NULL; h->in_buf = NULL; h->out_buf = NULL;
}

#endif  /* SA_STUB_BACKEND */
