# Real Distillation Training (A1 W8)

End-to-end resumable distillation of SpikeYOLO 23M -> tiny_fpga 1.16M
using val2017-alias (5K imgs) at 256x256, 30 epoch, batch 16.

ETA: ~3h on RTX 5060 Laptop 8GB. Loss = 1.0*det + 1.5*kd_logits + 0.5*feat_align + 0.3*spike_rate (all four ACTIVE since W8).

## Start (or resume)

```bat
tools\quant\start_real_training.bat
```

Auto-detects `runs/distill/resumable/latest.pt`; if present, resumes from there
(model weights + optimizer state + scheduler state + RNG). If absent, fresh start.

PID is written to `runs/distill/real_training.pid`. Logs:
- stdout/stderr: `runs/distill/real_training_stdout.log`, `_stderr.log`
- per-step CSV: `runs/distill/real_training_log.csv` (epoch,step,loss_total,loss_det,loss_kd,loss_align,loss_spike,lr)
- per-epoch resumable ckpt: `runs/distill/resumable/latest.pt` + `epoch_NN.pt`
- per-epoch state_dict snapshot: `models/tiny_fpga_fp32_distilled_real_epNN.pt`

## Monitor

```bash
bash tools/ci/monitor_distill_local.sh --md
# or:
tail -f runs/distill/real_training_log.csv
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv -l 5
```

## Graceful stop (preserves progress)

- **Foreground console** (rare with this Hidden launch): press `Ctrl+C` or `Ctrl+Break` -> Python signal handler saves resume ckpt then exits clean.
- **Background process**: graceful is **not possible** on Windows from the outside (`taskkill /F` does not trigger Python signal handlers). Workaround: every epoch end auto-saves to `latest.pt`, so worst-case kill loses ≤1 epoch (5-10 min).

## Force stop

```bat
tools\quant\stop_real_training.bat
```

Kills PID via `taskkill /F`. Re-launch with `start_real_training.bat` to resume from `latest.pt`.

## Resume after reboot / power loss

1. Open PowerShell or cmd, `cd C:\Users\jielu\Desktop\Project\SpikeYOLO`.
2. Run `tools\quant\start_real_training.bat`.
3. It detects `runs/distill/resumable/latest.pt` and continues from saved epoch.

Config drift guard: a SHA256 of the YAML config is stored in each ckpt; resume errors out if the active config differs (override with `--force-resume` if you knowingly tweaked LR / weights mid-run).

## Output artifacts (after 30 epoch)

- `models/tiny_fpga_fp32_distilled_real.pt` — final FP32 student (full Module, post-unwrap).
- `models/tiny_fpga_fp32_distilled_real_ep30.pt` — last per-epoch state_dict.
- `runs/distill/resumable/latest.pt` — last resumable (can re-launch from here for further training).

## Appendix B: optional Windows Task Scheduler at-startup

If you want auto-resume after every reboot, add a Task Scheduler entry:

```
schtasks /Create /SC ONSTART /TN "SpikeYOLO_distill_resume" ^
  /TR "C:\Users\jielu\Desktop\Project\SpikeYOLO\tools\quant\start_real_training.bat" ^
  /RU "%USERNAME%" /F
```

Disable with `schtasks /Delete /TN "SpikeYOLO_distill_resume" /F` once training completes.
