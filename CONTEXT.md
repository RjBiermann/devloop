# Context

Domain vocabulary for devloop. Terms here are the words this project uses — don't drift to synonyms.

## Glossary

### Ledger

The issue comment history as state. Failure and reset comments on an issue are
a protocol, not prose: the attempt cap (`max_attempts`) counts them back out of
the comment history — no extra state anywhere. The **ledger module**
(`devloop/ledger.py`) owns this interface: producer functions (`failure`,
`reset`) and the parser (`count`). Marker strings are load-bearing for
comments already on live issues and never change — only append. Related
terms from AGENTS.md: trigger labels, `ready-for-human`, the `devloop: status=`
marker (the spec-loop counterpart of the ledger protocol; the spec loop lives
in `devloop/spec.py`).

### Delivery

Turning a finished agent run into a PR — or telling the issue why not. The
**delivery module** (`devloop/delivery.py`) owns this interface: one function,
`deliver()`, behind which live the verify gate, commit, half-delivery heal,
the delivery conflict gate, self-delivery bookkeeping, and the PR body. It
never raises: every failure path posts its own ledger comment and returns an
`Outcome` (`pr=None` means nothing shipped). A silent delivery failure is a
bug in one place, not a forgotten except clause in a caller. Review is NOT
delivery — see Review.

### Review

Finding what's wrong before a human merges. The **review module**
(`devloop/review.py`) owns this interface: one function, `review_pr()`, behind
which live the review prompt (base template + repo guidance from
`skills/pre-review/SKILL.md` + the spec issue), per-round diff injection, the
PR-thread read, prior-findings carry between rounds, and the LGTM early-exit.
Review runs after a PR exists and is reachable on its own (`devloop review`,
`/review`). Findings only: a human reads them; the reviewer never changes
code.
