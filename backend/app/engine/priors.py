"""Context-aware priors with bounded influence (Safety rule 8).

p0(h) ∝ base(h) × personal(h) × context(h)

* context(h) is the product of LLM multipliers from {0.25, 0.5, 1, 2, 4}; each must cite at least
  one valid evidence id or it is forced to 1. The product is clipped to [0.1, 8].
* personal(h) comes from personal.py, clipped to [0.5, 3].
* Then the safety bounds hold simultaneously: every p <= cap (0.40), every p >= floor (0.005) and
  p("other") >= 0.08. We find the single scale t with sum_i clip(t * q_i, lo_i, hi_i) = 1 by
  bisection, which is the fixed point of "clip, renormalise, repeat".

The LLM supplies intuition; this code makes the decisions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .types import META_OTHER, Hypothesis


@dataclass
class ContextMultiplier:
    hypothesis_id: str
    factor: float
    evidence_ids: tuple[str, ...]
    reason: str = ""


@dataclass
class EvidenceChip:
    evidence_id: str
    factor: float
    reason: str


@dataclass
class PriorTerm:
    """Why a hypothesis got its prior; shown as chips on the caregiver view."""

    base: float
    personal: float = 1.0
    context: float = 1.0
    chips: list[EvidenceChip] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    unbounded: float = 0.0
    final: float = 0.0
    bounded: str | None = None  # "cap" | "floor" | "other_min"

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": round(self.base, 5),
            "personal": round(self.personal, 4),
            "context": round(self.context, 4),
            "chips": [
                {"evidence_id": c.evidence_id, "factor": c.factor, "reason": c.reason}
                for c in self.chips
            ],
            "rejected": self.rejected,
            "unbounded": round(self.unbounded, 5),
            "final": round(self.final, 5),
            "bounded": self.bounded,
        }


def snap_factor(value: float, allowed: list[float]) -> float:
    """Snap to the nearest allowed multiplier in log space."""
    if value <= 0 or not math.isfinite(value):
        return 1.0
    return min(allowed, key=lambda f: abs(math.log(f) - math.log(value)))


def context_factors(
    hyp_ids: list[str],
    multipliers: list[ContextMultiplier],
    valid_evidence: set[str],
    allowed: list[float],
    clip: tuple[float, float],
) -> tuple[dict[str, float], dict[str, list[EvidenceChip]], dict[str, list[dict[str, Any]]]]:
    known = set(hyp_ids)
    factor = {h: 1.0 for h in hyp_ids}
    chips: dict[str, list[EvidenceChip]] = {h: [] for h in hyp_ids}
    rejected: dict[str, list[dict[str, Any]]] = {h: [] for h in hyp_ids}
    for m in multipliers:
        if m.hypothesis_id not in known:
            continue
        f = snap_factor(m.factor, allowed)
        cited = [e for e in m.evidence_ids if e in valid_evidence]
        if not cited:
            rejected[m.hypothesis_id].append(
                {
                    "factor": m.factor,
                    "evidence_ids": list(m.evidence_ids),
                    "why": "no valid evidence",
                }
            )
            continue
        if f == 1.0:
            continue
        factor[m.hypothesis_id] *= f
        chips[m.hypothesis_id].append(EvidenceChip(",".join(cited), f, m.reason))
    lo, hi = clip
    for h in hyp_ids:
        factor[h] = float(np.clip(factor[h], lo, hi))
    return factor, chips, rejected


def apply_bounds(
    q: np.ndarray,
    cap: float,
    floor: float,
    other_index: int | None = None,
    other_min: float = 0.0,
) -> np.ndarray:
    """Return p with sum 1, floor <= p_i <= cap and p_other >= other_min, as close to q as a
    single rescaling allows."""
    n = len(q)
    q = np.asarray(q, dtype=float)
    q = np.where(q > 0, q, 1e-12)
    cap = max(cap, 1.0 / n)
    floor = min(floor, 1.0 / n)
    lo = np.full(n, floor)
    hi = np.full(n, cap)
    if other_index is not None:
        lo[other_index] = min(max(floor, other_min), cap)
    if lo.sum() > 1.0:  # infeasible floors: fall back to a plain normalisation of the floors
        return lo / lo.sum()

    def mass(t: float) -> float:
        return float(np.clip(t * q, lo, hi).sum())

    t_lo, t_hi = 0.0, float(np.max(hi / q)) + 1.0
    for _ in range(200):
        mid = 0.5 * (t_lo + t_hi)
        if mass(mid) < 1.0:
            t_lo = mid
        else:
            t_hi = mid
    p = np.clip(t_hi * q, lo, hi)
    residual = 1.0 - p.sum()
    free = (p > lo + 1e-15) & (p < hi - 1e-15)
    if abs(residual) > 0 and free.any():
        p[free] += residual * p[free] / p[free].sum()
    return p


def build_prior(
    hyps: list[Hypothesis],
    *,
    personal: dict[str, float] | None = None,
    multipliers: list[ContextMultiplier] | None = None,
    valid_evidence: set[str] | None = None,
    cap: float = 0.40,
    floor: float = 0.005,
    other_min: float = 0.08,
    allowed: list[float] | None = None,
    context_clip: tuple[float, float] = (0.1, 8.0),
    personal_clip: tuple[float, float] = (0.5, 3.0),
) -> tuple[np.ndarray, dict[str, PriorTerm]]:
    ids = [h.id for h in hyps]
    base = np.array([max(h.base_rate, 1e-9) for h in hyps], dtype=float)
    base = base / base.sum()
    personal = personal or {}
    pers = np.array(
        [float(np.clip(personal.get(h, 1.0), *personal_clip)) for h in ids], dtype=float
    )
    ctx, chips, rejected = context_factors(
        ids,
        multipliers or [],
        valid_evidence or set(),
        allowed or [0.25, 0.5, 1.0, 2.0, 4.0],
        context_clip,
    )
    ctx_arr = np.array([ctx[h] for h in ids], dtype=float)
    unbounded = base * pers * ctx_arr
    unbounded = unbounded / unbounded.sum()
    other_index = ids.index(META_OTHER) if META_OTHER in ids else None
    p = apply_bounds(unbounded, cap, floor, other_index, other_min)

    terms: dict[str, PriorTerm] = {}
    for i, h in enumerate(ids):
        bounded = None
        if p[i] >= cap - 1e-9 and unbounded[i] > cap:
            bounded = "cap"
        elif other_index == i and unbounded[i] < other_min:
            bounded = "other_min"
        elif p[i] <= floor + 1e-9 and unbounded[i] < floor:
            bounded = "floor"
        terms[h] = PriorTerm(
            base=float(base[i]),
            personal=float(pers[i]),
            context=float(ctx_arr[i]),
            chips=chips[h],
            rejected=rejected[h],
            unbounded=float(unbounded[i]),
            final=float(p[i]),
            bounded=bounded,
        )
    return p, terms
