# sw/driver — Kernel-space access (C2 Agent)

**Owner**: C2 Driver & SDK Agent — see [`docs/AGENT_PLAYBOOKS/C2_driver_sdk.md`](../../docs/AGENT_PLAYBOOKS/C2_driver_sdk.md)

## Purpose

Linux kernel-side glue for the spike_accel IP. Primary path is **UIO + dma-buf** (user-space), with an optional char driver fallback if UIO performance proves insufficient.

## Layout

```
uio_config.dts                 Auto-generated from hw/vivado/out/address_map.yaml
spike_accel.c                  Optional Linux char driver (built only if UIO fallback needed)
Makefile                       Out-of-tree kernel module build
```

## Generating uio_config.dts

**Do not edit by hand** — regenerate from address_map.yaml:

```bash
python ../../tools/ci/gen_dts.py \
    --addr-map ../../hw/vivado/out/address_map.yaml \
    --output uio_config.dts
```

CI verifies `git diff uio_config.dts` is empty.

## Acceptance gates

- `gen_dts.py` reproduces the committed `uio_config.dts` byte-for-byte
- `/dev/uio0` shows up on boot
- IRQ latency < 50 μs

## References

- linux/Documentation/driver-api/uio-howto.rst
- u-dma-buf upstream
