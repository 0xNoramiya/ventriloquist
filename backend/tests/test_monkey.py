"""Random sequences of patient answers and caregiver actions must never crash or break the state machine.

Runs in strict mode, where an invalid transition raises instead of being forced and logged.
"""

from __future__ import annotations

import os
import random

import pytest

from app.engine.types import Answer
from app.sessions.state_machine import State

from .conftest import make_session

PATIENT = ["spoken", "yes", "no", "unclear", "none"]
CAREGIVER = [
    "yes",
    "no",
    "unclear",
    "skip",
    "spell",
    "pause",
    "resume",
    "new_message",
    "refresh_context",
    "ack_emergency",
    "ack_sensitive",
    "ack_sensitive_silent",
    "emergency",
]


@pytest.mark.parametrize("seed", range(int(os.environ.get("MONKEY_SEEDS", "40"))))
async def test_random_interaction_sequences(ctx, seed):
    rng = random.Random(seed)
    scenario = rng.choice(["daughter", "cold", "spelling", "suction"])
    s = make_session(ctx, scenario, None)
    await s.start()
    for _ in range(80):
        if rng.random() < 0.8:
            act = rng.choice(PATIENT)
            if s.prompt is None:
                continue
            if act == "spoken":
                await s.spoken(s.prompt.id)
            else:
                if s.state in (
                    State.ASKING,
                    State.CONFIRMING,
                    State.SPELLING,
                    State.POST_CHECK,
                    State.SPEAKING,
                ):
                    await s.spoken(s.prompt.id)
                if s.prompt is not None:
                    weights = {"yes": 0.45, "no": 0.45, "unclear": 0.07, "none": 0.03}
                    choice = rng.choices(list(weights), list(weights.values()))[0]
                    if rng.random() < 0.01:
                        choice = "emergency"
                    await s.answer(s.prompt.id, Answer(choice))
        else:
            await s.override(rng.choice(CAREGIVER))
        assert s.state in State
        if s.state == State.SPEAKING:
            assert s.message is not None and s.message.status == "speaking"
    await s.end()
    assert s.state == State.DONE
    # every spoken message was preceded by a confirmation YES or a caregiver acknowledgement
    events = s.log.read()
    for i, e in enumerate(events):
        if e["event"] == "message" and e.get("status") == "speaking":
            prev = [x for x in events[:i] if x["event"] in ("observation", "override")]
            assert prev, "spoke without any answer"
            last = prev[-1]
            if last["event"] == "observation":
                assert last["observation"]["answer"] == "yes"
            else:
                assert last["action"] in ("yes", "ack_sensitive")
