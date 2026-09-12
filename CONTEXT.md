# Context

Domain vocabulary for devloop. Terms here are the words this project uses — don't drift to synonyms.

## Glossary

### Version

Semver-ish number identifying a release: `Tag = release`, every merge to master
bumps **patch** by default; the human declares a **minor** when they merge;
majors stay manual. Version counts merges, not significance — significance is
the human's call, encoded in the merge, never inferred.
_Avoid_: bump-as-judgment, release-note generation.

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

### Closeout

Closing the loop on a build: a human merged the devloop PR, so its issue's
lifecycle is complete. The **merge handler** (`core.handle_merge`, fired only
from a real forge merge event — never agent output) posts the
`devloop PR merged #N` ledger entry and closes the issue via
`forge.complete_issue`. Not a guardrail breach — same carve-out as `/retry`'s
close_pr: the human's merge IS the judgment that the work is done; devloop is
executing that act, not judging its own work. The completion marker is a
ledger record, never an attempt (see Ledger).

### Review

Finding what's wrong before a human merges. The **review module**
(`devloop/review.py`) owns this interface: one function, `review_pr()`, behind
which live the review prompt (base template + repo guidance from
`skills/pre-review/SKILL.md` + the spec issue), per-round diff injection, the
PR-thread read, prior-findings carry between rounds, and the LGTM early-exit.
Review runs after a PR exists and is reachable on its own (`devloop review`,
`/review`). Findings only: a human reads them; the reviewer never changes
code. Review returns its final findings — the build flow hands them to Repair.

### Repair

Acting on review findings before a human reads them. The **repair module**
(`devloop/repair.py`) owns this interface: one function, `repair_pr()`, behind
which live the fixer prompt (findings + diff + spec issue + PR thread, with
repo guidance from `skills/repair/SKILL.md`), the verify gate before any push,
the commit-and-push (the fixer commits, the pipeline pushes), and the
one-round verification re-review that decides fixed vs still open. Repair is
not Review — review finds, repair acts; review stays findings-only. Repair is
not Delivery — it never opens, closes, or merges a PR; it only pushes commits
to the PR branch that already exists. Not the same as the `ai-fix` label:
`ai-fix` is an issue-level trigger a human applies to start a build; Repair is
PR-level upkeep that runs inside one.
