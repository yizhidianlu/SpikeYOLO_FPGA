#!/bin/sh
# /opt/run_on_board.sh — start the SpikeYOLO demo with sane defaults.
# Pass --bench to emit JSON lines suitable for tools/perf/fps_bench.py.

set -e

BIN=/opt/spike_accel_demo
WEIGHTS=/lib/firmware/tiny_fpga_int8.bin

if [ ! -x "$BIN" ]; then
    echo "missing $BIN" >&2
    exit 1
fi
if [ ! -f "$WEIGHTS" ]; then
    echo "missing $WEIGHTS — flash via scp from PC: scp models/tiny_fpga_int8.bin root@zybo:/lib/firmware/" >&2
    exit 1
fi

# Pin to CPU1 to leave CPU0 for V4L2 IRQ handling
exec taskset -c 1 "$BIN" \
    --cam-dev /dev/video0 \
    --drm-dev /dev/dri/card0 \
    --weights "$WEIGHTS" \
    --cam-size 640x480 \
    "$@"
