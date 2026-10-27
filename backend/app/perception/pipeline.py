"""Answer perception for one response window (brief 9.3-9.6).

Runs the tracker path (SAM 3.1 + DTW, or the local optical-flow baseline) and the blind Spark judge
in parallel, then fuses them. The judge only ever sees the clip and the calibrated signal text.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.config import Settings
from app.engine.types import Answer, Observation
from app.providers.local import LocalFlowTracker
from app.providers.registry import Mode, ProviderHub
from app.roles import Roles

from .dtw import classify
from .features import Baseline, count_repetitions, normalise, sam_feature_seq
from .fusion import SourceResult, fuse, judge_probs, normalise_probs
from .media import normalize_video, read_frames

log = logging.getLogger(__name__)


@dataclass
class Perception:
    observation: Observation
    sources: list[SourceResult]
    overlay: dict[str, Any] | None = None
    latency_ms: float = 0.0
    usd: float = 0.0
    notes: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    late: asyncio.Task[SourceResult | None] | None = (
        None  # judge still running after an early decision
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.to_dict(),
            "latency_ms": round(self.latency_ms, 1),
            "usd": round(self.usd, 5),
            "notes": self.notes,
            "judge_pending": self.late is not None,
        }


def _template_source(
    name: str,
    seq: np.ndarray,
    tmpl: dict[str, Any],
    fps: float,
    emergency_count: int,
    missing: float = 0.0,
) -> SourceResult:
    baseline = Baseline.from_dict(tmpl["baseline"])
    x = normalise(seq, baseline)
    templates = {k: [np.asarray(t) for t in v] for k, v in tmpl["templates"].items()}
    probs, dists = classify(x, templates, tmpl["temperature"])
    probs = normalise_probs(probs)
    reps = count_repetitions(x, float(tmpl.get("yes_amplitude", 0.0)), fps)
    if reps >= emergency_count:
        probs = normalise_probs({**probs, "emergency": max(probs.get("emergency", 0.0), 0.6)})
    if missing > 0:
        # lost tracks lower the confidence: shrink toward uniform
        k = min(missing, 0.8)
        probs = {c: (1 - k) * p + k * 0.25 for c, p in probs.items()}
    return SourceResult(
        name,
        probs,
        True,
        {
            "distances": {k: round(v, 3) for k, v in dists.items()},
            "repetitions": reps,
            "missing": round(missing, 3),
        },
    )


def early_decision_ok(res: SourceResult | None, p_min: float, margin_min: float) -> bool:
    """Whether the tracker alone may decide, without waiting for the blind judge.

    Only for a clear YES or NO: confident, and the best template clearly closer than the runner-up.
    The fitted DTW temperature can be overconfident on a clip unlike the calibration clips, so the
    distance margin is checked as well. "No answer" always waits for the judge, which may see a
    movement the templates missed; a missed answer costs more than a few seconds.
    """
    if res is None or not res.ok:
        return False
    top, p = res.top
    if top not in ("yes", "no") or p < p_min:
        return False
    d = sorted(res.detail.get("distances", {}).values())
    if len(d) < 2:
        return False
    return d[0] <= 0 or d[1] / d[0] >= margin_min


async def perceive(
    clip: Path,
    calibration: dict[str, Any],
    workdir: Path,
    *,
    hub: ProviderHub,
    roles: Roles,
    settings: Settings,
    mode: Mode,
) -> Perception:
    t0 = time.perf_counter()
    pcfg = settings.perception
    workdir.mkdir(parents=True, exist_ok=True)
    # Answer windows use the frame rate the templates were built at, so a calibration keeps
    # working when the configured rate changes.
    target_fps = round(
        (calibration.get("tracker") or calibration.get("local") or {}).get("fps") or pcfg.fps
    )
    mp4 = await normalize_video(
        clip, workdir / f"{clip.stem}_norm.mp4", pcfg.width, pcfg.height, target_fps, max_s=6.0
    )
    fps = read_frames(mp4, max_frames=2).fps or float(target_fps)
    info = hub.resolve(mode)
    notes: list[str] = []
    usd = 0.0
    overlay: dict[str, Any] | None = None

    async def tracker_path() -> SourceResult | None:
        nonlocal usd, overlay
        tmpl = calibration.get("tracker")
        tracker = hub.tracker(mode)
        if not tmpl or tracker.provider in ("local", "mock"):
            return None
        prompts = calibration.get("prompts") or ["face"]
        try:
            results = await asyncio.gather(*(tracker.track(mp4, p) for p in prompts))
        except Exception as exc:
            notes.append(f"tracker failed: {exc}")
            return SourceResult("tracker", {}, ok=False, detail={"error": str(exc)[:200]})
        calls = []
        for r in results:
            cost = hub.record_track(r)
            usd += cost
            calls.append(
                {
                    "role": "tracker",
                    "provider": r.provider,
                    "model": r.model,
                    "latency_ms": round(r.latency_ms, 1),
                    "usd": round(cost, 6),
                    "fallback": False,
                    "error": None,
                }
            )
        overlay = results[0].to_overlay()
        seqs = [sam_feature_seq(r, fps=fps) for r in results]
        n = min(len(s.values) for s in seqs)
        if n < 4:
            return SourceResult(
                "tracker", {}, ok=False, detail={"error": "track lost"}, calls=calls
            )
        seq = np.concatenate([s.values[:n] for s in seqs], axis=1)
        missing = float(np.mean([s.missing_fraction for s in seqs]))
        res = _template_source("tracker", seq, tmpl, fps, pcfg.emergency_yes_count, missing)
        res.calls = calls
        return res

    async def local_path() -> SourceResult | None:
        nonlocal overlay
        tmpl = calibration.get("local")
        if not tmpl:
            return None
        res = await LocalFlowTracker().track(mp4, "motion")
        if overlay is None:
            overlay = res.to_overlay()
        seq = np.asarray(res.features or [])
        if len(seq) < 4:
            return SourceResult("local", {}, ok=False, detail={"error": "too few frames"})
        return _template_source("local", seq, tmpl, fps, pcfg.emergency_yes_count)

    async def judge_path() -> SourceResult | None:
        nonlocal usd
        if info.effective == Mode.MOCK or not hub.flag("use_spark_judge"):
            return None
        vl = getattr(hub.vision_language(mode), "media", hub.vision_language(mode))
        if vl.provider == "mock":
            return None  # no model may see the clip in this mode (e.g. on-premises privacy tier)
        timeout = pcfg.judge_timeout_s + 2
        try:
            r = await asyncio.wait_for(
                roles.judge(mode, mp4, calibration.get("signal_text", "")), timeout=timeout
            )
        except TimeoutError:
            notes.append("judge timed out")
            timed_out = {
                "role": "blind_judge",
                "provider": vl.provider,
                "model": getattr(vl, "model", "") or settings.models.get("spark", ""),
                "latency_ms": timeout * 1000.0,
                "usd": 0.0,
                "fallback": True,
                "error": "timeout",
            }
            return SourceResult(
                "spark", {}, ok=False, detail={"error": "timeout"}, calls=[timed_out]
            )
        usd += r.meta.usd
        calls = [r.meta.to_dict()]
        if not r.ok:
            return SourceResult("spark", {}, ok=False, detail={"error": r.meta.error}, calls=calls)
        return SourceResult(
            "spark",
            judge_probs(r.data.classification, r.data.confidence),
            True,
            {
                "observed": r.data.observed_movement,
                "frame_times": r.data.frame_times,
                "latency_ms": round(r.meta.latency_ms),
            },
            calls,
        )

    judge_task = asyncio.ensure_future(judge_path())
    track_res, local_res = await asyncio.gather(tracker_path(), local_path())
    late: asyncio.Task[SourceResult | None] | None = None
    judge_res: SourceResult | None = None
    early = early_decision_ok(track_res, pcfg.early_decision_p, pcfg.early_decision_margin)
    if early and not judge_task.done():
        # Latency: SAM is confident, so don't make the patient wait for the slower blind judge.
        # Its verdict is attached to the trail when it arrives (audit, disagreement alert).
        done, _ = await asyncio.wait({judge_task}, timeout=pcfg.early_grace_s)
        if not done:
            late = judge_task
            notes.append("early decision on the tracker; blind judge result follows")
    if late is None:
        judge_res = await judge_task
    sources = [r for r in (track_res, local_res, judge_res) if r is not None]
    weights = dict(calibration.get("weights") or {})
    tracker_ok = any(s.name == "tracker" and s.ok for s in sources)
    if tracker_ok:
        sources = [s for s in sources if s.name != "local" or len(sources) == 1]
    obs = fuse(sources, weights, pcfg.unclear_threshold)
    if late is not None:
        obs.confidence *= 0.95  # one source only
        obs.sources.setdefault("sources", {})["spark"] = {"ok": True, "pending": True}
    if obs.answer == Answer.UNCLEAR and not sources:
        notes.append("no perception source available; caregiver should tap the answer")
    keep = settings.raw["app"].get("keep_clips_for_evaluation") or hub.store.kv_get(
        "keep_clips_for_evaluation"
    )
    if not keep:

        def cleanup(_: object = None) -> None:
            for p in (clip, mp4):
                p.unlink(missing_ok=True)

        if late is not None:
            late.add_done_callback(cleanup)
        else:
            cleanup()
    calls = [c for s in sources for c in s.calls]
    return Perception(
        obs,
        sources,
        overlay,
        latency_ms=(time.perf_counter() - t0) * 1000,
        usd=usd,
        notes=notes,
        late=late,
        calls=calls,
    )
