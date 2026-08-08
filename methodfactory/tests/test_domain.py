"""State machine unit tests — the authority boundary (ADR-0003)."""

from __future__ import annotations

import unittest

from methodfactory.domain.states import State, TERMINAL_STATES, is_terminal
from methodfactory.domain.transitions import (
    ACTION_VOCABULARY,
    TRANSITION_TABLE,
    Action,
    legal_actions,
    transition_target,
)


class TransitionTableTests(unittest.TestCase):
    def test_intake_transitions(self):
        table = TRANSITION_TABLE[State.INTAKE]
        self.assertEqual(table[Action.RECORD_INPUT], State.INTAKE)
        self.assertEqual(table[Action.SET_OBJECTIVE], State.INTAKE)
        self.assertEqual(table[Action.PREPARE_SUMMARY], State.SUMMARY_PENDING)
        self.assertEqual(table[Action.CANCEL], State.CANCELLED)

    def test_summary_pending_transitions(self):
        table = TRANSITION_TABLE[State.SUMMARY_PENDING]
        self.assertEqual(table[Action.CONFIRM_SUMMARY], State.AUTHORING_AUTHORIZED)
        self.assertEqual(table[Action.REVISE_INTAKE], State.INTAKE)
        self.assertEqual(table[Action.CANCEL], State.CANCELLED)

    def test_authoring_authorized_transitions(self):
        table = TRANSITION_TABLE[State.AUTHORING_AUTHORIZED]
        self.assertEqual(table[Action.RECORD_DRAFT_ARTIFACT], State.DRAFT_READY)
        self.assertEqual(table[Action.REVISE_INTAKE], State.INTAKE)
        self.assertEqual(table[Action.CANCEL], State.CANCELLED)

    def test_draft_ready_only_cancel(self):
        self.assertEqual(legal_actions(State.DRAFT_READY), frozenset({Action.CANCEL}))

    def test_cancelled_has_no_actions(self):
        self.assertEqual(legal_actions(State.CANCELLED), frozenset())

    # Illegal transitions (skipped gates / out-of-order) must be impossible.
    def test_illegal_prepare_summary_from_summary_pending(self):
        self.assertIsNone(transition_target(State.SUMMARY_PENDING, Action.PREPARE_SUMMARY))

    def test_illegal_confirm_from_intake(self):
        self.assertIsNone(transition_target(State.INTAKE, Action.CONFIRM_SUMMARY))

    def test_illegal_record_draft_from_intake(self):
        self.assertIsNone(transition_target(State.INTAKE, Action.RECORD_DRAFT_ARTIFACT))

    def test_illegal_record_input_from_summary_pending(self):
        self.assertIsNone(transition_target(State.SUMMARY_PENDING, Action.RECORD_INPUT))

    def test_illegal_set_objective_from_authoring(self):
        self.assertIsNone(transition_target(State.AUTHORING_AUTHORIZED, Action.SET_OBJECTIVE))

    def test_revise_legal_from_summary_pending_and_authoring(self):
        self.assertEqual(transition_target(State.SUMMARY_PENDING, Action.REVISE_INTAKE), State.INTAKE)
        self.assertEqual(transition_target(State.AUTHORING_AUTHORIZED, Action.REVISE_INTAKE), State.INTAKE)

    def test_illegal_from_terminal(self):
        self.assertEqual(legal_actions(State.CANCELLED), frozenset())
        self.assertIsNone(transition_target(State.CANCELLED, Action.CANCEL))

    def test_terminal_states(self):
        for state in (State.CANCELLED, State.SHIPPED, State.REJECTED):
            self.assertTrue(is_terminal(state))
        self.assertFalse(is_terminal(State.DRAFT_READY))
        self.assertFalse(is_terminal(State.INTAKE))

    def test_vocabulary_exact(self):
        self.assertEqual(
            ACTION_VOCABULARY,
            frozenset(
                {
                    "record_input",
                    "set_objective",
                    "prepare_summary",
                    "confirm_summary",
                    "revise_intake",
                    "record_draft_artifact",
                    "cancel",
                }
            ),
        )

    def test_table_references_known_states_only(self):
        for state, actions in TRANSITION_TABLE.items():
            self.assertIn(state, State._value2member_map_.values())
            for target in actions.values():
                self.assertIn(target, State._value2member_map_.values())

    def test_every_nonterminal_state_has_cancel(self):
        for state in State:
            if not is_terminal(state) and state in TRANSITION_TABLE:
                self.assertIn(Action.CANCEL, TRANSITION_TABLE[state])

    def test_action_values_unique(self):
        values = [a.value for a in Action]
        self.assertEqual(len(values), len(set(values)))


if __name__ == "__main__":
    unittest.main()
