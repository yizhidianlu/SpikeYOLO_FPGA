# sw/sdk/baseline — ABI fence for libspike_accel.so.1

This directory locks the v1.1.0 public surface of `libspike_accel`. It is the
forensic record future PRs are diffed against to catch silent ABI breakage
(removed function, reordered struct field, widened enum, changed return type).

## Files

| File                          | Source                                            | Purpose                                                                                                |
|-------------------------------|---------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| `v1.1.0_api_signatures.json`  | `extract_api_signatures.py ../include/spike_accel.h` | Structured snapshot of macros / enums / structs / functions. Stable JSON schema; diff with any text tool. |
| `v1.1.0_symbols.txt`          | `objdump -t libspike_accel.a` (SA_STUB_BACKEND=1, MinGW gcc 5.3) | Flat list of exported `sa_*` symbols. Catches accidentally-hidden public symbols.                      |
| `extract_api_signatures.py`   | hand-written                                      | The parser. Re-run on any header change to regenerate the JSON.                                        |

## Why not `abidiff`?

`abidiff` (libabigail) is the eventual canonical tool, but it isn't available
on the current MinGW / Windows dev box. **M3 will wire real `abidiff` into
CI** -- the JSON fence is the bridge until then. The JSON schema is
deliberately compatible with a future `abidiff --to-json` consumer.

## How to diff a future header against this baseline

```bash
cd sw/sdk/baseline
python extract_api_signatures.py ../include/spike_accel.h /tmp/new.json
diff -u v1.1.0_api_signatures.json /tmp/new.json
```

A non-empty diff on a PR that did **not** bump `SA_API_VERSION_MAJOR` is a
contract violation. Additive changes (new function, new tail struct field)
require bumping `SA_API_VERSION_MINOR` and regenerating both baseline files
under a new `vX.Y.0_*` name; the old files stay in tree as historical record.

## Rebuilding the symbol list

```bash
cd sw/sdk
mkdir -p baseline/build_tmp && cd baseline/build_tmp
gcc -DSA_STUB_BACKEND=1 -D_POSIX_C_SOURCE=200809L \
    -I../../include -I../../src \
    -c ../../src/accel_drv.c ../../src/dma_buf.c \
       ../../src/sa_strerror.c ../../src/sa_version.c
ar rcs libspike_accel.a *.o
objdump -t libspike_accel.a | grep -E ' sa_[a-z_]+' | awk '{print $NF}' | sort -u
```

Compare against the curated public-API list in `v1.1.0_symbols.txt`; any new
public symbol must have an entry in `spike_accel.h` (otherwise visibility is
leaking).

## Coupling with B1 regmap

This baseline locks **API + ABI only**. The hardware-side regmap version is
governed by `docs/CONTRACTS.md` / `hw/hls/build/tiny_fpga_regmap.yaml`. v1.1.0
consumes B1 regmap **v1.0.3** (`LAYER_ID @ 0x10`, `LAYER_MASK @ 0x14`); a
future B1 regmap bump that changes a register offset is invisible to this
fence as long as `internal.h` (driver-internal) stays the only consumer.
