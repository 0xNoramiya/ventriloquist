"""Calibration wizard backend (brief 9.2): bring your own signal.

1. framing check (Muse Spark, image)            2. 15 s rest clip (natural blink baseline)
3. YES x3, NO x3, emergency (triple YES) x1      4. Muse Spark names the movement + a SAM prompt
5. SAM 3.1 tracks that body part on every clip -> feature templates (and the local optical-flow
   baseline, which is always computed as an on-device fallback)
6. leave-one-out accuracy per source -> fusion weights and the channel error rates a, b
7. if the signals are not distinct or accuracy < 0.8, suggest a different movement and repeat.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.config import Settings
from app.providers.base import Tracker, TrackResult
from app.providers.registry import Mode, ProviderHub
from app.roles import Roles
from app.schemas import CalibrationDescription

from .dtw import auto_temperature, leave_one_out
from .features import fit_baseline, normalise, peak_amplitude, sam_feature_seq
from .fusion import judge_probs
from .media import normalize_video, read_frames
from .signals import default_calibration, signal_text  # noqa: F401  (re-exported)

log = logging.getLogger(__name__)
LABELS = ("rest", "yes", "no", "emergency")
WINDOW_S = 4.0


@dataclass
class Example:
    label: str
    seq: np.ndarray
    clip: Path


def _windows(seq: np.ndarray, fps: float, window_s: float = WINDOW_S) -> list[np.ndarray]:
    n = int(window_s * fps)
    if len(seq) <= n * 1.5:
        return [seq]
    return [seq[i : i + n] for i in range(0, len(seq) - n + 1, n)]


async def _track_all(
    tracker: Tracker,
    clips: list[Path],
    prompts: list[str],
    hub: ProviderHub,
    sem: asyncio.Semaphore,
) -> dict[tuple[Path, str], TrackResult]:
    async def one(clip: Path, prompt: str) -> tuple[tuple[Path, str], TrackResult]:
        async with sem:
            res = await tracker.track(clip, prompt)
            hub.record_track(res, "calibration_tracker")
            return (clip, prompt), res

    pairs = await asyncio.gather(*(one(c, p) for c in clips for p in prompts))
    return dict(pairs)


def _seq_for(
    results: dict[tuple[Path, str], TrackResult], clip: Path, prompts: list[str]
) -> np.ndarray:
    fps = read_frames(clip, max_frames=2).fps or 15.0
    seqs = [sam_feature_seq(results[(clip, p)], fps=fps).values for p in prompts]
    n = min(len(s) for s in seqs) if seqs else 0
    return np.concatenate([s[:n] for s in seqs], axis=1) if n else np.zeros((0, 1))


def build_templates(examples: list[Example], fps: float) -> dict[str, Any]:
    """Baseline, normalised templates, DTW temperature, YES amplitude and LOO accuracy."""
    rest = [e.seq for e in examples if e.label == "rest"]
    motion = [e.seq for e in examples if e.label != "rest"]
    baseline = fit_baseline(rest, motion)
    normed = [(e.label, normalise(e.seq, baseline)) for e in examples]
    temp = auto_temperature([x for x in normed if x[0] != "emergency"])
    templates: dict[str, list[list[list[float]]]] = {}
    for label, seq in normed:
        templates.setdefault("none" if label == "rest" else label, []).append(seq.tolist())
    loo_input = [("none" if lab == "rest" else lab, s) for lab, s in normed if lab != "emergency"]
    loo = leave_one_out(loo_input, temp)
    correct = sum(t == p for t, p, _ in loo)
    yes_amp = float(np.median([peak_amplitude(s) for lab, s in normed if lab == "yes"] or [0.0]))
    return {
        "baseline": baseline.to_dict(),
        "templates": templates,
        "temperature": temp,
        "yes_amplitude": yes_amp,
        "fps": fps,
        "loo": [
            {"true": t, "pred": p, "probs": {k: round(v, 3) for k, v in pr.items()}}
            for t, p, pr in loo
        ],
        "accuracy": correct / len(loo) if loo else 0.0,
    }


def error_rates(
    loo: list[dict[str, Any]], prior_a: float = 1.0, prior_n: float = 10.0
) -> dict[str, float]:
    """a = P(observe NO | true YES), b = P(observe YES | true NO), Beta-smoothed (prior mean 0.1)."""
    yes = [r for r in loo if r["true"] == "yes"]
    no = [r for r in loo if r["true"] == "no"]
    a = (sum(r["pred"] == "no" for r in yes) + prior_a) / (len(yes) + prior_n)
    b = (sum(r["pred"] == "yes" for r in no) + prior_a) / (len(no) + prior_n)
    return {"a": float(np.clip(a, 0.03, 0.45)), "b": float(np.clip(b, 0.03, 0.45))}


async def finalize(
    patient_id: str,
    raw_clips: dict[str, list[Path]],
    workdir: Path,
    *,
    hub: ProviderHub,
    roles: Roles,
    settings: Settings,
    mode: Mode,
    hint: str | None = None,
    description_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    pcfg = settings.perception
    clips: dict[str, list[Path]] = {}
    for label, paths in raw_clips.items():
        for i, p in enumerate(paths):
            dst = workdir / f"{label}_{i}.mp4"
            await normalize_video(
                p, dst, pcfg.width, pcfg.height, pcfg.fps, max_s=16.0 if label == "rest" else 6.0
            )
            clips.setdefault(label, []).append(dst)
    info = hub.resolve(mode)

    # 4. describe the signals (Muse Spark watches the clips)
    if description_override:
        desc = CalibrationDescription.model_validate(description_override)
        desc_meta: dict[str, Any] = {"source": "caregiver"}
    else:
        res = await roles.describe_calibration(mode, clips, hint)
        desc, desc_meta = res.data, res.meta.to_dict()
    prompts = list(
        dict.fromkeys([desc.yes.sam_prompt.strip() or "face", desc.no.sam_prompt.strip() or "face"])
    )

    all_clips = [c for label in LABELS for c in clips.get(label, [])]
    fps = float(pcfg.fps)

    def examples_from(seqs: dict[Path, np.ndarray]) -> list[Example]:
        out: list[Example] = []
        for label in LABELS:
            for clip in clips.get(label, []):
                seq = seqs[clip]
                parts = _windows(seq, fps) if label == "rest" else [seq]
                out += [Example(label, s, clip) for s in parts if len(s) > 3]
        return out

    # 5a. local optical-flow baseline (always; on-device fallback)
    from app.providers.local import LocalFlowTracker

    local = LocalFlowTracker()
    local_results = await asyncio.gather(*(local.track(c, "motion") for c in all_clips))
    local_seqs = {
        c: np.asarray(r.features or [[0.0]]) for c, r in zip(all_clips, local_results, strict=True)
    }
    local_t = build_templates(examples_from(local_seqs), fps)

    # 5b. SAM 3.1 (or the Modal-hosted open weights in privacy mode)
    tracker = hub.tracker(mode)
    tracker_t: dict[str, Any] | None = None
    overlay = None
    if tracker.provider not in ("local", "mock"):
        try:
            results = await _track_all(tracker, all_clips, prompts, hub, asyncio.Semaphore(4))
            seqs = {c: _seq_for(results, c, prompts) for c in all_clips}
            tracker_t = build_templates(examples_from(seqs), fps)
            tracker_t["provider"] = tracker.provider
            first_yes = clips.get("yes", [None])[0]
            if first_yes is not None:
                overlay = results[(first_yes, prompts[0])].to_overlay()
        except Exception as exc:  # keep calibrating with the local baseline
            log.warning("tracker calibration failed: %s", exc)

    # 6. blind Spark judge on each labelled clip (leave-one-out is implicit: the judge never trains)
    judge_loo: list[dict[str, Any]] = []
    sig = signal_text(desc.model_dump())
    if info.effective != Mode.MOCK and hub.flag("use_spark_judge"):
        sem = asyncio.Semaphore(4)

        async def judge_one(label: str, clip: Path) -> dict[str, Any]:
            async with sem:
                r = await roles.judge(mode, clip, sig)
            probs = judge_probs(r.data.classification, r.data.confidence)
            pred = max(probs, key=probs.get)
            return {
                "true": "none" if label == "rest" else label,
                "pred": pred,
                "observed": r.data.observed_movement,
                "ok": r.ok,
            }

        jobs = [judge_one(lab, c) for lab in ("yes", "no", "rest") for c in clips.get(lab, [])]
        judge_loo = [j for j in await asyncio.gather(*jobs) if j["ok"]]
    judge_acc = (
        (sum(j["true"] == j["pred"] for j in judge_loo) / len(judge_loo)) if judge_loo else None
    )

    accuracy = {"local": local_t["accuracy"]}
    if tracker_t:
        accuracy["tracker"] = tracker_t["accuracy"]
    if judge_acc is not None:
        accuracy["spark"] = judge_acc
    weights = {k: max(v, 0.05) ** 2 for k, v in accuracy.items()}
    if tracker_t:
        weights["local"] *= 0.25  # the local baseline only matters when SAM is unavailable
    best_loo = (tracker_t or local_t)["loo"]
    if judge_loo and (judge_acc or 0) > (tracker_t or local_t)["accuracy"]:
        best_loo = judge_loo
    rates = error_rates(best_loo)
    best = max(accuracy.values()) if accuracy else 0.0
    ok = bool(desc.distinct) and best >= pcfg.calibration_min_accuracy
    suggestion = None
    if not ok:
        suggestion = (
            "The YES and NO movements were hard to tell apart. Try a bigger or different movement, "
            "for example eyebrows up for YES and eyes squeezed shut for NO, then calibrate again."
        )
    return {
        "mode": str(info.effective),
        "skipped": False,
        "description": desc.model_dump(),
        "description_meta": desc_meta,
        "signal_text": sig,
        "prompts": prompts,
        "tracker": tracker_t,
        "local": local_t,
        "judge_loo": judge_loo,
        "accuracy": accuracy,
        "weights": weights,
        "error_rates": rates,
        "ok": ok,
        "suggestion": suggestion,
        "overlay": overlay,
        "clips": {k: len(v) for k, v in clips.items()},
    }
