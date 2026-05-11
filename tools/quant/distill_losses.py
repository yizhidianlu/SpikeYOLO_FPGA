"""A1 Phase 1.5 distillation losses.

Three losses called from ``distill_from_teacher.py``:
 * ``kd_logits_loss``  — detect-head KD (cls KL on softened logits + reg L1).
 * ``feat_align_loss`` — per-layer MSE on adapter-projected teacher features.
 * ``spike_rate_loss`` — SNN-specific per-channel spike-rate L1.

torch is imported lazily so ``--help`` works on torch-less machines.
"""

from __future__ import annotations


def kd_logits_loss(student_p4, teacher_p4, num_classes, T: float = 4.0):
    """Detect-head KD: KL on cls logits (softened by T) + L1 on reg logits.

    Both inputs share shape ``(B, num_classes + 4*reg_max, H, W)``. The first
    ``num_classes`` channels are cls logits, the rest are bbox-distribution
    (DFL) logits. Returns a scalar tensor.
    """
    import torch
    import torch.nn.functional as F

    assert student_p4.shape == teacher_p4.shape, (
        f"shape mismatch: student {tuple(student_p4.shape)} vs teacher {tuple(teacher_p4.shape)}"
    )
    assert student_p4.dim() == 4, f"expected 4D BCHW logits, got {student_p4.dim()}D"
    assert student_p4.shape[1] >= num_classes, (
        f"channel {student_p4.shape[1]} < num_classes {num_classes}"
    )

    s_cls, s_reg = student_p4[:, :num_classes], student_p4[:, num_classes:]
    t_cls, t_reg = teacher_p4[:, :num_classes], teacher_p4[:, num_classes:]

    s_log = F.log_softmax(s_cls / T, dim=1)
    t_soft = F.softmax(t_cls / T, dim=1)
    cls_loss = F.kl_div(s_log, t_soft, reduction="batchmean") * (T * T)
    reg_loss = F.l1_loss(s_reg, t_reg) if s_reg.shape[1] > 0 else s_reg.new_zeros(())
    return cls_loss + reg_loss


def feat_align_loss(student_feats, teacher_feats_aligned, weights=None):
    """MSE per matched layer, weighted sum over layers.

    ``student_feats`` and ``teacher_feats_aligned`` are dicts keyed by alignment
    name (e.g. ``"layer_05_ds2"``). Teacher tensors must already be
    adapter-projected to student channel count.
    """
    import torch
    import torch.nn.functional as F

    assert isinstance(student_feats, dict) and isinstance(teacher_feats_aligned, dict)
    common = sorted(set(student_feats) & set(teacher_feats_aligned))
    assert common, "no overlapping alignment keys"

    weights = weights or {k: 1.0 for k in common}
    total = None
    for k in common:
        s, t = student_feats[k], teacher_feats_aligned[k]
        assert s.shape[1] == t.shape[1], f"{k}: channel mismatch {s.shape} vs {t.shape}"
        if s.shape[-2:] != t.shape[-2:]:
            t = F.adaptive_avg_pool2d(t, s.shape[-2:])
        loss = F.mse_loss(s, t) * float(weights.get(k, 1.0))
        total = loss if total is None else total + loss
    return total


def spike_rate_loss(student_spike_dict, teacher_spike_dict):
    """Per-channel mean spike-rate L1 over matched LIF tap names.

    Each value in the dicts is a binary {0,1} tensor of shape
    ``(T*D, B, C, H, W)`` or ``(B, C, H, W)``; we collapse all non-channel dims
    to a per-channel firing rate before comparing.
    """
    import torch

    assert isinstance(student_spike_dict, dict) and isinstance(teacher_spike_dict, dict)
    common = sorted(set(student_spike_dict) & set(teacher_spike_dict))
    if not common:
        # SNN spike taps may be empty in dry-run; return a zero scalar.
        any_t = next(iter(student_spike_dict.values()), None)
        return any_t.new_zeros(()) if any_t is not None else torch.zeros(())

    total = None
    for k in common:
        s = student_spike_dict[k].float()
        t = teacher_spike_dict[k].float()
        # collapse all dims except channel (assume channel = -3 for BCHW or 5D)
        ch_axis = -3 if s.dim() >= 3 else 0
        s_rate = s.mean(dim=[d for d in range(s.dim()) if d != s.dim() + ch_axis])
        t_rate = t.mean(dim=[d for d in range(t.dim()) if d != t.dim() + ch_axis])
        n = min(s_rate.shape[0], t_rate.shape[0])
        loss = (s_rate[:n] - t_rate[:n]).abs().mean()
        total = loss if total is None else total + loss
    return total
