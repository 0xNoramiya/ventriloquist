"""Spelling mode (brief 8.8): the escape hatch for anything not on the list.

The patient sees the alphabet with one group highlighted and is asked "Is your letter in this
group?". Each group is a contiguous run of the alphabet chosen to split the current letter
probability roughly in half (a probability-balanced, Huffman-style split that is still easy to
scan). Letter probabilities come from unigram/bigram counts of public-domain text, mixed with
word completions. Answers update a posterior over symbols under the same noisy channel as the
main engine; a letter is accepted at 0.90. Every 3 letters the patient checks the text so far.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.config import EngineConfig
from app.safety.sensitive import SensitiveResult, detect

from .eig import eig
from .posterior import bayes_update, effective_error_rates, normalize
from .types import Answer, Hypothesis, HypothesisSource, Observation, Question, QuestionKind

DATA_DIR = Path(__file__).parent / "data"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SPACE, END, UNDO = "SPACE", "END", "UNDO"
SYMBOLS: tuple[str, ...] = (*LETTERS, SPACE, END, UNDO)

# Fallback unigram percentages if the corpus statistics have not been built yet.
_FALLBACK_UNIGRAM = {
    "en": dict(
        zip(
            LETTERS,
            [
                8.2,
                1.5,
                2.8,
                4.3,
                12.7,
                2.2,
                2.0,
                6.1,
                7.0,
                0.15,
                0.77,
                4.0,
                2.4,
                6.7,
                7.5,
                1.9,
                0.1,
                6.0,
                6.3,
                9.1,
                2.8,
                0.98,
                2.4,
                0.15,
                2.0,
                0.07,
            ],
            strict=True,
        )
    ),
    "id": dict(
        zip(
            LETTERS,
            [
                19.0,
                2.5,
                0.7,
                3.5,
                8.0,
                0.1,
                3.5,
                2.5,
                8.5,
                1.0,
                5.5,
                3.0,
                4.0,
                9.0,
                2.0,
                2.5,
                0.01,
                4.5,
                4.0,
                5.0,
                5.0,
                0.1,
                0.5,
                0.02,
                1.5,
                0.05,
            ],
            strict=True,
        )
    ),
}

TEXTS = {
    "letter_q": {
        "en": "Is your letter in this group?",
        "id": "Apakah hurufnya ada di kelompok ini?",
    },
    "checkpoint": {"en": "Is everything so far correct?", "id": "Apakah sejauh ini sudah benar?"},
    "word_q": {"en": "Is your word {word}?", "id": "Apakah kata yang {hon} maksud {word}?"},
    "mean": {"en": "Do you mean: “{sentence}”?", "id": "Maksud {hon}: “{sentence}”?"},
    "keep": {"en": "Do you want to keep spelling?", "id": "Apakah {hon} ingin lanjut mengeja?"},
}


@dataclass
class LetterStats:
    unigram: dict[str, float]
    word_start: dict[str, float]
    bigram: dict[str, dict[str, float]]
    word_end: dict[str, float]


@lru_cache(maxsize=4)
def letter_stats(lang: str) -> LetterStats:
    path = DATA_DIR / f"letters_{lang}.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return LetterStats(raw["unigram"], raw["word_start"], raw["bigram"], raw["word_end"])
    uni = _FALLBACK_UNIGRAM.get(lang, _FALLBACK_UNIGRAM["en"])
    return LetterStats(uni, uni, {}, {k: v * 0.25 for k, v in uni.items()})


@lru_cache(maxsize=4)
def word_list(lang: str) -> list[tuple[str, int]]:
    path = DATA_DIR / f"words_{lang}.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [(w["w"].upper(), int(w.get("rank", i + 1))) for i, w in enumerate(raw["words"])]


def mock_completions(prefix: str, lang: str, k: int = 5) -> list[tuple[str, float]]:
    """Word completions from the bundled everyday word list (mock mode / offline fallback)."""
    prefix = prefix.upper()
    if len(prefix) < 2:
        return []
    matches = [(w, r) for w, r in word_list(lang) if w.startswith(prefix) and w != prefix]
    if not matches:
        return []
    weights = np.array([1.0 / (r**0.8) for _, r in matches])
    p_novel = {2: 0.45, 3: 0.3}.get(len(prefix), 0.2)
    probs = weights / weights.sum() * (1 - p_novel)
    ranked = sorted(zip([w for w, _ in matches], probs, strict=True), key=lambda x: -x[1])
    return [(w, float(p)) for w, p in ranked if not detect(w).sensitive][:k]


def symbol_prior(
    text: str,
    lang: str,
    completions: list[tuple[str, float]] | None = None,
) -> np.ndarray:
    """P(next symbol | text so far), mixing the letter model with word completions."""
    stats = letter_stats(lang)
    words = text.split(" ")
    current = words[-1] if words else ""
    p = np.zeros(len(SYMBOLS))
    if not current:
        base = np.array([stats.word_start.get(c, 0.0) + 0.5 for c in LETTERS])
        p_space = 0.0
        p_end = 0.30 if text.strip() else 0.0
    else:
        prev = current[-1]
        row = stats.bigram.get(prev, {})
        base = (
            np.array([row.get(c, 0.0) + 0.5 for c in LETTERS])
            if row
            else np.array([stats.unigram.get(c, 0.0) + 0.5 for c in LETTERS])
        )
        p_wend = stats.word_end.get(prev, 0.0) / max(stats.unigram.get(prev, 1.0), 1e-9)
        p_wend = float(np.clip(p_wend, 0.05, 0.6)) if len(current) >= 2 else 0.03
        p_space = 0.7 * p_wend
        p_end = 0.3 * p_wend
    p_undo = 0.03 if text else 0.0
    letters_mass = 1.0 - p_space - p_end - p_undo
    p[: len(LETTERS)] = base / base.sum() * letters_mass
    p[LETTERS.__len__()] = p_space
    p[len(LETTERS) + 1] = p_end
    p[len(LETTERS) + 2] = p_undo

    if completions and current:
        comp = np.zeros(len(SYMBOLS))
        for word, prob in completions:
            if not word.startswith(current) or len(word) <= len(current):
                continue
            comp[LETTERS.index(word[len(current)])] += prob
        mass = comp.sum()
        if mass > 0:
            lam = min(0.6, mass)
            p = (1 - lam) * p + lam * comp / mass
    return normalize(p)


def best_group(p: np.ndarray, a: float, b: float) -> tuple[int, int, float]:
    """Contiguous symbol range [i, j) maximising EIG (ties: shorter groups)."""
    cum = np.concatenate([[0.0], np.cumsum(p)])
    best = (0, 1, -1.0)
    n = len(p)
    for i in range(n):
        for j in range(i + 1, n + 1):
            if i == 0 and j == n:
                continue
            gain = float(eig(cum[j] - cum[i], a, b))
            if gain > best[2] + 1e-12 or (
                abs(gain - best[2]) <= 1e-12 and (j - i) < (best[1] - best[0])
            ):
                best = (i, j, gain)
    return best


class SpellEvent(StrEnum):
    ASKED = "asked"
    LETTER = "letter"
    UNDO = "undo"
    WORD = "word"
    END = "end"
    CHECKPOINT_OK = "checkpoint_ok"
    CHECKPOINT_FIX = "checkpoint_fix"
    REJECTED_WORD = "rejected_word"
    SENSITIVE = "sensitive"
    STUCK = "stuck"
    UNCLEAR = "unclear"
    NONE = "none"


@dataclass
class SpellOutcome:
    event: SpellEvent
    symbol: str | None = None
    text: str = ""
    sensitive: SensitiveResult | None = None


@dataclass
class SpellPrompt:
    question: Question
    stage: str  # letter | checkpoint | word
    group: list[str] = field(default_factory=list)
    word: str | None = None
    rephrased: bool = False

    def to_dict(self, lang: str, honorific: str) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "group": self.group,
            "word": self.word,
            "text": self.question.text(lang, honorific, self.rephrased),
            "question": self.question.to_dict(lang, honorific),
        }


class SpellingDecider:
    def __init__(self, lang: str, cfg: EngineConfig, a: float, b: float) -> None:
        self.lang = lang if lang in ("en", "id") else "en"
        self.cfg = cfg
        self.a, self.b = a, b
        self.text = ""
        self.checkpoint_at = 0  # characters of `text` the patient has verified
        self.since_checkpoint = 0
        self.completions: list[tuple[str, float]] = []
        self.rejected_words: set[str] = set()
        self.offered_words: set[tuple[str, str]] = set()
        self.p = symbol_prior("", self.lang)
        self.n_letter_q = 0
        self.n_questions = 0
        self.unclear_streak = 0
        self.pending: SpellPrompt | None = None
        self.done = False

    # ----------------------------------------------------------- state helpers
    @property
    def current_word(self) -> str:
        return self.text.split(" ")[-1] if self.text else ""

    def set_completions(self, completions: list[tuple[str, float]]) -> None:
        self.completions = [
            (w.upper(), float(p))
            for w, p in completions
            if w and w.upper() not in self.rejected_words and not detect(w).sensitive
        ]
        self._reset_letter()

    def _reset_letter(self) -> None:
        self.p = symbol_prior(self.text, self.lang, self.completions)
        self.n_letter_q = 0

    def top_symbols(self, k: int = 6) -> list[tuple[str, float]]:
        order = np.argsort(-self.p, kind="stable")[:k]
        return [(SYMBOLS[i], float(self.p[i])) for i in order]

    # ----------------------------------------------------------------- prompts
    def next_prompt(self) -> SpellPrompt:
        cfg = self.cfg
        if self.since_checkpoint >= cfg.spelling_checkpoint_every:
            q = Question(
                id=f"spell:checkpoint:{len(self.text)}",
                text_en=f"{TEXTS['checkpoint']['en']} {self.text.strip()}",
                text_id=f"{TEXTS['checkpoint']['id']} {self.text.strip()}",
                kind=QuestionKind.SPELLING,
                yes_ids=frozenset({"correct"}),
            )
            return self._set(SpellPrompt(q, "checkpoint"))
        word = self._word_to_offer()
        if word:
            self.offered_words.add((self.current_word, word))
            q = Question(
                id=f"spell:word:{word}",
                text_en=TEXTS["word_q"]["en"].format(word=word),
                text_id=TEXTS["word_q"]["id"].replace("{word}", word),
                kind=QuestionKind.SPELLING,
                yes_ids=frozenset({word}),
            )
            return self._set(SpellPrompt(q, "word", word=word))
        i, j, _ = best_group(self.p, self.a, self.b)
        group = list(SYMBOLS[i:j])
        q = Question(
            id=f"spell:group:{len(self.text)}:{self.n_letter_q}",
            text_en=TEXTS["letter_q"]["en"],
            text_id=TEXTS["letter_q"]["id"],
            kind=QuestionKind.SPELLING,
            yes_ids=frozenset(group),
            group=tuple(group),
        )
        return self._set(SpellPrompt(q, "letter", group=group))

    def _word_to_offer(self) -> str | None:
        cur = self.current_word
        if len(cur) < 2:
            return None
        for word, prob in sorted(self.completions, key=lambda x: -x[1]):
            if (
                word.startswith(cur)
                and word != cur
                and word not in self.rejected_words
                and (cur, word) not in self.offered_words
                and prob >= self.cfg.spelling_word_suggest_min
            ):
                return word
        return None

    def _set(self, prompt: SpellPrompt) -> SpellPrompt:
        self.pending = prompt
        self.n_questions += 1
        if prompt.stage == "letter":
            self.n_letter_q += 1
        return prompt

    def reask(self) -> SpellPrompt:
        assert self.pending is not None
        self.pending.rephrased = True
        self.n_questions += 1
        return self.pending

    # ---------------------------------------------------------------- answers
    def observe(self, obs: Observation) -> SpellOutcome:
        prompt = self.pending
        if prompt is None:
            raise RuntimeError("no pending spelling prompt")
        if obs.answer in (Answer.UNCLEAR, Answer.NONE):
            self.unclear_streak += 1
            return SpellOutcome(SpellEvent.UNCLEAR, text=self.text)
        self.unclear_streak = 0
        yes = obs.answer == Answer.YES

        if prompt.stage == "checkpoint":
            self.since_checkpoint = 0
            if yes:
                self.checkpoint_at = len(self.text)
                return SpellOutcome(SpellEvent.CHECKPOINT_OK, text=self.text)
            self.text = self.text[: self.checkpoint_at]
            self.completions = []
            self._reset_letter()
            return SpellOutcome(SpellEvent.CHECKPOINT_FIX, text=self.text)

        if prompt.stage == "word":
            word = prompt.word or ""
            if not yes:
                self.rejected_words.add(word)
                self.completions = [(w, p) for w, p in self.completions if w != word]
                self._reset_letter()
                return SpellOutcome(SpellEvent.REJECTED_WORD, text=self.text)
            words = self.text.split(" ")
            words[-1] = word
            self.text = " ".join(words)
            self.since_checkpoint = 0
            self.checkpoint_at = len(self.text)  # the patient just confirmed the whole word
            self.completions = []
            return self._after_word(SpellEvent.WORD, word)

        a_eff, b_eff = effective_error_rates(obs, self.a, self.b, tuple(self.cfg.eps_clip))
        mask = np.array([s in prompt.question.yes_ids for s in SYMBOLS])
        self.p = bayes_update(self.p, mask, obs.answer, a_eff, b_eff)
        k = int(np.argmax(self.p))
        if self.p[k] < self.cfg.spelling_letter_accept:
            if self.n_letter_q >= self.cfg.spelling_max_questions_per_letter:
                return SpellOutcome(SpellEvent.STUCK, text=self.text)
            return SpellOutcome(SpellEvent.ASKED, text=self.text)
        return self._commit(SYMBOLS[k])

    def _commit(self, sym: str) -> SpellOutcome:
        if sym == UNDO:
            self.text = self.text[:-1]
            self.checkpoint_at = min(self.checkpoint_at, len(self.text))
            self.since_checkpoint = max(self.since_checkpoint - 1, 0)
            self._reset_letter()
            return SpellOutcome(SpellEvent.UNDO, symbol=sym, text=self.text)
        if sym == END:
            self.text = self.text.strip()
            self.done = True
            return self._after_word(SpellEvent.END, None)
        if sym == SPACE:
            word = self.current_word
            self.text += " "
            self._reset_letter()
            return self._after_word(SpellEvent.WORD, word)
        self.text += sym
        self.since_checkpoint += 1
        self._reset_letter()
        return SpellOutcome(SpellEvent.LETTER, symbol=sym, text=self.text)

    def _after_word(self, event: SpellEvent, word: str | None) -> SpellOutcome:
        result = detect(self.text)
        if result.sensitive:
            return SpellOutcome(
                SpellEvent.SENSITIVE, symbol=word, text=self.text.strip(), sensitive=result
            )
        return SpellOutcome(event, symbol=word, text=self.text)


# --------------------------------------------------------------------------- sentence stage
SPELLED_ID = "spelled_text"
KEEP_ID = "keep_spelling"


def sentence_stage(
    spelled: str,
    sentences: list[tuple[str, str, float]],
) -> tuple[list[Hypothesis], np.ndarray, list[Question]]:
    """Hypotheses for choosing what to say after spelling: up to 3 suggested sentences
    (text_en, text_id, prob), the spelled text itself, or keep spelling."""
    spelled = spelled.strip()
    hyps: list[Hypothesis] = []
    weights: list[float] = []
    for i, (en, idn, prob) in enumerate(sentences[:3]):
        hyps.append(
            Hypothesis(
                id=f"sentence:{i}",
                text_en=en,
                text_id=idn,
                category="spelled",
                source=HypothesisSource.SPELLING,
                direct_en=TEXTS["mean"]["en"].format(sentence=en),
                direct_id=TEXTS["mean"]["id"].replace("{sentence}", idn),
            )
        )
        weights.append(max(prob, 0.01))
    if sentences:
        total = sum(weights)
        weights = [0.7 * w / total for w in weights]
        spelled_w, keep_w = 0.15, 0.15
    else:
        spelled_w, keep_w = 0.8, 0.2
    hyps.append(
        Hypothesis(
            id=SPELLED_ID,
            text_en=spelled.capitalize() if spelled.isupper() else spelled,
            text_id=spelled.capitalize() if spelled.isupper() else spelled,
            category="spelled",
            source=HypothesisSource.SPELLING,
            direct_en=TEXTS["mean"]["en"].format(sentence=spelled),
            direct_id=TEXTS["mean"]["id"].replace("{sentence}", spelled),
        )
    )
    hyps.append(
        Hypothesis(
            id=KEEP_ID,
            text_en="Keep spelling.",
            text_id="Lanjut mengeja.",
            category="control",
            source=HypothesisSource.SPELLING,
            direct_en=TEXTS["keep"]["en"],
            direct_id=TEXTS["keep"]["id"],
        )
    )
    prior = normalize(np.array([*weights, spelled_w, keep_w], dtype=float))
    questions = [
        Question(
            id=f"direct:{h.id}",
            text_en=h.direct_en or h.text_en,
            text_id=h.direct_id or h.text_id,
            kind=QuestionKind.ATTRIBUTE,
            yes_ids=frozenset({h.id}),
        )
        for h in hyps
    ]
    return hyps, prior, questions
