# URGENT_ASK_17 — `MT41K256M16 HA-125` NOT in Vivado 2024.1 PCW catalog; need fix strategy

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-29T16:40+08:00
**Status:** Stage 3 BD validation blocked; Main needs to pick fix strategy. Full DDR/board-delay diag below.

---

## Error (BD validation at `set_property PARTNO HA-125`)

```
ERROR: [IP_Flow 19-3478] Validation failed for parameter 'PCW UIPARAM DDR PARTNO(PCW_UIPARAM_DDR_PARTNO)'
  with current value 'MT41K256M16 HA-125' for BD Cell 'ps_0'.
PARAM PCW_UIPARAM_DDR_PARTNO :: MT41K256M16 HA-125 is out of range {
  MT41J128M8 JP-125, MT41J128M8 JP-15E, MT41J64M16 JT-125G, MT41J64M16 JT-15E,
  MT41J256M8 DA-107, MT41K128M16 JT-125, MT41J256M8 HX-125, MT41J256M8 HX-15E,
  MT41J256M8 HX-187E, MT41J128M16 HA-107G,
  MT41J128M16 HA-125,           ← closest HA variant (J-die, 1.5V)
  MT41J128M16 HA-15E, MT41J128M16 HA-187E, MT41J512M8 RA-15E,
  MT41K128M16 HA-15E,
  MT41K256M16 RE-125,           ← current board-preset default (wrong die)
  MT41K256M16 RE-15E,
  MT41K256M8 DA-125, MT41K256M8 DA-15E, MT41K256M8 HX-15E,
  MT41J256M16 RE-125,
  Custom
}
```

Vivado 2024.1's PCW IP catalog doesn't list `MT41K256M16 HA-125`. The board (per Digilent docs + JTAG test) is K-die (1.35V) HA rev — Vivado offers HA only as J-die (1.5V) or K-die at lower density (128M).

---

## Board-preset diag (BEFORE my override fails)

```
PCW_UIPARAM_DDR_PARTNO:           MT41K256M16 RE-125   ← Main's diag was right: wrong die
PCW_UIPARAM_DDR_FREQ_MHZ:         533.333333
PCW_UIPARAM_DDR_SPEED_BIN:        DDR3_1066F
PCW_UIPARAM_DDR_CL:               7
PCW_UIPARAM_DDR_T_FAW:            40.0
PCW_UIPARAM_DDR_T_RC:             48.75

Board delays (already set non-zero by preset — your "verify non-zero" concern is moot):
  BOARD_DELAY0:        0.221 ns      DQS_TO_CLK_DELAY_0:  -0.050 ns
  BOARD_DELAY1:        0.222 ns      DQS_TO_CLK_DELAY_1:  -0.044 ns
  BOARD_DELAY2:        0.217 ns      DQS_TO_CLK_DELAY_2:  -0.035 ns
  BOARD_DELAY3:        0.244 ns      DQS_TO_CLK_DELAY_3:  -0.100 ns ← largest negative
```

**Critical observation:** lane 3's `DQS_TO_CLK_DELAY` is `-0.100 ns` (the most negative of the 4 lanes). That matches your JTAG diag *exactly*: byte lane 3 is the one that fails read training. The board preset is pushing the DQS strobe forward (negative skew) most aggressively on lane 3, which on HA silicon (not RE) overshoots the read window.

---

## Three fix strategies (Main picks)

### Option A — pick `MT41J128M16 HA-125` (closest HA-die preset)

```diff
 set_property -dict [list \
-    CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 HA-125} \
+    CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41J128M16 HA-125} \
 ] [get_bd_cells ps_0]
```

Pro: gets HA-die read-training timing.
Con: J-die is **1.5V**; board provides **1.35V** (K-die). ps7_init.c will configure DDR_VDD_SEL for 1.5V → board's 1.35V supply will be undervoltage relative to spec → may brick DDR init worse than the original symptom. **Risky.**

### Option B — keep `MT41K256M16 RE-125` but fix lane-3 DQS_TO_CLK_DELAY (surgical)

```diff
 set_property -dict [list \
-    CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 HA-125} \
+    CONFIG.PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_3 {0.050} \
 ] [get_bd_cells ps_0]
```

(Or any positive value 0.0..+0.1 — pushing back so the DQS-to-CLK skew lands in the HA read window.)

Pro: keeps board preset's matching voltage class + small surgical fix. Doesn't depend on existence of an HA preset.
Con: tuning by guesswork without scope access; may need iteration. Doesn't help if lanes 0/1/2 also drift on HA silicon (your JTAG showed only lane 3 bad, so this might be enough).

### Option C — switch PARTNO to `Custom`, type the MT41K256M16 HA-125 datasheet timing parameters explicitly

```diff
 set_property -dict [list \
-    CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 HA-125} \
+    CONFIG.PCW_UIPARAM_DDR_PARTNO {Custom} \
+    CONFIG.PCW_UIPARAM_DDR_T_FAW {30.0} \
+    CONFIG.PCW_UIPARAM_DDR_T_RC  {48.75} \
+    CONFIG.PCW_UIPARAM_DDR_T_RAS_MIN {35.0} \
+    CONFIG.PCW_UIPARAM_DDR_T_RP {13.75} \
+    CONFIG.PCW_UIPARAM_DDR_T_RCD {13.75} \
+    CONFIG.PCW_UIPARAM_DDR_T_RRD {7.5} \
+    CONFIG.PCW_UIPARAM_DDR_T_REFI {7800} \
+    CONFIG.PCW_UIPARAM_DDR_T_WR {15.0} \
+    CONFIG.PCW_UIPARAM_DDR_T_RTP {7.5} \
+    CONFIG.PCW_UIPARAM_DDR_CL {7} \
+    CONFIG.PCW_UIPARAM_DDR_CWL {6} \
+    CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH {16 Bit} \
+    ...
 ] [get_bd_cells ps_0]
```

(Numbers from MT41K256M16HA-125 datasheet, JEDEC PC3-8500 / DDR3-1066 spec — verify against Digilent's official ref design too.)

Pro: literally correct part timing.
Con: ~15 explicit params; transcription risk; the board-preset's BOARD_DELAY + DQS skew defaults may need to be re-applied since switching to Custom may reset them.

**My recommendation:** **Option B first** (smallest blast radius — only touches lane 3 which is the proven-bad one). If after rebuild #3 the user still hits FSBL hang on board, escalate to Option C (Custom).

If Option B is the call, you can also broaden the surgical fix to all 4 lanes to be safer:

```bitbake
CONFIG.PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_0 {0.000}
CONFIG.PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_1 {0.000}
CONFIG.PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_2 {0.000}
CONFIG.PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_3 {0.000}
```

(Zero is the "no skew" baseline — read window centered on DQS rise.)

---

## Cloud sandbox state

- Vivado BD failed at `set_property PARTNO HA-125` — exit 1, no XSA written.
- Vivado_init.tcl set up with `board.repoPaths {/tmp/dig-boards/new/board_files}` (so `:1.2` board file is found — that part works).
- Out dir wiped; awaiting Main's call before re-running.
- HLS still blocked on URGENT_ASK_16 (independent path, doesn't affect this).

---

## Consolidated status

| Ask | Status |
|---|---|
| All earlier (1–15) | ✅ on origin/main |
| URGENT_ASK_16 (HLS struct-of-pointer) | ⏳ pending |
| **URGENT_ASK_17 (DDR PARTNO catalog gap)** | ⏳ **this ask** |

— Cloud Claude
