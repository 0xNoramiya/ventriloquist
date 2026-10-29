"""Live end-to-end check: exercise every model role through the real adapters.

Parts (default: all):
  roles       Spark: framing, scene, prior builder, question proposer, completer, sentences,
              sensitive classifier; Wonder: memory selector
  perception  calibration on synthetic clips (Spark describer, SAM 3.1 tracks, blind judge LOO)
              plus one answer window through the full perception pipeline
  session     the 'daughter' and 'spelling' scenarios with a simulated patient (answers are typed,
              so this measures context + question latency, not perception), questions per message
  memory      Wonder curator over the resulting stay history

Needs MODEL_API_KEY. Synthetic media comes from scripts/make_probe_media.py (data/probe_media/).
Writes docs/LIVE_CHECK.md and data/live_check/live_check.json. Typical cost: well under $0.50.

    PYTHONPATH=backend:. backend/.venv/bin/python scripts/live_check.py [--part roles]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
os.environ["APP_MODE"] = "live"

from app.config import load_settings  # noqa: E402
from app.memory import curator  # noqa: E402
from app.perception import calibration as calib  # noqa: E402
from app.perception.pipeline import perceive  # noqa: E402
from app.providers.registry import Mode, ProviderHub  # noqa: E402
from app.roles import Roles  # noqa: E402
from app.storage import Store  # noqa: E402

MEDIA = ROOT / "data" / "probe_media"
OUT = ROOT / "data" / "live_check"


def ensure_media() -> None:
    if not (MEDIA / "face_yes_eyebrows.mp4").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_probe_media.py")], check=True)


def variant(src: Path, dst: Path, shift: float, speed: float = 1.0) -> Path:
    """Slightly different repetitions of a synthetic clip (time shift + speed) for leave-one-out."""
    if not dst.exists():
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{shift:.2f}",
                "-i",
                str(src),
                "-vf",
                f"setpts={1 / speed:.3f}*PTS",
                "-t",
                "4",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(dst),
            ],
            check=True,
        )
    return dst


async def part_roles(hub: ProviderHub, roles: Roles, report: dict[str, Any]) -> None:
    evidence = [
        {
            "id": "T1",
            "kind": "transcript",
            "text": "Nurse: Your daughter Aisyah went home to rest, she'll be back at four.",
            "minutes_ago": 12,
        },
        {
            "id": "S1",
            "kind": "scene",
            "text": "A family photo stands on the bedside table; the patient is gazing toward it.",
        },
        {
            "id": "E1",
            "kind": "event",
            "text": "Visitor left (10 min ago)",
            "minutes_ago": 10,
            "event_kind": "visitor_left",
        },
        {
            "id": "E2",
            "kind": "event",
            "text": "Suctioned (20 min ago)",
            "minutes_ago": 20,
            "event_kind": "suctioned",
        },
        {
            "id": "E3",
            "kind": "event",
            "text": "Repositioned (3.0 h ago)",
            "minutes_ago": 180,
            "event_kind": "repositioned",
        },
    ]
    from app.engine.taxonomy import Person, build_hypotheses

    persons = [
        Person("Aisyah", "daughter"),
        Person("Rizal", "son"),
        Person("Siti", "wife"),
    ]
    hyps = [
        {"id": h.id, "text_en": h.text_en, "category": h.category}
        for h in build_hypotheses(hub.settings.base_rates, persons)
    ]
    people = [{"name": p.name, "relation": p.relation} for p in persons]
    calls = {
        "framing_check": roles.framing_check(Mode.LIVE, MEDIA / "face_still.png"),
        "scene_reader": roles.read_scene(Mode.LIVE, MEDIA / "hospital_room.png"),
        "prior_builder": roles.build_prior(Mode.LIVE, evidence, hyps, people),
        "question_proposer": roles.propose_questions(Mode.LIVE, evidence, hyps, []),
        "spelling_completer": roles.complete_word(Mode.LIVE, "KU", "KU", "id", evidence),
        "sentence_builder": roles.build_sentences(Mode.LIVE, "KUCING", "id", evidence, people),
        "sensitive_classifier": roles.classify_sensitive(Mode.LIVE, "SAYA MAU PULANG PAKSA"),
    }
    results = await asyncio.gather(*calls.values())
    for name, res in zip(calls, results, strict=True):
        report["roles"][name] = {
            "ok": res.ok,
            "meta": res.meta.to_dict(),
            "data": res.data.model_dump(),
        }
        print(
            f"  {name:22s} ok={res.ok} {res.meta.latency_ms:7.0f} ms ${res.meta.usd:.4f}  "
            f"{json.dumps(res.data.model_dump(), ensure_ascii=False)[:160]}"
        )


async def part_perception(
    hub: ProviderHub, roles: Roles, settings: Any, report: dict[str, Any]
) -> None:
    work = OUT / "perception"
    work.mkdir(parents=True, exist_ok=True)
    clips = {
        "rest": [MEDIA / "face_rest_blinks.mp4"],
        "yes": [
            variant(MEDIA / "face_yes_eyebrows.mp4", work / f"yes_{i}.mp4", s, sp)
            for i, (s, sp) in enumerate([(0.0, 1.0), (0.2, 1.1), (0.4, 0.95)])
        ],
        "no": [
            variant(MEDIA / "face_nod.mp4", work / f"no_{i}.mp4", s, sp)
            for i, (s, sp) in enumerate([(0.0, 1.0), (0.2, 1.1), (0.4, 0.95)])
        ],
    }
    t0 = time.perf_counter()
    cal = await calib.finalize(
        "live_check",
        clips,
        work / "cal",
        hub=hub,
        roles=roles,
        settings=settings,
        mode=Mode.LIVE,
        hint="eyebrows",
    )
    secs = time.perf_counter() - t0
    print(
        f"  calibration {secs:.1f}s ok={cal['ok']} accuracy={cal['accuracy']} rates={cal['error_rates']}"
    )
    print(f"  YES: {cal['description']['yes']}\n  NO:  {cal['description']['no']}")
    report["calibration"] = {
        k: v for k, v in cal.items() if k not in ("tracker", "local", "overlay")
    }
    report["calibration"]["seconds"] = round(secs, 1)
    windows = []
    for label, src in (
        ("yes", MEDIA / "face_yes_eyebrows.mp4"),
        ("no", MEDIA / "face_nod.mp4"),
        ("none", MEDIA / "face_rest_blinks.mp4"),
    ):
        tmp = work / f"answer_{label}.mp4"
        tmp.write_bytes(src.read_bytes())
        perc = await perceive(
            tmp, cal, work, hub=hub, roles=roles, settings=settings, mode=Mode.LIVE
        )
        obs = perc.observation
        windows.append(
            {
                "true": label,
                "answer": str(obs.answer),
                "confidence": round(obs.confidence, 3),
                "latency_ms": round(perc.latency_ms),
                "usd": round(perc.usd, 4),
                "sources": {s.name: s.to_dict() for s in perc.sources},
            }
        )
        print(
            f"  window true={label:4s} -> {obs.answer!s:8s} conf={obs.confidence:.2f} "
            f"{perc.latency_ms:6.0f} ms  sources={[(s.name, s.top) for s in perc.sources]}"
        )
    report["windows"] = windows


async def part_session(report: dict[str, Any], data_dir: Path) -> None:
    from app.cli import run_demo

    for scenario in ("daughter", "spelling"):
        t0 = time.perf_counter()
        res = await run_demo(scenario, 0.0, 1, "live", data_dir, quiet=True)
        res["wall_s"] = round(time.perf_counter() - t0, 1)
        lines = [json.loads(x) for x in Path(res["log"]).read_text().splitlines()]
        calls = [x for x in lines if x["event"] == "llm_call"]
        res["llm_calls"] = [
            {k: c.get(k) for k in ("role", "model", "latency_ms", "usd", "fallback")} for c in calls
        ]
        report["sessions"][scenario] = res
        print(
            f"  {scenario}: {res['confirmed']} questions={res['questions']} wall={res['wall_s']}s "
            f"calls={[(c['role'], round(c['latency_ms'] or 0)) for c in res['llm_calls']]}"
        )


async def part_memory(roles: Roles, store: Store, report: dict[str, Any]) -> None:
    patients = store.list_patients()
    if not patients:
        print("  no patients (run the session part first)")
        return
    out = []
    for p in patients[:2]:
        res = await curator.curate(store, roles, p["id"], Mode.LIVE)
        ops = store.memory_ops(p["id"], "pending")
        out.append(
            {
                "patient": p["display_name"],
                "result": res,
                "ops": [{k: o[k] for k in ("op", "text", "category", "reason")} for o in ops],
            }
        )
        print(
            f"  curator for {p['display_name']}: proposed={res['proposed']} rejected={len(res['rejected'])} "
            f"ops={[o['text'] for o in ops][:3]}"
        )
    report["memory"] = out


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Live check",
        "",
        (
            f"Last run {report['started']} with `scripts/live_check.py` against the real Meta Model API "
            f"(`APP_MODE=live`). Fictional patients and synthetic media only. Cost of the last run: "
            f"${report['spend_usd']:.3f}; all live-check runs in this data directory: "
            f"${report.get('spend_total_usd', report['spend_usd']):.3f}."
        ),
        "",
    ]
    if report["roles"]:
        lines += [
            "## Model roles",
            "",
            "| role | ok | latency (ms) | cost (USD) | output (truncated) |",
            "|---|---|---:|---:|---|",
        ]
        for name, r in report["roles"].items():
            out = json.dumps(r["data"], ensure_ascii=False)[:140].replace("|", "/")
            lines.append(
                f"| {name} | {r['ok']} | {r['meta']['latency_ms']:.0f} | {r['meta']['usd']:.4f} | `{out}` |"
            )
        lines.append("")
    if report.get("calibration"):
        c = report["calibration"]
        lines += [
            "## Calibration on synthetic clips",
            "",
            (
                f"- Muse Spark description: YES = {c['description']['yes']['motion']} ({c['description']['yes']['sam_prompt']}); "
                f"NO = {c['description']['no']['motion']} ({c['description']['no']['sam_prompt']}); distinct = {c['description']['distinct']}"
            ),
            f"- Leave-one-out accuracy: {c['accuracy']}; error rates {c['error_rates']}; ok = {c['ok']}; {c['seconds']} s",
            "",
        ]
    if report.get("windows"):
        lines += [
            "## Answer windows (full perception pipeline)",
            "",
            "| true | fused answer | confidence | latency (ms) | cost | sources |",
            "|---|---|---:|---:|---:|---|",
        ]
        for w in report["windows"]:
            src = ", ".join(f"{k}: {v['top']} {v['p']}" for k, v in w["sources"].items())
            lines.append(
                f"| {w['true']} | {w['answer']} | {w['confidence']} | {w['latency_ms']} | {w['usd']} | {src} |"
            )
        lines.append("")
    if report["sessions"]:
        lines += ["## Sessions (simulated patient answers, live context models)", ""]
        for name, s in report["sessions"].items():
            lines.append(
                f"- **{name}**: confirmed {s['confirmed']} in {s['questions']} questions; wall time {s['wall_s']} s; "
                f"model calls: "
                + ", ".join(
                    f"{c['role']} {c['latency_ms']:.0f} ms"
                    for c in s["llm_calls"]
                    if c["latency_ms"]
                )
            )
        lines.append("")
    if report.get("memory"):
        lines += ["## Memory curator (Muse Wonder)", ""]
        for m in report["memory"]:
            lines.append(
                f"- {m['patient']}: {m['result']['proposed']} proposed; "
                + "; ".join(o["text"] for o in m["ops"][:4])
            )
        lines.append("")
    (ROOT / "docs" / "LIVE_CHECK.md").write_text("\n".join(lines))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", action="append", choices=["roles", "perception", "session", "memory"])
    args = ap.parse_args()
    parts = args.part or ["roles", "perception", "session", "memory"]
    settings = load_settings().model_copy(update={"app_mode": "live"})
    if not settings.model_api_key:
        print("MODEL_API_KEY not set; skipping live check.")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    data_dir = OUT / "data"
    store = Store(data_dir)
    store.kv_set("app_mode", "live")
    hub = ProviderHub(settings, store)
    roles = Roles(hub, settings)
    ensure_media()
    report: dict[str, Any] = {"roles": {}, "sessions": {}}
    previous = OUT / "live_check.json"
    if previous.exists():  # keep results of parts not re-run this time
        report.update(json.loads(previous.read_text()))
    report["started"] = datetime.now(UTC).isoformat(timespec="seconds")
    if "roles" in parts:
        report["roles"] = {}
    if "session" in parts:
        report["sessions"] = {}
    spent0 = store.total_spend()
    if "roles" in parts:
        print("roles:")
        await part_roles(hub, roles, report)
    if "perception" in parts:
        print("perception:")
        await part_perception(hub, roles, settings, report)
    if "session" in parts:
        print("session:")
        await part_session(report, data_dir)
    if "memory" in parts:
        print("memory:")
        await part_memory(roles, Store(data_dir), report)
    report["spend_usd"] = Store(data_dir).total_spend() - spent0
    report["spend_total_usd"] = Store(data_dir).total_spend()
    (OUT / "live_check.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False, default=str)
    )
    write_markdown(report)
    print(f"spend this run: ${report['spend_usd']:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
