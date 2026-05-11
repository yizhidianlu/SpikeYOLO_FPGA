# ADR-0002: Compute budget for A1 30-epoch distillation

- Status: PROPOSED — pending user budget acknowledgement
- Date: 2026-05-11
- Deciders: D1 System Verification (D1-session-2026-05-11), needs user sign-off before A1 starts the run
- Affected risk: R8 (`distill_not_converging`)
- Affected playbooks: A1, D1
- Affected files: `tools/quant/distill_from_teacher.py`, `tools/quant/distill_config.yaml`, `models/tiny_fpga_fp32_distilled.pt`, `runs/baseline_summary.json`

## Problem

A1 has a working trainer skeleton (W2/W3) but `student_distilled` mAP in `runs/baseline_summary.json` is null because the 30-epoch knowledge-distillation loop has not run. The teacher is 23 M params @ 640×640; the student is 1.6 M params @ 256×256. With `distill_config.yaml` defaults (AdamW 5e-4 cosine, batch 64, 30 epochs, COCO train2017 ≈ 118 k imgs), the run takes roughly 50 GPU-h on a single A100 (80 GB). On the local RTX 5060 Laptop (8 GB) the same run extrapolates to ~250 GPU-h (≈ 10.4 days continuous) and may force batch ≤ 16 due to teacher activation memory, with non-trivial OOM risk in the multi-resolution `avgpool_from_640` path.

## Options

| Dimension | A. Cloud A100 (Lambda Labs / RunPod, on-demand) | B. Local RTX 5060 Laptop 8 GB | C. Colab Pro+ A100 (monthly) |
|---|---|---|---|
| Wall time | ~50 h ≈ 2.1 days (1× A100 80 GB, batch 64) | ~250 h ≈ 10.4 days (extrapolated 4–6×) | ~70 h ≈ 2.9 days (24-h session caps + queue) |
| Direct cost | ~$1.10 / h × 50 ≈ **$55 USD** | $0 (electricity, ~$2 if metered) | $50 / month (priority queue but no SLA on A100) |
| Interruption risk | Low. Spot pricing requires checkpoint+resume; on-demand is uninterrupted. | High. Laptop thermal throttling, OS update reboots, sleep events. | Medium. 24-h session ceiling forces resume each day; queue may bump to V100 / T4. |
| Checkpoint strategy | Every 5 epochs to S3 / GDrive; `--resume <ckpt>` already in skeleton. | Every 1 epoch to local disk; manual rsync to repo on completion. | Every epoch to mounted GDrive; reattach session each day. |
| OOM / batch cap | Batch 64 fits comfortably (teacher fwd+student fwd+adapter ≈ 18 GB peak). | Batch ≤ 16 likely; LR schedule needs re-tune; convergence quality degraded. | Batch 32–64 depending on which A100 SKU is allocated. |
| Reproducibility | Strong (pinned CUDA, fixed driver, captured in `runs/distill_<sha>.log`). | Strong (single host) but slow iteration. | Weak (heterogeneous backends across days). |
| Recommended | ★★★★★ DEFAULT | ★ debug-only | ★★★ student-budget alternative |

## Decision

**Recommended: Option A (cloud A100, on-demand).** Defer to user for final approval because of the $55 cash outlay. Until the user acknowledges the budget, Option B is the only path A1 may use, and it is restricted to ≤ 2 sanity epochs (smoke runs, not full convergence). Option C is acceptable if user prefers a recurring subscription, but D1 will not own the session-resume churn.

The recommendation balances: shortest wall time → fastest unblock of contracts that depend on `student_distilled.pt` (A2 golden regen, A1 v1.0.3 PTQ regen, eventual R4 mAP-delta gate), plus the cleanest checkpoint + reproducibility story for D1's monthly regression.

## R8 escalation path

Even under Option A, distill may not converge. The escalation chain is:

1. After epoch 5: D1 reads `distill_map` from the resume checkpoint's val log. If `< 5.0`, suspect data-loader / tap-shape regression — pause, file `risk:R8` issue, A1 to verify `teacher_inference_mode == avgpool_from_640` and that 5D→4D squeeze is active in the trainer (the W3 fix must be present).
2. After epoch 15: if `distill_map < 12.0`, raise KD temperature 4 → 8 (handler from `RISK_RULES.yaml` R8) and rerun the last 5 epochs from ckpt.
3. After epoch 30: if final `distill_map < 18.0` (R8 trigger), invoke A1 fallback Phase 5 (QAT for 5–10 epochs at INT8) and rerun PTQ. Budget impact: +20 GPU-h ≈ $22.
4. If still `< 18.0` after QAT: surface to user as a feature-coverage problem, not a budget problem; do not silently buy more compute.

## User acknowledgement checklist

A1 must NOT start a billable cloud run until the user has explicitly answered each of the following in a single PR comment or chat reply:

- [ ] Approve baseline budget of $55 USD on Lambda Labs / RunPod for one full 30-epoch run.
- [ ] Approve up to one R8-handler retry (+$22 ≈ $77 total) without requiring a second sign-off; any further compute requires re-approval.
- [ ] Approve weights upload destination for ckpts (GDrive folder URL OR S3 bucket name OR local-only).
- [ ] Confirm preferred provider (Lambda Labs vs RunPod vs other) and whether on-demand or spot is OK.
- [ ] Provide billing handle (no card details in repo — D1 expects user to drive the billing account directly; A1 receives only a temporary SSH key).

If user picks Option C instead, the only check needed is the GDrive folder for ckpts.

If user declines all paid options and insists on Option B, A1 will produce `models/tiny_fpga_fp32_distilled_localB.pt` from a 2-epoch sanity run only (no R8 evaluation possible) and the contract for `student_distilled` mAP remains null through M2; downstream Agents must be informed that the int8 .npz they consume is the post-init Kaiming version (mAP 0.00).

## Monitoring during the run

D1 will follow the run via whichever telemetry A1 wires up. Acceptable choices, ordered by D1 preference:

1. tensorboard event file synced to GDrive every 5 min (zero-config, browser-based).
2. wandb if A1 already has an account (project `spikeyolo-distill`, run name `m1_distill_<git_sha>`).
3. Plain CSV `runs/distill_progress.csv` with columns `epoch,step,loss,lr,distill_map,timestamp` rsynced every 10 min — the lowest-tech option, still sufficient for D1's monthly graph.

D1 does NOT need realtime tensorboard if the CSV is updated faithfully; pick whichever costs A1 the least friction.

## Post-training handoff

When the distill run completes:

1. A1 uploads the final `models/tiny_fpga_fp32_distilled.pt` (and the chosen telemetry artifact) to the agreed location.
2. A1 reruns `tools/quant/eval_quant_map.py --weights ... --target-degradation 1.0` locally and updates `runs/baseline_summary.json` with the real `student_distilled` number.
3. A1 reruns `tools/quant/run_ptq.py` to regenerate `models/tiny_fpga_int8.{npz,bin}` and writes a Contracts changelog v1.0.3 entry (sha256 + motivation).
4. A2 reruns `tools/verify/extract_golden.py` against the new .npz (golden_index sha256 update, `pad_autocorrected: false`).
5. A1 opens a PR `[A1] M2: distill complete + PTQ regen` carrying the .pt, .npz, .bin, and the changelog entry. CI's `numpy_regress.yml` `quant-change` label gate runs the heavy mAP-delta job; pass means the `student_distilled` row is also a contract refresh.
6. D1 cites the new mAP in the next monthly report's section 4.

## Decision log

This ADR is the canonical reference. Once the user acknowledges, append a brief note here (date, choice, billing handle reference) and flip status to `accepted`. Until then it stays `proposed` and A1 stays paused on real-train.

## References

- A1 sprint reports: `runs/A1_baseline_status.md`, `runs/A1_W1_complete_report.md`, `runs/A1_W3_report.md` (all flag R8 as pending escalation)
- D1 playbook: `docs/AGENT_PLAYBOOKS/D1_verification.md` ("Risk Handlers" table)
- Risk definition: `docs/RISK_RULES.yaml` R8
- Trainer: `tools/quant/distill_from_teacher.py`, `tools/quant/distill_config.yaml`
