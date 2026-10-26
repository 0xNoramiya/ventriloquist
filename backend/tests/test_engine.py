"""Engine tests (brief 8.10)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.config import EngineConfig, get_settings
from app.engine.eig import eig, h2
from app.engine.instantiation import TemplateProposal, validate_instantiations
from app.engine.policy import ActionKind, MessageDecider
from app.engine.posterior import bayes_update, effective_error_rates
from app.engine.priors import ContextMultiplier, apply_bounds, build_prior
from app.engine.questions import LLMQuestionProposal, validate_llm_questions
from app.engine.taxonomy import Person, attribute_questions, build_hypotheses
from app.engine.types import Answer, Hypothesis, Observation, Question, QuestionKind

CFG = EngineConfig()
PERSONS = [Person("Aisyah", "daughter"), Person("Rizal", "son"), Person("Siti", "wife")]


def taxonomy_setup():
    hyps = build_hypotheses(get_settings().base_rates, PERSONS)
    return hyps, attribute_questions(hyps, PERSONS)


def yes(conf: float = 1.0) -> Observation:
    return Observation(Answer.YES, conf)


def no(conf: float = 1.0) -> Observation:
    return Observation(Answer.NO, conf)


# --------------------------------------------------------------------------- EIG
def test_eig_nonnegative_and_peaks_at_half():
    s = np.linspace(0, 1, 1001)
    for a in (0.0, 0.05, 0.1, 0.2, 0.4):
        gains = eig(s, a, a)
        assert np.all(gains >= 0)
        assert abs(s[int(np.argmax(gains))] - 0.5) < 1e-9


@given(st.floats(0, 1), st.floats(0, 0.49), st.floats(0, 0.49))
def test_eig_bounded_by_entropy(s, a, b):
    g = eig(s, a, b)
    assert -1e-12 <= g <= h2(s) + 1e-9


def test_eig_zero_noise_equals_entropy():
    assert eig(0.5, 0.0, 0.0) == pytest.approx(1.0)
    assert eig(0.25, 0.0, 0.0) == pytest.approx(h2(0.25))


# --------------------------------------------------------------------- posterior
@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.floats(0.001, 1.0), min_size=2, max_size=40),
    st.lists(st.tuples(st.integers(0, 2**40), st.sampled_from(list(Answer)), st.floats(0, 1)), max_size=15),
)
def test_posterior_always_normalized(weights, steps):
    p = np.array(weights) / sum(weights)
    for seed, ans, conf in steps:
        rng = np.random.default_rng(seed)
        mask = rng.random(len(p)) < 0.5
        a, b = effective_error_rates(Observation(ans, conf), 0.1, 0.1, (0.03, 0.45))
        p = bayes_update(p, mask, ans, a, b)
        assert p.sum() == pytest.approx(1.0)
        assert np.all(p >= 0)


def test_unclear_does_not_update():
    p = np.array([0.2, 0.3, 0.5])
    mask = np.array([True, False, False])
    assert np.array_equal(bayes_update(p, mask, Answer.UNCLEAR, 0.1, 0.1), p)


def test_override_uses_observation_error_only():
    a, b = effective_error_rates(Observation(Answer.YES, 0.97, overridden=True), 0.3, 0.3, (0.03, 0.45))
    assert a == pytest.approx(0.03) and b == pytest.approx(0.03)
    a, b = effective_error_rates(Observation(Answer.YES, 0.97), 0.3, 0.2, (0.03, 0.45))
    assert (a, b) == (pytest.approx(0.3), pytest.approx(0.2))


# --------------------------------------------------------------------- priors
@settings(max_examples=300, deadline=None)
@given(
    st.lists(st.floats(1e-6, 1.0), min_size=4, max_size=45),
    st.data(),
)
def test_bounds_hold_against_adversarial_inputs(weights, data):
    n = len(weights)
    other = data.draw(st.integers(0, n - 1))
    q = np.array(weights)
    p = apply_bounds(q / q.sum(), 0.40, 0.005, other, 0.08)
    assert p.sum() == pytest.approx(1.0, abs=1e-9)
    cap = max(0.40, 1 / n)
    assert np.all(p <= cap + 1e-9)
    assert np.all(p >= min(0.005, 1 / n) - 1e-9)
    assert p[other] >= 0.08 - 1e-9


@settings(max_examples=100, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 32), st.floats(-10, 1e6), st.booleans()), max_size=60))
def test_build_prior_bounded_with_adversarial_multipliers(mults):
    hyps, _ = taxonomy_setup()
    ids = [h.id for h in hyps]
    multipliers = [
        ContextMultiplier(ids[i % len(ids)], f, ("T1",) if cited else ("BOGUS",), "adv")
        for i, f, cited in mults
    ]
    p, terms = build_prior(hyps, multipliers=multipliers, valid_evidence={"T1"},
                           personal={ids[0]: 1e9, ids[1]: 0.0})
    assert p.sum() == pytest.approx(1.0, abs=1e-9)
    assert p.max() <= 0.40 + 1e-9
    assert p.min() >= 0.005 - 1e-9
    assert p[ids.index("other")] >= 0.08 - 1e-9
    for t in terms.values():
        assert 0.1 - 1e-12 <= t.context <= 8.0 + 1e-12
        assert 0.5 <= t.personal <= 3.0


def test_uncited_multiplier_forced_to_one():
    hyps, _ = taxonomy_setup()
    _, terms = build_prior(
        hyps,
        multipliers=[ContextMultiplier("thirst", 4, ("S9",)), ContextMultiplier("cold", 4, ())],
        valid_evidence={"S1"},
    )
    assert terms["thirst"].context == 1.0 and terms["thirst"].rejected
    assert terms["cold"].context == 1.0


def test_context_multiplier_snaps_to_allowed_values():
    hyps, _ = taxonomy_setup()
    _, terms = build_prior(hyps, multipliers=[ContextMultiplier("cold", 3.1, ("E1",))], valid_evidence={"E1"})
    assert terms["cold"].context == 4.0
    assert terms["cold"].chips[0].evidence_id == "E1"


# ------------------------------------------------------------- the 3+1 test
def binary_world(n_bits: int = 3):
    hyps = [
        Hypothesis(id=f"h{i}", text_en=f"Message {i}.", text_id=f"Pesan {i}.", category="x",
                   attributes=frozenset(f"bit{k}" for k in range(n_bits) if i >> k & 1))
        for i in range(2**n_bits)
    ]
    questions = [
        Question(id=f"bit{k}", text_en="Is it this half?", text_id="Apakah ini?",
                 kind=QuestionKind.ATTRIBUTE,
                 yes_ids=frozenset(h.id for h in hyps if f"bit{k}" in h.attributes))
        for k in range(n_bits)
    ]
    return hyps, questions


@pytest.mark.parametrize("truth", range(8))
def test_zero_noise_eight_equiprobable_takes_three_questions_plus_confirm(truth):
    hyps, questions = binary_world()
    d = MessageDecider(hyps, np.full(8, 1 / 8), questions, CFG, a=0.0, b=0.0)
    act = d.next_action()
    asked = []
    while act.kind in (ActionKind.ASK, ActionKind.CONFIRM):
        asked.append(act.kind)
        act = d.observe(yes() if f"h{truth}" in act.question.yes_ids else no())
    assert act.kind == ActionKind.FINALIZE
    assert act.hypothesis.id == f"h{truth}"
    assert asked == [ActionKind.ASK] * 3 + [ActionKind.CONFIRM]


# ----------------------------------------------------------------- policy rules
def run_patient(d: MessageDecider, truth: str, flip_rng=None, eps: float = 0.0, max_steps: int = 40):
    act = d.next_action()
    trail = []
    for _ in range(max_steps):
        if act.kind not in (ActionKind.ASK, ActionKind.CONFIRM, ActionKind.OFFER_SPELL):
            break
        truthful = truth in act.question.yes_ids
        if flip_rng is not None and flip_rng.random() < eps:
            truthful = not truthful
        trail.append((act, truthful))
        act = d.observe(yes(1 - eps) if truthful else no(1 - eps))
    return act, trail


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 10**6), st.sampled_from([0.0, 0.1, 0.3]))
def test_confirm_gating(seed, eps):
    """FINALIZE only ever follows a confirmation answered YES that lifts p >= 0.95."""
    hyps, questions = taxonomy_setup()
    rng = np.random.default_rng(seed)
    truth = hyps[int(rng.integers(len(hyps)))].id
    prior, _ = build_prior(hyps)
    d = MessageDecider(hyps, prior, questions, CFG)
    act, trail = run_patient(d, truth, rng, eps)
    assert d.n_questions <= CFG.max_questions
    if act.kind == ActionKind.FINALIZE:
        last, said_yes = trail[-1]
        assert last.kind == ActionKind.CONFIRM and said_yes
        assert d.posterior()[act.hypothesis.id] >= CFG.finalize_threshold


def test_noise_free_taxonomy_finds_every_message():
    hyps, questions = taxonomy_setup()
    prior, _ = build_prior(hyps)
    for h in hyps:
        if h.is_meta:
            continue
        d = MessageDecider(hyps, prior, questions, CFG, a=0.0, b=0.0)
        act, _ = run_patient(d, h.id)
        assert act.kind == ActionKind.FINALIZE and act.hypothesis.id == h.id, h.id


def test_other_leads_to_spelling_offer():
    hyps, questions = taxonomy_setup()
    prior, _ = build_prior(hyps)
    d = MessageDecider(hyps, prior, questions, CFG, a=0.05, b=0.05)
    act, trail = run_patient(d, "other")
    assert act.kind in (ActionKind.ENTER_SPELLING, ActionKind.CAREGIVER)
    assert any(a.kind == ActionKind.OFFER_SPELL for a, _ in trail)


def test_confirmation_no_multiplies_by_factor():
    hyps, questions = binary_world()
    d = MessageDecider(hyps, np.array([0.72] + [0.04] * 7), questions, CFG)
    act = d.next_action()
    assert act.kind == ActionKind.CONFIRM and act.hypothesis.id == "h0"
    before = d.p.copy()
    d.observe(no())
    expected = before.copy()
    expected[0] *= CFG.confirm_no_factor
    expected /= expected.sum()
    assert np.allclose(d.p, expected)


def test_two_high_confirmation_nos_pause():
    hyps, questions = binary_world()
    d = MessageDecider(hyps, np.full(8, 1 / 8), questions, CFG)
    d.p = np.array([0.95] + [0.05 / 7] * 7)
    act = d.next_action()
    assert act.kind == ActionKind.CONFIRM and act.hypothesis.id == "h0"
    act = d.observe(no())
    assert act.kind != ActionKind.CAREGIVER
    d.p = np.array([0.01, 0.94] + [0.05 / 6] * 6)
    act = d.next_action()
    assert act.kind == ActionKind.CONFIRM and act.hypothesis.id == "h1"
    act = d.observe(no())
    assert act.kind == ActionKind.CAREGIVER and act.reason == "inconsistent"


def test_unclear_reask_then_caregiver_then_pause():
    hyps, questions = binary_world()
    d = MessageDecider(hyps, np.full(8, 1 / 8), questions, CFG)
    first = d.next_action()
    act = d.observe(Observation(Answer.UNCLEAR, 0.4))
    assert act.question.id == first.question.id and act.rephrased
    act = d.observe(Observation(Answer.UNCLEAR, 0.4))
    assert act.kind == ActionKind.CAREGIVER and act.reason == "tap_answer"
    # the caregiver taps an answer for the same question; the conversation continues
    act = d.observe(Observation(Answer.YES, 0.97, overridden=True))
    assert act.kind == ActionKind.ASK

    d2 = MessageDecider(hyps, np.full(8, 1 / 8), questions, CFG)
    d2.next_action()
    reasons = [d2.observe(Observation(Answer.NONE, 0.0)).reason for _ in range(3)]
    assert reasons == ["reask", "tap_answer", "unclear"]


def test_question_cap():
    hyps, questions = taxonomy_setup()
    prior, _ = build_prior(hyps)
    d = MessageDecider(hyps, prior, questions, CFG, a=0.45, b=0.45)
    rng = np.random.default_rng(1)
    act = d.next_action()
    while act.kind in (ActionKind.ASK, ActionKind.CONFIRM, ActionKind.OFFER_SPELL):
        act = d.observe(yes(0.55) if rng.random() < 0.5 else no(0.55))
        if act.kind == ActionKind.ENTER_SPELLING:
            break
    assert d.n_questions <= CFG.max_questions


def test_no_identical_question_repeats():
    hyps, questions = taxonomy_setup()
    prior, _ = build_prior(hyps)
    d = MessageDecider(hyps, prior, questions, CFG)
    _, trail = run_patient(d, "noise")
    seen = [a.question.partition_key for a, _ in trail if a.kind == ActionKind.ASK]
    assert len(seen) == len(set(seen))


def test_post_speak_retraction():
    hyps, questions = binary_world()
    d = MessageDecider(hyps, np.full(8, 1 / 8), questions, CFG, a=0.0, b=0.0)
    act, _ = run_patient(d, "h3")
    assert act.kind == ActionKind.FINALIZE
    p_before = d.posterior()["h3"]
    act = d.retract("h3")
    assert d.finalized is None
    assert d.posterior()["h3"] < p_before
    assert act.kind in (ActionKind.ASK, ActionKind.CONFIRM, ActionKind.OFFER_SPELL)


def test_emergency_bypasses_engine():
    hyps, questions = binary_world()
    d = MessageDecider(hyps, np.full(8, 1 / 8), questions, CFG)
    d.next_action()
    before = d.p.copy()
    act = d.observe(Observation(Answer.EMERGENCY, 0.9))
    assert act.kind == ActionKind.EMERGENCY
    assert np.array_equal(before, d.p)


# ------------------------------------------------------------ LLM validation
def test_llm_questions_validated():
    hyps, questions = taxonomy_setup()
    ids = {h.id for h in hyps}
    props = [
        LLMQuestionProposal("Is it about the photo on the table?", "Apakah ini tentang foto di meja?",
                            ["see_person:aisyah", "see_person:rizal"], ["S1"]),
        LLMQuestionProposal("Are you not comfortable?", "", ["position"], []),
        LLMQuestionProposal("Do you want 5 mg of morphine?", "", ["pain"], []),
        LLMQuestionProposal("Do you want to stop treatment?", "", ["other"], []),
        LLMQuestionProposal("Is it about a ghost id?", "", ["ghost"], []),
        LLMQuestionProposal("Are you cold and thirsty?", "", ["cold", "thirst"], []),
        LLMQuestionProposal("Is it about the long list of many things in the room?", "", ["light"], []),
    ]
    accepted, rejected = validate_llm_questions(props, ids, questions)
    assert [q.text_en for q in accepted] == ["Is it about the photo on the table?"]
    assert len(rejected) == 6


# --------------------------------------------- sensitive hypotheses never appear
def test_sensitive_or_uncited_instantiations_rejected():
    evidence = {"T1": "Your daughter Aisyah went home to rest, she'll be back at four.",
                "T2": "Pak Budi from the bank came by"}
    accepted, rejected = validate_instantiations(
        [
            TemplateProposal("where_person", {"name": "Aisyah", "relation": "daughter"}, ["T1"]),
            TemplateProposal("where_person", {"name": "Budi", "relation": "friend"}, []),
            TemplateProposal("want_item", {"item": "bank papers"}, ["T2"]),
            TemplateProposal("stop_treatment", {"name": "Aisyah"}, ["T1"]),
            TemplateProposal("want_item", {"item": "will to die"}, ["T1"]),
            TemplateProposal("call_person", {"name": "Zainab", "relation": "sister"}, ["T1"]),
        ],
        persons=PERSONS,
        evidence=evidence,
        existing_ids=set(),
    )
    assert [h.id for h in accepted] == ["where_person:aisyah"]
    assert len(rejected) == 5


@settings(max_examples=200, deadline=None)
@given(st.text(min_size=1, max_size=30), st.sampled_from(["see_person", "where_person", "call_person", "want_item"]))
def test_no_generated_hypothesis_is_sensitive(slot, template):
    from app.safety.sensitive import is_sensitive

    evidence = {"T1": f"note {slot} note"}
    slots = {"item": slot} if template == "want_item" else {"name": slot, "relation": "friend"}
    accepted, _ = validate_instantiations([TemplateProposal(template, slots, ["T1"])],
                                          persons=[], evidence=evidence, existing_ids=set())
    for h in accepted:
        assert not is_sensitive(h.text_en) and not is_sensitive(h.text_id)
