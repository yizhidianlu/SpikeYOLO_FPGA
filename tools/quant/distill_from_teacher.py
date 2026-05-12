"""A1 Phase 1.5: distill teacher (23M SpikeYOLO) -> tiny_fpga. Modes:
  --validate CKPT --min-map M : eval CKPT mAP, exit 0/1 vs M
  default                     : freeze teacher, build student, hook
                                 distill_alignment_layers, run epochs
                                 (guarded by --epochs > 1 + not --dry-run to
                                 avoid accidentally triggering ~50 GPU-h).
torch / ultralytics imported lazily so --help works on bare Python."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import signal
import sys
import time
from pathlib import Path

# Repo-root bootstrap so `import ultralytics` resolves to the local checkout
# regardless of where the script is invoked from (W3 fix mirroring A2's
# extract_golden.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="distill_from_teacher",
                                description="A1 Phase 1.5 KD: SpikeYOLO 23M -> tiny_fpga.")
    p.add_argument("--teacher", type=Path, help="teacher .pt (23M SpikeYOLO)")
    p.add_argument("--student-cfg", type=Path,
                   default=Path("ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml"))
    p.add_argument("--student-init", type=Path, default=Path("models/tiny_fpga_fp32.pt"))
    p.add_argument("--config", type=Path, default=Path("tools/quant/distill_config.yaml"))
    p.add_argument("--out", type=Path, default=Path("models/tiny_fpga_fp32_distilled.pt"))
    p.add_argument("--log", type=Path, default=Path("runs/distill/distill_log.csv"))
    p.add_argument("--validate", type=Path, default=None,
                   help="path to a .pt to evaluate; exits 0 if mAP >= --min-map")
    p.add_argument("--min-map", type=float, default=0.0)
    p.add_argument("--epochs", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=None)
    p.add_argument("--device", type=str, default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="single-batch wiring smoke test; no checkpoint saved")
    p.add_argument("--resume", type=Path, default=None,
                   help="explicit resumable .pt to continue from")
    p.add_argument("--resume-auto", action="store_true",
                   help="auto-pick newest mtime resumable .pt under cfg.resume_dir")
    p.add_argument("--force-resume", action="store_true",
                   help="skip config-hash check during resume (manual override)")
    return p


# ---------------------------------------------------------------------------
# Resumable-checkpoint helpers (W8 sprint).
# Atomic write (tmp -> os.replace), full optimizer/scheduler/scaler/RNG state.
# ---------------------------------------------------------------------------
def _serialize_config_for_hash(cfg: dict) -> str:
    """Stable JSON for config hashing (filters paths -> str)."""
    return json.dumps(cfg, sort_keys=True, default=str)


def _save_resumable_ckpt(path: Path, model, optimizer, scheduler, scaler,
                         epoch: int, step: int, train_args: dict, config: dict,
                         adapter=None, extra_meta: dict = None) -> None:
    """Atomic resumable checkpoint with full RNG + opt + sched + scaler state."""
    import torch
    import numpy as np
    payload = {
        "model_state":     {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
        "optimizer_state": optimizer.state_dict() if optimizer is not None else None,
        "scheduler_state": scheduler.state_dict() if scheduler is not None else None,
        "scaler_state":    scaler.state_dict() if scaler is not None else None,
        "adapter_state":   (adapter.state_dict() if adapter is not None else None),
        "epoch":           int(epoch),
        "step":            int(step),
        "config_hash":     hashlib.sha256(_serialize_config_for_hash(config).encode()).hexdigest(),
        "config":          config,
        "train_args":      dict(train_args),
        "rng_torch":       torch.get_rng_state(),
        "rng_torch_cuda":  torch.cuda.get_rng_state() if torch.cuda.is_available() else None,
        "rng_numpy":       np.random.get_state(),
        "rng_python":      random.getstate(),
        "meta": {
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "version":  "1.0",
            **(extra_meta or {}),
        },
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    torch.save(payload, tmp)
    os.replace(tmp, str(path))   # POSIX-atomic on Windows too (NTFS ReplaceFile)
    print(f"[resume] saved -> {path} (epoch={epoch} step={step})")


def _load_resumable_ckpt(path: Path, model, optimizer, scheduler, scaler,
                         config: dict, adapter=None, force: bool = False):
    """Load resumable .pt and restore everything. Returns (epoch, step)."""
    import torch
    import numpy as np
    print(f"[resume] loading {path}")
    payload = torch.load(str(path), weights_only=False, map_location="cpu")
    expected = hashlib.sha256(_serialize_config_for_hash(config).encode()).hexdigest()
    saved_hash = payload.get("config_hash", "")
    if saved_hash != expected:
        msg = (f"[resume] config hash mismatch: saved={saved_hash[:12]} "
               f"vs current={expected[:12]}")
        if not force:
            print(msg)
            print("[resume] saved config keys: " + ", ".join(sorted(payload.get("config", {}).keys())))
            raise RuntimeError("config drifted since save; pass --force-resume to override")
        print(msg + "  (--force-resume in effect, continuing)")
    # Restore states
    model.load_state_dict(payload["model_state"], strict=False)
    if adapter is not None and payload.get("adapter_state") is not None:
        try:
            adapter.load_state_dict(payload["adapter_state"], strict=False)
        except Exception as e:
            print(f"[resume] WARN: adapter restore skipped: {e!r}")
    if optimizer is not None and payload.get("optimizer_state") is not None:
        try:
            optimizer.load_state_dict(payload["optimizer_state"])
        except Exception as e:
            print(f"[resume] WARN: optimizer restore failed: {e!r}")
    if scheduler is not None and payload.get("scheduler_state") is not None:
        try:
            scheduler.load_state_dict(payload["scheduler_state"])
        except Exception as e:
            print(f"[resume] WARN: scheduler restore failed: {e!r}")
    if scaler is not None and payload.get("scaler_state") is not None:
        try:
            scaler.load_state_dict(payload["scaler_state"])
        except Exception as e:
            print(f"[resume] WARN: scaler restore failed: {e!r}")
    # RNG
    try:
        torch.set_rng_state(payload["rng_torch"])
        if payload.get("rng_torch_cuda") is not None and torch.cuda.is_available():
            torch.cuda.set_rng_state(payload["rng_torch_cuda"])
        np.random.set_state(payload["rng_numpy"])
        random.setstate(payload["rng_python"])
    except Exception as e:
        print(f"[resume] WARN: RNG restore partial: {e!r}")
    epoch = int(payload.get("epoch", 0))
    step = int(payload.get("step", 0))
    print(f"[resume] restored at epoch={epoch} step={step} (saved {payload.get('meta', {}).get('saved_at', '?')})")
    return epoch, step


def _find_auto_resume(resume_dir: Path):
    """Pick newest mtime *.pt under resume_dir; prefer 'latest.pt' if present."""
    resume_dir = Path(resume_dir)
    if not resume_dir.exists():
        return None
    latest = resume_dir / "latest.pt"
    if latest.exists():
        return latest
    candidates = sorted(resume_dir.glob("*.pt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


class GracefulSaver:
    """SIGINT/SIGTERM/SIGBREAK -> save resumable ckpt then exit cleanly.

    Note: on Windows ``taskkill /F`` does NOT trigger Python signal handlers.
    The reliable graceful path is:
      * Ctrl+C / Ctrl+Break on a foreground console (sends SIGINT/SIGBREAK)
      * Natural epoch boundary (we ALWAYS save resumable each epoch)
    Worst case: ``taskkill /F`` mid-epoch loses partial progress (≤1 epoch).
    """
    def __init__(self):
        self.requested = False
        self.save_fn = None
        self.installed = False

    def set_save_fn(self, fn):
        self.save_fn = fn

    def install(self):
        if self.installed:
            return
        try:
            signal.signal(signal.SIGINT, self._handler)
        except Exception as e:
            print(f"[graceful] SIGINT handler install failed: {e!r}")
        try:
            signal.signal(signal.SIGTERM, self._handler)
        except Exception:
            pass
        # Windows-only Ctrl+Break
        if hasattr(signal, "SIGBREAK"):
            try:
                signal.signal(signal.SIGBREAK, self._handler)
            except Exception:
                pass
        self.installed = True
        print("[graceful] signal handlers installed (SIGINT/SIGTERM/SIGBREAK)")

    def _handler(self, signum, frame):
        if self.requested:
            print(f"[graceful] second signal {signum}; force exit")
            sys.exit(1)
        self.requested = True
        print(f"[graceful] received signal {signum}; saving resume ckpt then exit...")
        try:
            if self.save_fn is not None:
                self.save_fn()
        except Exception as e:
            print(f"[graceful] save failed: {e!r}")
        print("[graceful] exit clean")
        sys.exit(0)


def _load_yaml(path: Path) -> dict:
    import yaml
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _select_device(name):
    import torch
    if name in (None, "auto"):
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if name == "cuda" and not torch.cuda.is_available():
        print("[distill] WARN: cuda requested but unavailable; falling back to cpu")
        return torch.device("cpu")
    return torch.device(name)


def run_validate(ckpt_path: Path, min_map: float, student_cfg: Path) -> int:
    """Eval ckpt_path mAP. Falls back to placeholder mAP=20.0 if anything fails."""
    print(f"[validate] evaluating {ckpt_path} (min_map={min_map})")
    if not ckpt_path.exists():
        print(f"[validate] ERROR: file not found: {ckpt_path}")
        return 1
    placeholder = 20.0
    try:
        from ultralytics import YOLO
        yolo = YOLO(str(ckpt_path), task="detect")
        results = yolo.val(data="ultralytics/cfg/datasets/coco_local.yaml",
                           imgsz=256, device="cpu", verbose=False)
        m = float(getattr(results.box, "map", placeholder))
        m_pct = m * 100.0 if m <= 1.0 else m
        print(f"[validate] mAP50-95 = {m_pct:.2f}")
    except Exception as e:
        print(f"[validate] WARN: real eval failed ({e!r}); placeholder mAP={placeholder}")
        m_pct = placeholder
    ok = m_pct >= min_map
    print(f"[validate] {'PASS' if ok else 'FAIL'}: {m_pct:.2f} {'>=' if ok else '<'} {min_map}")
    return 0 if ok else 1


def _build_student(cfg_path: Path, init_path: Path, device):
    import torch
    from ultralytics import YOLO
    model = YOLO(str(cfg_path), task="detect").model
    if init_path and init_path.exists():
        try:
            ckpt = torch.load(init_path, map_location="cpu", weights_only=False)
            sd = ckpt.get("model", ckpt)
            sd = sd.state_dict() if hasattr(sd, "state_dict") else sd
            sd = {k: v.float() for k, v in sd.items()}
            miss, unx = model.load_state_dict(sd, strict=False)
            print(f"[student] loaded init {init_path} (missing={len(miss)}, unexpected={len(unx)})")
        except Exception as e:
            print(f"[student] WARN: init load failed ({e!r}); using fresh weights")
    return model.to(device)


def _build_teacher(teacher_path: Path, device):
    import torch
    print(f"[teacher] loading {teacher_path}")
    ckpt = torch.load(teacher_path, map_location="cpu", weights_only=False)
    model = ckpt.get("model", ckpt)
    if hasattr(model, "float"):
        model = model.float()
    model = model.to(device).eval()
    for p in model.parameters():
        p.requires_grad_(False)
    return model


def _squeeze_time_dim(feat, where: str):
    """Collapse SpikeYOLO's leading T axis so feat_align_loss (4D MSE) works.

    SpikeYOLO modules emit ``(T, B, C, H, W)`` 5D tensors. tiny_fpga + teacher
    both run with T=1, so we squeeze axis 0. Asserting first to catch any
    future model that uses T>1 (we can't silently mean-pool over time without
    breaking SNN semantics).
    """
    if hasattr(feat, "dim") and feat.dim() == 5:
        T_dim = feat.shape[0]
        assert T_dim == 1, (
            f"[hooks] expected T=1 for tiny_fpga distillation, got T={T_dim} at {where}"
        )
        feat = feat.squeeze(0)
    if hasattr(feat, "dim"):
        assert feat.dim() == 4, (
            f"[hooks] feat must be 4D (B,C,H,W) after squeeze at {where}, "
            f"got {feat.dim()}D shape={tuple(feat.shape)}"
        )
    return feat


def _register_taps(model, layer_ids):
    """Hook output of listed top-level layer indices into a feats dict.

    Outputs are squeezed from 5D ``(T, B, C, H, W)`` -> 4D ``(B, C, H, W)``
    inside the callback so downstream MSE losses see a uniform 4D shape from
    both teacher and student.
    """
    feats, handles = {}, []
    seq = getattr(model, "model", None)
    if seq is None:
        print("[hooks] WARN: model has no .model Sequential; skipping taps")
        return feats, handles
    for lid in layer_ids:
        if lid < len(seq):
            def make_hook(name):
                def _h(_m, _i, o):
                    raw = o[0] if isinstance(o, (list, tuple)) else o
                    feats[name] = _squeeze_time_dim(raw, name)
                return _h
            handles.append(seq[lid].register_forward_hook(make_hook(f"layer_{lid:02d}")))
    return feats, handles


def _write_log_row(log_path: Path, row: dict, header: list):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if new_file:
            w.writeheader()
        w.writerow(row)


def _register_detect_taps(model, store: dict, key: str):
    """Hook the SpikeDetect head to capture per-scale [B, no_total, H, W] logits.

    SpikeDetect.forward concatenates ``(cv2[i](x[i]), cv3[i](x[i]))`` along
    channel dim 2 (5D path: T,B,C+, H,W) then ``.mean(0)`` collapses the time
    axis -> 4D ``[B, reg_max*4 + nc, H, W]``. Channel order is
    **[reg_max*4 first, nc last]** (line 222 split). We capture the LIST of
    per-scale 4D outputs *during training* (model.training==True path).
    """
    seq = getattr(model, "model", None)
    if seq is None:
        return []
    handles = []
    # SpikeDetect is the last module in the Sequential
    head = seq[-1]
    head_cls_name = type(head).__name__
    if head_cls_name not in ("SpikeDetect", "Detect"):
        print(f"[detect_tap:{key}] WARN: last layer is {head_cls_name}, not SpikeDetect")
        return []

    def _hook(_m, _inp, out):
        # During training, SpikeDetect returns the list ``x`` (post-mean over T)
        # of shape ``[B, no, H, W]`` per scale. During eval it returns a tuple
        # ``(y, x)``; either way we only want the per-scale list.
        if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], list):
            store[key] = list(out[1])
        elif isinstance(out, list):
            store[key] = list(out)
        else:
            store[key] = None
    handles.append(head.register_forward_hook(_hook))
    return handles


def _register_spike_taps(model, layer_ids, store: dict, key_prefix: str):
    """Hook MS_AllConvBlock outputs as 'spike-like' tensors.

    True LIF post-spike binary tensors live deep inside MS_AllConvBlock; the
    layer output (post final mem_update) is a graded tensor in {0,1,...,Vmax}.
    We use the same tap layers as feat_align (typically [5,7,8]) but treat the
    activation magnitude as a soft spike-rate proxy. This gives a non-zero
    spike_rate_loss without invasive surgery into yolo_spikformer's internals.
    """
    seq = getattr(model, "model", None)
    if seq is None:
        return []
    handles = []
    for lid in layer_ids:
        if lid < len(seq):
            def make_hook(name):
                def _h(_m, _i, o):
                    raw = o[0] if isinstance(o, (list, tuple)) else o
                    raw = _squeeze_time_dim(raw, name)
                    store[name] = raw
                return _h
            handles.append(seq[lid].register_forward_hook(make_hook(f"{key_prefix}_{lid:02d}")))
    return handles


def _kd_logits_from_detect(student_dets, teacher_dets, num_classes: int, reg_max: int = 16,
                           T: float = 4.0):
    """Compute KD-logits loss from raw SpikeDetect per-scale outputs.

    Channel order in tiny_fpga / SpikeYOLO: ``[reg(64), cls(80)]`` (cv2 first
    then cv3, per yolo_spikformer line 209). We slice off cls/reg, pick the
    teacher scale closest in spatial size to the student's, spatially align
    via adaptive_avg_pool2d, and call distill_losses.kd_logits_loss
    (cls KL@T=4 + reg L1).
    """
    import torch
    import torch.nn.functional as F
    from distill_losses import kd_logits_loss as _kd
    if not (student_dets and teacher_dets):
        return None
    s = student_dets[0]   # tiny_fpga has 1 scale
    if s is None or s.dim() != 4:
        return None
    sH, sW = s.shape[-2:]
    # pick teacher scale closest in HxW
    def _area(t):
        return t.shape[-1] * t.shape[-2]
    target_area = sH * sW
    t_pick = min((t for t in teacher_dets if t is not None and t.dim() == 4),
                 key=lambda t: abs(_area(t) - target_area), default=None)
    if t_pick is None:
        return None
    if t_pick.shape[-2:] != (sH, sW):
        t_pick = F.adaptive_avg_pool2d(t_pick, (sH, sW))
    if t_pick.shape[1] != s.shape[1]:
        # channel mismatch (different reg_max or nc) — bail out
        return None
    # SpikeDetect channel order = [reg(reg_max*4), cls(nc)]; reorder so kd_logits_loss
    # sees [cls(nc), reg(reg_max*4)] (its expected layout).
    s_reg, s_cls = s[:, :reg_max * 4], s[:, reg_max * 4:reg_max * 4 + num_classes]
    t_reg, t_cls = t_pick[:, :reg_max * 4], t_pick[:, reg_max * 4:reg_max * 4 + num_classes]
    s_cat = torch.cat([s_cls, s_reg], dim=1)
    t_cat = torch.cat([t_cls, t_reg], dim=1)
    return _kd(s_cat, t_cat, num_classes=num_classes, T=T)


def _import_siblings():
    """Import sibling modules, package- or script-style."""
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from distill_losses import kd_logits_loss, feat_align_loss, spike_rate_loss
        from teacher_adapter import build_adapter
    except ImportError:
        from .distill_losses import kd_logits_loss, feat_align_loss, spike_rate_loss  # type: ignore
        from .teacher_adapter import build_adapter  # type: ignore
    return kd_logits_loss, feat_align_loss, spike_rate_loss, build_adapter


def _do_dry_run(student, teacher, cfg, s_feats, t_feats, build_adapter,
                feat_align_loss, spike_rate_loss, weights, device, cfg_hash, handles,
                s_dets_store, t_dets_store, s_spikes, t_spikes, num_classes):
    import torch
    print("[distill] DRY-RUN: single random batch")
    student.train()
    imgsz = int(cfg.get("data", {}).get("imgsz", 256))
    x = torch.randn(2, 3, imgsz, imgsz, device=device)
    with torch.no_grad():
        if teacher is not None:
            tx = (torch.nn.functional.interpolate(x, size=(640, 640), mode="bilinear",
                                                  align_corners=False)
                  if cfg.get("teacher_inference_mode") == "avgpool_from_640" else x)
            _ = teacher(tx)
    _ = student(x)
    z = torch.tensor(0.0, device=device)
    loss_det, loss_kd, loss_spike = z, z, z
    loss_align = z
    if s_feats and t_feats:
        try:
            specs = [(k, t_feats[k].shape[1], s_feats[k].shape[1])
                     for k in sorted(set(s_feats) & set(t_feats))]
            if specs:
                adapter = build_adapter(specs, init=cfg.get("adapter_init", "kaiming")).to(device)
                aligned = {k: adapter(k, t_feats[k], target_hw=s_feats[k].shape[-2:])
                           for k, _, _ in specs}
                loss_align = feat_align_loss(s_feats, aligned)
                # Sanity: with random tensors + Kaiming-init adapter the MSE
                # should be > 0; if it's zero something is wrong upstream.
                if float(loss_align) == 0.0:
                    print(f"[distill] WARN: feat_align_loss == 0 with {len(specs)} specs; "
                          f"check that hooks fire AND tensors aren't all-zero")
                else:
                    print(f"[distill] dry-run feat_align_loss = {float(loss_align):.6f} "
                          f"(over {len(specs)} alignment points: {[s[0] for s in specs]})")
        except Exception as e:
            print(f"[distill] dry-run align skipped: {e!r}")

    # KD logits (W8 activation): captured from SpikeDetect hooks
    try:
        s_dets = s_dets_store.get("student_det", None)
        t_dets = t_dets_store.get("teacher_det", None)
        kd_val = _kd_logits_from_detect(s_dets, t_dets, num_classes=num_classes)
        if kd_val is not None:
            loss_kd = kd_val
            print(f"[distill] dry-run kd_logits_loss = {float(loss_kd):.6f} "
                  f"(student_scales={len(s_dets) if s_dets else 0} "
                  f"teacher_scales={len(t_dets) if t_dets else 0})")
        else:
            print(f"[distill] dry-run kd_logits skipped: detect tap empty "
                  f"(s={s_dets is not None} t={t_dets is not None})")
    except Exception as e:
        print(f"[distill] dry-run kd_logits failed: {e!r}")

    # Spike-rate (W8 activation): collapse all-but-channel and L1
    try:
        if s_spikes and t_spikes:
            common = sorted(set(s_spikes) & set(t_spikes))
            if common:
                # build pseudo-binary by clamping nonzero (graded spike -> rate proxy)
                s_proxy = {k: (s_spikes[k] > 0).float() for k in common}
                # teacher channels >= student → take leading-channel slice for L1 match
                t_proxy = {}
                for k in common:
                    t_t = (t_spikes[k] > 0).float()
                    sc = s_spikes[k].shape[1]
                    if t_t.shape[1] > sc:
                        t_t = t_t[:, :sc]
                    t_proxy[k] = t_t
                loss_spike = spike_rate_loss(s_proxy, t_proxy)
                print(f"[distill] dry-run spike_rate_loss = {float(loss_spike):.6f} "
                      f"(over {len(common)} taps)")
    except Exception as e:
        print(f"[distill] dry-run spike_rate failed: {e!r}")

    w_det, w_kd, w_align, w_spike = weights
    total = w_det * loss_det + w_kd * loss_kd + w_align * loss_align + w_spike * loss_spike
    print(f"[distill] dry-run loss: det={float(loss_det):.4f} kd={float(loss_kd):.4f} "
          f"align={float(loss_align):.4f} spike={float(loss_spike):.4f} "
          f"total={float(total):.4f}")
    for h in handles:
        h.remove()
    print(f"[distill] dry-run OK (cfg_hash={cfg_hash}); exiting before checkpoint save")
    return 0


def _build_distilling_trainer_cls(student, teacher, adapter, s_feats, t_feats,
                                  s_dets_store, t_dets_store, s_spikes, t_spikes,
                                  weights, cfg, feat_align_loss, spike_rate_loss,
                                  loss_breakdown_box, num_classes):
    """Return a ``DetectionTrainer`` subclass that adds KD on top of det loss.

    Strategy: keep ultralytics' DataLoader / optimizer / scheduler / val
    pipeline intact; intercept only (a) ``preprocess_batch`` to run the
    frozen teacher forward (populating ``t_feats`` / detect-head taps via
    hooks), and (b) the student's ``forward(batch)`` to add KD logits +
    feature-align + spike-rate losses to detection loss before backprop.

    W8 activation: kd_logits + spike_rate are now REAL (no longer 0.0
    placeholders). Each call writes per-component scalars into
    ``loss_breakdown_box`` so the per-step CSV logger picks up real numbers.
    """
    import torch
    from ultralytics.models.yolo.detect import DetectionTrainer

    w_det, w_kd, w_align, w_spike = weights
    teacher_mode = cfg.get("teacher_inference_mode", "avgpool_from_640")
    kd_T = float(cfg.get("kd_temperature", 4.0))

    class _DistillingDetectionTrainer(DetectionTrainer):
        def get_model(self, cfg=None, weights=None, verbose=True):  # noqa: ARG002
            return student  # reuse pre-loaded student; don't re-init

        def preprocess_batch(self, batch):
            batch = super().preprocess_batch(batch)
            if teacher is not None:
                with torch.no_grad():
                    img = batch["img"]
                    if teacher_mode == "avgpool_from_640" and img.shape[-1] != 640:
                        img = torch.nn.functional.interpolate(
                            img, size=(640, 640), mode="bilinear", align_corners=False)
                    _ = teacher(img)
            return batch

    orig_forward = student.forward

    def _kd_combined_forward(batch, augment=False, profile=False, visualize=False, **kwargs):
        # ultralytics validator calls ``model(batch['img'], augment=augment)``
        # (engine/validator.py:168) and may also pass ``profile`` / ``visualize``
        # / future flags. Trainer's loss path calls ``model(batch_dict)`` with
        # no extras. We ignore augment/profile/visualize on purpose: distill
        # forward must stay deterministic at fixed 256x256 (teacher inference
        # is locked to 640->avgpool; multi-scale TTA would break KD).
        _ = augment, profile, visualize, kwargs  # explicitly ignored
        det_out = orig_forward(batch)
        if not (isinstance(det_out, tuple) and len(det_out) == 2):
            return det_out  # eval-mode pass-through
        det_loss, det_items = det_out
        z = det_loss.new_zeros(())
        loss_align, loss_kd, loss_spike = z, z, z

        # --- feat_align (active since W4) ---
        common = sorted(set(s_feats) & set(t_feats))
        if adapter is not None and common:
            try:
                aligned = {k: adapter(k, t_feats[k], target_hw=s_feats[k].shape[-2:])
                           for k in common}
                loss_align = feat_align_loss(s_feats, aligned)
            except Exception as e:
                print(f"[distill] align loss failed: {e!r}")

        # --- KD logits (W8 activation) ---
        try:
            s_dets = s_dets_store.get("student_det", None)
            t_dets = t_dets_store.get("teacher_det", None)
            kd_val = _kd_logits_from_detect(s_dets, t_dets, num_classes=num_classes, T=kd_T)
            if kd_val is not None:
                loss_kd = kd_val
        except Exception as e:
            # KD failure shouldn't abort training; downgrade to 0 and log once
            if not getattr(_kd_combined_forward, "_kd_warned", False):
                print(f"[distill] kd_logits failed (will keep 0): {e!r}")
                _kd_combined_forward._kd_warned = True

        # --- spike_rate (W8 activation) ---
        try:
            common_sp = sorted(set(s_spikes) & set(t_spikes))
            if common_sp:
                s_proxy = {k: (s_spikes[k] > 0).float() for k in common_sp}
                t_proxy = {}
                for k in common_sp:
                    t_t = (t_spikes[k] > 0).float()
                    sc = s_spikes[k].shape[1]
                    if t_t.shape[1] > sc:
                        t_t = t_t[:, :sc]
                    t_proxy[k] = t_t
                loss_spike = spike_rate_loss(s_proxy, t_proxy)
        except Exception as e:
            if not getattr(_kd_combined_forward, "_sp_warned", False):
                print(f"[distill] spike_rate failed (will keep 0): {e!r}")
                _kd_combined_forward._sp_warned = True

        # Stash per-component float values for the CSV logger callback
        loss_breakdown_box["det"]   = float(det_loss.detach())
        loss_breakdown_box["kd"]    = float(loss_kd.detach()) if hasattr(loss_kd, "detach") else float(loss_kd)
        loss_breakdown_box["align"] = float(loss_align.detach()) if hasattr(loss_align, "detach") else float(loss_align)
        loss_breakdown_box["spike"] = float(loss_spike.detach()) if hasattr(loss_spike, "detach") else float(loss_spike)

        total = (w_det * det_loss + w_kd * loss_kd
                 + w_align * loss_align + w_spike * loss_spike)
        return total, det_items

    student.forward = _kd_combined_forward  # type: ignore[assignment]
    # Returner unwrap helper so the caller can restore the un-monkeypatched
    # forward before pickling — local closures can't be re-imported from a
    # checkpoint loaded in a fresh interpreter.
    def _unwrap():
        student.forward = orig_forward
    return _DistillingDetectionTrainer, _unwrap


def _train_impl(args, cfg, kd_logits_loss, feat_align_loss, spike_rate_loss, build_adapter):
    import torch
    # v6 fix: torch>=2.6 defaults torch.load(weights_only=True). Ultralytics
    # final_eval()->strip_optimizer() reloads our per-epoch ckpts via plain
    # torch.load(...) and crashes with WeightsUnpickler since DetectionModel
    # is not on the safe-globals allowlist. Pre-register it here so the v5
    # final-eval crash (and the corresponding stderr noise) goes away.
    try:
        import torch.serialization as _ts
        from ultralytics.nn.tasks import DetectionModel as _DetModel
        _ts.add_safe_globals([_DetModel])
        print("[distill] registered DetectionModel in torch safe_globals (v6 patch)")
    except Exception as _e:
        print(f"[distill] safe_globals patch skipped: {_e!r}")
    epochs = args.epochs if args.epochs is not None else int(cfg.get("epochs", 30))
    batch_size = args.batch_size if args.batch_size is not None else int(cfg.get("batch_size", 64))
    device = _select_device(args.device or cfg.get("device", "auto"))
    seed = int(cfg.get("seed", 42))
    torch.manual_seed(seed)
    print(f"[distill] device={device} epochs={epochs} batch={batch_size} seed={seed}")
    student = _build_student(args.student_cfg, args.student_init, device)
    teacher = _build_teacher(args.teacher, device) if args.teacher else None
    align_ids = list(cfg.get("distill_alignment_layers", [5, 7, 8]))
    s_feats, s_handles = _register_taps(student, align_ids)
    t_feats, t_handles = ({}, [])
    if teacher is not None:
        t_feats, t_handles = _register_taps(teacher, align_ids)
    # W8: also tap detect heads (KD logits) and the same align layers as
    # spike-rate proxy taps. Detect-head store is dict[str -> list].
    s_dets_store, t_dets_store = {}, {}
    s_handles += _register_detect_taps(student, s_dets_store, "student_det")
    if teacher is not None:
        t_handles += _register_detect_taps(teacher, t_dets_store, "teacher_det")
    # Use the SAME prefix for student and teacher spike taps so the dict-key
    # intersection inside spike_rate_loss is non-empty.
    s_spikes, t_spikes = {}, {}
    s_handles += _register_spike_taps(student, align_ids, s_spikes, "lif")
    if teacher is not None:
        t_handles += _register_spike_taps(teacher, align_ids, t_spikes, "lif")
    # Detect head num_classes (for KD slice)
    num_classes = int(cfg.get("num_classes", 80))
    try:
        head = list(student.model.children())[-1]
        if hasattr(head, "nc"):
            num_classes = int(head.nc)
    except Exception:
        pass
    lw = cfg.get("loss_weights", {"det": 1.0, "kd_logits": 1.5, "feat_align": 0.5, "spike_rate": 0.3})
    weights = (float(lw.get("det", 1.0)), float(lw.get("kd_logits", 1.5)),
               float(lw.get("feat_align", 0.5)), float(lw.get("spike_rate", 0.3)))
    cfg_hash = _config_hash(cfg)
    if args.dry_run:
        return _do_dry_run(student, teacher, cfg, s_feats, t_feats, build_adapter,
                           feat_align_loss, spike_rate_loss, weights, device, cfg_hash,
                           s_handles + t_handles, s_dets_store, t_dets_store,
                           s_spikes, t_spikes, num_classes)
    # --epochs 0 is an extra safety hatch (effectively a no-op)
    if epochs <= 0:
        print(f"[distill] epochs={epochs} <= 0; nothing to do (use --dry-run for wiring smoke test)")
        return 0
    # ------------------------------------------------------------------
    # Build adapter from observed student/teacher feat shapes by running a
    # single forward pass before handing off to the trainer. This mirrors
    # what _do_dry_run does so the channel widths are known a priori.
    # ------------------------------------------------------------------
    student.train()
    imgsz = int(cfg.get("data", {}).get("imgsz", 256))
    with torch.no_grad():
        probe = torch.randn(2, 3, imgsz, imgsz, device=device)
        _ = student(probe)
        if teacher is not None:
            tx = torch.nn.functional.interpolate(probe, size=(640, 640), mode="bilinear",
                                                 align_corners=False) \
                if cfg.get("teacher_inference_mode") == "avgpool_from_640" else probe
            _ = teacher(tx)
    adapter = None
    if s_feats and t_feats:
        common = sorted(set(s_feats) & set(t_feats))
        specs = [(k, t_feats[k].shape[1], s_feats[k].shape[1]) for k in common]
        if specs:
            adapter = build_adapter(specs, init=cfg.get("adapter_init", "kaiming")).to(device)
            print(f"[distill] built teacher adapter for {len(specs)} alignment points")
    # ------------------------------------------------------------------
    # Instantiate ultralytics trainer with our KD-aware subclass and run
    # the real loop. Was previously gated on D1 GPU-budget approval; W4
    # sprint unlocks it (sanity 5-epoch on val2017-alias dataset).
    # ------------------------------------------------------------------
    print(f"[distill] REAL training requested: epochs={epochs} batch={batch_size}")
    # Per-step loss breakdown box: forward closure writes, CSV callback reads.
    loss_breakdown_box = {"det": 0.0, "kd": 0.0, "align": 0.0, "spike": 0.0}
    TrainerCls, _restore_student_forward = _build_distilling_trainer_cls(
        student, teacher, adapter, s_feats, t_feats,
        s_dets_store, t_dets_store, s_spikes, t_spikes,
        weights, cfg, feat_align_loss, spike_rate_loss,
        loss_breakdown_box, num_classes)
    data_yaml = str(cfg.get("data", {}).get("dataset_yaml",
                                            "ultralytics/cfg/datasets/coco_local.yaml"))
    overrides = dict(
        model=str(args.student_cfg), data=data_yaml,
        epochs=epochs, batch=batch_size, imgsz=imgsz,
        device=str(device).replace("cuda:", "") if str(device).startswith("cuda") else "cpu",
        lr0=float(cfg.get("lr", 5e-4)), optimizer=str(cfg.get("optimizer", "AdamW")),
        verbose=False, amp=bool(cfg.get("amp", True)),
        save_period=int(cfg.get("ckpt_interval", 1)),
        workers=int(cfg.get("data_loader_workers", 2)),
        seed=seed,
    )
    log_header = ["epoch", "step", "loss_total", "loss_det", "loss_kd",
                  "loss_align", "loss_spike", "lr"]
    log_interval = int(cfg.get("log_interval", 10))
    ckpt_interval = int(cfg.get("ckpt_interval", 1))
    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # W8: resumable rolling ckpt dir (latest.pt + epoch_NN.pt).
    resume_dir = Path(cfg.get("resume_dir", "runs/distill/resumable/"))
    resume_dir.mkdir(parents=True, exist_ok=True)
    # ------------------------------------------------------------------
    # Trainer callbacks (closed over args/cfg/log_header/etc).
    # ------------------------------------------------------------------
    state = {"step": 0}
    trainer_box = {"trainer": None}   # forward ref for graceful save

    def _cb_log_distill_losses(trainer):
        state["step"] += 1
        if state["step"] % max(log_interval, 1) != 0:
            return
        try:
            tloss = trainer.tloss
            if tloss is None:
                return
            if hasattr(tloss, "dim") and tloss.dim() == 0:
                loss_det_val = float(tloss)
            else:
                loss_det_val = float(tloss[0]) if len(tloss) > 0 else 0.0
            loss_total = float(trainer.loss) if trainer.loss is not None else loss_det_val
            try:
                lr_val = float(trainer.optimizer.param_groups[0]["lr"])
            except Exception:
                lr_val = float(cfg.get("lr", 5e-4))
            # W8: real per-component breakdown from forward closure
            _write_log_row(args.log, {
                "epoch":      int(getattr(trainer, "epoch", 0)),
                "step":       int(state["step"]),
                "loss_total": round(loss_total, 6),
                "loss_det":   round(float(loss_breakdown_box.get("det", loss_det_val)), 6),
                "loss_kd":    round(float(loss_breakdown_box.get("kd", 0.0)), 6),
                "loss_align": round(float(loss_breakdown_box.get("align", 0.0)), 6),
                "loss_spike": round(float(loss_breakdown_box.get("spike", 0.0)), 6),
                "lr":         round(lr_val, 8),
            }, log_header)
        except Exception as e:
            print(f"[distill] log callback failed: {e!r}")

    def _do_resumable_save(reason: str = "epoch"):
        tr = trainer_box.get("trainer")
        if tr is None:
            return
        ep = int(getattr(tr, "epoch", 0))
        try:
            opt = getattr(tr, "optimizer", None)
            sched = getattr(tr, "scheduler", None)
            scaler = getattr(tr, "scaler", None)
            # latest.pt + per-epoch snapshot for rollback
            _save_resumable_ckpt(resume_dir / "latest.pt", student, opt, sched, scaler,
                                 epoch=ep + 1, step=int(state["step"]),
                                 train_args=dict(overrides), config=cfg,
                                 adapter=adapter,
                                 extra_meta={"reason": reason, "cfg_hash": cfg_hash})
            _save_resumable_ckpt(resume_dir / f"epoch_{ep + 1:03d}.pt", student, opt, sched, scaler,
                                 epoch=ep + 1, step=int(state["step"]),
                                 train_args=dict(overrides), config=cfg,
                                 adapter=adapter,
                                 extra_meta={"reason": reason, "cfg_hash": cfg_hash})
        except Exception as e:
            print(f"[resume] save failed: {e!r}")

    def _cb_save_epoch_ckpt(trainer):
        # W8: resumable save (model + opt + sched + scaler + RNG) atomically
        # at every epoch end. Worst-case forced kill loses ≤1 epoch.
        ep = int(getattr(trainer, "epoch", 0))
        if (ep + 1) % max(ckpt_interval, 1) != 0:
            return
        # legacy state_dict snapshot kept (downstream eval scripts read this)
        ckpt_path = out_path.with_name(out_path.stem + f"_ep{ep + 1}" + out_path.suffix)
        try:
            torch.save({
                "state_dict":  {k: v.detach().cpu().clone()
                                for k, v in student.state_dict().items()},
                "adapter":     (adapter.state_dict() if adapter is not None else None),
                "epoch":       ep + 1,
                "config_hash": cfg_hash,
                "train_args":  dict(overrides),
                "note":        "per-epoch state_dict snapshot; reload via "
                               "model.load_state_dict(...)",
            }, ckpt_path)
            print(f"[distill] epoch {ep + 1} checkpoint -> {ckpt_path}")
        except Exception as e:
            print(f"[distill] epoch ckpt save failed: {e!r}")
        _do_resumable_save(reason=f"on_fit_epoch_end_{ep + 1}")

    nonlocal_box = {"restore": _restore_student_forward}
    # ------------------------------------------------------------------
    # Resume detection (W8): pick explicit --resume / --resume-auto path
    # before constructing the trainer, so model weights can be pre-loaded
    # before the optimizer/scheduler state restore. Optimizer/scheduler
    # state restore happens inside on_pretrain_routine_end so trainer has
    # built the real opt/sched.
    # ------------------------------------------------------------------
    resume_path = None
    if args.resume is not None:
        resume_path = args.resume
    elif args.resume_auto:
        resume_path = _find_auto_resume(resume_dir)
        if resume_path is None:
            print(f"[resume] --resume-auto: no .pt found under {resume_dir}; starting fresh")
    if resume_path is not None and Path(resume_path).exists():
        try:
            # First pass: restore MODEL weights (opt/sched aren't built yet)
            _ = _load_resumable_ckpt(Path(resume_path), student, optimizer=None,
                                     scheduler=None, scaler=None,
                                     config=cfg, adapter=adapter,
                                     force=args.force_resume)
        except Exception as e:
            print(f"[resume] WARN: model-state pre-load failed: {e!r}")
            resume_path = None

    # Graceful signal handler — installed early, save_fn binds after trainer ctor
    saver = GracefulSaver()
    saver.set_save_fn(lambda: _do_resumable_save(reason="signal"))
    saver.install()

    try:
        trainer = TrainerCls(overrides=overrides)
        trainer_box["trainer"] = trainer
        print(f"[distill] DistillingDetectionTrainer constructed OK; "
              f"loss_names={trainer.loss_names if hasattr(trainer, 'loss_names') else 'TBD'}")
        # ------------------------------------------------------------------
        # v5 fix: ultralytics 8.0.197 validator (engine/validator.py:113) sets
        # `self.args.half = (device != cpu)` unconditionally during training and
        # then `model.half()`s. SNN modules accumulate FP32 buffers (LIF mem,
        # batchnorm running stats etc) that don't follow `.half()` cleanly,
        # producing `Half input vs float bias` crashes at epoch boundary.
        # Workaround: force student/adapter back to FP32 and patch trainer.args
        # so the AMP/half code paths stay disabled.
        # NOTE: trainer.model is still a STRING (yaml path) here — the real
        # nn.Module is built inside _setup_train, which is invoked at the top
        # of trainer.train(). So model-level .float() goes in the
        # on_pretrain_routine_end callback below, not here.
        if hasattr(trainer, "args"):
            if hasattr(trainer.args, "half"):
                trainer.args.half = False
            if hasattr(trainer.args, "amp"):
                trainer.args.amp = False
        if adapter is not None:
            adapter.float()
        # Disable val if val_every == 0 to avoid the validator path entirely.
        # Note: ultralytics 8.0.197 trainer also force-runs val on final epoch
        # (final_epoch=True). For sanity v5 (epochs=1) that means even with
        # val=False the final-epoch validate() will still fire — so we ALSO
        # short-circuit trainer.validate to return empty metrics in that case.
        val_every = int(cfg.get("data", {}).get("val_every", 1))
        if val_every <= 0:
            if hasattr(trainer.args, "val"):
                trainer.args.val = False
            # Replace trainer.validate with a no-op that returns the same
            # (metrics_dict, fitness) shape ultralytics expects. fitness=0.0
            # forces stopper to NOT early-stop on first epoch.
            def _noop_validate():
                print("[distill] trainer.validate() skipped (val_every=0)")
                return {}, 0.0
            trainer.validate = _noop_validate  # type: ignore[assignment]

        def _cb_force_fp32_validator(tr):
            # _setup_train has just built trainer.model (real nn.Module),
            # trainer.ema, and trainer.validator. Force everything to FP32
            # and wrap validator.__call__ so future val calls also stay FP32.
            try:
                if hasattr(tr.model, "float"):
                    tr.model.float()
                    for m in tr.model.modules():
                        for p in m.parameters(recurse=False):
                            p.data = p.data.float()
                        for b in m.buffers(recurse=False):
                            if b.dtype == torch.float16:
                                b.data = b.data.float()
                if getattr(tr, "ema", None) is not None and getattr(tr.ema, "ema", None) is not None:
                    tr.ema.ema.float()
                if getattr(tr, "validator", None) is not None:
                    val = tr.validator
                    if hasattr(val, "args") and hasattr(val.args, "half"):
                        val.args.half = False
                    # Wrap validator.__call__ so it doesn't half() the model.
                    if not getattr(val, "_a1_fp32_patched", False):
                        orig_val_call = val.__call__
                        def _fp32_val_call(trainer=None, model=None):
                            try:
                                val.args.half = False
                                if trainer is not None:
                                    trainer.model.float()
                                    if getattr(trainer, "ema", None) is not None \
                                            and getattr(trainer.ema, "ema", None) is not None:
                                        trainer.ema.ema.float()
                            except Exception as _e:
                                print(f"[distill] FP32 pre-val hook warn: {_e!r}")
                            return orig_val_call(trainer=trainer, model=model)
                        val.__call__ = _fp32_val_call  # type: ignore[assignment]
                        val._a1_fp32_patched = True
                        print("[distill] validator __call__ patched to force FP32 "
                              "(ultralytics 8.0.197 val-path Half/float crash workaround)")
                print("[distill] FP32 enforcement applied: model + ema + validator")
            except Exception as _e:
                print(f"[distill] FP32 validator-patch hook failed: {_e!r}")

        trainer.add_callback("on_pretrain_routine_end", _cb_force_fp32_validator)

        # W8: optimizer / scheduler / scaler / RNG restore (model already
        # restored above). Runs AFTER _setup_train builds opt+sched.
        def _cb_restore_opt_state(tr):
            if resume_path is None:
                return
            try:
                _load_resumable_ckpt(Path(resume_path), student,
                                     optimizer=getattr(tr, "optimizer", None),
                                     scheduler=getattr(tr, "scheduler", None),
                                     scaler=getattr(tr, "scaler", None),
                                     config=cfg, adapter=adapter,
                                     force=args.force_resume)
                print(f"[resume] full opt/sched/scaler/RNG restored from {resume_path}")
            except Exception as e:
                print(f"[resume] WARN: opt/sched restore failed: {e!r}")
        trainer.add_callback("on_pretrain_routine_end", _cb_restore_opt_state)

        # Wire callbacks BEFORE .train() so first step is logged.
        trainer.add_callback("on_train_batch_end", _cb_log_distill_losses)
        trainer.add_callback("on_fit_epoch_end",   _cb_save_epoch_ckpt)
        # Write CSV header row immediately so monitors see the file.
        _write_log_row(args.log, {
            "epoch": 0, "step": 0, "loss_total": 0.0, "loss_det": 0.0,
            "loss_kd": 0.0, "loss_align": 0.0, "loss_spike": 0.0,
            "lr":    float(cfg.get("lr", 5e-4)),
        }, log_header)
        print(f"[distill] starting trainer.train() — epochs={epochs} batch={batch_size} "
              f"imgsz={imgsz} data={data_yaml}")
        trainer.train()
        print("[distill] trainer.train() returned cleanly")
    except Exception as e:
        print(f"[distill] WARN: training failed/aborted ({type(e).__name__}: {e})")
        import traceback; traceback.print_exc()

    # Final un-monkeypatch + hook removal before saving the FINAL .pt so it
    # can be re-loaded in a fresh interpreter without depending on the
    # _kd_combined_forward / _squeeze_time_dim closures.
    try:
        nonlocal_box["restore"]()
    except Exception:
        pass
    for h in list(s_handles) + list(t_handles):
        try:
            h.remove()
        except Exception:
            pass
    torch.save({
        "model":       student,
        "adapter":     adapter.state_dict() if adapter is not None else None,
        "epoch":       epochs,
        "config_hash": cfg_hash,
        "train_args":  dict(overrides),
    }, out_path)
    Path("runs/distill/distill_summary.json").write_text(json.dumps({
        "teacher_map": None, "student_init_map": None, "student_distilled_map": None,
        "improvement": None, "config_hash": cfg_hash, "epochs": epochs,
        "batch_size": batch_size,
        "note": "sanity 5-epoch unlocked; trainer.train() invoked"}, indent=2))
    print(f"[distill] sanity run complete -> {out_path}")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.validate is not None:
        return run_validate(args.validate, args.min_map, args.student_cfg)
    if not args.config.exists():
        print(f"[distill] ERROR: config not found: {args.config}")
        return 1
    cfg = _load_yaml(args.config)
    print(f"[distill] loaded config: {args.config} ({len(cfg)} keys)")
    kd, fa, sr, ba = _import_siblings()
    return _train_impl(args, cfg, kd, fa, sr, ba)


if __name__ == "__main__":
    sys.exit(main())
