# hw/vivado — System Architect (B2 Agent)

**Owner**: B2 System Architect Agent — see [`docs/AGENT_PLAYBOOKS/B2_system_architect.md`](../../docs/AGENT_PLAYBOOKS/B2_system_architect.md)

## Purpose

Vivado 2023.2 Block Design integrating spike_accel IP (from B1), AXI DMA, VDMA, Xilinx/Digilent HDMI TX, Zynq PS, and DDR3 controller. Produces the bitstream and the address map that drives C1 device tree and C2 driver.

## Layout

```
build_bd.tcl           BD creation
build_bitstream.tcl    synth + impl + write_bitstream
constraints/           XDC pin assignments (ZYBO Z7-20)
out/                   system.bit, system.hwh, system.xsa, address_map.yaml
reports/               timing_summary.rpt, utilization.rpt
scripts/               helper Tcl (axi_protocol_check etc.)
```

## Build

```bash
source /opt/Xilinx/Vivado/2023.2/settings64.sh
vivado -mode batch -source build_bd.tcl
vivado -mode batch -source build_bitstream.tcl
```

## Contracts produced

- **C4**: `out/address_map.yaml` → C2 (uio_config.dts auto-gen)

## Acceptance gates

- WNS ≥ 0 ns (M4 @ 100 MHz → M5 @ 150 MHz)
- HDMI 1080p@60 outputs test pattern (M2)
- AXI DMA loopback bandwidth ≥ 1.2 GB/s

## References

- Digilent ZYBO Z7-20 Reference Manual + Master XDC
- Xilinx UG994 Designing IP Subsystems Using IP Integrator
- Xilinx PG059 AXI Interconnect
