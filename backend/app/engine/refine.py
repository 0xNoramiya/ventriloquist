"""Optional pain refinement after "I'm in pain." is confirmed (brief 8.2).

Relay only: location and "worse than before" are passed on in the patient's words.
Nothing here assesses, scores or interprets the pain.
"""

from __future__ import annotations

import numpy as np

from .taxonomy import load_taxonomy
from .types import Hypothesis, HypothesisSource, Question, QuestionKind


def location_stage() -> tuple[list[Hypothesis], np.ndarray, list[Question]]:
    spec = load_taxonomy()["pain_refinement"]
    msg = spec["message"]
    hyps: list[Hypothesis] = []
    for loc in spec["locations"]:
        if loc["id"] == "elsewhere":
            text_en, text_id = "The pain is somewhere else.", "Sakitnya di tempat lain."
        else:
            text_en = msg["en"].format(loc=loc["en"])
            text_id = msg["id"].format(loc=loc["id_text"])
        hyps.append(
            Hypothesis(
                id=f"pain_loc:{loc['id']}",
                text_en=text_en,
                text_id=text_id,
                category="pain_location",
                attributes=frozenset(loc.get("groups", [])),
                source=HypothesisSource.TAXONOMY,
                direct_en=loc["direct_en"],
                direct_id=loc["direct_id"],
            )
        )
    questions: list[Question] = []
    for gid, g in spec["groups"].items():
        yes = frozenset(h.id for h in hyps if gid in h.attributes)
        questions.append(
            Question(id=f"pain_group:{gid}", text_en=g["en"], text_id=g["id"],
                     kind=QuestionKind.ATTRIBUTE, yes_ids=yes)
        )
    for h in hyps:
        questions.append(
            Question(id=f"direct:{h.id}", text_en=h.direct_en or "", text_id=h.direct_id or "",
                     kind=QuestionKind.ATTRIBUTE, yes_ids=frozenset({h.id}))
        )
    prior = np.full(len(hyps), 1.0 / len(hyps))
    return hyps, prior, questions


def offer_question() -> Question:
    spec = load_taxonomy()["pain_refinement"]["offer"]
    return Question(id="pain:offer", text_en=spec["en"], text_id=spec["id"],
                    kind=QuestionKind.META, yes_ids=frozenset({"refine"}))


def worse_question() -> Question:
    spec = load_taxonomy()["pain_refinement"]["worse_question"]
    return Question(id="pain:worse", text_en=spec["en"], text_id=spec["id"],
                    kind=QuestionKind.META, yes_ids=frozenset({"worse"}))


def worse_message() -> tuple[str, str]:
    spec = load_taxonomy()["pain_refinement"]["worse_message"]
    return spec["en"], spec["id"]
