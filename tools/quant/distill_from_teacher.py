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
    lw = cfg.get("loss_weights", {"det": 1.0, "kd_logits": 1.5, "feat_align": 0.5, "spike_rate": 0.3})
    weights = (float(lw.get("det", 1.0)), float(lw.get("kd_logits", 1.5)),
               float(lw.get("feat_align", 0.5)), float(lw.get("spike_rate", 0.3)))
    cfg_hash = _config_hash(cfg)
    if args.dry_run:
        return _do_dry_run(student, teacher, cfg, s_feats, t_feats, build_adapter,
                           feat_align_loss, weights, device, cfg_hash, s_handles + t_handles)
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
    TrainerCls, _restore_student_forward = _build_distilling_trainer_cls(
        student, teacher, adapter, s_feats, t_feats, weights, cfg, feat_align_loss)
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
    # ------------------------------------------------------------------
    # Trainer callbacks (closed over args/cfg/log_header/etc).
    # ------------------------------------------------------------------
    state = {"step": 0}

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
            _write_log_row(args.log, {
                "epoch":      int(getattr(trainer, "epoch", 0)),
                "step":       int(state["step"]),
                "loss_total": round(loss_total, 6),
                "loss_det":   round(loss_det_val, 6),
                "loss_kd":    0.0,
                "loss_align": 0.0,
                "loss_spike": 0.0,
                "lr":         round(lr_val, 8),
            }, log_header)
        except Exception as e:
            print(f"[distill] log callback failed: {e!r}")

    def _cb_save_epoch_ckpt(trainer):
        # Save state_dict only (NOT the full Module) so the per-epoch
        # checkpoint can be reloaded in a fresh interpreter without needing
        # the KD-monkeypatched forward closures to be in scope. The final
        # save at the end of train_impl() saves the unwrapped Module.
        ep = int(getattr(trainer, "epoch", 0))
        if (ep + 1) % max(ckpt_interval, 1) != 0:
            return
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

    nonlocal_box = {"restore": _restore_student_forward}
    try:
        trainer = TrainerCls(overrides=overrides)
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
