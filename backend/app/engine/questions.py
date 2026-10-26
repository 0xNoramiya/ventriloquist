"""Question candidates and selection (brief 8.4, 8.5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.safety.advice import question_problems

from .eig import eig
from .types import Question, QuestionKind

_KIND_PRIORITY = {QuestionKind.ATTRIBUTE: 0, QuestionKind.LLM: 1, QuestionKind.META: 2}


@dataclass
class LLMQuestionProposal:
    text_en: str
    text_id: str
    yes_ids: list[str]
    evidence_ids: list[str]


@dataclass
class Scored:
    question: Question
    s: float
    eig: float
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.question.id,
            "text_en": self.question.text_en,
            "kind": str(self.question.kind),
            "s": round(self.s, 4),
            "eig": round(self.eig, 4),
            "score": round(self.score, 4),
        }


def validate_llm_questions(
    proposals: list[LLMQuestionProposal],
    known_ids: set[str],
    existing: list[Question],
    max_questions: int = 5,
    max_words: int = 10,
) -> tuple[list[Question], list[dict[str, Any]]]:
    """Keep proposals whose yes-ids exist and whose wording passes the safety rules."""
    accepted: list[Question] = []
    rejected: list[dict[str, Any]] = []
    seen = {q.partition_key for q in existing}
    for i, prop in enumerate(proposals):
        problems = question_problems(prop.text_en, prop.text_id, max_words)
        yes = frozenset(prop.yes_ids)
        unknown = [y for y in yes if y not in known_ids]
        if unknown:
            problems.append(f"unknown_ids:{','.join(sorted(unknown))}")
        if not yes:
            problems.append("empty_yes_set")
        if yes in seen:
            problems.append("duplicate_partition")
        if len(accepted) >= max_questions:
            problems.append("over_limit")
        if problems:
            rejected.append({"text_en": prop.text_en, "problems": problems})
            continue
        seen.add(yes)
        accepted.append(
            Question(
                id=f"llm:{i}:{abs(hash((prop.text_en, yes))) % 10**8}",
                text_en=prop.text_en.strip(),
                text_id=prop.text_id.strip() or prop.text_en.strip(),
                kind=QuestionKind.LLM,
                yes_ids=yes,
                evidence_ids=tuple(prop.evidence_ids),
            )
        )
    return accepted, rejected


def yes_matrix(ids: list[str], questions: list[Question]) -> np.ndarray:
    """(n_questions, n_hypotheses) float matrix of yes-set membership."""
    index = {h: i for i, h in enumerate(ids)}
    mat = np.zeros((len(questions), len(ids)), dtype=float)
    for qi, q in enumerate(questions):
        for y in q.yes_ids:
            j = index.get(y)
            if j is not None:
                mat[qi, j] = 1.0
    return mat


def score_questions(
    posterior: np.ndarray,
    ids: list[str],
    questions: list[Question],
    a: float,
    b: float,
    lambda_words: float,
    mat: np.ndarray | None = None,
) -> list[Scored]:
    """EIG - lambda * word_count for every candidate, best first; ties prefer attribute questions."""
    if not questions:
        return []
    if mat is None:
        mat = yes_matrix(ids, questions)
    s = mat @ posterior
    gains = np.asarray(eig(s, a, b), dtype=float).reshape(-1)
    scored = [
        Scored(q, float(s[i]), float(gains[i]), float(gains[i] - lambda_words * q.word_count))
        for i, q in enumerate(questions)
    ]
    scored.sort(
        key=lambda x: (-round(x.score, 9), _KIND_PRIORITY.get(x.question.kind, 3), x.question.id)
    )
    return scored
