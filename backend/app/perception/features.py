"""Per-frame movement features (brief 9.3).

SAM path: track the calibrated body part with its text prompt; per frame take box area, centroid x/y,
box height and top edge, normalised against the rest baseline, plus whether the part was seen at
all: eyes squeezed shut are often not found as "eyes", and that absence is the signal. Lost boxes
are interpolated for the geometric features. Works with boxes alone (masks are optional).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.providers.base import TrackResult

SAM_FEATURES = ["area", "cx", "cy", "h", "top", "seen"]
# Calibrations made before "seen" was added keep their five features.
LEGACY_SAM_FEATURES = SAM_FEATURES[:5]


@dataclass
class FeatureSeq:
    values: np.ndarray  # (T, D)
    names: list[str]
    missing_fraction: float
    times: list[float]


def sam_feature_seq(
    track: TrackResult,
    n_frames: int | None = None,
    fps: float = 15.0,
    names: list[str] | None = None,
) -> FeatureSeq:
    """Aggregate all objects of each frame (e.g. both eyes) into one box-derived feature row."""
    if track.features is not None:
        vals = np.asarray(track.features, dtype=float)
        return FeatureSeq(vals, track.feature_names or [], 0.0, [f.t for f in track.frames])
    by_index = {round(f.t * fps): f for f in track.frames}
    total = n_frames or (max(by_index) + 1 if by_index else 0)
    rows = []
    missing = 0
    for i in range(total):
        f = by_index.get(i)
        if not f or not f.objects:
            rows.append([np.nan] * (len(SAM_FEATURES) - 1) + [0.0])
            missing += 1
            continue
        boxes = np.array([o.box for o in f.objects], dtype=float)
        x0, y0 = boxes[:, 0].min(), boxes[:, 1].min()
        x1, y1 = boxes[:, 2].max(), boxes[:, 3].max()
        area = float(sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes))
        rows.append([area, (x0 + x1) / 2, (y0 + y1) / 2, y1 - y0, y0, 1.0])
    vals = np.array(rows, dtype=float) if rows else np.zeros((0, len(SAM_FEATURES)))
    vals = _interpolate(vals)
    names = names or SAM_FEATURES
    vals = vals[:, [SAM_FEATURES.index(n) for n in names]] if len(vals) else vals
    return FeatureSeq(
        vals, list(names), missing / total if total else 1.0, [i / fps for i in range(total)]
    )


def _interpolate(vals: np.ndarray) -> np.ndarray:
    if vals.size == 0:
        return vals
    out = vals.copy()
    idx = np.arange(len(out))
    for d in range(out.shape[1]):
        col = out[:, d]
        ok = ~np.isnan(col)
        if ok.sum() == 0:
            out[:, d] = 0.0
        elif ok.sum() < len(col):
            out[:, d] = np.interp(idx, idx[ok], col[ok])
    return out


@dataclass
class Baseline:
    mean: np.ndarray
    scale: np.ndarray

    def to_dict(self) -> dict[str, list[float]]:
        return {"mean": self.mean.tolist(), "scale": self.scale.tolist()}

    @classmethod
    def from_dict(cls, d: dict[str, list[float]]) -> Baseline:
        return cls(np.array(d["mean"]), np.array(d["scale"]))


def fit_baseline(rest: list[np.ndarray], motion: list[np.ndarray]) -> Baseline:
    """Centre on the rest clips; scale each dimension by the spread seen across all calibration clips."""
    rest_all = np.concatenate([r for r in rest if len(r)]) if rest else np.zeros((1, 1))
    all_rows = (
        np.concatenate([x for x in rest + motion if len(x)]) if (rest or motion) else rest_all
    )
    mean = np.median(rest_all, axis=0)
    spread = np.percentile(all_rows, 95, axis=0) - np.percentile(all_rows, 5, axis=0)
    scale = np.where(spread > 1e-6, spread, 1.0)
    return Baseline(mean, scale)


def normalise(seq: np.ndarray, baseline: Baseline) -> np.ndarray:
    """Centre each clip on its own median pose (the movement is a minority of the window, so the
    median is the resting pose; this removes slow drift between clips) and scale per dimension."""
    if seq.size == 0:
        return seq
    return (seq - np.median(seq, axis=0, keepdims=True)) / baseline.scale


def count_repetitions(
    seq: np.ndarray, amplitude: float, fps: float, min_gap_s: float = 0.35
) -> int:
    """Peaks of movement energy above half the calibrated YES amplitude (for triple-YES)."""
    if seq.size == 0 or amplitude <= 0:
        return 0
    energy = np.linalg.norm(seq - np.median(seq, axis=0), axis=1)
    k = max(1, int(fps * 0.15))
    energy = np.convolve(energy, np.ones(k) / k, mode="same")
    thr = 0.5 * amplitude
    peaks, last = 0, -1e9
    above = False
    for i, v in enumerate(energy):
        if v >= thr and not above and (i - last) / fps >= min_gap_s:
            peaks += 1
            last = i
            above = True
        elif v < thr * 0.6:
            above = False
    return peaks


def peak_amplitude(seq: np.ndarray) -> float:
    if seq.size == 0:
        return 0.0
    return float(np.linalg.norm(seq - np.median(seq, axis=0), axis=1).max())
