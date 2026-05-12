# Urgent Ask #2 from Remote Claude — Step 3 csynth blocked on struct-of-pointers top arg

## Context

- **Step**: 3 (Vitis HLS C-synthesis)
- **Current git HEAD**: `0b3df61` (step1 PASS commit)
- **Wall time so far on Step 3**: ~1 min (aborted very early in csynth)
- **Aggregate Step 1 wall**: ~21 min (10/10 PASS; see step1_csim_report.md)

## What happened

`vitis_hls -f run_synth.tcl` aborted at target 1/5 (`sa_tiny_fpga_top`):

```
INFO: [HLS 200-1995] There were 49,754 instructions in the design after the
                    'Compile/Link' phase
ERROR: [HLS 214-298] Struct type with pointer type inside on top function
                    argument is not supported, please disaggregate argument 'L'
                    manually (src/tiny_fpga_top.cpp:148:0)
ERROR: [HLS 200-1715] Encountered problem during source synthesis
Pre-synthesis failed.
```

The struct is `sa_layer_weights_t` (defined in `hw/hls/include/dtypes.h`):

```cpp
typedef struct {
    const sa_i8_t  *w;
    const sa_i32_t *bias;
    const sa_i8_t  *out_shift;
} sa_layer_weights_t;
```

Used in `sa_tiny_fpga_top()` signature at `tiny_fpga_top.cpp:134`:

```cpp
void sa_tiny_fpga_top(
    const sa_i8_t  *img_in,
          sa_i8_t  *feat_out,
    int             layer_id,
    const sa_layer_weights_t *L,        /* L[30]                              */
    ...
)
```

The header comment at `tiny_fpga_top.cpp:104-110` already discusses the design choice ("Alternative: 30 individual m_axi ports — explodes the IP regmap to >100 AXI registers. We pick the array form").

## My diagnosis

Vitis HLS 2024.1 rejects struct-of-pointers on top function args because each pointer would need its own m_axi master port and the bundle doesn't expose them. The HLS hint "please disaggregate argument 'L' manually" points directly at `#pragma HLS DISAGGREGATE`.

Step 5 is fully blocked — `build_bd.tcl` instantiates `spike_accel_0` via VLNV `xilinx.com:hls:sa_tiny_fpga_top:1.0`, which requires `sa_tiny_fpga_top.xo` from this synth.

## Options

### Option α — `#pragma HLS DISAGGREGATE variable=L`  *(recommended, ~1 line)*

Inside `sa_tiny_fpga_top()` body, immediately after the opening brace:

```cpp
void sa_tiny_fpga_top(
    const sa_i8_t  *img_in,
    sa_i8_t  *feat_out,
    int       layer_id,
    const sa_layer_weights_t *L,
    ...
){
#pragma HLS DISAGGREGATE variable=L           // <— add this line
    SA_AXI_MM(img_in,        gmem0, 196608)
    ...
}
```

After disaggregate, the struct's 3 pointer members get individual m_axi ports. Regmap adds ~6 × 30 = 180 address registers — actually, since L is a pointer-to-array, this might collapse to just 3 m_axi ports (one per struct field, each pointing to a flat array of 30 entries). Either way Vitis decides.

**Effort**: 1 line.
**Risk**: low. May change regmap layout — Contract 3 documentation (`tiny_fpga_regmap.yaml`) needs updating, but no functional change.
**Owner**: B1 / Main Claude.

### Option β — Refactor to 3 flat top-level arrays

Replace `L` with `w_all / bias_all / out_shift_all` flat arrays, index by per-layer offset table.

**Effort**: ~30 min (touches all 30 layer call-sites in `tiny_fpga_top.cpp`).
**Risk**: medium (offset arithmetic; easy to off-by-one).
**Benefit**: simplest regmap (3 ptr, 30-entry offset table fits in BRAM).
**Owner**: B1.

### Option γ — Remote-only leaf-kernel workaround (partial progress, does NOT unblock Step 5)

Remote writes a one-target synth driver (similar to Option C csim wrapper) and synths just the 4 leaf kernels (`sa_ms_downsampling / sa_ms_all_conv_block / sa_spike_sppf / sa_detect_head`). Generates partial Step 4 utilization snapshots.

**Effort (Remote)**: ~10 min wrapper + ~20-30 min synth (~25 min for ms_all_conv_block estimated).
**Does NOT produce `sa_tiny_fpga_top.xo`** → Step 5 still blocked.
**Owner**: Remote (no source mods).

## What I'm doing while waiting

- Nothing destructive.
- step3_synth_report.md and this URGENT_ASK_2.md committed and pushed.
- Will not attempt Option γ leaf-synth without explicit go-ahead from Main / user — given Main's fix for Option α is ~1 line, waiting probably saves more time than partial leaf data buys.
- Will periodically `git pull` and check `REPLIES_FROM_MAIN.md`.

## My recommendation

**Option α**. One-line fix, no regmap blow-up if Vitis collapses the m_axi correctly, no semantic change. If regmap-wise Vitis explodes ports, **Option β** is the principled fix.

**Option γ** I'd only run if Main is ≥ 1 hour out — partial leaf utilization is mostly useful for sanity-checking the resource budget against the per-kernel slice, but `tiny_fpga_top` is the headline IP and what Step 5 actually needs.

## Awaiting reply by

ASAP, since this blocks the entire remaining pipeline (Steps 3, 4, 5, 6). If Main is online, ~5 min should be enough to push the pragma.

— Remote Claude, 2026-05-12T15:53:00+08:00
