# hw/vivado — System Architect (B2 Agent)

**Owner**: B2 System Architect Agent — see [`docs/AGENT_PLAYBOOKS/B2_system_architect.md`](../../docs/AGENT_PLAYBOOKS/B2_system_architect.md)

## Purpose

Vivado 2023.2 Block Design integrating spike_accel IP (from B1), AXI DMA, VDMA, Digilent rgb2dvi HDMI TX, Zynq PS, and DDR3 controller. Produces the bitstream and the address map that drives C1 device tree and C2 driver.

## Layout

```
build_bd.tcl           BD creation (top-level — full wiring lives here)
build_bitstream.tcl    synth + impl + write_bitstream
constraints/           XDC pin assignments (ZYBO Z7-20)
out/                   system.bit, system.hwh, system.xsa, address_map.yaml
ip_repo/
  digilent/            vivado-library submodule (rgb2dvi, axi_dynclk, dvi2rgb, ...)
  spike_accel/         B1 .xo drop point + tiny_fpga_regmap.yaml
scripts/               helper Tcl (setup_ip_repo, cleanup_ip_repo, axi_protocol_check,
                       synth_impl, synth_metrics, build_bd wrapper)
```

## Setup (first time per clone)

```bash
bash hw/vivado/scripts/setup_ip_repo.sh        # Linux / WSL / Git Bash
hw\vivado\scripts\setup_ip_repo.bat            # Windows cmd
```

The script registers Digilent's `vivado-library` as a git submodule under
`hw/vivado/ip_repo/digilent/`. The `-f` flag bypasses the local `.gitignore`
that exists to deter hand-unzipped releases. On a fresh clone this leaves
`.gitmodules` and the submodule entry staged — review and commit if you
want them in your PR.

## Cleanup

```bash
bash hw/vivado/scripts/cleanup_ip_repo.sh           # soft: drop workdir only
bash hw/vivado/scripts/cleanup_ip_repo.sh --hard    # also drop submodule + .git/modules entry
```

Use `--hard` only when you intend to commit a removal of the submodule
registration. Otherwise the soft mode is enough to recover from a corrupted
checkout (re-run `setup_ip_repo.sh` to restore).

## B1 IP hand-off into `ip_repo/spike_accel/`

```bash
# in hw/hls/
make hls-synth-tiny       # exports build/sa_tiny_fpga_top.xo
cp build/sa_tiny_fpga_top.xo  ../vivado/ip_repo/spike_accel/
cp build/tiny_fpga_regmap.yaml ../vivado/ip_repo/spike_accel/
```

`build_bd.tcl` looks for `sa_tiny_fpga_top.xo` in either the HLS build dir
or `ip_repo/spike_accel/`. The IP shows up as
`xilinx.com:hls:sa_tiny_fpga_top:1.0` in the catalog.

## Build

```bash
source /opt/Xilinx/Vivado/2023.2/settings64.sh
bash hw/vivado/scripts/setup_ip_repo.sh        # once, see above
vivado -mode batch -source hw/vivado/build_bd.tcl
vivado -mode batch -source hw/vivado/build_bitstream.tcl
vivado -mode batch -source hw/vivado/scripts/synth_metrics.tcl
```

`synth_metrics.tcl` emits `out/timing.csv` (WNS/WHS/Fmax/LUT/DSP/BRAM) which
is the canonical input to the D2 CI risk dispatcher (`docs/RISK_RULES.yaml`
R1 / R2).

## M2-W1 self-hosted Vivado runner checklist

Before kicking off the first real synth on the self-hosted Linux box:

- [ ] Vivado 2023.2 installed and licensed (xc7z020 needs Webpack)
- [ ] `git clone --recurse-submodules` (or run `setup_ip_repo.sh`)
- [ ] `hw/hls/build/sa_tiny_fpga_top.xo` present (B1 must have run
      `make hls-synth-tiny` first; CI mirrors the .xo into
      `ip_repo/spike_accel/`)
- [ ] `hw/vivado/ip_repo/digilent/vivado-library/ip/rgb2dvi/` exists
- [ ] `out/` directory cleaned (`rm -rf hw/vivado/out/spike_zybo*`)
- [ ] `vivado -mode batch -source hw/vivado/build_bd.tcl` returns 0
- [ ] `vivado -mode batch -source hw/vivado/build_bitstream.tcl` produces
      `out/system.bit` and `out/system.hwh`
- [ ] `vivado -mode batch -source hw/vivado/scripts/synth_metrics.tcl`
      writes `out/timing.csv` with WNS >= 0 ns
- [ ] Update `out/address_map.yaml` with `bitstream_path` and `hwh_path`
      fields (placeholders today — filled by the runner after a real synth)

## Contracts produced

- **C4**: `out/address_map.yaml` -> C2 (uio_config.dts auto-gen) + C1 (devtree)

## Acceptance gates

- WNS >= 0 ns (M4 @ 100 MHz -> M5 @ 150 MHz)
- HDMI 1080p@60 outputs test pattern (M2)
- AXI DMA loopback bandwidth >= 1.2 GB/s

## References

- Digilent ZYBO Z7-20 Reference Manual + Master XDC
- Xilinx UG994 Designing IP Subsystems Using IP Integrator
- Xilinx PG059 AXI Interconnect
- Xilinx PG082 AXI VDMA
- Xilinx PG288 SmartConnect
- Digilent rgb2dvi vivado-library: <https://github.com/Digilent/vivado-library>
