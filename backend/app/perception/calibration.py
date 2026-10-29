"""Calibration wizard backend: bring your own signal.

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

import cv2
import numpy as np

from app.config import Settings
from app.providers.base import Tracker, TrackResult
from app.providers.registry import Mode, ProviderHub
from app.roles import Roles
from app.schemas import CalibrationDescription

from .dtw import fit_temperature, leave_one_out
from .features import SAM_FEATURES, fit_baseline, normalise, peak_amplitude, sam_feature_seq
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


def signal_roi(
    tracks: list[TrackResult], margin: float = 0.6, min_side: float = 0.35
) -> list[float] | None:
    """Region around the patient's signal body parts, from SAM boxes over the calibration clips,
    as fractions of the normalised 4:3 frame (a square in fractions is 4:3 in pixels). The blind
    judge watches this crop: on a whole 320x240 frame a face is about 110 px wide and Muse Spark
    missed most eyebrow raises (12/26 vs 24/26 cropped, generated clips)."""
    boxes = np.array([o.box for r in tracks for f in r.frames for o in f.objects], dtype=float)
    if len(boxes) < 3:
        return None
    x0, y0 = np.percentile(boxes[:, 0], 5), np.percentile(boxes[:, 1], 5)
    x1, y1 = np.percentile(boxes[:, 2], 95), np.percentile(boxes[:, 3], 95)
    return _padded_square(x0, y0, x1, y1, margin, min_side)


def motion_roi(
    signal_clips: list[Path], rest_clips: list[Path], margin: float = 0.6, min_side: float = 0.35
) -> list[float] | None:
    """On-device stand-in for signal_roi when SAM gave no boxes (privacy mode without a
    self-hosted SAM): where the YES and NO clips move more than the rest clip, as the same padded
    square. On the generated clips it finds the eyebrows, as SAM does."""

    def energy(clip: Path) -> np.ndarray | None:
        frames = read_frames(clip, gray=True).images
        if len(frames) < 3:
            return None
        a = np.stack([cv2.GaussianBlur(f, (5, 5), 0) for f in frames]).astype(np.float32)
        d = np.abs(np.diff(a, axis=0))
        k = max(1, len(d) // 10)  # the busiest tenth of the frames: a raise is brief
        return np.sort(d, axis=0)[-k:].mean(axis=0)

    sig = [e for e in map(energy, signal_clips) if e is not None]
    if not sig:
        return None
    rest = [e for e in map(energy, rest_clips) if e is not None]
    m = np.mean(sig, axis=0) - (np.mean(rest, axis=0) if rest else 0.0)
    m = cv2.GaussianBlur(np.clip(m, 0.0, None), (0, 0), 3)
    if m.max() < 1.0:  # under one grey level: nothing moved, so keep the whole frame
        return None
    ys, xs = np.nonzero(m > 0.5 * m.max())
    h, w = m.shape
    return _padded_square(
        np.percentile(xs, 5) / w,
        np.percentile(ys, 5) / h,
        (np.percentile(xs, 95) + 1) / w,
        (np.percentile(ys, 95) + 1) / h,
        margin,
        min_side,
    )


def _padded_square(
    x0: float, y0: float, x1: float, y1: float, margin: float, min_side: float
) -> list[float]:
    side = float(min(1.0, max(max(x1 - x0, y1 - y0) * (1 + 2 * margin), min_side)))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left = float(np.clip(cx - side / 2, 0.0, 1.0 - side))
    top = float(np.clip(cy - side / 2, 0.0, 1.0 - side))
    return [round(left, 4), round(top, 4), round(left + side, 4), round(top + side, 4)]


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
    temp = fit_temperature(
        [("none" if lab == "rest" else lab, s) for lab, s in normed if lab != "emergency"]
    )
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
    raw_of: dict[Path, Path] = {}
    for label, paths in raw_clips.items():
        for i, p in enumerate(paths):
            dst = workdir / f"{label}_{i}.mp4"
            await normalize_video(
                p, dst, pcfg.width, pcfg.height, pcfg.fps, max_s=16.0 if label == "rest" else 6.0
            )
            clips.setdefault(label, []).append(dst)
            raw_of[dst] = p
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

    def examples_from(seqs: dict[Path, np.ndarray], fps: float) -> list[Example]:
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
    local_t = build_templates(examples_from(local_seqs, fps), fps)

    # 5b. SAM 3.1 (or the Modal-hosted open weights in privacy mode)
    tracker = hub.tracker(mode)
    tracker_t: dict[str, Any] | None = None
    overlay = None
    roi: list[float] | None = None
    if tracker.provider not in ("local", "mock"):
        try:
            # SAM 3.1 runs at its own, lower frame rate (faster, equally accurate)
            tfps = float(pcfg.tracker_fps)
            sam_of = {c: c.with_name(f"{c.stem}_sam.mp4") for c in all_clips}
            if tfps != fps:
                await asyncio.gather(
                    *(
                        normalize_video(
                            c, sam_of[c], pcfg.width, pcfg.height, pcfg.tracker_fps, max_s=None
                        )
                        for c in all_clips
                    )
                )
            else:
                sam_of = {c: c for c in all_clips}
            sam_clips = list(sam_of.values())
            results = await _track_all(tracker, sam_clips, prompts, hub, asyncio.Semaphore(4))
            seqs = {c: _seq_for(results, sam_of[c], prompts) for c in all_clips}
            tracker_t = build_templates(examples_from(seqs, tfps), tfps)
            tracker_t["provider"] = tracker.provider
            tracker_t["features"] = list(SAM_FEATURES)
            roi = signal_roi(list(results.values()))
            first_yes = clips.get("yes", [None])[0]
            if first_yes is not None:
                overlay = results[(sam_of[first_yes], prompts[0])].to_overlay()
        except Exception as exc:  # keep calibrating with the local baseline
            log.warning("tracker calibration failed: %s", exc)
    roi_source = "sam" if roi else None
    if roi is None and info.effective != Mode.MOCK:  # only a model judge watches the crop
        signal = [c for label in ("yes", "no") for c in clips.get(label, [])]
        roi = await asyncio.to_thread(motion_roi, signal, clips.get("rest", []))
        roi_source = "motion" if roi else None

    # 6. blind Spark judge on each labelled clip (leave-one-out is implicit: the judge never trains)
    judge_loo: list[dict[str, Any]] = []
    sig = signal_text(desc.model_dump())
    vl = hub.vision_language(mode)
    judge_can_see = getattr(vl, "media", vl).provider != "mock"
    if info.effective != Mode.MOCK and hub.flag("use_spark_judge") and judge_can_see:
        sem = asyncio.Semaphore(4)

        async def judge_one(label: str, clip: Path) -> dict[str, Any]:
            async with sem:
                if roi:  # the judge sees what it will see for answers
                    clip = await normalize_video(
                        raw_of[clip],
                        clip.with_name(f"{clip.stem}_judge.mp4"),
                        pcfg.width,
                        pcfg.height,
                        pcfg.fps,
                        max_s=16.0 if label == "rest" else 6.0,
                        roi=roi,
                    )
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
        "roi": roi,
        "roi_source": roi_source,
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
