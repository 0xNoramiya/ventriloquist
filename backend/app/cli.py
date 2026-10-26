"""Command-line demo: run a full session against a simulated patient, no browser and no keys needed.

python -m app.cli demo --scenario daughter          (make demo-mock)
python -m app.cli demo --scenario spelling --noise 0.05
python -m app.cli scenarios
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.perception.calibration import default_calibration
from app.providers.registry import Mode, ProviderHub
from app.roles import Roles
from app.scenarios import apply as apply_scenario
from app.scenarios import load as load_scenario
from app.scenarios import names as scenario_names
from app.sessions.session import AppContext, Session
from app.sessions.simulated import SimulatedPatient
from app.sessions.state_machine import State
from app.storage import Store, new_id

TERMINAL = {State.DONE, State.CAREGIVER_NEEDED, State.PAUSED, State.EMERGENCY}


def _bar(p: float, width: int = 20) -> str:
    n = int(round(p * width))
    return "#" * n + "." * (width - n)


async def run_demo(
    scenario_name: str,
    noise: float,
    seed: int,
    mode: str,
    data_dir: Path | None,
    quiet: bool = False,
) -> dict[str, Any]:
    if mode == "mock":
        os.environ["APP_MODE"] = "mock"
    settings = load_settings()
    if mode == "live":
        settings = settings.model_copy(update={"app_mode": "live"})
    store = Store(data_dir or settings.data_dir)
    hub = ProviderHub(settings, store)
    store.kv_set("app_mode", "live" if mode == "live" else "mock")
    ctx = AppContext(settings, store, hub, Roles(hub, settings))
    scenario = load_scenario(scenario_name)
    profile = dict(scenario["profile"])
    pid = store.create_patient(profile)
    patient = store.get_patient(pid)
    assert patient is not None
    sid = new_id("ses")
    store.create_session(sid, pid, mode)
    apply_scenario(store, scenario, pid, sid)
    sp = scenario.get("patient") or {}
    sim = SimulatedPatient(
        truth=sp.get("truth"),
        spell=sp.get("spell"),
        sentence_en=sp.get("sentence_en"),
        noise=noise,
        seed=seed,
    )
    printed: set[str] = set()

    def out(*a: Any) -> None:
        if not quiet:
            print(*a, flush=True)

    async def on_change(s: Session, event: dict[str, Any] | None) -> None:
        if event:
            out(f"  !! {event.get('type')}: {event.get('text', '')}")
        if s.trail and s.trail[-1]["prompt_id"] not in printed_answers:
            t = s.trail[-1]
            printed_answers.append(t["prompt_id"])
            out(f"       -> {t['answer'].upper():8s} (conf {t['confidence']:.2f}, {t['source']})")
        p = s.prompt
        if p and p.id not in printed:
            printed.add(p.id)
            if p.kind == "message":
                out(f"\n  >>> PHONE SAYS: \u201c{p.text}\u201d\n")
            else:
                extra = f"  [{' '.join(p.group)}]" if p.group else ""
                out(
                    f"  Q{s.questions_this_message:>2} ({p.kind}{'/' + p.sub if p.sub else ''}): {p.text}{extra}"
                )

    printed_answers: list[str] = []
    session = Session(
        sid,
        patient,
        default_calibration(mode, a=max(noise, 0.05), b=max(noise, 0.05)),
        ctx,
        mode=Mode(mode) if mode != "privacy" else Mode.PRIVACY,
        simulated=sim,
        scenario=scenario,
        on_change=on_change,
        strict=True,
    )
    out(
        f"Ventriloquist demo: scenario '{scenario_name}' ({scenario.get('title', '')}), mode={mode}, noise={noise}"
    )
    out(
        f"Patient: {profile['display_name']}, language={profile.get('language')}, family="
        f"{', '.join(f['name'] + ' (' + f['relation'] + ')' for f in profile.get('family', []))}"
    )
    t0 = time.time()
    await session.start()
    out("\n  Evidence:")
    for e in session.evidence.to_list():
        out(f"    {e['id']:4s} {e['text']}")
    out("\n  Prior (top 6, after bounded context multipliers):")
    for h in session._top_posterior(6):
        chips = ", ".join(f"{c['evidence_id']} x{c['factor']:g}" for c in h["chips"])
        out(
            f"    {h['p']:.3f} {_bar(h['p'])} {h['text_en']}  {('[' + chips + ']') if chips else ''}"
        )
    out("")
    deadline = time.time() + 120
    while session.state not in TERMINAL and time.time() < deadline:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    await session.end()
    confirmed = [m for m in session.messages if m.status == "confirmed"]
    result = {
        "scenario": scenario_name,
        "final_state": str(session.state),
        "confirmed": [m.text_en for m in confirmed],
        "retracted": [m.text_en for m in session.messages if m.status == "retracted"],
        "questions": confirmed[0].questions if confirmed else session.questions_this_message,
        "caregiver_reason": session.caregiver_reason,
        "log": str(session.log.path),
        "seconds": round(time.time() - t0, 2),
    }
    out(f"\n  Result: {json.dumps(result, indent=2)}")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ventriloquist")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="run a simulated session")
    d.add_argument("--scenario", default="daughter", choices=scenario_names())
    d.add_argument("--noise", type=float, default=0.0)
    d.add_argument("--seed", type=int, default=1)
    d.add_argument("--mode", default="mock", choices=["mock", "live", "privacy"])
    d.add_argument("--data-dir", type=Path, default=None)
    sub.add_parser("scenarios", help="list scenarios")
    args = ap.parse_args(argv)
    if args.cmd == "scenarios":
        for n in scenario_names():
            print(n, "-", load_scenario(n).get("title", ""))
        return 0
    result = asyncio.run(run_demo(args.scenario, args.noise, args.seed, args.mode, args.data_dir))
    return 0 if result["confirmed"] else 1


if __name__ == "__main__":
    sys.exit(main())
