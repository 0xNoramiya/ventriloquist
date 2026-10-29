"""Bayesian updates under a noisy yes/no channel."""

from __future__ import annotations

import numpy as np

from .types import Answer, Observation


def normalize(p: np.ndarray) -> np.ndarray:
    total = float(p.sum())
    if total <= 0 or not np.isfinite(total):
        return np.full_like(p, 1.0 / len(p))
    return p / total


def effective_error_rates(
    obs: Observation, a: float, b: float, eps_clip: tuple[float, float]
) -> tuple[float, float]:
    """Per-observation error rates.

    eps_eff = clip(1 - confidence, lo, hi). A detector observation is never trusted more than
    the patient's calibrated error rates allow, so a' = max(a, eps_eff). A caregiver override
    is a human reading of the patient and uses eps_eff alone.
    """
    lo, hi = eps_clip
    eps = float(np.clip(1.0 - obs.confidence, lo, hi))
    if obs.overridden:
        return eps, eps
    return float(np.clip(max(a, eps), lo, hi)), float(np.clip(max(b, eps), lo, hi))


def bayes_update(
    p: np.ndarray, yes_mask: np.ndarray, answer: Answer, a_eff: float, b_eff: float
) -> np.ndarray:
    """Posterior after observing YES or NO to a question with yes-set `yes_mask`."""
    if answer == Answer.YES:
        lik = np.where(yes_mask, 1.0 - a_eff, b_eff)
    elif answer == Answer.NO:
        lik = np.where(yes_mask, a_eff, 1.0 - b_eff)
    else:
        return p.copy()  # UNCLEAR / NONE never update
    return normalize(p * lik)


def confirm_no(p: np.ndarray, index: int, factor: float) -> np.ndarray:
    q = p.copy()
    q[index] *= factor
    return normalize(q)


def to_dict(p: np.ndarray, ids: list[str]) -> dict[str, float]:
    return {hid: float(v) for hid, v in zip(ids, p, strict=True)}
