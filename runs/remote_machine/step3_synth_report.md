# Step 3 — Vitis HLS C-synthesis

## Status: BLOCKED (0/5 csynth targets completed)
## Wall time: 58 s (vitis_hls invocation; aborted at first target after 55 s of csynth)
## Started: 2026-05-12T15:50:17+08:00
## Completed: 2026-05-12T15:51:15+08:00 (abort)

## Commands run

```cmd
call E:\Applaction\Xilinx\Vitis_HLS\2024.1\settings64.bat
cd hw\hls
vitis_hls -f run_synth.tcl
```

Background-launched from PowerShell `cmd /c` wrapper. Output captured to
`runs/remote_machine/step3_synth_stdout.log` (~22 KB).

## Results per target

| # | Top                  | csynth status | Note |
|---|----------------------|----------------|------|
| 1 | sa_tiny_fpga_top     | **ERROR**     | `[HLS 214-298] Struct type with pointer type inside on top function argument is not supported, please disaggregate argument 'L' manually` |
| 2 | sa_ms_downsampling   | not run       | tcl foreach aborted on prior error |
| 3 | sa_ms_all_conv_block | not run       | (same) |
| 4 | sa_spike_sppf        | not run       | (same) |
| 5 | sa_detect_head       | not run       | (same) |

## Issues — BLOCKER

**Root cause**: `sa_tiny_fpga_top` takes `const sa_layer_weights_t *L` as an argument. The typedef is in `hw/hls/include/dtypes.h`:

```cpp
typedef struct {
    const sa_i8_t  *w;
    const sa_i32_t *bias;
    const sa_i8_t  *out_shift;
} sa_layer_weights_t;
```

Vitis HLS 2024.1 rejects struct-of-pointers as a top-function argument. The dispatcher uses `L[0].w` / `L[0].bias` / `L[0].out_shift` indexing inside the body, so the design intent was a packed array of weight-pointer bundles. The header comment in `tiny_fpga_top.cpp` already notes this is a deliberate choice over 30 individual `m_axi` ports.

**Exact log snippet**:

```
ERROR: [HLS 214-298] Struct type with pointer type inside on top function argument is not supported, please disaggregate argument 'L' manually (src/tiny_fpga_top.cpp:148:0)
ERROR: [HLS 200-1715] Encountered problem during source synthesis
INFO: [HLS 200-2161] Finished Command csynth_design Elapsed time: 00:00:55
Pre-synthesis failed.
```

This is a source-code issue in `hw/hls/src/tiny_fpga_top.cpp` (B1 owner). Remote cannot modify it.

Other (non-blocking) findings:
- 50+ deprecated-pragma WARN per file (`#pragma HLS INTERFACE` old syntax, ADR-0005 known)
- 1 block-comment warning: `WARNING: [HLS 207-997] '/*' within block comment (include\op_macros.h:20:19)` — minor, ignore

## Outputs

| Path | Size | Note |
|---|---:|---|
| `runs/remote_machine/step3_synth_stdout.log` | ~22 KB | Full vitis_hls trace including error |
| `hw/hls/build/` | (empty) | No .xo produced |
| `hw/hls/reports/` | (empty) | No utilization / timing |
| `hw/hls/synth_sa_tiny_fpga_top/` | ~few MB | csynth project artifacts (gitignored) |

## Diagnosis & remediation paths

The Vitis HLS hint says "disaggregate argument 'L' manually". Options for the B1 owner:

### Option α — `#pragma HLS DISAGGREGATE variable=L`  *(cleanest, ~1 line)*

Inside `sa_tiny_fpga_top()` body, before any other pragma:

```cpp
void sa_tiny_fpga_top(
    ...
    const sa_layer_weights_t *L,
    ...
){
#pragma HLS DISAGGREGATE variable=L
    SA_AXI_MM(img_in, gmem0, 196608)
    ...
}
```

Tells HLS to expand each struct field into its own m_axi master port. Increases regmap by 6 32-bit address registers (3 ptr × 2 hi/lo) per layer, but Vitis usually packs them efficiently.

Effort: ~1 minute. Risk: low. Regmap impact: contained.

### Option β — Refactor to 3 flat top-level arrays

Replace `const sa_layer_weights_t *L` with:
```cpp
const sa_i8_t  *w_all,
const sa_i32_t *bias_all,
const sa_i8_t  *out_shift_all,
```
And replace `L[i].w / L[i].bias / L[i].out_shift` indexing with computed offsets into the flat arrays.

Effort: ~30 minutes (touch 30 callsites). Risk: medium (offset arithmetic). Regmap impact: 3 ptr only (much cleaner).

### Option γ — Defer M5 sharding refactor (not viable for M2)

The header comment hints at "M5 might shard if PE pipelining needs per-bank locality". M5 isn't here.

## Workaround paths Remote *could* attempt (with approval)

### Option C-leaf — synth just the 4 leaf kernels for partial Step 4 data

Wrap a Python/PowerShell driver that loops the 4 leaf targets only, skipping `sa_tiny_fpga_top`. Gets us utilization + timing snapshots for `sa_ms_downsampling`, `sa_ms_all_conv_block`, `sa_spike_sppf`, `sa_detect_head`. Step 4 gate can run on these.

**Does NOT unblock Step 5** — Vivado BD requires `sa_tiny_fpga_top.xo` to instantiate `spike_accel_0`. The leaf .xo files individually are not consumed by `build_bd.tcl`.

Effort: 10 minutes. Useful if Main is slow to fix. Reversible.

## Awaiting

`URGENT_ASK_2.md` pushed alongside this report. Standing by for Main Claude's
fix to `hw/hls/src/tiny_fpga_top.cpp` per Option α (recommended).

## Next step

Cannot proceed to Step 4 (no reports) or Step 5 (no .xo) until tiny_fpga_top synthesizes. Awaiting reply on `runs/remote_machine/REPLIES_FROM_MAIN.md`.
