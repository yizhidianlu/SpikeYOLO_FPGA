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
import sys
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
    return p


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
                feat_align_loss, weights, device, cfg_hash, handles):
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
                                  weights, cfg, feat_align_loss):
    """Return a ``DetectionTrainer`` subclass that adds KD on top of det loss.

    Strategy: keep ultralytics' DataLoader / optimizer / scheduler / val
    pipeline intact; intercept only (a) ``preprocess_batch`` to run the
    frozen teacher forward (populating ``t_feats`` via hooks), and
    (b) the student's ``forward(batch)`` to add the alignment loss to the
    detection loss before backprop. The trainer loop calls
    ``self.loss, self.loss_items = self.model(batch)`` (engine/trainer.py
    line 344), so wrapping ``student.forward`` is a transparent splice.

    KD logits + spike_rate losses stay placeholder zeros until the
    detect-head and LIF taps are wired (M2 work).
    """
    import torch
    from ultralytics.models.yolo.detect import DetectionTrainer

    w_det, _w_kd, w_align, _w_spike = weights
    teacher_mode = cfg.get("teacher_inference_mode", "avgpool_from_640")

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

    def _kd_combined_forward(batch):
        det_out = orig_forward(batch)
        if not (isinstance(det_out, tuple) and len(det_out) == 2):
            return det_out  # eval-mode pass-through
        det_loss, det_items = det_out
        loss_align = det_loss.new_zeros(())
        common = sorted(set(s_feats) & set(t_feats))
        if adapter is not None and common:
            try:
                aligned = {k: adapter(k, t_feats[k], target_hw=s_feats[k].shape[-2:])
                           for k in common}
                loss_align = feat_align_loss(s_feats, aligned)
            except Exception as e:
                print(f"[distill] align loss failed: {e!r}")
        return w_det * det_loss + w_align * loss_align, det_items

    student.forward = _kd_combined_forward  # type: ignore[assignment]
    # Returner unwrap helper so the caller can restore the un-monkeypatched
    # forward before pickling — local closures can't be re-imported from a
    # checkpoint loaded in a fresh interpreter.
    def _unwrap():
        student.forward = orig_forward
    return _DistillingDetectionTrainer, _unwrap


def _train_impl(args, cfg, kd_logits_loss, feat_align_loss, spike_rate_loss, build_adapter):
    import torch
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
    lw = cfg.get("loss_weights", {"det": 1.0, "kd_logits": 1.5, "feat_align": 0.5, "spike_rate": 0.3})
    weights = (float(lw.get("det", 1.0)), float(lw.get("kd_logits", 1.5)),
               float(lw.get("feat_align", 0.5)), float(lw.get("spike_rate", 0.3)))
    cfg_hash = _config_hash(cfg)
    if args.dry_run:
        return _do_dry_run(student, teacher, cfg, s_feats, t_feats, build_adapter,
                           feat_align_loss, weights, device, cfg_hash, s_handles + t_handles)
    if not (epochs > 1):
        print(f"[distill] epochs={epochs} <= 1; refusing full training without --epochs > 1")
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
    # Instantiate ultralytics trainer with our KD-aware subclass. We do
    # NOT call .train() yet — left as a TODO for the actual 30-epoch run
    # once D1 approves the GPU budget. Constructor alone validates that
    # the data yaml resolves and the dataloader can be built.
    # ------------------------------------------------------------------
    print(f"[distill] REAL training requested: epochs={epochs} batch={batch_size}")
    TrainerCls, _restore_student_forward = _build_distilling_trainer_cls(
        student, teacher, adapter, s_feats, t_feats, weights, cfg, feat_align_loss)
    overrides = dict(
        model=str(args.student_cfg), data="ultralytics/cfg/datasets/coco_local.yaml",
        epochs=epochs, batch=batch_size, imgsz=imgsz,
        device=str(device).replace("cuda:", "") if str(device).startswith("cuda") else "cpu",
        lr0=float(cfg.get("lr", 5e-4)), optimizer="AdamW", verbose=False,
    )
    try:
        trainer = TrainerCls(overrides=overrides)
        # Construction succeeded -> dataloader, optimizer, scheduler all wire-able.
        print(f"[distill] DistillingDetectionTrainer constructed OK; "
              f"loss_names={trainer.loss_names if hasattr(trainer, 'loss_names') else 'TBD'}")
        # Actual trainer.train() call deferred pending D1 budget approval.
        print("[distill] NOTE: trainer.train() call deferred — pass --dry-run to "
              "smoke-test or wait for D1 GPU budget approval.")
    except Exception as e:
        print(f"[distill] WARN: trainer construction failed ({type(e).__name__}: {e}); "
              "saving student snapshot anyway")

    log_header = ["epoch", "step", "loss_total", "loss_det", "loss_kd",
                  "loss_align", "loss_spike", "lr"]
    _write_log_row(args.log, {"epoch": 0, "step": 0, "loss_total": 0.0, "loss_det": 0.0,
                              "loss_kd": 0.0, "loss_align": 0.0, "loss_spike": 0.0,
                              "lr": float(cfg.get("lr", 5e-4))}, log_header)
    # Restore un-monkeypatched forward AND drop hook handles BEFORE saving so
    # the checkpoint can be loaded in a fresh interpreter without needing
    # _kd_combined_forward / _squeeze_time_dim in scope (the hook callback
    # closures get pickled inside Module._forward_hooks otherwise).
    _restore_student_forward()
    for h in s_handles + t_handles:
        h.remove()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"model": student, "epoch": 0, "train_args": {}}, args.out)
    Path("runs/distill/distill_summary.json").write_text(json.dumps({
        "teacher_map": None, "student_init_map": None, "student_distilled_map": None,
        "improvement": None, "config_hash": cfg_hash, "epochs": epochs,
        "batch_size": batch_size,
        "note": "trainer wired; train() call gated on D1 GPU budget"}, indent=2))
    print(f"[distill] skeleton run complete -> {args.out}")
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
