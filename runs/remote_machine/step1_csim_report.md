# Step 1 — Vitis HLS C-simulation (Option A + Option C)

## Status: SUCCESS  (10/10 targets PASS, byte-identical end-to-end)
## Wall time: ~21 min (~3 min Option A attempt + 17 min Option C run + ~1 min triage)
## Started: 2026-05-12T15:04:38+08:00 (first attempt, vanilla)
## Re-attempt Option A: 2026-05-12T15:24:29+08:00 (post-Main patch)
## Final Option C run: 2026-05-12T15:30:23 - 15:47:14 (~17 min)

## Commands run

```cmd
# Initial attempt (pre-Main patch) — aborted at target 3
cd C:\Users\jielu\Desktop\Workspace\SpikeYOLO_FPGA
call E:\Applaction\Xilinx\Vitis_HLS\2024.1\settings64.bat
cd hw\hls
vitis_hls -f run_csim.tcl   # FAILED at sa_ms_downsampling (return 2)

# Re-run after Main's Option A patch (commit 8c3c5ff)
git pull origin vivado/synth-runner
vitis_hls -f run_csim.tcl   # 4/10 PASS, aborted at sa_ms_downsampling
                            #  (Option A patch has `set REPO_ROOT [file normalize ..]`
                            #   which from hw/hls/ resolves to <repo>/hw, not <repo>)

# Option C wrapper (per-target invocation, env-var passing)
cmd /c 'call settings64.bat && powershell -File runs\remote_machine\run_all_csim.ps1'
# 10/10 PASS
```

## Results per target

| # | Top                  | Wall (s) | inside-vitis | golden-loaded?   |
|---|----------------------|---------:|--------------|------------------|
| 1 | sa_conv2d_int        |        9 | CSim done 0 err | stem_real soft-skip (hardcoded path); 4 synthetic subtests OK |
| 2 | sa_conv2d_bn         |       10 | CSim done 0 err | synthetic only |
| 3 | sa_lif_expand        |        8 | CSim done 0 err | synthetic only |
| 4 | sa_maxpool_or        |        8 | CSim done 0 err | synthetic only |
| 5 | sa_ms_downsampling   |       16 | CSim done 0 err | layer_00_stem, **98304 elems byte-identical (DUT vs GOLDEN OK)** |
| 6 | sa_sep_conv          |       25 | CSim done 0 err | sep_conv_smoke, **49152 elems byte-identical** |
| 7 | sa_ms_all_conv_block |      169 | CSim done 0 err | layer_01_acb1, **98304 elems byte-identical** |
| 8 | sa_spike_sppf        |       18 | CSim done 0 err | layer_08_sppf, **12288 elems byte-identical** |
| 9 | sa_detect_head       |        9 | CSim done 0 err | layer_11_detect, **12288 elems byte-identical** |
| 10 | sa_tiny_fpga_top    |      737 | CSim done 0 err | **end-to-end 12288 elems byte-identical (DUT vs GOLDEN OK)** |
| total |                  |     1011 | 10 PASS / 0 FAIL | 6 testbenches loaded real golden |

## Outputs

| Path | Size | Note |
|---|---:|---|
| `runs/remote_machine/step1_csim_optionC_stdout.log` | ~86 KB | Full inside-vitis trace (UTF-8) |
| `runs/remote_machine/step1_csim_optionC_driverout.log` | ~700 B | Per-target wall + exit summary |
| `runs/remote_machine/step1_csim_stdout.log` | ~25 KB | Earlier Option-A attempt log (4/10 PASS, retained for diff vs Option C) |
| `hw/hls/csim_sa_*/` (10 dirs) | ~10-100 MB each | csim project artifacts (gitignored; build only) |

## Key metrics

- **PASS rate**: 10 / 10 targets (after Option C fallback)
- **Byte-identical end-to-end** on `sa_tiny_fpga_top` (12288 elems, INT8 detect-head output)
- **Compiler**: Vitis HLS 2024.1 internal Clang
- **0 FAIL markers**, **0 nonzero return**, **0 simulation failed** across full Option C log
- 50+ deprecated-pragma WARN per target (`#pragma HLS INTERFACE m_axi` old-syntax) — expected per ADR-0005, M2-W2 backlog
- Build warning `__GMP_LIBGMP_DLL macro redefined` × 1 per target — Vitis HLS 2024.1 internal header conflict, harmless

## Issues

### Issue 1 (RESOLVED, recorded for the next session): Main's Option A patch has `set REPO_ROOT [file normalize ..]` bug

When invoked from `hw/hls/` (per the canonical `cd hw\hls && vitis_hls -f run_csim.tcl` flow), the TCL `..` resolves to `<repo>/hw`, not `<repo>`. Resulting env vars:

```
SA_REPO_ROOT  = .../SpikeYOLO_FPGA/hw                                      (wrong; should be repo root)
SA_WEIGHT_DIR = .../SpikeYOLO_FPGA/hw/models/exploded                       (path does not exist)
SA_GOLDEN_DIR = .../SpikeYOLO_FPGA/hw/tests/golden/exploded/layer_00_stem  (path does not exist)
```

Targets 1-4 (synthetic) pass anyway because they don't read these. Target 5+ fail on file open.

**Fix**: change `hw/hls/run_csim.tcl` line:
```tcl
set REPO_ROOT  [file normalize ..]
```
to:
```tcl
set REPO_ROOT  [file normalize ../..]
```

Remote cannot modify `hw/hls/run_csim.tcl` per protocol. Filed for B1 owner / Main Claude in `runs/remote_machine/REPLIES_FROM_REMOTE.md` (this commit).

### Issue 2 (workaround): `-tclargs` fragile under cmd /c quoting

Initial Option C used `vitis_hls -f script.tcl -tclargs <TOP> ...` but Vitis HLS 2024.1 saw `argv[0] = "-f"` when invoked via `cmd /c "..."`. Worked around by switching to env-var parameter passing (`OPT_C_TOP / OPT_C_SRCS_CSV / OPT_C_TBS_CSV`). See updated `runs/remote_machine/run_csim_one_target.tcl` and `run_all_csim.ps1`.

### Issue 3 (workaround): UTF-16 mangling

Initial Option C captured vitis_hls output into a PowerShell variable then `Out-File -Encoding utf8 -Append`. This mixed cmd's UTF-16 output with PS file BOM, producing garbled CJK in the log. Fixed by piping cmd's stdout/stderr **directly** to the log file (`cmd /c "vitis_hls ... >> $Stdout 2>&1"`) and using `Add-Content -Encoding ascii` for short summary lines.

### Issue 4 (informational): `stem_real` soft-skip in `tb_conv2d_int.cpp`

Has hardcoded `tests/golden/exploded/layer_00_stem` with no env_or override, so always soft-skips on Vitis HLS CWD. Not a regression — testbench is designed to skip when load fails. Other 4 synthetic subtests still validate the kernel. No action needed.

### Issue 5 (informational): `tiny_fpga_regmap.yaml` is documented but ungenerated

`hw/hls/README.md` lines 42/108/118 reference it as a Contract 3 deliverable but no generator script exists. `hw/vivado/build_bd.tcl` doesn't actually consume it (uses VLNV + assign_bd_address). Step 5 will succeed without it. Future B1 task: write the regmap emitter.

## Next step

Skip Step 2 (cosim) per Main Claude's REPLY (10/10 PASS → cosim deferred to PR-label gate).
Begin Step 3: `vitis_hls -f run_synth.tcl` for 5 csynth targets (~25 min on this Ryzen).
