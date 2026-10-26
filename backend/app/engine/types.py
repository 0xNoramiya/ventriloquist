"""Core engine types (brief Section 8.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Answer(StrEnum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"
    EMERGENCY = "emergency"
    NONE = "none"


class QuestionKind(StrEnum):
    ATTRIBUTE = "attribute"
    LLM = "llm"
    CONFIRM = "confirm"
    SPELLING = "spelling"
    META = "meta"


class HypothesisSource(StrEnum):
    TAXONOMY = "taxonomy"
    PROFILE = "profile"
    LLM = "llm"
    SPELLING = "spelling"


# Hypotheses that steer the conversation rather than carry a message.
META_OTHER = "other"
META_SPELL = "spell"
META_STOP = "stop"
META_IDS = frozenset({META_OTHER, META_SPELL, META_STOP})


@dataclass
class Hypothesis:
    id: str
    text_en: str
    text_id: str
    category: str
    attributes: frozenset[str] = frozenset()
    base_rate: float = 0.01
    urgent: bool = False
    source: HypothesisSource = HypothesisSource.TAXONOMY
    evidence_ids: tuple[str, ...] = ()
    direct_en: str | None = None  # natural single-item question, e.g. "Are you thirsty?"
    direct_id: str | None = None

    @property
    def is_meta(self) -> bool:
        return self.id in META_IDS

    def text(self, lang: str) -> str:
        return self.text_id if lang == "id" else self.text_en

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text_en": self.text_en,
            "text_id": self.text_id,
            "category": self.category,
            "attributes": sorted(self.attributes),
            "base_rate": self.base_rate,
            "urgent": self.urgent,
            "source": str(self.source),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass
class Question:
    id: str
    text_en: str
    text_id: str
    kind: QuestionKind
    yes_ids: frozenset[str]
    target_id: str | None = None  # for confirmations
    rephrase_en: str | None = None
    rephrase_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    group: tuple[str, ...] = ()  # spelling: the highlighted symbols

    @property
    def word_count(self) -> int:
        return len(self.text_en.split())

    @property
    def partition_key(self) -> frozenset[str]:
        return self.yes_ids

    def text(self, lang: str, honorific: str = "Anda", rephrased: bool = False) -> str:
        if lang == "id":
            raw = (
                self.rephrase_id if rephrased and self.rephrase_id else self.text_id
            ) or self.text_en
        else:
            raw = self.rephrase_en if rephrased and self.rephrase_en else self.text_en
        return render(raw, honorific)

    def to_dict(self, lang: str = "en", honorific: str = "Anda") -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": str(self.kind),
            "text_en": render(self.text_en, honorific),
            "text_id": render(self.text_id, honorific),
            "text": self.text(lang, honorific),
            "yes_ids": sorted(self.yes_ids),
            "target_id": self.target_id,
            "word_count": self.word_count,
            "evidence_ids": list(self.evidence_ids),
            "group": list(self.group),
        }


@dataclass
class Observation:
    answer: Answer
    confidence: float = 0.9
    sources: dict[str, Any] = field(default_factory=dict)
    overridden: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": str(self.answer),
            "confidence": round(self.confidence, 4),
            "sources": self.sources,
            "overridden": self.overridden,
        }


def render(text: str, honorific: str) -> str:
    """Fill the Indonesian honorific placeholder. English strings have no placeholder."""
    return text.replace("{hon}", honorific)
