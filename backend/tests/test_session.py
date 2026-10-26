"""End-to-end session behaviour in mock mode, including every safety rule that lives in the session."""

from __future__ import annotations

import json

import pytest

from app.engine.types import Answer
from app.providers.registry import Mode
from app.sessions.simulated import SimulatedPatient
from app.sessions.state_machine import State

from .conftest import make_session, run_until


def log_events(session):
    return [json.loads(x) for x in session.log.path.read_text().splitlines()]


async def test_daughter_scenario_finalizes_quickly(ctx):
    s = make_session(ctx, "daughter", SimulatedPatient(truth="see_person:aisyah"))
    await s.start()
    await run_until(s)
    assert s.state == State.DONE
    confirmed = [m for m in s.messages if m.status == "confirmed"]
    assert confirmed and confirmed[0].text_en == "I want to see my daughter, Aisyah."
    assert confirmed[0].questions <= 5
    events = [e["event"] for e in log_events(s)]
    for needed in ("session_start", "context", "prior", "prompt", "observation", "message"):
        assert needed in events
    stored = ctx.store.messages(s.pid, "confirmed")
    assert stored[0]["hypothesis_id"] == "see_person:aisyah"


@pytest.mark.parametrize("scenario,truth", [("suction", "suction"), ("cold", "cold")])
async def test_other_scenarios(ctx, scenario, truth):
    s = make_session(ctx, scenario, SimulatedPatient(truth=truth))
    await s.start()
    await run_until(s)
    assert [m.hypothesis_id for m in s.messages if m.status == "confirmed"] == [truth]


async def test_spelling_scenario(ctx):
    sim = SimulatedPatient(spell="KUCING", sentence_en="Who is feeding my cat?")
    s = make_session(ctx, "spelling", sim)
    await s.start()
    await run_until(s, timeout=30)
    confirmed = [m for m in s.messages if m.status == "confirmed"]
    assert confirmed and confirmed[0].text_en == "Who is feeding my cat?"
    assert confirmed[0].text_id == "Siapa yang memberi makan kucing saya?"


async def test_nothing_spoken_before_confirmation_yes(ctx):
    s = make_session(ctx, "daughter", SimulatedPatient(truth="cold", noise=0.0))
    await s.start()
    await run_until(s)
    events = log_events(s)
    for i, e in enumerate(events):
        if e["event"] == "message" and e.get("status") == "speaking":
            prev = [x for x in events[:i] if x["event"] == "observation"][-1]
            prompt = [x for x in events[:i] if x["event"] == "prompt"][-1]
            assert prompt["prompt"]["kind"] == "confirm"
            assert prev["observation"]["answer"] == "yes"


async def test_post_speak_retraction_resumes(ctx):
    class Picky(SimulatedPatient):
        said_no = False

        def answer(self, prompt, view):
            if prompt.get("kind") == "post_check" and not self.said_no:
                self.said_no = True
                return Answer.NO
            return super().answer(prompt, view)

    s = make_session(ctx, "cold", Picky(truth="cold"))
    await s.start()
    await run_until(s)
    statuses = [m.status for m in s.messages]
    assert statuses[0] == "retracted"
    assert "confirmed" in statuses or s.state == State.CAREGIVER_NEEDED
    assert ctx.store.messages(s.pid, "retracted")


@pytest.mark.parametrize(
    "target_state", [State.ASKING, State.LISTENING, State.SPEAKING, State.DONE, State.PAUSED]
)
async def test_emergency_from_every_state(ctx, target_state):
    events = []
    s = make_session(ctx, "cold", None, events=events)
    await s.start()
    if target_state in (State.LISTENING,):
        await s.spoken(s.prompt.id)
    elif target_state == State.SPEAKING:
        while s.state != State.SPEAKING:
            q = s.prompt
            await s.spoken(q.id)
            await s.answer(
                q.id,
                Answer.YES if "cold" in (q.question.yes_ids if q.question else []) else Answer.NO,
            )
    elif target_state == State.DONE:
        await s.end()
    elif target_state == State.PAUSED:
        await s.override("pause")
    assert s.state == target_state
    await s.emergency("test")
    assert s.state == State.EMERGENCY
    assert any(e.get("type") == "alarm" and "help now" in e.get("text", "") for e in events)
    await s.override("ack_emergency")
    assert s.state == State.PAUSED


async def test_triple_yes_observation_triggers_alarm(ctx):
    events = []
    s = make_session(ctx, "cold", None, events=events)
    await s.start()
    await s.spoken(s.prompt.id)
    await s.answer(s.prompt.id, Answer.EMERGENCY)
    assert s.state == State.EMERGENCY
    assert events and events[-1]["type"] == "alarm"


async def test_sensitive_spelled_message_held_for_caregiver(ctx):
    events = []
    s = make_session(ctx, "spelling", SimulatedPatient(spell="MAU MATI"), events=events)
    await s.start()
    await run_until(s, timeout=60)
    assert s.state == State.CAREGIVER_NEEDED and s.caregiver_reason == "sensitive_verify"
    assert s.message.status == "needs_verification"
    assert "death_wish_self_harm" in s.message.categories
    assert any(e.get("type") == "sensitive" for e in events)
    raw_log = s.log.path.read_text()
    assert "MATI" not in raw_log  # redacted in the session log
    assert not ctx.store.messages(s.pid)  # not stored before acknowledgement
    await s.override("ack_sensitive_silent")
    stored = ctx.store.messages(s.pid)
    assert stored and stored[0]["sensitive"] == 1 and stored[0]["text_en"] is None
    assert not ctx.store.memory(s.pid, None)


async def test_sensitive_ack_speaks_then_post_checks(ctx):
    s = make_session(ctx, "spelling", SimulatedPatient(spell="MAU MATI"), strict=True)
    await s.start()
    await run_until(s, timeout=60)
    s.sim = None
    s.auto_speak = False
    await s.override("ack_sensitive")
    assert s.state == State.SPEAKING and s.prompt.kind == "message"


async def test_caregiver_override_applies_and_is_badged(ctx):
    s = make_session(ctx, "cold", None)
    await s.start()
    await s.spoken(s.prompt.id)
    res = await s.override("yes")
    assert res["ok"]
    assert s.trail[-1]["overridden"] is True and s.trail[-1]["source"] == "caregiver"


async def test_unclear_three_times_hands_to_caregiver(ctx):
    s = make_session(ctx, "cold", None)
    await s.start()
    for _ in range(3):
        await s.spoken(s.prompt.id) if s.state != State.CAREGIVER_NEEDED else None
        await s.answer(s.prompt.id, Answer.UNCLEAR)
    assert s.state == State.CAREGIVER_NEEDED
    assert s.caregiver_reason in ("unclear", "tap_answer")


async def test_pain_refinement_relays_location(ctx):
    sim = SimulatedPatient(truth="pain", pain_location="chest", worse=True)
    s = make_session(ctx, "cold", sim)
    await s.start()
    await run_until(s, timeout=30)
    texts = [m.text_en for m in s.messages if m.status == "confirmed"]
    assert texts[0] == "I'm in pain."
    assert "The pain is in my chest." in texts
    assert "It is worse than before." in texts


async def test_indonesian_prompts_use_honorific(ctx):
    s = make_session(ctx, "suction", SimulatedPatient(truth="suction"), language="id")
    await s.start()
    await run_until(s)
    prompts = [e["prompt"]["text"] for e in log_events(s) if e["event"] == "prompt"]
    assert any("Ibu" in p for p in prompts)
    assert all("{hon}" not in p for p in prompts)


async def test_budget_guard_forces_mock(ctx):
    settings = ctx.settings.model_copy(update={"model_api_key": "x"})
    ctx.hub.settings = settings
    assert ctx.hub.resolve(Mode.LIVE).effective == Mode.LIVE
    ctx.store.add_spend("meta", "muse-spark-1.3", "test", 0.95 * settings.budget.max_usd)
    info = ctx.hub.resolve(Mode.LIVE)
    assert info.effective == Mode.MOCK and "budget" in info.reason
    assert ctx.hub.cost.status().level == "mock"


async def test_privacy_without_baseten_stays_local(ctx):
    info = ctx.hub.resolve(Mode.PRIVACY)
    assert info.effective == Mode.MOCK
    assert ctx.hub.tracker(Mode.PRIVACY).provider == "local"


async def test_delete_patient_wipes_everything(ctx):
    s = make_session(ctx, "daughter", SimulatedPatient(truth="see_person:aisyah"))
    await s.start()
    await run_until(s)
    await s.end()
    ctx.store.add_memory(
        s.pid, "Daughter Aisyah visits after work.", "family", "caregiver", "caregiver:entered"
    )
    counts = ctx.store.delete_patient(s.pid)
    assert counts["patients"] == 1 and counts["messages"] >= 1
    assert not s.log.path.exists()
    assert ctx.store.get_patient(s.pid) is None
    assert not ctx.store.memory(s.pid, None)


async def test_spelling_loop_is_capped(ctx):
    """A patient who rejects every suggestion and never finishes must not loop forever (cost guard)."""

    class Stubborn(SimulatedPatient):
        def answer(self, prompt, view):
            if prompt.get("stage") == "sentence":
                return Answer.NO
            return super().answer(prompt, view)

    s = make_session(ctx, "spelling", Stubborn(spell="KUCING", sentence_en="nothing like this"))
    await s.start()
    await run_until(s, timeout=60)
    assert s.state == State.CAREGIVER_NEEDED
    assert s.caregiver_reason in (
        "spelling_stuck",
        "no_questions_left",
        "question_cap",
        "inconsistent",
    )
    assert s.questions_this_message < 200


async def test_session_log_redacts_profile_names(ctx):
    s = make_session(ctx, "daughter", SimulatedPatient(truth="see_person:aisyah"))
    await s.start()
    await run_until(s)
    raw = s.log.path.read_text()
    assert "Aisyah" not in raw and "Pak Hasan" not in raw
    assert "[daughter]" in raw
