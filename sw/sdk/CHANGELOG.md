# libspike_accel CHANGELOG

All ABI-affecting changes are gated against `sw/sdk/baseline/v1.1.0_*` (see
`sw/sdk/baseline/README.md`). Versioning is semver-on-the-shared-object:
removing or repurposing a symbol bumps SOVERSION; adding one at the tail
bumps MINOR; bug fixes bump PATCH.

## [1.1.0] - 2026-05-11

### Added
- `sa_set_layer_id(handle, int32_t)` -- single-layer dispatch (`-1` = run
  all 12 layers, `0..11` = single layer for per-layer debug / bisection).
- `sa_set_layer_mask(handle, uint32_t)` -- layer execution mask (bit i set
  = layer i scheduled; honoured only when `layer_id == -1`).
- Two new tail fields in `sa_perf_t`: `int32_t last_layer_id`,
  `uint32_t last_layer_mask`. Appended only -- v1.0.x positional readers
  remain valid.
- New error code: `SA_ERR_BUSY` -- returned by `sa_infer(timeout_ms=0)`
  when the engine cannot be claimed without waiting.
- `sa_reset_perf(handle)` -- zero cumulative perf counters.
- `sa_version()` -- returns `"MAJOR.MINOR.PATCH"` string (currently `"1.1.0"`).

### Changed
- `sa_infer(timeout_ms=...)` is now contract-authoritative:
  - `0`  = non-blocking try; returns `SA_OK` or `SA_ERR_BUSY` immediately.
  - `>0` = bounded wait; returns `SA_OK` or `SA_ERR_TIMEOUT`.
  - `-1` = wait forever (POSIX `poll`/`select` convention).
- `sa_infer_async` now uses `timeout_ms=-1` internally -- the completion
  callback is the only authoritative completion signal.
- `feat_out` is only memcpy'd from CMA on `status == SA_OK`. TIMEOUT / BUSY
  no longer stomps the caller buffer with stale data.

### Backward Compatibility
- ABI compatible with v1.0.x. No field reorder; new fields appended only.
- SOVERSION unchanged (still `libspike_accel.so.1`).
- All v1.0.x call sites compile and run unchanged.
- Consumes: B1 regmap **v1.0.3** (`LAYER_ID @ 0x10`, `LAYER_MASK @ 0x14`).

### Baseline locked
- `sw/sdk/baseline/v1.1.0_api_signatures.json` (parser output -- structured)
- `sw/sdk/baseline/v1.1.0_symbols.txt` (objdump output -- flat symbol list)

## [1.0.0] - 2026-05-04

Initial Contract 5 release: open/close/load_weights/get_model_info/infer/
get_perf/strerror, sync API only.
