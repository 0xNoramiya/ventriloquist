"""Learning curve: questions per confirmed message as personal memory accumulates.

Each simulated patient has their own habits (base rates skewed by a log-normal factor) and talks over
10 sessions of 5 messages, one session a day. Confirmed messages feed the personal base rates
(Dirichlet, 3-day half-life), exactly as in the live system. No room context, so the curve isolates
the effect of memory. Simulation, not clinical evidence.

    python -m sim.learning_curve [--patients 300] [--noise 0.05]
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import numpy as np

from app.engine.personal import ConfirmedMessage, personal_multipliers
from app.engine.policy import ActionKind, MessageDecider
from app.engine.priors import build_prior

from .simulate import NOW, World, answer


def run(
    patients: int, noise: float, sessions: int = 10, per_session: int = 5, seed: int = 11
) -> dict:
    world = World()
    cfg = world.cfg
    rng = np.random.default_rng(seed)
    curve = np.zeros((patients, sessions))
    for pi in range(patients):
        skew = rng.lognormal(0.0, 0.9, size=len(world.messages))
        dist = world.message_base * skew
        dist /= dist.sum()
        history: list[ConfirmedMessage] = []
        for si in range(sessions):
            now = NOW + timedelta(days=si)
            qs = []
            for _ in range(per_session):
                truth = world.messages[int(rng.choice(len(world.messages), p=dist))].id
                personal = (
                    personal_multipliers(
                        history,
                        world.base_rates,
                        now,
                        half_life_days=cfg.personal_half_life_days,
                        prior_strength=cfg.personal_prior_strength,
                    )
                    if history
                    else {}
                )
                prior, _ = build_prior(world.hyps, personal=personal)
                d = MessageDecider(
                    world.hyps, prior, world.questions, cfg, a=max(noise, 0.02), b=max(noise, 0.02)
                )
                act = d.next_action()
                while act.kind in (ActionKind.ASK, ActionKind.CONFIRM, ActionKind.OFFER_SPELL):
                    act = d.observe(answer(rng, truth in act.question.yes_ids, noise))
                qs.append(d.n_questions)
                if act.kind == ActionKind.FINALIZE and act.hypothesis.id == truth:
                    history.append(ConfirmedMessage(truth, now))
            curve[pi, si] = float(np.mean(qs))
    mean = curve.mean(axis=0)
    sem = curve.std(axis=0, ddof=1) / np.sqrt(patients)
    return {
        "patients": patients,
        "noise": noise,
        "sessions": sessions,
        "per_session": per_session,
        "mean_questions": mean.round(3).tolist(),
        "sem": sem.round(3).tolist(),
        "label": "simulation, not clinical evidence",
    }


def chart(result: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial"],
            "font.size": 10,
            "axes.edgecolor": "#c9c8c2",
            "axes.labelcolor": "#52514e",
            "xtick.color": "#52514e",
            "ytick.color": "#52514e",
            "text.color": "#0b0b0b",
            "svg.fonttype": "path",
        }
    )
    x = np.arange(1, result["sessions"] + 1)
    y = np.array(result["mean_questions"])
    e = np.array(result["sem"])
    fig, ax = plt.subplots(figsize=(6.4, 3.4), facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.fill_between(x, y - 1.96 * e, y + 1.96 * e, color="#2a78d6", alpha=0.15, linewidth=0)
    ax.plot(x, y, color="#2a78d6", linewidth=2, marker="o", markersize=5)
    ax.annotate(
        f"{y[0]:.2f}",
        (x[0], y[0]),
        textcoords="offset points",
        xytext=(0, 8),
        ha="center",
        fontsize=9,
    )
    ax.annotate(
        f"{y[-1]:.2f}",
        (x[-1], y[-1]),
        textcoords="offset points",
        xytext=(0, 8),
        ha="center",
        fontsize=9,
    )
    ax.set_xticks(x)
    ax.set_xlabel("Session (one a day, 5 messages each)")
    ax.set_ylabel("Mean questions per message")
    ax.set_title(
        f"Personal memory, no room context, noise {result['noise']:.0%} "
        f"({result['patients']} simulated patients)",
        fontsize=10,
        color="#52514e",
    )
    fig.tight_layout()
    fig.savefig(path, format="svg", facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=300)
    ap.add_argument("--noise", type=float, default=0.05)
    ap.add_argument("--out", type=Path, default=Path("docs"))
    args = ap.parse_args()
    result = run(args.patients, args.noise)
    (args.out / "learning_curve.json").write_text(json.dumps(result, indent=1))
    chart(result, args.out / "img" / "learning_curve.svg")
    print(" ".join(f"{v:.2f}" for v in result["mean_questions"]))


if __name__ == "__main__":
    main()
