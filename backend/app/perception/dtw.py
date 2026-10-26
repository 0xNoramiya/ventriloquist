"""Dynamic time warping nearest-neighbour classification (brief 9.3)."""

from __future__ import annotations

import numpy as np


def dtw_distance(a: np.ndarray, b: np.ndarray, window: int | None = None) -> float:
    """Length-normalised DTW distance between two (T, D) sequences (Euclidean frame cost)."""
    a = np.atleast_2d(np.asarray(a, dtype=float))
    b = np.atleast_2d(np.asarray(b, dtype=float))
    if a.shape[0] == 0 or b.shape[0] == 0:
        return float("inf")
    n, m = len(a), len(b)
    w = max(window or max(n, m), abs(n - m))
    cost = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    acc = np.full((n + 1, m + 1), np.inf)
    acc[0, 0] = 0.0
    for i in range(1, n + 1):
        lo, hi = max(1, i - w), min(m, i + w)
        for j in range(lo, hi + 1):
            acc[i, j] = cost[i - 1, j - 1] + min(acc[i - 1, j], acc[i, j - 1], acc[i - 1, j - 1])
    return float(acc[n, m] / (n + m))


def resample(seq: np.ndarray, length: int) -> np.ndarray:
    seq = np.atleast_2d(np.asarray(seq, dtype=float))
    if len(seq) == length or len(seq) < 2:
        return seq
    src = np.linspace(0, 1, len(seq))
    dst = np.linspace(0, 1, length)
    return np.stack([np.interp(dst, src, seq[:, d]) for d in range(seq.shape[1])], axis=1)


def classify(
    seq: np.ndarray,
    templates: dict[str, list[np.ndarray]],
    temperature: float,
    length: int = 32,
    window: int = 8,
) -> tuple[dict[str, float], dict[str, float]]:
    """Softmin over the nearest template distance of each class. Returns (probs, distances)."""
    x = resample(seq, length)
    dists: dict[str, float] = {}
    for label, temps in templates.items():
        if temps:
            dists[label] = min(
                dtw_distance(x, resample(np.asarray(t), length), window) for t in temps
            )
    if not dists:
        return {}, {}
    labels = list(dists)
    d = np.array([dists[k] for k in labels])
    logits = -(d - d.min()) / max(temperature, 1e-6)
    p = np.exp(logits)
    p /= p.sum()
    return {k: float(v) for k, v in zip(labels, p, strict=True)}, dists


def leave_one_out(
    examples: list[tuple[str, np.ndarray]], temperature: float, length: int = 32, window: int = 8
) -> list[tuple[str, str, dict[str, float]]]:
    """(true label, predicted label, probs) for each example classified against all the others."""
    out = []
    for i, (label, seq) in enumerate(examples):
        temps: dict[str, list[np.ndarray]] = {}
        for j, (lab, s) in enumerate(examples):
            if j != i:
                temps.setdefault(lab, []).append(s)
        probs, _ = classify(seq, temps, temperature, length, window)
        pred = max(probs, key=probs.get) if probs else "none"
        out.append((label, pred, probs))
    return out


def auto_temperature(
    examples: list[tuple[str, np.ndarray]], length: int = 32, window: int = 8
) -> float:
    """Median within-class nearest-neighbour distance, so a typical match is worth ~1 nat."""
    by_label: dict[str, list[np.ndarray]] = {}
    for lab, s in examples:
        by_label.setdefault(lab, []).append(resample(s, length))
    d = []
    for seqs in by_label.values():
        for i, a in enumerate(seqs):
            others = [dtw_distance(a, b, window) for j, b in enumerate(seqs) if j != i]
            if others:
                d.append(min(others))
    return float(np.median(d)) if d else 1.0
