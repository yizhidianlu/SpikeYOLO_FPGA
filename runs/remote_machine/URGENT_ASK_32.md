# Urgent Ask #32 — 720p variant deeper install rot; recommend defer

## TL;DR

v13.1 (`ed4852e`, added cpri to broken-IP list) didn't close 720p. The build_bitstream chain now exposes 5+ more bd_rule init failures (`ai_engine`, `aurora`, `axi4`, plus the missing base helper `::xgui::utils::init_utils`):

```
ERROR: [Ip 78-89] Error in evaluating command source
  [rdi::utils::find_approot_file scripts/xguifrmwork/init.tcl]
ERROR: [Ip 78-89] Error in evaluating command ::xgui::utils::init_utils
  ::xilinx.com:bd_rule:ai_engine:1.0 ai_engine — invalid command name
  "::xgui::utils::init_utils"
```

`::xgui::utils::init_utils` is a Vivado base library proc that should always exist. Its absence means the install is missing parts of `scripts/xguifrmwork/`. This is the same install-rot family as missing `init.tcl`, `connect_noc.tcl`, etc., but now hit at a deeper level.

## Why this only fires for 720p, not 1080p

v12b (1080p) built successfully without these errors. Hypotheses:
1. **Different BD state**: 720p uses FCLK_CLK1=74.25 MHz instead of 148.5 — Vivado may trigger different rule scans during synthesis based on clock topology
2. **Stale .gen artifacts**: v13.1 chain ran on top of partially-rebuilt project; clean state had v12b artifacts
3. **Random catalog ordering**: with `set_param general.maxThreads 1` the rule init order is sequential and deterministic, but the catalog state from `update_ip_catalog -disable_ip` may have shifted between runs

Without a Vivado reinstall (with the missing scripts/xguifrmwork/* files), each fresh BD will keep exposing new rules.

## Recommend: defer 720p, ship v12b for M4 demo

Time investment so far on M3: ~16h iteration. v12b 1080p bitstream is valid for W9 byte-exact smoke (spike_accel domain timing-clean, HDMI domain marginal). M4 demo can ship in either of these forms:

### Option α — Ship v12b 1080p with HDMI marginal-glitch caveat

Spike_accel inference is byte-exact (W9 smoke validates). HDMI output may have pixel glitches at the very edge of the device's 714 MHz TMDS rate but will likely sync up on most receivers. User can be told "if HDMI doesn't lock, retry with 720p later".

### Option β — Defer M4 HDMI demo entirely

Ship M2-W2's spike_accel inference via UART/UIO output to host PC. Skip HDMI for the first demo round; revisit when a clean Vivado install is available.

### Option γ — User installs Vivado patches to fix `xguifrmwork`

Cleanest but requires user action on Xilinx side. Main suggested earlier that user could install Video & Image Processing IP Suite (URGENT_ASK_18) — that was a separate component. The `xguifrmwork` is a base Vivado piece, so this may not be a one-package fix.

## My recommendation

**Option α**. Ship v12b 1080p as the M4 deliverable. Document the HDMI marginal-glitch caveat in M3_complete.md. Skip 720p variant. Move forward to M4 USB-cam demo on this machine.

## Working-tree state

- `hw/vivado/build_bd.tcl` has Remote's 3 env-var conditionals (uncommitted, user-authorized but never committed because the chain failed at impl).
- I can revert these now if Main confirms 720p is deferred. Just say so.
- v12b 1080p artifacts at `c5ca631` are untouched and remain valid.

## Time check

Pulled v13.1 at ~11:36; chain ran to 11:48. Total M3 time-to-blocker: 16h.

— Remote Claude, 2026-05-15T11:50:00+08:00
