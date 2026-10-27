"""Detector evaluation on labelled clips (brief 13.2).

Put clips recorded with consenting participants in data/labeled/{yes,no,rest,emergency}/ (gitignored)
and a calibration for the same participant in data/labeled/calibration/{rest,yes,no,emergency}_*.{webm,mp4}.
The script calibrates on the calibration clips, then runs every labelled clip through the full
perception pipeline and reports a confusion matrix per source (tracker, local, spark) and fused,
plus latency statistics. Results go to docs/DETECTOR_EVAL.md and data/labeled/results.json.

    PYTHONPATH=backend:. backend/.venv/bin/python scripts/eval_detector.py [--mode mock|live] [--synthetic]

--synthetic builds a tiny labelled set from the synthetic probe media so the script can be exercised
without recordings (those numbers say nothing about real patients).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

LABELS = ("yes", "no", "rest", "emergency")
CLASSES = ("yes", "no", "none", "emergency", "unclear")
LABELED = ROOT / "data" / "labeled"


def build_synthetic(base: Path) -> None:
    media = ROOT / "data" / "probe_media"
    if not (media / "face_yes_eyebrows.mp4").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_probe_media.py")], check=True)
    src = {
        "yes": media / "face_yes_eyebrows.mp4",
        "no": media / "face_nod.mp4",
        "rest": media / "face_rest_blinks.mp4",
    }
    for split, shifts in (("calibration", (0.0, 0.25, 0.5)), ("eval", (0.1, 0.35, 0.6))):
        for label, path in src.items():
            for i, s in enumerate(shifts):
                d = base / split if split == "calibration" else base / label
                d.mkdir(parents=True, exist_ok=True)
                name = f"{label}_{i}.mp4" if split == "calibration" else f"{label}_{split}_{i}.mp4"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-ss",
                        f"{s:.2f}",
                        "-i",
                        str(path),
                        "-t",
                        "4",
                        "-an",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        str(d / name),
                    ],
                    check=True,
                )


def confusion(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, int]]:
    m = {t: dict.fromkeys(CLASSES, 0) for t in ("yes", "no", "none", "emergency")}
    for r in rows:
        pred = r[key]
        if pred is None:
            continue
        m[r["true"]][pred if pred in CLASSES else "unclear"] += 1
    return m


def accuracy(m: dict[str, dict[str, int]]) -> float:
    total = sum(sum(v.values()) for v in m.values())
    return sum(m[t][t] for t in m) / total if total else 0.0


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="mock", choices=["mock", "live"])
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--fps", type=int, help="override perception.fps (calibration and answers)")
    args = ap.parse_args()
    os.environ["APP_MODE"] = args.mode

    from app.config import load_settings
    from app.perception import calibration as calib
    from app.perception.pipeline import perceive
    from app.providers.registry import Mode, ProviderHub
    from app.roles import Roles
    from app.storage import Store

    base = LABELED if not args.synthetic else ROOT / "data" / "labeled_synthetic"
    if args.synthetic:
        build_synthetic(base)
    cal_dir = base / "calibration"
    if not cal_dir.exists():
        print(f"No calibration clips in {cal_dir}. Record them first (see the module docstring).")
        return
    settings = load_settings().model_copy(update={"app_mode": args.mode})
    if args.fps:
        perception = settings.perception.model_copy(update={"fps": args.fps})
        settings = settings.model_copy(update={"perception": perception})
    work = base / "_work"
    store = Store(work / "data")
    store.kv_set("app_mode", args.mode)
    store.kv_set("keep_clips_for_evaluation", True)
    hub = ProviderHub(settings, store)
    roles = Roles(hub, settings)
    mode = Mode.LIVE if args.mode == "live" else Mode.MOCK
    clips = {lab: sorted(cal_dir.glob(f"{lab}_*")) for lab in LABELS}
    cal = await calib.finalize(
        "eval", clips, work / "cal", hub=hub, roles=roles, settings=settings, mode=mode
    )
    rows: list[dict[str, Any]] = []
    for label in LABELS:
        for clip in sorted((base / label).glob("*")) if (base / label).exists() else []:
            tmp = work / f"in_{clip.name}"
            shutil.copy(clip, tmp)
            perc = await perceive(
                tmp, cal, work, hub=hub, roles=roles, settings=settings, mode=mode
            )
            src = {s.name: (s.top[0] if s.ok else None) for s in perc.sources}
            rows.append(
                {
                    "clip": clip.name,
                    "true": "none" if label == "rest" else label,
                    "fused": str(perc.observation.answer),
                    "tracker": src.get("tracker"),
                    "local": src.get("local"),
                    "spark": src.get("spark"),
                    "latency_ms": round(perc.latency_ms),
                    "usd": perc.usd,
                }
            )
            print(f"{clip.name:28s} true={rows[-1]['true']:9s} fused={rows[-1]['fused']:9s} {src}")
    if not rows:
        print("No labelled clips found.")
        return
    lat = [r["latency_ms"] for r in rows]
    result = {
        "mode": args.mode,
        "synthetic": args.synthetic,
        "n": len(rows),
        "calibration": {
            "accuracy": cal["accuracy"],
            "error_rates": cal["error_rates"],
            "ok": cal["ok"],
        },
        "confusion": {k: confusion(rows, k) for k in ("fused", "tracker", "local", "spark")},
        "latency_ms": {
            "median": statistics.median(lat),
            "p90": sorted(lat)[int(0.9 * (len(lat) - 1))],
            "max": max(lat),
        },
        "rows": rows,
    }
    (base / "results.json").write_text(json.dumps(result, indent=1))
    lines = [
        "# Detector evaluation",
        "",
        f"Mode `{args.mode}`, {len(rows)} clips at {settings.perception.fps} fps"
        f"{' (SYNTHETIC cartoon clips: not evidence about real patients)' if args.synthetic else ''}.",
        f"Calibration leave-one-out accuracy: {cal['accuracy']}; error rates {cal['error_rates']}.",
        f"Latency per answer window: median {result['latency_ms']['median']} ms, p90 {result['latency_ms']['p90']} ms.",
        "",
    ]
    for key in ("fused", "tracker", "local", "spark"):
        m = result["confusion"][key]
        if not any(sum(v.values()) for v in m.values()):
            continue
        lines += [
            f"## {key} (accuracy {accuracy(m):.2f})",
            "",
            "| true \\ predicted | " + " | ".join(CLASSES) + " |",
            "|---|" + "---:|" * len(CLASSES),
        ]
        lines += [f"| {t} | " + " | ".join(str(m[t][c]) for c in CLASSES) + " |" for t in m]
        lines.append("")
    out = ROOT / "docs" / ("DETECTOR_EVAL_SYNTHETIC.md" if args.synthetic else "DETECTOR_EVAL.md")
    out.write_text("\n".join(lines))
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
