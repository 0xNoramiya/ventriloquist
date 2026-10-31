"""Detector evaluation on labelled clips.

Put clips recorded with consenting participants in data/labeled/{yes,no,rest,emergency}/ (gitignored)
and a calibration for the same participant in data/labeled/calibration/{rest,yes,no,emergency}_*.{webm,mp4}.
The script calibrates on the calibration clips, then runs every labelled clip through the full
perception pipeline and reports a confusion matrix per source (tracker, local, spark) and fused,
plus latency statistics. Results go to docs/DETECTOR_EVAL.md and data/labeled/results.json.

    PYTHONPATH=backend:. backend/.venv/bin/python scripts/eval_detector.py [--mode mock|live|privacy]
        [--synthetic] [--data DIR --name NAME --note TEXT]

--mode privacy runs the server's privacy path: the judge is Muse Spark Open (Baseten, or Modal with
MODAL_SPARK_URL) and the tracker is self-hosted SAM (MODAL_SAM_URL) or the on-device optical flow.

--synthetic builds a tiny labelled set from the synthetic probe media so the script can be exercised
without recordings (those numbers say nothing about real patients).

--runs N scores every clip N times on one calibration. The judge is a language model and does not
always answer the same way, so a single pass over a small set reports luck as much as accuracy; the
report gives per-run numbers and their spread.
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
    src = {
        "yes": media / "face_yes_eyebrows.mp4",
        "no": media / "face_nod.mp4",
        "rest": media / "face_rest_blinks.mp4",
        "emergency": media / "face_emergency_eyebrows.mp4",
    }
    if not all(p.exists() for p in src.values()):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_probe_media.py")], check=True)
    for split, shifts in (
        ("calibration", (0.0, 0.25, 0.5)),
        ("eval", (0.1, 0.35, 0.6)),
    ):
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


def score(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Correct, confidently wrong, and "ask again" (unclear, or the source did not answer)."""
    correct = sum(r[key] == r["true"] for r in rows)
    unclear = sum(r[key] in ("unclear", None) for r in rows)
    return {
        "n": len(rows),
        "answered": len(rows) - unclear,
        "correct": correct,
        "wrong": len(rows) - correct - unclear,
        "unclear": unclear,
    }


def spread(values: list[int]) -> str:
    if min(values) == max(values):
        return str(values[0])
    return f"{statistics.mean(values):.1f} (range {min(values)}-{max(values)})"


def accuracy(m: dict[str, dict[str, int]]) -> float:
    total = sum(sum(v.values()) for v in m.values())
    return sum(m[t][t] for t in m) / total if total else 0.0


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="mock", choices=["mock", "live", "privacy"])
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--fps", type=int, help="override perception.fps (calibration and answers)")
    ap.add_argument("--data", type=Path, help="another labelled folder with the same layout")
    ap.add_argument(
        "--name",
        default="",
        help="report suffix, e.g. GENERATED -> DETECTOR_EVAL_GENERATED.md",
    )
    ap.add_argument(
        "--note",
        default="",
        help="one line describing the clips, printed in the report",
    )
    ap.add_argument(
        "--runs",
        type=int,
        default=1,
        help="score every clip this many times on one calibration, and report the spread",
    )
    ap.add_argument("--verbose", action="store_true", help="print each source's reading per clip")
    args = ap.parse_args()
    # privacy is a session toggle on live
    app_mode = "live" if args.mode == "privacy" else args.mode
    os.environ["APP_MODE"] = app_mode

    from app.config import load_settings
    from app.perception import calibration as calib
    from app.perception.pipeline import perceive
    from app.providers.registry import Mode, ProviderHub
    from app.roles import Roles
    from app.storage import Store

    base = args.data or (LABELED if not args.synthetic else ROOT / "data" / "labeled_synthetic")
    if args.synthetic:
        build_synthetic(base)
    cal_dir = base / "calibration"
    if not cal_dir.exists():
        print(f"No calibration clips in {cal_dir}. Record them first (see the module docstring).")
        return
    settings = load_settings().model_copy(update={"app_mode": app_mode})
    if args.fps:
        perception = settings.perception.model_copy(update={"fps": args.fps})
        settings = settings.model_copy(update={"perception": perception})
    work = base / "_work"
    store = Store(work / "data")
    store.kv_set("app_mode", app_mode)
    store.kv_set("keep_clips_for_evaluation", True)
    hub = ProviderHub(settings, store)
    roles = Roles(hub, settings)
    mode = Mode(args.mode)
    if args.verbose:
        print("mode:", hub.resolve(mode).to_dict())
    clips = {lab: sorted(cal_dir.glob(f"{lab}_*")) for lab in LABELS}
    cal = await calib.finalize(
        "eval", clips, work / "cal", hub=hub, roles=roles, settings=settings, mode=mode
    )
    if args.verbose:
        print("signal:", cal.get("signal_text"), "| SAM prompts:", cal.get("prompts"))
        print("judge crop:", cal.get("roi"), "from", cal.get("roi_source"))
    rows: list[dict[str, Any]] = []
    for run in range(1, args.runs + 1):
        if args.runs > 1:
            print(f"--- run {run} of {args.runs} ---")
        for label in LABELS:
            for clip in sorted((base / label).glob("*")) if (base / label).exists() else []:
                tmp = work / f"in_{clip.name}"
                shutil.copy(clip, tmp)
                perc = await perceive(
                    tmp, cal, work, hub=hub, roles=roles, settings=settings, mode=mode
                )
                sources = list(perc.sources)
                if perc.late is not None:  # early decision on the tracker: still score the judge
                    late = await perc.late
                    if late is not None:
                        sources.append(late)
                src = {s.name: (s.top[0] if s.ok else None) for s in sources}
                rows.append(
                    {
                        "run": run,
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
                print(
                    f"{clip.name:28s} true={rows[-1]['true']:9s} fused={rows[-1]['fused']:9s} {src}"
                )
                if args.verbose:
                    for x in sources:
                        d = x.to_dict()
                        keep = (
                            "top",
                            "p",
                            "distances",
                            "missing",
                            "repetitions",
                            "observed",
                            "error",
                        )
                        print("   ", x.name, {k: d[k] for k in keep if k in d})
    if not rows:
        print("No labelled clips found.")
        return
    lat = [r["latency_ms"] for r in rows]
    runs = [[r for r in rows if r["run"] == i] for i in range(1, args.runs + 1)]
    per_run = [
        {
            "run": i + 1,
            "fused": score(rs, "fused"),
            "judge": score(rs, "spark"),
            "latency_ms_median": statistics.median([r["latency_ms"] for r in rs]),
            "usd": round(sum(r["usd"] or 0 for r in rs), 4),
        }
        for i, rs in enumerate(runs)
        if rs
    ]
    result = {
        "mode": args.mode,
        "synthetic": args.synthetic,
        "runs": args.runs,
        "per_run": per_run,
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
        (
            f"Mode `{args.mode}`, {len(rows) // max(args.runs, 1)} clips"
            + (f" scored {args.runs} times ({len(rows)} judgments)" if args.runs > 1 else "")
            + f" at {settings.perception.fps} fps"
            + (
                " (SYNTHETIC cartoon clips: not evidence about real patients)"
                if args.synthetic
                else ""
            )
            + "."
        ),
        *([args.note] if args.note else []),
        f"Calibration leave-one-out accuracy: {cal['accuracy']}; error rates {cal['error_rates']}.",
        f"Latency per answer window: median {result['latency_ms']['median']} ms, p90 {result['latency_ms']['p90']} ms.",
        "",
    ]
    if args.runs > 1:
        clips_per_run = per_run[0]["fused"]["n"]
        lines += [
            f"## {args.runs} runs over the same {clips_per_run} clips",
            "",
            "One calibration, every clip scored again in each run. The blind judge is a language",
            "model and does not always answer the same way, so a single pass over a set this small",
            "reports luck as well as accuracy.",
            "",
            "| run | fused correct | wrong | ask again | judge correct / answered | median latency |",
            "|---|---:|---:|---:|---:|---:|",
            *[
                f"| {r['run']} | {r['fused']['correct']} | {r['fused']['wrong']} |"
                f" {r['fused']['unclear']} | {r['judge']['correct']} / {r['judge']['answered']} |"
                f" {r['latency_ms_median']:.0f} ms |"
                for r in per_run
            ],
            "",
            f"Fused correct {spread([r['fused']['correct'] for r in per_run])} of {clips_per_run};"
            f" confidently wrong {spread([r['fused']['wrong'] for r in per_run])};"
            f" ask again {spread([r['fused']['unclear'] for r in per_run])}.",
            "",
            "The matrices below pool every run, so each cell counts "
            f"{args.runs} judgments per clip.",
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
    suffix = f"_{args.name}" if args.name else ("_SYNTHETIC" if args.synthetic else "")
    out = ROOT / "docs" / f"DETECTOR_EVAL{suffix}.md"
    out.write_text("\n".join(lines))
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
