# Digilent vendor IP repo

Drop-in location for Digilent's `vivado-library` so that `build_bd.tcl` can
resolve the VLNV `digilentinc.com:ip:rgb2dvi:1.4` (and friends) when it
instantiates the HDMI Tx pipeline picked in
`docs/decisions/0001_hdmi_tx_selection.md`.

## How to populate

Recommended: git submodule (so `setup_ip_repo.sh` can re-pull on a fresh
clone).

```bash
cd hw/vivado/ip_repo/digilent
git submodule add https://github.com/Digilent/vivado-library.git
# subsequent updates:
git submodule update --init --recursive
```

`hw/vivado/build_bd.tcl` already does
`set_property ip_repo_paths` + `update_ip_catalog` after `create_project`, so
no further wiring is needed once `vivado-library/` exists.

Alternative (offline / no-submodule): download the latest release zip from
`https://github.com/Digilent/vivado-library/releases`, extract to
`hw/vivado/ip_repo/digilent/vivado-library/`. Layout must match the upstream
repo so the VLNV path resolves.

## IPs we consume

- `digilentinc.com:ip:rgb2dvi:1.4`  — HDMI Tx serializer (active)
- `digilentinc.com:ip:dvi2rgb:2.0`  — HDMI Rx (reserved, post-M5 if camera
  swap to HDMI input)
- `digilentinc.com:ip:axi_dynclk:1.0` — pixel-clock generator for 1080p60

## License

`vivado-library/` upstream is BSD-3-Clause. Not redistributed in this repo —
fetched at build time per the recipe above.
