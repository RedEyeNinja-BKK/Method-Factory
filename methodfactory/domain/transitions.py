"""Action vocabulary and the transition table — the sole legality authority.

Prompt wording never defines legality (ADR-0003, ADR-0005).
"""

from __future__ import annotations

from enum import Enum

from .states import State


class Action(str, Enum):
    RECORD_INPUT = "record_input"
    SET_OBJECTIVE = "set_objective"
    PREPARE_SUMMARY = "prepare_summary"
    CONFIRM_SUMMARY = "confirm_summary"
    REVISE_INTAKE = "revise_intake"
    RECORD_DRAFT_ARTIFACT = "record_draft_artifact"
    CANCEL = "cancel"


ACTION_VOCABULARY = frozenset(a.value for a in Action)

# TRANSITION_TABLE[state] -> {action: target_state}
TRANSITION_TABLE: dict[State, dict[Action, State]] = {
    State.INTAKE: {
        Action.RECORD_INPUT: State.INTAKE,
        Action.SET_OBJECTIVE: State.INTAKE,
        Action.PREPARE_SUMMARY: State.SUMMARY_PENDING,
        Action.CANCEL: State.CANCELLED,
    },
    State.SUMMARY_PENDING: {
        Action.CONFIRM_SUMMARY: State.AUTHORING_AUTHORIZED,
        Action.REVISE_INTAKE: State.INTAKE,
        Action.CANCEL: State.CANCELLED,
    },
    State.AUTHORING_AUTHORIZED: {
        Action.RECORD_DRAFT_ARTIFACT: State.DRAFT_READY,
        Action.REVISE_INTAKE: State.INTAKE,
        Action.CANCEL: State.CANCELLED,
    },
    State.DRAFT_READY: {
        Action.CANCEL: State.CANCELLED,
    },
    # Terminal states have no legal actions.
    State.CANCELLED: {},
}

# Future phases add REVIEW/TRIAL/SHIP transitions. The states exist in the
# vocabulary (ADR-0003) but are deliberately unreachable until implemented.


def transition_target(state: State, action: Action) -> State | None:
    """Return the target state for a legal transition, else None."""
    return TRANSITION_TABLE.get(state, {}).get(action)


def legal_actions(state: State) -> frozenset[Action]:
    return frozenset(TRANSITION_TABLE.get(state, {}).keys())
