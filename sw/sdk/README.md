# sw/sdk — User-space SDK (C2 Agent)

**Owner**: C2 Driver & SDK Agent — see [`docs/AGENT_PLAYBOOKS/C2_driver_sdk.md`](../../docs/AGENT_PLAYBOOKS/C2_driver_sdk.md)

## Purpose

C/C++ user-space library wrapping spike_accel IP through UIO + dma-buf. Exposes the API locked by **Contract 5**.

## Layout

```
include/spike_accel.h          Public API header (Contract 5)
src/
  accel_drv.c                  Core SDK
  dma_buf.c                    CMA buffer manager
tests/
  test_api_contract.c          Contract 5 verification
  test_dma_loopback.c          DMA path verification (no-leak 100k loops)
baseline/
  libspike_accel.abi           ABI baseline (abidiff gate)
CMakeLists.txt                 Build script
build/                         Generated artifacts (libspike_accel.so)
```

## Build

```bash
mkdir -p build && cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=../cmake/zynq_toolchain.cmake
cmake --build .
ctest
```

## ABI policy

- Public API frozen at v1.0
- semver `libspike_accel.so.1` — no breaking changes within major
- `abidiff baseline/libspike_accel.abi build/libspike_accel.so.1` must pass on every PR

## Acceptance gates

- All tests in `tests/` pass
- DMA single 1 MB transfer < 1 ms
- 100k inferences with valgrind shows zero leaks
- `abidiff` clean

## References

- [`docs/CONTRACTS.md`](../../docs/CONTRACTS.md) — Contract 5 spec
- libabigail documentation
