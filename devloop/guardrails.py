"""Guardrails: the non-negotiable contract. Enforced, not documented."""

from __future__ import annotations


class GuardrailViolation(Exception):
    """Raised when an agent attempts an action reserved for humans."""


# Operations an agent may never perform. Humans only.
HUMAN_ONLY = frozenset({
    "merge",          # acceptance is the one immutable step
    "approve",        # approving = accepting
    "close_issue",    # the agent doesn't judge its own work done
    "apply_trigger",  # labels create work; agents never create work
})

