"""Sensitive-topic detector (Safety rule 3).

The engine never generates, ranks or asks about sensitive topics. A patient can still say anything
by spelling; when a spelled message matches a sensitive category the caregiver sees it at once with
a "Verify in person with the patient" banner, it is not spoken until a caregiver acknowledges it,
and it is never stored in memory.

Layer 1 (always on): EN/ID keyword lists in data/sensitive_keywords.json, tuned for recall.
Layer 2 (live mode): an LLM classifier (see app.roles.safety_classifier) that can only ADD flags.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

KEYWORDS_PATH = Path(__file__).parent / "data" / "sensitive_keywords.json"

CATEGORIES = (
    "refuse_treatment",
    "end_of_life",
    "death_wish_self_harm",
    "abuse_safety",
    "consent",
    "legal_financial",
)

# Minimal built-in list so the detector works even before the full list is generated.
_FALLBACK: dict[str, dict[str, list[str]]] = {
    "refuse_treatment": {
        "en": ["STOP TREATMENT", "NO MORE TREATMENT", "TAKE THE TUBE OUT", "PULL THE TUBE", "TURN OFF THE MACHINE", "REFUSE"],
        "id": ["STOP PENGOBATAN", "CABUT SELANG", "LEPAS SELANG", "MATIKAN MESIN", "TOLAK", "PULANG PAKSA"],
    },
    "end_of_life": {
        "en": ["DNR", "DO NOT RESUSCITATE", "LET ME GO", "END OF LIFE", "LET ME DIE"],
        "id": ["JANGAN DIRESUSITASI", "BIARKAN SAYA PERGI", "AKHIR HIDUP"],
    },
    "death_wish_self_harm": {
        "en": ["WANT TO DIE", "KILL MYSELF", "SUICIDE", "END IT", "DIE", "DEAD"],
        "id": ["MAU MATI", "INGIN MATI", "BUNUH DIRI", "MATI", "BUNUH"],
    },
    "abuse_safety": {
        "en": ["HIT ME", "HURT ME", "ABUSE", "AFRAID OF HIM", "AFRAID OF HER", "HARASS"],
        "id": ["DIPUKUL", "MEMUKUL", "DISAKITI", "KEKERASAN", "DILECEHKAN"],
    },
    "consent": {
        "en": ["CONSENT", "PERMISSION", "SIGN THE", "SIGN PAPERS", "SIGN FORM", "OPERATION", "SURGERY"],
        "id": ["PERSETUJUAN", "IZIN", "TANDA TANGAN", "OPERASI"],
    },
    "legal_financial": {
        "en": ["MY WILL", "LAST WILL", "TESTAMENT", "INHERITANCE", "BANK", "LAWYER", "TRANSFER MONEY"],
        "id": ["WASIAT", "SURAT WASIAT", "WARISAN", "BANK", "PENGACARA", "TRANSFER UANG"],
    },
}


@dataclass
class SensitiveResult:
    sensitive: bool
    categories: list[str] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)
    method: str = "keywords"

    def to_dict(self) -> dict:
        return {
            "sensitive": self.sensitive,
            "categories": self.categories,
            "matches": self.matches,
            "method": self.method,
        }


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^A-Z]+", " ", text.upper()).split())


@lru_cache(maxsize=1)
def keyword_table() -> dict[str, list[str]]:
    data = _FALLBACK
    if KEYWORDS_PATH.exists():
        try:
            loaded = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))["categories"]
            data = {
                cat: {
                    lang: list(loaded.get(cat, {}).get(lang, [])) + _FALLBACK[cat][lang]
                    for lang in ("en", "id")
                }
                for cat in CATEGORIES
            }
        except (KeyError, ValueError):
            data = _FALLBACK
    table: dict[str, list[str]] = {}
    for cat, langs in data.items():
        words = {_norm(w) for lang in langs.values() for w in lang}
        table[cat] = sorted(w for w in words if w)
    return table


def detect(text: str) -> SensitiveResult:
    """Keyword layer. Short keywords need word boundaries; long ones also match unspaced text,
    because patients often spell without spaces."""
    spaced = f" {_norm(text)} "
    unspaced = spaced.replace(" ", "")
    cats: list[str] = []
    matches: list[str] = []
    for cat, words in keyword_table().items():
        for w in words:
            hit = f" {w} " in spaced or (len(w.replace(" ", "")) >= 6 and w.replace(" ", "") in unspaced)
            if hit:
                if cat not in cats:
                    cats.append(cat)
                matches.append(w)
    return SensitiveResult(bool(cats), cats, matches)


def is_sensitive(text: str) -> bool:
    return detect(text).sensitive
