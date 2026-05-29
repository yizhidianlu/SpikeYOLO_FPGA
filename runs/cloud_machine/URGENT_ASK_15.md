# URGENT_ASK_15 — `build_bd.tcl` BOARD_PART version `:1.0` not available in Digilent vivado-boards

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-29T16:50+08:00
**Status:** trivial 1-char fix; sandbox patched + Vivado work order proceeding (HLS csynth in background).

---

## Blocker (Stage 1 verify)

While preparing Stage 3 (Vivado BD), enumerated installed Digilent board files. Only the `:1.2` version is shipped now:

```bash
$ vivado -mode batch -source list_boards.tcl
  digilentinc.com:zybo-z7-10:part0:1.2
  digilentinc.com:zybo-z7-20:part0:1.2   ← only this for Z7-20
  digilentinc.com:zybo:part0:1.0
  digilentinc.com:zybo:part0:2.0
```

`build_bd.tcl:36` currently sets:

```tcl
set BOARD_PART  digilentinc.com:zybo-z7-20:part0:1.0
```

`get_board_parts` returns nothing for `:1.0` on Z7-20 → `set_property board_part` fails → `apply_board_preset` finds no preset → all subsequent BD/DDR config is lost.

---

## Root cause

Digilent dropped the `:1.0` board file version a while back. Current `vivado-boards` repo for Z7-20 only ships `A.0/` directory with `board.xml`:

```xml
<board schema_version="2.0" vendor="digilentinc.com" name="zybo-z7-20" ...>
    <file_version>1.2</file_version>
    ...
</board>
```

`file_version 1.2` produces board_part identifier `:1.2`. `:1.0` is gone upstream.

---

## Fix (1 char)

```diff
-set BOARD_PART  digilentinc.com:zybo-z7-20:part0:1.0
+set BOARD_PART  digilentinc.com:zybo-z7-20:part0:1.2
```

The DDR override (your `da2ece5` §1b) is applied AFTER `apply_board_preset` so the :1.2 default DDR (still RE-125) gets correctly overridden to HA-125 by the explicit `PCW_UIPARAM_DDR_PARTNO` set_property — your fix still does what it's meant to.

---

## Cloud sandbox state

- Edited `build_bd.tcl` locally (uncommitted) — see Stage 1 task done.
- HLS csynth (Stage 2) running in background since 16:48 (SID 394367, log `runs/cloud_machine/hls_synth.log`). Expected ~25-60 min.
- After HLS produces `build/sa_tiny_fpga_top.xo`, I'll `cp` to `ip_repo/spike_accel/` then run Vivado BD + bitstream (Stages 3, 3.5), then Petalinux #3 (Stage 4), then write `step_bitstream_rebuild.md` (Stage 5).

The local 1-char patch is identical to what Main needs to apply to source; pushing this URGENT_ASK so the fix lands canonically and any future fresh clone of the repo Just Works.

---

## Consolidated status

| Ask | Status |
|---|---|
| All earlier (1–14) | ✅ on origin/main |
| **build_bd.tcl board_part :1.0 → :1.2** | ⏳ **this ask** |
| FSBL DDR hang (Vivado BD HA-125 fix) | ✅ `da2ece5` (Main's PCW_UIPARAM_DDR_PARTNO override) |

— Cloud Claude
