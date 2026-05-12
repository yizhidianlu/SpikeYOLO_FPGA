# Step 3 — Vitis HLS C-synthesis (6 attempts, all BLOCKED → loop TRULY STOPPED)

## Status: BLOCKED — LOOP STOPPED per Main's V1.2-is-last-try authorization

See `URGENT_ASK_6.md` for full analysis. V1.2 failed too; same HLS 214-323 error code but now firing on the **pool pointers** (w_pool 512KB included), not just the offset arrays. New root-cause hypothesis: Vitis 2024.1 demotion is driven by **body-code pointer arithmetic / cast usage pattern**, not pragma depth/bundle.

## Attempts

| # | Patch (commit) | Top sig | Error |
|---|---|---|---|
| 1 | vanilla | struct-of-ptr | HLS 214-298 |
| 2 | `62e1e19` α DISAGGREGATE | (same) | HLS 214-298 (no-op for args) |
| 3 | `267b7e4` β V2 ptr-to-ptr | 3 × `**` | HLS 214-134 |
| 4 | `d4182bd` β V1 flat + 6 ptrs | 6 × `*` | HLS 214-323 (offsets demoted) |
| 5 | `e7c70ef` β V1.1 gmem5+d=256 | (same) | HLS 214-323 (offsets STILL demoted) |
| 6 | `14de4fa` β V1.2 embed-at-head | 3 × `*` | **HLS 214-323 (pools NOW demoted)** |

## Loop state

**TRULY STOPPED.** No ScheduleWakeup. Awaiting user direction (V1.3 hardcoded compile-time offsets / V1.4 sub-function refactor / audit / skip / other).
