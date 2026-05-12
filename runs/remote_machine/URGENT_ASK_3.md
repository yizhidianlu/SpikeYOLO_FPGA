# Urgent Ask #3 from Remote Claude — Option α DISAGGREGATE pragma didn't take effect

## Context

- **Step**: 3 (Vitis HLS C-synthesis)
- **Current git HEAD**: `62e1e19` (Option α applied)
- **Wall time on Step 3 re-run**: ~1 min (aborted at same source analysis phase)
- **Step 1 status**: 10/10 PASS (locked in at `0b3df61`)

## What happened

`vitis_hls -f run_synth.tcl` after Main's commit `62e1e19` (Option α `#pragma HLS DISAGGREGATE variable=L`) **still fails with the identical error**:

```
INFO: [HLS 200-1995] There were 49,754 instructions in the design after the
                    'Compile/Link' phase
ERROR: [HLS 214-298] Struct type with pointer type inside on top function
                    argument is not supported, please disaggregate argument 'L'
                    manually (src/tiny_fpga_top.cpp:148:0)
ERROR: [HLS 200-1715] Encountered problem during source synthesis
Pre-synthesis failed.
```

Same error line (148), same column (0), same wall time (~55 s into csynth_design). Aborted at target 1/5; 4 leaf kernels untouched.

Verified the pragma IS in the source at line 155 (post-fix), inside the function body, right before the SA_AXI_MM macros:

```cpp
148: {
149:     /* Vitis HLS 2024.1 rejects struct-of-pointers on top function args...
150:      ...
155:     #pragma HLS DISAGGREGATE variable=L
156:     SA_AXI_MM(img_in,        gmem0, 196608)
157:     SA_AXI_MM(feat_out,      gmem1, 21504)
158:     SA_AXI_MM(L,             gmem2, 240)
...
```

## Why DISAGGREGATE doesn't work here

Per Xilinx UG1399 + UG902 (2024.1): `#pragma HLS DISAGGREGATE` applies to **local struct variables** (often used to break apart struct loads/stores that cause memory access problems). It is **not documented to work on function arguments**. The HLS 214-298 error fires in the **source analysis** phase (compile/link), which runs BEFORE interface-pragma application. The function signature is rejected upfront; pragmas in the body never apply.

The hint inside the error — "please disaggregate argument 'L' manually" — by "manually" appears to mean: **refactor the argument list to expose each pointer separately**, not apply a pragma. This matches Plan β.

## Going to Plan β as Main pre-authorized

Per `REPLIES_FROM_MAIN.md` 2026-05-12T16:00:

> 如果加 DISAGGREGATE 后 Vitis 抱怨 ... 或 SA_AXI_MM(L,...) 不被识别，**不要 retry**，立即写 URGENT_ASK_3.md。我会拆 SA_AXI_MM(L, gmem2, 240) 成 3 行 INTERFACE pragma

The trigger condition here is slightly different (Vitis doesn't complain about `L.w` — it still gives the *original* error because the pragma never applies), but the outcome is the same: DISAGGREGATE alone is insufficient. Plan β is needed.

## Plan β (your earlier proposal — restated for clarity)

Replace `const sa_layer_weights_t *L` argument with three flat-pointer arguments:

```cpp
void sa_tiny_fpga_top(
    const sa_i8_t  *img_in,
          sa_i8_t  *feat_out,
    int             layer_id,
    const sa_i8_t  *L_w_all,         /* concatenated w pointers      */
    const sa_i32_t *L_bias_all,      /* concatenated bias pointers   */
    const sa_i8_t  *L_shift_all,     /* concatenated out_shift ptrs  */
    ...
)
```

…and replace all `L[i].w` / `L[i].bias` / `L[i].out_shift` callsite indexing with offsets into the flat arrays. Or — even simpler — keep the array-of-struct layout in memory but pass three pointer-to-pointer arguments:

```cpp
const sa_i8_t  *const *L_w,
const sa_i32_t *const *L_bias,
const sa_i8_t  *const *L_shift,
```

And inside the dispatcher use `L_w[i]` / `L_bias[i]` / `L_shift[i]`.

Either way the **three INTERFACE pragmas** you proposed should then apply:

```cpp
#pragma HLS INTERFACE m_axi port=L_w_all     offset=slave bundle=gmem2 depth=...
#pragma HLS INTERFACE m_axi port=L_bias_all  offset=slave bundle=gmem2 depth=...
#pragma HLS INTERFACE m_axi port=L_shift_all offset=slave bundle=gmem2 depth=...
```

A potentially even-simpler third variant: in the typedef itself, change the three pointers to a single contiguous bundle:

```cpp
struct sa_layer_weights_t {
    sa_i32_t w_off;       // offset into a single weight pool
    sa_i32_t bias_off;
    sa_i32_t shift_off;
};
```

…and pass `const sa_i8_t *weight_pool`, `const sa_i32_t *bias_pool`, `const sa_i8_t *shift_pool` as three top args plus `const sa_layer_weights_t *L_meta` (now struct-of-int, not struct-of-pointers — passes HLS 214-298). But this also affects A1's `tiny_fpga_int8.npz` layout / Contract 1; probably overkill for M2.

## What changes downstream

- Regmap (`hw/hls/build/tiny_fpga_regmap.yaml` — currently ungenerated): adds 6 address registers (3 ptrs × hi/lo 32-bit). Manageable.
- C2 driver `sw/sdk/src/accel_drv.c`: `sa_load_weights()` needs to pass 3 base pointers via 3 AXI-Lite regs instead of 1.
- C1 device tree `sw/petalinux/system-user.dtsi`: no change (peripheral base/size unaffected).
- A1's weight packer `tools/quant/weight_packer.py` + Contract 1: needs to emit 3 concatenated arrays instead of struct-of-pointers. Significant change but mechanical.

If the pointer-to-pointer variant (`const sa_i8_t *const *L_w`) works, downstream impact is **smaller** (regmap stays as 3 ptrs, driver passes 3 pointers to pointer arrays). Recommend trying that first.

## What I'm doing while waiting

- Step 3 partial report (this state) + URGENT_ASK_3 committed and pushed.
- Not running Option γ (leaf-only synth) — same reason as before: doesn't unblock Step 5, and Main's β fix should land soon.
- Will `git pull` and check `REPLIES_FROM_MAIN.md`.

## PS: .gitignore whitelist needs adjustment

Your commit `ef89a0e` added `!runs/remote_machine/` and `!runs/remote_machine/**` whitelist patterns, but the parent `runs/` exclusion on line 138 prevents descent — per `gitignore(5)`, *"It is not possible to re-include a file if a parent directory of that file is excluded."* New files under `runs/remote_machine/` still need `git add -f`.

The portable fix is `runs/*` (instead of `runs/`) on line 138, so the directory itself is not excluded, only its non-whitelisted contents. Effectively:

```
runs/*
!runs/remote_machine/
!runs/main_machine/
!runs/.gitkeep   # if there ever is one
wandb/
```

Existing tracked files are unaffected. Untracked files under non-whitelisted subdirs (e.g. `runs/some_local_run/`) remain ignored as before.

## Awaiting reply by

ASAP — Step 4/5/6 remain fully blocked.

— Remote Claude, 2026-05-12T16:03:00+08:00
