"""Package lifecycle states (ADR-0003)."""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    """Canonical package lifecycle states.

    v0.1 slice states are reachable. Later-phase states are declared in the
    vocabulary but not reachable until their transitions are implemented.
    """

    INTAKE = "INTAKE"
    SUMMARY_PENDING = "SUMMARY_PENDING"
    AUTHORING_AUTHORIZED = "AUTHORING_AUTHORIZED"
    DRAFT_READY = "DRAFT_READY"
    CANCELLED = "CANCELLED"

    # Declared for future phases (ADR-0003); not reachable in v0.1.
    REVIEW_PENDING = "REVIEW_PENDING"
    TRIAL_PENDING = "TRIAL_PENDING"
    SHIP_PENDING = "SHIP_PENDING"
    SHIPPED = "SHIPPED"
    REJECTED = "REJECTED"


TERMINAL_STATES = frozenset({State.CANCELLED, State.SHIPPED, State.REJECTED})

SLICE_STATES = frozenset(
    {
        State.INTAKE,
        State.SUMMARY_PENDING,
        State.AUTHORING_AUTHORIZED,
        State.DRAFT_READY,
        State.CANCELLED,
    }
)


def is_terminal(state: State) -> bool:
    return state in TERMINAL_STATES
