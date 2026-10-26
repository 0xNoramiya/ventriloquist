"""On-device motion features: dense optical flow on a 3x3 grid. No model, nothing leaves the machine.

Used in mock mode (so a real camera still works without keys) and as the tracker of last resort in
privacy mode when no self-hosted SAM 3.1 endpoint is configured. It is a baseline, not SAM.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import cv2
import numpy as np

from app.perception.media import read_frames

from .base import FrameTracks, TrackedObject, Tracker, TrackResult

GRID = 3


def flow_features(
    path: Path, width: int = 160
) -> tuple[np.ndarray, list[float], list[tuple[int, int]]]:
    frames = read_frames(path, gray=True)
    if len(frames.images) < 2:
        return np.zeros((0, GRID * GRID * 3)), [], []
    h0, w0 = frames.images[0].shape[:2]
    scale = width / w0
    size = (width, max(1, int(h0 * scale)))
    prev = cv2.resize(frames.images[0], size)
    rows: list[list[float]] = []
    hot: list[tuple[int, int]] = []
    for img in frames.images[1:]:
        cur = cv2.resize(img, size)
        flow = cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 2, 9, 2, 5, 1.1, 0)
        gh, gw = size[1] // GRID, size[0] // GRID
        row: list[float] = []
        best, best_cell = -1.0, (0, 0)
        for r in range(GRID):
            for c in range(GRID):
                cell = flow[r * gh : (r + 1) * gh, c * gw : (c + 1) * gw]
                dx, dy = float(cell[..., 0].mean()), float(cell[..., 1].mean())
                mag = float(np.linalg.norm(cell, axis=-1).mean())
                row += [dx, dy, mag]
                if mag > best:
                    best, best_cell = mag, (r, c)
        rows.append(row)
        hot.append(best_cell)
        prev = cur
    return np.array(rows), frames.times[1:], hot


class LocalFlowTracker(Tracker):
    provider = "local"

    async def track(self, video: Path, prompt: str) -> TrackResult:
        t0 = time.perf_counter()
        feats, times, hot = await asyncio.to_thread(flow_features, video)
        frames = [
            FrameTracks(
                t, [TrackedObject(0, (c / GRID, r / GRID, (c + 1) / GRID, (r + 1) / GRID), 1.0)]
            )
            for t, (r, c) in zip(times, hot, strict=True)
        ]
        names = [
            f"{k}_{r}{c}" for r in range(GRID) for c in range(GRID) for k in ("dx", "dy", "mag")
        ]
        return TrackResult(
            frames,
            "local",
            "optical-flow-3x3",
            prompt,
            (time.perf_counter() - t0) * 1000,
            features=feats.tolist(),
            feature_names=names,
        )
