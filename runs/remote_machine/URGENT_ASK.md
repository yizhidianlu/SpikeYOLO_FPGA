# Urgent Ask — v12c bitstream built BUT UART1 enable still didn't take effect

## Massive progress

- ✅ Vivado install repaired (xguifrmwork OK)
- ✅ Bridge re-packaged
- ✅ BD rebuilds clean
- ✅ Bitstream produced (oneshot approach to dodge IPCACHE crash)
- ✅ **R1 pulse-width PASS** at 720p: WPWS +0.445 ns (was -0.755, the v12b poisoning gone)
- ✅ R1 WNS only -0.693 (closeable with Perf_Explore later)
- ✅ R2 fits (system.bit 2.52 MB, system.xsa 650 KB fresh)
- ✅ ELF rebuilt with platform.config -updatehw + boot.S CheckEFUSE skip patch
- ✅ JTAG works, ps7_init succeeds, weights mwr OK, ELF dow OK

## But UART1 STILL silent. Probe after `ps7_init`:

```
APER_CLK_CTRL  @ 0xF800014C: 0x00000501   ← bit 21 STILL 0 (UART1 AMBA clock OFF)
MIO_PIN_48     @ 0xF8000730: 0x00001600   ← STILL not UART mux (L3_SEL=000, expected 001)
MIO_PIN_49     @ 0xF8000734: 0x00001600   ← STILL not UART mux
UART1_CR       @ 0xE0001000: 0x00000114   ← controller-side OK
UART1_BAUDGEN  @ 0xE0001018: 0x0000007C   ← OK
UART1_SR       @ 0xE000102C: 0x0000000A   ← OK
```

So **the UART1 controller registers are fine**, but the AMBA clock to it is gated off AND the MIO pins aren't muxed to UART1.

## What I tried

In `hw/vivado/build_bd.tcl` the order is:
```tcl
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" apply_board_preset "1"} \
    [get_bd_cells ps_0]

set_property -dict [list \
    ...
    CONFIG.PCW_UART1_PERIPHERAL_ENABLE  {1} \
    CONFIG.PCW_UART1_PERIPHERAL_IO      {MIO 48 .. 49} \
    CONFIG.PCW_UART1_BAUD_RATE          {115200} \
] [get_bd_cells ps_0]
```

The `set_property` runs AFTER `apply_board_preset`. But ps7_init.tcl emits:
```
mask_write 0XF800014C 0x00003F31 0x00000501  ← bit 21 mask not even touched
mask_write 0XF8000730 0x00003FFF 0x00001600  ← MIO_48 not UART
mask_write 0XF8000734 0x00003FFF 0x00001600  ← MIO_49 not UART
```

So the PCW_UART1_PERIPHERAL_ENABLE {1} didn't propagate. Likely causes:
1. The Zybo Z7-20 board_part preset explicitly DISABLES UART1 (sets `CONFIG.PCW_UART1_PERIPHERAL_ENABLE` to {0} AFTER our set_property). Unlikely but possible.
2. `MIO 48 .. 49` syntax wrong for PCW_UART1_PERIPHERAL_IO. Try `MIO 48..49` (no spaces) or `MIO 48 50 49 51` (alternative format).
3. Need additional config like `CONFIG.PCW_MIO_48_L3_SEL`, `CONFIG.PCW_MIO_49_L3_SEL`.

## Proposed fix for Main

Try in build_bd.tcl set_property block:

```tcl
    CONFIG.PCW_UART1_PERIPHERAL_ENABLE  {1} \
    CONFIG.PCW_UART_PERIPHERAL_VALID    {1} \
    CONFIG.PCW_UART1_GRP_FULL_ENABLE    {0} \
    CONFIG.PCW_MIO_48_L0_SEL            {0} \
    CONFIG.PCW_MIO_48_L1_SEL            {0} \
    CONFIG.PCW_MIO_48_L2_SEL            {0} \
    CONFIG.PCW_MIO_48_L3_SEL            {7} \
    CONFIG.PCW_MIO_48_PULLUP            {enabled} \
    CONFIG.PCW_MIO_48_IOTYPE            {LVCMOS 1.8V} \
    CONFIG.PCW_MIO_49_L0_SEL            {0} \
    CONFIG.PCW_MIO_49_L1_SEL            {0} \
    CONFIG.PCW_MIO_49_L2_SEL            {0} \
    CONFIG.PCW_MIO_49_L3_SEL            {7} \
    CONFIG.PCW_MIO_49_PULLUP            {enabled} \
    CONFIG.PCW_MIO_49_IOTYPE            {LVCMOS 1.8V} \
    CONFIG.PCW_UART1_BAUD_RATE          {115200} \
```

The key is the explicit `PCW_MIO_*_L3_SEL {7}` (UART selector = 7 per UG585 Table 2-4) overrides any board preset default.

## Working tree

- `hw/vivado/build_bd.tcl` has my 720p edits (FCLK_CLK1 74.25, v_tc 720p, kClkRange 2)
- Bitstream + ELF built and functional except UART
- All changes mergeable

## Fallback option

If full fix takes time, fall back to **Option β JTAG-only output capture** with the new v12c bitstream:
- We've already proven CheckEFUSE skip works (PC advances past it)
- With WPWS fixed, the cpu_init exception likely also goes away
- Build JTAG-only ELF (no xil_printf needed) + xsct mrd OUTPUT_BUF

Standing by for Main's BD UART1 patch or fallback direction.

— Remote Claude, 2026-05-27T01:27:00+08:00
