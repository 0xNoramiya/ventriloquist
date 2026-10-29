"""Explicit session state machine.

Main path:  IDLE → CONTEXT_REFRESH → ASKING/CONFIRMING/SPELLING → LISTENING → PROCESSING → …
            → SPEAKING → POST_CHECK → LISTENING → PROCESSING → DONE
Side states: EMERGENCY (reachable from every state), PAUSED, SPELLING, CAREGIVER_NEEDED.
"""

from __future__ import annotations

from enum import StrEnum


class State(StrEnum):
    IDLE = "IDLE"
    CONTEXT_REFRESH = "CONTEXT_REFRESH"
    ASKING = "ASKING"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    CONFIRMING = "CONFIRMING"
    SPEAKING = "SPEAKING"
    POST_CHECK = "POST_CHECK"
    DONE = "DONE"
    EMERGENCY = "EMERGENCY"
    PAUSED = "PAUSED"
    SPELLING = "SPELLING"
    CAREGIVER_NEEDED = "CAREGIVER_NEEDED"


S = State
# States that put a question to the patient and then listen.
PROMPTING = {S.ASKING, S.CONFIRMING, S.SPELLING, S.POST_CHECK}
_NEXT_TURN = {S.ASKING, S.CONFIRMING, S.SPELLING, S.SPEAKING, S.PAUSED, S.CAREGIVER_NEEDED, S.DONE}

TRANSITIONS: dict[State, set[State]] = {
    S.IDLE: {S.CONTEXT_REFRESH},
    S.CONTEXT_REFRESH: {S.ASKING, S.CONFIRMING, S.SPELLING, S.CAREGIVER_NEEDED},
    S.ASKING: {S.LISTENING},
    S.CONFIRMING: {S.LISTENING},
    S.SPELLING: {S.LISTENING},
    S.POST_CHECK: {S.LISTENING},
    S.LISTENING: {S.PROCESSING, S.ASKING, S.CONFIRMING, S.SPELLING, S.POST_CHECK},  # re-ask paths
    S.PROCESSING: _NEXT_TURN | {S.POST_CHECK, S.CONTEXT_REFRESH},
    S.SPEAKING: {S.POST_CHECK, S.CAREGIVER_NEEDED},
    # caregiver can start spelling after a message; the family relay asks between messages
    S.DONE: {S.CONTEXT_REFRESH, S.IDLE, S.SPELLING, S.ASKING},
    S.PAUSED: {S.CONTEXT_REFRESH, S.ASKING, S.CONFIRMING, S.SPELLING, S.IDLE},
    S.CAREGIVER_NEEDED: {
        S.PROCESSING,  # caregiver entered the answer
        S.ASKING,
        S.CONFIRMING,
        S.SPELLING,
        S.SPEAKING,  # caregiver acknowledged a sensitive spelled message
        S.CONTEXT_REFRESH,
        S.PAUSED,
    },
    S.EMERGENCY: {S.PAUSED, S.CONTEXT_REFRESH},
}

# Reachable from anywhere (emergency must never be blocked; the caregiver can always end or pause).
ALWAYS = {S.EMERGENCY, S.DONE}
FROM_ANY_ACTIVE = {S.PAUSED, S.CAREGIVER_NEEDED}
TERMINAL = {S.DONE}


class InvalidTransition(RuntimeError):
    pass


def can_transition(src: State, dst: State) -> bool:
    if dst in ALWAYS:
        return True
    if dst in FROM_ANY_ACTIVE and src not in TERMINAL and src != S.EMERGENCY:
        return True
    return dst in TRANSITIONS.get(src, set())


class StateMachine:
    def __init__(self, initial: State = S.IDLE) -> None:
        self.state = initial
        self.history: list[tuple[State, State, str]] = []

    def to(self, dst: State, reason: str = "") -> State:
        if dst == self.state and dst in (S.CAREGIVER_NEEDED, S.PAUSED, S.EMERGENCY):
            return self.state
        if not can_transition(self.state, dst):
            raise InvalidTransition(f"{self.state} → {dst} ({reason})")
        self.history.append((self.state, dst, reason))
        self.state = dst
        return dst
