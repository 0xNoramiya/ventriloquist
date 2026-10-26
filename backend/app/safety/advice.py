"""Validators for model outputs (Safety rule 2 and the question wording rules in 8.4).

Model outputs are restricted to candidate patient messages, yes/no questions, scene facts and
observed-movement descriptions. Anything that looks like clinical advice is rejected and the
caller falls back safely.
"""

from __future__ import annotations

import re

from .sensitive import is_sensitive

_DOSE = re.compile(
    r"\b\d+(\.\d+)?\s?(mg|mcg|µg|ug|ml|cc|g|units?|iu|tetes|tablet|tab|kapsul)\b", re.I
)

_ADVICE_PHRASES = [
    r"\byou should\b",
    r"\byou need to\b",
    r"\byou must\b",
    r"\bi recommend\b",
    r"\bwe recommend\b",
    r"\brecommend(ed|ation)?\b",
    r"\bdiagnos\w*",
    r"\bprognos\w*",
    r"\btreatment (plan|option)s?\b",
    r"\bincrease the (dose|rate|oxygen)\b",
    r"\bdecrease the (dose|rate|oxygen)\b",
    r"\bcontraindicat\w*",
    r"\bsaturation\b",
    r"\bspo2\b",
    r"\bblood pressure is\b",
    r"\bheart rate is\b",
    r"\bsebaiknya\b",
    r"\bdianjurkan\b",
    r"\bharus minum\b",
    r"\bdosis\b",
    r"\bdiagnosis\b",
]
_ADVICE = re.compile("|".join(_ADVICE_PHRASES), re.I)

# Generic names only, enough to catch a model drifting into prescribing.
_DRUGS = re.compile(
    r"\b(morphine|morfin|fentanyl|propofol|midazolam|dexmedetomidine|ketamine|haloperidol|"
    r"lorazepam|diazepam|paracetamol|acetaminophen|ibuprofen|ketorolac|tramadol|"
    r"furosemide|norepinephrine|noradrenaline|epinephrine|adrenaline|dopamine|insulin|"
    r"heparin|enoxaparin|omeprazole|ondansetron|metoclopramide|salbutamol|albuterol|"
    r"dexamethasone|methylprednisolone|ceftriaxone|meropenem|vancomycin|antibiotic\w*|"
    r"antibiotik\w*|sedati\w*|analgesi\w*)\b",
    re.I,
)

_NEGATION = re.compile(
    r"\b(not|no|never|nothing|nobody|none|don'?t|doesn'?t|isn'?t|aren'?t|won'?t|can'?t|"
    r"didn'?t|without|tidak|bukan|jangan|belum|tak|enggak|nggak|gak)\b",
    re.I,
)
_MULTI_IDEA = re.compile(r"\b(and|dan|serta|also|juga)\b|;", re.I)


def contains_advice(text: str) -> bool:
    return bool(_DOSE.search(text) or _ADVICE.search(text) or _DRUGS.search(text))


def question_problems(text_en: str, text_id: str = "", max_words: int = 10) -> list[str]:
    """Reasons an LLM-proposed question is rejected. Empty list means it passes."""
    problems: list[str] = []
    for label, text in (("en", text_en), ("id", text_id)):
        if not text:
            continue
        if contains_advice(text):
            problems.append(f"advice:{label}")
        if is_sensitive(text):
            problems.append(f"sensitive:{label}")
        if _NEGATION.search(text):
            problems.append(f"negation:{label}")
        if _MULTI_IDEA.search(text) or text.count("?") > 1:
            problems.append(f"multiple_ideas:{label}")
    if not text_en.strip().endswith("?"):
        problems.append("not_a_question")
    if len(text_en.split()) > max_words:
        problems.append("too_long")
    return problems


def message_problems(text: str) -> list[str]:
    """Reasons an LLM-proposed patient message (hypothesis or sentence) is rejected."""
    problems: list[str] = []
    if contains_advice(text):
        problems.append("advice")
    if is_sensitive(text):
        problems.append("sensitive")
    if len(text) > 160:
        problems.append("too_long")
    return problems
