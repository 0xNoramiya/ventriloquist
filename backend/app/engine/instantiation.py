"""Validation of LLM-proposed hypotheses (brief 8.3).

The prior builder may add at most 3 hypotheses, only from allowed templates, only with slot values
that appear in the profile, memory or transcript (and cited), and never in sensitive categories.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.safety.advice import message_problems

from .taxonomy import Person, instantiate, load_taxonomy
from .types import Hypothesis, HypothesisSource


@dataclass
class TemplateProposal:
    template: str
    slots: dict[str, str]
    evidence_ids: list[str] = field(default_factory=list)


def _mentions(value: str, texts: list[str]) -> bool:
    pattern = re.compile(rf"\b{re.escape(value.strip())}\b", re.I)
    return any(pattern.search(t) for t in texts)


def validate_instantiations(
    proposals: list[TemplateProposal],
    *,
    persons: list[Person],
    evidence: dict[str, str],
    existing_ids: set[str],
    max_new: int = 3,
    base_rate: float = 0.02,
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Return accepted hypotheses and rejected proposals with reasons."""
    allowed = set(load_taxonomy()["templates"])
    known_people = {p.name.lower(): p for p in persons}
    accepted: list[Hypothesis] = []
    rejected: list[dict[str, Any]] = []
    seen = set(existing_ids)
    for prop in proposals:
        why: list[str] = []
        cited = [e for e in prop.evidence_ids if e in evidence]
        cited_texts = [evidence[e] for e in cited]
        if prop.template not in allowed:
            why.append("template_not_allowed")
        if not cited:
            why.append("no_valid_evidence")
        hyp: Hypothesis | None = None
        if not why:
            try:
                if "name" in prop.slots:
                    name = prop.slots["name"].strip()
                    relation = prop.slots.get("relation", "").strip()
                    person = known_people.get(name.lower())
                    if person is None:
                        # A name not in the profile must be said in a cited transcript/memory entry.
                        if not relation or not _mentions(name, cited_texts):
                            why.append("slot_not_in_evidence")
                        else:
                            person = Person(name, relation)
                    elif not (_mentions(name, cited_texts) or _mentions(person.relation, cited_texts)):
                        why.append("slot_not_cited")
                    if person is not None and not why:
                        hyp = instantiate(prop.template, person=person, base_rate=base_rate,
                                          source=HypothesisSource.LLM, evidence_ids=tuple(cited))
                elif "item" in prop.slots:
                    item = prop.slots["item"].strip()
                    if not _mentions(item, cited_texts):
                        why.append("slot_not_in_evidence")
                    else:
                        hyp = instantiate(prop.template, item_en=item, item_id=prop.slots.get("item_id"),
                                          base_rate=base_rate, source=HypothesisSource.LLM,
                                          evidence_ids=tuple(cited))
                else:
                    why.append("missing_slots")
            except (KeyError, ValueError) as exc:
                why.append(f"bad_template:{exc}")
        if hyp is not None:
            problems = message_problems(hyp.text_en) + message_problems(hyp.text_id)
            if problems:
                why.extend(problems)
            elif hyp.id in seen:
                why.append("duplicate")
            elif len(accepted) >= max_new:
                why.append("over_limit")
        if why or hyp is None:
            rejected.append({"template": prop.template, "slots": prop.slots, "why": why or ["invalid"]})
            continue
        seen.add(hyp.id)
        accepted.append(hyp)
    return accepted, rejected
