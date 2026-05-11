"""Python smoke for FPS-meter expected behaviour.

We don't try to compile the C++ ringbuf/fps_meter here (no g++ on Windows);
instead we re-implement the same EMA algorithm and confirm:
* monotone tick stream gives a stable FPS
* one large gap pulls EMA towards the slower instantaneous rate
* CV-of-FPS stays low for a uniform stream

This documents the algorithm so any later C++ refactor can compare against
this reference.
"""

from __future__ import annotations

import math
import time
from typing import List

import pytest


class PyFpsMeter:
    def __init__(self, ema_alpha: float = 0.1, window: int = 120):
        self.alpha = ema_alpha
        self.window = window
        self.history: List[float] = []
        self.last_t = None
        self.ema = 0.0
        self.frames = 0

    def tick(self, now: float) -> None:
        if self.last_t is not None:
            dt = now - self.last_t
            if dt > 0:
                inst = 1.0 / dt
                self.history.append(inst)
                if len(self.history) > self.window:
                    self.history.pop(0)
                if self.ema == 0:
                    self.ema = inst
                else:
                    self.ema = (1 - self.alpha) * self.ema + self.alpha * inst
        self.last_t = now
        self.frames += 1

    def cv(self) -> float:
        if len(self.history) < 2:
            return 0.0
        mean = sum(self.history) / len(self.history)
        if mean == 0:
            return 0.0
        var = sum((x - mean) ** 2 for x in self.history) / len(self.history)
        return math.sqrt(var) / mean


@pytest.mark.contract
def test_uniform_stream_low_cv():
    m = PyFpsMeter()
    t = 0.0
    for _ in range(120):
        m.tick(t)
        t += 1.0 / 30.0    # exactly 30 FPS
    assert abs(m.ema - 30.0) < 1.0
    assert m.cv() < 0.05


@pytest.mark.contract
def test_jitter_increases_cv():
    m = PyFpsMeter()
    t = 0.0
    for i in range(120):
        m.tick(t)
        # alternate 25 / 35 FPS
        t += (1.0 / 25.0) if i % 2 == 0 else (1.0 / 35.0)
    assert m.cv() > 0.1


@pytest.mark.contract
def test_ema_responds_to_slowdown():
    m = PyFpsMeter(ema_alpha=0.5)
    t = 0.0
    for _ in range(30):
        m.tick(t); t += 1 / 30.0
    fast_ema = m.ema
    # 1 s gap then continue
    t += 1.0
    for _ in range(5):
        m.tick(t); t += 1 / 30.0
    assert m.ema < fast_ema   # EMA fell after the long gap
