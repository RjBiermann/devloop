"""Issue comment ledger: the attempt-budget protocol.

Failure and reset messages on an issue are a protocol, not prose: the
attempt cap counts them back out of the comment history (no extra state).
Producers and the parser must agree, so both live here — call sites say
*what happened*, the ledger says *what it looks like on the issue*.

Marker strings are load-bearing for history: comments already on live
issues were written by older versions, so they never change — only append.
"""

from __future__ import annotations

from .forge import Forge, Issue

MARKERS = {
    "agent": "agent run FAILED",      # the agent run itself died/timed out
    "no-changes": "agent made NO changes",  # ran fine, delivered nothing
    "delivery": "delivery FAILED",    # gate/commit/PR stage failed
    "deferred": "build deferred",     # lost the delivery conflict gate
    "rebase": "rebase conflict",      # stale PR could not rebase; rebuilding
}

RESET = "build reset by"

# One truncation policy for every tail the ledger renders (was 800/1200
# split across call sites).
_TAIL = 1200


def failure(forge: Forge, issue: Issue | int, kind: str, note: str = "",
            tail: str = "") -> None:
    """Post one canonical failure comment. `note` is the plain-language
    middle; `tail` is fenced output, truncated here (one policy)."""
    body = MARKERS[kind]
    if note:
        body += f" — {note}"
    if tail:
        body += f"\n```\n{tail[-_TAIL:]}\n```"
    n = issue.number if isinstance(issue, Issue) else issue
    forge.comment(n, body)


def reset(forge: Forge, issue: Issue | int, reason: str = "") -> None:
    """Clear the attempt budget (the `/retry` path)."""
    body = RESET + (f" {reason}" if reason else "")
    n = issue.number if isinstance(issue, Issue) else issue
    forge.comment(n, body)


def count(forge: Forge, issue: Issue) -> int:
    """Past failed attempts, counted from the issue's own comment ledger —
    no extra state. Guards the scheduled sweeps against burning tokens on
    a poison task forever: after pipeline.max_attempts, a human re-labels
    (or issues `/retry`, which resets the budget from that point).
    Deferrals count too — a build that keeps losing the conflict gate is
    re-running its agent each sweep; the cap bounds that spend."""
    count = 0
    for c in forge.comments(issue.number):
        if c.body.startswith(RESET):
            count = 0
        elif any(c.body.startswith(m) for m in MARKERS.values()):
            count += 1
    return count
