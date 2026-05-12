# Step 3 — Vitis HLS C-synthesis (5 attempts, all BLOCKED → loop STOPPED)

## Status: BLOCKED — LOOP STOPPED per Variant 1.1 commitment

See `step3_stop_summary.md` for the rationale (loop self-stop) and Main's pre-authorized next move (Plan β Variant 1.2, embed offsets at pool head).

## Attempts

| # | Patch | Error | Result |
|---|---|---|---|
| 1 | vanilla | HLS 214-298 struct-of-ptr | URGENT_ASK_2 |
| 2 | Option α DISAGGREGATE | HLS 214-298 (no-op for args) | URGENT_ASK_3 |
| 3 | Plan β Variant 2 ptr-to-ptr | HLS 214-134 ptr-to-ptr | URGENT_ASK_4 |
| 4 | Variant 1 flat pools + offsets | HLS 214-323 offsets demoted | URGENT_ASK_5 |
| 5 | Variant 1.1 gmem5 + depth=256 | **HLS 214-323 (identical)** | **stop_summary** |

## Step 4 / 5 / 6 status: unchanged — blocked on `sa_tiny_fpga_top.xo`
