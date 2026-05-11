"""A1 Phase 1.5: 1x1 conv adapter projecting teacher features to student channels.

One adapter per alignment point; spatial mismatch handled by adaptive avgpool
inside ``forward``. torch is imported lazily to keep ``--help`` torch-free.
"""

from __future__ import annotations

from typing import List, Tuple


def build_adapter(alignment_specs: List[Tuple[str, int, int]], init: str = "kaiming"):
    """Factory: returns a TeacherAdapter instance (torch imported lazily)."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class TeacherAdapter(nn.Module):
        """Per-alignment 1x1 conv: teacher_ch -> student_ch (+ spatial align)."""

        def __init__(self, specs: List[Tuple[str, int, int]]):
            super().__init__()
            self.projs = nn.ModuleDict()
            self.specs = {name: (t_ch, s_ch) for name, t_ch, s_ch in specs}
            for name, t_ch, s_ch in specs:
                self.projs[name] = nn.Conv2d(t_ch, s_ch, kernel_size=1, bias=True)

        def init_weights(self, mode: str = "kaiming"):
            for m in self.projs.values():
                if mode == "kaiming":
                    nn.init.kaiming_normal_(m.weight, mode="fan_out", nonlinearity="relu")
                elif mode == "xavier":
                    nn.init.xavier_normal_(m.weight)
                else:
                    nn.init.normal_(m.weight, std=0.01)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

        def forward(self, name: str, teacher_feat: "torch.Tensor",
                    target_hw: tuple = None) -> "torch.Tensor":
            assert name in self.projs, f"no adapter registered for '{name}'"
            x = self.projs[name](teacher_feat)
            if target_hw is not None and x.shape[-2:] != tuple(target_hw):
                x = F.adaptive_avg_pool2d(x, tuple(target_hw))
            return x

    adapter = TeacherAdapter(alignment_specs)
    adapter.init_weights(init)
    return adapter


def spatial_align(teacher_feat, target_hw):
    """Standalone helper: avgpool teacher feat to ``target_hw`` if needed."""
    import torch.nn.functional as F
    if tuple(teacher_feat.shape[-2:]) == tuple(target_hw):
        return teacher_feat
    return F.adaptive_avg_pool2d(teacher_feat, tuple(target_hw))
