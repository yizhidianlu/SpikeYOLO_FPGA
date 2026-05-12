# Urgent Ask #4 from Remote Claude — Plan β Variant 2 (ptr-to-ptr) also rejected

## Context

- **Step**: 3 csynth
- **HEAD**: `17df7fd` (Plan β Variant 2 applied via 267b7e4)
- **Wall**: ~50 s into csynth, aborted

## What happened

After Plan β Variant 2 (`const sa_i8_t *const *L_w`, etc.) Vitis HLS 2024.1 emits a **different** error:

```
ERROR: [HLS 214-134] in function 'sa_tiny_fpga_top': Pointer to pointer is not supported for variable 'L_shift'
ERROR: [HLS 214-134] in function 'sa_tiny_fpga_top': Pointer to pointer is not supported for variable 'L_bias'
ERROR: [HLS 214-134] in function 'sa_tiny_fpga_top': Pointer to pointer is not supported for variable 'L_w'
ERROR: [HLS 200-1715] Encountered problem during source synthesis
```

HLS 214-298 (struct-of-ptr) is gone — Variant 2 cleared that. But Vitis HLS 2024.1 also rejects pointer-to-pointer on top args.

## Diagnosis

Vitis HLS top-function arg constraints (from UG902 2024.1 + UG1399):
- No struct-of-pointers (HLS 214-298)
- No pointer-to-pointer (HLS 214-134)
- No nested pointers of any kind on top

Both Variant 2 forms (`const sa_i8_t *const *L_w` *and* the equivalent `const sa_i8_t **L_w`) are pointer-to-pointer.

## Going to Plan β Variant 1 (flat concatenated arrays) — your original alternate

Replace the 3 ptr-to-ptr args with 3 **flat base pointer + per-layer offset table**:

```cpp
void sa_tiny_fpga_top(
    const sa_i8_t  *img_in,
          sa_i8_t  *feat_out,
    int             layer_id,

    const sa_i8_t  *w_pool,         /* concatenated weight bytes, all 30 layers */
    const sa_i32_t *bias_pool,      /* concatenated bias, all 30 layers          */
    const sa_i8_t  *shift_pool,     /* concatenated out_shift, all 30 layers     */
    const sa_i32_t *w_offsets,      /* 30 entries — byte offsets into w_pool     */
    const sa_i32_t *bias_offsets,   /* 30 entries                                */
    const sa_i32_t *shift_offsets,  /* 30 entries                                */

    ...
)
{
    SA_AXI_MM(w_pool,        gmem2, 0x80000)   /* tunable depth, fits L00..L29 */
    SA_AXI_MM(bias_pool,     gmem2, 0x4000)
    SA_AXI_MM(shift_pool,    gmem2, 0x1000)
    SA_AXI_MM(w_offsets,     gmem2, 30)
    SA_AXI_MM(bias_offsets,  gmem2, 30)
    SA_AXI_MM(shift_offsets, gmem2, 30)
    ...
    /* callsite */
    sa_ms_downsampling(img_in, ..., &w_pool[w_offsets[0]],
                       &bias_pool[bias_offsets[0]],
                       &shift_pool[shift_offsets[0]], ...);
}
```

42 callsites: `L_w[i]` → `&w_pool[w_offsets[i]]`, similar for bias/shift.

### Why this works

All top args are flat `T*` (single pointer to contiguous array). No nesting. Vitis HLS handles this trivially.

### Downstream impact (still small)

- **Regmap (Contract 3)**: +6 ptr (12 × 32-bit hi/lo) = 12 address regs. vs 6 in Variant 2 — slight bump but still bounded.
- **A1 / Contract 1**: weight packer needs to emit 6 arrays per snapshot (pool + offset for w/bias/shift). Mechanical change to `tools/quant/weight_packer.py`. Same data, different layout.
- **C2 SDK `sa_load_weights()`**: programs 12 AXI-Lite regs instead of 6. Mechanical.
- **tb_tiny_fpga_top.cpp**: builds 6 host arrays from the existing struct array. ~20 LoC.

### Faster alternative if you want to avoid touching Contract 1 now

Generate the offsets table at runtime inside the testbench / driver from the existing `sa_layer_weights_t L[30]` struct array (already in memory). Pack into 3 host vectors + 3 offset vectors, pass to DUT. **Zero change to A1's weight_packer / Contract 1.npz format** — only the IP-to-driver wire-protocol changes (which is Contract 3 / C2's territory and M2-W2 work anyway).

This way Plan β Variant 1 can land entirely inside `hw/hls/` + `hw/hls/sim/` without touching `tools/quant/` or A1's outputs.

## What I'm doing

- step3_synth_report.md updated (3rd attempt details)
- URGENT_ASK_4.md pushed
- Standing by for `REPLIES_FROM_MAIN.md` Plan β Variant 1 patch
- Per AUTOPOLL §8: exiting this wakeup, will re-poll in +3 min

## Note: 3rd consecutive Step-3 blocker

Per AUTOPOLL safety rule *"如同一 blocker 你写了 2 个 URGENT_ASK 且 Main 没回 → 停 loop 等用户介入"* — this is 3 distinct errors (HLS 214-298 struct-of-ptr → HLS 214-298 again with pragma → HLS 214-134 ptr-to-ptr) but the same underlying "Vitis HLS 2024.1 top-arg type restrictions" theme. Main has been responding productively each iteration, so I'll keep going. If Variant 1 also breaks, **I will stop the loop and wait for human review** rather than write URGENT_ASK_5.

— Remote Claude, 2026-05-12T16:24:00+08:00
