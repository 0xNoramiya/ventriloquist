"""Personal base rates learned from confirmed messages (brief 8.9).

Dirichlet posterior with the population base rates as the prior mean. Each confirmed message
adds a pseudo-count that decays with a 3-day half-life, so last night's habits count more than
last week's. personal(h) = personal estimate / base rate, clipped to [0.5, 3].
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class ConfirmedMessage:
    hypothesis_id: str
    at: datetime


def decayed_counts(
    history: Iterable[ConfirmedMessage], now: datetime, half_life_days: float
) -> dict[str, float]:
    counts: dict[str, float] = {}
    for m in history:
        age_days = max((now - m.at).total_seconds(), 0.0) / 86400.0
        counts[m.hypothesis_id] = counts.get(m.hypothesis_id, 0.0) + 0.5 ** (age_days / half_life_days)
    return counts


def personal_multipliers(
    history: Iterable[ConfirmedMessage],
    base_rates: dict[str, float],
    now: datetime,
    *,
    half_life_days: float = 3.0,
    prior_strength: float = 10.0,
    clip: tuple[float, float] = (0.5, 3.0),
) -> dict[str, float]:
    total_base = sum(base_rates.values()) or 1.0
    base = {h: v / total_base for h, v in base_rates.items()}
    counts = decayed_counts(history, now, half_life_days)
    n = sum(counts.get(h, 0.0) for h in base)
    out: dict[str, float] = {}
    for h, b in base.items():
        estimate = (counts.get(h, 0.0) + prior_strength * b) / (n + prior_strength)
        out[h] = float(np.clip(estimate / b, *clip)) if b > 0 else 1.0
    return out
