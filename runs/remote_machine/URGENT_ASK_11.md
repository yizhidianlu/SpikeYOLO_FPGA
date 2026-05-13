# Urgent Ask #11 — Step 5 impl blocked: Vivado 2024.1 install missing roe_framer auto_utils.tcl

## TL;DR

After `e340928` (macro shadowing fix), Step 3 re-csynth produced a **real** IP (536 m_axi mentions, all 5 `m_axi_gmem*` masters present). Step 5 BD construction **succeeded** (`build_bd.tcl OK — BD saved`). But `build_bitstream.tcl` → `launch_runs synth_1` immediately fails because the Vivado 2024.1 install on this machine has a **partial/corrupt roe_framer IP install** — the rule script auto-loader can't proceed.

Step 3 also exposed **R1 (timing) + R2 (resource) hard fires** in the HLS estimate — see §"Side issues" below.

## What happened — install corruption

```
# launch_runs synth_1 -jobs 8
couldn't read file "E:/Applaction/Xilinx/Vivado/2024.1/data/ip/xilinx/roe_framer_v3_0/automation/auto_utils.tcl": no such file or directory

    while executing "source [returnAutomationDir $REPOSITORY $MODEL_NAME]"
    invoked from within "if { [file exists [returnAutomationDir $REPOSITORY $MODEL_NAME]] } { ..."
    invoked from within "if { [llength [get_ipdefs -quiet -filter {NAME =~ *roe_framer*}]] > 0 } { ..."
    (procedure "loadMyAutomationLibAtStartup" line 4)
    invoked from within "loadMyAutomationLibAtStartup"
    (file "E:/Applaction/Xilinx/Vivado/2024.1/data/rsb/rules/roe_framer/bd.tcl" line 139)

ERROR: [BD 41-69] Error sourcing TCL script: ...
ERROR: [Vivado 12-4756] Launch of runs aborted due to earlier errors while preparing sub-designs for run execution.
```

The `roe_framer/bd.tcl` rule (under `E:\Applaction\Xilinx\Vivado\2024.1\data\rsb\rules\`) auto-loads at every `launch_runs` invocation and fails because `roe_framer_v3_0/automation/auto_utils.tcl` is missing under `data/ip/xilinx/`. This is an install-side issue, not project-side.

The `if { [llength [get_ipdefs ...roe_framer*]] > 0 }` guard at the outer level passes (roe_framer IP partial-install left some files), then the inner `source [returnAutomationDir ...]` walks into the missing file. There's no `[file exists ...]` guard at the call site.

## Options for the install issue

### Option α — Repair Vivado IP catalog (Main / human)

Re-run Vivado installer's "Update / Repair" with `roe_framer` IP component selected. The missing `auto_utils.tcl` and related `automation/` files come back. ~5 min.

Alternative quick test (without re-install): does the same fail on a minimal `create_project + launch_runs` empty project? If yes → confirmed Vivado-install issue. If no → something in our project triggers the broken rule path.

### Option β — Disable rule script auto-load via Vivado param

If a param like `set_param project.disableExternalRuleScripts 1` exists (need to verify in UG835), a one-line wrapper before `source build_bitstream.tcl` would skip rule loading. I can try this empirically — but it may have unintended side effects on other automation that build_bd.tcl already uses.

### Option γ — Skip `launch_runs synth_1`, use raw Vivado synth instead

Replace the `launch_runs synth_1 ; wait_on_run synth_1` pattern with direct `synth_design -top system_wrapper -part xc7z020clg400-1` — bypasses runs-infrastructure entirely. Then `place_design + route_design + write_bitstream` manually.

**Effort**: ~10 lines of new tcl. **Risk**: medium (skips Vivado's automatic constraint propagation; may need to manually source the .xdc).

### Option δ — Force-touch the missing file

`touch E:\Applaction\Xilinx\Vivado\2024.1\data\ip\xilinx\roe_framer_v3_0\automation\auto_utils.tcl` (empty file). The source script would no-op. **Hacky** but possibly works as a quick unblock. Writes to Xilinx install which is normally read-only / protected — needs admin.

## Side issues from Step 3 re-csynth (worth Main's attention)

### R1 (timing) regression

`sa_tiny_fpga_top_csynth.rpt`:

```
Clock     Target     Estimated   Uncertainty
ap_clk    10.00 ns   26.921 ns   2.70 ns
```

WNS estimate = 10 - 26.921 - 2.70 = **-19.62 ns** (previously -0.04 ns with scalar/ap_memory bindings). Real m_axi adapter logic adds multi-cycle DDR3 burst paths. HLS estimates are pessimistic; Vivado P&R typically tightens by 1-3 ns. But going from -0.04 → -19.62 is too large for impl alone to close.

### R2 (resource) regression

`sa_tiny_fpga_top_csynth.rpt`:

| Resource | Used | Avail | % |
|---|---:|---:|---:|
| BRAM_18K |   12 |   280 |   4% |
| DSP      |  119 |   220 |  54% |
| FF       | 80944 | 106400 | 76% |
| **LUT**  | **126220** | **53200** | **237%** |

LUT **2.37× over Z-7020 budget**. HLS estimates inflate LUT by typically 1.5-2× vs Vivado synth, so real LUT might be 60-80K — still 110-150% over. **Design does not fit on Z-7020 as-is**.

R2 handlers from `docs/RISK_RULES.yaml`:
- "Shrink PE array 16x8 → 8x8"
- "Time-multiplex shared PE across layers"
- "DW conv to LUT-based shift-add"

### Combined picture

- Interface mode FIXED — IP is functionally correct (5 m_axi masters wired correctly per build_bd.tcl)
- BUT design size + timing exceed Z-7020 envelope by 2-3×
- Needs **architectural shrink** (one of the R2 handlers) or **target swap** (Z-7035, Z-7045)

## My recommendation

1. **Option α** (re-install roe_framer / repair Vivado IP catalog) to unblock launch_runs — quickest path to empirical Vivado-side LUT count
2. **In parallel**: B1 owner reviews R2 handler choice. Most likely Plan A: reduce PE width / dataflow inlining in `sa_ms_all_conv_block` (the biggest leaf at 79640 FF / 124263 LUT in `Instance`)
3. **Step 5 BD partially succeeded** — BD construction + IP integration done; only impl/bitstream is blocked. Once Vivado fixed + LUT shrunk, we can resume.

## What I'm doing

- URGENT_ASK_11 + step5 partial report committed and pushed.
- Step 3 re-csynth artifacts preserved (5 .zip in build/, reports/, extracted IP at ip_repo/spike_accel/sa_tiny_fpga_top/).
- Step 5 BD partially produced — system.bd, system.hwh saved at hw/vivado/out/.
- Standing by per AUTOPOLL.

— Remote Claude, 2026-05-13T09:35:00+08:00
