"""Taxonomy v1, attribute partitions and template instantiation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .types import META_OTHER, META_SPELL, Hypothesis, HypothesisSource, Question, QuestionKind

TAXONOMY_PATH = Path(__file__).with_name("taxonomy_v1.yaml")


@dataclass(frozen=True)
class Person:
    name: str
    relation: str

    @property
    def slug(self) -> str:
        return slugify(self.name)


def slugify(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", norm.lower()).strip("_") or "x"


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, Any]:
    return yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))


def relation_id(relation: str) -> str:
    return load_taxonomy()["relations"].get(relation.lower().strip(), relation)


def is_family(relation: str) -> bool:
    return relation.lower().strip() not in set(load_taxonomy()["non_family_relations"])


def taxonomy_ids() -> list[str]:
    return [h["id"] for h in load_taxonomy()["hypotheses"]]


def build_hypotheses(
    base_rates: dict[str, float],
    persons: list[Person] | tuple[Person, ...] = (),
    spiritual_preference: str | None = None,
) -> list[Hypothesis]:
    """Taxonomy hypotheses plus one `see_person:{slug}` per profile person."""
    tax = load_taxonomy()
    hyps: list[Hypothesis] = []
    for row in tax["hypotheses"]:
        text_en, text_id = row["en"], row["id_text"]
        if row["id"] == "pray" and spiritual_preference:
            text_en = f"I want to pray or hear prayers ({spiritual_preference})."
            text_id = f"Saya ingin berdoa atau mendengarkan doa ({spiritual_preference})."
        hyps.append(
            Hypothesis(
                id=row["id"],
                text_en=text_en,
                text_id=text_id,
                category=row["domain"],
                attributes=frozenset(row.get("attributes", [])),
                base_rate=float(base_rates.get(row["id"], 0.01)),
                urgent=bool(row.get("urgent", False)),
                source=HypothesisSource.TAXONOMY,
                direct_en=row.get("direct_en"),
                direct_id=row.get("direct_id"),
            )
        )
    if persons:
        share = float(base_rates.get("see_person", 0.05)) / len(persons)
        for person in persons:
            hyps.append(
                instantiate(
                    "see_person", person=person, base_rate=share, source=HypothesisSource.PROFILE
                )
            )
    return hyps


def instantiate(
    template: str,
    *,
    person: Person | None = None,
    item_en: str | None = None,
    item_id: str | None = None,
    base_rate: float = 0.02,
    source: HypothesisSource = HypothesisSource.LLM,
    evidence_ids: tuple[str, ...] = (),
) -> Hypothesis:
    """Build a hypothesis from an allowed template. Raises KeyError for unknown templates."""
    spec = load_taxonomy()["templates"][template]
    attrs = set(spec["attributes"])
    if person is not None:
        slots = {
            "name": person.name,
            "relation": person.relation,
            "relation_id": relation_id(person.relation),
        }
        if not is_family(person.relation):
            attrs.discard("family")
        attrs.add(f"person:{person.slug}")
        hid = f"{template}:{person.slug}"
    elif item_en:
        slots = {"item": item_en, "item_id": item_id or item_en}
        hid = f"{template}:{slugify(item_en)}"
    else:
        raise ValueError(f"template {template} needs a person or an item")
    return Hypothesis(
        id=hid,
        text_en=spec["en"].format(**slots),
        text_id=spec["id"].format(**slots),
        category="people" if person else "items",
        attributes=frozenset(attrs),
        base_rate=base_rate,
        source=source,
        evidence_ids=evidence_ids,
        direct_en=spec["direct_en"].format(**slots),
        direct_id=spec["direct_id"]
        .replace("{name}", slots.get("name", ""))
        .replace("{item_id}", slots.get("item_id", "")),
    )


def attribute_questions(
    hyps: list[Hypothesis], persons: list[Person] | tuple[Person, ...] = ()
) -> list[Question]:
    """Attribute partitions, per-person partitions and direct single-item questions."""
    tax = load_taxonomy()
    ids_by_attr: dict[str, set[str]] = {}
    for h in hyps:
        for a in h.attributes:
            ids_by_attr.setdefault(a, set()).add(h.id)
    questions: list[Question] = []
    for attr, spec in tax["attribute_questions"].items():
        yes = ids_by_attr.get(attr)
        if not yes:
            continue
        questions.append(
            Question(
                id=f"attr:{attr}",
                text_en=spec["en"],
                text_id=spec["id"],
                kind=QuestionKind.ATTRIBUTE,
                yes_ids=frozenset(yes),
                rephrase_en=spec.get("rephrase_en"),
                rephrase_id=spec.get("rephrase_id"),
            )
        )
    pq = tax["person_question"]
    for person in persons:
        yes = ids_by_attr.get(f"person:{person.slug}")
        if not yes:
            continue
        questions.append(
            Question(
                id=f"person:{person.slug}",
                text_en=pq["en"].format(name=person.name),
                text_id=pq["id"].format(name=person.name),
                kind=QuestionKind.ATTRIBUTE,
                yes_ids=frozenset(yes),
            )
        )
    for h in hyps:
        if h.direct_en and h.id != META_OTHER:
            questions.append(direct_question(h))
    return questions


def direct_question(h: Hypothesis) -> Question:
    return Question(
        id=f"direct:{h.id}",
        text_en=h.direct_en or h.text_en,
        text_id=h.direct_id or h.text_id,
        kind=QuestionKind.ATTRIBUTE,
        yes_ids=frozenset({h.id}),
        evidence_ids=h.evidence_ids,
    )


def confirm_question(h: Hypothesis) -> Question:
    spec = load_taxonomy()["confirm_question"]
    if h.direct_en and (h.is_meta or h.category == "control"):
        # "Do you want me to stop asking for now?" reads better than quoting "Stop asking for now."
        text_en, text_id = h.direct_en, h.direct_id or h.text_id
        re_en, re_id = text_en, text_id
    else:
        text_en = spec["en"].format(message=h.text_en)
        text_id = spec["id"].replace("{message}", h.text_id)
        re_en = spec["rephrase_en"].format(message=h.text_en)
        re_id = spec["rephrase_id"].replace("{message}", h.text_id)
    return Question(
        id=f"confirm:{h.id}",
        text_en=text_en,
        text_id=text_id,
        kind=QuestionKind.CONFIRM,
        yes_ids=frozenset({h.id}),
        target_id=h.id,
        rephrase_en=re_en,
        rephrase_id=re_id,
    )


def spell_offer_question() -> Question:
    spec = load_taxonomy()["meta_questions"]["spell"]
    return Question(
        id="meta:spell",
        text_en=spec["en"],
        text_id=spec["id"],
        kind=QuestionKind.META,
        yes_ids=frozenset({META_SPELL, META_OTHER}),
    )


def post_check_question() -> Question:
    spec = load_taxonomy()["post_check"]
    return Question(
        id="meta:post_check",
        text_en=spec["en"],
        text_id=spec["id"],
        kind=QuestionKind.META,
        yes_ids=frozenset({"said_right"}),
    )
