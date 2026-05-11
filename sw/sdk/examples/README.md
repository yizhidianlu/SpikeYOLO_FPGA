# sw/sdk/examples -- libspike_accel reference programs

Five short C programs (each <= 70 lines) that exercise the v1.1.0 SDK. All
five compile and run host-side with `SA_STUB_BACKEND=1` -- no board needed.

| Example              | Demonstrates                                              |
|----------------------|-----------------------------------------------------------|
| `hello_open.c`       | sa_open / sa_version / sa_get_model_info / sa_close       |
| `infer_one_frame.c`  | sa_load_weights -> single sa_infer (33 ms budget) -> stats |
| `layer_isolation.c`  | v1.1.0 sa_set_layer_id for layer-by-layer debug bisection |
| `perf_counters.c`    | 100-frame sweep + periodic sa_get_perf + sa_reset_perf    |
| `async_pipeline.c`   | sa_infer_async + double-buffer slots (C3 main-loop ref)   |

## Build with CMake

```bash
cd sw/sdk/examples
cmake -B build -DSA_STUB_BACKEND=ON
cmake --build build
./build/hello_open
```

For the ZYBO target, point at your cross toolchain and disable the stub:

```bash
cmake -B build-arm \
    -DCMAKE_TOOLCHAIN_FILE=../cmake/zynq_toolchain.cmake \
    -DSA_STUB_BACKEND=OFF
cmake --build build-arm
```

## Build with plain `make`

```bash
cd sw/sdk/examples
make                # build all 5 into build/
make run-hello_open # build + run hello_open
make clean
```

Cross-compile: `make CC=arm-linux-gnueabihf-gcc SA_STUB_BACKEND=` (empty
disables the stub).

## Expected stub-backend output

```
$ ./build/hello_open
SDK version: 1.1.0
model: 256x256x3 -> 16x16 (nc=80, stride=16)

$ ./build/infer_one_frame
infer ok: out min=-125 max=125 mean=8.96

$ ./build/perf_counters | tail -2
100    1552697000   2595600      314400       100     0       64.2
final: layer_id=-1 mask=0xfff done=100 drop=0
```

## Cross-references

- Reading order for a new C3 contributor: `hello_open` -> `infer_one_frame`
  -> `perf_counters` -> `async_pipeline` (mirror the three-thread main loop
  pattern: producer / SDK / consumer with `atomic_int` slot flags).
- `layer_isolation` is the canonical entry point when `tests/test_bit_exact.py`
  flags a per-layer mismatch -- run each layer in isolation and compare
  output hashes against `tests/golden_layerwise/`.
- B1 regmap v1.0.3 (`LAYER_ID @ 0x10`, `LAYER_MASK @ 0x14`) is exercised by
  `layer_isolation`; if you ever see `last_layer_id` not echo back, that's
  a regmap regression, not an SDK bug.
