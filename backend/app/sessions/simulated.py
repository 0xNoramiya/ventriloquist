"""A simulated patient that answers prompts automatically (mock mode, CLI demo, tests).

It knows its true message (a hypothesis id, or text to spell) and answers each prompt truthfully,
flipped with probability `noise`. It never sees probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.engine.spelling import END, SPACE, UNDO
from app.engine.types import META_OTHER, META_SPELL, Answer


@dataclass
class SimulatedPatient:
    truth: str | None = None  # hypothesis id the patient means
    spell: str | None = None  # text the patient will spell when it is not on the list
    sentence_en: str | None = None  # which suggested sentence to accept after spelling
    pain_location: str | None = None
    worse: bool = False
    relay: bool = False  # answers YES when offered to send a message to a relative
    noise: float = 0.0
    seed: int = 0
    rng: np.random.Generator = field(init=False)

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        if self.spell:
            self.spell = self.spell.upper()

    def _flip(self, truthful: bool) -> Answer:
        if self.rng.random() < self.noise:
            truthful = not truthful
        return Answer.YES if truthful else Answer.NO

    def answer(self, prompt: dict[str, Any], session_view: dict[str, Any]) -> Answer:
        kind = prompt.get("kind")
        q = prompt.get("question") or {}
        yes_ids = set(q.get("yes_ids") or [])
        wanted = self.truth if self.truth else META_OTHER
        if kind in ("ask", "confirm"):
            stage = prompt.get("stage")
            if stage == "sentence":
                return self._flip(self._sentence_yes(yes_ids, session_view))
            if stage == "refine":
                return self._flip(f"pain_loc:{self.pain_location or 'elsewhere'}" in yes_ids)
            return self._flip(wanted in yes_ids)
        if kind == "offer_spell":
            return self._flip(bool(self.spell) or wanted in (META_OTHER, META_SPELL))
        if kind == "spelling":
            return self._flip(self._spelling_yes(prompt, session_view))
        if kind == "post_check":
            msg = session_view.get("message") or {}
            hid = msg.get("hypothesis_id")
            ok = (hid == self.truth) if self.truth else True
            if msg.get("source") == "refinement":
                ok = hid in (f"pain_loc:{self.pain_location}", None)
            if msg.get("source") == "spelling" and self.sentence_en:
                ok = (
                    msg.get("text_en") == self.sentence_en
                    or msg.get("hypothesis_id") == "spelled_text"
                )
            return self._flip(ok)
        if kind == "refine_offer":
            return self._flip(self.pain_location is not None)
        if kind == "worse":
            return self._flip(self.worse)
        if kind == "relay_offer":
            return self._flip(self.relay)
        return Answer.NO

    def _sentence_yes(self, yes_ids: set[str], view: dict[str, Any]) -> bool:
        hyps = {h["id"]: h for h in (view.get("sentence_options") or [])}
        typed = ((view.get("spelling") or {}).get("text") or "").strip()
        target = (self.spell or "").strip()
        complete = typed == target
        offered = {h.get("text_en") for h in hyps.values()}
        wants_sentence = bool(self.sentence_en and self.sentence_en in offered)
        for hid in yes_ids:
            h = hyps.get(hid)
            if not h:
                continue
            if wants_sentence and h.get("text_en") == self.sentence_en:
                return True
            if not wants_sentence and hid == "spelled_text" and complete:
                return True
            if hid == "keep_spelling" and not complete and not self.sentence_en:
                return True
            if hid == "spelled_text" and complete and not self.sentence_en:
                return True
        return False

    def _spelling_yes(self, prompt: dict[str, Any], view: dict[str, Any]) -> bool:
        target = self.spell or ""
        typed = (view.get("spelling") or {}).get("text", "")
        stage = prompt.get("sub")
        if stage == "checkpoint":
            return target.startswith(typed.rstrip())
        if stage == "word":
            cur = typed.split(" ")[-1]
            start = len(typed) - len(cur)
            return target[start:].split(" ")[0] == prompt.get("word")
        group = set(prompt.get("group") or [])
        if target.startswith(typed) and len(typed) < len(target):
            nxt = target[len(typed)]
            want = SPACE if nxt == " " else nxt
        elif typed.rstrip() == target:
            want = END
        else:
            want = UNDO
        return want in group
