/*
 * sw/sdk/tests/test_api_contract.c — Contract 5 conformance unit test.
 *
 * Run on both PC (with SA_STUB_BACKEND=1) and target board (real backend).
 * Exits non-zero on any failure; CTest picks it up.
 */

#include "spike_accel.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ASSERT_EQ(a, b)  do { if ((a) != (b)) {                                \
    fprintf(stderr, "FAIL %s:%d  %s != %s  (%ld vs %ld)\n",                   \
            __FILE__, __LINE__, #a, #b, (long)(a), (long)(b));                \
    exit(1); } } while (0)

#define ASSERT_OK(call)  ASSERT_EQ(call, SA_OK)


int main(int argc, char **argv)
{
    (void)argc; (void)argv;

    /* --- Version + strerror always work without an open handle --------- */
    const char *ver = sa_version();
    if (!ver || !ver[0]) { fprintf(stderr, "FAIL: empty version\n"); return 1; }
    if (!sa_strerror(SA_OK)) { fprintf(stderr, "FAIL: NULL strerror\n"); return 1; }
    fprintf(stdout, "version=%s strerror(OK)=%s\n", ver, sa_strerror(SA_OK));

    /* --- Invalid args ------------------------------------------------- */
    ASSERT_EQ(sa_open(NULL),                       SA_ERR_INVALID_ARG);
    ASSERT_EQ(sa_get_model_info(NULL, NULL),       SA_ERR_INVALID_ARG);
    ASSERT_EQ(sa_infer(NULL, NULL, NULL, 0),       SA_ERR_INVALID_ARG);

    /* --- Open + close roundtrip --------------------------------------- */
    sa_handle_t h = NULL;
    ASSERT_OK(sa_open(&h));
    if (!h) { fprintf(stderr, "FAIL: handle still NULL\n"); return 1; }

    /* --- Model info exposed ------------------------------------------- */
    sa_model_info_t info;
    ASSERT_OK(sa_get_model_info(h, &info));
    ASSERT_EQ(info.input_h,     256);
    ASSERT_EQ(info.input_w,     256);
    ASSERT_EQ(info.input_c,     3);
    ASSERT_EQ(info.num_classes, 80);

    /* --- Loading missing weights must fail cleanly -------------------- */
    ASSERT_EQ(sa_load_weights(h, "/tmp/_definitely_not_present.bin"),
              SA_ERR_WEIGHT_LOAD);

    /* --- Infer without weights -> SA_ERR_WEIGHT_LOAD ----------------- */
    int8_t img[3 * 256 * 256] = {0};
    int8_t out[84 * 16 * 16]  = {0};
    ASSERT_EQ(sa_infer(h, img, out, 1000), SA_ERR_WEIGHT_LOAD);

    /* --- Write a fake weight blob and load it ------------------------ */
    {
        FILE *f = fopen("_test_weights.bin", "wb");
        if (!f) { fprintf(stderr, "FAIL: cannot create fake weights\n"); return 1; }
        char zeros[1024]; memset(zeros, 0, sizeof(zeros));
        fwrite(zeros, 1, sizeof(zeros), f);
        fclose(f);
    }
    ASSERT_OK(sa_load_weights(h, "_test_weights.bin"));
    remove("_test_weights.bin");

    /* --- Real-ish infer: stub backend computes a deterministic output -- */
    for (int i = 0; i < (int)sizeof(img); i++) img[i] = (int8_t)((i * 7) & 0x7F);
    ASSERT_OK(sa_infer(h, img, out, 1000));

    /* output must not be all-zero (the stub backend transforms input) */
    int nz = 0;
    for (size_t i = 0; i < sizeof(out); i++) if (out[i] != 0) nz++;
    if (nz == 0) { fprintf(stderr, "FAIL: stub backend produced all-zero output\n");
                   return 1; }

    /* --- Performance counters ----------------------------------------- */
    sa_perf_t perf;
    ASSERT_OK(sa_get_perf(h, &perf));
    ASSERT_EQ(perf.frames_completed, 1);
    ASSERT_EQ(perf.frames_dropped,   0);

    ASSERT_OK(sa_reset_perf(h));
    ASSERT_OK(sa_get_perf(h, &perf));
    ASSERT_EQ(perf.frames_completed, 0);

    /* --- Close ------------------------------------------------------- */
    ASSERT_OK(sa_close(h));
    /* sa_close(NULL) must be a no-op */
    ASSERT_OK(sa_close(NULL));

    fprintf(stdout, "ALL PASS\n");
    return 0;
}
