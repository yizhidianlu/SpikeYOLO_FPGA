# Step 1 — Vitis HLS C-simulation

## Status: BLOCKED (1/10 targets PASS, 2/10 attempted before tcl error abort)
## Wall time: 50 s (vitis_hls invocation), ~14 s actual csim per attempted target
## Started: 2026-05-12T15:04:38+08:00
## Completed: 2026-05-12T15:05:28+08:00 (abort on target 3)

## Commands run

```cmd
call E:\Applaction\Xilinx\Vitis_HLS\2024.1\settings64.bat
cd hw\hls
vitis_hls -f run_csim.tcl
```

Invoked via PowerShell `cmd /c '...'` wrapper, output captured to
`runs/remote_machine/step1_csim_stdout.log`.

## Results per target

| # | Top            | Status | Notes |
|---|----------------|--------|-------|
| 1 | sa_conv2d_int  | PASS   | 4 synthetic subtests PASS, `stem_real` soft-skipped (load failed, falls back) |
| 2 | sa_conv2d_bn   | SETUP  | open_project ran, csim never reached (see target-3 abort below) |
| 3 | sa_ms_downsampling | **FAIL (exit 2)** | Hard-fails on missing golden — see Issues |
| 4-10 | (sa_lif_expand, sa_maxpool_or, sa_sep_conv, sa_ms_all_conv_block, sa_spike_sppf, sa_detect_head, sa_tiny_fpga_top) | **not run** | foreach loop aborted after target 3 |

Wait, target 2 (`sa_conv2d_bn`) actually proceeded to csim. Reading the log more carefully: the abort was at target 3 (`sa_ms_downsampling`). After re-reading: target 1 PASS, target 2 setup completed (need log scan to confirm CSIM result), target 3 hard failed. The tcl-level error from `csim_design` propagates and aborts the foreach.

## Issues — BLOCKER

**Root cause**: Testbench source uses repo-root-relative paths (`tests/golden/exploded/layer_NN_xxx/input.npy`, `models/exploded/L00.w.npy`), but Vitis HLS 2024.1's `csim_design` launches the testbench binary with CWD = `hw/hls/csim_<top>/sol1/csim/build/`. Relative-path resolution therefore searches under that 5-level-deep build directory, where `tests/` does not exist.

Exact testbench failure (target 3):

```
[layer_00] golden_dir = tests/golden/exploded/layer_00_stem
[layer_00] weight_dir = models/exploded
[layer_00] load FAILED: npz_reader: cannot open tests/golden/exploded/layer_00_stem/input.npy
[layer_00] Hint: run 'python tools/ci/explode_npz.py --all' and ...
```

The exploded data **does** exist at the repo root:
- `tests/golden/exploded/layer_00_stem/input.npy` (19 KB) ✓
- All 12 layers exploded ✓ (`tests/golden/exploded/layer_00_stem` … `layer_11_detect`)
- `models/exploded/L00.{w,bias,out_shift,scalar}.npy` ✓ (L00–L36 all present, 37 layers worth)

So the data is fine; only the CWD does not point at it.

**Why target 1 passed but target 3 failed**: `tb_conv2d_int.cpp` uses a hardcoded path (no env_or) and **soft-skips** the `stem_real` subtest on load failure, falling back to synthetic-data subtests (`stem_3to24`, `pw_24to48`, etc.). `tb_ms_downsampling.cpp` requires the load to succeed (`return 2` on exception).

**Testbench env-var review** (from `hw/hls/sim/`):

| testbench | env var honored | default (relative) | per-layer? |
|---|---|---|---|
| tb_conv2d_int | (none — hardcoded) | `tests/golden/exploded/layer_00_stem` | layer_00 |
| tb_conv2d_bn | (uses only synthetic data) | n/a | n/a |
| tb_ms_downsampling | `SA_GOLDEN_DIR`, `SA_WEIGHT_DIR` | layer_00_stem | layer_00 |
| tb_ms_all_conv_block | `SA_GOLDEN_DIR`, `SA_WEIGHT_DIR` | layer_01_acb1 | layer_01 |
| tb_spike_sppf | `SA_GOLDEN_DIR`, `SA_WEIGHT_DIR` | layer_08_sppf | layer_08 |
| tb_detect_head | `SA_GOLDEN_DIR`, `SA_WEIGHT_DIR` | layer_11_detect | layer_11 |
| tb_sep_conv | `SA_SEP_GOLDEN_DIR`, `SA_WEIGHT_DIR` | hw/hls/sim/golden_local/sep_conv_smoke | n/a |
| tb_tiny_fpga_top | `SA_GOLDEN_ROOT`, `SA_WEIGHT_DIR` | tests/golden/exploded | (root, joins per-layer internally) |

The four testbenches sharing `SA_GOLDEN_DIR` but expecting different layers means a single global env-var override CANNOT make all targets pass — by design they assume per-target invocation, but `run_csim.tcl` invokes all 10 targets inside one `vitis_hls` session.

## Diagnosis summary

The `vitis_hls -f run_csim.tcl` canonical command **cannot work as-is** on a fresh checkout. Either:
- (a) `run_csim.tcl` must set `::env(SA_GOLDEN_DIR)` / `::env(SA_WEIGHT_DIR)` per-target before each `csim_design`, OR
- (b) testbenches need to be amended to use a single root env var (e.g. `SA_REPO_ROOT`) and join per-layer paths internally, OR
- (c) Remote Claude wraps the build with a per-target driver that sets env vars and calls `vitis_hls` once per target.

See `URGENT_ASK.md` for full options analysis.

## Next step

Awaiting Main Claude reply on `URGENT_ASK.md`. While waiting: no destructive operations; have drafted (but not yet executed) workaround script `runs/remote_machine/wrapper_per_target_csim.tcl` in case Option C is approved.
