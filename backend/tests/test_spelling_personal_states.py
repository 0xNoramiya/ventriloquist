from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.config import EngineConfig
from app.engine.personal import ConfirmedMessage, personal_multipliers
from app.engine.policy import ActionKind, MessageDecider
from app.engine.spelling import (
    END,
    KEEP_ID,
    SPACE,
    SYMBOLS,
    SpellEvent,
    SpellingDecider,
    best_group,
    sentence_stage,
    symbol_prior,
)
from app.engine.types import Answer, Observation
from app.safety.sensitive import detect
from app.sessions.state_machine import (
    TRANSITIONS,
    InvalidTransition,
    State,
    StateMachine,
    can_transition,
)

CFG = EngineConfig()


def spell(
    target: str,
    lang: str = "en",
    eps: float = 0.0,
    seed: int = 0,
    completions=None,
    max_q: int = 400,
):
    """Drive the spelling decider with a simulated patient who means `target` then END."""
    rng = np.random.default_rng(seed)
    d = SpellingDecider(lang, CFG, a=max(eps, 0.02), b=max(eps, 0.02))
    events = []
    for _ in range(max_q):
        prompt = d.next_prompt()
        typed = d.text
        if prompt.stage == "checkpoint":
            truthful = target.startswith(typed.rstrip()) or target.startswith(typed)
        elif prompt.stage == "word":
            cur = typed.split(" ")[-1]
            start = len(typed) - len(cur)
            truthful = target[start:].split(" ")[0] == prompt.word
        else:
            if target.startswith(typed) and len(typed) < len(target):
                nxt = target[len(typed)]
                want = SPACE if nxt == " " else nxt
            elif typed == target:
                want = END
            else:
                want = "UNDO"
            truthful = want in prompt.group
        if rng.random() < eps:
            truthful = not truthful
        out = d.observe(Observation(Answer.YES if truthful else Answer.NO, 1 - eps))
        events.append(out.event)
        if completions is not None and out.event in (SpellEvent.LETTER, SpellEvent.UNDO):
            d.set_completions(completions(d.current_word))
        if out.event in (SpellEvent.END, SpellEvent.SENSITIVE, SpellEvent.STUCK):
            return d, out, events
    return d, None, events


def test_groups_are_contiguous_and_balanced():
    p = symbol_prior("", "en")
    i, j, gain = best_group(p, 0.05, 0.05)
    assert 0 <= i < j <= len(SYMBOLS)
    assert 0.3 < p[i:j].sum() < 0.7
    assert gain > 0.5


def test_symbol_prior_normalized_and_no_leading_space():
    p = symbol_prior("", "id")
    assert p.sum() == pytest.approx(1.0)
    assert p[SYMBOLS.index(SPACE)] == 0 and p[SYMBOLS.index(END)] == 0


def test_spells_word_without_noise():
    d, out, _ = spell("KUCING", "id")
    assert out.event == SpellEvent.END
    assert d.text == "KUCING"


def test_spells_word_with_noise_mostly_correct():
    ok = 0
    for seed in range(10):
        d, out, _ = spell("CAT", "en", eps=0.08, seed=seed)
        ok += bool(out and out.event == SpellEvent.END and d.text == "CAT")
    assert ok >= 7


def test_completion_shortcut_reduces_questions():
    plain, _, _ = spell("KUCING", "id")
    fast, out, events = spell(
        "KUCING", "id", completions=lambda cur: [("KUCING", 0.8)] if cur.startswith("KU") else []
    )
    assert out.event == SpellEvent.END and fast.text.strip() == "KUCING"
    assert SpellEvent.WORD in events
    assert fast.n_questions < plain.n_questions


def test_sensitive_spelled_text_is_flagged():
    d, out, _ = spell("MAU MATI", "id")
    assert out.event == SpellEvent.SENSITIVE
    assert "death_wish_self_harm" in out.sensitive.categories


def test_completions_never_offer_sensitive_words():
    d = SpellingDecider("id", CFG, 0.05, 0.05)
    d.text = "MA"
    d.set_completions([("MATI", 0.9), ("MAKAN", 0.5)])
    assert [w for w, _ in d.completions] == ["MAKAN"]


def test_sentence_stage_confirms_before_finalizing():
    hyps, prior, questions = sentence_stage(
        "KUCING",
        [
            ("Who is feeding my cat?", "Siapa yang memberi makan kucing saya?", 0.6),
            ("I miss my cat.", "Saya rindu kucing saya.", 0.4),
        ],
    )
    d = MessageDecider(hyps, prior, questions, CFG)
    act = d.next_action()
    steps = 0
    while act.kind in (ActionKind.ASK, ActionKind.CONFIRM):
        steps += 1
        act = d.observe(
            Observation(Answer.YES if "sentence:0" in act.question.yes_ids else Answer.NO, 0.9)
        )
    assert act.kind == ActionKind.FINALIZE and act.hypothesis.id == "sentence:0"
    assert steps >= 2  # at least one question plus a confirmation
    assert any(h.id == KEEP_ID for h in hyps)


def test_sensitive_detector_basics():
    assert detect("saya mau mati").sensitive
    assert detect("I WANT TO DIE").sensitive
    assert detect("CABUTSELANG").sensitive  # spelled without spaces
    assert not detect("Who is feeding my cat?").sensitive
    assert not detect("When will the tube come out?").sensitive
    assert not detect("Tolong matikan lampu").sensitive


def test_personal_multipliers_learn_and_decay():
    now = datetime(2026, 10, 30, tzinfo=UTC)
    base = {"pain": 0.1, "cold": 0.1, "thirst": 0.8}
    recent = [ConfirmedMessage("cold", now - timedelta(hours=h)) for h in range(8)]
    m = personal_multipliers(recent, base, now)
    assert m["cold"] > 1.5 and m["pain"] < 1.0
    old = [ConfirmedMessage("cold", now - timedelta(days=30)) for _ in range(8)]
    m_old = personal_multipliers(old, base, now)
    assert m_old["cold"] < m["cold"]
    assert all(0.5 <= v <= 3.0 for v in m.values())


def test_all_listed_transitions_valid():
    for src, dsts in TRANSITIONS.items():
        for dst in dsts:
            sm = StateMachine(src)
            assert sm.to(dst) == dst


@pytest.mark.parametrize("src", list(State))
def test_emergency_reachable_from_every_state(src):
    assert can_transition(src, State.EMERGENCY)
    sm = StateMachine(src)
    sm.to(State.EMERGENCY, "triple yes")
    assert sm.state == State.EMERGENCY


@pytest.mark.parametrize("src", list(State))
def test_caregiver_can_always_end(src):
    assert can_transition(src, State.DONE)


@pytest.mark.parametrize(
    "src,dst",
    [
        (State.IDLE, State.SPEAKING),
        (State.ASKING, State.SPEAKING),
        (State.LISTENING, State.SPEAKING),
        (State.DONE, State.SPEAKING),
        (State.EMERGENCY, State.ASKING),
        (State.CONTEXT_REFRESH, State.SPEAKING),
    ],
)
def test_invalid_transitions_rejected(src, dst):
    with pytest.raises(InvalidTransition):
        StateMachine(src).to(dst)


def test_speaking_only_reachable_from_processing_or_caregiver():
    """Nothing is spoken except after the engine finalizes or a caregiver acknowledges."""
    sources = [s for s in State if State.SPEAKING in TRANSITIONS.get(s, set())]
    assert set(sources) == {State.PROCESSING, State.CAREGIVER_NEEDED}
