# ADR-0001: HDMI Tx IP selection for ZYBO Z7-20

- **Status**: accepted
- **Date**: 2026-05-11
- **Deciders**: B2 System Architect (B2-session-2026-05-11-W3)
- **Affected contracts**: C4 (`hw/vivado/out/address_map.yaml`), implicitly C1 device tree
- **Affected playbooks**: B2, C1, C2, C3

## Context

The ZYBO Z7-20 exposes a single HDMI Tx connector (J11) wired through on-board
TMDS buffers. The PL must drive it with a video stream produced by the AXI VDMA
that reads framebuffers (256x256 detection overlay composited onto the camera
preview, scaled to 1080p) from DDR3. We have three candidate IPs.

| Option | IP | Pro | Con |
|---|---|---|---|
| A | Digilent `rgb2dvi` v1.4 | board-matched PHY, BSD-licensed, used by every Digilent ZYBO HDMI demo | DVI signaling — no audio, no HDR, capped at 1080p@60 |
| B | Xilinx HDMI 1.4 / 2.0 TX Subsystem | true HDMI, audio, EDID handshake | HDMI 2.0 needs a paid license; HDMI 1.4 free version is overkill for a bbox overlay |
| C | External ADV7511 over a Pmod-HDMI breakout | fully documented driver | ZYBO's on-board HDMI is not ADV7511; requires extra hardware (BoM change) |

## Decision

**Choose Option A (Digilent `rgb2dvi` v1.4).** The on-board HDMI Tx PHY on the
ZYBO Z7-20 is the exact one the Digilent reference designs target, so `rgb2dvi`
plugs in with zero PHY tuning. The lack of audio is acceptable: the only payload
on the HDMI line is the bbox overlay composited onto the camera preview, and the
end-to-end product KPI (>= 30 FPS detection overlay at 1080p) does not include
sound. DVI vs HDMI is invisible to a sink that supports HDMI 1.x (every consumer
monitor we will use).

## Consequences

- **C4 (address_map.yaml)**: `hdmi_tx.compat` stays `"digilent,axi-hdmi"` — already
  consistent with `docs/CONTRACTS.md` L262; no contract change needed.
- **C1 device tree**: corresponding node will use the same compatible string;
  no ALSA / sound subsystem required in Petalinux.
- **C2/C3 (driver / app)**: no audio stack, no ALSA dependency in `libspike_accel`
  or the demo binary.
- **VDMA output format**: AXI4-Stream RGB888 (24-bit), 1920 x 1080 @ 60 Hz with
  pixel clock = 148.5 MHz. VDMA `c_mm2s_max_burst_length = 256`, framebuffer
  stride = 1920 * 3 = 5760 B (kept 8 B-aligned).
- **Vivado clocking**: PL needs a second clock domain at 148.5 MHz for the
  pixel clock and 5x = 742.5 MHz for TMDS serialization (handled internally by
  `rgb2dvi` via OSERDESE2).

## Fallback path

If `rgb2dvi` cannot meet timing in M5 (post 150 MHz retiming on the compute
domain, OSERDESE2 placement may interact badly with PE-array routing), B2 will
re-spin the BD with **Xilinx HDMI 1.4 TX Subsystem (free license tier)**. This
is a separate redesign event tracked outside the canonical R1..R7 risk table —
since R3 already covers the DDR3-bandwidth path that is the more likely 1080p
failure mode, we treat HDMI IP swap as an isolated mitigation, not a numbered
risk. Estimated cost: 3 engineer-days (BD re-route + re-XDC + re-license).

If both DVI and Xilinx HDMI fail, fall back to 720p output (already a
documented R3 handler) before considering Option C, which would require a BoM
change.

## References

- `docs/CONTRACTS.md` Contract 4 (L259-262) — already encodes Option A's compat
- `docs/AGENT_PLAYBOOKS/B2_system_architect.md` "Decision log" pointer
- Digilent ZYBO Z7-20 reference manual, section "HDMI source"
- Digilent rgb2dvi IP repo: github.com/Digilent/vivado-library
