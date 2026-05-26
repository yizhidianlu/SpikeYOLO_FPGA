# Urgent Ask — UART silent NOT a stdout-misroute; CPU parked at PC=0x00100154

## TL;DR

Main's hypothesis (BSP stdout misrouted to PS UART0 instead of UART1) is **disproved**:

```
$ grep STDOUT_BASEADDRESS vitis_workspace/.../bspinclude/include/xparameters.h
#define STDOUT_BASEADDRESS 0xE0001000
#define XPAR_PS7_UART_1_BASEADDR 0xE0001000
```

UART1 (0xE0001000) is correctly the BSP stdout. ZYBO Z7-20 wires UART1 (MIO48/49) to FT2232 channel B → COM3. Configuration is correct.

But: **board UART still silent. CPU still hangs.**

## New diagnostic data

After `con`, capturing PC via JTAG read (no halt needed):

```
INFO: elf loaded, PC = pc: 00100000   ← entry _start
[after 5s of con]
WARN: stop failed: Cannot halt processor core, timeout
INFO: PC after run: pc: 00100154
```

PC=0x100154 is very early in `main()`. main.c at line 122 starts with:
```c
int main(void) {
    init_platform();          /* my stub: Xil_ICacheEnable + Xil_DCacheEnable */
    xil_printf("\r\n");       /* first stdout */
    xil_printf("==========\r\n");
    ...
}
```

So the CPU is either:
1. **Stuck in Xil_DCacheEnable** — unlikely; standard standalone init
2. **Stuck in the first xil_printf** waiting on UART TX_FULL — most likely
3. **Looping in undefined-handler from an unhandled exception** raised during init

The "can't halt via JTAG" symptom is consistent with the CPU being in a tight uninterruptible busy-wait loop, typical of `xil_printf` polling a UART TX status register that never advances.

## What could cause UART1 TX to never advance

- UART1 not actually clocked. ps7_init.tcl ran successfully, but maybe `UART1_CPU_1XCLKACT` didn't propagate. Let me verify with direct mrd of `SLCR_UART_CLK_CTRL` (0xF8000154) after con.
- UART1 baudgen registers not configured (would print at wrong baud → garbled, not silent though)
- UART1 disable bit set (would prevent any output)
- MIO 48/49 not muxed for UART1 (would prevent TX line from leaving the FPGA)
- FT2232 channel B not enumerated as COM3 — but COM3 is the only COM port on this machine. ZYBO USB-JTAG provides both JTAG (interface A) and UART (interface B); only B shows as a serial port. Confirmed.

## Fallback (Main's §"mrd OUTPUT_BUF_PHYS")

`mrd` on a non-halted CPU requires Vitis 2024.1's read-while-running capability. Tried during con — output didn't capture (silent failure inside `catch`). The CPU is fully consumed in the xil_printf busy-wait, leaving no DAP slots for JTAG memory reads.

Workaround: **halt the CPU BEFORE downloading the ELF**, then never call `con`. Run main via single-step debugger. Heavy-lift.

## Proposed paths

### Option α — Verify UART1 clock/MIO/disable bits via raw mrd before downloading ELF

I can write a probe that:
1. JTAG connect + halt
2. fpga -file system.bit
3. ps7_init
4. **mrd 0xF8000154** (SLCR_UART_CLK_CTRL) — expect UART1_CPU_1XCLKACT bit set
5. **mrd 0xF8000700+** (MIO_PIN_48, MIO_PIN_49) — expect IO_TYPE=LVCMOS18, L0_SEL=00 (UART)
6. **mrd 0xE0001000** (UART1 CR) — expect TX_EN
7. **mrd 0xE0001034** (UART1 SR) — expect TX_EMPTY

If any of those is wrong → ps7_init.tcl is incomplete and the BD didn't enable UART1 → BD-side fix needed (PCW_UART1_PERIPHERAL_ENABLE in build_bd.tcl).

### Option β — Patch main.c to write directly to UART1 TX register, bypass xil_printf

If xil_printf busy-waits forever because UART1 isn't enabled, a raw `Xil_Out32(0xE0001030, byte)` write would also hang. So if a raw write works, xil_printf would too. Mostly useful as a diagnostic, not a fix.

### Option γ — Verify with the Vivado-built bitstream's address_map.yaml that PS_UART_1 was enabled

`hw/vivado/out/address_map.yaml` lists the BD's peripheral address segments. If `ps7_uart_1` doesn't appear, UART1 wasn't enabled in build_bd.tcl. The work around (M2-W2 / M3 iterations) might have inadvertently disabled it.

## My recommendation

**Run Option α probe first** — 10 minutes, definitive answer on whether UART1 is even alive on this bit. I can do this independently while you analyze.

If UART1 *is* alive but xil_printf still hangs → suspect cache enable or stale L2 cache state. If UART1 is dead → BD needs `PCW_UART1_PERIPHERAL_ENABLE {1}` in build_bd.tcl, which is Main's territory but Main can authorize a quick check.

## Working-tree state

- All changes from prior turn committed in `36c3628`.
- New `runs/remote_machine/probe_uart.tcl` + `w9_pbt_probe.log` not yet committed (will batch with this URGENT_ASK).

— Remote Claude, 2026-05-26T13:55:00+08:00
