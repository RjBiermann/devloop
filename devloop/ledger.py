"""Issue comment ledger: the attempt-budget protocol.

Failure and reset messages on an issue are a protocol, not prose: the
attempt cap counts them back out of the comment history (no extra state).
Producers and the parser must agree, so both live here — call sites say
*what happened*, the ledger says *what it looks like on the issue*.

Marker strings are load-bearing for history: comments already on live
issues were written by older versions, so they never change — only append.
"""

from datetime import date

from .forge import Forge, Issue
from .runtime import TAIL

MARKERS = {
    "agent": "agent run FAILED",      # the agent run itself died/timed out
    "no-changes": "agent made NO changes",  # ran fine, delivered nothing
    "delivery": "delivery FAILED",    # gate/commit/PR stage failed
    "deferred": "build deferred",     # lost the delivery conflict gate
    "rebase": "rebase conflict",      # stale PR could not rebase; rebuilding
}

RESET = "build reset by"

# Daily budget marker: ledger.failure stamps the date on every failure
# comment, so a per-issue daily cap can be counted from the same comment
# history (no extra state, same no-extra-state principle as count()).
DAY = "devloop budget:"  # prefix line: "devloop budget: YYYY-MM-DD"

# Completion (not a failure kind — deliberately outside MARKERS, so count()
# never mistakes a merge for an attempt): a human merged the devloop PR.
MERGED = "devloop PR merged"

# Tail truncation lives in runtime.TAIL (one policy, shared with every
# place agent output is rendered).


def failure(forge: Forge, issue: Issue | int, kind: str, note: str = "",
            tail: str = "") -> None:
    """Post one canonical failure comment. `note` is the plain-language
    middle; `tail` is fenced output, truncated here (one policy)."""
    body = f"{DAY} {date.today().isoformat()}\n\n" + MARKERS[kind]
    if note:
        body += f" — {note}"
    if tail:
        body += f"\n```\n{tail[-TAIL:]}\n```"
    n = issue.number if isinstance(issue, Issue) else issue
    forge.comment(n, body)


def reset(forge: Forge, issue: Issue | int, reason: str = "") -> None:
    """Clear the attempt budget (the `/retry` path)."""
    body = RESET + (f" {reason}" if reason else "")
    n = issue.number if isinstance(issue, Issue) else issue
    forge.comment(n, body)


def merged(forge: Forge, issue: Issue | int, pr_number: int) -> None:
    """Post one completion entry: the human merged the devloop PR — the
    issue's build lifecycle is done. On the record like every ledger entry."""
    n = issue.number if isinstance(issue, Issue) else issue
    forge.comment(n, f"{MERGED} #{pr_number} — closing the issue")


def _scan_attempts(comments) -> tuple[int, int]:
    """One pass over the comment ledger → (total attempts, attempts today).
    Both budgets (max_attempts, max_per_day) read the same history."""
    total = today_n = 0
    today = f"{DAY} {date.today().isoformat()}\n"
    for c in comments:
        if c.body.startswith(RESET):
            total = today_n = 0
        elif any(m in c.body for m in MARKERS.values()):
            total += 1
            if c.body.startswith(today):
                today_n += 1
    return total, today_n


def budget(forge: Forge, issue: Issue) -> tuple[int, int]:
    """One pass over the ledger → (past attempts, attempts today). Both
    caps (max_attempts, max_per_day) read the same scan — the queue never
    fetches an issue's comment history twice."""
    return _scan_attempts(forge.comments(issue.number))


def count(forge: Forge, issue: Issue) -> int:
    """Past failed attempts, counted from the issue's own comment ledger —
    no extra state. Guards the scheduled sweeps against burning tokens on
    a poison task forever: after pipeline.max_attempts, a human re-labels
    (or issues `/retry`, which resets the budget from that point).
    Deferrals count too — a build that keeps losing the conflict gate is
    re-running its agent each sweep; the cap bounds that spend."""
    return _scan_attempts(forge.comments(issue.number))[0]
