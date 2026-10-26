"""Closed-form expected information gain for a yes/no question over a noisy channel (brief 8.5).

For yes-set S with s = sum_{h in S} p(h), a = P(obs NO | true YES), b = P(obs YES | true NO):
    P(obs YES) = s(1 - a) + (1 - s) b
    EIG = H2(P(obs YES)) - [s H2(a) + (1 - s) H2(b)]      (bits)
"""

from __future__ import annotations

import numpy as np

_TINY = 1e-12


def h2(x: np.ndarray | float) -> np.ndarray | float:
    """Binary entropy in bits, safe at 0 and 1."""
    x = np.clip(np.asarray(x, dtype=float), _TINY, 1 - _TINY)
    out = -(x * np.log2(x) + (1 - x) * np.log2(1 - x))
    return out if out.shape else float(out)


def eig(s: np.ndarray | float, a: float, b: float) -> np.ndarray | float:
    s = np.clip(np.asarray(s, dtype=float), 0.0, 1.0)
    p_yes = s * (1 - a) + (1 - s) * b
    out = h2(p_yes) - (s * h2(a) + (1 - s) * h2(b))
    out = np.maximum(out, 0.0)  # tiny negative values from float error only
    return out if np.ndim(out) else float(out)


def yes_mass(posterior: np.ndarray, yes_matrix: np.ndarray) -> np.ndarray:
    """s for every question at once. yes_matrix: (n_questions, n_hypotheses) boolean."""
    return yes_matrix.astype(float) @ posterior
