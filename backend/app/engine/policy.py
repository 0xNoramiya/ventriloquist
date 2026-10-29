"""Per-message decision policy (Safety rules 4, 8, 9).

`MessageDecider` owns the posterior for one message and decides the next action:
ask the most informative question, confirm the leading message, offer spelling, finalize,
or hand over to the caregiver. It is pure (no I/O) so the simulator and the live session
share exactly the same logic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from app.config import EngineConfig

from .posterior import bayes_update, confirm_no, effective_error_rates, normalize, to_dict
from .questions import Scored, score_questions, yes_matrix
from .taxonomy import confirm_question, spell_offer_question
from .types import (
    META_OTHER,
    META_SPELL,
    META_STOP,
    Answer,
    Hypothesis,
    Observation,
    Question,
    QuestionKind,
)


class ActionKind(StrEnum):
    ASK = "ask"
    CONFIRM = "confirm"
    OFFER_SPELL = "offer_spell"
    ENTER_SPELLING = "enter_spelling"
    FINALIZE = "finalize"
    PAUSE = "pause"
    CAREGIVER = "caregiver"
    EMERGENCY = "emergency"


QUESTION_ACTIONS = {ActionKind.ASK, ActionKind.CONFIRM, ActionKind.OFFER_SPELL}


@dataclass
class Action:
    kind: ActionKind
    question: Question | None = None
    hypothesis: Hypothesis | None = None
    reason: str = ""
    rephrased: bool = False
    candidates: list[Scored] = field(default_factory=list)

    def to_dict(self, lang: str = "en", honorific: str = "Anda") -> dict[str, Any]:
        return {
            "kind": str(self.kind),
            "question": self.question.to_dict(lang, honorific) if self.question else None,
            "text": self.question.text(lang, honorific, self.rephrased) if self.question else None,
            "hypothesis": self.hypothesis.to_dict() if self.hypothesis else None,
            "reason": self.reason,
            "rephrased": self.rephrased,
            "candidates": [c.to_dict() for c in self.candidates[:5]],
        }


@dataclass
class Turn:
    question: Question
    observation: Observation
    rephrased: bool
    a_eff: float
    b_eff: float
    posterior_after: dict[str, float]


class MessageDecider:
    def __init__(
        self,
        hyps: list[Hypothesis],
        prior: np.ndarray,
        questions: list[Question],
        cfg: EngineConfig,
        a: float | None = None,
        b: float | None = None,
        selector: Callable[[list[Scored]], Scored] | None = None,
    ) -> None:
        if len(hyps) != len(prior):
            raise ValueError("prior length must match hypotheses")
        self.hyps = hyps
        self.ids = [h.id for h in hyps]
        self.index = {h: i for i, h in enumerate(self.ids)}
        self.cfg = cfg
        self.a = cfg.default_error_rates["a"] if a is None else a
        self.b = cfg.default_error_rates["b"] if b is None else b
        self.prior = normalize(np.asarray(prior, dtype=float))
        self.p = self.prior.copy()
        self.pool: list[Question] = list(questions)
        self.asked_ids: set[str] = set()
        self.asked_partitions: set[frozenset[str]] = set()
        self.reasked: set[str] = set()
        self.confirm_counts: dict[str, int] = {}
        self.n_questions = 0
        self.unclear_streak = 0
        self.confirm_no_high = 0
        self.spell_offers = 0
        self.pending: Action | None = None
        self.turns: list[Turn] = []
        self.finalized: Hypothesis | None = None
        self.selector = selector
        self._mat: np.ndarray | None = None

    def hypothesis(self, hid: str) -> Hypothesis:
        return self.hyps[self.index[hid]]

    def posterior(self) -> dict[str, float]:
        return to_dict(self.p, self.ids)

    def top(self, k: int = 8) -> list[tuple[Hypothesis, float]]:
        order = np.argsort(-self.p, kind="stable")[:k]
        return [(self.hyps[i], float(self.p[i])) for i in order]

    def _mask(self, yes_ids: frozenset[str]) -> np.ndarray:
        mask = np.zeros(len(self.ids), dtype=bool)
        for y in yes_ids:
            j = self.index.get(y)
            if j is not None:
                mask[j] = True
        return mask

    def _p(self, hid: str) -> float:
        j = self.index.get(hid)
        return float(self.p[j]) if j is not None else 0.0

    def _set(self, action: Action) -> Action:
        self.pending = action
        return action

    def _ask(
        self, kind: ActionKind, question: Question, *, rephrased: bool = False, **kw: Any
    ) -> Action:
        self.n_questions += 1
        if question.kind != QuestionKind.CONFIRM:
            self.asked_ids.add(question.id)
            self.asked_partitions.add(question.partition_key)
        return self._set(Action(kind, question=question, rephrased=rephrased, **kw))

    def _confirm(self, h: Hypothesis) -> Action:
        n = self.confirm_counts.get(h.id, 0)
        self.confirm_counts[h.id] = n + 1
        return self._ask(ActionKind.CONFIRM, confirm_question(h), hypothesis=h, rephrased=n > 0)

    def _offer_spell(self, reason: str) -> Action:
        self.spell_offers += 1
        return self._ask(ActionKind.OFFER_SPELL, spell_offer_question(), reason=reason)

    def next_action(self) -> Action:
        cfg = self.cfg
        if self.n_questions >= cfg.max_questions:
            return self._set(Action(ActionKind.CAREGIVER, reason="question_cap"))
        top_h, p_top = self.top(1)[0]
        if p_top >= cfg.tau_confirm:
            if top_h.id != META_OTHER:
                return self._confirm(top_h)
            if self.spell_offers < 2:
                return self._offer_spell("other_likely")
            return self._set(Action(ActionKind.CAREGIVER, reason="no_match"))
        p_other = self._p(META_OTHER) + self._p(META_SPELL)
        if self.spell_offers == 0 and (
            p_other >= cfg.offer_spell_other
            or (self.n_questions >= cfg.offer_spell_after and p_top < 0.5)
        ):
            return self._offer_spell(
                "other_likely" if p_other >= cfg.offer_spell_other else "slow_progress"
            )
        if self._mat is None:
            self._mat = yes_matrix(self.ids, self.pool)
        keep = [
            i
            for i, q in enumerate(self.pool)
            if q.id not in self.asked_ids and q.partition_key not in self.asked_partitions
        ]
        scored = [
            s
            for s in score_questions(
                self.p,
                self.ids,
                [self.pool[i] for i in keep],
                self.a,
                self.b,
                cfg.lambda_words,
                mat=self._mat[keep] if keep else None,
            )
            if s.eig > 1e-4
        ]
        if scored:
            choice = self.selector(scored) if self.selector else scored[0]
            return self._ask(ActionKind.ASK, choice.question, candidates=scored[:5])
        if p_top >= 0.3 and top_h.id != META_OTHER:
            return self._confirm(top_h)
        if self.spell_offers < 2:
            return self._offer_spell("no_questions_left")
        return self._set(Action(ActionKind.CAREGIVER, reason="no_questions_left"))

    def observe(self, obs: Observation) -> Action:
        act = self.pending
        if act is None or act.question is None:
            raise RuntimeError("no pending question to observe")
        q = act.question
        if obs.answer == Answer.EMERGENCY:
            return Action(ActionKind.EMERGENCY, question=q, reason="emergency_signal")

        if obs.answer in (Answer.UNCLEAR, Answer.NONE):
            self.unclear_streak += 1
            self._record(q, obs, act.rephrased, 0.0, 0.0)
            if self.unclear_streak >= self.cfg.unclear_pause_after:
                return self._set(Action(ActionKind.CAREGIVER, question=q, reason="unclear"))
            if q.id not in self.reasked and self.n_questions < self.cfg.max_questions:
                self.reasked.add(q.id)
                self.n_questions += 1
                return self._set(
                    Action(
                        act.kind if act.kind in QUESTION_ACTIONS else ActionKind.ASK,
                        question=q,
                        hypothesis=act.hypothesis,
                        rephrased=True,
                        reason="reask",
                    )
                )
            return self._set(Action(ActionKind.CAREGIVER, question=q, reason="tap_answer"))

        self.unclear_streak = 0
        a_eff, b_eff = effective_error_rates(obs, self.a, self.b, tuple(self.cfg.eps_clip))
        mask = self._mask(q.yes_ids)

        if q.kind == QuestionKind.CONFIRM and q.target_id in self.index:
            i = self.index[q.target_id]
            p_before = float(self.p[i])
            if obs.answer == Answer.YES:
                self.p = bayes_update(self.p, mask, Answer.YES, a_eff, b_eff)
                self._record(q, obs, act.rephrased, a_eff, b_eff)
                if self.p[i] >= self.cfg.finalize_threshold:
                    h = self.hyps[i]
                    if h.id in (META_SPELL, META_OTHER):
                        return self._set(
                            Action(ActionKind.ENTER_SPELLING, hypothesis=h, reason="confirmed")
                        )
                    if h.id == META_STOP:
                        return self._set(
                            Action(ActionKind.PAUSE, hypothesis=h, reason="patient_asked")
                        )
                    self.finalized = h
                    return self._set(Action(ActionKind.FINALIZE, hypothesis=h, reason="confirmed"))
            else:
                self.p = confirm_no(self.p, i, self.cfg.confirm_no_factor)
                self._record(q, obs, act.rephrased, a_eff, b_eff)
                if p_before >= self.cfg.confirm_no_pause_min_p:
                    self.confirm_no_high += 1
                    if self.confirm_no_high >= self.cfg.confirm_no_pause_after:
                        return self._set(Action(ActionKind.CAREGIVER, reason="inconsistent"))
            return self.next_action()

        if q.kind == QuestionKind.META and q.id == "meta:spell" and obs.answer == Answer.YES:
            self._record(q, obs, act.rephrased, a_eff, b_eff)
            return self._set(Action(ActionKind.ENTER_SPELLING, reason="patient_chose_spelling"))

        self.p = bayes_update(self.p, mask, obs.answer, a_eff, b_eff)
        self._record(q, obs, act.rephrased, a_eff, b_eff)
        return self.next_action()

    def retract(self, hid: str) -> Action:
        """Post-speak check answered NO: mark down the message and continue the conversation."""
        if hid in self.index:
            self.p = confirm_no(self.p, self.index[hid], self.cfg.confirm_no_factor)
        self.finalized = None
        return self.next_action()

    def skip(self) -> Action:
        """Caregiver skipped the pending question: no update, move on."""
        return self.next_action()

    def _record(
        self, q: Question, obs: Observation, rephrased: bool, a_eff: float, b_eff: float
    ) -> None:
        self.turns.append(Turn(q, obs, rephrased, a_eff, b_eff, self.posterior()))
