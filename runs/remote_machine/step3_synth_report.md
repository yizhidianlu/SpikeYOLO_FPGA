# Step 3 — Vitis HLS C-synthesis (attempts 1-4, all BLOCKED)

## Status: BLOCKED (4th attempt — offset arrays demoted to scalar register, HLS 214-323)

## Attempts

| # | Patch | Error | URGENT_ASK |
|---|---|---|---|
| 1 | vanilla | HLS 214-298 struct-of-ptr | URGENT_ASK_2 |
| 2 | Option α DISAGGREGATE pragma | HLS 214-298 (pragma no-op for args) | URGENT_ASK_3 |
| 3 | Plan β Variant 2 ptr-to-ptr | HLS 214-134 ptr-to-ptr unsupported | URGENT_ASK_4 |
| 4 | Plan β Variant 1 flat pools + offsets | **HLS 214-323** offset arrays demoted to scalar register port | **URGENT_ASK_5** |

## Latest error

```
WARNING: [HLS 214-450] Ignore address on register port 'shift_offsets'  (line 359)
WARNING: [HLS 214-450] Ignore address on register port 'w_offsets'      (line 360)
WARNING: [HLS 214-450] Ignore address on register port 'bias_offsets'   (line 360)
... (many more)
ERROR: [HLS 214-323] Address computation on scalar port 'w_offsets' is not supported
ERROR: [HLS 214-323] Address computation on scalar port 'bias_offsets' is not supported
ERROR: [HLS 214-323] Address computation on scalar port 'shift_offsets' is not supported
```

Root cause hypothesis: 6 m_axi ports sharing `gmem2` bundle; the 3 offset arrays (depth=30) are too lightweight, Vitis demotes them to scalar register. See URGENT_ASK_5.md for full analysis + Plan β Variant 1.1 proposal (move offsets to separate bundle / increase depth).

## Next step

Awaiting Plan β Variant 1.1 patch in `REPLIES_FROM_MAIN.md`. Continuing loop. Step 4 / 5 / 6 remain blocked.
