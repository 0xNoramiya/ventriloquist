"""Engine simulation. Simulated patients, not clinical evidence.

For every cell (noise eps x context informativeness) we run N seeded trials per strategy:

* board                 - fixed-order manual board: categories in a fixed order, then items one by one
* random                - random informative question, same Bayesian bookkeeping and confirm policy
* eig                   - expected information gain, base-rate priors only
* eig_context           - EIG with evidence-cited context multipliers
* eig_context_personal  - EIG with context and personal memory (learned from 15 earlier messages)

A simulated patient answers truthfully, flipped with probability eps. Context: with some probability
the true message gets an evidence-backed multiplier, and distractor messages get multipliers too.

Usage:  python -m sim.simulate [--trials 2000] [--seed 7] [--out docs]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.engine.personal import ConfirmedMessage, personal_multipliers
from app.engine.policy import ActionKind, MessageDecider
from app.engine.priors import ContextMultiplier, build_prior
from app.engine.questions import Scored
from app.engine.taxonomy import Person, attribute_questions, build_hypotheses
from app.engine.types import Answer, Observation

STRATEGIES = ["board", "random", "eig", "eig_context", "eig_context_personal"]
NOISE = [0.0, 0.05, 0.10, 0.20]
CONTEXT = ["none", "weak", "strong"]
PERSONS = [Person("Aisyah", "daughter"), Person("Rizal", "son"), Person("Siti", "wife")]
BOARD_ORDER = [
    "body",
    "breathing_throat",
    "toilet",
    "environment",
    "information",
    "emotion",
    "people",
    "spiritual",
    "items",
]
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


@dataclass
class Outcome:
    finalized: bool
    correct: bool
    questions: int
    spelling: bool
    handover: bool


@dataclass
class CellResult:
    strategy: str
    noise: float
    context: str
    trials: int
    mean_q: float
    median_q: float
    success_rate: float
    wrong_rate: float
    spelling_rate: float
    handover_rate: float
    mean_q_success: float = field(default=0.0)


class World:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cfg = self.settings.engine
        self.hyps = build_hypotheses(self.settings.base_rates, PERSONS)
        self.ids = [h.id for h in self.hyps]
        self.questions = attribute_questions(self.hyps, PERSONS)
        self.messages = [h for h in self.hyps if not h.is_meta]
        base = np.array([h.base_rate for h in self.messages])
        self.message_base = base / base.sum()
        self.base_rates = {h.id: h.base_rate for h in self.hyps}


@dataclass
class Trial:
    truth: str
    multipliers: list[ContextMultiplier]
    history: list[ConfirmedMessage]


def sample_trial(world: World, rng: np.random.Generator, context: str) -> Trial:
    # Each simulated patient has their own habits: base rates skewed by a log-normal factor.
    skew = rng.lognormal(0.0, 0.9, size=len(world.messages))
    personal_dist = world.message_base * skew
    personal_dist /= personal_dist.sum()
    history = [
        ConfirmedMessage(
            world.messages[int(i)].id, NOW - timedelta(hours=float(rng.uniform(1, 120)))
        )
        for i in rng.choice(len(world.messages), size=15, p=personal_dist)
    ]
    truth = world.messages[int(rng.choice(len(world.messages), p=personal_dist))].id
    others = [h.id for h in world.messages if h.id != truth]
    mults: list[ContextMultiplier] = []
    if context == "weak":
        if rng.random() < 0.5:
            mults.append(ContextMultiplier(truth, 2.0, ("E1",), "sim evidence"))
        for d in rng.choice(others, size=3, replace=False):
            mults.append(ContextMultiplier(str(d), 2.0, ("E2",), "sim distractor"))
    elif context == "strong":
        if rng.random() < 0.8:
            mults.append(ContextMultiplier(truth, 4.0, ("E1",), "sim evidence"))
        for d in rng.choice(others, size=2, replace=False):
            mults.append(
                ContextMultiplier(
                    str(d),
                    4.0 if rng.random() < 0.3 else 2.0,
                    ("E2",),
                    "sim distractor",
                )
            )
    return Trial(truth, mults, history)


def answer(rng: np.random.Generator, truthful: bool, eps: float) -> Observation:
    flip = rng.random() < eps
    said_yes = truthful != flip
    return Observation(Answer.YES if said_yes else Answer.NO, 1.0 - eps)


def run_engine(
    world: World, trial: Trial, eps: float, strategy: str, rng: np.random.Generator
) -> Outcome:
    use_ctx = strategy in ("eig_context", "eig_context_personal")
    personal = None
    if strategy == "eig_context_personal":
        personal = personal_multipliers(
            trial.history,
            world.base_rates,
            NOW,
            half_life_days=world.cfg.personal_half_life_days,
            prior_strength=world.cfg.personal_prior_strength,
        )
    prior, _ = build_prior(
        world.hyps,
        personal=personal,
        multipliers=trial.multipliers if use_ctx else [],
        valid_evidence={"E1", "E2"},
    )
    selector: Callable[[list[Scored]], Scored] | None = None
    if strategy == "random":

        def selector(scored: list[Scored]) -> Scored:
            return scored[int(rng.integers(len(scored)))]

    d = MessageDecider(
        world.hyps, prior, world.questions, world.cfg, a=eps, b=eps, selector=selector
    )
    act = d.next_action()
    while act.kind in (ActionKind.ASK, ActionKind.CONFIRM, ActionKind.OFFER_SPELL):
        act = d.observe(answer(rng, trial.truth in act.question.yes_ids, eps))
    finalized = act.kind == ActionKind.FINALIZE
    return Outcome(
        finalized=finalized,
        correct=finalized and act.hypothesis.id == trial.truth,
        questions=d.n_questions,
        spelling=act.kind == ActionKind.ENTER_SPELLING,
        handover=act.kind in (ActionKind.CAREGIVER, ActionKind.PAUSE),
    )


def run_board(
    world: World, trial: Trial, eps: float, rng: np.random.Generator, cap: int
) -> Outcome:
    """A nurse with a printed board: 'Is it about <category>?' then each item, then confirm."""
    n = 0
    truth_domain = next(h.category for h in world.messages if h.id == trial.truth)
    for domain in BOARD_ORDER:
        items = [h for h in world.messages if h.category == domain]
        if not items:
            continue
        if n >= cap:
            return Outcome(False, False, n, False, True)
        n += 1
        if answer(rng, truth_domain == domain, eps).answer != Answer.YES:
            continue
        for item in items:
            if n >= cap:
                return Outcome(False, False, n, False, True)
            n += 1
            if answer(rng, item.id == trial.truth, eps).answer != Answer.YES:
                continue
            if n >= cap:
                return Outcome(False, False, n, False, True)
            n += 1  # "So your message is: ...?"
            if answer(rng, item.id == trial.truth, eps).answer == Answer.YES:
                return Outcome(True, item.id == trial.truth, n, False, False)
    return Outcome(False, False, n, True, False)


def summarise(strategy: str, eps: float, context: str, outcomes: list[Outcome]) -> CellResult:
    fin = [o.questions for o in outcomes if o.finalized]
    ok = [o.questions for o in outcomes if o.correct]
    n = len(outcomes)
    return CellResult(
        strategy=strategy,
        noise=eps,
        context=context,
        trials=n,
        mean_q=float(np.mean(fin)) if fin else float("nan"),
        median_q=float(statistics.median(fin)) if fin else float("nan"),
        success_rate=len(ok) / n,
        wrong_rate=sum(o.finalized and not o.correct for o in outcomes) / n,
        spelling_rate=sum(o.spelling for o in outcomes) / n,
        handover_rate=sum(o.handover for o in outcomes) / n,
        mean_q_success=float(np.mean(ok)) if ok else float("nan"),
    )


def run_cell(args: tuple[int, int, int, int]) -> list[CellResult]:
    trials, seed, ci, ni = args
    world = World()
    context, eps = CONTEXT[ci], NOISE[ni]
    # Same patients and truths for every strategy within a cell (paired comparison).
    trial_rng = np.random.default_rng([seed, ci, ni])
    cell_trials = [sample_trial(world, trial_rng, context) for _ in range(trials)]
    out: list[CellResult] = []
    for si, strategy in enumerate(STRATEGIES):
        rng = np.random.default_rng([seed, ci, ni, si, 1])
        outs = [
            run_board(world, t, eps, rng, world.cfg.max_questions)
            if strategy == "board"
            else run_engine(world, t, eps, strategy, rng)
            for t in cell_trials
        ]
        out.append(summarise(strategy, eps, context, outs))
    return out


def run(trials: int, seed: int, workers: int | None = None) -> list[CellResult]:
    cells = [(trials, seed, ci, ni) for ci in range(len(CONTEXT)) for ni in range(len(NOISE))]
    with ProcessPoolExecutor(max_workers=workers or min(len(cells), os.cpu_count() or 1)) as pool:
        return [r for cell in pool.map(run_cell, cells) for r in cell]


# ------------------------------------------------------------------ reporting
LABELS = {
    "board": "Fixed-order board",
    "random": "Random questions",
    "eig": "EIG, no context",
    "eig_context": "EIG + context",
    "eig_context_personal": "EIG + context + memory",
}
COLORS = {  # categorical slots 1-5 of the validated reference palette, fixed order
    "board": "#2a78d6",
    "random": "#eb6834",
    "eig": "#1baf7a",
    "eig_context": "#eda100",
    "eig_context_personal": "#e87ba4",
}


def write_charts(results: list[CellResult], img_dir: Path) -> list[str]:
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
    img_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for metric, ylabel, fname in (
        ("mean_q", "Mean questions (incl. confirmation)", "sim_mean_questions.svg"),
        ("success_rate", "Correct within 10 questions", "sim_success.svg"),
    ):
        fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True, facecolor="#fcfcfb")
        for ax, context in zip(axes, CONTEXT, strict=True):
            ax.set_facecolor("#fcfcfb")
            ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
            ax.set_axisbelow(True)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            for strategy in STRATEGIES:
                pts = [r for r in results if r.strategy == strategy and r.context == context]
                xs = [r.noise for r in pts]
                ys = [getattr(r, metric) * (100 if metric == "success_rate" else 1) for r in pts]
                ax.plot(
                    xs,
                    ys,
                    color=COLORS[strategy],
                    linewidth=2,
                    marker="o",
                    markersize=5,
                    linestyle="--" if strategy == "board" else "-",
                    label=LABELS[strategy],
                )
            ax.set_title(f"Context: {context}", fontsize=10, color="#0b0b0b")
            ax.set_xticks(NOISE)
            ax.set_xticklabels([f"{int(e * 100)}%" for e in NOISE])
            ax.set_xlabel("Answer noise (eps)")
        axes[0].set_ylabel(ylabel if metric == "mean_q" else ylabel + " (%)")
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="lower center", ncol=5, frameon=False, fontsize=9)
        fig.suptitle(
            "Simulation (simulated patients, not clinical evidence)",
            fontsize=10,
            color="#52514e",
        )
        fig.tight_layout(rect=(0, 0.08, 1, 0.95))
        path = img_dir / fname
        fig.savefig(path, format="svg", facecolor=fig.get_facecolor())
        plt.close(fig)
        written.append(str(path))
    return written


def learning_curve_section(docs: Path) -> list[str]:
    path = docs / "learning_curve.json"
    if not path.exists():
        return []
    lc = json.loads(path.read_text())
    m = lc["mean_questions"]
    return [
        "### Learning curve (personal memory)",
        "",
        f"`python -m sim.learning_curve`: {lc['patients']} simulated patients, {lc['sessions']} daily sessions of "
        f"{lc['per_session']} messages, noise {lc['noise']:.0%}, no room context. Confirmed messages feed the "
        "personal base rates (Dirichlet, 3-day half-life, factor clipped to [0.5, 3]). Mean questions per message "
        f"fall from **{m[0]:.2f}** in session 1 to **{m[-1]:.2f}** in session {lc['sessions']}. The effect is modest "
        "by design: the personal factor is bounded, and caregiver-approved memory facts (which act as room "
        "context in the live system) are not simulated here.",
        "",
        "![Learning curve](img/learning_curve.svg)",
        "",
    ]


def write_markdown(
    results: list[CellResult], path: Path, trials: int, seed: int, secs: float
) -> None:
    def num(x: float, fmt: str) -> str:
        return "n/a" if math.isnan(x) else format(x, fmt)

    def row(r: CellResult) -> str:
        return (
            f"| {LABELS[r.strategy]} | {num(r.mean_q, '.2f')} | {num(r.median_q, '.0f')} | {r.success_rate:.1%} | "
            f"{r.wrong_rate:.1%} | {r.spelling_rate:.1%} | {r.handover_rate:.1%} |"
        )

    lines = [
        "# Evaluation",
        "",
        "> **Simulation, not clinical evidence.** Simulated patients answer yes/no questions with a",
        "> fixed error rate. These numbers compare question-selection strategies under identical",
        "> conditions; they say nothing about real patients. Detector accuracy on real clips is",
        "> reported separately (section 2) once labeled clips are recorded.",
        "",
        "## 1. Engine simulation",
        "",
        f"Generated by `make sim` (`python -m sim.simulate --trials {trials} --seed {seed}`) in {secs:.0f} s.",
        f"{trials:,} seeded trials per cell; within a cell every strategy faces the same patients and the",
        "same true messages (paired comparison). Raw numbers: [`docs/sim_results.json`](sim_results.json).",
        "",
        "**Setup.** 30 messages (taxonomy v1 plus three family members from the profile). Each simulated",
        "patient has personal habits (base rates skewed by a log-normal factor, sigma 0.9) and 15 earlier",
        "confirmed messages. The true message is drawn from those habits. Answers flip with probability eps.",
        "Context: *weak* gives the true message a x2 evidence-backed multiplier half the time plus three x2",
        "distractors; *strong* gives it x4 80% of the time plus two distractors (x2, sometimes x4).",
        "All engine strategies use the same policy (confirm at 0.70, finalize at 0.95, cap of 10 questions",
        "including confirmations and the spelling offer). The board asks categories in a fixed order, then",
        "items one by one, then a confirmation; same cap.",
        "",
        "Columns: mean/median questions over finalized trials (including the confirmation); success = the",
        "correct message finalized within the cap; wrong = a wrong message finalized (before the post-speak",
        '"Did I say it right?" check, which gives the patient one more chance to retract it); spelling =',
        "fell back to spelling; handover = cap reached or paused for the caregiver.",
        "",
        "![Mean questions](img/sim_mean_questions.svg)",
        "",
        "![Success rate](img/sim_success.svg)",
        "",
    ]
    for context in CONTEXT:
        for eps in NOISE:
            lines += [
                f"### Context {context}, eps = {eps:.2f}",
                "",
                "| Strategy | Mean Q | Median Q | Success | Wrong | Spelling | Handover |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
            lines += [row(r) for r in results if r.context == context and r.noise == eps]
            lines.append("")
    key = {r.strategy: r for r in results if r.context == "strong" and r.noise == 0.10}
    verdict = key["eig_context"].mean_q < key["board"].mean_q
    lines += [
        "### Phase 1 definition of done",
        "",
        f"At eps = 0.10 with strong context, EIG + context needs **{key['eig_context'].mean_q:.2f}** mean questions",
        (
            f"vs **{key['board'].mean_q:.2f}** for the fixed-order board "
            f"({'PASS' if verdict else 'FAIL'}); success {key['eig_context'].success_rate:.1%} vs "
            f"{key['board'].success_rate:.1%}."
        ),
        "",
        *learning_curve_section(path.parent),
        "## 2. Detector evaluation",
        "",
        "See `scripts/eval_detector.py`. Real-patient numbers need labelled clips recorded by",
        "consenting participants in `data/labeled/{yes,no,rest,emergency}/` (gitignored); none are",
        "recorded yet. Results on generated clips of a fictional patient, in live and privacy mode,",
        "are in [`DETECTOR_DATA_GENERATED.md`](DETECTOR_DATA_GENERATED.md), and on cartoon clips in",
        "[`DETECTOR_EVAL_SYNTHETIC.md`](DETECTOR_EVAL_SYNTHETIC.md).",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=Path("docs"))
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    results = run(args.trials, args.seed)
    secs = time.time() - t0
    for r in results:
        print(
            f"{r.context:6s} eps={r.noise:.2f} {r.strategy:22s} meanQ={r.mean_q:5.2f} "
            f"success={r.success_rate:6.1%} wrong={r.wrong_rate:5.1%} spell={r.spelling_rate:5.1%}"
        )
    if args.no_report:
        return
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "sim_results.json").write_text(
        json.dumps(
            {
                "trials": args.trials,
                "seed": args.seed,
                "label": "simulation, not clinical evidence",
                "results": [asdict(r) for r in results],
            },
            indent=1,
        )
    )
    write_charts(results, args.out / "img")
    write_markdown(results, args.out / "EVAL.md", args.trials, args.seed, secs)
    print(f"wrote {args.out / 'EVAL.md'} in {secs:.0f}s")


if __name__ == "__main__":
    main()
