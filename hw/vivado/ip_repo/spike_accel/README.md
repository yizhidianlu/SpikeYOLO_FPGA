# spike_accel IP drop point

This is the BD-side landing zone for B1's HLS-packaged accelerator
(`tiny_fpga_top.xo`). Empty until M2-W1.

## Hand-off recipe (B1 -> B2, M2-W1)

After Vitis HLS synthesis succeeds in `hw/hls/`, B1 copies (or symlinks) the
two artefacts produced there into this directory:

```bash
cp hw/hls/build/tiny_fpga_top.xo            hw/vivado/ip_repo/spike_accel/
cp hw/hls/build/tiny_fpga_regmap.yaml       hw/vivado/ip_repo/spike_accel/
```

`hw/vivado/build_bd.tcl` currently points `ip_repo_paths` at `../hls/build`;
the next BD revision (M2-W1) will switch that to `../ip_repo/spike_accel` so
the BD is self-contained against the checked-in IP repo regardless of where
the HLS build dir lives. `regmap.yaml` is read by Contract 4 tooling
(`tools/ci/gen_dts.py`) to verify register offsets match `address_map.yaml`.

## What goes here (B1 side of Contract 3)

- `tiny_fpga_top.xo` — Vitis-packaged Vivado IP (.zip-of-IP-files)
- `tiny_fpga_regmap.yaml` — register layout per `docs/CONTRACTS.md` L160-204
  (must validate against the schema in Contract 3)

## License

Internal — same as the parent repo. Not redistributed.
